import importlib
import sys
import unittest
from pathlib import Path

import requests


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT_PATH = SCRIPTS_DIR / "youtube_to_discord.py"
APPROVED_AVATAR = (
    "https://discordactions.github.io/logo/media/original/youtube/"
    "youtube_social_circle_red.png"
)


def load_module():
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        sys.modules.pop("youtube_discord_delivery", None)
        return importlib.import_module("youtube_discord_delivery")
    finally:
        sys.path.pop(0)


class FakeResponse:
    def __init__(self, error=None, status_code=200, message_id="123456789012345678", headers=None):
        self.error = error
        self.status_code = status_code
        self.message_id = message_id
        self.headers = headers or {}
        self.raise_calls = 0

    def raise_for_status(self):
        self.raise_calls += 1
        if self.error is not None:
            raise self.error

    @property
    def text(self):
        raise AssertionError("response body must not be read or logged")

    def json(self):
        return {"id": self.message_id}


class RecordingPost:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class SequencePost:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class YouTubeDiscordDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_branding_overrides_plain_and_embed_payloads_without_mutation(self):
        payload = {
            "content": "video",
            "username": "stale",
            "embeds": [
                {"footer": {"text": "YouTube", "icon_url": "stale"}},
                {"title": "second"},
            ],
        }

        result = self.module.branded_youtube_payload(payload)

        self.assertEqual("YouTube", result["username"])
        self.assertEqual(APPROVED_AVATAR, result["avatar_url"])
        self.assertEqual(APPROVED_AVATAR, result["embeds"][0]["footer"]["icon_url"])
        self.assertEqual(APPROVED_AVATAR, result["embeds"][1]["footer"]["icon_url"])
        self.assertNotIn("avatar_url", payload)
        self.assertEqual("stale", payload["embeds"][0]["footer"]["icon_url"])
        self.assertNotIn("footer", payload["embeds"][1])

    def test_webhook_uses_bounded_timeout_and_approved_branding(self):
        response = FakeResponse()
        post = RecordingPost(response)

        result = self.module.send_youtube_webhook(
            "https://discord.example/webhook",
            {"content": "video", "username": "stale"},
            post=post,
        )

        self.assertEqual("123456789012345678", result.message_id)
        self.assertFalse(result.ambiguous_retry)
        self.assertEqual(1, response.raise_calls)
        self.assertEqual(1, len(post.calls))
        url, kwargs = post.calls[0]
        self.assertEqual("https://discord.example/webhook?wait=true", url)
        self.assertEqual((5.0, 15.0), kwargs["timeout"])
        self.assertEqual("application/json", kwargs["headers"]["Content-Type"])
        self.assertEqual("YouTube", kwargs["json"]["username"])
        self.assertEqual(APPROVED_AVATAR, kwargs["json"]["avatar_url"])

    def test_webhook_raises_on_non_success_without_reading_response_body(self):
        error = requests.HTTPError("HTTP 500")
        post = RecordingPost(FakeResponse(error=error))

        with self.assertRaises(requests.HTTPError):
            self.module.send_youtube_webhook(
                "https://discord.example/webhook",
                {"content": "video"},
                post=post,
                sleep=lambda _seconds: None,
            )

    def test_rate_limit_honors_retry_after_and_retries_once(self):
        post = SequencePost(
            [
                FakeResponse(
                    error=requests.HTTPError("HTTP 429"),
                    status_code=429,
                    headers={"Retry-After": "1.25"},
                ),
                FakeResponse(message_id="223456789012345678"),
            ]
        )
        sleeps = []

        result = self.module.send_youtube_webhook(
            "https://discord.example/webhook?thread_id=7",
            {"content": "video"},
            post=post,
            sleep=sleeps.append,
        )

        self.assertEqual("223456789012345678", result.message_id)
        self.assertEqual([1.25], sleeps)
        self.assertEqual(2, len(post.calls))
        self.assertIn("thread_id=7", post.calls[0][0])
        self.assertIn("wait=true", post.calls[0][0])

    def test_network_retry_is_marked_ambiguous(self):
        post = SequencePost(
            [
                requests.Timeout("response unknown"),
                FakeResponse(message_id="323456789012345678"),
            ]
        )

        result = self.module.send_youtube_webhook(
            "https://discord.example/webhook",
            {"content": "video"},
            post=post,
            sleep=lambda _seconds: None,
        )

        self.assertEqual("323456789012345678", result.message_id)
        self.assertTrue(result.ambiguous_retry)
        self.assertEqual(2, result.attempt_count)
        self.assertEqual(2, len(post.calls))

    def test_double_network_failure_keeps_ambiguous_retry_evidence(self):
        post = SequencePost(
            [
                requests.Timeout("response unknown 1"),
                requests.Timeout("response unknown 2"),
            ]
        )

        with self.assertRaises(requests.Timeout) as raised:
            self.module.send_youtube_webhook(
                "https://discord.example/webhook",
                {"content": "video"},
                post=post,
                sleep=lambda _seconds: None,
            )

        self.assertEqual("ambiguous_retry", raised.exception.error_code)
        self.assertEqual(2, raised.exception.attempt_count)
        self.assertEqual(2, len(post.calls))

    def test_youtube_script_uses_shared_delivery_for_plain_and_embed_payloads(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn("from youtube_discord_delivery import", source)
        self.assertIn("send_youtube_webhook", source)
        self.assertIn("send_youtube_webhook(webhook_url, payload)", source)
        self.assertNotIn("response = requests.post(webhook_url", source)
        self.assertNotIn("logging.error(response.text)", source)


if __name__ == "__main__":
    unittest.main()
