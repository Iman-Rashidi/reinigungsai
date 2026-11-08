"""Transparent rule-based opportunity classification and explainable scoring."""
from __future__ import annotations

import re
from datetime import date
from typing import Mapping

from .models import Opportunity, clean_text


CATEGORY_TERMS = {
    "Reinigung": (
        "gebaeudereinigung", "reinigungsdienst", "reinigungsleistungen",
        "unterhaltsreinigung", "bueroreinigung", "glasreinigung",
        "fensterreinigung", "sonderreinigung", "facility cleaning",
        "cleaning services",
    ),
    "Sicherheit": (
        "sicherheitsdienst", "sicherheitsleistungen", "wachdienst",
        "objektschutz", "bewachung", "empfangsdienst", "security services",
    ),
    "Facility Management": (
        "facility management", "hausmeisterservice", "gebaeudeservice",
        "gebaeudemanagement", "technisches gebaeudemanagement",
        "instandhaltung", "hauswart",
    ),
    "Bau / Handwerk": (
        "bauleistungen", "sanierung", "handwerker", "bauunternehmen",
        "instandsetzungsarbeiten", "bauunterhalt",
    ),
}

JOB_TERMS = (
    "stellenangebot", "stellenanzeige", "karriere", "bewerbung",
    "vollzeitstelle", "teilzeitstelle", "ausbildung", "gehalt",
    "bewerber", "mitarbeiter gesucht", "reinigungskraft gesucht",
    "job als", "stellen als",
)
PROCUREMENT_TERMS = (
    "ausschreibung", "vergabeverfahren", "vergabe", "rahmenvertrag",
    "leistungsbeschreibung", "angebotsfrist", "angebot abgeben",
    "angebot einreichen", "auftragnehmer", "dienstleister gesucht",
    "reinigungsfirma gesucht", "reinigungsdienst gesucht",
    "auftragsbekanntmachung", "teilnahmewettbewerb",
)
PRIVATE_NEED_TERMS = (
    "reinigungsfirma gesucht", "reinigungsdienst gesucht",
    "dienstleister gesucht", "angebot einholen", "reinigungsauftrag",
    "reinigung beauftragen",
)


def _fold(value: object) -> str:
    text = clean_text(value).casefold()
    return text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")


def classify_opportunity(
    title: str,
    description: str = "",
    cpv: str = "",
    declared_category: str = "",
) -> tuple[str, str]:
    text = _fold(f"{title} {description} {cpv}")
    job_hit = any(term in text for term in JOB_TERMS)
    procurement_hit = any(term in text for term in PROCUREMENT_TERMS)
    if job_hit and not procurement_hit:
        return "Unbekannt", "job"
    for category, terms in CATEGORY_TERMS.items():
        if any(term in text for term in terms):
            return category, "tender" if procurement_hit else ("service_request" if any(term in text for term in PRIVATE_NEED_TERMS) else "signal")
    if declared_category in CATEGORY_TERMS:
        return declared_category, "tender" if procurement_hit else "signal"
    return "Unbekannt", "tender" if procurement_hit else "signal"


def is_nrw_location(text: str) -> bool | None:
    folded = _fold(text)
    if not folded.strip():
        return None
    non_nrw_regions = (
        "bayern", "berlin", "brandenburg", "sachsen", "thueringen",
        "thuringen", "hessen", "hamburg", "bremen", "saarland",
        "niedersachsen", "schleswig holstein", "mecklenburg vorpommern",
        "rheinland pfalz", "baden wuerttemberg", "baden wurttemberg",
    )
    if any(term in folded for term in non_nrw_regions):
        return False
    if any(term in folded for term in ("nordrhein westfalen", "north rhine westphalia", "nrw", "dea")):
        return True
    nrw_places = (
        "aachen", "bielefeld", "bochum", "bonn", "bottrop", "dortmund",
        "duisburg", "duesseldorf", "dueren", "essen", "gelsenkirchen",
        "guetersloh", "hagen", "herne", "koeln", "krefeld", "leverkusen",
        "moenchengladbach", "muenster", "neuss", "oberhausen", "paderborn",
        "recklinghausen", "siegen", "solingen", "viersen", "witten", "wuppertal",
    )
    if any(term in folded for term in nrw_places):
        return True
    return None


def score_opportunity(item: Opportunity) -> tuple[int, str, list[str]]:
    text = _fold(f"{item.title} {item.description} {item.cpv}")
    score = int(max(0, min(1, float(item.provider_score or 0))) * 25)
    evidence = []
    if item.category != "Unbekannt":
        score += 25
        evidence.append(f"Kategorie passt: {item.category}")
    if any(term in text for term in PROCUREMENT_TERMS):
        score += 20
        evidence.append("Hinweis auf Vergabe oder konkreten Auftrag")
    elif any(term in text for term in PRIVATE_NEED_TERMS):
        score += 18
        evidence.append("Hinweis auf privaten Dienstleistungsbedarf")
    else:
        evidence.append("Bedarf noch nicht als Auftrag verifiziert")
    location = is_nrw_location(f"{item.city} {item.region} {item.postal_code} {item.description[:1200]}")
    if location is True:
        score += 20
        evidence.append("NRW-Bezug im Text erkennbar")
    elif location is None:
        score += 5
        evidence.append("Leistungsort noch zu prüfen")
    else:
        evidence.append("NRW-Bezug nicht bestätigt")
    if item.deadline:
        try:
            due = date.fromisoformat(item.deadline[:10])
            if due >= date.today():
                score += 15
                evidence.append("Frist noch nicht abgelaufen")
            else:
                evidence.append("Frist möglicherweise abgelaufen")
        except ValueError:
            evidence.append("Fristformat nicht eindeutig")
    if item.buyer:
        score += 5
        evidence.append("Auftraggeber angegeben")
    score = max(0, min(100, score))
    return score, "; ".join(evidence), evidence


def enrich_opportunity(item: Opportunity) -> Opportunity:
    category, kind = classify_opportunity(item.title, item.description, item.cpv, item.category)
    if category != "Unbekannt":
        item.category = category
    item.opportunity_type = kind if item.opportunity_type in {"", "signal", "unknown"} else item.opportunity_type
    item.score, item.score_reason, item.evidence = score_opportunity(item)
    return item
