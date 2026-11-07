"""Basic shared-password gate for the public staging app.

This is a staging safeguard only, not production identity or authorization.
"""
import hmac


def password_matches(candidate: str, configured_password: str) -> bool:
    """Compare a submitted password without a plain string equality check."""
    if not configured_password:
        return False
    return hmac.compare_digest(str(candidate), str(configured_password))
