"""Secure API adapter for a self-hosted Listmonk email-marketing instance.

The adapter only creates campaign drafts. Subscriber creation is limited to
documented consent and double-opt-in lists; it never confirms subscriptions.
"""
from __future__ import annotations

import base64
import json
import re
from datetime import date
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class ListmonkConfigurationError(ValueError):
    """Raised when the Listmonk endpoint or credentials are invalid."""


class ListmonkAPIError(RuntimeError):
    """Raised when the Listmonk API rejects or cannot complete a request."""


_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class ListmonkClient:
    """Small HTTPS-only Listmonk client using a least-privilege API account."""

    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        api_token: str,
        timeout: int = 12,
        opener: Callable | None = None,
    ) -> None:
        parsed = urlsplit((base_url or "").strip())
        if (
            parsed.scheme.casefold() != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ListmonkConfigurationError(
                "LISTMONK_URL muss eine gültige HTTPS-Adresse ohne Zugangsdaten sein."
            )
        if not str(username or "").strip() or not str(api_token or "").strip():
            raise ListmonkConfigurationError(
                "LISTMONK_API_USER und LISTMONK_API_TOKEN müssen gesetzt sein."
            )
        if timeout < 1 or timeout > 60:
            raise ListmonkConfigurationError("Der API-Timeout muss zwischen 1 und 60 Sekunden liegen.")

        self.base_url = base_url.strip().rstrip("/")
        self.username = username.strip()
        self.api_token = api_token.strip()
        self.timeout = timeout
        self.opener = opener or urlopen

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        token = base64.b64encode(
            f"{self.username}:{self.api_token}".encode("utf-8")
        ).decode("ascii")
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers={
                "Authorization": f"Basic {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "ReinigungsRadar-Listmonk-Integration/1.0",
            },
            method=method,
        )

        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise ListmonkAPIError(
                    "Listmonk hat die API-Zugangsdaten oder Berechtigungen abgelehnt."
                ) from None
            raise ListmonkAPIError(
                f"Listmonk hat die Anfrage abgelehnt (HTTP {exc.code})."
            ) from None
        except (URLError, TimeoutError, OSError):
            raise ListmonkAPIError(
                "Listmonk ist derzeit nicht erreichbar. HTTPS-Adresse und Netzwerkzugriff prüfen."
            ) from None

        try:
            decoded = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            raise ListmonkAPIError("Listmonk hat keine gültige JSON-Antwort geliefert.") from None
        if not isinstance(decoded, dict):
            raise ListmonkAPIError("Listmonk hat ein unerwartetes Antwortformat geliefert.")
        return decoded

    @staticmethod
    def _data(payload: dict):
        return payload.get("data", payload)

    def get_lists(self) -> list[dict]:
        payload = self._request("GET", "/api/lists")
        data = self._data(payload)
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("results") or data.get("items") or data.get("lists")
        else:
            items = None
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ListmonkAPIError("Listmonk hat keine gültige Listenübersicht geliefert.")
        return items

    def _require_double_optin_lists(self, list_ids: list[int]) -> None:
        if not list_ids:
            raise ValueError("Mindestens eine Double-Opt-in-Liste auswählen.")
        available = {
            int(item["id"]): item
            for item in self.get_lists()
            if str(item.get("id", "")).isdigit()
        }
        for list_id in list_ids:
            item = available.get(list_id)
            if item is None:
                raise ValueError("Eine ausgewählte Listmonk-Liste existiert nicht oder ist nicht verfügbar.")
            if str(item.get("optin", "")).casefold() != "double":
                raise ValueError("Nur Listen mit aktiviertem Double-Opt-in dürfen verwendet werden.")
            if str(item.get("status", "active")).casefold() == "archived":
                raise ValueError("Archivierte Listen können nicht verwendet werden.")

    def add_consented_subscriber(
        self,
        *,
        email: str,
        name: str,
        list_id: int,
        consent_date: str,
        consent_method: str,
        evidence_reference: str,
        consent_confirmed: bool,
    ) -> dict:
        """Create a subscriber with an unconfirmed double-opt-in list membership."""
        email = (email or "").strip()
        name = (name or "").strip()
        evidence_reference = (evidence_reference or "").strip()
        consent_method = (consent_method or "").strip()
        if not _EMAIL_RE.fullmatch(email):
            raise ValueError("Eine gültige E-Mail-Adresse eingeben.")
        if not name:
            raise ValueError("Name oder Unternehmen angeben.")
        if not consent_confirmed:
            raise ValueError("Ohne dokumentierte vorherige ausdrückliche Einwilligung ist keine Aufnahme erlaubt.")
        if not evidence_reference:
            raise ValueError("Eine Nachweisreferenz zur Einwilligung ist erforderlich.")
        try:
            recorded_date = date.fromisoformat((consent_date or "").strip())
        except ValueError:
            raise ValueError("Das Einwilligungsdatum muss im Format YYYY-MM-DD stehen.") from None
        if recorded_date > date.today():
            raise ValueError("Das Einwilligungsdatum darf nicht in der Zukunft liegen.")
        if consent_method not in {
            "E-Mail-Bestätigung",
            "Webformular mit Double-Opt-in",
            "Schriftliche Einwilligung",
        }:
            raise ValueError("Die Art der Einwilligung ist ungültig.")
        try:
            parsed_list_id = int(list_id)
        except (TypeError, ValueError):
            raise ValueError("Eine gültige Double-Opt-in-Liste auswählen.") from None
        if parsed_list_id < 1:
            raise ValueError("Eine gültige Double-Opt-in-Liste auswählen.")

        self._require_double_optin_lists([parsed_list_id])
        payload = {
            "email": email,
            "name": name,
            "status": "enabled",
            "lists": [parsed_list_id],
            "preconfirm_subscriptions": False,
            "attribs": {
                "consent_recorded_date": recorded_date.isoformat(),
                "consent_method": consent_method,
                "consent_evidence_reference": evidence_reference[:300],
                "consent_policy": "prior_explicit_consent_and_double_opt_in",
            },
        }
        return self._request("POST", "/api/subscribers", payload)

    def create_campaign_draft(
        self,
        *,
        name: str,
        subject: str,
        list_ids: list[int],
        body: str,
    ) -> dict:
        """Create a regular Markdown campaign draft; this method never starts it."""
        name = (name or "").strip()
        subject = (subject or "").strip()
        body = (body or "").strip()
        if not name or not subject or not body:
            raise ValueError("Kampagnenname, Betreff und Inhalt sind Pflichtfelder.")
        if len(name) > 200 or len(subject) > 500 or len(body) > 100_000:
            raise ValueError("Ein Kampagnenfeld überschreitet die zulässige Länge.")
        try:
            clean_ids = sorted({int(value) for value in list_ids})
        except (TypeError, ValueError):
            raise ValueError("Ungültige Zielgruppen-Auswahl.") from None
        if not clean_ids or any(value < 1 for value in clean_ids):
            raise ValueError("Mindestens eine gültige Zielgruppe auswählen.")

        self._require_double_optin_lists(clean_ids)
        payload = {
            "name": name,
            "subject": subject,
            "lists": clean_ids,
            "type": "regular",
            "content_type": "markdown",
            "body": body,
        }
        return self._request("POST", "/api/campaigns", payload)
