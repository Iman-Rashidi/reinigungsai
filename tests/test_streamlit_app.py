import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StreamlitAppTests(unittest.TestCase):
    def test_app_has_valid_python_syntax(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        ast.parse(source, filename="app.py")

    def test_streamlit_requirement_is_not_html_escaped(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("streamlit>=1.40,<2.0", requirements)
        self.assertNotIn("&lt;", requirements)


if __name__ == "__main__":
    unittest.main()
