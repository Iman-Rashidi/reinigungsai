import os
import unittest
from unittest.mock import patch

from src.supabase_leads import (
    normalise_lead_record,
    persist_search_batch,
)


class SupabaseLeadNormalisationTests(unittest.TestCase):
    def test_public_search_record_uses_domain_and_redacts_contacts(self):
        record = normalise_lead_record(
            {
                "Titel": "Gebäudereinigung gesucht",
                "Domain": "portal.example",
                "Suchauszug": "Kontakt: info@example.com oder +49 30 12345678",
                "Quellenlink": "https://www.portal.example/jobs/123?utm_source=test",
                "Relevanz": 88,
                "Signal": "Möglicher Bedarf",
            },
            source="public_web",
            city="Viersen",
            category="Reinigung",
        )
        self.assertEqual(record["source"], "portal.example")
        self.assertEqual(record["canonical_url"], "https://portal.example/jobs/123")
        self.assertNotIn("info@example.com", record["description"])
        self.assertNotIn("12345678", record["description"])
        self.assertEqual(record["ad_status"], "unknown")
        self.assertEqual(record["source_metadata"]["relevance"], 88)

    def test_ted_record_excludes_contact_fields_and_long_description(self):
        record = normalise_lead_record(
            {
                "title": "Gebäudereinigung einer Schule",
                "publication_number": "TED-2026-123",
                "url": "https://ted.europa.eu/notice/123",
                "deadline": "2026-12-15T12:00:00+01:00",
                "description": "Angebotsunterlagen. Kontakt: private.person@example.com",
                "buyer": "Öffentlicher Auftraggeber",
                "email": "private.person@example.com",
                "phone": "+49 211 123456",
                "contact_person": "Private Person",
                "cpv": "90911200",
            },
            source="ted",
            city="NRW",
            category="Reinigung",
        )
        self.assertEqual(record["source"], "ted")
        self.assertEqual(record["external_id"], "TED-2026-123")
        self.assertEqual(record["deadline"], "2026-12-15")
        self.assertEqual(record["ad_status"], "active")
        self.assertIsNone(record["description"])
        self.assertNotIn("email", record)
        self.assertNotIn("phone", record)
        self.assertNotIn("buyer", record)
        self.assertNotIn("contact_person", record)
        self.assertEqual(record["source_metadata"]["cpv"], "90911200")

    def test_invalid_source_url_is_not_canonicalized(self):
        record = normalise_lead_record(
            {"title": "Auftrag", "url": "javascript:alert(1)"},
            source="public_web",
        )
        self.assertIsNone(record["canonical_url"])
        self.assertIsNone(record["original_url"])  # unsafe/non-HTTP URL is not persisted

    def test_empty_title_is_skipped(self):
        self.assertIsNone(
            normalise_lead_record({"title": "   "}, source="ted")
        )

    def test_storage_is_disabled_without_all_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(
                persist_search_batch(
                    source="ted",
                    query="",
                    city="NRW",
                    category="Reinigung",
                    records=[],
                )
            )


if __name__ == "__main__":
    unittest.main()
