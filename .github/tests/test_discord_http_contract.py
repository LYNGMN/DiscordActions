import importlib
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import requests


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def load_module(name):
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        sys.modules.pop(name, None)
        return importlib.import_module(name)
    finally:
        sys.path.pop(0)


class RecordedHandler(BaseHTTPRequestHandler):
    responses = []
    requests_seen = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        type(self).requests_seen.append(
            {"path": self.path, "body": json.loads(body.decode("utf-8"))}
        )
        if not type(self).responses:
            self.send_response(500)
            self.end_headers()
            return
        status, headers, payload = type(self).responses.pop(0)
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return


class DiscordHttpContractTests(unittest.TestCase):
    def serve(self, responses):
        RecordedHandler.responses = list(responses)
        RecordedHandler.requests_seen = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), RecordedHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return "http://127.0.0.1:{}/api/webhooks/1/token".format(
            server.server_address[1]
        )

    def setUp(self):
        self.delivery = load_module("google_news_discord_delivery")

    def test_rate_limit_header_and_body_are_honoured(self):
        url = self.serve(
            [
                (
                    429,
                    {"Retry-After": "0"},
                    {"retry_after": 0.0, "global": False},
                ),
                (200, {}, {"id": "1234567890"}),
            ]
        )

        with mock.patch.dict(
            os.environ, {"NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"}
        ):
            message_id = self.delivery.send_webhook_message(
                url,
                {"content": "hello"},
                sleep=lambda _: None,
            )

        self.assertEqual("1234567890", message_id)
        self.assertEqual(2, len(RecordedHandler.requests_seen))
        self.assertEqual(
            {"parse": []},
            RecordedHandler.requests_seen[0]["body"]["allowed_mentions"],
        )
        self.assertEqual(
            {"parse": []},
            RecordedHandler.requests_seen[1]["body"]["allowed_mentions"],
        )

    def test_discord_harmful_link_error_is_recorded_without_retry(self):
        url = self.serve(
            [
                (
                    400,
                    {},
                    {"code": 240000, "message": "potentially harmful link"},
                )
            ]
        )

        with mock.patch.dict(
            os.environ, {"NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"}
        ):
            with self.assertRaises(requests.HTTPError) as raised:
                self.delivery.send_webhook_message(
                    url,
                    {"content": "hello"},
                    sleep=lambda _: None,
                )

        self.assertEqual(
            "discord_http_400_api_240000", raised.exception.error_code
        )
        self.assertEqual(1, len(RecordedHandler.requests_seen))

    def test_server_error_retries_once(self):
        url = self.serve(
            [
                (500, {}, {"message": "temporary"}),
                (200, {}, {"id": "2234567890"}),
            ]
        )

        with mock.patch.dict(
            os.environ, {"NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"}
        ):
            message_id = self.delivery.send_webhook_message(
                url,
                {"content": "hello"},
                sleep=lambda _: None,
            )

        self.assertEqual("2234567890", message_id)
        self.assertEqual(2, len(RecordedHandler.requests_seen))


if __name__ == "__main__":
    unittest.main()
