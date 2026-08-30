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
        self.calls = []

    def resolve(self, source_url):
        self.calls.append(source_url)
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

                self.assertEqual(1, len(resolver.calls))
                self.assertEqual(
                    "https://publisher.example/resolved-story",
                    items[0]["link"],
                )


if __name__ == "__main__":
    unittest.main()
