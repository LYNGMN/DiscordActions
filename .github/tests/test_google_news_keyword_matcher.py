import importlib
import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def load_module():
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        sys.modules.pop("google_news_keyword_matcher", None)
        return importlib.import_module("google_news_keyword_matcher")
    finally:
        sys.path.pop(0)


class GoogleNewsKeywordMatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def setUp(self):
        self.compiled = self.module.compile_keyword_match(
            "아이유 when:3d",
            'IU | "Lee Ji-eun" | 이지은',
        )
        self.related_description = """
            <a href="https://news.google.com/rss/articles/main">이솔이 비키니 화제</a>
            <font color="#6f6f6f">네이트</font>
            <ol>
              <li>
                <a href="https://news.google.com/rss/articles/related">아이유 새 앨범 공개</a>
                <font color="#6f6f6f">언론사</font>
              </li>
            </ol>
        """

    def test_title_mode_rejects_item_matched_only_by_related_news(self):
        result = self.module.match_google_news_item(
            "이솔이, 파격 비키니 룩에 반전 글래머 자랑 - 네이트",
            self.related_description,
            self.compiled,
            "title",
        )

        self.assertFalse(result.matched)
        self.assertIsNone(result.matched_field)

    def test_description_mode_accepts_a_related_article_title(self):
        result = self.module.match_google_news_item(
            "이솔이, 파격 비키니 룩에 반전 글래머 자랑 - 네이트",
            self.related_description,
            self.compiled,
            "title_or_description",
        )

        self.assertTrue(result.matched)
        self.assertEqual("description", result.matched_field)

    def test_publisher_url_and_html_attributes_are_not_matchable_text(self):
        description = """
            <a href="https://example.com/iu">전혀 다른 기사</a>
            <font color="#6f6f6f">아이유 뉴스</font>
        """

        result = self.module.match_google_news_item(
            "전혀 다른 기사 - 아이유 뉴스",
            description,
            self.compiled,
            "title_or_description",
        )

        self.assertFalse(result.matched)

    def test_ascii_alias_uses_word_boundaries(self):
        self.assertTrue(
            self.module.match_google_news_item(
                "IU announces a concert", "", self.compiled, "title"
            ).matched
        )
        self.assertFalse(
            self.module.match_google_news_item(
                "Chromium announces a concert", "", self.compiled, "title"
            ).matched
        )

    def test_boolean_operators_parentheses_quotes_and_implicit_and(self):
        compiled = self.module.compile_keyword_match(
            '("Lee Ji-eun" OR (IU & concert)) AND NOT rumor',
            "",
        )

        self.assertTrue(compiled.matches("IU concert confirmed"))
        self.assertTrue(compiled.matches("Lee   Ji-eun returns"))
        self.assertFalse(compiled.matches("IU concert rumor"))
        self.assertFalse(compiled.matches("IU interview"))

    def test_pipe_ampersand_bang_and_leading_minus_are_supported(self):
        compiled = self.module.compile_keyword_match(
            "(아이유 | IU) & !루머 -가짜",
            "",
        )

        self.assertTrue(compiled.matches("아이유 콘서트"))
        self.assertFalse(compiled.matches("아이유 루머"))
        self.assertFalse(compiled.matches("IU 가짜 기사"))

    def test_negative_only_expression_matches_clean_title(self):
        compiled = self.module.compile_keyword_match("NOT 루머", "")

        result = self.module.match_google_news_item(
            "아이유 콘서트 확정 - 언론사",
            "",
            compiled,
            "title",
        )

        self.assertTrue(result.matched)
        self.assertEqual("title", result.matched_field)

    def test_invalid_expression_fails_closed(self):
        for expression in ("아이유 OR", "(아이유", "AND 아이유", "\"\""):
            with self.subTest(expression=expression), self.assertRaisesRegex(
                ValueError, "invalid keyword expression"
            ):
                self.module.compile_keyword_match(expression, "")

    def test_query_can_be_derived_from_an_encoded_rss_url(self):
        rss_url = (
            "https://news.google.com/rss/search?"
            "q=%EC%95%84%EC%9D%B4%EC%9C%A0+when%3A3d&hl=ko&gl=KR&ceid=KR%3Ako"
        )

        self.assertEqual(
            "아이유 when:3d",
            self.module.extract_keyword_query("", rss_url),
        )

    def test_filter_fingerprint_changes_with_mode_or_aliases(self):
        title_fingerprint = self.module.keyword_filter_fingerprint(
            self.compiled, "title"
        )
        description_fingerprint = self.module.keyword_filter_fingerprint(
            self.compiled, "title_or_description"
        )
        other_aliases = self.module.compile_keyword_match("아이유", "IU | 이지은")

        self.assertNotEqual(title_fingerprint, description_fingerprint)
        self.assertNotEqual(
            title_fingerprint,
            self.module.keyword_filter_fingerprint(other_aliases, "title"),
        )


if __name__ == "__main__":
    unittest.main()
