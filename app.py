import os
import streamlit as st
import pandas as pd
from src.notion_reader import query_leads
from src.notion_lead_analyzer import analyze_pages

st.set_page_config(page_title='ReinigungsRadar', page_icon='🧹', layout='wide')
st.title('🧹 ReinigungsRadar')
st.subheader('Das intelligente Lead-Cockpit für Reinigungsunternehmen')
st.caption('Ein Produkt von ReinigungsAI · Interner MVP · Nur lesender Zugriff')
st.warning('Nur für lokale interne Tests. Nicht öffentlich mit echten Kundendaten einsetzen, bevor Authentifizierung, Mandantentrennung, Zugriffskontrollen und Datenschutzprüfung umgesetzt sind.')
st.info('Der Score misst dokumentierte Nachweise und Recherchepriorität, nicht die Verkaufswahrscheinlichkeit. Diese App verändert keine Notion-Daten und versendet keine Nachrichten.')
if not os.environ.get('NOTION_TOKEN') or not os.environ.get('NOTION_DATA_SOURCE_ID'):
 st.error('Konfiguration fehlt: NOTION_TOKEN und NOTION_DATA_SOURCE_ID müssen als Umgebungsvariablen gesetzt sein. Zugangsdaten niemals in den Quellcode schreiben.')
 st.stop()
if st.button('Leads aus Notion laden und analysieren', type='primary'):
    try:
        with st.spinner('Lese Leads aus Notion ...'):
 pages = query_leads()
 assessments, skipped = analyze_pages(pages)
 st.session_state['assessments'] = assessments
 st.session_state['skipped'] = skipped
 st.session_state['pages'] = pages
 st.success('Analyse abgeschlossen. Notion wurde nicht verändert.')
    except Exception:
 st.error('Notion-Abfrage fehlgeschlagen. Bitte Verbindung und Konfiguration prüfen. Zugangsdaten werden nicht angezeigt.')

assessments = st.session_state.get('assessments')
if assessments is None:
 st.markdown('Starte die Analyse, um deine vorhandenen Leads anzuzeigen.')
 st.stop()

skipped = st.session_state.get('skipped', 0)
avg = sum(x['score'] for x in assessments) / len(assessments) if assessments else 0
c1, c2, c3 = st.columns(3)
c1.metric('Analysierte Leads', len(assessments))
c2.metric('Leere Datensätze übersprungen', skipped)
c3.metric('Durchschnittlicher Score', f'{avg:.1f} / 5')

labels = {
 'verified_company_location': 'Unternehmen und Standort belegt',
 'service_fit': 'Passung zur Reinigungsleistung',
 'documented_cleaning_need': 'Reinigungsbedarf dokumentiert',
 'relevant_contact_role': 'Zuständige Kontaktrolle identifiziert',
 'documented_procurement_path': 'Beschaffungsweg dokumentiert',
}

def plain(prop):
    if not isinstance(prop, dict): return ''
    for key in ('title', 'rich_text'):
 items = prop.get(key, [])
        if isinstance(items, list): return ''.join(i.get('plain_text', '') for i in items if isinstance(i, dict))
    if isinstance(prop.get('select'), dict): return prop['select'].get('name', '')
    return str(prop.get('url') or '')

fields = {}
for page in st.session_state.get('pages', []):
 props = page.get('properties', {})
 company = plain(props.get('Unternehmen', {}))
    if company: fields[company] = {k: plain(v) for k, v in props.items()}

search = st.text_input('Unternehmen suchen')
potentials = sorted({x['potential'] for x in assessments})
chosen = st.multiselect('Potenzial filtern', potentials, default=potentials)
rows = []
shown = []
for item in assessments:
 f = fields.get(item['company'], {})
    if item['potential'] not in chosen: continue
    if search and search.casefold() not in (item['company'] + ' ' + f.get('Stadt', '')).casefold(): continue
 rows.append({'Unternehmen': item['company'], 'Score': f"{item['score']}/5", 'Potenzial': item['potential'], 'Stadt': f.get('Stadt', ''), 'Branche': f.get('Branche', ''), 'Fehlende Nachweise': ', '.join(labels.get(k, k) for k in item['missing_evidence'])})
 shown.append((item, f))
st.markdown('### Lead-Übersicht')
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
st.markdown('### Details')
for item, f in shown:
    with st.expander(f"{item['company']} · {item['score']}/5 · {item['potential']}"):
        for key, value in item['evidence'].items(): st.write(('✅' if value else '⬜') + ' ' + labels.get(key, key))
 st.write('Noch zu prüfen: ' + ', '.join(labels.get(k, k) for k in item['missing_evidence']))
        if f.get('Website'): st.markdown('[Website öffnen](' + f['Website'] + ')')
        if f.get('Quellenlink'): st.markdown('[Quelle öffnen](' + f['Quellenlink'] + ')')
 st.caption(item['note'])
st.caption('ReinigungsRadar · Read-only-Prototyp · Keine automatische Kontaktaufnahme.')
