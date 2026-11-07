"""Two-directory NRW dashboard for ReinigungsRadar.

Read-only Notion integration. Separate data sources:
- NOTION_DATA_SOURCE_ID: prospective private-sector customers
- PROVIDER_DATA_SOURCE_ID: cleaning/security service providers
"""
from __future__ import annotations

import os

from src.access_control import password_matches

import streamlit as st

from notion_reader import DEFAULT_DATA_SOURCE_ID, NotionAPIError, query_data_source
from directory_data import (
    CUSTOMER_COLUMNS,
    PROVIDER_COLUMNS,
    complete_rows,
    csv_bytes,
    filter_rows,
    pages_to_rows,
)

st.set_page_config(page_title="ReinigungsRadar NRW", page_icon="📒", layout="wide")

for secret_name in ("APP_PASSWORD", "NOTION_TOKEN", "NOTION_DATA_SOURCE_ID", "PROVIDER_DATA_SOURCE_ID", "NOTION_VERSION"):
    if not os.environ.get(secret_name):
        try:
            value = st.secrets.get(secret_name)
        except Exception:
            value = None
        if value:
            os.environ[secret_name] = str(value)


# Fail closed: the public staging service must not expose the dashboard without
# an explicitly configured shared access password.
APP_PASSWORD = os.environ.get("APP_PASSWORD", "").strip()
AUTH_KEY = "reinigungsradar_authenticated"

if not APP_PASSWORD:
    st.title("📒 ReinigungsRadar NRW")
    st.error(
        "Dashboard gesperrt: Das geschützte Render-Secret APP_PASSWORD fehlt. "
        "Bitte zuerst in Render als Secret konfigurieren."
    )
    st.stop()

if not st.session_state.get(AUTH_KEY, False):
    st.title("📒 ReinigungsRadar NRW")
    st.caption("Geschützter Staging-Zugang")
    with st.form("reinigungsradar_login"):
        entered_password = st.text_input("Zugangspasswort", type="password")
        login_submitted = st.form_submit_button("Anmelden")
    if login_submitted:
        if password_matches(entered_password, APP_PASSWORD):
            st.session_state[AUTH_KEY] = True
            st.rerun()
        else:
            st.error("Das Zugangspasswort ist nicht korrekt.")
    st.stop()

st.title("📒 ReinigungsRadar NRW")
st.caption(
    "Zwei getrennte Firmenverzeichnisse · NRW-Zielgebiet · vorhandener Pilotdatenbestand "
    "aktuell mit Schwerpunkt Mönchengladbach"
)
st.info(
    "Interner MVP mit read-only Notion-Anbindung. Keine automatische Kontaktaufnahme "
    "und keine Änderung an Notion-Datensätzen."
)
st.warning(
    "APP_PASSWORD bietet nur einen gemeinsamen Staging-Zugang und ersetzt keine "
    "produktive Benutzerverwaltung. Vor echten personenbezogenen Daten müssen "
    "individuelle Zugriffe, Mandantentrennung und Datenschutz geprüft sein. "
    "Öffentliche Kontaktdaten sind keine Einwilligung für Werbeansprache."
)

with st.sidebar:
    if st.button("Abmelden"):
        st.session_state[AUTH_KEY] = False
        st.rerun()
    st.header("Filter")
    st.text_input("Bundesland", value="Nordrhein-Westfalen (NRW)", disabled=True)
    city_filter = st.text_input("Stadt enthält", placeholder="z. B. Viersen")
    category_filter = st.text_input("Branche / Dienstleistung enthält")
    search_text = st.text_input("Freitextsuche", placeholder="Firma, Ort, Website …")

def property_text(prop):
    if not isinstance(prop, dict):
        return str(prop).strip() if prop is not None else ""
    for key in ("title", "rich_text", "multi_select"):
        items = prop.get(key)
        if isinstance(items, list):
            parts = []
            for item in items:
                if isinstance(item, dict):
                    parts.append(str(item.get("plain_text") or item.get("name") or ""))
            return "; ".join(part for part in parts if part)
    for key in ("url", "email", "phone_number", "number"):
        if prop.get(key) is not None:
            return str(prop[key]).strip()
    for key in ("select", "status"):
        selected = prop.get(key)
        if isinstance(selected, dict):
            return str(selected.get("name") or "")
    return ""

def pages_to_rows(pages):
    rows = []
    for page in pages:
        props = page.get("properties", {})
        row = {name: property_text(value) for name, value in props.items()}
        if row.get("Unternehmen", "").strip():
            rows.append(row)
    return rows

def complete_rows(rows, columns):
    result = []
    for row in rows:
        result.append({column: str(row.get(column) or "") for column in columns})
    return result

def filter_rows(rows, columns, category_column):
    filtered = []
    for row in rows:
        if city_filter and city_filter.casefold() not in row.get("Stadt", "").casefold():
            continue
        if category_filter and category_filter.casefold() not in row.get(category_column, "").casefold():
            continue
        if search_text and not any(search_text.casefold() in str(value).casefold() for value in row.values()):
            continue
        filtered.append(row)
    return filtered

def csv_bytes(rows, columns):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")

if st.button("Beide Verzeichnisse laden", type="primary"):
    token = os.environ.get("NOTION_TOKEN", "").strip()
    customer_id = (os.environ.get("NOTION_DATA_SOURCE_ID") or DEFAULT_DATA_SOURCE_ID).strip()
    provider_id = os.environ.get("PROVIDER_DATA_SOURCE_ID", "").strip()

    st.session_state["customer_rows"] = []
    st.session_state["provider_rows"] = []

    if not token:
        st.error("NOTION_TOKEN fehlt. Bitte in Render unter Environment Variables konfigurieren.")
    else:
        errors = []
        customer_loaded = False
        provider_loaded = False
        with st.spinner("Lese beide getrennten Notion-Datenquellen …"):
            if customer_id:
                try:
                    customer_pages = query_data_source(customer_id)
                    st.session_state["customer_rows"] = pages_to_rows(customer_pages)
                    customer_loaded = True
                except NotionAPIError as exc:
                    errors.append(f"Kundenverzeichnis: {exc}")
            else:
                errors.append("NOTION_DATA_SOURCE_ID fehlt.")

            if provider_id:
                try:
                    provider_pages = query_data_source(provider_id)
                    st.session_state["provider_rows"] = pages_to_rows(provider_pages)
                    provider_loaded = True
                except NotionAPIError as exc:
                    errors.append(f"Anbieter-Verzeichnis: {exc}")
            else:
                errors.append("PROVIDER_DATA_SOURCE_ID fehlt.")

        for error in errors:
            st.error(f"Notion-Verbindung: {error}")

        if customer_loaded and provider_loaded and not errors:
            st.success(
                "Beide Datenquellen wurden erfolgreich und getrennt gelesen. "
                "Notion-Datensätze wurden nicht verändert."
            )
            st.caption(
                f"Kunden: {len(st.session_state['customer_rows'])} · "
                f"Anbieter: {len(st.session_state['provider_rows'])}"
            )
        elif customer_loaded or provider_loaded:
            st.warning(
                "Nur ein Teil der Datenquellen konnte geladen werden. "
                "Die erfolgreiche Liste bleibt verfügbar; Details stehen oben."
            )


customer_rows = st.session_state.get("customer_rows", [])
provider_rows = st.session_state.get("provider_rows", [])
customer_rows = complete_rows(customer_rows, CUSTOMER_COLUMNS)
provider_rows = complete_rows(provider_rows, PROVIDER_COLUMNS)

customer_tab, provider_tab, setup_tab = st.tabs([
    "🏢 Kundenverzeichnis", "🛡️ Anbieter-Verzeichnis", "⚙️ Datenquellen"
])

with customer_tab:
    st.subheader("Private Unternehmen mit möglichem Bedarf")
    st.caption(
        "Büros, Industrie, Handel, Hotels, Gastronomie, private Gesundheitsunternehmen, "
        "Immobilienverwaltung und weitere private Einrichtungen."
    )
    visible = filter_rows(
        customer_rows, city_filter, category_filter, search_text, "Branche"
    )
    st.metric("Kunden-Datensätze", len(customer_rows))
    st.dataframe(visible, use_container_width=True, hide_index=True)
    st.download_button(
        "Kundenverzeichnis als CSV exportieren",
        data=csv_bytes(visible, CUSTOMER_COLUMNS),
        file_name="reinigungsradar_nrw_kunden.csv",
        mime="text/csv",
        disabled=not visible,
    )
    if not (os.environ.get("NOTION_DATA_SOURCE_ID") or DEFAULT_DATA_SOURCE_ID).strip():
        st.warning("NOTION_DATA_SOURCE_ID ist nicht konfiguriert.")

with provider_tab:
    st.subheader("Anbieter für Reinigung und Security")
    st.caption("Eigenständiges Verzeichnis für Dienstleister, mögliche Partner und Marktübersicht.")
    visible = filter_rows(
        provider_rows, city_filter, category_filter, search_text, "Dienstleistung"
    )
    st.metric("Anbieter-Datensätze", len(provider_rows))
    st.dataframe(visible, use_container_width=True, hide_index=True)
    st.download_button(
        "Anbieter-Verzeichnis als CSV exportieren",
        data=csv_bytes(visible, PROVIDER_COLUMNS),
        file_name="reinigungsradar_nrw_anbieter.csv",
        mime="text/csv",
        disabled=not visible,
    )
    if not os.environ.get("PROVIDER_DATA_SOURCE_ID"):
        st.warning(
            "PROVIDER_DATA_SOURCE_ID fehlt. Das Anbieter-Verzeichnis ist noch nicht "
            "mit einer eigenen Notion-Datenbank verbunden."
        )

with setup_tab:
    st.subheader("Getrennte Notion-Datenbanken")
    st.markdown(
        "**Kundenverzeichnis**\n"
        "- Secret: `NOTION_DATA_SOURCE_ID`\n"
        "- Vorhandene Felder: Branche, Score, Potenzial, Status, Datenqualität, Prüfnotizen und nächste Schritte.\n\n"
        "**Anbieter-Verzeichnis**\n"
        "- Secret: `PROVIDER_DATA_SOURCE_ID`\n"
        "- Vorhandene Felder: Dienstleistung, Einsatzgebiet, Zertifikate / Erlaubnisse und Datenstatus.\n\n"
        "**Wichtiger Datenhinweis**\n"
        "- Der vorhandene Kundenbestand ist ein Mönchengladbach-Pilot und noch keine vollständige NRW-Abdeckung."
    )
    st.info(
        "Die App liest beide Datenquellen unabhängig voneinander und nur lesend. "
        "Leere Platzhalter-Datensätze werden ausgeblendet. Der aktuelle Bestand "
        "ist ein regionaler Pilot und noch keine vollständige NRW-Abdeckung. "
        "Quellen, Datenqualität und Prüfdatum bleiben sichtbar; fehlende Belege "
        "werden nicht als bestätigter Bedarf ausgegeben."
    )

st.caption(
    "ReinigungsRadar NRW · Kunden und Anbieter strikt getrennt · "
    "keine Ausschreibungssuche · keine automatische Kontaktaufnahme."
)
