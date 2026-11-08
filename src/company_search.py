"""On-demand, read-only discovery of business locations from OpenStreetMap."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

OVERPASS_DEFAULT_URL = "https://overpass.private.coffee/api/interpreter"
USER_AGENT = "ReinigungsRadarNRW/1.0 (on-demand business directory discovery)"

NRW_CITIES = [
    "Aachen", "Bielefeld", "Bochum", "Bonn", "Bottrop", "Dortmund",
    "Duisburg", "Düren", "Düsseldorf", "Essen", "Gelsenkirchen",
    "Krefeld", "Leverkusen", "Mönchengladbach", "Mülheim an der Ruhr",
    "Münster", "Neuss", "Oberhausen", "Paderborn", "Recklinghausen",
    "Siegen", "Solingen", "Viersen", "Witten", "Wuppertal",
]

CUSTOMER_CATEGORIES = {
    "Alle passenden Standorte": [
        'nwr["name"]["office"](area.searchArea);',
        'nwr["name"]["shop"](area.searchArea);',
        'nwr["name"]["tourism"~"hotel|guest_house"](area.searchArea);',
        'nwr["name"]["amenity"~"restaurant|cafe|hospital|clinic|doctors|dentist"](area.searchArea);',
        'nwr["name"]["landuse"="industrial"](area.searchArea);',
        'nwr["name"]["industrial"](area.searchArea);',
    ],
    "Büros und Unternehmen": ['nwr["name"]["office"](area.searchArea);'],
    "Handel und Einzelhandel": ['nwr["name"]["shop"](area.searchArea);'],
    "Hotels und Beherbergung": ['nwr["name"]["tourism"~"hotel|guest_house"](area.searchArea);'],
    "Gastronomie": ['nwr["name"]["amenity"~"restaurant|cafe"](area.searchArea);'],
    "Gesundheit": ['nwr["name"]["amenity"~"hospital|clinic|doctors|dentist"](area.searchArea);'],
    "Industrie und Gewerbe": [
        'nwr["name"]["landuse"="industrial"](area.searchArea);',
        'nwr["name"]["industrial"](area.searchArea);',
    ],
}

PROVIDER_CATEGORIES = {
    "Reinigungsunternehmen": [
        'nwr["name"]["craft"="cleaning"](area.searchArea);',
        'nwr["name"]["office"="cleaning"](area.searchArea);',
        'nwr["name"]["service"="cleaning"](area.searchArea);',
        'nwr["name"~"Gebäudereinigung|Reinigungsservice|Reinigungsfirma|Cleaning",i](area.searchArea);',
    ],
}


class CompanySearchError(RuntimeError):
    """Raised when an OpenStreetMap/Overpass search fails."""


def build_company_query(city: str, mode: str, category: str, limit: int = 80) -> str:
    """Build a bounded Overpass query for any named municipality inside NRW."""
    city = " ".join((city or "").split())
    if (
        len(city) < 2
        or len(city) > 80
        or not re.fullmatch(r"[\wÄÖÜäöüß .,'()\-]+", city, flags=re.UNICODE)
    ):
        raise ValueError("Bitte einen gültigen Stadt- oder Gemeindenamen in NRW eingeben.")
    category_map = PROVIDER_CATEGORIES if mode == "Anbieter" else CUSTOMER_CATEGORIES
    if category not in category_map:
        raise ValueError("Die ausgewählte Kategorie ist ungültig.")
    safe_city = city.replace("\\", "\\\\").replace('"', '\\"')
    safe_limit = max(5, min(int(limit), 100))
    selectors = "\n".join(category_map[category])
    return (
        '[out:json][timeout:25];\n'
        'area["boundary"="administrative"]["name"="Nordrhein-Westfalen"]["admin_level"="4"]->.nrw;\n'
        f'area["boundary"="administrative"]["name"="{safe_city}"]["admin_level"~"6|7|8"](area.nrw)->.searchArea;\n'
        '(\n' + selectors + '\n);\n'
        f'out center tags {safe_limit};'
    )


def _best_tag(tags: dict, *keys: str) -> str:
    for key in keys:
        value = tags.get(key)
        if value:
            return str(value).strip()
    return ""


def _category_label(tags: dict, mode: str) -> str:
    for key in ("office", "craft", "shop", "tourism", "amenity", "industrial", "landuse", "service"):
        value = tags.get(key)
        if value:
            return f"{key}: {value}"
    return "Standort laut OpenStreetMap" if mode == "Kunden" else "Dienstleister laut OpenStreetMap"


def _normalise_element(element: dict, city: str, mode: str) -> dict[str, str]:
    tags = element.get("tags") or {}
    street = _best_tag(tags, "addr:street")
    house_number = _best_tag(tags, "addr:housenumber")
    postcode = _best_tag(tags, "addr:postcode")
    address = " ".join(part for part in (street, house_number) if part)
    if postcode:
        address = f"{postcode} {address}".strip()
    element_type = str(element.get("type") or "")
    element_id = str(element.get("id") or "")
    osm_url = f"https://www.openstreetmap.org/{element_type}/{element_id}" if element_type and element_id else "https://www.openstreetmap.org/"
    website = _best_tag(tags, "contact:website", "website", "url")
    if website and not website.startswith(("https://", "http://")):
        website = "https://" + website
    return {
        "Unternehmen": _best_tag(tags, "name"),
        "Branche / Typ": _category_label(tags, mode),
        "Stadt": _best_tag(tags, "addr:city") or city,
        "Adresse": address,
        "PLZ": postcode,
        "Telefon": _best_tag(tags, "contact:phone", "phone"),
        "E-Mail": _best_tag(tags, "contact:email", "email"),
        "Website": website,
        "Quelle": "OpenStreetMap",
        "Quellenlink": osm_url,
        "Prüfdatum": datetime.now(timezone.utc).date().isoformat(),
        "Datenstatus": "Öffentlicher Karteneintrag – nicht unabhängig verifiziert",
    }


def search_companies(
    city: str,
    mode: str,
    category: str,
    limit: int = 80,
    timeout: int = 22,
) -> dict:
    """Search one city on demand, fail over across public Overpass instances."""
    query = build_company_query(city, mode, category, limit)
    configured = os.environ.get("OVERPASS_API_URL", "").strip()
    endpoints = []
    if configured:
        endpoints.append(configured)
    endpoints.extend([
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        OVERPASS_DEFAULT_URL,
    ])
    # Preserve order while removing duplicate endpoints.
    endpoints = list(dict.fromkeys(endpoints))

    failures: list[str] = []
    payload = None
    for endpoint in endpoints:
        if not endpoint.startswith("https://"):
            failures.append("configured endpoint is not HTTPS")
            continue
        request = Request(
            endpoint,
            data=urlencode({"data": query}).encode("utf-8"),
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                candidate = json.loads(response.read().decode("utf-8"))
            if not isinstance(candidate, dict) or not isinstance(candidate.get("elements"), list):
                failures.append("invalid JSON response")
                continue
            payload = candidate
            break
        except HTTPError as exc:
            failures.append(f"{endpoint}: HTTP {exc.code}")
        except (URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", None)
            failures.append(f"{endpoint}: {reason or type(exc).__name__}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            failures.append(f"{endpoint}: invalid JSON")

    if payload is None:
        details = "; ".join(failures[-3:])
        raise CompanySearchError(
            "Alle öffentlichen Overpass-Server sind momentan nicht erreichbar "
            "oder ausgelastet. " + details
        )

    elements = payload.get("elements")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for element in elements:
        if not isinstance(element, dict):
            continue
        row = _normalise_element(element, city, mode)
        name = row["Unternehmen"].strip()
        if not name:
            continue
        key = re.sub(r"[^a-z0-9]+", "", name.casefold())
        address_key = re.sub(r"[^a-z0-9]+", "", row["Adresse"].casefold())
        dedupe_key = f"{key}|{address_key}" if address_key else f"{key}|{row['Stadt'].casefold()}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        rows.append(row)

    return {
        "city": city,
        "mode": mode,
        "category": category,
        "count": len(rows),
        "rows": rows,
        "source": "OpenStreetMap / Overpass API",
        "source_timestamp": (payload.get("osm3s") or {}).get("timestamp_osm_base", ""),
        "query": query,
    }
