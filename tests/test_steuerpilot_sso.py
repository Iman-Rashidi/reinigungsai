import unittest

from src.steuerpilot_sso import get_sso_secret

from src.steuerpilot_sso import create_sso_token, verify_sso_token


SECRET = "test-only-secret-material-with-at-least-32-characters"


class SteuerPilotSSOTests(unittest.TestCase):
    def test_reads_the_canonical_shared_secret_name(self):
        self.assertEqual(
            get_sso_secret({"STEUERPILOT_RADAR_SSO_SECRET": "  " + SECRET + "  "}),
            SECRET,
        )

    def test_supports_the_existing_misspelled_secret_name(self):
        self.assertEqual(
            get_sso_secret({"STEUEERPILOT_RADAR_SSO_SECRET": SECRET}),
            SECRET,
        )

    def test_canonical_secret_takes_precedence(self):
        canonical = SECRET + "-canonical"
        self.assertEqual(
            get_sso_secret({
                "STEUERPILOT_RADAR_SSO_SECRET": canonical,
                "STEUEERPILOT_RADAR_SSO_SECRET": SECRET,
            }),
            canonical,
        )

    def test_valid_token_returns_expected_claims(self):
        token = create_sso_token(SECRET, now=1_800_000_000)
        claims = verify_sso_token(token, SECRET, now=1_800_000_030)
        self.assertIsNotNone(claims)
        self.assertEqual(claims["sub"], "demo-admin")
        self.assertEqual(claims["aud"], "reinigungsradar")

    def test_wrong_secret_is_rejected(self):
        token = create_sso_token(SECRET, now=1_800_000_000)
        self.assertIsNone(verify_sso_token(token, SECRET + "-wrong", now=1_800_000_030))

    def test_expired_token_is_rejected(self):
        token = create_sso_token(SECRET, now=1_800_000_000)
        self.assertIsNone(verify_sso_token(token, SECRET, now=1_800_000_181))

    def test_malformed_token_is_rejected(self):
        self.assertIsNone(verify_sso_token("not-a-token", SECRET, now=1_800_000_000))

    def test_short_secret_is_rejected(self):
        with self.assertRaises(ValueError):
            create_sso_token("too-short", now=1_800_000_000)


if __name__ == "__main__":
    unittest.main()
