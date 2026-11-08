"""Short-lived HMAC SSO tokens for the experimental SteuerPilot Pro shell."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any


ISSUER = "steuerpilot-pro"
AUDIENCE = "reinigungsradar"
MAX_TOKEN_TTL_SECONDS = 180
SSO_SECRET_ENV = "STEUERPILOT_RADAR_SSO_SECRET"
LEGACY_SSO_SECRET_ENV = "STEUEERPILOT_RADAR_SSO_SECRET"


def get_sso_secret(environ=None) -> str:
    """Read the shared SSO secret, preferring the correctly-spelled key."""
    source = os.environ if environ is None else environ
    current = str(source.get(SSO_SECRET_ENV) or "").strip()
    if current:
        return current
    return str(source.get(LEGACY_SSO_SECRET_ENV) or "").strip()


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_sso_token(secret: str, *, now: int | None = None, subject: str = "demo-admin") -> str:
    """Create a signed token for the ReinigungsRadar staging audience."""
    if not isinstance(secret, str) or len(secret) < 32:
        raise ValueError("SSO secret must contain at least 32 characters")
    issued_at = int(time.time() if now is None else now)
    payload = {
        "aud": AUDIENCE,
        "exp": issued_at + MAX_TOKEN_TTL_SECONDS,
        "iat": issued_at,
        "iss": ISSUER,
        "sub": str(subject),
    }
    encoded = _b64url_encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{_b64url_encode(signature)}"


def verify_sso_token(
    token: str,
    secret: str,
    *,
    now: int | None = None,
) -> dict[str, Any] | None:
    """Return the verified claims or None; malformed tokens never raise."""
    if not isinstance(token, str) or len(token) > 2048 or not isinstance(secret, str) or len(secret) < 32:
        return None
    try:
        encoded, supplied_signature = token.split(".", 1)
        if not encoded or not supplied_signature or "." in supplied_signature:
            return None
        expected = hmac.new(
            secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
        ).digest()
        actual = _b64url_decode(supplied_signature)
        if not hmac.compare_digest(actual, expected):
            return None
        claims = json.loads(_b64url_decode(encoded).decode("utf-8"))
        if not isinstance(claims, dict):
            return None
        current = int(time.time() if now is None else now)
        issued_at = claims.get("iat")
        expires_at = claims.get("exp")
        if (
            claims.get("iss") != ISSUER
            or claims.get("aud") != AUDIENCE
            or not isinstance(claims.get("sub"), str)
            or not claims.get("sub")
            or isinstance(issued_at, bool)
            or not isinstance(issued_at, int)
            or isinstance(expires_at, bool)
            or not isinstance(expires_at, int)
            or issued_at > current + 15
            or expires_at <= current
            or expires_at <= issued_at
            or expires_at - issued_at > MAX_TOKEN_TTL_SECONDS
        ):
            return None
        return claims
    except (ValueError, TypeError, UnicodeError, json.JSONDecodeError, base64.binascii.Error):
        return None
