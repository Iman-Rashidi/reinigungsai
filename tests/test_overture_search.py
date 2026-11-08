import json
import unittest
from unittest.mock import patch

from src import overture_search


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.payload


class FakeBatch:
    def __init__(self, rows):
        self.rows = rows

    def to_pylist(self):
        return self.rows


class OvertureSearchTests(unittest.TestCase):
    def test_city_bbox_geocoder_matches_exact_city_and_normalises_latitude_order(self):
        payload = {
            "features": [
                {"properties": {
                    "name": "Köln", "countrycode": "DE",
                    "extent": [6.772, 51.084, 7.162, 50.830],
                }},
                {"properties": {
                    "name": "Mönchengladbach", "countrycode": "DE",
                    "extent": [6.3, 51.3, 6.6, 51.0],
                }},
            ]
        }
        with patch("src.overture_search.urlopen", return_value=FakeResponse(payload)):
            bbox = overture_search.geocode_city_bbox("Koln")
        self.assertEqual(bbox, (6.772, 50.830, 7.162, 51.084))

    def test_city_geocoder_rejects_a_different_city(self):
        payload = {"features": [{"properties": {
            "name": "Mönchengladbach", "countrycode": "DE",
            "extent": [6.3, 51.3, 6.6, 51.0],
        }}]}
        with patch("src.overture_search.urlopen", return_value=FakeResponse(payload)):
            with self.assertRaises(overture_search.OvertureSearchError):
                overture_search.geocode_city_bbox("Köln")

    def test_category_filter_includes_cleaning_companies_only(self):
        rows = [
            {
                "id": "gers-1",
                "names": {"primary": "Rhein Reinigung GmbH"},
                "taxonomy": {"primary": "commercial_cleaning", "hierarchy": ["services_and_business", "cleaning"]},
                "confidence": 0.95,
                "operating_status": "open",
                "addresses": [{"freeform": "Domstraße 1, Köln", "postcode": "50667"}],
                "phones": ["+49 221 123456"],
                "emails": ["info@example.de"],
                "websites": ["example.de"],
            },
            {
                "id": "gers-2",
                "names": {"primary": "Kölner Bäckerei"},
                "taxonomy": {"primary": "bakery", "hierarchy": ["food_and_drink", "bakery"]},
                "confidence": 0.99,
                "operating_status": "open",
                "addresses": [{"freeform": "Markt 2, Köln"}],
            },
        ]
        with patch("src.overture_search.geocode_city_bbox", return_value=(6.7, 50.8, 7.2, 51.1)):
            with patch("src.overture_search._iter_batches", return_value=[FakeBatch(rows)]):
                found = overture_search.search_overture_companies(
                    "Köln", "Anbieter", "Reinigungsunternehmen", limit=100
                )
        self.assertEqual([row["Unternehmen"] for row in found], ["Rhein Reinigung GmbH"])
        self.assertEqual(found[0]["Telefon"], "+49 221 123456")
        self.assertTrue(found[0]["Website"].startswith("https://"))
        self.assertEqual(found[0]["Quelle"], "Overture Maps")

    def test_closed_or_low_confidence_records_are_not_returned(self):
        records = [
            {
                "names": {"primary": "Geschlossen"},
                "taxonomy": {"primary": "commercial_cleaning"},
                "operating_status": "permanently_closed",
            },
            {
                "names": {"primary": "Unsicher"},
                "taxonomy": {"primary": "commercial_cleaning"},
                "confidence": 0.1,
            },
        ]
        with patch("src.overture_search.geocode_city_bbox", return_value=(6.7, 50.8, 7.2, 51.1)):
            with patch("src.overture_search._iter_batches", return_value=[FakeBatch(records)]):
                found = overture_search.search_overture_companies(
                    "Köln", "Anbieter", "Reinigungsunternehmen", limit=100
                )
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
