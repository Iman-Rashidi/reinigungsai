import unittest

from src.ted_search import (
    _normalise_notice,
    build_expert_query,
)


class TEDSearchTests(unittest.TestCase):
    def test_default_search_is_limited_to_nrw(self):
        self.assertEqual(
            build_expert_query("Gebäudereinigung"),
            'FT~"Gebäudereinigung" AND buyer-country=DEU AND place-of-performance=DEA* '
            "SORT BY publication-date DESC",
        )

    def test_search_is_limited_to_germany_and_nrw(self):
        query = build_expert_query("Glasreinigung")
        self.assertIn("buyer-country=DEU", query)
        self.assertIn("place-of-performance=DEA*", query)

    def test_rejects_other_regions_and_countries(self):
        with self.assertRaises(ValueError):
            build_expert_query("Reinigung", region="DE")
        with self.assertRaises(ValueError):
            build_expert_query("Reinigung", region="AT")
        with self.assertRaises(ValueError):
            build_expert_query("Reinigung", country_code="AUT")

    def test_rejects_empty_or_unsupported_input(self):
        with self.assertRaises(ValueError):
            build_expert_query("   ")
        with self.assertRaises(ValueError):
            build_expert_query("cleaning; DROP")

    def test_multilingual_title_and_buyer_prefer_german(self):
        notice = _normalise_notice({
            "notice-title": {
                "eng": "Germany – Building-cleaning services",
                "ukr": "Німеччина – Послуги з прибирання",
                "deu": "Deutschland – Gebäudereinigung",
            },
            "publication-number": "12345-2026",
            "buyer-name": {
                "eng": "City of Example",
                "deu": "Stadt Beispiel",
            },
            "place-of-performance-city-proc": ["Viersen"],
            "place-of-performance-subdiv-proc": ["DEA1"],
        })
        self.assertEqual(notice["title"], "Deutschland – Gebäudereinigung")
        self.assertEqual(notice["buyer"], "Stadt Beispiel")
        self.assertIn("Viersen", notice["location"])
        self.assertIn("DEA1", notice["location"])

    def test_falls_back_to_english_when_german_missing(self):
        notice = _normalise_notice({
            "notice-title": {"eng": "Building-cleaning services"},
        })
        self.assertEqual(notice["title"], "Building-cleaning services")


    def test_multilingual_buyer_name_arrays_choose_german_and_hide_other_languages(self):
        notice = _normalise_notice({
            "notice-title": {
                "eng": "Building-cleaning services",
                "deu": "Gebäudereinigung",
            },
            "buyer-name": {
                "eng": ["City of Example"],
                "nld": ["Gemeente Voorbeeld"],
                "deu": ["Stadt Beispiel"],
            },
        })
        self.assertEqual(notice["title"], "Gebäudereinigung")
        self.assertEqual(notice["buyer"], "Stadt Beispiel")

        no_german = _normalise_notice({
            "notice-title": {"hun": "Németország – takarítás"},
            "buyer-name": {"nld": ["Gemeente Voorbeeld"]},
        })
        self.assertEqual(no_german["title"], "Ohne Titel")
        self.assertEqual(no_german["buyer"], "")

    def test_extracts_buyer_and_contact_address_and_phone_fields(self):
        notice = _normalise_notice({
            "notice-title": {"deu": "Gebäudereinigung"},
            "buyer-name": {"deu": ["Stadt Beispiel"]},
            "organisation-street-buyer": {"deu": "Rathausplatz 1"},
            "buyer-post-code": "41747",
            "buyer-city": {"deu": "Viersen"},
            "organisation-tel-buyer": "+49 2162 100",
            "touchpoint-street-buyer": {"deu": "Kreishausstraße 2"},
            "buyer-touchpoint-post-code": "41747",
            "touchpoint-city-buyer": {"deu": "Viersen"},
            "touchpoint-tel-buyer": "+49 2162 200",
        })
        self.assertEqual(notice["buyer_street"], "Rathausplatz 1")
        self.assertEqual(notice["buyer_postcode"], "41747")
        self.assertEqual(notice["buyer_city"], "Viersen")
        self.assertEqual(notice["phone"], "+49 2162 200")
        self.assertEqual(notice["contact_street"], "Kreishausstraße 2")
        self.assertEqual(notice["contact_postcode"], "41747")
        self.assertEqual(notice["contact_city"], "Viersen")

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
        self.assertEqual(notice["email"], "")
        self.assertEqual(notice["phone"], "")
        self.assertEqual(notice["completeness"]["present"], 1)
        self.assertIn("Originalunterlagen", notice["evidence_note"])

    def test_extracts_public_buyer_contact_and_tender_requirements(self):
        notice = _normalise_notice({
            "notice-title": {"deu": "Unterhaltsreinigung"},
            "buyer-name": {"deu": "Stadt Viersen"},
            "buyer-contact-point": {"deu": "Vergabestelle"},
            "buyer-person": {"deu": "Max Beispiel"},
            "buyer-email": "vergabe@example.de",
            "organisation-tel-buyer": "+49 2162 12345",
            "description-proc": {"deu": "Reinigung von Schulgebäuden"},
            "selection-criterion-description-lot": {"deu": "Referenzen erforderlich"},
            "award-criterion-description-lot": {"deu": "Preis und Qualität"},
            "estimated-value-proc": "100000",
            "estimated-value-cur-proc": "EUR",
            "document-url-lot": "https://example.de/unterlagen",
            "submission-url-lot": "https://example.de/abgabe",
            "deadline": "2026-12-01",
        })
        self.assertEqual(notice["contact_person"], "Max Beispiel")
        self.assertEqual(notice["email"], "vergabe@example.de")
        self.assertEqual(notice["phone"], "+49 2162 12345")
        self.assertEqual(notice["selection_criteria"], "Referenzen erforderlich")
        self.assertEqual(notice["award_criteria"], "Preis und Qualität")
        self.assertEqual(notice["completeness"]["present"], 10)


if __name__ == "__main__":
    unittest.main()
