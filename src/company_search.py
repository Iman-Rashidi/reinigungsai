"""On-demand, read-only discovery of business locations from OpenStreetMap."""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from src.overture_search import OvertureSearchError, search_overture_companies

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
    "Reinigung": [
        'nwr["name"]["craft"="cleaning"](area.searchArea);',
        'nwr["name"]["office"="cleaning"](area.searchArea);',
        'nwr["name"]["service"="cleaning"](area.searchArea);',
        'nwr["name"~"Gebäudereinigung|Reinigungsservice|Reinigungsfirma|Cleaning",i](area.searchArea);',
    ],
    "Sicherheit und Bewachung": [
        'nwr["name"]["office"~"security|guard"](area.searchArea);',
        'nwr["name"]["craft"="security"](area.searchArea);',
        'nwr["name"]["security"](area.searchArea);',
        'nwr["name"~"Sicherheitsdienst|Sicherheitsunternehmen|Sicherheitsservice|Security|Wachdienst|Bewachung|Objektschutz|Werkschutz|Veranstaltungsschutz|Personenschutz|Empfangsdienst|Revierdienst|Wachschutz|Alarmdienst|Schließdienst|Doorman|Guarding",i](area.searchArea);',
        'nwr["brand"~"Sicherheitsdienst|Sicherheitsunternehmen|Security|Wachdienst|Bewachung|Objektschutz|Werkschutz",i](area.searchArea);',
        'nwr["operator"~"Sicherheitsdienst|Sicherheitsunternehmen|Security|Wachdienst|Bewachung|Objektschutz|Werkschutz",i](area.searchArea);',
        'nwr["description"~"Sicherheitsdienst|Bewachung|Objektschutz|Werkschutz|Veranstaltungsschutz|Wachschutz",i](area.searchArea);',
    ],
    "Service und Facility Management": [
        'nwr["name"]["office"="facility_management"](area.searchArea);',
        'nwr["name"]["service"="facility_management"](area.searchArea);',
        'nwr["name"~"Facility.?Management|Gebäudeservice|Hausmeisterservice|Industrieservice",i](area.searchArea);',
    ],
    "Bauunternehmen und Baugewerbe": [
        'nwr["name"]["office"="construction"](area.searchArea);',
        'nwr["name"]["construction"](area.searchArea);',
        'nwr["name"~"Bauunternehmen|Bau GmbH|Baugesellschaft|Hochbau|Tiefbau|Bauleistungen",i](area.searchArea);',
    ],
}

PROVIDER_CATEGORIES = {
    "Reinigungsunternehmen": [
        'nwr["name"]["craft"="cleaning"](area.searchArea);',
        'nwr["name"]["office"="cleaning"](area.searchArea);',
        'nwr["name"]["service"="cleaning"](area.searchArea);',
        'nwr["name"~"Gebäudereinigung|Reinigungsservice|Reinigungsfirma|Cleaning",i](area.searchArea);',
    ],
    "Sicherheitsdienste": [
        'nwr["name"]["office"~"security|guard"](area.searchArea);',
        'nwr["name"]["craft"="security"](area.searchArea);',
        'nwr["name"]["security"](area.searchArea);',
        'nwr["name"~"Sicherheitsdienst|Sicherheitsunternehmen|Sicherheitsservice|Security|Wachdienst|Bewachung|Objektschutz|Werkschutz|Veranstaltungsschutz|Personenschutz|Empfangsdienst|Revierdienst|Wachschutz|Alarmdienst|Schließdienst|Doorman|Guarding",i](area.searchArea);',
        'nwr["brand"~"Sicherheitsdienst|Sicherheitsunternehmen|Security|Wachdienst|Bewachung|Objektschutz|Werkschutz",i](area.searchArea);',
        'nwr["operator"~"Sicherheitsdienst|Sicherheitsunternehmen|Security|Wachdienst|Bewachung|Objektschutz|Werkschutz",i](area.searchArea);',
        'nwr["description"~"Sicherheitsdienst|Bewachung|Objektschutz|Werkschutz|Veranstaltungsschutz|Wachschutz",i](area.searchArea);',
    ],
    "Facility Management": [
        'nwr["name"]["office"="facility_management"](area.searchArea);',
        'nwr["name"]["service"="facility_management"](area.searchArea);',
        'nwr["name"~"Facility.?Management|Gebäudeservice|Hausmeisterservice|Industrieservice",i](area.searchArea);',
    ],
    "Bauunternehmen": [
        'nwr["name"]["office"="construction"](area.searchArea);',
        'nwr["name"]["construction"](area.searchArea);',
        'nwr["name"~"Bauunternehmen|Bau GmbH|Baugesellschaft|Hochbau|Tiefbau|Bauleistungen",i](area.searchArea);',
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
    safe_limit = max(5, min(int(limit), 1000))
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
        "Unternehmen": _best_tag(tags, "name", "brand", "operator"),
        "Branche / Typ": _category_label(tags, mode),
        "Stadt": _best_tag(tags, "addr:city") or city,
        "Adresse": address,
        "PLZ": postcode,
        "Telefon": _best_tag(tags, "contact:phone", "phone"),
        "E-Mail": _best_tag(tags, "contact:email", "email"),
        "Ansprechpartner": _best_tag(tags, "contact:person", "contact:name", "contact:individual"),
        "Funktion Ansprechpartner": _best_tag(tags, "contact:role", "contact:job_title", "contact:position", "contact:title"),
        "Website": website,
        "Quelle": "OpenStreetMap",
        "Quellenlink": osm_url,
        "Prüfdatum": datetime.now(timezone.utc).date().isoformat(),
        "Datenstatus": "Öffentlicher Karteneintrag – nicht unabhängig verifiziert",
    }




def _city_key(value: str) -> str:
    """Create a comparison key for municipality names without accent differences."""
    text = str(value or "").strip().casefold().replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"^(?:kreisfreie\s+stadt|landeshauptstadt|stadt)\s+", "", text)
    text = re.sub(r"\s*,?\s*(?:kreisfreie\s+stadt|stadt)$", "", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def _same_city(candidate: str, requested: str) -> bool:
    """Return True only when a source explicitly identifies the requested city."""
    requested_key = _city_key(requested)
    return bool(requested_key and _city_key(candidate) == requested_key)

def _photon_search(city: str, mode: str, category: str, limit: int, timeout: int) -> dict:
    """Fallback search against Photon public OSM index, at low request volume."""
    if mode == "Anbieter":
        term_map = {
            "Reinigungsunternehmen": "Gebäudereinigung Reinigungsservice",
            "Sicherheitsdienste": "Sicherheitsdienst Sicherheitsunternehmen Security Wachdienst Bewachung Objektschutz Werkschutz Veranstaltungsschutz",
            "Facility Management": "Facility Management Hausmeisterservice",
            "Bauunternehmen": "Bauunternehmen",
        }
    else:
        term_map = {
            "Alle passenden Standorte": "Unternehmen Büro Gewerbe",
            "Büros und Unternehmen": "Büro Unternehmen",
            "Handel und Einzelhandel": "Einzelhandel Geschäft",
            "Hotels und Beherbergung": "Hotel",
            "Gastronomie": "Restaurant Café",
            "Gesundheit": "Krankenhaus Klinik Arztpraxis",
            "Industrie und Gewerbe": "Industrieunternehmen Gewerbe",
            "Reinigung": "Reinigungsunternehmen Gebäudereinigung",
            "Sicherheit und Bewachung": "Sicherheitsdienst Bewachung Wachdienst",
            "Service und Facility Management": "Facility Management Hausmeisterservice",
            "Bauunternehmen und Baugewerbe": "Bauunternehmen Baugewerbe",
        }
    terms = term_map.get(category)
    if not terms:
        raise ValueError("Die ausgewählte Kategorie ist ungültig.")
    search_term = f"{terms} {city} Nordrhein-Westfalen Deutschland"
    params = urlencode({"q": search_term, "limit": min(max(int(limit), 5), 20), "lang": "de"})
    request = Request(
        f"https://photon.komoot.io/api/?{params}",
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        method="GET",
    )
    try:
        with urlopen(request, timeout=min(timeout, 12)) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise CompanySearchError(f"Photon meldet HTTP {exc.code}.") from None
    except (URLError, TimeoutError, OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        reason = getattr(exc, "reason", None)
        raise CompanySearchError(f"Photon ist nicht erreichbar: {reason or type(exc).__name__}.") from None

    rows = []
    seen = set()
    for feature in payload.get("features", []):
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties") or {}
        name = str(props.get("name") or "").strip()
        if not name:
            continue
        # Photon is a global index. Require an explicit locality match rather
        # than trusting query wording, which can otherwise leak other cities.
        city_values = [
            str(props.get(key) or "").strip()
            for key in ("city", "locality", "county", "district")
            if props.get(key)
        ]
        if not any(_same_city(value, city) for value in city_values):
            continue
        osm_id = props.get("osm_id")
        osm_type = str(props.get("osm_type") or "").lower()
        osm_kind = {"n": "node", "w": "way", "r": "relation"}.get(osm_type, "node")
        source_url = (
            f"https://www.openstreetmap.org/{osm_kind}/{osm_id}"
            if osm_id else "https://www.openstreetmap.org/"
        )
        key = re.sub(r"[^a-z0-9]+", "", name.casefold())
        address_key = re.sub(
            r"[^a-z0-9]+", "",
            " ".join(str(props.get(k) or "") for k in ("postcode", "street", "housenumber")).casefold()
        )
        dedupe_key = f"{key}|{address_key}" if address_key else f"{key}|{city.casefold()}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        street = " ".join(str(props.get(k) or "").strip() for k in ("street", "housenumber")).strip()
        postcode = str(props.get("postcode") or "")
        rows.append({
            "Unternehmen": name,
            "Branche / Typ": " ".join(str(props.get(k) or "") for k in ("osm_key", "osm_value")).strip() or category,
            "Stadt": city,
            "Adresse": " ".join(part for part in (postcode, street) if part),
            "PLZ": postcode,
            "Telefon": "",
            "E-Mail": "",
            "Ansprechpartner": "",
            "Funktion Ansprechpartner": "",
            "Website": "",
            "Quelle": "OpenStreetMap / Photon",
            "Quellenlink": source_url,
            "Prüfdatum": datetime.now(timezone.utc).date().isoformat(),
            "Datenstatus": "Photon-Kartentreffer – Kontaktdaten nicht enthalten; bitte prüfen",
        })
    return {
        "city": city, "mode": mode, "category": category,
        "count": len(rows), "rows": rows,
        "source": "OpenStreetMap / Photon (Fallback)",
        "source_timestamp": datetime.now(timezone.utc).isoformat(),
        "query": search_term,
    }


def _company_row_keys(row: dict[str, str]) -> set[tuple[str, ...]]:
    """Build conservative same-location keys so different branches stay distinct."""
    name = re.sub(r"[^a-z0-9]+", "", str(row.get("Unternehmen") or "").casefold())
    if not name:
        return set()
    city = _city_key(row.get("Stadt") or "")
    address = re.sub(r"[^a-z0-9]+", "", str(row.get("Adresse") or "").casefold())
    postcode = re.sub(r"\D+", "", str(row.get("PLZ") or ""))
    phone = re.sub(r"\D+", "", str(row.get("Telefon") or ""))
    keys: set[tuple[str, ...]] = set()
    if address:
        keys.add(("name-address", name, address))
    elif postcode:
        keys.add(("name-postcode", name, postcode))
    else:
        keys.add(("name-city", name, city))
    if phone:
        keys.add(("name-phone", name, phone))
    return keys


def _merge_company_rows(*row_groups: list[dict[str, str]]) -> list[dict[str, str]]:
    """Merge records across providers while retaining distinct branch addresses."""
    merged: list[dict[str, str]] = []
    key_to_index: dict[tuple[str, ...], int] = {}
    for group in row_groups:
        for source_row in group:
            row = dict(source_row)
            keys = _company_row_keys(row)
            matched_index = next(
                (key_to_index[key] for key in keys if key in key_to_index),
                None,
            )
            if matched_index is None:
                matched_index = len(merged)
                merged.append(row)
            else:
                current = merged[matched_index]
                for field, value in row.items():
                    if field in ("Quelle", "Quellenlink", "Datenstatus"):
                        continue
                    if value and not current.get(field):
                        current[field] = value
                source_names = list(dict.fromkeys(
                    part.strip()
                    for part in (str(current.get("Quelle", "")) + " + " + str(row.get("Quelle", ""))).split("+")
                    if part.strip()
                ))
                current["Quelle"] = " + ".join(source_names)
                old_status = str(current.get("Datenstatus") or "").strip()
                new_status = str(row.get("Datenstatus") or "").strip()
                if new_status and new_status not in old_status:
                    current["Datenstatus"] = " · ".join(part for part in (old_status, new_status) if part)
                if not current.get("Quellenlink") and row.get("Quellenlink"):
                    current["Quellenlink"] = row["Quellenlink"]
            for key in keys:
                key_to_index[key] = matched_index
    return merged


def search_companies(
    city: str,
    mode: str,
    category: str,
    limit: int = 250,
    timeout: int = 22,
) -> dict:
    """Search a town across Overture Places and OpenStreetMap, then deduplicate."""
    city = " ".join((city or "").split()).strip()
    if not city:
        raise ValueError("Bitte eine Stadt oder Gemeinde in NRW eingeben.")
    requested_limit = max(10, min(int(limit), 5000))

    # Validate the mode and category before calling any external source.
    query = build_company_query(city, mode, category, requested_limit)

    warnings: list[str] = []
    overture_rows: list[dict[str, str]] = []
    try:
        overture_rows = search_overture_companies(
            city=city,
            mode=mode,
            category=category,
            limit=requested_limit,
            timeout=timeout,
        )
    except (OvertureSearchError, ValueError) as exc:
        warnings.append(f"Overture Maps: {exc}")

    # OSM remains a complementary source. It no longer has a 100-record ceiling.
    osm_limit = min(requested_limit, 1000)
    osm_query = build_company_query(city, mode, category, osm_limit)
    endpoints = [
        "https://ovp.dresel.systems/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
        "https://overpass-api.de/api/interpreter",
        OVERPASS_DEFAULT_URL,
    ]
    endpoints = list(dict.fromkeys(endpoints))

    failures: list[str] = []
    payload = None
    for endpoint in endpoints:
        if not endpoint.startswith("https://"):
            failures.append("configured endpoint is not HTTPS")
            continue
        request = Request(
            endpoint,
            data=urlencode({"data": osm_query}).encode("utf-8"),
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=min(max(timeout, 5), 15)) as response:
                candidate = json.loads(response.read().decode("utf-8"))
            if not isinstance(candidate, dict) or not isinstance(candidate.get("elements"), list):
                failures.append(f"{endpoint}: invalid JSON response")
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

    osm_rows: list[dict[str, str]] = []
    photon_rows: list[dict[str, str]] = []
    if payload is not None:
        for element in payload.get("elements", []):
            if not isinstance(element, dict):
                continue
            tags = element.get("tags") or {}
            tagged_city = _best_tag(tags, "addr:city")
            if tagged_city and not _same_city(tagged_city, city):
                continue
            row = _normalise_element(element, city, mode)
            if not row["Unternehmen"].strip():
                continue
            osm_rows.append(row)
    else:
        warnings.append(
            "Overpass war nicht erreichbar. Die Suche versucht zusätzlich den Photon-Index."
        )
        try:
            photon_result = _photon_search(city, mode, category, min(requested_limit, 20), timeout)
            photon_rows = photon_result.get("rows", [])
        except (CompanySearchError, ValueError) as exc:
            failures.append(str(exc))

    source_groups = []
    if overture_rows:
        source_groups.append(overture_rows)
    if osm_rows:
        source_groups.append(osm_rows)
    if photon_rows:
        source_groups.append(photon_rows)

    if not source_groups and payload is None and not warnings:
        warnings.extend(failures[-3:])
    if not source_groups and payload is None and not overture_rows:
        details = "; ".join((warnings + failures)[-5:])
        raise CompanySearchError(
            "Weder Overture Maps noch OpenStreetMap/Photon konnten Ergebnisse liefern. "
            + details
        )

    merged_rows = _merge_company_rows(*source_groups) if source_groups else []
    merged_rows = merged_rows[:requested_limit]

    source_breakdown = {
        "Overture Maps": len(overture_rows),
        "OpenStreetMap / Overpass": len(osm_rows),
        "OpenStreetMap / Photon": len(photon_rows),
    }
    used_sources = [
        source for source, count in source_breakdown.items()
        if count > 0
    ]
    if not used_sources:
        # A successful empty response still identifies the providers that were queried.
        used_sources = (
            ["Overture Maps", "OpenStreetMap / Overpass"]
            if payload is not None
            else ["OpenStreetMap / Photon"]
        )

    return {
        "city": city,
        "mode": mode,
        "category": category,
        "count": len(merged_rows),
        "rows": merged_rows,
        "source": " + ".join(used_sources),
        "source_breakdown": source_breakdown,
        "source_warnings": warnings + failures[-3:],
        "source_timestamp": (payload.get("osm3s") or {}).get("timestamp_osm_base", "")
        if payload is not None else datetime.now(timezone.utc).isoformat(),
        "query": osm_query,
        "requested_limit": requested_limit,
    }
