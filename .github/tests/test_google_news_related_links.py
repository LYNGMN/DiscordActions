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

    def test_uses_safe_google_rss_source_when_resolution_fails(self):
        module = load_module()
        source = "https://news.google.com/rss/articles/article-id?oc=5"
        resolver = RecordingResolver(
            SimpleNamespace(
                url=source,
                status="fallback",
                article_id="article-id",
                error_code="budget_exhausted",
            )
        )

        self.assertEqual(source, module.resolve_related_url(resolver, source))

    def test_rejects_unsafe_or_non_article_fallback_sources(self):
        module = load_module()
        for source in (
            "https://news.google.com/fullcoverage/article-id",
            "https://sub.news.google.com/rss/articles/article-id",
            "javascript:alert(1)",
            "",
        ):
            with self.subTest(source=source):
                resolver = RecordingResolver(
                    SimpleNamespace(
                        url="javascript:alert(1)",
                        status="fallback",
                        article_id="article-id",
                        error_code="invalid_response",
                    )
                )
                self.assertIsNone(module.resolve_related_url(resolver, source))


if __name__ == "__main__":
    unittest.main()
