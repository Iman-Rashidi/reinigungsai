import json
import unittest
from unittest.mock import patch

from src.opportunity_engine.adapters import search_ted_paginated


class FakeResponse:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.value).encode("utf-8")


def notice(number, title):
    return {
        "publication-number": number,
        "notice-title": {"deu": title},
        "buyer-name": {"deu": "Stadt Viersen"},
        "publication-date": "2026-11-07",
        "deadline": "2026-12-01",
        "place-of-performance-city-proc": ["Viersen"],
        "place-of-performance-subdiv-proc": ["DEA1"],
        "description-proc": {"deu": "Öffentliche Ausschreibung Gebäudereinigung"},
        "url": "https://ted.europa.eu/notice/" + number,
    }


class TedPaginationTests(unittest.TestCase):
    def test_iteration_token_fetches_subsequent_pages(self):
        pages = [
            {"notices": [notice("1-2026", "Unterhaltsreinigung")], "iterationNextToken": "cursor-2"},
            {"notices": [notice("2-2026", "Gebäudereinigung")], "iterationNextToken": None},
        ]
        with patch("src.opportunity_engine.adapters.urlopen", side_effect=[FakeResponse(pages[0]), FakeResponse(pages[1])]) as mocked:
            items = search_ted_paginated("Gebäudereinigung", max_pages=4, per_page=100)
        self.assertEqual(len(items), 2)
        self.assertEqual(mocked.call_count, 2)
        second_request = mocked.call_args_list[1].args[0]
        body = json.loads(second_request.data.decode("utf-8"))
        self.assertEqual(body["paginationMode"], "ITERATION")
        self.assertEqual(body["iterationNextToken"], "cursor-2")


if __name__ == "__main__":
    unittest.main()
