"""Read-only Notion data-source client.

This module never creates, updates, or deletes Notion content.
Credentials are read only from environment variables.
"""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_BASE = "https://api.notion.com/v1"
DEFAULT_DATA_SOURCE_ID = "e8e0c29f-db71-4908-8344-23d10a5269ec"
DEFAULT_NOTION_VERSION = "2026-03-11"


class NotionAPIError(RuntimeError):
    """Raised when the Notion API request fails."""


def query_data_source(data_source_id: str, page_size: int = 100, max_pages: int = 10) -> list[dict]:
    """Read rows from the specified Notion data source, with bounded pagination."""
    token = os.environ.get("NOTION_TOKEN", "").strip()
    notion_version = os.environ.get("NOTION_VERSION", DEFAULT_NOTION_VERSION).strip()
    data_source_id = (data_source_id or "").strip()
    if not token:
        raise NotionAPIError("NOTION_TOKEN is not configured. Add it as a protected environment secret.")
    if not data_source_id:
        raise NotionAPIError("A Notion data source ID is not configured.")

    url = f"{API_BASE}/data_sources/{data_source_id}/query"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": notion_version,
        "Content-Type": "application/json",
    }
    results: list[dict] = []
    cursor = None

    for _ in range(max(1, min(max_pages, 10))):
        payload = {"page_size": max(1, min(page_size, 100))}
        if cursor:
            payload["start_cursor"] = cursor
        request = Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        try:
            with urlopen(request, timeout=20) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise NotionAPIError(f"Notion API returned HTTP {exc.code}.") from None
        except URLError:
            raise NotionAPIError("Could not reach the Notion API.") from None
        except TimeoutError:
            raise NotionAPIError("The Notion API request timed out.") from None

        results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
        if not cursor:
            break
    return results


def query_leads(page_size: int = 100, max_pages: int = 10) -> list[dict]:
    """Backward-compatible reader for the original customer-lead data source."""
    data_source_id = os.environ.get("NOTION_DATA_SOURCE_ID", DEFAULT_DATA_SOURCE_ID).strip()
    return query_data_source(data_source_id, page_size=page_size, max_pages=max_pages)


def main() -> None:
    leads = query_leads()
    print(f"Read-only Notion check completed: {len(leads)} lead record(s) retrieved.")
    print("No Notion records were changed.")


if __name__ == "__main__":
    main()
