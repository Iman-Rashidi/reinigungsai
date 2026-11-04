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
    "Gebäudetyp", "Reinigungsbedarf", "Security-Bedarf", "Bedarfsbelege",
    "Aktueller Anbieter", "Beschaffungsweg", "Standorte", "Bedarfs-Prüfdatum",
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
    "Gebäudetyp": ("Gebäudetyp", "Objekttyp", "Gebäudeart"),
    "Reinigungsbedarf": ("Reinigungsbedarf", "Cleaning Need", "Reinigungsleistungen"),
    "Security-Bedarf": ("Security-Bedarf", "Sicherheitsbedarf", "Security Need"),
    "Bedarfsbelege": ("Bedarfsbelege", "Need Evidence", "Nachweis Bedarf"),
    "Aktueller Anbieter": ("Aktueller Anbieter", "Bestehender Dienstleister", "Current Provider"),
    "Beschaffungsweg": ("Beschaffungsweg", "Einkauf / Vergabe", "Procurement Route"),
    "Standorte": ("Standorte", "Anzahl Standorte", "Locations"),
    "Bedarfs-Prüfdatum": ("Bedarfs-Prüfdatum", "Need Review Date"),
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



# Transparent, rule-based need hypotheses. These rules never claim that a
# company has a confirmed need merely because of its industry.
NEED_RULES = [
    (("industrie", "produktion", "fertigung", "werk", "fabrik", "maschinenbau"),
     ["Industriereinigung (zu prüfen)", "Unterhaltsreinigung für Büro-/Sozialflächen", "Glas- und Fassadenreinigung (objektabhängig)"],
     ["Gebäudeflächen und Produktionsbereiche", "Reinigungsintervalle und Sicherheitsvorgaben", "interne oder externe Leistungserbringung"]),
    (("büro", "businesspark", "business park", "coworking", "verwaltung", "bürogebäude"),
     ["Büro- und Unterhaltsreinigung", "Glasreinigung", "Grundreinigung (periodisch)"],
     ["Nutzfläche und Belegungsgrad", "Reinigungsfrequenz", "Hausverwaltung oder Facility Management"]),
    (("einzelhandel", "handel", "shopping", "center", "markt", "möbelhaus", "kaufhaus"),
     ["Reinigung von Verkaufs- und Gemeinschaftsflächen", "Glas- und Eingangsbereichreinigung", "Grundreinigung außerhalb der Öffnungszeiten"],
     ["Öffnungszeiten und Publikumsverkehr", "Anzahl und Größe der Verkaufsflächen", "interne oder externe Reinigung"]),
    (("hotel", "gastronomie", "restaurant", "übernachtung"),
     ["Reinigung öffentlicher und interner Flächen", "Glasreinigung", "Sonderreinigung nach Bedarf"],
     ["Zimmer-/Flächenumfang", "Reinigungsorganisation und Spitzenzeiten", "Hygiene- und Qualitätsvorgaben"]),
    (("klinik", "krankenhaus", "medizin", "gesundheit", "pflege"),
     ["Reinigung sensibler Bereiche (fachlich und regulatorisch zu prüfen)", "Unterhaltsreinigung öffentlicher/administrativer Flächen", "Zutritts- und Objektschutz (objektabhängig)"],
     ["Bereichsspezifische Hygieneanforderungen", "Qualifikationen und Nachweise", "Zutritts- und Sicherheitskonzept"]),
    (("logistik", "lager", "distribution", "versand"),
     ["Reinigung von Lager- und Verkehrsflächen", "Unterhaltsreinigung von Büro-/Sozialflächen", "Objektschutz und Zutrittskontrolle (objektabhängig)"],
     ["Lager- und Verkehrsflächen", "Schichtbetrieb und Betriebszeiten", "Sicherheits- und Zutrittsanforderungen"]),
]

def analyze_company_needs(row: dict) -> dict:
    """Return explainable service hypotheses and gaps, not a sales-probability prediction."""
    industry = " ".join((row.get("Branche / Einrichtung", ""), row.get("Gebäudetyp", ""))).casefold()
    explicit_cleaning = row.get("Reinigungsbedarf", "").strip()
    explicit_security = row.get("Security-Bedarf", "").strip()
    candidates = []
    evidence_level = "Branchenbasierte Hypothese"
    if explicit_cleaning:
        candidates.extend(("Reinigung", item.strip()) for item in re.split(r"[;,\\n]+", explicit_cleaning) if item.strip())
        evidence_level = "Bedarf im Datensatz hinterlegt · Beleg prüfen"
    if explicit_security:
        candidates.extend(("Sicherheit", item.strip()) for item in re.split(r"[;,\\n]+", explicit_security) if item.strip())
        evidence_level = "Bedarf im Datensatz hinterlegt · Beleg prüfen"
    matched_rule = None
    for keywords, cleaning, gaps in NEED_RULES:
        if any(keyword in industry for keyword in keywords):
            matched_rule = (cleaning, gaps)
            if not explicit_cleaning:
                candidates.extend(("Reinigung", item) for item in cleaning)
            break
    if not explicit_security and matched_rule:
        if any(word in industry for word in ("klinik", "krankenhaus", "logistik", "lager", "center", "shopping", "hotel")):
            candidates.append(("Sicherheit", "Objektschutz / Zutrittskontrolle (nur bei konkretem Bedarf prüfen)"))
    if not matched_rule and not candidates:
        candidates = [("Reinigung", "Bedarf offen · Objekttyp und Flächennutzung zuerst ermitteln")]
    gaps = list(matched_rule[1]) if matched_rule else ["Gebäudetyp und Flächennutzung", "Flächenumfang und Reinigungsfrequenz", "Interne oder externe Leistungserbringung"]
    for field, label in (
        ("Bedarfsbelege", "konkreter Bedarfsbeleg"),
        ("Aktueller Anbieter", "aktueller Dienstleister"),
        ("Beschaffungsweg", "Beschaffungsweg / zuständige Stelle"),
        ("Standorte", "Standorte und Flächenumfang"),
    ):
        if not row.get(field, "").strip():
            gaps.append(label)
    return {
        "candidates": candidates,
        "gaps": list(dict.fromkeys(gaps)),
        "evidence_level": evidence_level,
        "evidence": row.get("Bedarfsbelege", "").strip(),
        "current_provider": row.get("Aktueller Anbieter", "").strip() or "Nicht bekannt",
        "procurement": row.get("Beschaffungsweg", "").strip() or "Nicht bekannt",
        "review_date": row.get("Bedarfs-Prüfdatum", "").strip() or "Nicht angegeben",
        "is_explicit": bool(explicit_cleaning or explicit_security),
    }


def provider_matches_for_need(need_label: str, city: str, providers: list[dict]) -> list[dict]:
    """Show only directory entries with a literal service/city overlap."""
    terms = [term for term in re.findall(r"[a-zäöüß]{5,}", need_label.casefold())
             if term not in {"(objektabhängig)", "(periodisch)", "prüfen", "bedarf"}]
    matches = []
    for provider in providers:
        service = provider.get("Dienstleistung", "").casefold()
        provider_city = provider.get("Stadt", "").casefold()
        city_ok = not city or not provider_city or city.casefold() in provider_city
        if city_ok and terms and any(term in service for term in terms):
            matches.append(provider)
    return matches[:5]


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
        provider_id = (os.environ.get("PROVIDER_DATA_SOURCE_ID") or "collection://78e8e33b-4989-41d7-a4bf-da76ea11271d").strip()
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

overview, opportunities, needs_tab, customers_tab, providers_tab, market, quality, sources = st.tabs([
    "◈ Overview", "◎ Opportunity Explorer", "⌖ Bedarfsanalyse", "▦ Kunden", "⬡ Anbieter",
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
    need_candidates = sum(bool(analyze_company_needs(row)["candidates"]) for row in customers)
    st.metric("Kunden mit analysierbaren Bedarfshypothesen", need_candidates, help="Branchenbasierte Hypothesen, keine bestätigten Bedarfe.")
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


with needs_tab:
    st.subheader("Bedarfsanalyse · Need Intelligence")
    st.caption("Branchenwissen erzeugt Hypothesen. Ein bestätigter Bedarf erfordert einen konkreten, datierten Beleg oder eine Bestätigung des Unternehmens.")
    need_rows = customers
    explicit_count = sum(bool(row.get("Reinigungsbedarf") or row.get("Security-Bedarf")) for row in need_rows)
    hypothesis_count = sum(bool(analyze_company_needs(row)["candidates"]) for row in need_rows)
    n1, n2, n3 = st.columns(3)
    n1.metric("Unternehmen im Filter", len(need_rows))
    n2.metric("Bedarf im Datensatz hinterlegt", explicit_count)
    n3.metric("Profile mit Analyse-Hypothese", hypothesis_count)
    st.warning("Eine Branchenzuordnung ist kein Nachweis eines tatsächlichen Bedarfs, eines Budgets oder einer Wechselabsicht. Unbekannte Angaben bleiben ausdrücklich offen.")
    if not need_rows:
        st.info("Zuerst Kundendaten aus Notion laden oder Filter anpassen.")
    else:
        for row in need_rows:
            analysis = analyze_company_needs(row)
            with st.expander(f"{row.get('Unternehmen') or 'Unternehmen'} · {row.get('Stadt') or 'Ort unbekannt'}", expanded=False):
                a, b = st.columns([1.25, 1])
                with a:
                    st.markdown("**Mögliche passende Leistungen**")
                    for group, service in analysis["candidates"]:
                        st.markdown(f"- **{group}:** {service}")
                    st.caption(f"Grundlage: {analysis['evidence_level']}")
                    if analysis["evidence"]:
                        st.markdown("**Hinterlegte Belege**")
                        st.write(analysis["evidence"])
                    else:
                        st.info("Kein konkreter Bedarfsbeleg im Datensatz hinterlegt.")
                    st.markdown("**Aktueller Anbieter:** " + analysis["current_provider"])
                    st.markdown("**Beschaffungsweg:** " + analysis["procurement"])
                with b:
                    st.markdown("**Was vor einer Kooperation zu klären ist**")
                    for gap in analysis["gaps"]:
                        st.markdown(f"- {gap}")
                    st.caption("Bedarfsanalyse zuletzt geprüft: " + analysis["review_date"])
                st.markdown("**Passende Anbieter im Verzeichnis (nur Text-/Ortsübereinstimmung)**")
                shown = 0
                for group, service in analysis["candidates"]:
                    for provider in provider_matches_for_need(service, row.get("Stadt", ""), providers):
                        st.write(f"- {provider.get('Unternehmen')} · {provider.get('Dienstleistung')} · {provider.get('Stadt')}")
                        shown += 1
                if not shown:
                    st.caption("Kein passender Eintrag über die vorhandenen Dienstleistungs- und Ortsangaben gefunden. Das bedeutet nicht, dass es keine Anbieter gibt.")
                st.markdown("**Empfohlener nächster Recherche-Schritt**")
                if not analysis["evidence"]:
                    st.write("Offizielle Unternehmensseite und öffentliche Objektinformationen prüfen; einen konkreten Beleg für einen ausgeschriebenen oder kommunizierten Bedarf suchen.")
                elif not analysis["current_provider"] or analysis["current_provider"] == "Nicht bekannt":
                    st.write("Zuständige Einkaufs-, Facility-Management- oder Objektleitung und den offiziellen Kooperationsweg recherchieren.")
                else:
                    st.write("Anforderungen, Leistungsumfang und zulässigen Weg zur Angebotsabgabe anhand der Unternehmensangaben prüfen.")
    st.markdown("#### Export der Bedarfsanalyse")
    if need_rows:
        need_export = []
        for row in need_rows:
            analysis = analyze_company_needs(row)
            need_export.append({
                "Unternehmen": row.get("Unternehmen", ""),
                "Stadt": row.get("Stadt", ""),
                "Branche": row.get("Branche / Einrichtung", ""),
                "Bedarfshypothesen": " | ".join(f"{group}: {service}" for group, service in analysis["candidates"]),
                "Bedarfsstatus": analysis["evidence_level"],
                "Bedarfsbelege": analysis["evidence"],
                "Aktueller Anbieter": analysis["current_provider"],
                "Beschaffungsweg": analysis["procurement"],
                "Offene Fragen": " | ".join(analysis["gaps"]),
                "Prüfdatum": analysis["review_date"],
                "Quellenlink": row.get("Quellenlink", ""),
            })
        st.download_button("Bedarfsanalyse als CSV exportieren", csv_bytes(need_export, list(need_export[0].keys())), "reinigungsradar_bedarfsanalyse.csv", "text/csv")

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
    provider_id = (os.environ.get("PROVIDER_DATA_SOURCE_ID") or "collection://78e8e33b-4989-41d7-a4bf-da76ea11271d").strip()
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
