"""Company discovery from Overture Maps' open Places dataset.

Only the requested city's bounding box is read from Overture's public cloud
GeoParquet. No Google Maps key, paid API, local bulk download, or database is
required. The public Photon endpoint is used only to resolve a city bounding
box; its result is cached by Streamlit at the application layer.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import warnings

USER_AGENT = "ReinigungsRadarNRW/2.0 (open Overture company discovery)"
PHOTON_URL = "https://photon.komoot.io/api/"
OVERTURE_GUIDE_URL = "https://docs.overturemaps.org/guides/places/"
MAX_RESULTS = 5000

CATEGORY_PATTERNS = {
    "Büros und Unternehmen": (
        "business", "professional_service", "office", "company", "corporate",
        "commercial", "consulting", "accounting", "coworking", "legal_service",
        "marketing_agency", "employment_service",
    ),
    "Handel und Einzelhandel": (
        "shopping", "retail", "store", "shop", "supermarket", "market",
        "department_store", "convenience",
    ),
    "Hotels und Beherbergung": (
        "lodging", "hotel", "guest_house", "hostel", "motel", "bed_and_breakfast",
    ),
    "Gastronomie": (
        "food_and_drink", "restaurant", "cafe", "bar", "bakery", "fast_food",
        "food_court", "caterer",
    ),
    "Gesundheit": (
        "health_care", "hospital", "clinic", "doctor", "dentist", "medical",
        "pharmacy", "physiotherapy",
    ),
    "Industrie und Gewerbe": (
        "industrial", "manufacturing", "factory", "warehouse", "logistics",
        "industrial_park", "distribution_center",
    ),
    "Reinigung": (
        "cleaning", "janitorial", "housekeeping", "laundry", "dry_clean",
        "commercial_clean", "maid_service",
    ),
    "Reinigungsunternehmen": (
        "cleaning", "janitorial", "housekeeping", "laundry", "dry_clean",
        "commercial_clean", "maid_service",
    ),
    "Sicherheitsdienste": (
        "security", "guard", "alarm", "surveillance", "locksmith",
    ),
    "Sicherheit und Bewachung": (
        "security", "guard", "alarm", "surveillance", "locksmith",
    ),
    "Facility Management": (
        "facility", "property_management", "building_maintenance", "janitorial",
        "handyman", "maintenance", "building_service",
    ),
    "Service und Facility Management": (
        "facility", "property_management", "building_maintenance", "janitorial",
        "handyman", "maintenance", "building_service",
    ),
    "Bauunternehmen": (
        "construction", "contractor", "builder", "engineering", "architect",
        "roofing", "plumbing", "electrician", "renovation",
    ),
    "Bauunternehmen und Baugewerbe": (
        "construction", "contractor", "builder", "engineering", "architect",
        "roofing", "plumbing", "electrician", "renovation",
    ),
}

NON_COMMERCIAL_ALL_MATCH = (
    "mountain", "peak", "waterfall", "river", "lake", "beach", "natural_feature",
    "national_park", "campground", "trail",
)


class OvertureSearchError(RuntimeError):
    """Raised when Overture search cannot be completed."""


def _city_key(value: str) -> str:
    value = str(value or "").strip().casefold().replace("ß", "ss")
    value = value.replace("ä", "a").replace("ö", "o").replace("ü", "u")
    value = value.replace("ae", "a").replace("oe", "o").replace("ue", "u")
    value = re.sub(r"^(?:kreisfreie\s+stadt|landeshauptstadt|stadt)\s+", "", value)
    return re.sub(r"[^a-z0-9]+", "", value)


def geocode_city_bbox(city: str, timeout: int = 15) -> tuple[float, float, float, float]:
    """Resolve one exact German city/town result to a Photon bounding box."""
    city = " ".join(str(city or "").split()).strip()
    if len(city) < 2 or len(city) > 80:
        raise ValueError("Bitte einen gültigen Stadt- oder Gemeindenamen eingeben.")

    params = urlencode({
        "q": f"{city}, Nordrhein-Westfalen, Deutschland",
        "countrycode": "DE",
        "lang": "de",
        "limit": 10,
    })
    request = Request(
        f"{PHOTON_URL}?{params}",
        headers={"Accept": "application/geo+json, application/json", "User-Agent": USER_AGENT},
        method="GET",
    )
    try:
        with urlopen(request, timeout=min(max(timeout, 5), 20)) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise OvertureSearchError(f"Photon meldet HTTP {exc.code} bei der Stadtsuche.") from None
    except (URLError, TimeoutError, OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        reason = getattr(exc, "reason", None)
        raise OvertureSearchError(
            f"Das Suchgebiet für {city} konnte nicht ermittelt werden: "
            f"{reason or type(exc).__name__}."
        ) from None

    for feature in payload.get("features", []):
        props = feature.get("properties") or {}
        if _city_key(props.get("name", "")) != _city_key(city):
            continue
        if str(props.get("countrycode") or "").upper() not in ("", "DE"):
            continue
        extent = props.get("extent")
        if not isinstance(extent, (list, tuple)) or len(extent) != 4:
            continue
        try:
            x1, y1, x2, y2 = (float(value) for value in extent)
        except (TypeError, ValueError):
            continue
        west, east = sorted((x1, x2))
        south, north = sorted((y1, y2))
        if -180 <= west < east <= 180 and -90 <= south < north <= 90:
            # Reject implausibly broad geocoder matches; these are not towns.
            if east - west <= 1.5 and north - south <= 1.5:
                return west, south, east, north

    raise OvertureSearchError(
        f"Für „{city}“ wurde keine eindeutige Gemeindegrenze gefunden. "
        "Bitte den offiziellen Stadtnamen eingeben."
    )


def _iter_batches(bbox: tuple[float, float, float, float], timeout: int):
    """Return the official Overture Arrow stream for only the intersecting files."""
    try:
        from overturemaps import record_batch_reader
        from overturemaps.core import StacIndexWarning
    except ImportError as exc:
        raise OvertureSearchError(
            "Der Overture-Datenclient fehlt. Bitte overturemaps installieren."
        ) from exc

    # A failed STAC index must not silently trigger a slow scan of every global
    # Places file on a small free instance.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", StacIndexWarning)
            reader = record_batch_reader(
                "place",
                bbox=bbox,
                connect_timeout=min(max(timeout, 5), 20),
                request_timeout=min(max(timeout * 2, 15), 60),
                stac=True,
            )
    except Exception as exc:
        raise OvertureSearchError(f"Overture konnte die Stadtdateien nicht laden: {exc}") from None

    if reader is None:
        raise OvertureSearchError("Overture hat keinen Datenstrom für dieses Suchgebiet geliefert.")
    return reader


def _first(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        for item in value:
            result = _first(item)
            if result:
                return result
        return ""
    if isinstance(value, dict):
        for key in ("value", "primary", "url", "number", "freeform"):
            result = _first(value.get(key))
            if result:
                return result
        return ""
    return str(value).strip()


def _category_text(record: dict) -> str:
    taxonomy = record.get("taxonomy") or {}
    values = [
        record.get("basic_category"),
        taxonomy.get("primary") if isinstance(taxonomy, dict) else "",
        taxonomy.get("hierarchy") if isinstance(taxonomy, dict) else "",
        taxonomy.get("alternates") if isinstance(taxonomy, dict) else "",
    ]
    return " ".join(_first(value) for value in values if value).casefold()


def _matches_category(record: dict, category: str) -> bool:
    text = _category_text(record)
    if category == "Alle passenden Standorte":
        return not any(pattern in text for pattern in NON_COMMERCIAL_ALL_MATCH)
    patterns = CATEGORY_PATTERNS.get(category)
    if not patterns:
        return True
    return any(pattern in text for pattern in patterns)


def _normalise_record(record: dict, city: str) -> dict[str, str] | None:
    names = record.get("names") or {}
    name = _first(names.get("primary") if isinstance(names, dict) else names)
    if not name:
        return None

    status = str(record.get("operating_status") or "").casefold()
    if status in ("permanently_closed", "closed_permanently"):
        return None

    confidence_value = record.get("confidence")
    try:
        confidence = float(confidence_value) if confidence_value is not None else None
    except (TypeError, ValueError):
        confidence = None
    if confidence is not None and confidence < 0.20:
        return None

    addresses = record.get("addresses") or []
    address = addresses[0] if addresses and isinstance(addresses[0], dict) else {}
    address_text = _first(address.get("freeform"))
    if not address_text:
        address_text = " ".join(
            part for part in (
                _first(address.get("postcode")),
                _first(address.get("locality")),
                _first(address.get("region")),
            ) if part
        )

    taxonomy = record.get("taxonomy") or {}
    category = ""
    if isinstance(taxonomy, dict):
        category = _first(taxonomy.get("primary"))
    category = category or _first(record.get("basic_category")) or "Unternehmen / Standort"

    websites = record.get("websites") or []
    website = _first(websites)
    if website and not website.startswith(("https://", "http://")):
        website = "https://" + website

    return {
        "Unternehmen": name,
        "Branche / Typ": category.replace("_", " "),
        "Stadt": city,
        "Adresse": address_text,
        "PLZ": _first(address.get("postcode")),
        "Telefon": _first(record.get("phones")),
        "E-Mail": _first(record.get("emails")),
        "Ansprechpartner": "",
        "Funktion Ansprechpartner": "",
        "Website": website,
        "Quelle": "Overture Maps",
        "Quellenlink": OVERTURE_GUIDE_URL,
        "Prüfdatum": datetime.now(timezone.utc).date().isoformat(),
        "Datenstatus": (
            f"Offener Overture-Karteneintrag"
            + (f" · Confidence {confidence:.2f}" if confidence is not None else "")
            + (f" · Status {status}" if status else "")
            + (f" · GERS {record.get('id')}" if record.get("id") else "")
            + " · Angaben vor Nutzung prüfen"
        ),
    }


def search_overture_companies(
    city: str,
    mode: str,
    category: str,
    limit: int = 1000,
    timeout: int = 20,
) -> list[dict[str, str]]:
    """Find named Overture Places within one town's bounding box."""
    if mode not in ("Kunden", "Anbieter"):
        raise ValueError("Die Suchart ist ungültig.")
    allowed = (
        ("Alle passenden Standorte", "Büros und Unternehmen", "Handel und Einzelhandel",
         "Hotels und Beherbergung", "Gastronomie", "Gesundheit", "Industrie und Gewerbe",
         "Reinigung", "Sicherheit und Bewachung", "Service und Facility Management",
         "Bauunternehmen und Baugewerbe")
        if mode == "Kunden"
        else ("Reinigungsunternehmen", "Sicherheitsdienste", "Facility Management", "Bauunternehmen")
    )
    if category not in allowed:
        raise ValueError("Die ausgewählte Kategorie ist ungültig.")

    bbox = geocode_city_bbox(city, timeout=timeout)
    reader = _iter_batches(bbox, timeout)
    max_rows = max(10, min(int(limit), MAX_RESULTS))
    results: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    scanned = 0
    max_scan = min(max_rows * 40, 100_000)

    try:
        for batch in reader:
            for record in batch.to_pylist():
                scanned += 1
                if scanned > max_scan:
                    break
                if not isinstance(record, dict) or not _matches_category(record, category):
                    continue
                row = _normalise_record(record, city)
                if row is None:
                    continue
                name_key = re.sub(r"[^a-z0-9]+", "", row["Unternehmen"].casefold())
                address_key = re.sub(r"[^a-z0-9]+", "", row["Adresse"].casefold())
                dedupe_key = (name_key, address_key or _city_key(city))
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                results.append(row)
                if len(results) >= max_rows:
                    break
            if scanned > max_scan or len(results) >= max_rows:
                break
    except Exception as exc:
        if results:
            return results
        raise OvertureSearchError(f"Fehler beim Lesen der Overture-Daten: {exc}") from None

    return results
