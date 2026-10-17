"""Regressions for the October 2026 DiscordActions incident."""
import importlib
import sys
import tempfile
import unittest
from pathlib import Path

import requests

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))


class Response:
    def __init__(self, status_code):
        self.status_code = status_code
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("should not appear in safe logs")


class Session:
    def get(self, *_args, **_kwargs):
        return Response(502)


class IncidentRegressionTests(unittest.TestCase):
    def test_google_news_http_status_is_propagated_without_url(self):
        guard_module = importlib.import_module("google_news_request_guard")
        with tempfile.TemporaryDirectory() as directory:
            guard = guard_module.GoogleNewsRequestGuard(
                Session(), str(Path(directory) / "resolver.db")
            )
            from unittest.mock import patch
            with patch("time.sleep"):
                with self.assertRaises(requests.HTTPError) as raised:
                    guard.request("get", "https://news.google.com/rss?secret=hidden")
        self.assertEqual("http_502", raised.exception.error_code)
        self.assertNotIn("hidden", raised.exception.error_code)

    def test_youtube_discord_http_error_is_categorized(self):
        module = importlib.import_module("youtube_discord_delivery")
        response = Response(403)
        with self.assertRaises(requests.HTTPError) as raised:
            module.send_youtube_webhook(
                "https://discord.example/webhook",
                {"content": "video"},
                post=lambda *_args, **_kwargs: response,
                sleep=lambda _seconds: None,
            )
        self.assertEqual("discord_http_403", raised.exception.error_code)

    def test_youtube_missing_details_do_not_abort_entire_batch(self):
        source = (SCRIPTS / "youtube_to_discord.py").read_text(encoding="utf-8")
        self.assertIn("if video_id in details_by_id", source)
        self.assertNotIn('raise RuntimeError("youtube_video_details_incomplete")', source)


if __name__ == "__main__":
    unittest.main()
