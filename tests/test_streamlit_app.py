import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StreamlitAppTests(unittest.TestCase):
    def test_app_has_valid_python_syntax(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        ast.parse(source, filename="app.py")


    def test_ted_dashboard_uses_the_nrw_active_notice_search(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("Ausschreibungen (TED)", source)
        self.assertIn("search_active_notices(", source)
        self.assertIn('region="NRW"', source)
        self.assertIn("keine automatische Kontaktaufnahme oder Angebotsabgabe", source)

    def test_free_mode_does_not_call_metered_public_web_search(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("TAVILY_API_KEY", source)
        self.assertNotIn("cached_public_lead_search", source)
        self.assertNotIn("search_public_leads(", source)
        self.assertIn("Kostenloser Modus", source)

    def test_brevo_email_marketing_tab_is_consent_gated_and_draft_only(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("E-Mail-Marketing", source)
        self.assertIn("create_doi_contact(", source)
        self.assertIn("create_campaign_draft(", source)
        self.assertIn("Keine Versand- oder Planungsfunktion", source)
        self.assertIn("BREVO_API_KEY", source)
        self.assertNotIn("send_campaign(", source)

    def test_streamlit_requirement_is_not_html_escaped(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("streamlit>=1.40,<2.0", requirements)
        self.assertNotIn("&lt;", requirements)


if __name__ == "__main__":
    unittest.main()
