import importlib
import sys
import unittest
from pathlib import Path
from unittest import mock


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


if __name__ == "__main__":
    unittest.main()
