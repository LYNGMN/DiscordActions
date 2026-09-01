import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from google_news_publisher_names import (  # noqa: E402
    normalize_article_title,
    normalize_publisher_name,
)


class GoogleNewsPublisherNamesTests(unittest.TestCase):
    def test_known_domains_use_canonical_korean_names(self):
        cases = (
            ("v.daum.net", "https://v.daum.net/v/1", "다음"),
            ("koreadaily.com", "https://www.koreadaily.com/article/1", "미주중앙일보"),
            ("mydaily.co.kr", "https://www.mydaily.co.kr/page/view/1", "마이데일리"),
            ("Chosunbiz", "https://biz.chosun.com/entertainment/1", "조선비즈"),
            ("xportsnews.com", "https://www.xportsnews.com/article/1", "엑스포츠뉴스"),
        )

        for publisher_name, article_url, expected in cases:
            with self.subTest(article_url=article_url):
                self.assertEqual(
                    expected,
                    normalize_publisher_name(publisher_name, article_url),
                )

    def test_known_rss_label_is_normalized_when_google_url_is_retained(self):
        self.assertEqual(
            "다음",
            normalize_publisher_name(
                "v.daum.net",
                "https://news.google.com/rss/articles/unresolved",
            ),
        )

    def test_unknown_publisher_is_preserved(self):
        self.assertEqual(
            "Example Press",
            normalize_publisher_name(
                "Example Press",
                "https://v.daum.net.evil.example/story",
            ),
        )

    def test_article_title_normalizes_only_the_final_publisher_suffix(self):
        self.assertEqual(
            "첫 문장 - 두 번째 문장 - 마이데일리",
            normalize_article_title(
                "첫 문장 - 두 번째 문장 - mydaily.co.kr",
                "https://www.mydaily.co.kr/page/view/1",
            ),
        )

    def test_article_title_without_publisher_suffix_is_preserved(self):
        self.assertEqual(
            "구분자가 없는 제목",
            normalize_article_title(
                "구분자가 없는 제목",
                "https://v.daum.net/v/1",
            ),
        )


if __name__ == "__main__":
    unittest.main()
