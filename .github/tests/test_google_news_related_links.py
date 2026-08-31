import importlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def load_module():
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        sys.modules.pop("google_news_related_links", None)
        return importlib.import_module("google_news_related_links")
    finally:
        sys.path.pop(0)


class RecordingResolver:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def resolve_related(self, source_url):
        self.calls.append(source_url)
        return self.result


class GoogleNewsRelatedLinksTests(unittest.TestCase):
    def test_returns_resolved_publisher_url(self):
        module = load_module()
        resolver = RecordingResolver(
            SimpleNamespace(
                url="https://publisher.example/story?id=7",
                status="resolved",
                article_id="article-id",
                error_code=None,
            )
        )

        result = module.resolve_related_url(
            resolver,
            "https://news.google.com/rss/articles/article-id?oc=5",
        )

        self.assertEqual("https://publisher.example/story?id=7", result)
        self.assertEqual(1, len(resolver.calls))

    def test_rejects_fallback_google_and_non_http_urls(self):
        module = load_module()
        for url in (
            "https://news.google.com/rss/articles/article-id?oc=5",
            "https://sub.news.google.com/articles/article-id",
            "javascript:alert(1)",
            "",
        ):
            with self.subTest(url=url):
                resolver = RecordingResolver(
                    SimpleNamespace(
                        url=url,
                        status="fallback",
                        article_id="article-id",
                        error_code="budget_exhausted",
                    )
                )
                self.assertIsNone(module.resolve_related_url(resolver, "source"))

    def test_related_item_limit_is_four(self):
        module = load_module()
        self.assertEqual(4, module.MAX_RELATED_ITEMS)


if __name__ == "__main__":
    unittest.main()
