import unittest
from src.notion_reader import extract_title


class NotionReaderTests(unittest.TestCase):
    def test_extracts_title_plain_text(self):
        page = {
            "properties": {
                "Unternehmen": {
                    "type": "title",
                    "title": [
                        {"plain_text": "Beispiel "},
                        {"plain_text": "GmbH"},
                    ],
                }
            }
        }
        self.assertEqual(extract_title(page), "Beispiel GmbH")

    def test_missing_title_returns_empty_string(self):
        self.assertEqual(extract_title({"properties": {}}), "")

    def test_does_not_assume_property_name(self):
        page = {"properties": {"Company": {"title": [{"plain_text": "Test AG"}]}}}
        self.assertEqual(extract_title(page), "Test AG")


if __name__ == "__main__":
    unittest.main()
