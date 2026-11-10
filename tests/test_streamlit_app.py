import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StreamlitAppTests(unittest.TestCase):
    def test_app_has_valid_python_syntax(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        ast.parse(source, filename="app.py")


    def test_staging_has_no_login_or_password_gate(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("get_sso_secret", source)
        self.assertNotIn("verify_sso_token", source)
        self.assertNotIn("APP_PASSWORD", source)
        self.assertNotIn("password_matches(", source)
        self.assertNotIn("Der direkte Zugang ist deaktiviert", source)
        self.assertNotIn("Abmelden", source)

    def test_public_passwordless_ui_has_no_trial_or_central_login_copy(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("Pilot", source)
        self.assertNotIn("MVP", source)
        self.assertNotIn("Der Zugriff erfolgt ausschließlich über die zentrale SteuerPilot-Anmeldung", source)
        self.assertIn("Öffentlicher Zugriff ohne Anmeldung", source)

    def test_ted_dashboard_uses_the_nrw_active_notice_search(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("Ausschreibungen (TED)", source)
        self.assertIn("search_active_notices(", source)
        self.assertIn('region="NRW"', source)
        self.assertIn("keine automatische Kontaktaufnahme oder Angebotsabgabe", source)

    def test_streamlit_requirement_is_not_html_escaped(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("streamlit>=1.40,<2.0", requirements)
        self.assertNotIn("&lt;", requirements)


if __name__ == "__main__":
    unittest.main()
