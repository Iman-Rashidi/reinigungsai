"""Small local demo for the ReinigungsAI lead scoring prototype."""
from lead_analyzer import assess_lead


def main() -> None:
    demo_evidence = {
        "verified_company_location": True,
        "service_fit": True,
        "documented_cleaning_need": False,
        "relevant_contact_role": False,
        "documented_procurement_path": False,
    }
    result = assess_lead(demo_evidence)
    print(f"Score: {result.score}/5")
    print(f"Potenzial: {result.potential}")
    print("Fehlende Nachweise:", ", ".join(result.missing_evidence) or "Keine")
    print(result.note)


if __name__ == "__main__":
    main()
