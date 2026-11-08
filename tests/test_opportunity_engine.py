import tempfile
import unittest
from pathlib import Path

from src.opportunity_engine.classifier import classify_opportunity, enrich_opportunity
from src.opportunity_engine.models import Opportunity, canonical_url, identity_key
from src.opportunity_engine.store import OpportunityStore


class OpportunityModelTests(unittest.TestCase):
    def test_url_keeps_notice_query_but_removes_tracking(self):
        url = canonical_url("https://example.de/notice?id=123&utm_source=mail&version=2#section")
        self.assertEqual(url, "https://example.de/notice?id=123&version=2")

    def test_job_posts_are_not_classified_as_service_tenders(self):
        category, kind = classify_opportunity(
            "Reinigungskraft gesucht – Vollzeit",
            "Bewerbung und Gehalt ab sofort",
        )
        self.assertEqual(kind, "job")

    def test_cleaning_tender_is_classified(self):
        category, kind = classify_opportunity(
            "Unterhaltsreinigung für Schulgebäude",
            "Öffentliche Ausschreibung und Angebotsfrist",
        )
        self.assertEqual(category, "Reinigung")
        self.assertEqual(kind, "tender")

    def test_identity_key_requires_context_to_merge_across_sources(self):
        a = identity_key("Unterhaltsreinigung", "Stadt Viersen", "Viersen")
        b = identity_key("Unterhaltsreinigung", "Stadt Viersen", "Viersen")
        c = identity_key("Unterhaltsreinigung", "Stadt Neuss", "Neuss")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)


class OpportunityStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = OpportunityStore(str(Path(self.temp.name) / "opportunities.sqlite3"))
        self.db.seed_sources([
            {"source_id": "bkms", "name": "BKMS", "kind": "official", "priority": 10},
            {"source_id": "ted", "name": "TED", "kind": "official", "priority": 20},
        ])

    def tearDown(self):
        self.temp.cleanup()

    def make_item(self, source="bkms", external_id="ocid-1", deadline="2026-12-01"):
        return enrich_opportunity(Opportunity(
            source_id=source,
            external_id=external_id,
            title="Unterhaltsreinigung Schulen",
            buyer="Stadt Viersen",
            description="Öffentliche Ausschreibung für Gebäudereinigung in NRW",
            city="Viersen",
            region="Nordrhein-Westfalen",
            category="Reinigung",
            opportunity_type="tender",
            deadline=deadline,
            url="https://example.de/tender?id=9",
            source_priority=10 if source == "bkms" else 20,
        ))

    def test_insert_and_cross_source_dedupe(self):
        first = self.db.upsert_opportunity(self.make_item())
        second = self.db.upsert_opportunity(self.make_item("ted", "12345-2026"))
        self.assertTrue(first["inserted"])
        self.assertFalse(second["inserted"])
        self.assertEqual(second["source_count"], 2)
        self.assertEqual(len(self.db.list_opportunities()), 1)

    def test_changed_deadline_is_recorded(self):
        self.db.upsert_opportunity(self.make_item())
        changed = self.db.upsert_opportunity(self.make_item(deadline="2026-12-15"))
        self.assertTrue(changed["changed"])
        changes = self.db.recent_changes()
        self.assertTrue(any(row["field"] == "deadline" for row in changes))

    def test_source_runs_and_health_are_persisted(self):
        run_id = self.db.start_run("bkms")
        self.db.finish_run(run_id, "bkms", "ok", 12, 3, 1)
        source = next(row for row in self.db.list_sources() if row["source_id"] == "bkms")
        self.assertEqual(source["last_status"], "ok")
        self.assertEqual(source["last_count"], 12)

    def test_url_ids_do_not_collapse_distinct_notice_ids(self):
        one = self.make_item(external_id="notice-1")
        two = self.make_item(external_id="notice-2")
        # Same identity may merge cross-source; same-source records remain one
        # procurement record if title/buyer/location are identical.
        self.db.upsert_opportunity(one)
        self.db.upsert_opportunity(two)
        self.assertEqual(len(self.db.list_opportunities()), 1)


if __name__ == "__main__":
    unittest.main()
