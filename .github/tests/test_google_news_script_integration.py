import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


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

    def get_stats(self):
        return {"network_resolution_attempts": 0}

    def resolve_related(self, source_url):
        self.related_calls.append(source_url)
        return SimpleNamespace(
            url="https://publisher.example/resolved-story",
            status="resolved",
            article_id="article-id",
            error_code=None,
        )


class OpenCircuitGuard:
    def __init__(self, *args, **kwargs):
        pass

    def get_open_circuit(self):
        return None


class RuntimeResolver(StubResolver):
    def __init__(self, *args, **kwargs):
        super().__init__()


class SequenceResolver(StubResolver):
    def __init__(self, urls):
        super().__init__()
        self.urls = iter(urls)

    def resolve_related(self, source_url):
        self.related_calls.append(source_url)
        url = next(self.urls)
        return SimpleNamespace(
            url=url,
            status="resolved",
            article_id="article-id",
            error_code=None,
        )


class GoogleNewsScriptIntegrationTests(unittest.TestCase):
    def test_each_handler_completes_one_crash_safe_manual_delivery(self):
        published_at = format_datetime(datetime.now(timezone.utc), usegmt=True)
        rss = (
            "<rss><channel><item>"
            "<guid>runtime-guid</guid>"
            "<title>Runtime title</title>"
            "<link>https://news.google.com/rss/articles/runtime-id</link>"
            "<pubDate>{}</pubDate>"
            "<description>&lt;ul&gt;&lt;/ul&gt;</description>"
            "</item></channel></rss>"
        ).format(published_at).encode("utf-8")

        for script_path in SCRIPT_PATHS:
            with self.subTest(script=script_path.name), tempfile.TemporaryDirectory() as temp_dir:
                module = load_script(script_path)
                profile_id = script_path.name.split("-")[1].split("_")[0] + "_runtime"
                module.DB_PATH = str(Path(temp_dir) / "articles.db")
                module.RESOLVER_DB_PATH = str(Path(temp_dir) / "resolver.db")
                module.RESULT_PATH = str(Path(temp_dir) / "result.json")
                module.PROFILE_ID = profile_id
                module.MANUAL_TEST_MODE = True
                module.MAX_NETWORK_RESOLUTIONS = 1
                module.GoogleNewsRequestGuard = OpenCircuitGuard
                module.GoogleNewsUrlResolver = RuntimeResolver

                if "top_" in script_path.name:
                    module.INITIALIZE_TOP = False
                    module.DISCORD_WEBHOOK_TOP = "redacted"
                    module.DISCORD_USERNAME_TOP = "Google News"
                    rss_metadata = ("redacted-rss", None, "UTC", "%Y-%m-%d %H:%M:%S")
                elif "topic_" in script_path.name:
                    module.INITIALIZE_TOPIC = False
                    module.DISCORD_WEBHOOK_TOPIC = "redacted"
                    module.DISCORD_USERNAME_TOPIC = "Google News"
                    rss_metadata = ("redacted-rss", "Topic", "ko")
                else:
                    module.INITIALIZE_KEYWORD = False
                    module.DISCORD_WEBHOOK_KEYWORD = "redacted"
                    module.DISCORD_USERNAME_KEYWORD = "Google News"
                    rss_metadata = ("redacted-rss", "Keyword", "KR")

                with mock.patch.object(module, "get_rss_url", return_value=rss_metadata), mock.patch.object(
                    module, "fetch_rss_feed", return_value=rss
                ), mock.patch.object(
                    module,
                    "send_discord_message",
                    return_value="123456789012345678",
                ):
                    exit_code = module.main()

                self.assertEqual(0, exit_code)
                result = json.loads(Path(module.RESULT_PATH).read_text(encoding="utf-8"))
                self.assertEqual("success", result["status"])
                self.assertEqual(1, result["processed_count"])
                self.assertEqual(0, result["pending_count"])
                with sqlite3.connect(module.DB_PATH) as connection:
                    delivery = connection.execute(
                        "SELECT delivery_status, discord_message_id "
                        "FROM news_items WHERE guid = 'runtime-guid'"
                    ).fetchone()
                    identity_count = connection.execute(
                        "SELECT COUNT(*) FROM google_news_article_identity"
                    ).fetchone()[0]
                self.assertEqual(("sent", "123456789012345678"), delivery)
                self.assertEqual(2, identity_count)

    def test_all_handlers_use_the_shared_bounded_runtime_contract(self):
        for script_path in SCRIPT_PATHS:
            with self.subTest(script=script_path.name):
                source = script_path.read_text(encoding="utf-8")

                self.assertIn("GOOGLE_NEWS_DB_PATH", source)
                self.assertIn("GOOGLE_NEWS_RESOLVER_DB_PATH", source)
                self.assertIn("GOOGLE_NEWS_MAX_NETWORK_RESOLUTIONS", source)
                self.assertIn("GOOGLE_NEWS_RESULT_PATH", source)
                self.assertIn("GoogleNewsRequestGuard", source)
                self.assertIn("prepare_scheduled_items", source)
                self.assertIn("reserve_delivery", source)
                self.assertIn("mark_delivery_sent", source)
                self.assertIn("write_profile_result", source)
                self.assertIn("request_guard=request_guard", source)
                self.assertIn("fetch_rss_feed(rss_url, request_guard)", source)
                self.assertLess(
                    source.index("GoogleNewsRequestGuard("),
                    source.index("fetch_rss_feed(rss_url, request_guard)"),
                )

    def test_keyword_handler_has_one_effective_rss_url_builder(self):
        keyword_source = SCRIPT_PATHS[0].read_text(encoding="utf-8")
        self.assertEqual(1, keyword_source.count("def get_rss_url():"))

    def test_discord_delivery_waits_for_and_returns_a_message_id(self):
        for script_path in SCRIPT_PATHS:
            with self.subTest(script=script_path.name):
                module = load_script(script_path)
                response = SimpleNamespace(
                    status_code=200,
                    headers={},
                    raise_for_status=lambda: None,
                    json=lambda: {"id": "123456789012345678"},
                )
                with mock.patch.object(module.requests, "post", return_value=response) as post:
                    message_id = module.send_discord_message(
                        "https://discord.com/api/webhooks/redacted",
                        "safe message",
                        username="Google News",
                    )

                self.assertEqual("123456789012345678", message_id)
                self.assertEqual({"wait": "true"}, post.call_args.kwargs["params"])
                self.assertEqual((5.0, 15.0), post.call_args.kwargs["timeout"])
                self.assertEqual(
                    "Google News", post.call_args.kwargs["json"]["username"]
                )

    def test_discord_429_waits_and_retries_once(self):
        for script_path in SCRIPT_PATHS:
            for source, headers, retry_payload in (
                ("header", {"Retry-After": "0"}, {}),
                ("json", {}, {"retry_after": 0.0}),
            ):
                with self.subTest(script=script_path.name, source=source):
                    module = load_script(script_path)
                    rate_limited = SimpleNamespace(
                        status_code=429,
                        headers=headers,
                        raise_for_status=mock.Mock(
                            side_effect=module.requests.HTTPError("rate limited")
                        ),
                        json=lambda: retry_payload,
                    )
                    delivered = SimpleNamespace(
                        status_code=200,
                        headers={},
                        raise_for_status=lambda: None,
                        json=lambda: {"id": "123456789012345678"},
                    )

                    with mock.patch.object(
                        module.requests,
                        "post",
                        side_effect=[rate_limited, delivered],
                    ) as post:
                        message_id = module.send_discord_message(
                            "https://discord.com/api/webhooks/redacted",
                            "safe message",
                            username="Google News",
                        )

                    self.assertEqual("123456789012345678", message_id)
                    self.assertEqual(2, post.call_count)

    def test_discord_429_retry_is_bounded_and_never_loops(self):
        for script_path in SCRIPT_PATHS:
            with self.subTest(script=script_path.name, case="excessive-delay"):
                module = load_script(script_path)
                rate_limited = SimpleNamespace(
                    status_code=429,
                    headers={"Retry-After": "61"},
                    raise_for_status=mock.Mock(
                        side_effect=module.requests.HTTPError("rate limited")
                    ),
                    json=lambda: {"retry_after": 61.0},
                )

                with mock.patch.object(
                    module.requests, "post", return_value=rate_limited
                ) as post, self.assertRaisesRegex(
                    RuntimeError, "discord_delivery_failed"
                ):
                    module.send_discord_message(
                        "https://discord.com/api/webhooks/redacted",
                        "safe message",
                        username="Google News",
                    )

                self.assertEqual(1, post.call_count)

            with self.subTest(script=script_path.name, case="second-429"):
                module = load_script(script_path)
                rate_limited = SimpleNamespace(
                    status_code=429,
                    headers={"Retry-After": "0"},
                    raise_for_status=mock.Mock(
                        side_effect=module.requests.HTTPError("rate limited")
                    ),
                    json=lambda: {"retry_after": 0.0},
                )

                with mock.patch.object(
                    module.requests,
                    "post",
                    side_effect=[rate_limited, rate_limited],
                ) as post, self.assertRaisesRegex(
                    RuntimeError, "discord_delivery_failed"
                ):
                    module.send_discord_message(
                        "https://discord.com/api/webhooks/redacted",
                        "safe message",
                        username="Google News",
                    )

                self.assertEqual(2, post.call_count)

    def test_validation_mode_never_calls_discord(self):
        for script_path in SCRIPT_PATHS:
            with self.subTest(script=script_path.name):
                module = load_script(script_path)
                module.VALIDATE_ONLY = True
                with mock.patch.object(
                    module.requests,
                    "post",
                    side_effect=AssertionError("validation must not call Discord"),
                ) as post:
                    message_id = module.send_discord_message(
                        "validation-only", "safe message", username="Google News"
                    )

                self.assertEqual("0", message_id)
                post.assert_not_called()

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

    def test_all_scripts_omit_unresolved_related_links_and_stop_after_four(self):
        description = "<ul>{}</ul>".format(
            "".join(
                '<li><a href="https://news.google.com/rss/articles/{}">Story {}</a>'
                '<font color="#6f6f6f">Publisher</font></li>'.format(index, index)
                for index in range(6)
            )
        )
        urls = [
            "https://news.google.com/rss/articles/unresolved",
            "https://publisher.example/1",
            "https://publisher.example/2",
            "https://publisher.example/3",
            "https://publisher.example/4",
            "https://publisher.example/5",
        ]

        for script_path in SCRIPT_PATHS:
            with self.subTest(script=script_path.name):
                module = load_script(script_path)
                resolver = SequenceResolver(urls)

                items = module.extract_news_items(description, resolver)

                self.assertEqual(4, len(items))
                self.assertEqual(5, len(resolver.related_calls))
                self.assertTrue(
                    all("news.google.com" not in item["link"] for item in items)
                )

    def test_related_descriptions_omit_every_unresolved_google_news_link(self):
        description = """
            <ul>
              <li>
                <a href="https://news.google.com/rss/articles/unresolved">
                  Unresolved related story
                </a>
                <font color="#6f6f6f">Publisher</font>
              </li>
              <li>
                <a href="https://news.google.com/fullcoverage/unresolved">
                  Google 뉴스에서 전체 콘텐츠 보기
                </a>
              </li>
            </ul>
        """

        for script_path in SCRIPT_PATHS:
            with self.subTest(script=script_path.name):
                module = load_script(script_path)
                resolver = SequenceResolver(
                    [
                        "https://news.google.com/rss/articles/unresolved",
                        "https://news.google.com/fullcoverage/unresolved",
                    ]
                )

                if "keyword_" in script_path.name:
                    rendered, _ = module.parse_html_description(
                        description,
                        resolver,
                        "Main story",
                        "https://publisher.example/main",
                    )
                else:
                    rendered = module.parse_html_description(description, resolver)

                self.assertNotIn("news.google.com", rendered)
                self.assertNotIn("전체 콘텐츠 보기", rendered)

    def test_keyword_and_science_technology_source_titles_are_exact(self):
        keyword = load_script(SCRIPT_PATHS[0])
        topic = load_script(SCRIPT_PATHS[2])
        item = {
            "title": "테스트 기사",
            "link": "https://publisher.example/story",
            "description": "",
            "pub_date": "Sun, 30 Aug 2026 12:00:00 GMT",
        }

        keyword_message = keyword.format_discord_message(item, "아이유", "KR")
        topic_message = topic.format_discord_message(
            item,
            "Google 뉴스",
            "기술 뉴스",
            "과학/기술",
            "🇰🇷",
            "KR",
        )

        self.assertIn("`Google 뉴스 - 아이유 - 한국 🇰🇷`", keyword_message)
        self.assertIn(
            "`Google 뉴스 - 기술 뉴스 - 과학/기술 🇰🇷`",
            topic_message,
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
                self.assertNotIn("{RSS_URL_TOP}", source)
                self.assertNotIn("{RSS_URL_TOPIC}", source)
                self.assertNotIn("{RSS_URL_KEYWORD}", source)
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
