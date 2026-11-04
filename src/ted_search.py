"""Read-only search client for active German public procurement notices on TED.

The default search is restricted to North Rhine-Westphalia (NUTS 1 code DEA).
The optional Germany-wide mode uses the place-of-performance country filter.
Titles and buyer names are rendered in German where TED provides that locale.
"""
from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TED_SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
DEFAULT_FIELDS = [
    "publication-number",
    "notice-title",
    "buyer-name",
    "publication-date",
    "deadline",
    "place-of-performance",
    "place-of-performance-city-proc",
    "place-of-performance-city-lot",
    "place-of-performance-city-part",
    "place-of-performance-subdiv-proc",
]


class TEDSearchError(RuntimeError):
    """Raised when the public TED search request fails."""


def build_expert_query(
    keyword: str,
    region: str = "NRW",
    country_code: str = "DEU",
) -> str:
    """Build an active-notice query restricted to NRW or all of Germany."""
    clean = " ".join((keyword or "").split())
    if not clean or len(clean) > 100:
        raise ValueError("Bitte ein Suchwort mit 1 bis 100 Zeichen eingeben.")
    if not re.fullmatch(r"[\wÄÖÜäöüß -]+", clean, flags=re.UNICODE):
        raise ValueError("Das Suchwort enthält nicht unterstützte Zeichen.")
    if country_code != "DEU":
        raise ValueError("Für diesen MVP ist nur Deutschland (DEU) freigeschaltet.")

    region_filters = {
        "NRW": "place-of-performance=DEA*",
        "DE": "place-of-performance=DEU",
    }
    if region not in region_filters:
        raise ValueError("Bitte NRW oder ganz Deutschland als Suchgebiet wählen.")

    phrase = clean.replace('"', "")
    return (
        f'FT~"{phrase}" AND {region_filters[region]} '
        "SORT BY publication-date DESC"
    )


def _localized_text(value) -> str:
    """Choose German text from TED multilingual fields, then English."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for language in ("deu", "ger", "DE", "de", "eng", "en"):
            candidate = value.get(language)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        for candidate in value.values():
            text = _localized_text(candidate)
            if text:
                return text
        return ""
    if isinstance(value, list):
        parts = [_localized_text(item) for item in value]
        return "; ".join(part for part in parts if part)
    return ""


def _normalise_notice(item: dict) -> dict:
    """Map known TED fields into a stable, German-language display shape."""
    title = _localized_text(item.get("notice-title") or item.get("title")) or "Ohne Titel"
    publication_number = item.get("publication-number") or item.get("publicationNumber") or ""
    url = item.get("url") or item.get("notice-url") or ""
    if not url and isinstance(item.get("links"), list):
        for link in item["links"]:
            if isinstance(link, dict) and link.get("url"):
                url = link["url"]
                break

    location_parts = []
    for key in (
        "place-of-performance-city-proc",
        "place-of-performance-city-lot",
        "place-of-performance-city-part",
        "place-of-performance-subdiv-proc",
        "place-of-performance",
    ):
        value = _localized_text(item.get(key))
        if value and value not in location_parts:
            location_parts.append(value)

    return {
        "title": title,
        "publication_number": str(publication_number),
        "buyer": _localized_text(item.get("buyer-name") or item.get("buyerName")),
        "publication_date": _localized_text(item.get("publication-date") or item.get("publicationDate")),
        "deadline": _localized_text(item.get("deadline")),
        "location": " · ".join(location_parts),
        "url": str(url),
        "source": "TED – Tenders Electronic Daily",
        "evidence_note": (
            "Öffentliche Vergabebekanntmachung. Reinigungsbedarf, "
            "externe Vergabe und Eignung müssen anhand der Bekanntmachung "
            "und Vergabeunterlagen einzeln geprüft werden."
        ),
    }


def search_active_notices(
    keyword: str,
    limit: int = 30,
    timeout: int = 25,
    region: str = "NRW",
) -> dict:
    """Search active TED notices for performance in NRW or Germany."""
    query = build_expert_query(keyword, region=region)
    payload = {
        "query": query,
        "fields": DEFAULT_FIELDS,
        "limit": max(1, min(int(limit), 100)),
        "scope": "ACTIVE",
        "paginationMode": "PAGE_NUMBER",
        "page": 1,
    }
    request = Request(
        TED_SEARCH_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise TEDSearchError(f"TED Search API returned HTTP {exc.code}.") from None
    except (URLError, TimeoutError):
        raise TEDSearchError("Die TED-Suchschnittstelle ist momentan nicht erreichbar.") from None
    except json.JSONDecodeError:
        raise TEDSearchError("Die TED-Suchschnittstelle lieferte keine gültige JSON-Antwort.") from None

    raw_items = data.get("notices") or data.get("results") or data.get("items") or []
    if not isinstance(raw_items, list):
        raise TEDSearchError("Unerwartetes Antwortformat der TED-Suchschnittstelle.")
    notices = [_normalise_notice(item) for item in raw_items if isinstance(item, dict)]
    total = data.get("total") or data.get("totalNoticeCount") or data.get("total-notices")
    return {
        "query": query,
        "region": region,
        "total": total if total is not None else len(notices),
        "returned": len(notices),
        "notices": notices,
        "source_url": TED_SEARCH_URL,
        "scope": "ACTIVE",
    }
