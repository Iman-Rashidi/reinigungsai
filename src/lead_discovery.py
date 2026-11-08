"""Public-web lead discovery with a guarded search-provider adapter.

This module searches indexed public pages through Tavily when the operator
configures an API key. It does not log in to, crawl, or scrape LinkedIn,
Facebook, MyHammer, Indeed, StepStone, or other restricted platforms.
Results are unverified opportunity signals, not consent to contact.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlsplit, urlunsplit
from urllib.request import Request, urlopen

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
USER_AGENT = "ReinigungsRadarNRW/1.0 (+https://reinigungsai.onrender.com)"

LEAD_CATEGORIES = {
    "Reinigung": {
        "terms": [
            "Gebäudereinigung", "Reinigungsdienst", "Reinigungsfirma",
            "Reinigungskraft gesucht", "Unterhaltsreinigung", "Büroreinigung",
        ],
        "intent": [
            "Reinigungsdienst gesucht", "Reinigungsfirma gesucht",
            "Ausschreibung Gebäudereinigung", "Vergabe Gebäudereinigung",
            "Unternehmen sucht Reinigungskraft",
        ],
    },
    "Sicherheit": {
        "terms": [
            "Sicherheitsdienst", "Wachdienst", "Objektschutz",
            "Empfangsdienst", "Bewachung",
        ],
        "intent": [
            "Sicherheitsdienst gesucht", "Ausschreibung Sicherheitsdienst",
            "Vergabe Objektschutz", "Wachdienst Auftrag",
        ],
    },
    "Facility Management": {
        "terms": [
            "Facility Management", "Hausmeisterservice", "Gebäudeservice",
            "technisches Gebäudemanagement",
        ],
        "intent": [
            "Facility Management Dienstleister gesucht",
            "Ausschreibung Gebäudeservice", "Hausmeisterservice Auftrag",
        ],
    },
    "Bau / Handwerk": {
        "terms": [
            "Bauunternehmen", "Handwerker", "Bauleistungen",
            "Sanierung", "Instandhaltung",
        ],
        "intent": [
            "Bauunternehmen gesucht", "Handwerker gesucht",
            "Ausschreibung Bauleistungen", "Auftrag Bauunternehmen",
        ],
    },
}

# These platforms are available as manual links only. Do not send them to an
# automated search/fetch pipeline without an explicit, authorized integration.
RESTRICTED_DOMAINS = (
    "linkedin.com",
    "facebook.com",
    "my-hammer.de",
    "indeed.com",
    "stepstone.de",
    "xing.com",
    "instagram.com",
    "threads.net",
    "tiktok.com",
    "kleinanzeigen.de",
)

SEARCH_EXCLUDE_DOMAINS = list(RESTRICTED_DOMAINS) + [
    "youtube.com",
    "pinterest.com",
]

PORTAL_LINKS = [
    {
        "label": "Bundesagentur für Arbeit",
        "url": "https://www.arbeitsagentur.de/jobsuche/",
        "mode": "Manuelle Suche",
        "note": "Öffentliche Stellenanzeigen; Arbeitgeber und Bedarfssignal prüfen.",
    },
    {
        "label": "Indeed Deutschland",
        "url": "https://de.indeed.com/",
        "mode": "Manuelle Suche",
        "note": "Keine automatisierte Datenerfassung in diesem Modul.",
    },
    {
        "label": "StepStone",
        "url": "https://www.stepstone.de/",
        "mode": "Manuelle Suche",
        "note": "Nutzung über die Website; kein Crawler.",
    },
    {
        "label": "LinkedIn Jobs",
        "url": "https://www.linkedin.com/jobs/",
        "mode": "Manuelle Suche",
        "note": "Keine Profil- oder Beitrags-Scrapes.",
    },
    {
        "label": "MyHammer",
        "url": "https://www.my-hammer.de/",
        "mode": "Manuelle Suche",
        "note": "AGB verbieten automatisiertes Sammeln und kommerzielle Datenbankbildung.",
    },
    {
        "label": "Facebook",
        "url": "https://www.facebook.com/",
        "mode": "Manuelle Suche",
        "note": "Gruppen und Beiträge nur innerhalb der Plattform und mit zulässigem Zugriff prüfen.",
    },
    {
        "label": "XING",
        "url": "https://www.xing.com/",
        "mode": "Manuelle Suche",
        "note": "Kein automatisiertes Auslesen von Profilen oder Beiträgen.",
    },
]

INTENT_PATTERNS = re.compile(
    r"gesucht|sucht .*dienstleister|bedarf|ausschreibung|vergabe|auftrag|"
    r"angebot einholen|anbieter gesucht|reinigungsfirma|dienstleister gesucht|"
    r"rahmenvertrag|unterhaltsreinigung",
    re.IGNORECASE,
)


class LeadDiscoveryError(RuntimeError):
    """Raised when the public-web search provider fails or is unavailable."""


def validate_city(city: str) -> str:
    """Validate a short NRW location query without assuming a specific city."""
    value = " ".join((city or "").split()).strip()
    if len(value) < 2 or len(value) > 80:
        raise ValueError("Bitte einen gültigen Stadt- oder Gemeindenamen eingeben.")
    if not re.fullmatch(r"[\wÄÖÜäöüß .,'()\-]+", value, flags=re.UNICODE):
        raise ValueError("Der Ortsname enthält nicht unterstützte Zeichen.")
    return value


def build_search_query(city: str, category: str, extra_terms: str = "") -> str:
    """Build a targeted public-web query for NRW opportunity signals."""
    city = validate_city(city)
    if category not in LEAD_CATEGORIES:
        raise ValueError("Die ausgewählte Kategorie ist ungültig.")
    terms = LEAD_CATEGORIES[category]
    intent = " OR ".join(f'"{term}"' for term in terms["intent"][:4])
    keywords = " OR ".join(f'"{term}"' for term in terms["terms"][:4])
    extra = " ".join((extra_terms or "").split())[:120]
    suffix = f" {extra}" if extra else ""
    return (
        f'({intent} OR {keywords}) "{city}" Nordrhein-Westfalen{suffix} '
        "öffentliche Anzeige Unternehmen Auftrag"
    )


def is_restricted_domain(hostname: str) -> bool:
    """Return True for platforms that this app must not automatically crawl."""
    host = (hostname or "").lower().strip(".")
    return any(host == domain or host.endswith("." + domain) for domain in RESTRICTED_DOMAINS)


def _canonical_url(url: str) -> str:
    parsed = urlsplit((url or "").strip())
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return ""
    host = parsed.hostname.lower()
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, "", ""))


def _score_result(title: str, snippet: str, city: str, category: str, provider_score: float) -> tuple[int, str]:
    text = f"{title} {snippet}".casefold()
    terms = LEAD_CATEGORIES[category]["terms"]
    term_hits = sum(1 for term in terms if term.casefold() in text)
    local_hit = city.casefold() in text or "nordrhein-westfalen" in text or "nrw" in text
    intent_hit = bool(INTENT_PATTERNS.search(text))
    score = int(max(0.0, min(1.0, provider_score)) * 45)
    score += min(term_hits, 3) * 12
    score += 18 if intent_hit else 0
    score += 10 if local_hit else 0
    score = min(100, score)
    if intent_hit and term_hits:
        note = "Mögliches konkretes Bedarfssignal – Originalseite prüfen"
    elif term_hits:
        note = "Thematisch passend – tatsächlichen Bedarf prüfen"
    else:
        note = "Schwaches Signal – manuelle Prüfung erforderlich"
    return score, note


def normalise_results(raw_results: list[dict], city: str, category: str) -> list[dict[str, str]]:
    """Normalize search-provider results, reject restricted platforms, dedupe URLs."""
    city = validate_city(city)
    if category not in LEAD_CATEGORIES:
        raise ValueError("Die ausgewählte Kategorie ist ungültig.")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        url = _canonical_url(str(item.get("url") or ""))
        if not url:
            continue
        host = urlsplit(url).hostname or ""
        if is_restricted_domain(host):
            continue
        key = url.casefold()
        if key in seen:
            continue
        seen.add(key)
        title = " ".join(str(item.get("title") or "").split())[:240]
        snippet = " ".join(str(item.get("content") or "").split())[:700]
        try:
            provider_score = float(item.get("score") or 0)
        except (TypeError, ValueError):
            provider_score = 0.0
        score, note = _score_result(title, snippet, city, category, provider_score)
        rows.append({
            "Titel": title or "Ohne Titel",
            "Domain": host,
            "Suchauszug": snippet,
            "Veröffentlicht": str(item.get("published_date") or "Vom Suchanbieter nicht geliefert"),
            "Relevanz": str(score),
            "Signal": note,
            "Status": "Öffentliches Suchergebnis – Originalquelle nicht unabhängig geprüft",
            "Quellenlink": url,
            "Prüfzeitpunkt": checked_at,
        })
    rows.sort(key=lambda row: int(row["Relevanz"]), reverse=True)
    return rows


def search_public_leads(
    city: str,
    category: str,
    limit: int = 15,
    extra_terms: str = "",
    api_key: str | None = None,
    timeout: int = 25,
) -> dict:
    """Search public indexed pages via Tavily; never scrape restricted platforms."""
    city = validate_city(city)
    query = build_search_query(city, category, extra_terms)
    key = (api_key or os.environ.get("TAVILY_API_KEY", "")).strip()
    if not key:
        raise LeadDiscoveryError(
            "TAVILY_API_KEY fehlt. Ohne Such-API-Schlüssel bleiben nur die manuellen Portal-Links verfügbar."
        )
    payload = {
        "api_key": key,
        "query": query,
        "topic": "general",
        "search_depth": "basic",
        "max_results": max(5, min(int(limit), 20)),
        "include_answer": False,
        "include_raw_content": False,
        "exclude_domains": SEARCH_EXCLUDE_DOMAINS,
    }
    request = Request(
        TAVILY_SEARCH_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise LeadDiscoveryError("Tavily hat den API-Schlüssel abgelehnt. Bitte den Schlüssel in Render prüfen.") from None
        if exc.code == 429:
            raise LeadDiscoveryError("Das Suchkontingent ist momentan ausgeschöpft. Bitte später erneut versuchen.") from None
        raise LeadDiscoveryError(f"Die Websuche antwortet mit HTTP {exc.code}.") from None
    except (URLError, TimeoutError, OSError):
        raise LeadDiscoveryError("Der Suchdienst ist momentan nicht erreichbar.") from None
    except json.JSONDecodeError:
        raise LeadDiscoveryError("Der Suchdienst lieferte keine gültige JSON-Antwort.") from None

    raw_results = data.get("results") or []
    if not isinstance(raw_results, list):
        raise LeadDiscoveryError("Unerwartetes Antwortformat des Suchdienstes.")
    rows = normalise_results(raw_results, city, category)
    return {
        "city": city,
        "category": category,
        "query": query,
        "count": len(rows),
        "rows": rows,
        "source": "Tavily Public Web Search",
        "source_timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "excluded_platforms": list(RESTRICTED_DOMAINS),
    }


def build_manual_portal_links(city: str, category: str) -> list[dict[str, str]]:
    """Return official portal home/search links for user-operated searches."""
    city = validate_city(city)
    if category not in LEAD_CATEGORIES:
        raise ValueError("Die ausgewählte Kategorie ist ungültig.")
    phrase = {
        "Reinigung": "Gebäudereinigung Reinigungskraft Reinigungsdienst",
        "Sicherheit": "Sicherheitsdienst Objektschutz Wachdienst",
        "Facility Management": "Facility Management Hausmeisterservice",
        "Bau / Handwerk": "Bauleistungen Handwerker Instandhaltung",
    }[category]
    q = quote_plus(phrase)
    location = quote_plus(f"{city}, Nordrhein-Westfalen")
    links = []
    for portal in PORTAL_LINKS:
        item = dict(portal)
        if item["label"] == "LinkedIn Jobs":
            item["url"] = f"https://www.linkedin.com/jobs/search/?keywords={q}&location={location}"
        elif item["label"] == "Indeed Deutschland":
            item["url"] = f"https://de.indeed.com/jobs?q={q}&l={location}"
        elif item["label"] == "Facebook":
            item["url"] = f"https://www.facebook.com/search/posts/?q={q}%20{location}"
        elif item["label"] == "Bundesagentur für Arbeit":
            item["url"] = f"https://www.arbeitsagentur.de/jobsuche/?was={q}&wo={location}"
        links.append(item)
    return links
