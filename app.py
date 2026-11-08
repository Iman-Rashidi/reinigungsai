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
from src.lead_discovery import (
    LEAD_CATEGORIES,
    LeadDiscoveryError,
    build_manual_portal_links,
    search_public_leads,
)
from src.company_search import (
    CUSTOMER_CATEGORIES,
    PROVIDER_CATEGORIES,
    CompanySearchError,
    search_companies,
)
from src.opportunity_engine.dashboard import render_opportunity_engine_tab

st.set_page_config(page_title="ReinigungsRadar NRW", page_icon="📒", layout="wide")

for secret_name in ("APP_PASSWORD", "NOTION_TOKEN", "NOTION_DATA_SOURCE_ID", "PROVIDER_DATA_SOURCE_ID", "NOTION_VERSION"):
    if not os.environ.get(secret_name):
        try:
            value = st.secrets.get(secret_name)
        except Exception:
            value = None
        if value:
            os.environ[secret_name] = str(value)


@st.cache_data(ttl=1800, show_spinner=False)
def cached_company_search(city: str, mode: str, category: str, limit: int):
    """Cache city-specific live search results for at most 30 minutes."""
    return search_companies(city=city, mode=mode, category=category, limit=limit)

@st.cache_data(ttl=1800, show_spinner=False)
def cached_public_lead_search(city: str, category: str, extra_terms: str, limit: int):
    """Cache indexed public-web opportunity signals for at most 30 minutes."""
    return search_public_leads(
        city=city,
        category=category,
        extra_terms=extra_terms,
        limit=limit,
    )


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

customer_tab, provider_tab, discovery_tab, lead_radar_tab, opportunity_engine_tab, tender_tab, setup_tab = st.tabs([
    "🏢 Kundenverzeichnis",
    "🛡️ Anbieter-Verzeichnis",
    "🔎 Neue Firmen finden",
    "🌐 Job- & Projekt-Radar",
    "🧭 Opportunity Engine",
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
    google_places_enabled = bool(os.environ.get("GOOGLE_MAPS_API_KEY", "").strip())
    if google_places_enabled:
        st.caption(
            "Live-Firmensuche über Google Maps / Places API. Treffer enthalten die von Google "
            "ermittelte Adresse, Stadt und den direkten Maps-Link."
        )
        st.info("Die Suche ist stadtbezogen. Quelle und Prüfdatum werden pro Treffer angezeigt; Notion bleibt unverändert.")
    else:
        st.caption(
            "Live-Firmensuche über OpenStreetMap / Overpass. Für Google Maps muss "
            "GOOGLE_MAPS_API_KEY als geschütztes Render-Secret eingerichtet werden."
        )
        st.warning(
            "Google Maps ist noch nicht aktiviert. Aktuell läuft die Suche über OpenStreetMap; "
            "die Trefferqualität und Adressabdeckung können je nach Stadt variieren."
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

        contact_ready_rows = [
            row for row in new_rows
            if row.get("E-Mail", "").strip() and row.get("Telefon", "").strip()
        ]
        procurement_terms = re.compile(
            r"einkauf|beschaffung|vergabe|vertrags|facility|objektleitung|"
            r"kaufmännisch|leitung|geschäftsführ|procurement|contract",
            re.IGNORECASE,
        )
        for row in new_rows:
            role = row.get("Funktion Ansprechpartner", "")
            person = row.get("Ansprechpartner", "")
            has_full_contact = bool(row.get("E-Mail", "").strip() and row.get("Telefon", "").strip())
            row["Kontaktstatus"] = (
                "E-Mail + Telefon vorhanden" if has_full_contact
                else "Kontaktdaten unvollständig – ergänzen"
            )
            row["Priorität"] = (
                "⭐ GOLD – Ansprechpartner für Vergabe/Verträge erkennbar"
                if has_full_contact and person and role and procurement_terms.search(role)
                else "Standard – Kontaktdaten vollständig" if has_full_contact
                else "Noch zu prüfen"
            )
        gold_rows = [row for row in contact_ready_rows if row["Priorität"].startswith("⭐ GOLD")]
        st.caption(
            "Alle neuen Firmennamen werden angezeigt – auch wenn E-Mail oder Telefonnummer fehlen. "
            "Der Kontaktstatus wird separat markiert. ⭐ GOLD gibt es nur bei ausdrücklich genanntem "
            "Ansprechpartner und einer passenden Funktionsangabe zu Einkauf, Vergabe, Verträgen oder Objektleitung."
        )

        metric_cols = st.columns(4)
        metric_cols[0].metric("Treffer insgesamt", len(found_rows))
        metric_cols[1].metric("Neue Firmen mit E-Mail + Telefon", len(contact_ready_rows))
        metric_cols[2].metric("⭐ Gold-Priorität", len(gold_rows))
        metric_cols[3].metric("Bereits gespeichert", len(duplicate_rows))

        if new_rows:
            if contact_ready_rows:
                st.success(
                    f"{len(new_rows)} neue Firmen gefunden. Davon haben {len(contact_ready_rows)} "
                    "bereits eine öffentliche E-Mail-Adresse und Telefonnummer."
                )
            else:
                st.warning(
                    f"{len(new_rows)} Firmennamen gefunden. Noch keine davon hat gleichzeitig "
                    "eine öffentliche E-Mail-Adresse und Telefonnummer. Die Namen bleiben sichtbar, "
                    "damit du die Unternehmen prüfen und Kontaktdaten ergänzen kannst."
                )
            discovery_columns = [
                "Priorität", "Kontaktstatus", "Unternehmen", "Branche / Typ", "Stadt", "Adresse", "PLZ",
                "Ansprechpartner", "Funktion Ansprechpartner", "Telefon", "E-Mail",
                "Website", "Quelle", "Quellenlink", "Prüfdatum", "Datenstatus",
            ]
            ordered_rows = sorted(
                new_rows,
                key=lambda row: (
                    not row["Priorität"].startswith("⭐ GOLD"),
                    not bool(row.get("E-Mail", "").strip() and row.get("Telefon", "").strip()),
                    row.get("Unternehmen", "").casefold(),
                ),
            )
            st.dataframe(ordered_rows, use_container_width=True, hide_index=True)
            st.download_button(
                "Alle neuen Firmennamen als CSV exportieren",
                data=csv_bytes(ordered_rows, discovery_columns),
                file_name=f"reinigungsradar_firmen_{discovery_result.get('mode', 'firmen').lower()}_{discovery_result.get('city', 'nrw').lower().replace(' ', '_')}.csv",
                mime="text/csv",
            )
            if contact_ready_rows:
                qualified_rows = sorted(
                    contact_ready_rows,
                    key=lambda row: (not row["Priorität"].startswith("⭐ GOLD"), row.get("Unternehmen", "").casefold()),
                )
                st.download_button(
                    "Nur Firmen mit E-Mail + Telefon als CSV exportieren",
                    data=csv_bytes(qualified_rows, discovery_columns),
                    file_name=f"reinigungsradar_qualifizierte_{discovery_result.get('mode', 'firmen').lower()}_{discovery_result.get('city', 'nrw').lower().replace(' ', '_')}.csv",
                    mime="text/csv",
                )
        elif found_rows:
            st.warning("Es wurden Treffer gefunden, aber alle gleichen bereits vorhandenen Namen oder Websites im Notion-Verzeichnis.")
        else:
            st.warning("Für diese Stadt und Kategorie wurden keine passenden öffentlichen Einträge gefunden.")

        if duplicate_rows:
            with st.expander("Bereits im Notion-Verzeichnis erkannte Einträge"):
                st.dataframe(duplicate_rows, use_container_width=True, hide_index=True)

        source_name = discovery_result.get("source", "Unbekannte Quelle")
        st.caption(f"Quelle: {source_name} · Stadt angefragt: {discovery_result.get('city', '')}")
        if discovery_result.get("source_timestamp"):
            st.caption(f"Datenstand: {discovery_result['source_timestamp']}")
        if "Google" in source_name:
            st.markdown("[Google Maps Platform – Places API](https://developers.google.com/maps/documentation/places/web-service/text-search)")
        else:
            st.caption(
                "Daten © OpenStreetMap contributors, Lizenz ODbL 1.0. Karteneinträge können "
                "unvollständig oder veraltet sein; Unternehmensangaben vor Nutzung prüfen."
            )
            st.markdown("[OpenStreetMap – Copyright und Lizenz](https://www.openstreetmap.org/copyright)")
        st.warning(
            "Ein öffentlich eingetragener Firmenkontakt ist keine Einwilligung zur Werbung. "
            "Datenschutz und rechtliche Voraussetzungen einer Kontaktaufnahme sind separat zu prüfen."
        )
    else:
        st.caption("Noch keine Suche ausgeführt. Die Suche wird nur auf Knopfdruck gestartet und höchstens 30 Minuten zwischengespeichert.")

with lead_radar_tab:
    st.subheader("Job- & Projekt-Radar für NRW")
    st.caption(
        "Sucht öffentliche Hinweise auf möglichen Bedarf an Reinigung, Sicherheit, "
        "Facility Management und Bau-/Handwerksleistungen. Treffer sind Bedarfssignale, "
        "keine bestätigten Kaufabsichten."
    )

    radar_city = st.text_input(
        "Stadt / Region",
        value="Mönchengladbach",
        max_chars=80,
        key="lead_radar_city",
    )
    radar_category = st.selectbox(
        "Gesuchter Leistungsbereich",
        list(LEAD_CATEGORIES.keys()),
        key="lead_radar_category",
    )
    radar_extra = st.text_input(
        "Zusätzliche Suchbegriffe (optional)",
        placeholder="z. B. Büro, Hotel, Industrie, Hausverwaltung",
        max_chars=120,
        key="lead_radar_extra",
    )
    radar_limit = st.slider(
        "Maximale Suchtreffer",
        min_value=5,
        max_value=20,
        value=15,
        key="lead_radar_limit",
    )

    tavily_enabled = bool(os.environ.get("TAVILY_API_KEY", "").strip())
    if tavily_enabled:
        st.success("Websuche ist aktiviert. Ergebnisse kommen aus dem öffentlichen Suchindex.")
    else:
        st.info(
            "Automatische Websuche ist vorbereitet, aber noch nicht aktiviert. "
            "Dafür muss TAVILY_API_KEY als Secret in Render hinterlegt werden. "
            "Die manuellen Portal-Links unten funktionieren bereits."
        )

    if st.button("Öffentliche Webquellen durchsuchen", type="primary", key="run_lead_radar"):
        st.session_state.pop("lead_radar_result", None)
        st.session_state.pop("lead_radar_error", None)
        try:
            with st.spinner("Durchsuche öffentliche Suchergebnisse und bewerte Bedarfssignale …"):
                st.session_state["lead_radar_result"] = cached_public_lead_search(
                    radar_city,
                    radar_category,
                    radar_extra,
                    int(radar_limit),
                )
        except (LeadDiscoveryError, ValueError) as exc:
            st.session_state["lead_radar_error"] = str(exc)

    radar_error = st.session_state.get("lead_radar_error", "")
    radar_result = st.session_state.get("lead_radar_result")
    if radar_error:
        st.warning(radar_error)
    elif radar_result:
        radar_rows = radar_result.get("rows", [])
        st.metric("Öffentliche Bedarfssignale gefunden", len(radar_rows))
        if radar_rows:
            st.dataframe(
                radar_rows,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Quellenlink": st.column_config.LinkColumn("Originalquelle"),
                    "Relevanz": st.column_config.NumberColumn("Relevanz", min_value=0, max_value=100),
                },
            )
            radar_csv_columns = [
                "Titel", "Domain", "Suchauszug", "Veröffentlicht", "Relevanz",
                "Signal", "Status", "Quellenlink", "Prüfzeitpunkt",
            ]
            st.download_button(
                "Bedarfssignale als CSV exportieren",
                data=csv_bytes(radar_rows, radar_csv_columns),
                file_name="reinigungsradar_nrw_bedarfssignale.csv",
                mime="text/csv",
            )
        else:
            st.info("Der Suchdienst lieferte für diese Suchanfrage keine verwendbaren öffentlichen Ergebnisse.")
        st.caption(
            f"Suchanfrage: {radar_result.get('query', '')} · "
            f"Quelle: {radar_result.get('source', '')} · "
            f"Geprüft: {radar_result.get('source_timestamp', '')}"
        )

    st.divider()
    st.markdown("**Manuelle Suche auf Job-, Projekt- und Social-Plattformen**")
    st.caption(
        "Diese Links öffnen die jeweilige Plattform für eine normale manuelle Suche. "
        "Sie werden nicht automatisch ausgelesen."
    )
    try:
        portal_links = build_manual_portal_links(radar_city, radar_category)
    except ValueError as exc:
        portal_links = []
        st.warning(str(exc))
    portal_columns = st.columns(3)
    for index, portal in enumerate(portal_links):
        with portal_columns[index % 3]:
            st.link_button(portal["label"], portal["url"], use_container_width=True)
            st.caption(portal["note"])

    st.info(
        "LinkedIn, Facebook, MyHammer, Indeed und StepStone sind in diesem Modul "
        "bewusst vom automatischen Crawling ausgeschlossen. MyHammer untersagt in seinen "
        "AGB automatisiertes Sammeln und kommerzielle Datenbankbildung; LinkedIn und "
        "StepStone untersagen nicht autorisiertes Crawling. Für diese Plattformen ist "
        "eine ausdrückliche API-/Partnerfreigabe erforderlich."
    )
    st.warning(
        "Die Treffer sind keine bestätigte Kaufabsicht. Vor einer geschäftlichen "
        "Kontaktaufnahme müssen Quelle, Aktualität, Unternehmensbezug und die "
        "datenschutz- sowie wettbewerbsrechtlichen Voraussetzungen separat geprüft werden. "
        "Personenprofile und private Gruppendaten werden nicht gesammelt."
    )

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
        tender_category = st.selectbox(
            "Ausschreibungskategorie",
            ["Reinigung", "Sicherheit"],
            help="Die TED-Suche ist bewusst auf diese beiden Leistungsbereiche begrenzt.",
        )
        tender_keyword = {
            "Reinigung": "Gebäudereinigung",
            "Sicherheit": "Sicherheitsdienst",
        }[tender_category]
        st.caption(f"TED-Suchbegriff: {tender_keyword}")
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

with opportunity_engine_tab:
    render_opportunity_engine_tab()

st.caption(
    "ReinigungsRadar NRW · Kunden, Anbieter und Ausschreibungen getrennt · "
    "read-only · keine automatische Kontaktaufnahme oder Angebotsabgabe."
)
