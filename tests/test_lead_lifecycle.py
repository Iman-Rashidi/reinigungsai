import unittest
from datetime import date

from src.lead_lifecycle import (
    compare_ad_snapshots,
    detect_ad_status,
    find_duplicate_pairs,
    normalize_lead,
)


class LeadLifecycleTests(unittest.TestCase):
    def test_detects_same_order_across_different_portals(self):
        records = [
            {
                "title": "Gebäudereinigung für Bürogebäude gesucht",
                "city": "Viersen",
                "category": "Reinigung",
                "source": "Portal A",
                "url": "https://portal-a.example/jobs/123",
            },
            {
                "title": "Gebaeudereinigung fuer Buerogebaeude gesucht",
                "city": "Viersen",
                "category": "Reinigung",
                "source": "Portal B",
                "url": "https://portal-b.example/order/987",
            },
        ]
        pairs = find_duplicate_pairs(records)
        self.assertEqual(len(pairs), 1)
        self.assertTrue(pairs[0]["cross_portal"])
        self.assertIn("similar_title_same_location", pairs[0]["reasons"])

    def test_exact_url_ignores_tracking_parameters_and_www(self):
        records = [
            {"title": "Auftrag", "url": "https://www.example.de/jobs/1?utm_source=a", "source": "A"},
            {"title": "Andere Überschrift", "url": "http://example.de/jobs/1?ref=b", "source": "B"},
        ]
        # Canonical URL normalization intentionally upgrades scheme and drops query.
        self.assertEqual(len(find_duplicate_pairs(records)), 1)
        self.assertEqual(normalize_lead(records[0])["url"], "https://example.de/jobs/1")

    def test_empty_titles_do_not_create_fuzzy_duplicates(self):
        records = [
            {"title": "", "city": "Viersen", "category": "Reinigung", "source": "A"},
            {"title": "", "city": "Viersen", "category": "Reinigung", "source": "B"},
        ]
        self.assertEqual(find_duplicate_pairs(records), [])

    def test_unsafe_and_non_http_urls_are_not_canonicalized(self):
        records = [
            {"title": "Same", "url": "javascript://example.de/jobs/1", "source": "A"},
            {"title": "Same", "url": "https://example.de/jobs/1", "source": "B"},
        ]
        self.assertEqual(len(find_duplicate_pairs(records)), 0)

    def test_identical_external_identifier_is_a_strong_match(self):
        records = [
            {"title": "Unterschiedlicher Titel A", "external_id": "TED-123", "source": "A"},
            {"title": "Unterschiedlicher Titel B", "external_id": "TED-123", "source": "B"},
        ]
        pairs = find_duplicate_pairs(records)
        self.assertEqual(len(pairs), 1)
        self.assertIn("same_external_id", pairs[0]["reasons"])

    def test_similar_titles_in_different_cities_are_not_duplicates(self):
        records = [
            {"title": "Gebäudereinigung gesucht", "city": "Viersen", "category": "Reinigung"},
            {"title": "Gebäudereinigung gesucht", "city": "Köln", "category": "Reinigung"},
        ]
        self.assertEqual(find_duplicate_pairs(records), [])

    def test_unrelated_categories_are_not_fuzzy_duplicates(self):
        records = [
            {"title": "Dienstleister gesucht", "city": "Viersen", "category": "Reinigung"},
            {"title": "Dienstleister gesucht", "city": "Viersen", "category": "Sicherheit"},
        ]
        self.assertEqual(find_duplicate_pairs(records), [])

    def test_explicit_past_deadline_marks_ad_expired(self):
        result = detect_ad_status({"deadline": "2026-11-07"}, today=date(2026, 11, 8))
        self.assertEqual(result["status"], "expired")
        self.assertEqual(result["reason"], "deadline_passed")

    def test_explicit_closed_status_marks_expired(self):
        result = detect_ad_status({"status": "abgelaufen"}, today=date(2026, 11, 8))
        self.assertEqual(result["status"], "expired")
        self.assertEqual(result["reason"], "explicit_status")

    def test_old_last_seen_without_deadline_is_stale_not_expired(self):
        result = detect_ad_status(
            {"last_seen": "2026-09-01"},
            today=date(2026, 11, 8),
            stale_after_days=30,
        )
        self.assertEqual(result["status"], "stale")

    def test_missing_lifecycle_evidence_is_unknown(self):
        result = detect_ad_status({}, today=date(2026, 11, 8))
        self.assertEqual(result["status"], "unknown")

    def test_snapshot_comparison_reports_only_changed_fields(self):
        previous = {"title": "Reinigung", "deadline": "2026-12-01", "location": "Viersen"}
        current = {"title": "Reinigung für Schule", "deadline": "2026-12-15", "location": "Viersen"}
        result = compare_ad_snapshots(previous, current)
        self.assertTrue(result["changed"])
        self.assertEqual(set(result["changed_fields"]), {"title", "deadline"})
        self.assertEqual(result["change_count"], 2)

    def test_identical_snapshots_have_no_changes(self):
        snapshot = {"title": "Reinigung", "deadline": "2026-12-01"}
        result = compare_ad_snapshots(snapshot, dict(snapshot))
        self.assertFalse(result["changed"])
        self.assertEqual(result["change_count"], 0)


if __name__ == "__main__":
    unittest.main()
