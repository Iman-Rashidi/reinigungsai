import unittest
from src.duplicate_checker import find_possible_duplicates, normalize_domain, normalize_company_name


class DuplicateCheckerTests(unittest.TestCase):
    def test_company_suffix_normalization(self):
        self.assertEqual(normalize_company_name("Beispiel GmbH"), normalize_company_name("Beispiel"))

    def test_domain_normalization(self):
        self.assertEqual(normalize_domain("https://www.example.de/kontakt"), "example.de")

    def test_match_by_domain(self):
        candidate = {"name": "Neue Firma", "website": "https://example.de"}
        existing = [{"name": "Andere Bezeichnung", "website": "www.example.de"}]
        self.assertEqual(len(find_possible_duplicates(candidate, existing)), 1)

    def test_no_match(self):
        candidate = {"name": "Alpha GmbH", "website": "alpha.de"}
        existing = [{"name": "Beta GmbH", "website": "beta.de"}]
        self.assertEqual(find_possible_duplicates(candidate, existing), [])


if __name__ == "__main__":
    unittest.main()
