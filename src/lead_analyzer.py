"""Evidence-based scoring for ReinigungsAI. Prototype only; no web scraping or outreach."""
from dataclasses import dataclass
from typing import Iterable

CRITERIA = (
    "verified_company_location",
    "service_fit",
    "documented_cleaning_need",
    "relevant_contact_role",
    "documented_procurement_path",
)

@dataclass(frozen=True)
class LeadAssessment:
    score: int
    potential: str
    missing_evidence: tuple[str, ...]
    note: str


def assess_lead(evidence: dict[str, bool]) -> LeadAssessment:
    """Score five documented criteria; absent/unknown evidence receives zero."""
    score = sum(1 for key in CRITERIA if evidence.get(key) is True)
    missing = tuple(key for key in CRITERIA if evidence.get(key) is not True)
    if score >= 4:
        potential = "Hoch"
    elif score >= 2:
        potential = "Mittel"
    else:
        potential = "Niedrig"
    return LeadAssessment(
        score=score,
        potential=potential,
        missing_evidence=missing,
        note="Score measures documented evidence and research priority, not sales probability.",
    )


def assess_many(records: Iterable[dict]) -> list[LeadAssessment]:
    """Assess a sequence of evidence dictionaries."""
    return [assess_lead(record) for record in records]
