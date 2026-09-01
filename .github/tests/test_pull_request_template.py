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
        for heading in (
            "## Purpose",
            "## Related issue",
            "## Changes",
            "## User impact",
            "## Verification",
            "## Operational notes",
        ):
            self.assertIn(heading, english)
        for heading in (
            "## 목적",
            "## 관련 Issue",
            "## 변경 내용",
            "## 사용자 영향",
            "## 검증",
            "## 운영 참고사항",
        ):
            self.assertIn(heading, korean)
        self.assertNotIn("\\n", source)

    def test_template_links_work_instead_of_listing_a_future_backlog(self):
        source = TEMPLATE.read_text(encoding="utf-8")

        self.assertIn("Closes #", source)
        self.assertIn("future work belongs in a separate Issue", source)
        self.assertIn("후속 작업은 별도 Issue로 관리", source)
        self.assertNotIn("## Not included", source)
        self.assertNotIn("## 포함하지 않은 내용", source)

    def test_template_contains_complete_bilingual_review_and_merge_checklists(self):
        source = TEMPLATE.read_text(encoding="utf-8")

        for required_line in (
            "### Review Checklist",
            "### Merge Checklist",
            "The Pull Request remains Draft until exact-state final authorization.",
            "New changes received new tests and Review",
            "### 리뷰 체크리스트",
            "### 병합 체크리스트",
            "Pull Request는 정확한 상태에 대한 최종 승인 전까지 Draft를 유지합니다.",
            "새 변경에는 새 테스트와 Review를 수행",
        ):
            self.assertIn(required_line, source)


if __name__ == "__main__":
    unittest.main()
