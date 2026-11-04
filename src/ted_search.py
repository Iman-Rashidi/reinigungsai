"""Read-only search client for active German public procurement notices on TED.

Search is strictly restricted to Germany and North Rhine-Westphalia
(NUTS 1 code DEA). There is no Germany-wide or other-country mode.
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
    "buyer-contact-point",
    "buyer-email",
    "buyer-person",
    "buyer-city",
    "buyer-post-code",
    "buyer-internet-address",
    "organisation-street-buyer",
    "organisation-tel-buyer",
    "buyer-touchpoint-post-code",
    "buyer-touchpoint-internet-address",
    "touchpoint-street-buyer",
    "touchpoint-tel-buyer",
    "description-proc",
    "selection-criterion-name-lot",
    "selection-criterion-description-lot",
    "exclusion-grounds-description",
    "award-criterion-name-lot",
    "award-criterion-description-lot",
    "award-criterion-number-weight-lot",
    "estimated-value-proc",
    "estimated-value-cur-proc",
    "document-url-lot",
    "submission-url-lot",
    "contract-duration-period-lot",
    "main-classification-proc",
    "procedure-type",
]


class TEDSearchError(RuntimeError):
    """Raised when the public TED search request fails."""


def build_expert_query(
    keyword: str,
    region: str = "NRW",
    country_code: str = "DEU",
) -> str:
    """Build an active-notice query restricted to NRW within Germany."""
    clean = " ".join((keyword or "").split())
    if not clean or len(clean) > 100:
        raise ValueError("Bitte ein Suchwort mit 1 bis 100 Zeichen eingeben.")
    if not re.fullmatch(r"[\wÄÖÜäöüß -]+", clean, flags=re.UNICODE):
        raise ValueError("Das Suchwort enthält nicht unterstützte Zeichen.")
    if country_code != "DEU":
        raise ValueError("Für diesen MVP ist nur Deutschland (DEU) freigeschaltet.")

    if region != "NRW":
        raise ValueError("Für diesen MVP ist ausschließlich Nordrhein-Westfalen (NRW) freigeschaltet.")

    phrase = clean.replace('"', "")
    return (
        f'FT~"{phrase}" AND buyer-country=DEU AND place-of-performance=DEA* '
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
        # TED multilingual maps may contain strings OR arrays of strings
        # (notably buyer-name). Select German first, English second.
        normalised = {str(key).lower(): candidate for key, candidate in value.items()}
        for language in ("deu", "ger", "de", "eng", "en"):
            candidate = normalised.get(language)
            text = _localized_text(candidate) if candidate is not None else ""
            if text:
                return text
        # Do not silently display an arbitrary language as if it were German.
        language_keys = {"bul", "ces", "dan", "deu", "ell", "eng", "est", "fin",
                         "fra", "gle", "hrv", "hun", "ita", "lav", "lit", "mlt",
                         "nld", "pol", "por", "ron", "slk", "slv", "spa", "swe"}
        if any(key in language_keys for key in normalised):
            return ""
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

    def first_text(*keys):
        for key in keys:
            text = _localized_text(item.get(key))
            if text:
                return text
        return ""

    details = {
        "buyer": first_text("buyer-name", "buyerName"),
        "contact_point": first_text("buyer-contact-point", "buyer-touchpoint-contact-point"),
        "contact_person": first_text("buyer-person", "buyer-touchpoint-name"),
        "email": first_text("buyer-email", "organisation-email-buyer", "buyer-touchpoint-email"),
        "phone": first_text("touchpoint-tel-buyer", "organisation-tel-buyer"),
        "buyer_street": first_text("organisation-street-buyer"),
        "buyer_city": first_text("buyer-city"),
        "buyer_postcode": first_text("buyer-post-code"),
        "buyer_website": first_text("buyer-internet-address"),
        "contact_street": first_text("touchpoint-street-buyer"),
        "contact_postcode": first_text("buyer-touchpoint-post-code"),
        "contact_city": first_text("buyer-touchpoint-city"),
        "contact_website": first_text("buyer-touchpoint-internet-address"),
        "description": first_text("description-proc"),
        "selection_criteria": first_text("selection-criterion-name-lot", "selection-criterion-description-lot"),
        "exclusion_criteria": first_text("exclusion-grounds-description", "exclusion-grounds"),
        "award_criteria": first_text("award-criterion-name-lot", "award-criterion-description-lot"),
        "award_weights": first_text("award-criterion-number-weight-lot"),
        "estimated_value": first_text("estimated-value-proc"),
        "estimated_value_currency": first_text("estimated-value-cur-proc"),
        "documents_url": first_text("document-url-lot"),
        "submission_url": first_text("submission-url-lot"),
        "contract_duration": first_text("contract-duration-period-lot"),
        "cpv": first_text("main-classification-proc"),
        "procedure_type": first_text("procedure-type"),
    }
    completeness_fields = (
        "buyer", "description", "email", "phone", "selection_criteria",
        "exclusion_criteria", "award_criteria", "estimated_value",
        "documents_url", "submission_url", "deadline",
    )
    present = sum(bool(details.get(key) or (key == "deadline" and _localized_text(item.get("deadline")))) for key in completeness_fields)

    return {
        "title": title,
        "publication_number": str(publication_number),
        **details,
        "publication_date": _localized_text(item.get("publication-date") or item.get("publicationDate")),
        "deadline": _localized_text(item.get("deadline")),
        "location": " · ".join(location_parts),
        "url": str(url),
        "completeness": {
            "present": present,
            "total": len(completeness_fields),
            "missing": [key for key in completeness_fields if not (details.get(key) or (key == "deadline" and _localized_text(item.get("deadline"))))],
        },
        "source": "TED – Tenders Electronic Daily",
        "evidence_note": (
            "Öffentliche Vergabebekanntmachung. Angaben werden nur angezeigt, "
            "wenn sie in den TED-Daten enthalten sind. Eignung und vollständige "
            "Teilnahmebedingungen sind anhand der Originalunterlagen zu prüfen."
        ),
    }


def search_active_notices(
    keyword: str,
    limit: int = 30,
    timeout: int = 25,
    region: str = "NRW",
) -> dict:
    """Search active TED notices for performance only in NRW, Germany."""
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
