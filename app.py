"""Two-directory NRW dashboard for ReinigungsRadar.

Read-only Notion integration. Separate data sources:
- NOTION_DATA_SOURCE_ID: prospective private-sector customers
- PROVIDER_DATA_SOURCE_ID: cleaning/security service providers
"""
from __future__ import annotations

import os
import re

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
from src.ted_search import TEDSearchError, search_active_notices
from src.company_search import (
    CUSTOMER_CATEGORIES,
    PROVIDER_CATEGORIES,
    CompanySearchError,
    search_companies,
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


@st.cache_data(ttl=21600, show_spinner=False)
def cached_company_search(city: str, mode: str, category: str, limit: int):
    """Cache on-demand OpenStreetMap discovery results for six hours."""
    return search_companies(city=city, mode=mode, category=category, limit=limit)


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

customer_tab, provider_tab, discovery_tab, tender_tab, setup_tab = st.tabs([
    "🏢 Kundenverzeichnis",
    "🛡️ Anbieter-Verzeichnis",
    "🔎 Neue Firmen finden",
    "📄 Ausschreibungen (TED)",
    "⚙️ Datenquellen",
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


with discovery_tab:
    st.subheader("Neue Firmen in NRW finden")
    st.caption(
        "On-Demand-Suche nach öffentlichen Firmen- und Standort-Einträgen in OpenStreetMap. "
        "Die Suche ergänzt den gespeicherten Notion-Bestand, ersetzt aber kein vollständiges Handelsregister."
    )
    st.info(
        "Wähle eine NRW-Stadt und eine Branche. Die Suche fragt OpenStreetMap live ab, "
        "zeigt Quelle und Prüfdatum und schreibt nichts nach Notion."
    )

    discovery_mode = st.radio(
        "Gesucht werden",
        ["Kunden", "Anbieter"],
        horizontal=True,
        key="discovery_mode",
    )
    category_options = (
        list(CUSTOMER_CATEGORIES.keys())
        if discovery_mode == "Kunden"
        else list(PROVIDER_CATEGORIES.keys())
    )
    with st.form("company_discovery_search"):
        discovery_city = st.text_input(
            "Stadt / Gemeinde in NRW",
            value="Mönchengladbach",
            max_chars=80,
            placeholder="z. B. Viersen, Köln, Düren oder Erkelenz",
        )
        discovery_category = st.selectbox("Branche / Dienstleistung", category_options)
        discovery_limit = st.slider("Maximale Treffer", min_value=10, max_value=100, value=60, step=10)
        discovery_submitted = st.form_submit_button(
            "Neue Firmen suchen",
            type="primary",
        )

    if discovery_submitted:
        st.session_state.pop("discovery_result", None)
        st.session_state.pop("discovery_error", None)
        try:
            with st.spinner(f"Suche öffentliche Einträge in {discovery_city} …"):
                st.session_state["discovery_result"] = cached_company_search(
                    discovery_city,
                    discovery_mode,
                    discovery_category,
                    int(discovery_limit),
                )
        except (CompanySearchError, ValueError) as exc:
            st.session_state["discovery_error"] = str(exc)

    discovery_error = st.session_state.get("discovery_error", "")
    discovery_result = st.session_state.get("discovery_result")
    if discovery_error:
        st.error(f"Firmensuche fehlgeschlagen: {discovery_error}")
    elif discovery_result:
        found_rows = discovery_result.get("rows", [])
        saved_rows = customer_rows if discovery_result.get("mode") == "Kunden" else provider_rows

        def match_key(value: str) -> str:
            return "".join(character for character in str(value).casefold() if character.isalnum())

        def website_key(value: str) -> str:
            return (
                str(value or "").strip().casefold()
                .removeprefix("https://")
                .removeprefix("http://")
                .removeprefix("www.")
                .rstrip("/")
            )

        saved_names = {match_key(row.get("Unternehmen", "")) for row in saved_rows}
        saved_websites = {website_key(row.get("Website", "")) for row in saved_rows if row.get("Website")}
        new_rows = [
            row for row in found_rows
            if match_key(row.get("Unternehmen", "")) not in saved_names
            and (not website_key(row.get("Website", "")) or website_key(row.get("Website", "")) not in saved_websites)
        ]
        duplicate_rows = [row for row in found_rows if row not in new_rows]

        metric_cols = st.columns(3)
        metric_cols[0].metric("Treffer aus OpenStreetMap", len(found_rows))
        metric_cols[1].metric("Neu gegenüber Notion", len(new_rows))
        metric_cols[2].metric("Bereits gespeichert", len(duplicate_rows))

        if new_rows:
            st.success(f"{len(new_rows)} neue, noch nicht im gewählten Notion-Verzeichnis erkannte Einträge gefunden.")
            discovery_columns = [
                "Unternehmen", "Branche / Typ", "Stadt", "Adresse", "PLZ",
                "Telefon", "E-Mail", "Website", "Quelle", "Quellenlink",
                "Prüfdatum", "Datenstatus",
            ]
            st.dataframe(new_rows, use_container_width=True, hide_index=True)
            st.download_button(
                "Neue Treffer als CSV exportieren",
                data=csv_bytes(new_rows, discovery_columns),
                file_name=f"reinigungsradar_neue_{discovery_result.get('mode', 'firmen').lower()}_{discovery_result.get('city', 'nrw').lower().replace(' ', '_')}.csv",
                mime="text/csv",
            )
        elif found_rows:
            st.warning("Es wurden Treffer gefunden, aber alle gleichen bereits vorhandenen Namen oder Websites im Notion-Verzeichnis.")
        else:
            st.warning("Für diese Stadt und Kategorie wurden keine passenden öffentlichen OpenStreetMap-Einträge gefunden.")

        if duplicate_rows:
            with st.expander("Bereits im Notion-Verzeichnis erkannte Einträge"):
                st.dataframe(duplicate_rows, use_container_width=True, hide_index=True)

        if discovery_result.get("source_timestamp"):
            st.caption(f"Stand der OpenStreetMap-Datenbank: {discovery_result['source_timestamp']}")
        st.caption(
            "Quelle: OpenStreetMap / Overpass API. Daten © OpenStreetMap contributors, "
            "Lizenz ODbL 1.0. Karteneinträge können unvollständig, veraltet oder falsch kategorisiert sein; "
            "Unternehmen und Kontaktdaten vor einer geschäftlichen Nutzung eigenständig prüfen."
        )
        st.markdown("[OpenStreetMap – Copyright und Lizenz](https://www.openstreetmap.org/copyright)")
        st.warning(
            "Ein öffentlich eingetragener Firmenkontakt ist keine Einwilligung zur Werbung. "
            "Datenschutz und rechtliche Voraussetzungen einer Kontaktaufnahme sind separat zu prüfen."
        )
    else:
        st.caption("Noch keine Suche ausgeführt. Die Suche wird nur auf Knopfdruck gestartet und sechs Stunden zwischengespeichert.")

with tender_tab:
    st.subheader("Aktive öffentliche Ausschreibungen in NRW")
    st.caption(
        "Quelle: TED – Tenders Electronic Daily. Suche nach aktiven Bekanntmachungen "
        "mit Leistungsort Nordrhein-Westfalen (NUTS-1-Code DEA)."
    )
    st.warning(
        "Dieser Suchlauf deckt nur TED ab. Vergabe.NRW, DTVP, service.bund.de "
        "und andere nationale Portale sind noch nicht angebunden. "
        "Eine TED-Bekanntmachung ist keine automatische Eignungs- oder Zuschlagsaussage."
    )

    with st.form("ted_tender_search"):
        tender_keyword = st.text_input(
            "Suchbegriff",
            value="Gebäudereinigung",
            max_chars=100,
            help="Zum Beispiel Gebäudereinigung, Unterhaltsreinigung oder Sicherheitsdienst.",
        )
        tender_limit = st.number_input(
            "Maximale Treffer",
            min_value=5,
            max_value=100,
            value=25,
            step=5,
        )
        tender_submitted = st.form_submit_button(
            "Aktive TED-Ausschreibungen suchen",
            type="primary",
        )

    if tender_submitted:
        st.session_state["ted_notices"] = []
        st.session_state["ted_search_error"] = ""
        st.session_state["ted_search_ran"] = True
        try:
            with st.spinner("Suche aktive TED-Bekanntmachungen für NRW …"):
                ted_result = search_active_notices(
                    tender_keyword,
                    limit=int(tender_limit),
                    region="NRW",
                )
            st.session_state["ted_notices"] = ted_result["notices"]
            st.session_state["ted_total"] = ted_result["total"]
            st.session_state["ted_query"] = ted_result["query"]
        except (TEDSearchError, ValueError) as exc:
            st.session_state["ted_search_error"] = str(exc)

    ted_error = st.session_state.get("ted_search_error", "")
    ted_notices = st.session_state.get("ted_notices", [])
    if ted_error:
        st.error(f"TED-Suche fehlgeschlagen: {ted_error}")
    elif ted_notices:
        st.success(
            f"{len(ted_notices)} Treffer geladen. "
            f"TED meldet insgesamt {st.session_state.get('ted_total', len(ted_notices))} passende aktive Bekanntmachungen."
        )
        for notice in ted_notices:
            publication_number = notice.get("publication_number") or "Ohne Veröffentlichungsnummer"
            title = notice.get("title") or "Ohne Titel"
            with st.expander(f"{publication_number} · {title}"):
                meta_cols = st.columns(3)
                meta_cols[0].caption("Auftraggeber")
                meta_cols[0].write(notice.get("buyer") or "Nicht angegeben")
                meta_cols[1].caption("Veröffentlicht")
                meta_cols[1].write(notice.get("publication_date") or "Nicht angegeben")
                meta_cols[2].caption("Frist")
                meta_cols[2].write(notice.get("deadline") or "Nicht angegeben")

                if notice.get("location"):
                    st.write(f"**Leistungsort:** {notice['location']}")
                if notice.get("description"):
                    st.markdown("**Leistungsbeschreibung**")
                    st.write(notice["description"])
                if notice.get("estimated_value"):
                    currency = notice.get("estimated_value_currency") or ""
                    st.write(f"**Geschätzter Auftragswert:** {notice['estimated_value']} {currency}".strip())
                if notice.get("cpv"):
                    st.write(f"**CPV:** {notice['cpv']}")
                if notice.get("procedure_type"):
                    st.write(f"**Verfahren:** {notice['procedure_type']}")

                if notice.get("selection_criteria"):
                    st.markdown("**Eignungskriterien**")
                    st.write(notice["selection_criteria"])
                if notice.get("exclusion_criteria"):
                    st.markdown("**Ausschlussgründe**")
                    st.write(notice["exclusion_criteria"])
                if notice.get("award_criteria"):
                    st.markdown("**Zuschlagskriterien**")
                    st.write(notice["award_criteria"])
                if notice.get("award_weights"):
                    st.write(f"**Gewichtung:** {notice['award_weights']}")

                contact_items = [
                    ("Kontaktstelle", notice.get("contact_point")),
                    ("Kontaktperson", notice.get("contact_person")),
                    ("E-Mail", notice.get("email")),
                    ("Telefon", notice.get("phone")),
                ]
                present_contacts = [(label, value) for label, value in contact_items if value]
                if present_contacts:
                    st.markdown("**Öffentliche Kontaktdaten der Vergabestelle**")
                    for label, value in present_contacts:
                        st.write(f"{label}: {value}")

                link_cols = st.columns(3)
                if notice.get("url", "").startswith("https://"):
                    link_cols[0].link_button("TED-Bekanntmachung", notice["url"])
                if notice.get("documents_url", "").startswith("https://"):
                    link_cols[1].link_button("Vergabeunterlagen", notice["documents_url"])
                if notice.get("submission_url", "").startswith("https://"):
                    link_cols[2].link_button("Einreichungsportal", notice["submission_url"])

                completeness = notice.get("completeness", {})
                st.caption(
                    f"Datenvollständigkeit: {completeness.get('present', 0)} von "
                    f"{completeness.get('total', 0)} Prüffeldern. "
                    "Fehlende Angaben stehen möglicherweise nur in den Originalunterlagen."
                )
                st.caption(notice.get("evidence_note", "Angaben anhand der Originalbekanntmachung prüfen."))
    elif st.session_state.get("ted_search_ran"):
        st.info("Für diesen Suchbegriff wurden in den aktiven TED-Bekanntmachungen keine Treffer zurückgegeben.")
    else:
        st.info("Suchbegriff eingeben und Suche starten. Es werden nur aktive Bekanntmachungen mit Leistungsort NRW abgefragt.")

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
        "- Der vorhandene Kundenbestand ist ein Mönchengladbach-Pilot und noch keine vollständige NRW-Abdeckung.\n\n"
        "**Ausschreibungen**\n"
        "- Aktive TED-Bekanntmachungen mit Leistungsort NRW; weitere Vergabeportale sind noch nicht integriert."
    )
    st.info(
        "Die App liest beide Datenquellen unabhängig voneinander und nur lesend. "
        "Leere Platzhalter-Datensätze werden ausgeblendet. Der aktuelle Bestand "
        "ist ein regionaler Pilot und noch keine vollständige NRW-Abdeckung. "
        "Quellen, Datenqualität und Prüfdatum bleiben sichtbar; fehlende Belege "
        "werden nicht als bestätigter Bedarf ausgegeben."
    )

st.caption(
    "ReinigungsRadar NRW · Kunden, Anbieter und TED-Ausschreibungen getrennt · "
    "read-only · keine automatische Kontaktaufnahme oder Angebotsabgabe."
)
