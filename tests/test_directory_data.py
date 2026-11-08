import unittest

from directory_data import (
    CUSTOMER_COLUMNS,
    PROVIDER_COLUMNS,
    complete_rows,
    csv_bytes,
    filter_rows,
    pages_to_rows,
    property_text,
)


class DirectoryDataTests(unittest.TestCase):
    def test_property_text_reads_notion_title_rich_text_select_number_and_date(self):
        self.assertEqual(property_text({"title": [{"plain_text": "Beispiel GmbH"}]}), "Beispiel GmbH")
        self.assertEqual(property_text({"rich_text": [{"plain_text": "Industrie"}]}), "Industrie")
        self.assertEqual(property_text({"select": {"name": "Mittel"}}), "Mittel")
        self.assertEqual(property_text({"number": 0}), "0")
        self.assertEqual(property_text({"date": {"start": "2026-11-04"}}), "2026-11-04")
        self.assertEqual(
            property_text({"date": {"start": "2026-11-04", "end": "2026-11-06"}}),
            "2026-11-04 – 2026-11-06",
        )

    def test_pages_to_rows_discards_empty_notion_placeholder_rows(self):
        pages = [
            {"properties": {
                "Unternehmen": {"title": [{"plain_text": "Beispiel GmbH"}]},
                "Branche": {"rich_text": [{"plain_text": "Industrie"}]},
                "Stadt": {"rich_text": [{"plain_text": "Mönchengladbach"}]},
                "Prüfdatum": {"date": {"start": "2026-11-04"}},
                "Score": {"number": 2},
            }},
            {"properties": {"Unternehmen": {"title": []}, "Stadt": {"rich_text": []}}},
        ]
        rows = pages_to_rows(pages)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Unternehmen"], "Beispiel GmbH")
        self.assertEqual(rows[0]["Prüfdatum"], "2026-11-04")
        self.assertEqual(rows[0]["Score"], "2")

    def test_pages_to_rows_accepts_flattened_notion_records(self):
        records = [
            {"Unternehmen": "Trützschler Group SE", "Branche": "Industrie", "Stadt": "Mönchengladbach"},
            {"Unternehmen": "", "Branche": "", "Stadt": ""},
        ]
        rows = pages_to_rows(records)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Unternehmen"], "Trützschler Group SE")
        self.assertEqual(rows[0]["Branche"], "Industrie")

    def test_complete_rows_aligns_to_real_customer_and_provider_schemas(self):
        customer = complete_rows([{"Unternehmen": "Beispiel", "Branche": "Industrie"}], CUSTOMER_COLUMNS)[0]
        provider = complete_rows([{"Unternehmen": "Dienstleister", "Dienstleistung": "Reinigung"}], PROVIDER_COLUMNS)[0]
        self.assertEqual(customer["Branche"], "Industrie")
        self.assertIn("Quelle / Hinweis", customer)
        self.assertEqual(provider["Dienstleistung"], "Reinigung")
        self.assertIn("Datenstatus", provider)

    def test_filters_city_category_and_search_independently(self):
        rows = [
            {"Unternehmen": "Beispiel GmbH", "Stadt": "Mönchengladbach", "Branche": "Industrie"},
            {"Unternehmen": "Andere AG", "Stadt": "Düsseldorf", "Branche": "Handel"},
        ]
        self.assertEqual(len(filter_rows(rows, city_filter="Mönchen", category_column="Branche")), 1)
        self.assertEqual(len(filter_rows(rows, category_filter="handel", category_column="Branche")), 1)
        self.assertEqual(len(filter_rows(rows, search_text="beispiel")), 1)

    def test_csv_is_utf8_bom_and_contains_expected_headers(self):
        data = csv_bytes([{"Unternehmen": "Beispiel GmbH"}], ["Unternehmen", "Stadt"])
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        self.assertIn("Unternehmen,Stadt".encode("utf-8"), data)


if __name__ == "__main__":
    unittest.main()
