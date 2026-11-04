import ast
from pathlib import Path
import unittest


class DashboardSyntaxTests(unittest.TestCase):
    def test_app_is_valid_python(self):
        source = Path(__file__).resolve().parents[1] / "app.py"
        ast.parse(source.read_text(encoding="utf-8"), filename=str(source))


if __name__ == "__main__":
    unittest.main()
