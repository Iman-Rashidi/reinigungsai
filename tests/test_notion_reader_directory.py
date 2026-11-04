import os
import unittest
from unittest.mock import patch

from src.notion_reader import NotionAPIError, query_data_source


class NotionReaderDirectoryTests(unittest.TestCase):
    def test_query_data_source_requires_token(self):
        with patch.dict(os.environ, {"NOTION_TOKEN": ""}, clear=False):
            with self.assertRaises(NotionAPIError):
                query_data_source("a-data-source-id")

    def test_query_data_source_requires_data_source_id(self):
        with patch.dict(os.environ, {"NOTION_TOKEN": "test-token"}, clear=False):
            with self.assertRaises(NotionAPIError):
                query_data_source("")


if __name__ == "__main__":
    unittest.main()
