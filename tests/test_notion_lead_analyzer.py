import unittest

from src.notion_lead_analyzer import assess_record, extract_fields, analyze_pages


class NotionLeadAnalyzerTests(unittest.TestCase):
    def test_verified_location_and_service_fit(self):
        result = assess_record({
            "Unternehmen": "Beispiel GmbH",
            "Stadt": "Mönchengladbach",
            "Adresse": "Musterstraße 1",
            "Branche": "Bürostandort",
        })
        self.assertTrue(result["evidence"]["verified_company_location"])
        self.assertTrue(result["evidence"]["service_fit"])
        self.assertEqual(result["score"], 2)
        self.assertEqual(result["potential"], "Mittel")

    def test_mentions_of_unconfirmed_need_do_not_count(self):
        result = assess_record({
            "Unternehmen": "Beispiel GmbH",
            "Stadt": "Mönchengladbach",
            "Adresse": "Musterstraße 1",
            "Branche": "Einzelhandel",
            "Quelle / Hinweis": "Reinigungsbedarf nicht bestätigt; Ausschreibung nicht belegt.",
        })
        self.assertFalse(result["evidence"]["documented_cleaning_need"])
        self.assertFalse(result["evidence"]["documented_procurement_path"])

    def test_affirmative_need_and_procurement_evidence_count(self):
        result = assess_record({
            "Unternehmen": "Beispiel GmbH",
            "Stadt": "Mönchengladbach",
            "Adresse": "Musterstraße 1",
            "Branche": "Krankenhaus",
            "Quelle / Hinweis": "Reinigungsbedarf ist bestätigt. Ausschreibung ist veröffentlicht.",
        })
        self.assertTrue(result["evidence"]["documented_cleaning_need"])
        self.assertTrue(result["evidence"]["documented_procurement_path"])

    def test_extract_fields_reads_notion_title_and_rich_text(self):
        page = {"properties": {
            "Unternehmen": {"title": [{"plain_text": "Test AG"}]},
            "Branche": {"rich_text": [{"plain_text": "Büro"}]},
            "Website": {"url": "https://example.org"},
        }}
        fields = extract_fields(page)
        self.assertEqual(fields["Unternehmen"], "Test AG")
        self.assertEqual(fields["Branche"], "Büro")
        self.assertEqual(fields["Website"], "https://example.org")

    def test_empty_rows_are_skipped(self):
        assessments, skipped = analyze_pages([
            {"properties": {"Unternehmen": {"title": []}}},
            {"properties": {"Unternehmen": {"title": [{"plain_text": "Test GmbH"}]}}},
        ])
        self.assertEqual(len(assessments), 1)
        self.assertEqual(skipped, 1)


if __name__ == "__main__":
    unittest.main()
