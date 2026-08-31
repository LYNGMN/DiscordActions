import importlib
import sys
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


if __name__ == "__main__":
    unittest.main()
