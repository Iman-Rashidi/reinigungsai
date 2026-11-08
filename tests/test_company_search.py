import json
import os
import unittest
from unittest.mock import patch

from src import company_search


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.payload


class CompanySearchTests(unittest.TestCase):
    def test_query_targets_the_requested_city_not_the_pilot_city(self):
        query = company_search.build_company_query(
            "Köln", "Kunden", "Büros und Unternehmen"
        )
        self.assertIn('"name"="Köln"', query)
        self.assertNotIn('"name"="Mönchengladbach"', query)

    def test_city_comparison_handles_umlauts_and_city_prefixes(self):
        self.assertTrue(company_search._same_city("Kreisfreie Stadt Köln", "Koln"))
        self.assertTrue(company_search._same_city("Düsseldorf", "Dusseldorf"))
        self.assertFalse(company_search._same_city("Mönchengladbach", "Köln"))

    def test_overpass_results_from_other_cities_are_discarded(self):
        payload = {
            "elements": [
                {
                    "type": "node",
                    "id": 1,
                    "tags": {
                        "name": "Kölner Büro",
                        "office": "company",
                        "addr:city": "Köln",
                    },
                },
                {
                    "type": "node",
                    "id": 2,
                    "tags": {
                        "name": "Mönchengladbacher Büro",
                        "office": "company",
                        "addr:city": "Mönchengladbach",
                    },
                },
            ]
        }
        with patch("src.company_search.urlopen", return_value=FakeResponse(payload)):
            result = company_search.search_companies(
                "Köln", "Kunden", "Büros und Unternehmen", limit=10
            )
        self.assertEqual(result["city"], "Köln")
        self.assertEqual([row["Unternehmen"] for row in result["rows"]], ["Kölner Büro"])
        self.assertEqual(result["rows"][0]["Stadt"], "Köln")

    def test_google_places_key_is_ignored_and_never_called(self):
        payload = {"elements": []}
        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "must-not-be-used"}):
            with patch(
                "src.company_search.urlopen", return_value=FakeResponse(payload)
            ) as mocked_urlopen:
                company_search.search_companies(
                    "Köln", "Kunden", "Büros und Unternehmen", limit=10
                )
        request = mocked_urlopen.call_args.args[0]
        self.assertIn("overpass", request.full_url)
        self.assertNotIn("googleapis.com", request.full_url)

    def test_photon_fallback_rejects_results_without_an_exact_city_match(self):
        payload = {
            "features": [
                {
                    "properties": {
                        "name": "Firma in Köln",
                        "city": "Köln",
                        "osm_id": 11,
                        "osm_type": "n",
                    }
                },
                {
                    "properties": {
                        "name": "Firma in Mönchengladbach",
                        "city": "Mönchengladbach",
                        "osm_id": 12,
                        "osm_type": "n",
                    }
                },
                {
                    "properties": {
                        "name": "Unklarer Treffer",
                        "district": "Ehrenfeld",
                        "osm_id": 13,
                        "osm_type": "n",
                    }
                },
            ]
        }
        with patch("src.company_search.urlopen", return_value=FakeResponse(payload)):
            result = company_search._photon_search(
                "Köln", "Kunden", "Büros und Unternehmen", limit=10, timeout=5
            )
        self.assertEqual([row["Unternehmen"] for row in result["rows"]], ["Firma in Köln"])
        self.assertTrue(all(row["Stadt"] == "Köln" for row in result["rows"]))


if __name__ == "__main__":
    unittest.main()
