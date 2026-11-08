"""Small, fail-open adapter for persisting public opportunity signals to Supabase.

Only non-personal opportunity fields are stored. The server-only ingestion token
is sent in a dedicated header and is never logged or included in error messages.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


class SupabaseLeadStoreError(RuntimeError):
    """Raised when the configured staging lead store cannot accept a batch."""


_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s()./-]{6,}\d)(?!\w)")


def _canonical_url(value: object) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    host = parsed.hostname.lower().removeprefix("www.")
    port = parsed.port
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    path = re.sub(r"/+", "/", parsed.path).rstrip("/") or "/"
    return urlunsplit(("https", netloc, path, "", ""))


def _iso_date(value: object) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidate = raw[:10]
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return None


def _safe_text(value: object, limit: int = 4000) -> str | None:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return None
    text = _EMAIL_RE.sub("[email removed]", text)
    text = _PHONE_RE.sub("[phone removed]", text)
    return text[:limit]


def normalise_lead_record(
    record: dict,
    *,
    source: str,
    city: str = "",
    category: str = "",
) -> dict | None:
    """Map a web or TED result to the limited, non-contact lead schema."""
    if not isinstance(record, dict):
        return None

    is_ted = source.casefold() == "ted"
    title = str(
        record.get("title") or record.get("Titel") or record.get("headline") or ""
    ).strip()
    if not title:
        return None

    raw_url = str(
        record.get("url")
        or record.get("Quellenlink")
        or record.get("source_url")
        or ""
    ).strip()
    canonical_url = _canonical_url(raw_url)
    original_url = raw_url if canonical_url else ""
    external_id = str(
        record.get("publication_number")
        or record.get("external_id")
        or record.get("notice_id")
        or ""
    ).strip() or None

    if is_ted:
        source_id = "ted"
        source_name = "TED – Tenders Electronic Daily"
        status = "active"
        status_reason = "returned_by_TED_active_scope"
        metadata = {
            key: str(record.get(key) or "")[:500]
            for key in (
                "cpv",
                "procedure_type",
                "publication_date",
                "estimated_value",
                "estimated_value_currency",
            )
            if record.get(key)
        }
    else:
        host = (urlsplit(canonical_url).hostname if canonical_url else "") or ""
        source_id = host or source.casefold() or "public_web"
        source_name = host or source
        status = "unknown"
        status_reason = "public_search_signal_not_independently_verified"
        metadata = {
            "relevance": record.get("Relevanz", record.get("relevance")),
            "signal": _safe_text(record.get("Signal", record.get("signal")), 500),
            "published": _safe_text(
                record.get("Veröffentlicht", record.get("published_date")), 120
            ),
        }
        metadata = {key: value for key, value in metadata.items() if value is not None}

    return {
        "source": source_id[:160],
        "source_name": source_name[:240] if source_name else None,
        "external_id": external_id[:240] if external_id else None,
        "canonical_url": canonical_url,
        "original_url": original_url[:2048] if original_url else None,
        "title": title[:1000],
        "description": (
            None if is_ted else _safe_text(
                record.get("description")
                or record.get("Suchauszug")
                or record.get("snippet"),
                4000,
            )
        ),
        "location": _safe_text(
            record.get("location")
            or record.get("Stadt")
            or record.get("Ort")
            or city,
            500,
        ),
        "category": _safe_text(
            record.get("category")
            or record.get("Kategorie")
            or category,
            200,
        ),
        "deadline": _iso_date(record.get("deadline") or record.get("Frist")),
        "ad_status": status,
        "status_reason": status_reason,
        "source_metadata": metadata,
    }


def persist_search_batch(
    *,
    source: str,
    query: str,
    city: str,
    category: str,
    records: list[dict],
    timeout: int = 15,
) -> dict | None:
    """Persist up to 100 non-personal records; return None when storage is disabled.

    Failures are reported with a safe status-only message. Search itself should
    continue to work even when the persistence service is unavailable.
    """
    base_url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    publishable_key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
    ingest_token = os.environ.get("SUPABASE_INGEST_TOKEN", "").strip()

    if not (base_url and publishable_key and ingest_token):
        return None

    parsed_base = urlsplit(base_url)
    if parsed_base.scheme != "https" or not (
        parsed_base.hostname or ""
    ).endswith(".supabase.co"):
        raise SupabaseLeadStoreError("Supabase endpoint configuration is invalid.")

    if not isinstance(records, list):
        raise SupabaseLeadStoreError("Search records must be a list.")

    safe_records = [
        item
        for item in (
            normalise_lead_record(
                record,
                source=source,
                city=city,
                category=category,
            )
            for record in records[:100]
        )
        if item is not None
    ]

    if not safe_records:
        return {
            "processed": 0,
            "inserted": 0,
            "updated": 0,
            "new_snapshots": 0,
        }

    payload = {
        "p_source": source[:160],
        "p_query": query[:1000],
        "p_city": city[:160],
        "p_category": category[:160],
        "p_records": safe_records,
    }
    request = Request(
        f"{base_url}/rest/v1/rpc/ingest_search_batch",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "apikey": publishable_key,
            "Authorization": f"Bearer {publishable_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-reinigungsradar-token": ingest_token,
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
    except HTTPError as exc:
        raise SupabaseLeadStoreError(
            f"Supabase ingestion rejected the batch (HTTP {exc.code})."
        ) from None
    except (URLError, TimeoutError, OSError):
        raise SupabaseLeadStoreError(
            "Supabase ingestion is temporarily unreachable."
        ) from None

    try:
        result = json.loads(response_body)
    except json.JSONDecodeError:
        raise SupabaseLeadStoreError(
            "Supabase returned an invalid ingestion response."
        ) from None

    if not isinstance(result, dict):
        raise SupabaseLeadStoreError("Supabase returned an unexpected response.")
    return result
