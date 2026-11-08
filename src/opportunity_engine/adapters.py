"""Official procurement feeds and guarded public-web adapter.

BKMS publishes CC0 daily/monthly bulk exports. This client only consumes the
documented public export API; it does not crawl authenticated vendor portals.
"""
from __future__ import annotations

import json
import re
import zipfile
from datetime import datetime, timedelta
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from src.lead_discovery import LeadDiscoveryError, search_public_leads
from src.ted_search import (
    DEFAULT_FIELDS,
    TED_SEARCH_URL,
    TEDSearchError,
    _normalise_notice,
    build_expert_query,
)
from .classifier import classify_opportunity
from .models import Opportunity, canonical_url, clean_text


BKMS_EXPORT_URL = "https://oeffentlichevergabe.de/api/notice-exports"
BKMS_HOME_URL = "https://oeffentlichevergabe.de/"
USER_AGENT = "ReinigungsRadarNRW/2.0 (+https://reinigungsai.onrender.com)"
TED_KEYWORDS = {
    "Reinigung": ("Gebäudereinigung", "Reinigungsdienstleistungen", "Unterhaltsreinigung"),
    "Sicherheit": ("Sicherheitsdienst", "Wachdienst", "Objektschutz"),
    "Facility Management": ("Facility Management", "Hausmeisterservice"),
    "Bau / Handwerk": ("Bauleistungen", "Sanierung"),
    "Alle": ("Gebäudereinigung", "Sicherheitsdienst", "Facility Management", "Hausmeisterservice"),
}
TAVILY_CATEGORIES = {
    "Reinigung": ("Reinigung",),
    "Sicherheit": ("Sicherheit",),
    "Facility Management": ("Facility Management",),
    "Bau / Handwerk": ("Bau / Handwerk",),
    "Alle": ("Reinigung", "Sicherheit", "Facility Management", "Bau / Handwerk"),
}


def _safe_request(url: str, timeout: int = 45) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/zip, application/octet-stream, application/json;q=0.9, */*;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} bei {url.split('?')[0]}") from None
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Netzwerkfehler beim Abruf von {url.split('?')[0]}: {exc}") from None


def fetch_bkms_day(day: str, timeout: int = 45) -> bytes:
    """Download one official BKMS OCDS ZIP publication day (not today/future)."""
    parsed = datetime.strptime(day, "%Y-%m-%d").date()
    yesterday = datetime.now(ZoneInfo("Europe/Berlin")).date() - timedelta(days=1)
    if parsed < datetime(2022, 12, 1).date() or parsed > yesterday:
        raise ValueError("BKMS erlaubt nur Veröffentlichungstage ab 01.12.2022 bis einschließlich gestern.")
    url = f"{BKMS_EXPORT_URL}?{urlencode({'pubDay': day, 'format': 'ocds.zip'})}"
    payload = _safe_request(url, timeout=timeout)
    if not zipfile.is_zipfile(BytesIO(payload)):
        raise RuntimeError(f"BKMS lieferte für {day} keine gültige ZIP-Datei.")
    return payload


def _walk_places(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_places(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_places(child)


def _ocds_fields(release: dict) -> dict:
    tender = release.get("tender") or {}
    buyer = release.get("buyer") or {}
    parties = release.get("parties") or []
    if not buyer.get("name"):
        for party in parties:
            if "buyer" in (party.get("roles") or []):
                buyer = party
                break

    locations = []
    postal_code = ""
    for candidate in _walk_places(tender.get("lots") or []) :
        place = candidate.get("placeOfPerformance") or candidate
        if not isinstance(place, dict):
            continue
        address = place.get("address") or {}
        parts = [
            clean_text(place.get("name")),
            clean_text(address.get("locality")),
            clean_text(address.get("region")),
            clean_text(address.get("postalCode")),
            clean_text(address.get("countryName")),
        ]
        if any(parts):
            locations.extend(part for part in parts if part)
            postal_code = postal_code or clean_text(address.get("postalCode"))

    for candidate in _walk_places(tender.get("items") or []):
        address = candidate.get("deliveryAddress") or {}
        parts = [
            clean_text(address.get("locality")),
            clean_text(address.get("region")),
            clean_text(address.get("postalCode")),
        ]
        locations.extend(part for part in parts if part)
        postal_code = postal_code or clean_text(address.get("postalCode"))

    # Some OCDS publishers put the performance location directly on tender.
    direct = tender.get("placeOfPerformance") or {}
    if isinstance(direct, dict):
        address = direct.get("address") or {}
        locations.extend(
            clean_text(part) for part in (
                direct.get("name"), address.get("locality"),
                address.get("region"), address.get("postalCode"),
            ) if clean_text(part)
        )
        postal_code = postal_code or clean_text(address.get("postalCode"))

    items = tender.get("items") or []
    cpv_values = []
    for item in items:
        classification = item.get("classification") or {}
        code = clean_text(classification.get("id"))
        if code:
            cpv_values.append(code)
    for lot in tender.get("lots") or []:
        for item in lot.get("items") or []:
            code = clean_text((item.get("classification") or {}).get("id"))
            if code:
                cpv_values.append(code)

    documents = release.get("documents") or tender.get("documents") or []
    document_url = ""
    for document in documents:
        candidate = clean_text(document.get("url"))
        if candidate.startswith(("https://", "http://")):
            document_url = candidate
            break

    period = tender.get("tenderPeriod") or {}
    value = tender.get("value") or {}
    title = clean_text(tender.get("title") or release.get("title"))
    if not title and tender.get("lots"):
        title = clean_text((tender["lots"][0] or {}).get("title"))
    return {
        "title": title,
        "description": clean_text(tender.get("description") or release.get("description")),
        "buyer": clean_text(buyer.get("name")),
        "city": next((part for part in locations if part and not re.match(r"^(DEA|DE[A-Z0-9]{2,})$", part, re.I)), ""),
        "region": next((part for part in locations if re.search(r"Nordrhein|North Rhine|\bDEA[A-Z0-9]*\b", part, re.I)), ""),
        "postal_code": postal_code,
        "publication_date": clean_text(release.get("date") or release.get("publishedDate")),
        "deadline": clean_text(period.get("endDate") or tender.get("tenderPeriodEndDate")),
        "estimated_value": clean_text(value.get("amount")),
        "currency": clean_text(value.get("currency") or "EUR"),
        "cpv": ", ".join(dict.fromkeys(cpv_values)),
        "url": canonical_url(document_url),
    }


def parse_bkms_zip(payload: bytes, category: str = "Alle") -> list[Opportunity]:
    """Parse OCDS JSON files in an official BKMS export and extract tenders."""
    opportunities: list[Opportunity] = []
    try:
        archive = zipfile.ZipFile(BytesIO(payload))
    except (zipfile.BadZipFile, OSError):
        raise RuntimeError("Die BKMS-Datei ist kein lesbares ZIP-Archiv.") from None

    for member in archive.infolist():
        if member.is_dir() or not member.filename.lower().endswith(".json"):
            continue
        try:
            document = json.loads(archive.read(member).decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        releases = document.get("releases") if isinstance(document, dict) else None
        if not isinstance(releases, list):
            releases = [document] if isinstance(document, dict) else []
        for release in releases:
            if not isinstance(release, dict):
                continue
            tags = {clean_text(tag).casefold() for tag in (release.get("tag") or [])}
            if tags and not tags.intersection({"tender", "tenderupdate", "planning", "planningupdate"}):
                continue
            tender = release.get("tender") or {}
            fields = _ocds_fields(release)
            if not fields["title"]:
                continue
            declared = clean_text(tender.get("mainProcurementCategory"))
            found_category, kind = classify_opportunity(
                fields["title"], fields["description"], fields["cpv"], declared
            )
            if kind == "job" or found_category == "Unbekannt":
                continue
            if category not in {"Alle", "", found_category}:
                continue
            place_text = " ".join((fields["city"], fields["region"], fields["postal_code"]))
            # Explicitly out-of-NRW address is rejected. Unknown locations are
            # retained as unverified signals rather than silently discarded.
            from .classifier import is_nrw_location
            if is_nrw_location(place_text) is False:
                continue
            external_id = clean_text(release.get("ocid") or document.get("ocid") or release.get("id") or member.filename)
            if not external_id:
                external_id = member.filename
            raw_url = fields["url"]
            opportunities.append(Opportunity(
                source_id="bkms",
                external_id=external_id,
                title=fields["title"],
                url=raw_url,
                buyer=fields["buyer"],
                description=fields["description"],
                city=fields["city"],
                region=fields["region"] or ("NRW (region code DEA)" if "DEA" in place_text else ""),
                postal_code=fields["postal_code"],
                category=found_category,
                opportunity_type=kind,
                publication_date=fields["publication_date"],
                deadline=fields["deadline"],
                estimated_value=fields["estimated_value"],
                currency=fields["currency"],
                cpv=fields["cpv"],
                source_priority=10,
                raw={
                    "ocid": external_id,
                    "release_id": clean_text(release.get("id")),
                    "tags": sorted(tags),
                    "format": "OCDS 1.1",
                    "source_export": "BKMS OpenData API",
                },
            ))
    return opportunities


def search_bkms(days_back: int = 7, category: str = "Alle", max_records: int = 8000) -> list[Opportunity]:
    """Read up to 31 completed publication days from the official BKMS open-data feed."""
    if not 1 <= int(days_back) <= 31:
        raise ValueError("Der BKMS-Zeitraum muss zwischen 1 und 31 Tagen liegen.")
    yesterday = datetime.now(ZoneInfo("Europe/Berlin")).date() - timedelta(days=1)
    collected: dict[str, Opportunity] = {}
    for offset in range(int(days_back)):
        day = (yesterday - timedelta(days=offset)).isoformat()
        parsed = parse_bkms_zip(fetch_bkms_day(day), category=category)
        for item in parsed:
            collected[item.external_id] = item
            if len(collected) >= max_records:
                return list(collected.values())
    return list(collected.values())


def _ted_to_opportunity(notice: dict, keyword: str) -> Opportunity:
    publication_id = clean_text(notice.get("publication_number"))
    location = clean_text(notice.get("location"))
    city = ""
    for part in re.split(r"[;,·]", location):
        candidate = clean_text(part)
        if candidate and not re.fullmatch(r"DE[A-Z0-9]{1,4}", candidate, re.I):
            city = candidate
            if candidate.casefold() not in {"nordrhein-westfalen", "germany", "deutschland"}:
                break
    category, kind = classify_opportunity(
        notice.get("title", ""), notice.get("description", ""), notice.get("cpv", "")
    )
    if category == "Unbekannt":
        category = "Sicherheit" if "sicher" in keyword.casefold() or "wachdienst" in keyword.casefold() else "Reinigung"
    return Opportunity(
        source_id="ted",
        external_id=publication_id or canonical_url(notice.get("url")) or clean_text(notice.get("title")),
        title=notice.get("title", ""),
        url=notice.get("url", ""),
        buyer=notice.get("buyer", ""),
        description=notice.get("description", ""),
        city=city,
        region="Nordrhein-Westfalen (NUTS DEA)",
        category=category,
        opportunity_type="tender",
        publication_date=notice.get("publication_date", ""),
        deadline=notice.get("deadline", ""),
        estimated_value=notice.get("estimated_value", ""),
        currency=notice.get("estimated_value_currency", "EUR"),
        cpv=notice.get("cpv", ""),
        source_priority=20,
        raw={"publication_number": publication_id, "ted_keyword": keyword},
    )


def search_ted_paginated(keyword: str, max_pages: int = 4, per_page: int = 250) -> list[Opportunity]:
    """Search TED's public API using its scroll token instead of silently stopping at page 1."""
    query = build_expert_query(keyword)
    payload = {
        "query": query,
        "fields": DEFAULT_FIELDS,
        "limit": max(1, min(int(per_page), 250)),
        "scope": "ACTIVE",
        "paginationMode": "ITERATION",
    }
    results: list[Opportunity] = []
    seen: set[str] = set()
    next_token = ""
    for page_number in range(max(1, min(int(max_pages), 20))):
        body = dict(payload)
        if next_token:
            body["iterationNextToken"] = next_token
        request = Request(
            TED_SEARCH_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": USER_AGENT},
            method="POST",
        )
        try:
            with urlopen(request, timeout=35) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise TEDSearchError(f"TED Search API returned HTTP {exc.code}.") from None
        except (URLError, TimeoutError, OSError):
            raise TEDSearchError("Die TED-Suchschnittstelle ist momentan nicht erreichbar.") from None
        except json.JSONDecodeError:
            raise TEDSearchError("Die TED-Suchschnittstelle lieferte keine gültige JSON-Antwort.") from None
        notices = data.get("notices") or data.get("results") or data.get("items") or []
        if not isinstance(notices, list):
            raise TEDSearchError("Unerwartetes Antwortformat der TED-Suchschnittstelle.")
        for raw in notices:
            if not isinstance(raw, dict):
                continue
            normalised = _normalise_notice(raw)
            item = _ted_to_opportunity(normalised, keyword)
            if item.external_id not in seen:
                seen.add(item.external_id)
                results.append(item)
        token = (
            data.get("iterationNextToken")
            or data.get("iteration-next-token")
            or data.get("nextToken")
            or data.get("next_token")
            or ""
        )
        if not notices or not token or token == next_token:
            break
        next_token = str(token)
    return results


def search_tavily_opportunities(city: str, category: str, limit: int = 15) -> list[Opportunity]:
    from .classifier import classify_opportunity
    categories = TAVILY_CATEGORIES.get(category, ("Reinigung",))
    collected: dict[str, Opportunity] = {}
    for query_category in categories:
        response = search_public_leads(city=city, category=query_category, limit=limit)
        for row in response.get("rows", []):
            url = canonical_url(row.get("Quellenlink"))
            if not url:
                continue
            found_category, kind = classify_opportunity(
                row.get("Titel", ""), row.get("Suchauszug", ""), declared_category=query_category
            )
            item = Opportunity(
                source_id="tavily",
                external_id=url,
                title=row.get("Titel", ""),
                url=url,
                description=row.get("Suchauszug", ""),
                city=city,
                region="NRW (Suchanfrage)",
                category=found_category if found_category != "Unbekannt" else query_category,
                opportunity_type=kind,
                publication_date=row.get("Veröffentlicht", ""),
                source_priority=40,
                provider_score=float(row.get("Relevanz") or 0) / 100.0,
                raw={"domain": row.get("Domain"), "search_signal": row.get("Signal"), "query": response.get("query")},
            )
            collected[url] = item
    return list(collected.values())
