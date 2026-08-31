import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / ".github" / "pull_request_template.md"


class PullRequestTemplateTests(unittest.TestCase):
    def test_template_keeps_complete_english_then_complete_korean_sections(self):
        source = TEMPLATE.read_text(encoding="utf-8")

        self.assertIn("Pull Request title must be written in English", source)
        self.assertIn("Re-open the published Pull Request", source)
        divider = "\n---\n"
        self.assertEqual(1, source.count(divider))
        english, korean = source.split(divider)
        self.assertIn("\n# English\n", english)
        self.assertTrue(korean.startswith("\n# 한국어\n"))
        self.assertLess(english.index("# English"), english.index("## Purpose"))
        for heading in ("## Purpose", "## Included", "## Not included", "## Verification"):
            self.assertIn(heading, english)
        for heading in ("## 목적", "## 포함 내용", "## 포함하지 않은 내용", "## 검증"):
            self.assertIn(heading, korean)
        self.assertNotIn("\\n", source)


if __name__ == "__main__":
    unittest.main()
