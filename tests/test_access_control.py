import unittest

from src.access_control import password_matches


class AccessControlTests(unittest.TestCase):
    def test_missing_configured_password_fails_closed(self):
        self.assertFalse(password_matches("anything", ""))

    def test_matching_password_is_accepted(self):
        self.assertTrue(password_matches("demo-secret", "demo-secret"))

    def test_wrong_password_is_rejected(self):
        self.assertFalse(password_matches("wrong", "demo-secret"))


if __name__ == "__main__":
    unittest.main()
