"""Two-directory NRW dashboard for ReinigungsRadar.

Read-only Notion integration. Separate data sources:
- NOTION_DATA_SOURCE_ID: prospective private-sector customers
- PROVIDER_DATA_SOURCE_ID: cleaning/security service providers
"""
from __future__ import annotations

import os
import re
from datetime import date

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
from src.lead_discovery import LEAD_CATEGORIES, build_manual_portal_links
from src.lead_lifecycle import (
    compare_ad_snapshots,
    detect_ad_status,
    find_duplicate_pairs,
)
from src.supabase_leads import SupabaseLeadStoreError, persist_search_batch
from src.brevo_client import BrevoAPIError, BrevoClient, BrevoConfigurationError
from src.company_search import (
    CUSTOMER_CATEGORIES,
    PROVIDER_CATEGORIES,
    CompanySearchError,
    search_companies,
)

st.set_page_config(page_title="ReinigungsRadar NRW", page_icon="📒", layout="wide")

for secret_name in ("APP_PASSWORD", "NOTION_TOKEN", "NOTION_DATA_SOURCE_ID", "PROVIDER_DATA_SOURCE_ID", "NOTION_VERSION", "BREVO_API_KEY", "BREVO_DOI_TEMPLATE_ID", "BREVO_DOI_REDIRECT_URL", "BREVO_SENDER_EMAIL", "BREVO_SENDER_NAME"):
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
    city_filter = st.text_input(
        "Stadt enthält (nur gespeicherte Einträge)",
        placeholder="z. B. Köln",
        help="Dieser Filter zeigt nur passende Datensätze, die bereits aus Notion geladen wurden. Für eine neue Firmensuche nutze „Neue Firmen finden“.",
    )
    st.caption("Der Stadtfilter startet keine Live-Suche.")
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

customer_tab, provider_tab, discovery_tab, lead_radar_tab, tender_tab, email_marketing_tab, setup_tab = st.tabs([
    "🏢 Kundenverzeichnis",
    "🛡️ Anbieter-Verzeichnis",
    "🔎 Neue Firmen finden",
    "🌐 Job- & Projekt-Radar",
    "📄 Ausschreibungen (TED)",
    "📨 E-Mail-Marketing",
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
        "Kostenlose Live-Firmensuche über Overture Maps und ergänzend OpenStreetMap / Overpass. "
        "Die Ortsdaten werden aus offenen Datensätzen geladen; es wird kein Google-Places- oder "
        "anderer kostenpflichtiger Places-Dienst aufgerufen."
    )
    st.info(
        "Gib die gewünschte Stadt unten ein. Overture lädt nur die räumlich passenden Dateien "
        "für das Suchgebiet; OpenStreetMap ergänzt die Treffer. Notion bleibt unverändert."
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
            "Stadt / Gemeinde in NRW (Live-Suche)",
            value="",
            max_chars=80,
            placeholder="z. B. Köln, Düsseldorf, Viersen oder Erkelenz",
            help="Hier wird tatsächlich eine neue Suche in der eingegebenen Stadt gestartet.",
        )
        discovery_category = st.selectbox("Branche / Dienstleistung", category_options)
        discovery_limit = st.slider("Maximale Treffer", min_value=50, max_value=1000, value=250, step=50)
        discovery_submitted = st.form_submit_button(
            "Neue Firmen suchen",
            type="primary",
        )

    if discovery_submitted:
        st.session_state.pop("discovery_result", None)
        st.session_state.pop("discovery_error", None)
        if not discovery_city.strip():
            st.session_state["discovery_error"] = "Bitte zuerst eine Stadt eingeben, zum Beispiel Köln."
        else:
            try:
                with st.spinner(f"Kostenlose Overture- und OpenStreetMap-Suche in {discovery_city} …"):
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
        st.caption(f"Quellen: {source_name} · Stadt angefragt: {discovery_result.get('city', '')}")
        source_breakdown = discovery_result.get("source_breakdown", {})
        if source_breakdown:
            parts = [
                f"{source}: {count}"
                for source, count in source_breakdown.items()
                if count
            ]
            st.caption("Treffer vor Zusammenführung: " + " · ".join(parts))
        for source_warning in discovery_result.get("source_warnings", []):
            st.warning(source_warning)
        if discovery_result.get("source_timestamp"):
            st.caption(f"Datenstand: {discovery_result['source_timestamp']}")
        if "Google" in source_name:
            st.markdown("[Google Maps Platform – Places API](https://developers.google.com/maps/documentation/places/web-service/text-search)")
        else:
            if "Overture Maps" in source_name:
                st.caption(
                    "Overture Places: offene Datensätze unter CDLA Permissive 2.0 und Apache 2.0. "
                    "Einträge können unvollständig oder veraltet sein."
                )
                st.markdown("[Overture Maps – Places-Daten und Quellen](https://docs.overturemaps.org/guides/places/)")
            st.caption(
                "OpenStreetMap-Daten © OpenStreetMap contributors, Lizenz ODbL 1.0. "
                "Unternehmensangaben vor Nutzung prüfen."
            )
            st.markdown("[OpenStreetMap – Copyright und Lizenz](https://www.openstreetmap.org/copyright)")
        st.warning(
            "Ein öffentlich eingetragener Firmenkontakt ist keine Einwilligung zur Werbung. "
            "Datenschutz und rechtliche Voraussetzungen einer Kontaktaufnahme sind separat zu prüfen."
        )
    else:
        st.caption("Noch keine Suche ausgeführt. Gib zuerst die gewünschte Stadt ein. Die Suche startet nur auf Knopfdruck und wird höchstens 30 Minuten zwischengespeichert.")

with lead_radar_tab:
    st.subheader("Job- & Projekt-Radar für NRW")
    st.caption(
        "Sucht öffentliche Hinweise auf möglichen Bedarf an Reinigung, Sicherheit, "
        "Facility Management und Bau-/Handwerksleistungen. Treffer sind Bedarfssignale, "
        "keine bestätigten Kaufabsichten."
    )

    radar_city = st.text_input(
        "Stadt / Region",
        value="",
        max_chars=80,
        placeholder="z. B. Köln, Düsseldorf oder Viersen",
        key="lead_radar_city",
    )
    radar_category = st.selectbox(
        "Gesuchter Leistungsbereich",
        list(LEAD_CATEGORIES.keys()),
        key="lead_radar_category",
    )
    st.info(
        "Kostenloser Modus: automatische Websuche über externe Such-APIs ist deaktiviert, "
        "damit keine nutzungsabhängigen API-Kosten entstehen. Die manuellen Suchlinks "
        "weiter unten bleiben verfügbar und verwenden keine API-Anbindung dieser App."
    )

    radar_error = st.session_state.get("lead_radar_error", "")
    radar_result = st.session_state.get("lead_radar_result")
    if radar_error:
        st.warning(radar_error)
    elif radar_result:
        radar_rows = radar_result.get("rows", [])
        st.metric("Öffentliche Bedarfssignale gefunden", len(radar_rows))
        storage_result = st.session_state.get("lead_radar_storage")
        storage_error = st.session_state.get("lead_radar_storage_error", "")
        if storage_result:
            st.caption(
                "Supabase-Staging: "
                f"{storage_result.get('processed', 0)} Datensätze verarbeitet · "
                f"{storage_result.get('inserted', 0)} neu · "
                f"{storage_result.get('updated', 0)} aktualisiert."
            )
        elif storage_error:
            st.warning(f"Speicherung in Supabase fehlgeschlagen; die Suchergebnisse bleiben verfügbar: {storage_error}")
        radar_changes = st.session_state.get("lead_radar_changes", [])
        if radar_changes:
            with st.expander(f"Änderungen seit der letzten Suche ({len(radar_changes)})"):
                for change in radar_changes:
                    st.write(f"**{change['title']}**")
                    st.json(change["changed_fields"])

        # Compare public-web results with TED notices already loaded in this session.
        ted_for_dedup = st.session_state.get("ted_notices", [])
        combined_records = [
            {
                "title": row.get("Titel", ""),
                "description": row.get("Suchauszug", ""),
                "location": radar_result.get("city", ""),
                "category": radar_result.get("category", ""),
                "source": row.get("Domain", "Public Web"),
                "url": row.get("Quellenlink", ""),
            }
            for row in radar_rows
        ]
        combined_records.extend([
            {
                "title": notice.get("title", ""),
                "description": notice.get("description", ""),
                "location": notice.get("location", ""),
                "source": "TED",
                "external_id": notice.get("publication_number", ""),
                "url": notice.get("url", ""),
            }
            for notice in ted_for_dedup
        ])
        cross_portal_duplicates = [
            pair for pair in find_duplicate_pairs(combined_records)
            if pair.get("cross_portal")
        ] if len(combined_records) > 1 else []
        if cross_portal_duplicates:
            duplicate_view = []
            for pair in cross_portal_duplicates:
                left = combined_records[pair["left_index"]]
                right = combined_records[pair["right_index"]]
                duplicate_view.append({
                    "Portal A": left.get("source", ""),
                    "Auftrag A": left.get("title", ""),
                    "Portal B": right.get("source", ""),
                    "Auftrag B": right.get("title", ""),
                    "Ähnlichkeit": pair["similarity"],
                    "Erkennungsgrund": ", ".join(pair["reasons"]),
                })
            st.warning(f"{len(duplicate_view)} mögliche portalübergreifende Doppelmeldungen erkannt. Bitte manuell bestätigen.")
            st.dataframe(duplicate_view, use_container_width=True, hide_index=True)
        elif ted_for_dedup:
            st.caption("Aktuell wurde keine ausreichend belegte portalübergreifende Doppelmeldung zwischen Websuche und TED erkannt.")
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
        previous_notices = st.session_state.get("ted_notices", [])
        st.session_state["ted_notices"] = []
        st.session_state["ted_search_error"] = ""
        st.session_state.pop("ted_storage_error", None)
        st.session_state.pop("ted_storage", None)
        st.session_state["ted_search_ran"] = True
        try:
            with st.spinner("Suche aktive TED-Bekanntmachungen für NRW …"):
                ted_result = search_active_notices(
                    tender_keyword,
                    limit=int(tender_limit),
                    region="NRW",
                )
            try:
                st.session_state["ted_storage"] = persist_search_batch(
                    source="ted",
                    query=ted_result.get("query", ""),
                    city="NRW",
                    category=tender_category,
                    records=ted_result.get("notices", []),
                )
            except SupabaseLeadStoreError as exc:
                st.session_state["ted_storage_error"] = str(exc)
            previous_by_id = {
                item.get("publication_number") or item.get("url"): item
                for item in previous_notices
                if item.get("publication_number") or item.get("url")
            }
            ted_changes = []
            for item in ted_result["notices"]:
                stable_key = item.get("publication_number") or item.get("url")
                old_item = previous_by_id.get(stable_key)
                if old_item:
                    diff = compare_ad_snapshots(old_item, item)
                    if diff["changed"]:
                        ted_changes.append({"title": item.get("title", "Ohne Titel"), **diff})
            st.session_state["ted_changes"] = ted_changes
            st.session_state["ted_notices"] = ted_result["notices"]
            st.session_state["ted_total"] = ted_result["total"]
            st.session_state["ted_query"] = ted_result["query"]
        except (TEDSearchError, ValueError) as exc:
            st.session_state["ted_search_error"] = str(exc)

    ted_error = st.session_state.get("ted_search_error", "")
    ted_notices = st.session_state.get("ted_notices", [])
    current_radar = st.session_state.get("lead_radar_result") or {}
    current_radar_rows = current_radar.get("rows", [])
    if ted_notices and current_radar_rows:
        cross_records = [
            {
                "title": row.get("Titel", ""),
                "description": row.get("Suchauszug", ""),
                "location": current_radar.get("city", ""),
                "category": current_radar.get("category", ""),
                "source": row.get("Domain", "Public Web"),
                "url": row.get("Quellenlink", ""),
            }
            for row in current_radar_rows
        ]
        cross_records.extend([
            {
                "title": item.get("title", ""),
                "description": item.get("description", ""),
                "location": item.get("location", ""),
                "source": "TED",
                "external_id": item.get("publication_number", ""),
                "url": item.get("url", ""),
            }
            for item in ted_notices
        ])
        cross_matches = [
            pair for pair in find_duplicate_pairs(cross_records)
            if pair.get("cross_portal")
        ]
        if cross_matches:
            with st.expander(f"Portalübergreifende Doppelmeldungen ({len(cross_matches)})"):
                for pair in cross_matches:
                    left = cross_records[pair["left_index"]]
                    right = cross_records[pair["right_index"]]
                    st.write(
                        f"**{left.get('title', '')}** ({left.get('source', '')}) "
                        f"↔ **{right.get('title', '')}** ({right.get('source', '')})"
                    )
                    st.caption(
                        f"Ähnlichkeit: {pair['similarity']:.0%} · "
                        f"Erkennung: {', '.join(pair['reasons'])} · "
                        "Bitte Originalquellen manuell vergleichen."
                    )
    if ted_error:
        st.error(f"TED-Suche fehlgeschlagen: {ted_error}")
    elif ted_notices:
        ted_changes = st.session_state.get("ted_changes", [])
        if ted_changes:
            with st.expander(f"Änderungen seit der letzten TED-Suche ({len(ted_changes)})"):
                for change in ted_changes:
                    st.write(f"**{change['title']}**")
                    st.json(change["changed_fields"])
        st.success(
            f"{len(ted_notices)} Treffer geladen. "
            f"TED meldet insgesamt {st.session_state.get('ted_total', len(ted_notices))} passende aktive Bekanntmachungen."
        )
        ted_storage = st.session_state.get("ted_storage")
        ted_storage_error = st.session_state.get("ted_storage_error", "")
        if ted_storage:
            st.caption(
                "Supabase-Staging: "
                f"{ted_storage.get('processed', 0)} Bekanntmachungen verarbeitet · "
                f"{ted_storage.get('inserted', 0)} neu · "
                f"{ted_storage.get('updated', 0)} aktualisiert."
            )
        elif ted_storage_error:
            st.warning(f"Speicherung in Supabase fehlgeschlagen; TED-Treffer bleiben verfügbar: {ted_storage_error}")
        for notice in ted_notices:
            publication_number = notice.get("publication_number") or "Ohne Veröffentlichungsnummer"
            title = notice.get("title") or "Ohne Titel"
            with st.expander(f"{publication_number} · {title}"):
                lifecycle = detect_ad_status({"deadline": notice.get("deadline"), "status": "active"})
                lifecycle_label = {
                    "active": "Aktiv / Frist noch offen",
                    "expired": "Abgelaufen",
                    "stale": "Veraltet – Aktualität prüfen",
                    "unknown": "Status nicht belegbar",
                }.get(lifecycle["status"], lifecycle["status"])
                st.caption(f"Anzeigenstatus: {lifecycle_label} · Nachweis: {lifecycle['reason']}")
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


with email_marketing_tab:
    st.subheader("Brevo – kostenloses E-Mail-Marketing")
    st.caption("Direkte HTTPS-API-Anbindung ohne separaten Mailserver oder SMTP-Hosting.")
    st.warning("Öffentliche Firmen-E-Mail-Adressen sind keine Werbeeinwilligung. Kontakte aus der Firmensuche werden niemals automatisch übernommen.")
    api_key = os.environ.get("BREVO_API_KEY", "").strip()
    doi_template = os.environ.get("BREVO_DOI_TEMPLATE_ID", "").strip()
    doi_redirect = os.environ.get("BREVO_DOI_REDIRECT_URL", "").strip()
    if not api_key:
        st.info("Brevo ist noch nicht verbunden. Hinterlege den Schlüssel als Render-Secret BREVO_API_KEY. Für Double-Opt-in zusätzlich BREVO_DOI_TEMPLATE_ID und BREVO_DOI_REDIRECT_URL konfigurieren.")
    else:
        try:
            brevo = BrevoClient(api_key=api_key)
        except BrevoConfigurationError as exc:
            st.error(str(exc))
            brevo = None
        if brevo:
            if st.button("Brevo-Verbindung testen und Listen laden", type="primary", key="brevo_test"):
                try:
                    st.session_state["brevo_lists"] = brevo.get_lists()
                    st.session_state["brevo_campaigns"] = brevo.get_campaigns()
                    st.session_state["brevo_error"] = ""
                    st.session_state["brevo_ok"] = True
                except BrevoAPIError as exc:
                    st.session_state["brevo_error"] = str(exc)
                    st.session_state["brevo_ok"] = False
            if st.session_state.get("brevo_ok"):
                st.success(f"Verbindung erfolgreich: {len(st.session_state.get('brevo_lists', []))} Listen geladen.")
            elif st.session_state.get("brevo_error"):
                st.error(st.session_state["brevo_error"])
            lists = st.session_state.get("brevo_lists", [])
            if lists:
                st.dataframe([{"ID": x.get("id"), "Name": x.get("name"), "Kontakte": x.get("uniqueSubscribers", 0)} for x in lists], use_container_width=True, hide_index=True)
                names = {int(x["id"]): str(x.get("name") or f"Liste {x['id']}") for x in lists if str(x.get("id", "")).isdigit()}
                st.divider()
                st.markdown("**Kontakt nur per Double-Opt-in aufnehmen**")
                if not (doi_template.isdigit() and doi_redirect.startswith("https://")):
                    st.info("DOI-Vorlage fehlt: BREVO_DOI_TEMPLATE_ID und BREVO_DOI_REDIRECT_URL konfigurieren.")
                else:
                    with st.form("brevo_doi_contact"):
                        email = st.text_input("E-Mail-Adresse")
                        first_name = st.text_input("Vorname (optional)")
                        list_id = st.selectbox("Zielgruppe", list(names), format_func=lambda x: names[x])
                        consent_date = st.date_input("Datum der vorherigen Einwilligung", value=date.today())
                        proof = st.text_input("Nachweisreferenz zur Einwilligung")
                        consent = st.checkbox("Die vorherige ausdrückliche Werbeeinwilligung liegt vor und ist nachweisbar.")
                        doi_submit = st.form_submit_button("Double-Opt-in anfordern")
                    if doi_submit:
                        try:
                            brevo.create_doi_contact(email=email, first_name=first_name, list_id=int(list_id), template_id=int(doi_template), redirection_url=doi_redirect, consent_date=consent_date.isoformat(), evidence_reference=proof, consent_confirmed=consent)
                            st.success("Bestätigungs-E-Mail angefordert. Die Aufnahme erfolgt erst nach DOI-Bestätigung.")
                        except (BrevoAPIError, ValueError) as exc:
                            st.error(f"DOI-Anfrage fehlgeschlagen: {exc}")
                st.divider()
                st.markdown("**Kampagne als Entwurf erstellen**")
                with st.form("brevo_campaign_draft"):
                    name = st.text_input("Interner Kampagnenname")
                    subject = st.text_input("Betreff")
                    sender_email = st.text_input("Verifizierte Absenderadresse", value=os.environ.get("BREVO_SENDER_EMAIL", ""))
                    sender_name = st.text_input("Absendername", value=os.environ.get("BREVO_SENDER_NAME", "ReinigungsRadar"))
                    target_ids = st.multiselect("Zielgruppen mit dokumentierter Einwilligung", list(names), format_func=lambda x: names[x])
                    preview = st.text_input("Vorschautext (optional)")
                    body = st.text_area("E-Mail-Inhalt", height=220)
                    audience_ok = st.checkbox("Alle Kontakte dieser Listen haben eine dokumentierte rechtmäßige Werbeeinwilligung.")
                    audience_proof = st.text_input("Referenz zur Einwilligungsdokumentation der Zielgruppe")
                    draft_submit = st.form_submit_button("Kampagnenentwurf erstellen")
                if draft_submit:
                    try:
                        result = brevo.create_campaign_draft(name=name, subject=subject, sender_email=sender_email, sender_name=sender_name, list_ids=target_ids, body=body, preview_text=preview, audience_consent_confirmed=audience_ok, audience_evidence_reference=audience_proof)
                        st.success(f"Entwurf in Brevo erstellt (ID: {result.get('id', 'unbekannt')}). Kein Versand wurde ausgelöst.")
                    except (BrevoAPIError, ValueError) as exc:
                        st.error(f"Entwurf konnte nicht erstellt werden: {exc}")
                campaigns = st.session_state.get("brevo_campaigns", [])
                if campaigns:
                    st.markdown("**Vorhandene Kampagnen**")
                    st.dataframe([{"ID": x.get("id"), "Name": x.get("name"), "Status": x.get("status"), "Betreff": x.get("subject")} for x in campaigns], use_container_width=True, hide_index=True)
    st.caption("Keine Versand- oder Planungsfunktion im Radar. Versand und finale Zielgruppenprüfung bleiben manuell in Brevo.")

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
        "**E-Mail-Marketing**\n"
        "- Brevo Free wird direkt über die HTTPS-API angebunden; Secret: BREVO_API_KEY.\n"
        "- Neue Kontakte nur mit dokumentierter vorheriger Einwilligung und Double-Opt-in.\n"
        "- Kampagnen werden nur als Entwurf angelegt; Versand bleibt manuell in Brevo.\n\n"
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
    "read-only für Verzeichnisse · E-Mail-Kampagnen nur als Entwurf · keine automatische Kontaktaufnahme oder Angebotsabgabe."
)
