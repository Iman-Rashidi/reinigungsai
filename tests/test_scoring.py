import unittest
from src.lead_analyzer import assess_lead


class LeadScoringTests(unittest.TestCase):
    def test_all_unknown_scores_zero(self):
        result = assess_lead({})
        self.assertEqual(result.score, 0)
        self.assertEqual(result.potential, "Niedrig")
        self.assertEqual(len(result.missing_evidence), 5)

    def test_two_documented_criteria_scores_medium(self):
        result = assess_lead({"verified_company_location": True, "service_fit": True})
        self.assertEqual(result.score, 2)
        self.assertEqual(result.potential, "Mittel")

    def test_all_five_scores_high(self):
        from src.lead_analyzer import CRITERIA
        result = assess_lead({key: True for key in CRITERIA})
        self.assertEqual(result.score, 5)
        self.assertEqual(result.potential, "Hoch")

    def test_truthy_non_boolean_does_not_count(self):
        result = assess_lead({"verified_company_location": "yes"})
        self.assertEqual(result.score, 0)


if __name__ == "__main__":
    unittest.main()
