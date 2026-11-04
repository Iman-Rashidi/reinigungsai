import unittest

from src.ted_search import TEDSearchError, _normalise_notice, build_expert_query


class TEDSearchTests(unittest.TestCase):
    def test_builds_german_active_search_query(self):
        self.assertEqual(
            build_expert_query("Gebäudereinigung"),
            'FT~"Gebäudereinigung" AND buyer-country=DEU SORT BY publication-date DESC',
        )

    def test_rejects_empty_or_unsupported_input(self):
        with self.assertRaises(ValueError):
            build_expert_query("   ")
        with self.assertRaises(ValueError):
            build_expert_query("cleaning; DROP")

    def test_normalises_notice_without_inventing_url(self):
        notice = _normalise_notice({
            "notice-title": "Reinigungsleistungen",
            "publication-number": "12345-2026",
            "buyer-name": "Stadt Beispiel",
        })
        self.assertEqual(notice["title"], "Reinigungsleistungen")
        self.assertEqual(notice["publication_number"], "12345-2026")
        self.assertEqual(notice["buyer"], "Stadt Beispiel")
        self.assertEqual(notice["url"], "")
        self.assertIn("müssen", notice["evidence_note"])


if __name__ == "__main__":
    unittest.main()
