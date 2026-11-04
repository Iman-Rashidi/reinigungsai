"""Read-only search client for active EU public procurement notices on TED.

Uses the official, anonymous TED Search API. It never submits notices or
writes to Notion. Search results are evidence leads, not proof of an award
or an externally outsourced cleaning requirement.
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
    "buyer-country",
    "publication-date",
    "deadline",
]


class TEDSearchError(RuntimeError):
    """Raised when the public TED search request fails."""


def build_expert_query(keyword: str, country_code: str = "DEU") -> str:
    """Build a conservative full-text query for active German notices."""
    clean = " ".join((keyword or "").split())
    if not clean or len(clean) > 100:
        raise ValueError("Bitte ein Suchwort mit 1 bis 100 Zeichen eingeben.")
    if not re.fullmatch(r"[\wÄÖÜäöüß -]+", clean, flags=re.UNICODE):
        raise ValueError("Das Suchwort enthält nicht unterstützte Zeichen.")
    if country_code != "DEU":
        raise ValueError("Für diesen MVP ist nur Deutschland (DEU) freigeschaltet.")
    phrase = clean.replace('"', "")
    return f'FT~"{phrase}" AND buyer-country={country_code} SORT BY publication-date DESC'


def _normalise_notice(item: dict) -> dict:
    """Map known TED fields into a stable, display-safe shape."""
    title = item.get("notice-title") or item.get("title") or "Ohne Titel"
    publication_number = item.get("publication-number") or item.get("publicationNumber") or ""
    url = item.get("url") or item.get("notice-url") or ""
    if not url and isinstance(item.get("links"), list):
        for link in item["links"]:
            if isinstance(link, dict) and link.get("url"):
                url = link["url"]
                break
    return {
        "title": str(title),
        "publication_number": str(publication_number),
        "buyer": str(item.get("buyer-name") or item.get("buyerName") or ""),
        "buyer_country": str(item.get("buyer-country") or item.get("buyerCountry") or ""),
        "publication_date": str(item.get("publication-date") or item.get("publicationDate") or ""),
        "deadline": str(item.get("deadline") or ""),
        "url": str(url),
        "source": "TED – Tenders Electronic Daily",
        "evidence_note": (
            "Öffentliche Vergabebekanntmachung. Reinigungsbedarf, "
            "externe Vergabe und Eignung müssen anhand der Bekanntmachung "
            "und Vergabeunterlagen einzeln geprüft werden."
        ),
    }


def search_active_notices(keyword: str, limit: int = 30, timeout: int = 25) -> dict:
    """Search active notices in Germany using the anonymous official TED API."""
    query = build_expert_query(keyword)
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
        "total": total if total is not None else len(notices),
        "returned": len(notices),
        "notices": notices,
        "source_url": TED_SEARCH_URL,
        "scope": "ACTIVE",
    }
