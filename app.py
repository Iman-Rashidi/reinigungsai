"""Read-only Streamlit dashboard for ReinigungsRadar."""
from __future__ import annotations

import os

import streamlit as st

from src.notion_lead_analyzer import analyze_pages, extract_fields
from src.notion_reader import NotionAPIError, query_leads
from src.ted_search import TEDSearchError, search_active_notices

st.set_page_config(page_title="ReinigungsRadar", page_icon="🧹", layout="wide")

# Streamlit Community Cloud stores credentials in st.secrets. The Notion
# client reads environment variables, so copy only the required values into
# this process environment. No credentials are displayed or written to files.
for secret_name in ("NOTION_TOKEN", "NOTION_DATA_SOURCE_ID", "NOTION_VERSION"):
    if not os.environ.get(secret_name):
        try:
            secret_value = st.secrets.get(secret_name)
        except Exception:
            secret_value = None
        if secret_value:
            os.environ[secret_name] = str(secret_value)

st.title("🧹 ReinigungsRadar")
st.subheader("Das intelligente Lead-Cockpit für Reinigungsunternehmen")
st.caption("Ein Produkt von ReinigungsAI · Interner MVP · Nur lesender Zugriff")

st.warning(
    "Interner Prototyp: Nicht mit echten Kundendaten öffentlich einsetzen, "
    "bevor Authentifizierung, Mandantentrennung, Zugriffskontrollen und "
    "Datenschutzprüfung umgesetzt sind."
)
st.info(
    "Der Score misst dokumentierte Nachweise und Recherchepriorität, "
    "nicht die Verkaufswahrscheinlichkeit. Diese App verändert keine "
    "Notion-Daten und versendet keine Nachrichten."
)

# Live, read-only search of official TED procurement notices.
st.markdown("## 🔎 Live-Suche nach öffentlichen Ausschreibungen")
st.caption(
    "Quelle: TED – Tenders Electronic Daily · ausschließlich Deutschland, "
    "nur Nordrhein-Westfalen (NRW / NUTS-Code DEA) · nur lesend · "
    "keine automatische Übernahme nach Notion."
)
with st.form("ted_search_form"):
    ted_keyword = st.text_input(
        "Suchbegriff",
        value="Gebäudereinigung",
        help="Beispiel: Gebäudereinigung, Unterhaltsreinigung oder Glasreinigung",
    )
    st.text_input("Suchgebiet", value="Nordrhein-Westfalen (NRW), Deutschland", disabled=True)
    ted_limit = st.selectbox("Maximale Treffer", [10, 20, 30, 50], index=2)
    ted_submitted = st.form_submit_button("Jetzt live auf TED suchen")

if ted_submitted:
    try:
        with st.spinner("Suche aktive TED-Bekanntmachungen in Nordrhein-Westfalen ..."):
            ted_result = search_active_notices(
                ted_keyword,
                limit=ted_limit,
            )
        st.session_state["ted_result"] = ted_result
        st.success(
            f"TED-Abfrage abgeschlossen: {ted_result['returned']} Treffer "
            f"zurückgegeben."
        )
    except (TEDSearchError, ValueError) as exc:
        st.error(f"TED-Suche fehlgeschlagen: {exc}")

ted_result = st.session_state.get("ted_result")
if ted_result:
    st.caption(
        f"Suchgebiet: Nordrhein-Westfalen, Deutschland · Abfrage: {ted_result['query']} · "
        f"Bereich: ACTIVE · Zurückgegeben: {ted_result['returned']} · "
        f"Gesamt laut API: {ted_result['total']}"
    )
    if ted_result["notices"]:
        st.markdown("### Ausschreibungen im Überblick")
        overview_rows = []
        for notice in ted_result["notices"]:
            completeness = notice.get("completeness") or {}
            present = completeness.get("present", 0)
            total = max(1, completeness.get("total", 1))
            estimated_value = notice.get("estimated_value") or ""
            estimated_currency = notice.get("estimated_value_currency") or ""
            overview_rows.append({
                "Ausschreibung": notice.get("title") or "Ohne Titel",
                "Vergabenummer": notice.get("publication_number") or "Nicht angegeben",
                "Stadt / Leistungsort": notice.get("location") or "Nicht angegeben",
                "Auftraggeber": notice.get("buyer") or "Nicht veröffentlicht",
                "Angebotsfrist": notice.get("deadline") or "Nicht angegeben",
                "Auftragswert": (
                    f"{estimated_value} {estimated_currency}".strip()
                    if estimated_value else "Nicht veröffentlicht"
                ),
                "Informationsstand": f"{present}/{total} Felder",
            })
        st.dataframe(
            overview_rows,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Ausschreibung": st.column_config.TextColumn("Ausschreibung", width="large"),
                "Stadt / Leistungsort": st.column_config.TextColumn("Stadt / Leistungsort", width="medium"),
                "Auftraggeber": st.column_config.TextColumn("Auftraggeber", width="medium"),
            },
        )
        st.caption(
            "Die Tabelle ist die Kurzübersicht. Öffne darunter eine Ausschreibung "
            "für Kontaktdaten, Bedingungen, Unterlagen und weitere Details. "
            "„Informationsstand“ misst Datenvollständigkeit, nicht Zuschlagschancen."
        )
        for notice in ted_result["notices"]:
            heading = notice.get("title", "")
            if notice.get("publication_number", ""):
                heading += f" · {notice.get("publication_number", "")}"
            with st.expander(heading):
                st.markdown("#### Auftraggeber und Kontakt")
                st.write(f"**Auftraggeber:** {notice.get("buyer", "") or 'Nicht veröffentlicht'}")
                st.write(f"**Kontaktstelle:** {notice.get("contact_point", "") or 'Nicht veröffentlicht'}")
                st.write(f"**Kontaktperson:** {notice.get("contact_person", "") or 'Nicht veröffentlicht'}")
                st.write(f"**E-Mail:** {notice.get("email", "") or 'Nicht veröffentlicht'}")
                st.write(f"**Telefon:** {notice.get("phone", "") or 'Nicht veröffentlicht'}")
                st.write(f"**Adresse:** {notice.get("buyer_postcode", "") or ''} {notice.get("buyer_city", "") or ''}".strip() or "Nicht veröffentlicht")
                if (notice.get("buyer_website") or "").startswith(("https://", "http://")):
                    st.markdown(f"[Website des Auftraggebers]({notice.get("buyer_website", "")})")
                st.markdown("#### Leistungs- und Vergabedetails")
                st.write(f"**Ort der Leistung:** {notice.get("location", "") or 'Nicht angegeben'}")
                st.write(f"**Beschreibung:** {notice.get("description", "") or 'Nicht in TED-Suchdaten enthalten'}")
                st.write(f"**CPV-Code:** {notice.get("cpv", "") or 'Nicht angegeben'}")
                st.write(f"**Verfahrensart:** {notice.get("procedure_type", "") or 'Nicht angegeben'}")
                st.write(f"**Geschätzter Auftragswert:** {notice.get("estimated_value", "") or 'Nicht veröffentlicht'} {notice.get("estimated_value_currency", "") or ''}".strip())
                st.write(f"**Laufzeit:** {notice.get("contract_duration", "") or 'Nicht angegeben'}")
                st.write(f"**Veröffentlichung:** {notice.get("publication_date", "") or 'Nicht angegeben'}")
                st.write(f"**Angebotsfrist:** {notice.get("deadline", "") or 'Nicht angegeben'}")
                st.markdown("#### Teilnahmebedingungen und Bewertung")
                st.write(f"**Eignungskriterien:** {notice.get("selection_criteria", "") or 'Originalunterlagen prüfen'}")
                st.write(f"**Ausschlussgründe:** {notice.get("exclusion_criteria", "") or 'Originalunterlagen prüfen'}")
                st.write(f"**Zuschlagskriterien:** {notice.get("award_criteria", "") or 'Originalunterlagen prüfen'}")
                st.write(f"**Gewichtung:** {notice.get("award_weights", "") or 'Nicht angegeben'}")
                st.markdown("#### Unterlagen und Angebotsabgabe")
                if (notice.get("documents_url") or "").startswith(("https://", "http://")):
                    st.markdown(f"[Vergabeunterlagen öffnen]({notice.get("documents_url", "")})")
                else:
                    st.write("**Vergabeunterlagen:** Link nicht vorhanden")
                if (notice.get("submission_url") or "").startswith(("https://", "http://")):
                    st.markdown(f"[Einreichungsportal öffnen]({notice.get("submission_url", "")})")
                else:
                    st.write("**Einreichungsportal:** Nicht angegeben")
                completeness = notice.get("completeness") or {"present": 0, "total": 1}
                completeness_total = max(1, completeness.get("total", 1))
                completeness_present = completeness.get("present", 0)
                st.progress(min(1.0, completeness_present / completeness_total))
                st.caption(f"Informationsabdeckung: {completeness_present} von {completeness_total} Prüffeldern. Keine Erfolgswahrscheinlichkeit.")
                if (notice.get("url") or "").startswith("https://ted.europa.eu/"):
                    st.markdown(f"[Originalbekanntmachung bei TED öffnen]({notice.get("url", "")})")
                st.warning(notice.get("evidence_note", ""))
    else:
        st.info(
            "Für dieses Suchgebiet wurden keine aktiven Bekanntmachungen "
            "zurückgegeben. Das bedeutet nicht, dass es keine privaten "
            "Reinigungsaufträge oder andere Beschaffungsbedarfe gibt."
        )

if not os.environ.get("NOTION_TOKEN"):
    st.error(
        "NOTION_TOKEN fehlt. Bitte in Streamlit unter "
        "Manage app → Settings → Secrets als NOTION_TOKEN hinterlegen. "
        "Das Token niemals in den Quellcode eintragen."
    )
    st.stop()

if st.button("Leads aus Notion laden und analysieren", type="primary"):
    try:
        with st.spinner("Lese Leads aus Notion ..."):
            pages = query_leads()
            assessments, skipped = analyze_pages(pages)
            fields_by_company = {}
            for page in pages:
                fields = extract_fields(page)
                company = fields.get("Unternehmen", "").strip()
                if company:
                    fields_by_company[company] = fields

        st.session_state["assessments"] = assessments
        st.session_state["skipped"] = skipped
        st.session_state["fields_by_company"] = fields_by_company
        st.success("Analyse abgeschlossen. Notion wurde nicht verändert.")
    except NotionAPIError as exc:
        st.error(f"Notion-Abfrage fehlgeschlagen: {exc}")
    except Exception as exc:
        st.error(
            "Unerwarteter Fehler beim Laden der Leads "
            f"({type(exc).__name__}). Bitte Konfiguration und Logs prüfen."
        )

assessments = st.session_state.get("assessments")
if assessments is None:
    st.markdown("Starte die Analyse, um deine vorhandenen Leads anzuzeigen.")
    st.stop()

fields_by_company = st.session_state.get("fields_by_company", {})
skipped = st.session_state.get("skipped", 0)
average_score = (
    sum(item["score"] for item in assessments) / len(assessments)
    if assessments
    else 0
)

metric_a, metric_b, metric_c = st.columns(3)
metric_a.metric("Analysierte Leads", len(assessments))
metric_b.metric("Leere Datensätze übersprungen", skipped)
metric_c.metric("Durchschnittlicher Score", f"{average_score:.1f} / 5")

labels = {
    "verified_company_location": "Unternehmen und Standort belegt",
    "service_fit": "Passung zur Reinigungsleistung",
    "documented_cleaning_need": "Reinigungsbedarf dokumentiert",
    "relevant_contact_role": "Zuständige Kontaktrolle identifiziert",
    "documented_procurement_path": "Beschaffungsweg dokumentiert",
}

search = st.text_input("Unternehmen oder Stadt suchen")
potentials = ["Hoch", "Mittel", "Niedrig"]
selected_potentials = st.multiselect(
    "Potenzial filtern",
    options=potentials,
    default=potentials,
)

visible_items = []
for item in assessments:
    fields = fields_by_company.get(item["company"], {})
    city = fields.get("Stadt", "")
    if item["potential"] not in selected_potentials:
        continue
    searchable = f'{item["company"]} {city}'.casefold()
    if search and search.casefold() not in searchable:
        continue
    visible_items.append((item, fields))

visible_items.sort(key=lambda pair: pair[0]["score"], reverse=True)

st.markdown("### Lead-Übersicht")
table_rows = [
    {
        "Unternehmen": item["company"],
        "Score": f'{item["score"]}/5',
        "Potenzial": item["potential"],
        "Stadt": fields.get("Stadt", ""),
        "Branche": fields.get("Branche", ""),
        "Fehlende Nachweise": ", ".join(
            labels.get(key, key) for key in item["missing_evidence"]
        ),
    }
    for item, fields in visible_items
]

if table_rows:
    st.dataframe(table_rows, use_container_width=True, hide_index=True)
else:
    st.write("Keine Leads für diese Filter gefunden.")

st.markdown("### Details")
for item, fields in visible_items:
    with st.expander(
        f'{item["company"]} · {item["score"]}/5 · {item["potential"]}'
    ):
        for key, proven in item["evidence"].items():
            icon = "✅" if proven else "⬜"
            st.write(f'{icon} {labels.get(key, key)}')

        if item["missing_evidence"]:
            missing_labels = [
                labels.get(key, key) for key in item["missing_evidence"]
            ]
            st.write("Noch zu prüfen: " + ", ".join(missing_labels))

        website = fields.get("Website", "")
        source_url = fields.get("Quellenlink", "")
        if website:
            st.markdown(f"[Website öffnen]({website})")
        if source_url:
            st.markdown(f"[Quelle öffnen]({source_url})")

        st.caption(item["note"])

st.caption(
    "ReinigungsRadar · Read-only-Prototyp · Keine automatische Kontaktaufnahme."
)
