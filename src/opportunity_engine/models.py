"""Shared data model and conservative identity normalisation."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_KEYS = {
    "gclid", "fbclid", "msclkid", "ref", "source", "campaign",
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
}


def clean_text(value: object, limit: int = 12000) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    return " ".join(str(value).split())[:limit]


def normalise_text(value: object) -> str:
    text = clean_text(value).casefold()
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def canonical_url(value: object) -> str:
    """Remove tracking noise but retain query parameters that may identify a notice."""
    raw = clean_text(value, 3000)
    try:
        parsed = urlsplit(raw)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return ""
        host = parsed.hostname.lower().rstrip(".")
        if parsed.port:
            host = f"{host}:{parsed.port}"
        path = re.sub(r"/{2,}", "/", parsed.path or "/").rstrip("/") or "/"
        query = []
        for key, item in parse_qsl(parsed.query, keep_blank_values=True):
            low = key.casefold()
            if low in TRACKING_KEYS or low.startswith("utm_"):
                continue
            query.append((key, item))
        query.sort(key=lambda pair: (pair[0].casefold(), pair[1]))
        return urlunsplit((parsed.scheme.lower(), host, path, urlencode(query, doseq=True), ""))
    except (TypeError, ValueError):
        return ""


def identity_key(
    title: str,
    buyer: str = "",
    city: str = "",
    region: str = "",
    publication_date: str = "",
    fallback: str = "",
) -> str:
    """Conservative cross-source key; avoid merging title-only coincidences."""
    title_key = normalise_text(title)
    buyer_key = normalise_text(buyer)
    place_key = normalise_text(city or region)
    if not title_key:
        basis = fallback or "empty-record"
    elif buyer_key and place_key:
        basis = "|".join((title_key, buyer_key, place_key))
    elif buyer_key:
        basis = "|".join((title_key, buyer_key, clean_text(publication_date)[:7]))
    elif place_key:
        basis = "|".join((title_key, place_key, clean_text(publication_date)[:7]))
    else:
        basis = "|".join((title_key, clean_text(publication_date)[:10], fallback))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


@dataclass
class Opportunity:
    source_id: str
    external_id: str
    title: str
    url: str = ""
    buyer: str = ""
    description: str = ""
    city: str = ""
    region: str = ""
    postal_code: str = ""
    category: str = "Unbekannt"
    opportunity_type: str = "signal"
    publication_date: str = ""
    deadline: str = ""
    estimated_value: str = ""
    currency: str = "EUR"
    cpv: str = ""
    source_priority: int = 50
    provider_score: float = 0.0
    score: int = 0
    score_reason: str = ""
    evidence: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.source_id = clean_text(self.source_id, 80) or "unknown"
        self.external_id = clean_text(self.external_id, 500) or canonical_url(self.url) or hashlib.sha256(
            clean_text(self.title).encode("utf-8")
        ).hexdigest()
        self.title = clean_text(self.title, 500) or "Ohne Titel"
        self.url = canonical_url(self.url) or clean_text(self.url, 3000)
        self.buyer = clean_text(self.buyer, 500)
        self.description = clean_text(self.description, 12000)
        self.city = clean_text(self.city, 160)
        self.region = clean_text(self.region, 160)
        self.postal_code = clean_text(self.postal_code, 20)
        self.publication_date = clean_text(self.publication_date, 80)
        self.deadline = clean_text(self.deadline, 80)
        self.estimated_value = clean_text(self.estimated_value, 80)
        self.cpv = clean_text(self.cpv, 300)
        self.evidence = [clean_text(item, 500) for item in self.evidence if clean_text(item)]
        if not isinstance(self.raw, dict):
            self.raw = {"raw_value": clean_text(self.raw)}

    @property
    def canonical_key(self) -> str:
        return identity_key(
            self.title, self.buyer, self.city, self.region, self.publication_date,
            fallback=f"{self.source_id}:{self.external_id}",
        )

    def to_dict(self) -> dict:
        return asdict(self)
