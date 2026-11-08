import json
import unittest
from datetime import date
from urllib.error import HTTPError

from src.listmonk_client import (
    ListmonkAPIError,
    ListmonkClient,
    ListmonkConfigurationError,
)


class FakeResponse:
    def __init__(self, payload):
        self.raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.raw


class RawResponse(FakeResponse):
    def __init__(self, raw):
        self.raw = raw


class FakeOpener:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        if isinstance(payload, RawResponse):
            return payload
        return FakeResponse(payload)


class ListmonkClientTests(unittest.TestCase):
    def client(self, opener):
        return ListmonkClient(
            base_url="https://mail.example.test",
            username="radar-api",
            api_token="test-api-token",
            opener=opener,
        )

    def test_requires_https_and_credentials(self):
        with self.assertRaises(ListmonkConfigurationError):
            ListmonkClient(
                base_url="http://mail.example.test",
                username="radar-api",
                api_token="token",
            )
        with self.assertRaises(ListmonkConfigurationError):
            ListmonkClient(
                base_url="https://mail.example.test",
                username="",
                api_token="token",
            )

    def test_get_lists_sends_basic_auth_and_parses_response(self):
        opener = FakeOpener({"data": {"results": [{"id": 7, "name": "Opt-in", "optin": "double"}], "total": 1, "per_page": "all", "page": 1}})
        lists = self.client(opener).get_lists()
        self.assertEqual(lists[0]["id"], 7)
        request, timeout = opener.requests[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.full_url, "https://mail.example.test/api/lists?per_page=all")
        self.assertTrue(request.get_header("Authorization").startswith("Basic "))
        self.assertGreaterEqual(timeout, 1)

    def test_get_lists_handles_real_listmonk_paginated_response(self):
        opener = FakeOpener({
            "data": {
                "results": [{"id": 12, "name": "Kunden", "optin": "double", "status": "active"}],
                "total": 1,
                "per_page": 100,
                "page": 1,
            }
        })
        lists = self.client(opener).get_lists()
        self.assertEqual(lists, [{"id": 12, "name": "Kunden", "optin": "double", "status": "active"}])

    def test_add_subscriber_requires_proof_and_double_optin(self):
        opener = FakeOpener({"data": {"results": [{"id": 7, "optin": "single"}]}})
        with self.assertRaises(ValueError):
            self.client(opener).add_consented_subscriber(
                email="hello@example.test",
                name="Test GmbH",
                list_id=7,
                consent_date=date.today().isoformat(),
                consent_method="E-Mail-Bestätigung",
                evidence_reference="proof-1",
                consent_confirmed=True,
            )
        self.assertEqual(len(opener.requests), 1)

    def test_add_subscriber_never_preconfirms_double_optin(self):
        opener = FakeOpener(
            {"data": {"results": [{"id": 7, "name": "Opt-in", "optin": "double", "status": "active"}]}},
            {"data": {"id": 99, "email": "hello@example.test"}},
        )
        self.client(opener).add_consented_subscriber(
            email="hello@example.test",
            name="Test GmbH",
            list_id=7,
            consent_date=date.today().isoformat(),
            consent_method="Webformular mit Double-Opt-in",
            evidence_reference="webform-entry-123",
            consent_confirmed=True,
        )
        request, _ = opener.requests[1]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertFalse(payload["preconfirm_subscriptions"])
        self.assertEqual(payload["lists"], [7])
        self.assertEqual(payload["attribs"]["consent_evidence_reference"], "webform-entry-123")

    def test_draft_campaign_only_targets_double_optin_lists(self):
        opener = FakeOpener(
            {"data": {"results": [{"id": 7, "optin": "double", "status": "active"}]}},
            {"data": {"id": 42, "status": "draft"}},
        )
        result = self.client(opener).create_campaign_draft(
            name="Pilot",
            subject="Information",
            list_ids=[7],
            body="Guten Tag",
        )
        self.assertEqual(result["data"]["status"], "draft")
        request, _ = opener.requests[1]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(payload["content_type"], "markdown")
        self.assertNotIn("status", payload)
        self.assertNotIn("send_at", payload)

    def test_campaign_cannot_target_single_optin_list(self):
        opener = FakeOpener({"data": {"results": [{"id": 3, "optin": "single"}]}})
        with self.assertRaises(ValueError):
            self.client(opener).create_campaign_draft(
                name="Pilot",
                subject="Information",
                list_ids=[3],
                body="Text",
            )
        self.assertEqual(len(opener.requests), 1)

    def test_non_json_response_is_rejected(self):
        opener = FakeOpener(RawResponse(b"not-json"))
        with self.assertRaises(ListmonkAPIError):
            self.client(opener).get_lists()

    def test_api_authentication_errors_do_not_leak_response_body(self):
        error = HTTPError(
            "https://mail.example.test/api/lists",
            401,
            "Unauthorized",
            hdrs=None,
            fp=None,
        )
        opener = FakeOpener(error)
        with self.assertRaises(ListmonkAPIError) as context:
            self.client(opener).get_lists()
        self.assertNotIn("test-api-token", str(context.exception))

    def test_invalid_date_and_missing_consent_are_rejected_before_api_calls(self):
        opener = FakeOpener({"data": []})
        client = self.client(opener)
        with self.assertRaises(ValueError):
            client.add_consented_subscriber(
                email="hello@example.test",
                name="Test GmbH",
                list_id=7,
                consent_date="not-a-date",
                consent_method="E-Mail-Bestätigung",
                evidence_reference="proof-1",
                consent_confirmed=True,
            )
        with self.assertRaises(ValueError):
            client.add_consented_subscriber(
                email="hello@example.test",
                name="Test GmbH",
                list_id=7,
                consent_date=date.today().isoformat(),
                consent_method="E-Mail-Bestätigung",
                evidence_reference="proof-1",
                consent_confirmed=False,
            )
        self.assertEqual(len(opener.requests), 0)


if __name__ == "__main__":
    unittest.main()
