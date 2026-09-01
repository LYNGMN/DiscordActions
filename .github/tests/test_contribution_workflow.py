import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRIBUTING = ROOT / ".github" / "CONTRIBUTING.md"
ISSUE_TEMPLATE_DIR = ROOT / ".github" / "ISSUE_TEMPLATE"
FEATURE_FORM = ISSUE_TEMPLATE_DIR / "01-feature-request.yml"
BUG_FORM = ISSUE_TEMPLATE_DIR / "02-bug-report.yml"
CONFIG = ISSUE_TEMPLATE_DIR / "config.yml"


class ContributionWorkflowTests(unittest.TestCase):
    def test_contributing_guide_separates_issue_and_pull_request_responsibilities(self):
        self.assertTrue(CONTRIBUTING.is_file(), "missing .github/CONTRIBUTING.md")
        source = CONTRIBUTING.read_text(encoding="utf-8")

        self.assertLess(source.index("# English"), source.index("# 한국어"))
        self.assertIn("An Issue records work to be done", source)
        self.assertIn("A Pull Request records the implemented change", source)
        self.assertIn("A Pull Request body is not a backlog", source)
        self.assertIn("Issue는 앞으로 해야 할 일을 기록", source)
        self.assertIn("Pull Request는 실제로 구현한 변경을 기록", source)
        self.assertIn("Pull Request 본문은 작업 목록이 아닙니다", source)

    def test_contributing_guide_defines_when_issues_and_branches_are_needed(self):
        self.assertTrue(CONTRIBUTING.is_file(), "missing .github/CONTRIBUTING.md")
        source = CONTRIBUTING.read_text(encoding="utf-8")

        self.assertIn("tiny self-contained correction", source)
        self.assertIn("umbrella Issue", source)
        self.assertIn("Create a Branch only when implementation starts", source)
        self.assertIn("작고 독립적인 수정", source)
        self.assertIn("상위 Issue", source)
        self.assertIn("구현을 시작할 때만 Branch를 만듭니다", source)

    def test_issue_forms_collect_complete_bilingual_records(self):
        for path in (FEATURE_FORM, BUG_FORM):
            with self.subTest(path=path.name):
                self.assertTrue(path.is_file(), f"missing {path.name}")
                source = path.read_text(encoding="utf-8")
                self.assertIn("English", source)
                self.assertIn("한국어", source)
                self.assertIn("Acceptance criteria", source)
                self.assertIn("완료 조건", source)
                self.assertGreaterEqual(source.count("required: true"), 8)
                self.assertNotIn("\\n", source)

    def test_issue_chooser_uses_structured_forms_for_normal_contributions(self):
        self.assertTrue(CONFIG.is_file(), "missing .github/ISSUE_TEMPLATE/config.yml")
        source = CONFIG.read_text(encoding="utf-8")

        self.assertIn("blank_issues_enabled: false", source)
        self.assertNotIn("contact_links:", source)


if __name__ == "__main__":
    unittest.main()
