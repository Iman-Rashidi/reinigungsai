"""Basic duplicate checks for company names and website domains; no external calls."""
import re
from urllib.parse import urlparse


def normalize_company_name(name: str) -> str:
    value = (name or "").strip().lower()
    value = re.sub(r"\b(gmbh|ug|ag|kg|gbr|mbh|e\.v\.)\b", " ", value)
    return re.sub(r"[^a-z0-9]+", "", value)


def normalize_domain(website: str) -> str:
    raw = (website or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def find_possible_duplicates(candidate: dict, existing: list[dict]) -> list[dict]:
    """Return existing rows matching normalized name OR website domain."""
    candidate_name = normalize_company_name(candidate.get("name", ""))
    candidate_domain = normalize_domain(candidate.get("website", ""))
    matches = []
    for row in existing:
        same_name = candidate_name and candidate_name == normalize_company_name(row.get("name", ""))
        row_domain = normalize_domain(row.get("website", ""))
        same_domain = candidate_domain and candidate_domain == row_domain
        if same_name or same_domain:
            matches.append(row)
    return matches
