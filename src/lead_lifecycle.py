"""Cross-portal lead deduplication and advertisement lifecycle helpers.

The module is deliberately provider-agnostic and performs no network access.
It keeps source records intact: duplicate detection annotates relationships
instead of silently deleting potentially useful evidence.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import urlsplit, urlunsplit


TITLE_FIELDS = ("title", "Titel", "name", "headline", "subject")
DESCRIPTION_FIELDS = ("description", "content", "snippet", "Suchauszug", "text")
LOCATION_FIELDS = ("city", "location", "Ort", "Stadt", "place")
CATEGORY_FIELDS = ("category", "service", "type", "Kategorie", "Branche")
URL_FIELDS = ("url", "source_url", "Quellenlink", "link")
ID_FIELDS = ("external_id", "publication_number", "id", "record_id")
DATE_FIELDS = ("deadline", "expires_at", "expiration_date", "Ablaufdatum")
STATUS_FIELDS = ("status", "Status", "state")


def _first(record: dict, fields: tuple[str, ...]) -> str:
    for field in fields:
        value = record.get(field)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _canonical_url(value: str) -> str:
    if not value:
        return ""
    parsed = urlsplit(value.strip())
    if not parsed.hostname:
        return ""
    host = parsed.hostname.lower().removeprefix("www.")
    path = re.sub(r"/+", "/", parsed.path).rstrip("/") or "/"
    return urlunsplit(("https", host, path, "", ""))


def _parse_date(value, today: date | None = None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    for candidate in (raw, raw[:10]):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            pass
    for fmt in ("%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    return None


def normalize_lead(record: dict) -> dict:
    """Return a comparable normalized view without mutating the input record."""
    if not isinstance(record, dict):
        raise TypeError("Each lead must be a dictionary.")
    title = _first(record, TITLE_FIELDS)
    location = _first(record, LOCATION_FIELDS)
    category = _first(record, CATEGORY_FIELDS)
    description = _first(record, DESCRIPTION_FIELDS)
    url = _canonical_url(_first(record, URL_FIELDS))
    external_id = _first(record, ID_FIELDS)
    return {
        "title": title,
        "title_key": _fold(title),
        "location": location,
        "location_key": _fold(location),
        "category": category,
        "category_key": _fold(category),
        "description": description,
        "description_key": _fold(description),
        "url": url,
        "external_id": external_id,
        "source": _first(record, ("source", "portal", "Domain", "Quelle")),
    }


def find_duplicate_pairs(
    records: list[dict],
    title_threshold: float = 0.88,
) -> list[dict]:
    """Find likely duplicate records, including matches across different portals.

    Exact canonical URLs or equal non-empty external IDs are strong matches.
    Fuzzy matches require a similar title plus the same non-empty location and
    compatible categories, reducing false positives for generic job titles.
    """
    if not 0.5 <= title_threshold <= 1:
        raise ValueError("title_threshold must be between 0.5 and 1.")
    normalized = [normalize_lead(record) for record in records]
    pairs = []
    for left_index, left in enumerate(normalized):
        for right_index in range(left_index + 1, len(normalized)):
            right = normalized[right_index]
            reasons = []
            similarity = SequenceMatcher(None, left["title_key"], right["title_key"]).ratio()
            if left["url"] and left["url"] == right["url"]:
                reasons.append("same_canonical_url")
            if left["external_id"] and left["external_id"] == right["external_id"]:
                reasons.append("same_external_id")
            same_location = bool(left["location_key"] and left["location_key"] == right["location_key"])
            compatible_category = (
                not left["category_key"]
                or not right["category_key"]
                or left["category_key"] == right["category_key"]
            )
            if similarity >= title_threshold and same_location and compatible_category:
                reasons.append("similar_title_same_location")
            if reasons:
                pairs.append({
                    "left_index": left_index,
                    "right_index": right_index,
                    "similarity": round(similarity, 4),
                    "sources": [left["source"], right["source"]],
                    "cross_portal": bool(
                        left["source"] and right["source"] and left["source"] != right["source"]
                    ),
                    "reasons": reasons,
                })
    return pairs


def detect_ad_status(
    record: dict,
    today: date | None = None,
    stale_after_days: int = 30,
) -> dict:
    """Classify an ad as active, expired, stale, or unknown.

    A passed explicit deadline or an explicit closed/expired status is expired.
    Missing deadlines are never guessed: old last-seen dates are marked stale,
    not expired.
    """
    if stale_after_days < 0:
        raise ValueError("stale_after_days cannot be negative.")
    today = today or datetime.now(timezone.utc).date()
    raw_status = _fold(_first(record, STATUS_FIELDS))
    expired_words = {"expired", "abgelaufen", "geschlossen", "closed", "beendet", "archived"}
    active_words = {"active", "aktiv", "open", "offen", "published", "veroeffentlicht"}
    deadline = _parse_date(_first(record, DATE_FIELDS))
    if raw_status in expired_words or (deadline is not None and deadline < today):
        return {"status": "expired", "deadline": deadline.isoformat() if deadline else None,
                "reason": "explicit_status" if raw_status in expired_words else "deadline_passed"}
    if raw_status in active_words:
        return {"status": "active", "deadline": deadline.isoformat() if deadline else None,
                "reason": "explicit_active_status"}
    last_seen = _parse_date(record.get("last_seen") or record.get("last_seen_at"))
    if last_seen and (today - last_seen).days > stale_after_days:
        return {"status": "stale", "deadline": deadline.isoformat() if deadline else None,
                "reason": "not_seen_recently"}
    if deadline is not None:
        return {"status": "active", "deadline": deadline.isoformat(), "reason": "deadline_not_passed"}
    return {"status": "unknown", "deadline": None, "reason": "insufficient_lifecycle_evidence"}


def compare_ad_snapshots(
    previous: dict,
    current: dict,
    fields: tuple[str, ...] = (
        "title", "description", "location", "category", "deadline", "status", "url"
    ),
) -> dict:
    """Report field-level changes between two snapshots of the same ad."""
    if not isinstance(previous, dict) or not isinstance(current, dict):
        raise TypeError("Snapshots must be dictionaries.")
    changes = {}
    for field in fields:
        old_value = previous.get(field)
        new_value = current.get(field)
        if old_value != new_value:
            changes[field] = {"before": old_value, "after": new_value}
    return {
        "changed": bool(changes),
        "changed_fields": changes,
        "change_count": len(changes),
    }
