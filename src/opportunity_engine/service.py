"""Fault-isolated multi-source orchestration and persistent ingestion."""
from __future__ import annotations

import os
from pathlib import Path

from .adapters import search_bkms, search_tavily_opportunities, search_ted_paginated
from .classifier import enrich_opportunity, is_nrw_location
from .models import Opportunity, clean_text
from .store import OpportunityStore


SOURCE_DEFINITIONS = [
    {
        "source_id": "bkms", "name": "Bekanntmachungsservice (Open Data)",
        "kind": "official_bulk_api", "access_mode": "public", "enabled": True,
        "priority": 10, "notes": "Offizielle deutsche Bekanntmachungen; CC0 OCDS-Export, tägliche Abrufe."
    },
    {
        "source_id": "ted", "name": "TED – Tenders Electronic Daily",
        "kind": "official_search_api", "access_mode": "public", "enabled": True,
        "priority": 20, "notes": "Öffentliche TED Search API mit iterativer Seitennavigation."
    },
    {
        "source_id": "tavily", "name": "Tavily Public Web Search",
        "kind": "search_api", "access_mode": "api_key", "enabled": True,
        "priority": 40, "notes": "Ergänzende öffentliche Bedarfssignale; keine bestätigten Aufträge."
    },
    {
        "source_id": "auftragsbank", "name": "Auftragsbank",
        "kind": "manual_portal", "access_mode": "manual_only", "enabled": False,
        "priority": 80, "notes": "Kein automatisches Crawling ohne dokumentierte und autorisierte Schnittstelle."
    },
    {
        "source_id": "myhammer", "name": "MyHammer",
        "kind": "manual_portal", "access_mode": "manual_only", "enabled": False,
        "priority": 90, "notes": "Nur manuell; keine automatisierte Sammlung ohne ausdrückliche Freigabe."
    },
    {
        "source_id": "linkedin", "name": "LinkedIn",
        "kind": "restricted_platform", "access_mode": "manual_only", "enabled": False,
        "priority": 90, "notes": "Keine Profil-, Gruppen- oder Post-Scrapes."
    },
    {
        "source_id": "facebook", "name": "Facebook",
        "kind": "restricted_platform", "access_mode": "manual_only", "enabled": False,
        "priority": 90, "notes": "Keine privaten Gruppen- oder Profilinhalte."
    },
]


TED_QUERIES = {
    "Reinigung": ("Gebäudereinigung", "Reinigungsdienstleistungen", "Unterhaltsreinigung"),
    "Sicherheit": ("Sicherheitsdienst", "Wachdienst", "Objektschutz"),
    "Facility Management": ("Facility Management", "Hausmeisterservice"),
    "Bau / Handwerk": ("Bauleistungen", "Sanierung"),
    "Alle": ("Gebäudereinigung", "Sicherheitsdienst", "Facility Management", "Hausmeisterservice"),
}


def _matches_request(item: Opportunity, city: str, category: str) -> bool:
    if category not in {"", "Alle"} and item.category != category:
        return False
    location_text = " ".join((item.city, item.region, item.postal_code))
    nrw = is_nrw_location(location_text)
    if nrw is False:
        return False
    if city and city.casefold() not in {"nrw", "nordrhein-westfalen", "alle"}:
        haystack = " ".join((location_text, item.buyer, item.description[:1000])).casefold()
        if city.casefold() not in haystack:
            return False
    return True


def run_discovery(
    city: str = "NRW",
    category: str = "Alle",
    days_back: int = 7,
    include_tavily: bool = True,
    store: OpportunityStore | None = None,
) -> dict:
    """Run every configured public source; one provider failure never stops the rest."""
    city = clean_text(city, 100) or "NRW"
    if category not in {"Alle", "Reinigung", "Sicherheit", "Facility Management", "Bau / Handwerk"}:
        raise ValueError("Ungültige Kategorie.")
    days_back = max(1, min(int(days_back), 31))
    db = store or OpportunityStore()
    db.seed_sources(SOURCE_DEFINITIONS)

    report = {
        "city": city, "category": category, "days_back": days_back,
        "sources": [], "records_seen": 0, "records_new": 0, "records_changed": 0,
        "errors": 0,
    }

    def execute(source_id: str, runner):
        run_id = db.start_run(source_id)
        seen = inserted = changed = 0
        errors = []
        try:
            records = runner()
            for record in records:
                if not _matches_request(record, city, category):
                    continue
                seen += 1
                enriched = enrich_opportunity(record)
                result = db.upsert_opportunity(enriched)
                inserted += int(result["inserted"])
                changed += int(result["changed"])
            status = "ok"
        except Exception as exc:  # isolate one source from the others
            errors.append(f"{type(exc).__name__}: {exc}")
            status = "error"
        db.finish_run(run_id, source_id, status, seen, inserted, changed, "; ".join(errors))
        summary = {
            "source_id": source_id, "status": status, "seen": seen,
            "new": inserted, "changed": changed, "error": "; ".join(errors),
        }
        report["sources"].append(summary)
        report["records_seen"] += seen
        report["records_new"] += inserted
        report["records_changed"] += changed
        report["errors"] += len(errors)

    def run_bkms():
        records = search_bkms(days_back=days_back, category=category)
        if city.casefold() not in {"nrw", "nordrhein-westfalen", "alle"}:
            # City matching happens in the shared gate; don't pre-filter the
            # whole export by buyer address because buyer and service location differ.
            return records
        return records

    execute("bkms", run_bkms)

    def run_ted():
        records = []
        for keyword in TED_QUERIES.get(category, TED_QUERIES["Alle"]):
            records.extend(search_ted_paginated(keyword, max_pages=4, per_page=250))
        return records

    execute("ted", run_ted)

    if include_tavily and os.environ.get("TAVILY_API_KEY", "").strip():
        execute("tavily", lambda: search_tavily_opportunities(city, category, limit=15))
    else:
        db.mark_source_status(
            "tavily", "needs_config" if include_tavily else "not_requested",
            "TAVILY_API_KEY fehlt." if include_tavily else "",
        )
        report["sources"].append({
            "source_id": "tavily",
            "status": "needs_config" if include_tavily else "not_requested",
            "seen": 0, "new": 0, "changed": 0,
            "error": "TAVILY_API_KEY fehlt." if include_tavily else "",
        })

    for source in SOURCE_DEFINITIONS:
        if source["access_mode"] == "manual_only":
            db.mark_source_status(source["source_id"], "manual_only", source["notes"])

    report["total_opportunities"] = db.stats()["total"]
    report["storage_path"] = db.path
    report["storage_warning"] = (
        "Render-Dateisystem ist ohne Persistent Disk nicht dauerhaft. "
        "OPPORTUNITY_DB_PATH muss auf einen gemounteten /var/data-Pfad zeigen."
        if (os.environ.get("RENDER_SERVICE_ID") or os.environ.get("RENDER"))
        and not Path(db.path).expanduser().resolve().as_posix().startswith("/var/data/")
        else ""
    )
    return report
