import importlib
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def load_module():
    scripts_path = str(SCRIPTS_DIR)
    sys.path.insert(0, scripts_path)
    try:
        sys.modules.pop("google_news_discord_delivery", None)
        return importlib.import_module("google_news_discord_delivery")
    finally:
        sys.path.pop(0)


class FakeResponse:
    status_code = 200
    headers = {}

    def raise_for_status(self):
        return None

    def json(self):
        return {"id": "1234567890"}


class GoogleNewsDiscordDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.delivery = load_module()

    def test_approved_branding_overrides_caller_values_without_mutation(self):
        payload = {
            "content": "safe message",
            "username": "Stale Name",
            "avatar_url": "https://example.com/stale.png",
        }

        with mock.patch.object(
            self.delivery.requests,
            "post",
            return_value=FakeResponse(),
        ) as post:
            self.delivery.send_webhook_message(
                "https://example.com/webhook",
                payload,
            )

        posted_payload = post.call_args.kwargs["json"]
        self.assertEqual("Google News", posted_payload["username"])
        self.assertEqual(
            "https://discordactions.github.io/logo/media/original/news/googlenews.png",
            posted_payload["avatar_url"],
        )
        self.assertEqual("Stale Name", payload["username"])
        self.assertEqual("https://example.com/stale.png", payload["avatar_url"])

    def test_long_content_is_limited_before_post_and_keeps_date(self):
        date_line = "📅 2026-08-30 04:00:20 PM"
        content = (
            "headline\nhttps://publisher.example/article\n>>> "
            + ("x" * 2400)
            + "\n"
            + date_line
        )
        payload = {"content": content, "username": "Google News"}

        with mock.patch.object(
            self.delivery.requests,
            "post",
            return_value=FakeResponse(),
        ) as post:
            message_id = self.delivery.send_webhook_message(
                "https://example.com/webhook",
                payload,
            )

        posted_payload = post.call_args.kwargs["json"]
        self.assertEqual("1234567890", message_id)
        self.assertLessEqual(len(posted_payload["content"]), 2000)
        self.assertLessEqual(
            len(posted_payload["content"].encode("utf-16-le")) // 2,
            2000,
        )
        self.assertTrue(posted_payload["content"].endswith(date_line))
        self.assertIn("\n…\n", posted_payload["content"])
        self.assertEqual(content, payload["content"])

    def test_split_content_preserves_every_related_line_in_order(self):
        lines = [
            "> - [Story {}](https://publisher.example/{}) | Publisher".format(
                index, index
            )
            for index in range(80)
        ]
        content = "Main story\n" + "\n".join(lines) + "\n📅 date"

        chunks = self.delivery.split_discord_content(content)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(
            len(chunk.encode("utf-16-le")) // 2 <= 2000 for chunk in chunks
        ))
        combined = "\n".join(chunks)
        positions = [combined.index(line) for line in lines]
        self.assertEqual(sorted(positions), positions)
        self.assertTrue(combined.endswith("📅 date"))

    def test_network_failure_retries_once_and_marks_result_ambiguous(self):
        with mock.patch.object(
            self.delivery.requests,
            "post",
            side_effect=[requests.Timeout("unknown"), FakeResponse()],
        ) as post, mock.patch.object(self.delivery.time, "sleep"):
            message_id = self.delivery.send_webhook_message(
                "https://example.com/webhook",
                {"content": "safe"},
                sleep=lambda _seconds: None,
            )

        self.assertEqual("1234567890", message_id)
        self.assertTrue(message_id.ambiguous_retry)
        self.assertEqual(2, message_id.attempt_count)
        self.assertEqual(2, post.call_count)

    def test_double_network_failure_keeps_ambiguous_retry_evidence(self):
        with mock.patch.object(
            self.delivery.requests,
            "post",
            side_effect=[requests.Timeout("unknown-1"), requests.Timeout("unknown-2")],
        ) as post, mock.patch.object(self.delivery.time, "sleep"):
            with self.assertRaises(requests.Timeout) as raised:
                self.delivery.send_webhook_message(
                    "https://example.com/webhook",
                    {"content": "safe"},
                    sleep=lambda _seconds: None,
                )

        self.assertEqual("ambiguous_retry", raised.exception.error_code)
        self.assertEqual(2, raised.exception.attempt_count)
        self.assertEqual(2, post.call_count)

    def test_server_failure_retries_once_without_ambiguous_marker(self):
        server_error = FakeResponse()
        server_error.status_code = 503
        server_error.raise_for_status = mock.Mock(
            side_effect=requests.HTTPError("server error")
        )
        with mock.patch.object(
            self.delivery.requests,
            "post",
            side_effect=[server_error, FakeResponse()],
        ) as post, mock.patch.object(self.delivery.time, "sleep"):
            message_id = self.delivery.send_webhook_message(
                "https://example.com/webhook",
                {"content": "safe"},
                sleep=lambda _seconds: None,
            )

        self.assertFalse(message_id.ambiguous_retry)
        self.assertEqual(2, post.call_count)

    def test_rate_limit_uses_reset_header_and_retries_until_success(self):
        rate_limited = []
        for _index in range(2):
            response = FakeResponse()
            response.status_code = 429
            response.headers = {"X-RateLimit-Reset-After": "0.25"}
            response.json = mock.Mock(return_value={"message": "rate limited"})
            response.raise_for_status = mock.Mock(
                side_effect=requests.HTTPError("unsafe response detail")
            )
            rate_limited.append(response)
        sleeps = []

        with mock.patch.object(
            self.delivery.requests,
            "post",
            side_effect=rate_limited + [FakeResponse()],
        ) as post:
            message_id = self.delivery.send_webhook_message(
                "https://example.com/webhook",
                {"content": "safe"},
                sleep=sleeps.append,
            )

        self.assertEqual("1234567890", message_id)
        self.assertEqual(3, post.call_count)
        self.assertEqual([0.25, 0.25], sleeps)

    def test_successful_exhausted_bucket_waits_before_next_message(self):
        exhausted = FakeResponse()
        exhausted.headers = {
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset-After": "0.75",
        }
        sleeps = []

        with mock.patch.object(
            self.delivery.requests,
            "post",
            return_value=exhausted,
        ):
            self.delivery.send_webhook_message(
                "https://example.com/webhook",
                {"content": "safe"},
                sleep=sleeps.append,
            )

        self.assertEqual([0.75], sleeps)

    def test_unrecoverable_http_error_records_safe_status_code(self):
        bad_request = FakeResponse()
        bad_request.status_code = 400
        bad_request.raise_for_status = mock.Mock(
            side_effect=requests.HTTPError("unsafe response detail")
        )

        with mock.patch.object(
            self.delivery.requests,
            "post",
            return_value=bad_request,
        ):
            with self.assertRaises(requests.HTTPError) as raised:
                self.delivery.send_webhook_message(
                    "https://example.com/webhook",
                    {"content": "safe"},
                    sleep=lambda _seconds: None,
                )

        self.assertEqual("discord_http_400", raised.exception.error_code)
        self.assertNotIn("unsafe response detail", raised.exception.error_code)

    def test_unrecoverable_http_error_records_safe_discord_api_code(self):
        blocked = FakeResponse()
        blocked.status_code = 400
        blocked.json = mock.Mock(
            return_value={
                "code": 240000,
                "message": "unsafe response detail",
            }
        )
        blocked.raise_for_status = mock.Mock(
            side_effect=requests.HTTPError("unsafe response detail")
        )

        with mock.patch.object(
            self.delivery.requests,
            "post",
            return_value=blocked,
        ):
            with self.assertRaises(requests.HTTPError) as raised:
                self.delivery.send_webhook_message(
                    "https://example.com/webhook",
                    {"content": "safe"},
                    sleep=lambda _seconds: None,
                )

        self.assertEqual(
            "discord_http_400_api_240000",
            raised.exception.error_code,
        )
        self.assertEqual(240000, raised.exception.discord_api_code)
        self.assertEqual(400, raised.exception.http_status_code)
        self.assertNotIn("unsafe response detail", raised.exception.error_code)

    def test_harmful_original_link_uses_cached_google_news_fallback_once(self):
        blocked = FakeResponse()
        blocked.status_code = 400
        blocked.json = mock.Mock(
            return_value={"code": 240000, "message": "blocked"}
        )
        blocked.raise_for_status = mock.Mock(
            side_effect=requests.HTTPError("unsafe response detail")
        )
        payload = {
            "content": (
                "**Headline**\n"
                "https://publisher.example/article\n\n"
                "📅 date"
            )
        }

        with tempfile.TemporaryDirectory() as directory:
            resolver_db = str(Path(directory) / "resolver.db")
            with sqlite3.connect(resolver_db) as connection:
                connection.execute(
                    "CREATE TABLE google_news_url_cache ("
                    "article_id TEXT PRIMARY KEY, google_url TEXT NOT NULL, "
                    "resolved_url TEXT, status TEXT NOT NULL, "
                    "attempt_count INTEGER NOT NULL DEFAULT 0, "
                    "last_error_code TEXT, next_retry_at TEXT, updated_at TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO google_news_url_cache "
                    "(article_id, google_url, resolved_url, status, updated_at) "
                    "VALUES (?, ?, ?, 'resolved', ?)",
                    (
                        "article-id",
                        "https://news.google.com/rss/articles/article-id?oc=5",
                        "https://publisher.example/article",
                        "2026-09-02T00:00:00+00:00",
                    ),
                )

            with mock.patch.object(
                self.delivery.requests,
                "post",
                side_effect=[blocked, FakeResponse()],
            ) as post:
                message_id = self.delivery.send_webhook_message(
                    "https://example.com/webhook",
                    payload,
                    sleep=lambda _seconds: None,
                    resolver_db_path=resolver_db,
                )

        self.assertEqual("1234567890", message_id)
        self.assertTrue(message_id.google_news_fallback)
        self.assertEqual(2, message_id.attempt_count)
        self.assertEqual(2, post.call_count)
        fallback_content = post.call_args_list[1].kwargs["json"]["content"]
        self.assertIn("https://news.google.com/rss/articles/article-id?oc=5", fallback_content)
        self.assertNotIn("https://publisher.example/article", fallback_content)
        self.assertIn("https://publisher.example/article", payload["content"])

    def test_other_discord_400_codes_do_not_replace_original_links(self):
        blocked = FakeResponse()
        blocked.status_code = 400
        blocked.json = mock.Mock(
            return_value={"code": 50035, "message": "invalid form body"}
        )
        blocked.raise_for_status = mock.Mock(
            side_effect=requests.HTTPError("unsafe response detail")
        )

        with mock.patch.object(
            self.delivery.requests,
            "post",
            return_value=blocked,
        ) as post:
            with self.assertRaises(requests.HTTPError) as raised:
                self.delivery.send_webhook_message(
                    "https://example.com/webhook",
                    {"content": "https://publisher.example/article"},
                    sleep=lambda _seconds: None,
                    resolver_db_path="missing.db",
                )

        self.assertEqual("discord_http_400_api_50035", raised.exception.error_code)
        self.assertEqual(1, post.call_count)

    def test_fallback_requires_an_exact_url_and_trusted_google_hostname(self):
        blocked = FakeResponse()
        blocked.status_code = 400
        blocked.json = mock.Mock(
            return_value={"code": 240000, "message": "blocked"}
        )
        blocked.raise_for_status = mock.Mock(
            side_effect=requests.HTTPError("unsafe response detail")
        )

        with tempfile.TemporaryDirectory() as directory:
            resolver_db = str(Path(directory) / "resolver.db")
            with sqlite3.connect(resolver_db) as connection:
                connection.execute(
                    "CREATE TABLE google_news_url_cache ("
                    "article_id TEXT PRIMARY KEY, google_url TEXT NOT NULL, "
                    "resolved_url TEXT, status TEXT NOT NULL)"
                )
                connection.executemany(
                    "INSERT INTO google_news_url_cache "
                    "(article_id, google_url, resolved_url, status) "
                    "VALUES (?, ?, ?, 'resolved')",
                    (
                        (
                            "prefix",
                            "https://news.google.com/rss/articles/prefix",
                            "https://publisher.example/article",
                        ),
                        (
                            "untrusted",
                            "https://news.google.com.evil.example/article",
                            "https://publisher.example/exact",
                        ),
                    ),
                )

            with mock.patch.object(
                self.delivery.requests,
                "post",
                return_value=blocked,
            ) as post:
                with self.assertRaises(requests.HTTPError):
                    self.delivery.send_webhook_message(
                        "https://example.com/webhook",
                        {
                            "content": (
                                "https://publisher.example/article-extra\n"
                                "https://publisher.example/exact"
                            )
                        },
                        sleep=lambda _seconds: None,
                        resolver_db_path=resolver_db,
                    )

        self.assertEqual(1, post.call_count)

    def test_rate_limit_failure_preserves_prior_response_unknown_evidence(self):
        rate_limited = FakeResponse()
        rate_limited.status_code = 429
        rate_limited.headers = {"Retry-After": "0"}
        rate_limited.json = mock.Mock(return_value={"retry_after": 0.0})
        rate_limited.raise_for_status = mock.Mock(
            side_effect=requests.HTTPError("unsafe response detail")
        )

        with mock.patch.object(
            self.delivery.requests,
            "post",
            side_effect=[requests.Timeout("response unknown")]
            + [rate_limited] * 5,
        ) as post:
            with self.assertRaises(requests.HTTPError) as raised:
                self.delivery.send_webhook_message(
                    "https://example.com/webhook",
                    {"content": "safe"},
                    sleep=lambda _seconds: None,
                )

        self.assertEqual("ambiguous_retry", raised.exception.error_code)
        self.assertEqual(6, raised.exception.attempt_count)
        self.assertEqual(6, post.call_count)


if __name__ == "__main__":
    unittest.main()
