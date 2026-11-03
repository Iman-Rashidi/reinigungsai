"""Conservative, read-only analysis of existing Notion leads.

This module converts explicit CRM evidence into the Version 0.8 rubric.
It does not browse the web, call an LLM, or modify Notion records.
"""
from __future__ import annotations

import re
from typing import Any

from src.notion_reader import query_leads

CRITERIA = (
    "verified_company_location",
    "service_fit",
    "documented_cleaning_need",
    "relevant_contact_role",
    "documented_procurement_path",
)

SERVICE_FIT_TERMS = (
    "gewerbepark", "büro", "buero", "bürostandort", "lager",
    "halle", "einzelhandel", "einkaufszentrum", "krankenhaus",
    "gesundheitswesen", "coworking", "serviced office", "gastronomie",
    "gewerbe", "industrie", "hotel", "praxis",
)

CLEANING_NEED_PATTERNS = (
    r"reinigungsbedarf\s+(?:ist\s+)?bestätigt",
    r"bedarf\s+an\s+reinigungsleistungen\s+(?:ist\s+)?bestätigt",
    r"sucht\s+(?:einen?\s+)?reinigungsdienstleister",
    r"reinigungsdienstleister\s+gesucht",
    r"reinigungsauftrag\s+(?:wurde\s+)?ausgeschrieben",
    r"aktuelle\s+ausschreibung\s+(?:für\s+)?(?:die\s+)?reinigung",
)

CONTACT_PATTERNS = (
    r"facility[- ]manager\s+(?:ist\s+)?(?:bekannt|identifiziert)",
    r"(?:technische[rn]?\s+)?ansprechpartner\s+(?:ist\s+)?(?:bekannt|identifiziert)",
    r"(?:facility|technik|einkauf)(?:s[- ]/und)?(?:\s+und\s+einkauf)?[- ]funktion\s+(?:ist\s+)?identifiziert",
    r"einkaufskontakt\s+(?:ist\s+)?(?:bekannt|identifiziert)",
)

PROCUREMENT_PATTERNS = (
    r"ausschreibung\s+(?:ist\s+)?veröffentlicht",
    r"vergabeportal\s+(?:ist\s+)?(?:benannt|verlinkt|bekannt)",
    r"lieferantenportal\s+(?:ist\s+)?(?:benannt|verlinkt|bekannt)",
    r"beschaffungsprozess\s+(?:ist\s+)?dokumentiert",
    r"angebotseinreichung\s+(?:erfolgt|möglich)\s+über",
)


def _plain_text(value: Any) -> str:
    """Extract plain text from a Notion property value without guessing."""
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    for key in ("title", "rich_text"):
        items = value.get(key)
        if isinstance(items, list):
            return "".join(
                item.get("plain_text", "")
                for item in items
                if isinstance(item, dict)
            ).strip()
    if value.get("type") == "url" or "url" in value:
        return str(value.get("url") or "").strip()
    if isinstance(value.get("select"), dict):
        return str(value["select"].get("name") or "").strip()
    return ""


def extract_fields(page: dict[str, Any]) -> dict[str, str]:
    properties = page.get("properties", {})
    return {name: _plain_text(prop) for name, prop in properties.items()}


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def assess_record(fields: dict[str, str]) -> dict[str, Any]:
    name = fields.get("Unternehmen", "").strip()
    city = fields.get("Stadt", "").strip()
    address = fields.get("Adresse", "").strip()
    website = fields.get("Website", "").strip()
    industry = fields.get("Branche", "").casefold()
    evidence_text = " ".join(
        fields.get(key, "")
        for key in ("Quelle / Hinweis", "Bewertungsgrundlage", "KI-Einschätzung", "Prüfnotizen")
    ).casefold()

    evidence = {
        "verified_company_location": bool(name and city and (address or website)),
        "service_fit": any(term in industry for term in SERVICE_FIT_TERMS),
        "documented_cleaning_need": _matches_any(evidence_text, CLEANING_NEED_PATTERNS),
        "relevant_contact_role": _matches_any(evidence_text, CONTACT_PATTERNS),
        "documented_procurement_path": _matches_any(evidence_text, PROCUREMENT_PATTERNS),
    }
    score = sum(evidence.values())
    potential = "Hoch" if score >= 4 else "Mittel" if score >= 2 else "Niedrig"
    missing = [criterion for criterion, proven in evidence.items() if not proven]
    return {
        "company": name or "(ohne Unternehmensnamen)",
        "score": score,
        "potential": potential,
        "evidence": evidence,
        "missing_evidence": missing,
        "note": "Score misst dokumentierte Belege und Recherchepriorität, nicht Verkaufswahrscheinlichkeit.",
    }


def analyze_pages(pages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    assessments = []
    skipped = 0
    for page in pages:
        fields = extract_fields(page)
        if not fields.get("Unternehmen", "").strip():
            skipped += 1
            continue
        assessments.append(assess_record(fields))
    return assessments, skipped


def main() -> None:
    pages = query_leads()
    assessments, skipped = analyze_pages(pages)
    print(f"Read-only lead analysis: {len(assessments)} lead(s); {skipped} empty record(s) skipped.")
    print("No Notion records were changed.")
    for item in assessments:
        print(f"\n{item['company']}: {item['score']}/5 ({item['potential']})")
        for criterion, proven in item["evidence"].items():
            print(f"  {'[x]' if proven else '[ ]'} {criterion}")
        if item["missing_evidence"]:
            print("  Missing: " + ", ".join(item["missing_evidence"]))
        print("  " + item["note"])


if __name__ == "__main__":
    main()
