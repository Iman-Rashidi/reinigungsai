import json
import unittest
import zipfile
from io import BytesIO

from src.opportunity_engine.adapters import parse_bkms_zip


def make_zip():
    release = {
        "ocid": "ocds-example-2026-001",
        "id": "notice-001-2026",
        "date": "2026-11-07T10:00:00Z",
        "tag": ["tender"],
        "buyer": {"name": "Stadt Viersen"},
        "tender": {
            "title": "Unterhaltsreinigung für Schulen",
            "description": "Öffentliche Ausschreibung für Gebäudereinigung in Nordrhein-Westfalen.",
            "mainProcurementCategory": "services",
            "tenderPeriod": {"endDate": "2026-12-01T10:00:00+01:00"},
            "value": {"amount": 120000, "currency": "EUR"},
            "items": [{
                "classification": {"id": "90911200-8", "scheme": "CPV"},
                "deliveryAddress": {
                    "locality": "Viersen",
                    "region": "Nordrhein-Westfalen",
                    "postalCode": "41747",
                },
            }],
            "documents": [{"url": "https://example.de/tender-documents"}],
        },
    }
    payload = BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("notice-001.json", json.dumps({"releases": [release]}))
    return payload.getvalue()


class BkmsAdapterTests(unittest.TestCase):
    def test_extracts_official_cleaning_tender(self):
        items = parse_bkms_zip(make_zip(), category="Reinigung")
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.source_id, "bkms")
        self.assertEqual(item.external_id, "ocds-example-2026-001")
        self.assertEqual(item.category, "Reinigung")
        self.assertEqual(item.city, "Viersen")
        self.assertEqual(item.deadline[:10], "2026-12-01")
        self.assertEqual(item.estimated_value, "120000")
        self.assertEqual(item.url, "https://example.de/tender-documents")

    def test_skips_other_region_and_unrelated_award_notice(self):
        # The adapter must not convert an unrelated job/award document into a tender.
        source = {
            "ocid": "ocds-other",
            "id": "award-001",
            "date": "2026-11-07",
            "tag": ["award"],
            "buyer": {"name": "Stadt München"},
            "tender": {
                "title": "Unterhaltsreinigung",
                "description": "Vergabe Bayern",
                "tenderPeriod": {"endDate": "2026-12-01"},
                "items": [{
                    "classification": {"id": "90911200-8"},
                    "deliveryAddress": {"locality": "München", "region": "Bayern"},
                }],
            },
        }
        payload = BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("other.json", json.dumps({"releases": [source]}))
        self.assertEqual(parse_bkms_zip(payload.getvalue()), [])


if __name__ == "__main__":
    unittest.main()
