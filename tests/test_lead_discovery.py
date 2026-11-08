import unittest
from urllib.parse import urlsplit, parse_qs

from src.lead_discovery import (
    build_manual_portal_links,
    build_search_query,
    is_restricted_domain,
    normalise_results,
)


class LeadDiscoveryTests(unittest.TestCase):
    def test_search_query_contains_location_and_service(self):
        query = build_search_query("Viersen", "Reinigung")
        self.assertIn("Viersen", query)
        self.assertIn("Gebäudereinigung", query)
        self.assertIn("Nordrhein-Westfalen", query)

    def test_invalid_category_is_rejected(self):
        with self.assertRaises(ValueError):
            build_search_query("Viersen", "Unbekannt")

    def test_restricted_domains_are_blocked_with_subdomains(self):
        self.assertTrue(is_restricted_domain("www.linkedin.com"))
        self.assertTrue(is_restricted_domain("m.facebook.com"))
        self.assertTrue(is_restricted_domain("my-hammer.de"))
        self.assertFalse(is_restricted_domain("example.de"))

    def test_results_are_deduplicated_and_restricted_platforms_removed(self):
        raw = [
            {
                "title": "Gebäudereinigung gesucht in Viersen",
                "url": "https://example.de/auftrag?utm_source=search",
                "content": "Ausschreibung für Gebäudereinigung in Nordrhein-Westfalen",
                "score": 0.9,
                "published_date": "2026-11-01",
            },
            {
                "title": "Duplicate",
                "url": "https://example.de/auftrag?ref=other",
                "content": "Duplicate record",
                "score": 0.5,
            },
            {
                "title": "LinkedIn post",
                "url": "https://www.linkedin.com/posts/example",
                "content": "Gebäudereinigung gesucht",
                "score": 1.0,
            },
            {
                "title": "MyHammer project",
                "url": "https://www.my-hammer.de/auftrag/123",
                "content": "Reinigungsdienst gesucht",
                "score": 1.0,
            },
        ]
        rows = normalise_results(raw, "Viersen", "Reinigung")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Domain"], "example.de")
        self.assertGreaterEqual(rows[0]["Relevanz"], 50)
        self.assertTrue(rows[0]["Quellenlink"].startswith("https://"))

    def test_manual_portal_shortcuts_include_job_and_social_sources(self):
        links = build_manual_portal_links("Viersen", "Sicherheit")
        labels = {item["label"] for item in links}
        self.assertIn("MyHammer", labels)
        self.assertIn("Facebook", labels)
        self.assertIn("LinkedIn Jobs", labels)
        linkedin = next(item for item in links if item["label"] == "LinkedIn Jobs")
        parsed = urlsplit(linkedin["url"])
        self.assertEqual(parse_qs(parsed.query)["location"], ["Viersen, Nordrhein-Westfalen"])


if __name__ == "__main__":
    unittest.main()
