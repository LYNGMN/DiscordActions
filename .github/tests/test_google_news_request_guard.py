import importlib
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest import mock

import requests


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def load_guard_module():
    scripts_path = str(SCRIPTS_DIR)
    sys.path.insert(0, scripts_path)
    try:
        sys.modules.pop("google_news_request_guard", None)
        return importlib.import_module("google_news_request_guard")
    finally:
        sys.path.pop(0)


class FakeResponse:
    def __init__(self, status_code=200, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self.content = text.encode("utf-8")

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError("HTTP {}".format(self.status_code))
            error.response = self
            raise error


class QueueSession:
    def __init__(self, get_responses=None, post_responses=None):
        self.get_responses = list(get_responses or [])
        self.post_responses = list(post_responses or [])
        self.get_calls = []
        self.post_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        if not self.get_responses:
            raise AssertionError("unexpected GET request")
        response = self.get_responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        if not self.post_responses:
            raise AssertionError("unexpected POST request")
        response = self.post_responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class GoogleNewsRequestGuardTests(unittest.TestCase):
    def setUp(self):
        self.module = load_guard_module()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = str(Path(self.temp_dir.name) / "resolver.db")
        self.fixed_now = datetime(2026, 8, 31, 3, 0, tzinfo=timezone.utc)

    def make_guard(self, session):
        return self.module.GoogleNewsRequestGuard(
            session=session,
            db_path=self.db_path,
            utc_now=lambda: self.fixed_now,
        )

    def test_rss_429_blocks_a_new_guard_using_the_same_database(self):
        first_session = QueueSession(
            get_responses=[FakeResponse(429, headers={"Retry-After": "120"})]
        )
        first = self.make_guard(first_session)

        with self.assertRaises(self.module.RateLimitError) as raised:
            first.request("get", "https://news.google.com/rss")

        second_session = QueueSession()
        second = self.make_guard(second_session)
        with self.assertRaises(self.module.CircuitOpenError) as blocked:
            second.request("get", "https://news.google.com/rss")

        self.assertEqual("http_429", raised.exception.error_code)
        self.assertEqual("http_429", blocked.exception.source_error_code)
        self.assertEqual([], second_session.get_calls)
        self.assertEqual(
            self.fixed_now + timedelta(seconds=120),
            second.get_open_circuit().blocked_until,
        )

    def test_http_403_opens_the_same_persistent_circuit(self):
        guard = self.make_guard(QueueSession(get_responses=[FakeResponse(403)]))

        with self.assertRaises(self.module.AccessDeniedError):
            guard.request("get", "https://news.google.com/rss")

        state = guard.get_open_circuit()
        self.assertEqual("http_403", state.error_code)
        self.assertEqual(
            self.fixed_now + timedelta(hours=1),
            state.blocked_until,
        )

    def test_retry_after_numeric_and_http_date_are_clamped(self):
        cases = (
            ("1", 60),
            (format_datetime(self.fixed_now + timedelta(minutes=10), usegmt=True), 600),
            ("999999", 6 * 60 * 60),
            ("invalid", 60 * 60),
        )
        for index, (header, expected_seconds) in enumerate(cases):
            with self.subTest(header=header):
                db_path = str(Path(self.temp_dir.name) / "case-{}.db".format(index))
                guard = self.module.GoogleNewsRequestGuard(
                    session=QueueSession(
                        get_responses=[FakeResponse(429, headers={"Retry-After": header})]
                    ),
                    db_path=db_path,
                    utc_now=lambda: self.fixed_now,
                )
                with self.assertRaises(self.module.RateLimitError):
                    guard.request("get", "https://news.google.com/rss")
                self.assertEqual(
                    self.fixed_now + timedelta(seconds=expected_seconds),
                    guard.get_open_circuit().blocked_until,
                )

    def test_connection_and_5xx_failures_retry_once(self):
        connection_session = QueueSession(
            get_responses=[requests.ConnectionError("offline"), FakeResponse(200)]
        )
        with mock.patch("time.sleep") as sleep:
            response = self.make_guard(connection_session).request(
                "get", "https://news.google.com/rss"
            )
        self.assertEqual(200, response.status_code)
        self.assertEqual(2, len(connection_session.get_calls))
        self.assertEqual((5.0, 15.0), connection_session.get_calls[0][1]["timeout"])
        sleep.assert_called_once_with(2.0)

        server_session = QueueSession(
            post_responses=[FakeResponse(503), FakeResponse(200)]
        )
        with mock.patch("time.sleep") as sleep:
            response = self.make_guard(server_session).request(
                "post", "https://news.google.com/_/rpc", data={"f.req": "safe"}
            )
        self.assertEqual(200, response.status_code)
        self.assertEqual(2, len(server_session.post_calls))
        sleep.assert_called_once_with(2.0)

    def test_exception_and_database_do_not_store_requested_url(self):
        sensitive_url = "https://news.google.com/rss?query=must-not-leak"
        guard = self.make_guard(
            QueueSession(get_responses=[FakeResponse(429, text="sensitive response")])
        )

        with self.assertRaises(self.module.RateLimitError) as raised:
            guard.request("get", sensitive_url)

        self.assertNotIn("must-not-leak", str(raised.exception))
        self.assertNotIn("sensitive response", str(raised.exception))
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT blocked_until, last_error_code, updated_at "
                "FROM google_news_resolver_state WHERE state_key = 'global'"
            ).fetchone()
        self.assertEqual("http_429", row[1])
        self.assertNotIn("must-not-leak", " ".join(row))


if __name__ == "__main__":
    unittest.main()
