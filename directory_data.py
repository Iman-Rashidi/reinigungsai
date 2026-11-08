"""Pure helpers for rendering Notion directory records in the Streamlit app."""
from __future__ import annotations

import csv
import io
from typing import Any


CUSTOMER_COLUMNS = [
    "Unternehmen", "Branche", "Stadt", "Adresse", "Website", "Score",
    "Potenzial", "Status", "Datenqualität", "Quellenlink", "Quelle / Hinweis",
    "Offene Informationen", "Nächster Schritt", "Prüfdatum",
    "Duplikatprüfung", "Bewertungsgrundlage", "Prüfnotizen",
]

PROVIDER_COLUMNS = [
    "Unternehmen", "Dienstleistung", "Stadt", "PLZ", "Adresse", "Telefon",
    "E-Mail", "Website", "Einsatzgebiet", "Zertifikate / Erlaubnisse",
    "Quelle", "Quellenlink", "Prüfdatum", "Datenstatus", "Notizen",
]


def property_text(prop: Any) -> str:
    """Convert a Notion API property object to a readable scalar string."""
    if not isinstance(prop, dict):
        return str(prop).strip() if prop is not None else ""

    for key in ("title", "rich_text", "multi_select"):
        items = prop.get(key)
        if isinstance(items, list):
            parts = []
            for item in items:
                if isinstance(item, dict):
                    value = item.get("plain_text")
                    if value is None:
                        value = item.get("name")
                    if value is None and isinstance(item.get("text"), dict):
                        value = item["text"].get("content")
                    parts.append(str(value or ""))
            return "; ".join(part for part in parts if part)

    date_value = prop.get("date")
    if isinstance(date_value, dict):
        start = str(date_value.get("start") or "").strip()
        end = str(date_value.get("end") or "").strip()
        if start and end and end != start:
            return f"{start} – {end}"
        return start

    for key in ("url", "email", "phone_number", "number"):
        if prop.get(key) is not None:
            return str(prop[key]).strip()

    for key in ("select", "status"):
        selected = prop.get(key)
        if isinstance(selected, dict):
            return str(selected.get("name") or "").strip()

    if prop.get("checkbox") is not None:
        return "Ja" if prop["checkbox"] else "Nein"

    return ""


def pages_to_rows(pages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Map Notion pages to directory rows, using the page title as a safe fallback.

    Notion databases can name their title property differently (e.g. Name, Firma,
    or Unternehmen). The API page title is authoritative even when that property
    does not match the dashboard's canonical column name.
    """
    rows: list[dict[str, str]] = []
    for page in pages:
        properties = page.get("properties", {})
        row = {name: property_text(value) for name, value in properties.items()}

        # Prefer the canonical field, then common German/English title labels.
        company_name = (
            row.get("Unternehmen", "").strip()
            or row.get("Firma", "").strip()
            or row.get("Name", "").strip()
        )

        # If the title property has a custom label, discover it by its Notion type.
        if not company_name:
            for property_name, prop in properties.items():
                if isinstance(prop, dict) and isinstance(prop.get("title"), list):
                    company_name = property_text(prop).strip()
                    if company_name:
                        break

        # Final fallback: Notion's page-level title extraction.
        if not company_name:
            title_parts = []
            for prop in properties.values():
                if isinstance(prop, dict) and isinstance(prop.get("title"), list):
                    title_parts.extend(
                        str(item.get("plain_text") or "")
                        for item in prop["title"]
                        if isinstance(item, dict)
                    )
            company_name = " ".join(part for part in title_parts if part).strip()

        if company_name:
            row["Unternehmen"] = company_name
            rows.append(row)
    return rows

def complete_rows(
    rows: list[dict[str, str]], columns: list[str]
) -> list[dict[str, str]]:
    """Return rows with a stable column order and blank values for missing fields."""
    return [{column: str(row.get(column) or "") for column in columns} for row in rows]


def filter_rows(
    rows: list[dict[str, str]],
    city_filter: str = "",
    category_filter: str = "",
    search_text: str = "",
    category_column: str = "Branche",
) -> list[dict[str, str]]:
    """Apply case-insensitive city, category, and full-row text filters."""
    city_term = city_filter.strip().casefold()
    category_term = category_filter.strip().casefold()
    search_term = search_text.strip().casefold()
    filtered = []
    for row in rows:
        if city_term and city_term not in row.get("Stadt", "").casefold():
            continue
        if category_term and category_term not in row.get(category_column, "").casefold():
            continue
        if search_term and not any(
            search_term in str(value).casefold() for value in row.values()
        ):
            continue
        filtered.append(row)
    return filtered


def csv_bytes(rows: list[dict[str, str]], columns: list[str]) -> bytes:
    """Export rows as Excel-friendly UTF-8 CSV."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")
