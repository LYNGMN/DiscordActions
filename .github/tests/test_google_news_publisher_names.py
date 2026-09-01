import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from google_news_publisher_names import (  # noqa: E402
    PublisherRegistry,
    load_default_registry,
    normalize_article_title,
    normalize_message_publisher_names,
)


class GoogleNewsPublisherNamesTests(unittest.TestCase):
    def test_default_registry_normalizes_approved_domains_and_aliases(self):
        registry = load_default_registry()
        cases = (
            ("v.daum.net", "https://news.google.com/rss/articles/id", "다음"),
            ("Daum", "https://news.google.com/rss/articles/id", "다음"),
            ("news.nate.com", "https://news.google.com/rss/articles/id", "네이트"),
            ("NATE", "https://news.google.com/rss/articles/id", "네이트"),
            ("Korea Daily", "https://news.google.com/rss/articles/id", "미주중앙일보"),
            ("MyDaily", "https://news.google.com/rss/articles/id", "마이데일리"),
            ("Chosun Biz", "https://news.google.com/rss/articles/id", "조선비즈"),
            ("Xports News", "https://news.google.com/rss/articles/id", "엑스포츠뉴스"),
        )

        for label, url, expected in cases:
            with self.subTest(label=label, url=url):
                result = registry.resolve(label, url)
                self.assertTrue(result.mapped)
                self.assertEqual(expected, result.display_name)

        domains = (
            ("https://news.daum.net/story", "다음"),
            ("https://news.nate.com/view/1", "네이트"),
            ("https://www.koreadaily.com/article/1", "미주중앙일보"),
            ("https://www.mydaily.co.kr/page/view/1", "마이데일리"),
            ("https://biz.chosun.com/story/1", "조선비즈"),
            ("https://www.xportsnews.com/article/1", "엑스포츠뉴스"),
        )
        for url, expected in domains:
            with self.subTest(url=url):
                result = registry.resolve("Unknown Publisher", url)
                self.assertTrue(result.mapped)
                self.assertEqual(expected, result.display_name)

    def test_domain_matching_accepts_real_subdomains_but_rejects_suffix_tricks(self):
        registry = load_default_registry()

        mapped = registry.resolve("unknown", "https://m.news.nate.com/view/1")
        unsafe = registry.resolve("v.daum.net.evil.example", "https://v.daum.net.evil.example/1")

        self.assertEqual("네이트", mapped.display_name)
        self.assertTrue(mapped.mapped)
        self.assertEqual("v.daum.net.evil.example", unsafe.display_name)
        self.assertFalse(unsafe.mapped)
        self.assertTrue(unsafe.domain_like)

    def test_unknown_domain_is_preserved_and_human_label_is_not_domain_like(self):
        registry = load_default_registry()

        unknown_domain = registry.resolve("news.example.com", "https://news.example.com/story")
        human_label = registry.resolve("Example Press", "https://example.com/story")

        self.assertEqual("news.example.com", unknown_domain.display_name)
        self.assertEqual("news.example.com", unknown_domain.normalized_label)
        self.assertEqual("news.example.com", unknown_domain.hostname)
        self.assertFalse(unknown_domain.mapped)
        self.assertTrue(unknown_domain.domain_like)
        self.assertFalse(human_label.mapped)
        self.assertFalse(human_label.domain_like)

    def test_title_and_stored_message_normalization_change_only_publisher_positions(self):
        registry = load_default_registry()
        title = "첫 문장 - 두 번째 문장 - news.nate.com"
        content = (
            "**메인 기사 - mydaily.co.kr**\n"
            "https://www.mydaily.co.kr/page/view/1\n"
            "> - [연관 기사](<https://v.daum.net/v/1>) | v.daum.net"
        )

        self.assertEqual(
            "첫 문장 - 두 번째 문장 - 네이트",
            normalize_article_title(title, "https://news.nate.com/view/1", registry),
        )
        normalized = normalize_message_publisher_names(content, registry)
        self.assertIn("**메인 기사 - 마이데일리**", normalized)
        self.assertIn("https://www.mydaily.co.kr/page/view/1", normalized)
        self.assertIn("https://v.daum.net/v/1", normalized)
        self.assertIn("| 다음", normalized)

    def test_registry_rejects_duplicate_domains_aliases_and_unknown_fields(self):
        invalid_payloads = (
            {
                "schema_version": 1,
                "publishers": [
                    {"canonical_name": "A", "domains": ["example.com"], "aliases": ["A"]},
                    {"canonical_name": "B", "domains": ["EXAMPLE.COM"], "aliases": ["B"]},
                ],
            },
            {
                "schema_version": 1,
                "publishers": [
                    {"canonical_name": "A", "domains": ["a.example"], "aliases": ["Same"]},
                    {"canonical_name": "B", "domains": ["b.example"], "aliases": ["same"]},
                ],
            },
            {"schema_version": 1, "publishers": [], "unexpected": True},
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "publishers.json"
            for payload in invalid_payloads:
                with self.subTest(payload=payload):
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        PublisherRegistry.from_path(path)


if __name__ == "__main__":
    unittest.main()
