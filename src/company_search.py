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



def _google_places_search(city: str, mode: str, category: str, limit: int, api_key: str) -> dict:
    """Search Google Places Text Search (New); requires a configured Places API key."""
    if mode == "Anbieter":
        search_term = "Gebäudereinigungsunternehmen Reinigungsservice"
    else:
        search_term = {
            "Alle passenden Standorte": "Unternehmen Büro Industrie Gewerbe",
            "Büros und Unternehmen": "Bürogebäude Unternehmen Firmenstandort",
            "Handel und Einzelhandel": "Einkaufszentrum Einzelhandel Geschäft",
            "Hotels und Beherbergung": "Hotel",
            "Gastronomie": "Restaurant Café",
            "Gesundheit": "Krankenhaus Klinik Arztpraxis",
            "Industrie und Gewerbe": "Industrieunternehmen Gewerbepark Fabrik",
        }.get(category, "Unternehmen")
    body = json.dumps({
        "textQuery": f"{search_term} in {city}, Nordrhein-Westfalen, Deutschland",
        "pageSize": min(max(int(limit), 1), 20),
        "languageCode": "de",
        "regionCode": "DE",
    }).encode("utf-8")
    request = Request(
        "https://places.googleapis.com/v1/places:searchText",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": (
                "places.id,places.displayName,places.formattedAddress,"
                "places.addressComponents,places.websiteUri,places.nationalPhoneNumber,"
                "places.googleMapsUri,places.location,places.types"
            ),
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise CompanySearchError(f"Google Places API meldet HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise CompanySearchError(f"Google Places API ist momentan nicht erreichbar: {exc}") from exc

    rows = []
    for place in payload.get("places", []):
        name = (place.get("displayName") or {}).get("text", "").strip()
        if not name:
            continue
        components = place.get("addressComponents") or []
        city_name = ""
        postcode = ""
        for component in components:
            types = component.get("types") or []
            if any(t in types for t in ("locality", "postal_town")):
                city_name = component.get("longText", "")
            if "postal_code" in types:
                postcode = component.get("longText", "")
        if not city_name:
            # Keep the selected municipality as fallback, never the pilot city.
            city_name = city
        rows.append({
            "Unternehmen": name,
            "Branche / Typ": ", ".join((place.get("types") or [])[:3]) or category,
            "Stadt": city_name,
            "Adresse": place.get("formattedAddress", ""),
            "PLZ": postcode,
            "Telefon": place.get("nationalPhoneNumber", ""),
            "E-Mail": "",
            "Website": place.get("websiteUri", ""),
            "Quelle": "Google Maps / Google Places",
            "Quellenlink": place.get("googleMapsUri", ""),
            "Prüfdatum": datetime.now(timezone.utc).date().isoformat(),
            "Datenstatus": "Google Places-Ergebnis – Angaben vor Kontaktaufnahme prüfen",
        })
    return {
        "city": city, "mode": mode, "category": category, "count": len(rows),
        "rows": rows, "source": "Google Maps / Google Places API",
        "source_timestamp": datetime.now(timezone.utc).isoformat(),
    }

def search_companies(
    city: str,
    mode: str,
    category: str,
    limit: int = 80,
    timeout: int = 22,
) -> dict:
    """Search one city on demand, fail over across public Overpass instances."""
    city = " ".join((city or "").split()).strip()
    if not city:
        raise ValueError("Bitte eine Stadt in NRW eingeben.")
    google_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if google_key:
        return _google_places_search(city, mode, category, limit, google_key)
    query = build_company_query(city, mode, category, limit)
    configured = os.environ.get("OVERPASS_API_URL", "").strip()
    endpoints = []
    if configured:
        endpoints.append(configured)
    endpoints.extend([
        # Europe-wide daily extract, independent of the main OSMF instance.
        "https://ovp.dresel.systems/api/interpreter",
        # Global VK Maps instance, operated independently.
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
        "https://overpass-api.de/api/interpreter",
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
