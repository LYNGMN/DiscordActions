import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT_PATHS = (
    SCRIPTS_DIR / "googlenews-keyword_to_discord.py",
    SCRIPTS_DIR / "googlenews-top_to_discord.py",
    SCRIPTS_DIR / "googlenews-topic_to_discord.py",
)


def load_script(path):
    scripts_path = str(SCRIPTS_DIR)
    sys.path.insert(0, scripts_path)
    try:
        module_name = path.stem.replace("-", "_") + "_integration_test"
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


class StubResolver:
    def __init__(self):
        self.main_calls = []
        self.related_calls = []

    def resolve(self, source_url):
        self.main_calls.append(source_url)
        return SimpleNamespace(
            url="https://publisher.example/resolved-story",
            status="resolved",
            article_id="article-id",
            error_code=None,
        )

    def resolve_related(self, source_url):
        self.related_calls.append(source_url)
        return SimpleNamespace(
            url="https://publisher.example/resolved-story",
            status="resolved",
            article_id="article-id",
            error_code=None,
        )


class GoogleNewsScriptIntegrationTests(unittest.TestCase):
    def test_all_scripts_use_shared_resolver_for_related_news(self):
        description = """
            <ul>
              <li>
                <a href="https://news.google.com/rss/articles/article-id?oc=5">
                  Related story
                </a>
                <font color="#6f6f6f">Publisher</font>
              </li>
            </ul>
        """

        for script_path in SCRIPT_PATHS:
            with self.subTest(script=script_path.name):
                module = load_script(script_path)
                self.assertFalse(hasattr(module, "get_original_url"))
                self.assertTrue(hasattr(module, "GoogleNewsUrlResolver"))
                resolver = StubResolver()

                items = module.extract_news_items(description, resolver)

                self.assertEqual([], resolver.main_calls)
                self.assertEqual(1, len(resolver.related_calls))
                self.assertEqual(
                    "https://publisher.example/resolved-story",
                    items[0]["link"],
                )

    def test_all_scripts_wire_safe_manual_test_mode(self):
        for script_path in SCRIPT_PATHS:
            with self.subTest(script=script_path.name):
                module = load_script(script_path)
                source = script_path.read_text(encoding="utf-8")

                self.assertFalse(module.MANUAL_TEST_MODE)
                self.assertTrue(callable(module.prepare_manual_test_items))
                self.assertTrue(callable(module.validate_manual_test_result))
                self.assertIn("prepare_manual_test_items(", source)
                self.assertIn("validate_manual_test_result(", source)

    def test_all_scripts_log_sanitized_resolver_stats(self):
        for script_path in SCRIPT_PATHS:
            with self.subTest(script=script_path.name):
                source = script_path.read_text(encoding="utf-8")

                self.assertIn("resolver.get_stats()", source)
                self.assertNotIn("RSS 피드 URL:", source)
                self.assertNotIn("가져오는데 실패했습니다: {url}", source)
                self.assertNotIn(
                    "RSS 피드 가져오기 실패 (시도 {attempt + 1}/{max_retries}): {e}",
                    source,
                )
                self.assertNotIn(
                    "Discord 메시지 전송 실패 (시도 {attempt + 1}/{max_retries}): {e}",
                    source,
                )
                self.assertNotIn("Discord 메시지 전송 최종 실패: {e}", source)
                self.assertIn('RuntimeError("rss_fetch_failed") from None', source)
                self.assertIn(
                    'RuntimeError("discord_delivery_failed") from None',
                    source,
                )


if __name__ == "__main__":
    unittest.main()
