"""ReinigungsRadar 2.0 - analytics-first NRW market intelligence MVP.

The app is read-only: it queries two separate Notion data sources and never
creates, updates, or deletes Notion records. All metrics are derived from
loaded records; no demo values or synthetic company records are injected.
"""
from __future__ import annotations

import csv
import io
import os
import re
from collections import Counter

import pandas as pd
import streamlit as st

from notion_reader import DEFAULT_DATA_SOURCE_ID, NotionAPIError, query_data_source

st.set_page_config(
    page_title="ReinigungsRadar 2.0 | NRW Intelligence",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Resolve Streamlit secrets without exposing their values in the UI.
for secret_name in ("NOTION_TOKEN", "NOTION_DATA_SOURCE_ID", "PROVIDER_DATA_SOURCE_ID", "NOTION_VERSION"):
    if not os.environ.get(secret_name):
        try:
            secret_value = st.secrets.get(secret_name)
        except Exception:
            secret_value = None
        if secret_value:
            os.environ[secret_name] = str(secret_value)

CUSTOMER_COLUMNS = [
    "Unternehmen", "Branche / Einrichtung", "Stadt", "PLZ", "Adresse",
    "Telefon", "E-Mail", "Website", "Reinigungsbedarf", "Security-Bedarf",
    "Quelle", "Quellenlink", "Prüfdatum", "Datenstatus", "Potenzial",
    "Score", "Bewertungsgrundlage", "KI-Einschätzung", "Offene Informationen",
    "Prüfnotizen",
]
PROVIDER_COLUMNS = [
    "Unternehmen", "Dienstleistung", "Stadt", "PLZ", "Adresse",
    "Telefon", "E-Mail", "Website", "Einsatzgebiet", "Zertifikate / Erlaubnisse",
    "Quelle", "Quellenlink", "Prüfdatum", "Datenstatus", "Notizen",
]
ALIASES = {
    "Unternehmen": ("Unternehmen", "Name", "Firma"),
    "Branche / Einrichtung": ("Branche / Einrichtung", "Branche", "Industrie", "Kategorie"),
    "Dienstleistung": ("Dienstleistung", "Services", "Leistung", "Kategorie"),
    "Stadt": ("Stadt", "Ort", "City"),
    "PLZ": ("PLZ", "Postleitzahl", "ZIP"),
    "Adresse": ("Adresse", "Anschrift"),
    "Website": ("Website", "Webseite", "URL"),
    "Quelle": ("Quelle", "Quelle / Hinweis", "Source"),
    "Quellenlink": ("Quellenlink", "Quellenlink / URL", "Source URL"),
    "Prüfdatum": ("Prüfdatum", "Eingangsdatum", "Zuletzt geprüft"),
    "Datenstatus": ("Datenstatus", "Datenqualität", "Status"),
    "Score": ("Score", "Priorität", "Research Priority"),
    "Bewertungsgrundlage": ("Bewertungsgrundlage", "Potenzial", "Begründung"),
    "KI-Einschätzung": ("KI-Einschätzung", "Einschätzung"),
    "Prüfnotizen": ("Prüfnotizen", "Notizen"),
}


def property_text(prop: object) -> str:
    """Convert common Notion property payloads into readable strings."""
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
    for key in ("url", "email", "phone_number", "number", "checkbox"):
        if prop.get(key) is not None:
            return str(prop[key]).strip()
    for key in ("select", "status"):
        selected = prop.get(key)
        if isinstance(selected, dict):
            return str(selected.get("name") or "")
    date_value = prop.get("date")
    if isinstance(date_value, dict):
        return str(date_value.get("start") or "")
    return ""


def pages_to_rows(pages: list[dict], columns: list[str]) -> list[dict[str, str]]:
    """Normalize Notion page properties while retaining source field names."""
    rows = []
    for page in pages:
        properties = page.get("properties", {})
        raw = {name: property_text(value) for name, value in properties.items()}
        row = {}
        for column in columns:
            candidates = ALIASES.get(column, (column,))
            row[column] = next((raw[key] for key in candidates if raw.get(key)), "")
        if not row.get("Unternehmen"):
            # Some databases use a non-standard title-property name.
            for name, value in properties.items():
                if isinstance(value, dict) and isinstance(value.get("title"), list):
                    row["Unternehmen"] = property_text(value)
                    break
        if row.get("Unternehmen"):
            rows.append(row)
    return rows


def filter_rows(rows: list[dict], city: str, category: str, query: str, category_field: str) -> list[dict]:
    filtered = []
    for row in rows:
        if city and city.casefold() not in row.get("Stadt", "").casefold():
            continue
        if category and category.casefold() not in row.get(category_field, "").casefold():
            continue
        if query and not any(query.casefold() in str(value).casefold() for value in row.values()):
            continue
        filtered.append(row)
    return filtered


def csv_bytes(rows: list[dict], columns: list[str]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def parse_score(value: str) -> float | None:
    """Parse numeric score forms such as '4', '4/5' or '4 von 5'."""
    if not value:
        return None
    match = re.search(r"\d+(?:[.,]\d+)?", value)
    if not match:
        return None
    try:
        return float(match.group().replace(",", "."))
    except ValueError:
        return None


def completeness(rows: list[dict], fields: tuple[str, ...]) -> float:
    if not rows:
        return 0.0
    populated = sum(bool(row.get(field, "").strip()) for row in rows for field in fields)
    return populated / (len(rows) * len(fields)) * 100


def count_values(rows: list[dict], field: str) -> dict[str, int]:
    values = [row.get(field, "").strip() or "Nicht angegeben" for row in rows]
    return dict(Counter(values).most_common(12))


def chart_frame(counts: dict[str, int]) -> pd.DataFrame:
    """Build a labelled frame for Streamlit charts, including empty states."""
    return pd.DataFrame({"Kategorie": list(counts.keys()), "Anzahl": list(counts.values())})


def render_directory(rows: list[dict], columns: list[str], filename: str, label: str) -> None:
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.download_button(
        f"{label} als CSV exportieren",
        data=csv_bytes(rows, columns),
        file_name=filename,
        mime="text/csv",
        disabled=not rows,
        use_container_width=False,
    )


st.markdown(
    """
    <style>
    .block-container {padding-top: 1.5rem; padding-bottom: 2.5rem; max-width: 1500px;}
    [data-testid="stMetric"] {background: var(--secondary-background-color); padding: 14px 16px; border-radius: 12px;}
    div[data-testid="stMetricValue"] {font-size: 1.8rem;}
    .rr-eyebrow {font-size: .75rem; letter-spacing: .12em; color: #8492a6; font-weight: 700;}
    </style>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("## 📡 ReinigungsRadar")
    st.caption("2.0 · MARKET INTELLIGENCE")
    st.divider()
    st.markdown("**Datenbereich**")
    st.text_input("Bundesland", value="Nordrhein-Westfalen", disabled=True)
    city_filter = st.text_input("Stadt", placeholder="Alle NRW-Städte")
    category_filter = st.text_input("Branche / Dienstleistung", placeholder="z. B. Industrie")
    search_text = st.text_input("Freitext", placeholder="Firma, PLZ, Website …")
    st.divider()
    if st.button("↻ Daten aus Notion laden", type="primary", use_container_width=True):
        token = os.environ.get("NOTION_TOKEN", "").strip()
        customer_id = (os.environ.get("NOTION_DATA_SOURCE_ID") or DEFAULT_DATA_SOURCE_ID).strip()
        provider_id = os.environ.get("PROVIDER_DATA_SOURCE_ID", "").strip()
        if not token:
            st.session_state["load_error"] = "NOTION_TOKEN fehlt. Bitte als geschütztes Streamlit Secret hinterlegen."
        else:
            try:
                with st.spinner("Lese beide Notion-Verzeichnisse …"):
                    customer_pages = query_data_source(customer_id)
                    provider_pages = query_data_source(provider_id) if provider_id else []
                st.session_state["customer_rows"] = pages_to_rows(customer_pages, CUSTOMER_COLUMNS)
                st.session_state["provider_rows"] = pages_to_rows(provider_pages, PROVIDER_COLUMNS)
                st.session_state["load_error"] = ""
                st.session_state["last_loaded"] = f"{len(customer_pages)} Kunden-Seiten · {len(provider_pages)} Anbieter-Seiten"
            except NotionAPIError as exc:
                st.session_state["load_error"] = str(exc)
    if st.session_state.get("last_loaded"):
        st.caption("Letzter Ladevorgang")
        st.caption(st.session_state["last_loaded"])
    if st.session_state.get("load_error"):
        st.error(st.session_state["load_error"])
    st.divider()
    st.caption("Read-only · kein automatischer Outreach")

customer_rows = st.session_state.get("customer_rows", [])
provider_rows = st.session_state.get("provider_rows", [])
customers = filter_rows(customer_rows, city_filter, category_filter, search_text, "Branche / Einrichtung")
providers = filter_rows(provider_rows, city_filter, category_filter, search_text, "Dienstleistung")

st.markdown('<div class="rr-eyebrow">NRW · OPPORTUNITY & MARKET INTELLIGENCE</div>', unsafe_allow_html=True)
st.title("ReinigungsRadar 2.0")
st.caption("Markt verstehen. Potenziale erkennen. Entscheidungen mit nachvollziehbaren Belegen treffen.")
st.info(
    "Interner MVP mit read-only Notion-Anbindung. Öffentliche Kontaktdaten sind keine "
    "Einwilligung zur Werbeansprache. Vor produktiver Nutzung mit personenbezogenen Daten "
    "sind Zugriffsschutz, Mandantentrennung und Datenschutzprüfung erforderlich.",
    icon="🔒",
)

overview, opportunities, customers_tab, providers_tab, market, quality, sources = st.tabs([
    "◈ Overview", "◎ Opportunity Explorer", "▦ Kunden", "⬡ Anbieter",
    "⌁ Marktanalyse", "✓ Datenqualität", "⚙ Datenquellen",
])

with overview:
    st.subheader("Marktüberblick")
    st.caption("Alle Kennzahlen werden aus den aktuell geladenen Datensätzen berechnet.")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Kunden-Datensätze", len(customer_rows))
    k2.metric("Anbieter-Datensätze", len(provider_rows))
    scored = [parse_score(row.get("Score", "")) for row in customers]
    scored_values = [score for score in scored if score is not None]
    k3.metric("Bewertete Kunden", len(scored_values))
    source_complete = sum(bool(row.get("Quellenlink") or row.get("Quelle")) for row in customer_rows)
    k4.metric("Kunden mit Quellenhinweis", source_complete, help="Mindestens Quellenname oder Quellenlink vorhanden.")
    left, right = st.columns([1.25, 1])
    with left:
        st.markdown("#### Kunden nach Branche")
        industry_counts = count_values(customers, "Branche / Einrichtung")
        if industry_counts:
            st.bar_chart(chart_frame(industry_counts), x="Kategorie", y="Anzahl", horizontal=True, height=330)
        else:
            st.info("Noch keine Kundendaten geladen oder für diese Filter gefunden.")
    with right:
        st.markdown("#### Datenabdeckung")
        coverage = {
            "Website": completeness(customer_rows, ("Website",)),
            "Quelle": completeness(customer_rows, ("Quelle", "Quellenlink")),
            "Ort": completeness(customer_rows, ("Stadt", "PLZ")),
            "Prüfdatum": completeness(customer_rows, ("Prüfdatum",)),
        }
        st.bar_chart(chart_frame(coverage), x="Kategorie", y="Anzahl", horizontal=True, height=260)
        st.caption("Vollständigkeit der vorhandenen Felder, keine Aussage über sachliche Richtigkeit.")
    st.markdown("#### Zuletzt geladene Kunden")
    if customers:
        preview_cols = ["Unternehmen", "Branche / Einrichtung", "Stadt", "Datenstatus", "Prüfdatum"]
        st.dataframe([{key: row.get(key, "") for key in preview_cols} for row in customers[:8]], hide_index=True, use_container_width=True)
    else:
        st.info("Über „Daten aus Notion laden“ in der Seitenleiste die vorhandenen Daten einlesen.")

with opportunities:
    st.subheader("Opportunity Explorer")
    st.caption("Priorisierung zur Recherche, keine Vorhersage eines Vertragsabschlusses.")
    scored_rows = []
    for row in customers:
        score = parse_score(row.get("Score", ""))
        if score is not None:
            scored_rows.append({**row, "_score": score})
    if scored_rows:
        scored_rows.sort(key=lambda item: item["_score"], reverse=True)
        st.caption(f"{len(scored_rows)} Datensätze mit einem lesbaren Score im aktuellen Filter.")
        for row in scored_rows:
            with st.container(border=True):
                top_a, top_b = st.columns([3, 1])
                top_a.markdown(f"**{row.get('Unternehmen') or 'Unternehmen ohne Namen'}**")
                top_a.caption(" · ".join(part for part in (row.get("Stadt", ""), row.get("Branche / Einrichtung", "")) if part))
                top_b.metric("Recherche-Score", row["_score"])
                reason = row.get("Bewertungsgrundlage") or row.get("KI-Einschätzung") or row.get("Potenzial")
                st.write(reason or "Keine Bewertungsgrundlage hinterlegt.")
                evidence = row.get("Quellenlink") or row.get("Quelle")
                if evidence:
                    st.caption(f"Quelle: {evidence}")
                st.caption(f"Status: {row.get('Datenstatus') or 'Nicht angegeben'} · Prüfdatum: {row.get('Prüfdatum') or 'Nicht angegeben'}")
    elif customers:
        st.warning("Für diese Datensätze ist noch kein auswertbarer Score hinterlegt. Es wird kein Score erfunden.")
        st.dataframe(customers, use_container_width=True, hide_index=True)
    else:
        st.info("Nach dem Laden der Kundendaten erscheinen hier bewertete Recherche-Kandidaten.")

with customers_tab:
    st.subheader("Kundenverzeichnis")
    st.caption("Private Unternehmen und Einrichtungen mit möglichem Bedarf an Reinigung oder Sicherheitsdiensten.")
    st.metric("Treffer im aktuellen Filter", len(customers))
    render_directory(customers, CUSTOMER_COLUMNS, "reinigungsradar_nrw_kunden.csv", "Kundenverzeichnis")

with providers_tab:
    st.subheader("Anbieter-Verzeichnis")
    st.caption("Getrenntes Marktverzeichnis für Reinigungs- und Sicherheitsdienstleister.")
    st.metric("Treffer im aktuellen Filter", len(providers))
    render_directory(providers, PROVIDER_COLUMNS, "reinigungsradar_nrw_anbieter.csv", "Anbieter-Verzeichnis")
    if not os.environ.get("PROVIDER_DATA_SOURCE_ID", "").strip():
        st.warning("PROVIDER_DATA_SOURCE_ID fehlt. Das Anbieter-Verzeichnis ist noch nicht mit einer eigenen Notion-Datenbank verbunden.")

with market:
    st.subheader("Marktanalyse")
    st.caption("Deskriptive Auswertung der geladenen Datensätze; keine Hochrechnung auf den Gesamtmarkt.")
    m1, m2 = st.columns(2)
    with m1:
        st.markdown("#### Kunden nach Stadt")
        city_counts = count_values(customers, "Stadt")
        if city_counts:
            st.bar_chart(chart_frame(city_counts), x="Kategorie", y="Anzahl", horizontal=True, height=320)
        else:
            st.info("Keine Kundendaten für die aktuelle Auswahl.")
    with m2:
        st.markdown("#### Anbieter nach Dienstleistung")
        service_counts = count_values(providers, "Dienstleistung")
        if service_counts:
            st.bar_chart(chart_frame(service_counts), x="Kategorie", y="Anzahl", horizontal=True, height=320)
        else:
            st.info("Noch keine Anbieterdaten geladen. Eine eigene Anbieter-Datenquelle muss verbunden werden.")
    st.markdown("#### Regionale Abdeckung")
    known_cities = sorted({row.get("Stadt", "").strip() for row in customer_rows + provider_rows if row.get("Stadt", "").strip()})
    if known_cities:
        st.write(", ".join(known_cities))
    else:
        st.info("Stadtangaben sind noch nicht vorhanden.")

with quality:
    st.subheader("Datenqualität & Nachvollziehbarkeit")
    st.caption("Vollständigkeit ist nicht gleich Richtigkeit. Jede Quelle muss separat geprüft werden.")
    q1, q2 = st.columns(2)
    with q1:
        st.markdown("#### Kunden")
        st.metric("Vollständigkeit: Quelle + URL", f"{completeness(customer_rows, ('Quelle', 'Quellenlink')):.0f}%")
        st.metric("Vollständigkeit: Ort + PLZ", f"{completeness(customer_rows, ('Stadt', 'PLZ')):.0f}%")
        missing_source = [row.get("Unternehmen", "") for row in customer_rows if not row.get("Quelle") and not row.get("Quellenlink")]
        if missing_source:
            st.warning(f"{len(missing_source)} Kundendatensätze ohne Quellenangabe")
            st.write(", ".join(missing_source[:20]))
    with q2:
        st.markdown("#### Anbieter")
        st.metric("Vollständigkeit: Quelle + URL", f"{completeness(provider_rows, ('Quelle', 'Quellenlink')):.0f}%")
        st.metric("Vollständigkeit: Ort + PLZ", f"{completeness(provider_rows, ('Stadt', 'PLZ')):.0f}%")
        missing_provider_source = [row.get("Unternehmen", "") for row in provider_rows if not row.get("Quelle") and not row.get("Quellenlink")]
        if missing_provider_source:
            st.warning(f"{len(missing_provider_source)} Anbieterdatensätze ohne Quellenangabe")
            st.write(", ".join(missing_provider_source[:20]))
    st.markdown("#### Qualitätsstatus")
    status_counts = count_values(customer_rows + provider_rows, "Datenstatus")
    if status_counts:
        st.bar_chart(chart_frame(status_counts), x="Kategorie", y="Anzahl", horizontal=True)
    else:
        st.info("Noch keine Datenstatus-Angaben vorhanden.")

with sources:
    st.subheader("Datenquellen & Systemstatus")
    token_present = bool(os.environ.get("NOTION_TOKEN", "").strip())
    customer_id = (os.environ.get("NOTION_DATA_SOURCE_ID") or DEFAULT_DATA_SOURCE_ID).strip()
    provider_id = os.environ.get("PROVIDER_DATA_SOURCE_ID", "").strip()
    s1, s2, s3 = st.columns(3)
    s1.metric("Notion Token", "Verbunden" if token_present else "Fehlt")
    s2.metric("Kundenquelle", "Konfiguriert" if customer_id else "Fehlt")
    s3.metric("Anbieterquelle", "Konfiguriert" if provider_id else "Fehlt")
    st.markdown("**Kundenverzeichnis**")
    st.code("NOTION_DATA_SOURCE_ID", language="text")
    st.markdown("**Anbieter-Verzeichnis**")
    st.code("PROVIDER_DATA_SOURCE_ID", language="text")
    st.info(
        "Die App liest Notion ausschließlich. Sie erstellt keine Datenbanken und verändert keine Datensätze. "
        "Die Anbieterquelle ist optional, bis eine separate Notion-Datenbank angelegt und freigegeben wurde."
    )

st.divider()
st.caption("ReinigungsRadar 2.0 · NRW · Read-only · Keine automatische Kontaktaufnahme · Keine öffentlichen Ausschreibungsdaten")
