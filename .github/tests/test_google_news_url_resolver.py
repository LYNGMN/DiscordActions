import base64
import importlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
import sqlite3
from unittest import mock

import requests


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def load_resolver_module():
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        return importlib.import_module("google_news_url_resolver")
    except ModuleNotFoundError as error:
        if error.name == "google_news_url_resolver":
            raise AssertionError("google_news_url_resolver.py must exist")
        raise
    finally:
        sys.path.pop(0)


class UnexpectedSession:
    def get(self, *args, **kwargs):
        raise AssertionError("disabled resolution must not make a GET request")

    def post(self, *args, **kwargs):
        raise AssertionError("disabled resolution must not make a POST request")


class FakeResponse:
    def __init__(self, status_code=200, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error


class QueueSession:
    def __init__(self, get_responses=None, post_responses=None):
        self.get_responses = list(get_responses or [])
        self.post_responses = list(post_responses or [])
        self.get_calls = []
        self.post_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append({"url": url, "kwargs": kwargs})
        if not self.get_responses:
            raise AssertionError("unexpected GET request")
        response = self.get_responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    def post(self, url, **kwargs):
        self.post_calls.append({"url": url, "kwargs": kwargs})
        if not self.post_responses:
            raise AssertionError("unexpected POST request")
        response = self.post_responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class RecordingRequestGuard:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get_open_circuit(self):
        return None

    def clear_circuit(self):
        return None

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})
        if not self.responses:
            raise AssertionError("unexpected guarded request")
        return self.responses.pop(0)

class GoogleNewsUrlResolverTests(unittest.TestCase):
    @staticmethod
    def _successful_responses(original_url):
        html = (
            '<c-wiz><div jscontroller="abc" data-n-a-sg="signature" '
            'data-n-a-ts="1725891265"></div></c-wiz>'
        )
        rpc_payload = [
            [
                "wrb.fr",
                "Fbv4je",
                json.dumps(["garturlres", original_url]),
                None,
                None,
                [3],
                "generic",
            ]
        ]
        return (
            FakeResponse(text=html),
            FakeResponse(text=")]}'\n\n" + json.dumps(rpc_payload)),
        )

    def test_disabled_resolution_returns_original_url_without_network(self):
        module = load_resolver_module()
        source_url = "https://news.google.com/rss/articles/article-id?oc=5"

        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = module.GoogleNewsUrlResolver(
                session=UnexpectedSession(),
                db_path=str(Path(temp_dir) / "news.db"),
                enabled=False,
                min_interval_seconds=0,
            )

            result = resolver.resolve(source_url)

        self.assertEqual(source_url, result.url)
        self.assertEqual("disabled", result.status)
        self.assertEqual("article-id", result.article_id)
        self.assertIsNone(result.error_code)

    def test_new_format_uses_decoding_parameters_and_preserves_encoded_query(self):
        module = load_resolver_module()
        article_id = "CBMiOpaqueArticleId"
        source_url = f"https://news.google.com/rss/articles/{article_id}?oc=5"
        original_url = (
            "https://publisher.example/story?target="
            "https%3A%2F%2Fsource.example%2Fa%3Fx%3D1%26y%3D2"
        )
        html = (
            '<c-wiz><div jscontroller="abc" data-n-a-sg="signature-value" '
            'data-n-a-ts="1725891265"></div></c-wiz>'
        )
        rpc_payload = [
            [
                "wrb.fr",
                "Fbv4je",
                json.dumps(["garturlres", original_url]),
                None,
                None,
                [3],
                "generic",
            ],
            ["di", 16],
            ["af.httprm", 16, "request-id", 9],
        ]
        session = QueueSession(
            get_responses=[FakeResponse(text=html)],
            post_responses=[FakeResponse(text=")]}'\n\n" + json.dumps(rpc_payload))],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = module.GoogleNewsUrlResolver(
                session=session,
                db_path=str(Path(temp_dir) / "news.db"),
                min_interval_seconds=0,
            )

            result = resolver.resolve(source_url)

        self.assertEqual(original_url, result.url)
        self.assertEqual("resolved", result.status)
        self.assertEqual(article_id, result.article_id)
        self.assertIsNone(result.error_code)
        self.assertEqual(1, len(session.get_calls))
        self.assertEqual((5.0, 15.0), session.get_calls[0]["kwargs"]["timeout"])
        self.assertEqual(1, len(session.post_calls))

        request_payload = json.loads(
            session.post_calls[0]["kwargs"]["data"]["f.req"]
        )
        inner_payload = json.loads(request_payload[0][0][1])
        self.assertEqual(article_id, inner_payload[2])
        self.assertEqual(1725891265, inner_payload[3])
        self.assertEqual("signature-value", inner_payload[4])

    def test_injected_request_guard_handles_parameter_and_rpc_requests(self):
        module = load_resolver_module()
        article_id = "CBMiInjectedGuard"
        source_url = "https://news.google.com/rss/articles/{}?oc=5".format(article_id)
        original_url = "https://publisher.example/guarded"
        get_response, post_response = self._successful_responses(original_url)
        guard = RecordingRequestGuard([get_response, post_response])

        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = module.GoogleNewsUrlResolver(
                session=UnexpectedSession(),
                db_path=str(Path(temp_dir) / "news.db"),
                request_guard=guard,
                min_interval_seconds=0,
            )
            result = resolver.resolve(source_url)

        self.assertEqual("resolved", result.status)
        self.assertEqual(["get", "post"], [call["method"] for call in guard.calls])
        self.assertTrue(guard.calls[0]["url"].endswith(article_id))
        self.assertEqual(module.GoogleNewsUrlResolver.BATCH_EXECUTE_URL, guard.calls[1]["url"])

    def test_missing_parameters_on_articles_path_falls_back_to_rss_path(self):
        module = load_resolver_module()
        article_id = "CBMiRssFallback"
        source_url = f"https://news.google.com/rss/articles/{article_id}?oc=5"
        html = (
            '<c-wiz><div jscontroller="abc" data-n-a-sg="rss-signature" '
            'data-n-a-ts="1725891265"></div></c-wiz>'
        )
        rpc_payload = [
            [
                "wrb.fr",
                "Fbv4je",
                json.dumps(["garturlres", "https://publisher.example/rss-fallback"]),
                None,
                None,
                [3],
                "generic",
            ]
        ]
        session = QueueSession(
            get_responses=[FakeResponse(text="<html></html>"), FakeResponse(text=html)],
            post_responses=[FakeResponse(text=")]}'\n\n" + json.dumps(rpc_payload))],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = module.GoogleNewsUrlResolver(
                session=session,
                db_path=str(Path(temp_dir) / "news.db"),
                min_interval_seconds=0,
            )
            result = resolver.resolve(source_url)

        self.assertEqual("resolved", result.status)
        self.assertEqual(
            f"https://news.google.com/articles/{article_id}",
            session.get_calls[0]["url"],
        )
        self.assertEqual(
            f"https://news.google.com/rss/articles/{article_id}",
            session.get_calls[1]["url"],
        )

    def test_malformed_rpc_response_returns_google_news_fallback(self):
        module = load_resolver_module()
        article_id = "CBMiMalformedResponse"
        source_url = f"https://news.google.com/rss/articles/{article_id}?oc=5"
        html = (
            '<c-wiz><div jscontroller="abc" data-n-a-sg="signature" '
            'data-n-a-ts="1725891265"></div></c-wiz>'
        )
        session = QueueSession(
            get_responses=[FakeResponse(text=html)],
            post_responses=[FakeResponse(text=")]}'\n\nnot-json")],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = module.GoogleNewsUrlResolver(
                session=session,
                db_path=str(Path(temp_dir) / "news.db"),
                min_interval_seconds=0,
            )
            result = resolver.resolve(source_url)

        self.assertEqual(source_url, result.url)
        self.assertEqual("fallback", result.status)
        self.assertEqual("decode_failed", result.error_code)

    def test_non_google_url_is_passed_through_without_network(self):
        module = load_resolver_module()
        source_url = "https://publisher.example/already-original"

        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = module.GoogleNewsUrlResolver(
                session=UnexpectedSession(),
                db_path=str(Path(temp_dir) / "news.db"),
                min_interval_seconds=0,
            )
            result = resolver.resolve(source_url)

        self.assertEqual(source_url, result.url)
        self.assertEqual("passthrough", result.status)
        self.assertIsNone(result.article_id)

    def test_successful_resolution_is_reused_from_sqlite_cache(self):
        module = load_resolver_module()
        article_id = "CBMiCachedArticleId"
        source_url = f"https://news.google.com/read/{article_id}?hl=ko"
        original_url = "https://publisher.example/cached-story"
        html = (
            '<c-wiz><div jscontroller="abc" data-n-a-sg="cache-signature" '
            'data-n-a-ts="1725891265"></div></c-wiz>'
        )
        rpc_payload = [
            [
                "wrb.fr",
                "Fbv4je",
                json.dumps(["garturlres", original_url]),
                None,
                None,
                [3],
                "generic",
            ],
            ["di", 16],
            ["af.httprm", 16, "request-id", 9],
        ]
        session = QueueSession(
            get_responses=[FakeResponse(text=html), FakeResponse(text=html)],
            post_responses=[
                FakeResponse(text=")]}'\n\n" + json.dumps(rpc_payload)),
                FakeResponse(text=")]}'\n\n" + json.dumps(rpc_payload)),
            ],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = module.GoogleNewsUrlResolver(
                session=session,
                db_path=str(Path(temp_dir) / "news.db"),
                min_interval_seconds=0,
            )

            first_result = resolver.resolve(source_url)
            second_result = resolver.resolve(source_url)

        self.assertEqual("resolved", first_result.status)
        self.assertEqual("cache_hit", second_result.status)
        self.assertEqual(original_url, second_result.url)
        self.assertEqual(1, len(session.get_calls))
        self.assertEqual(1, len(session.post_calls))

    def test_legacy_base64_url_is_resolved_without_network(self):
        module = load_resolver_module()
        original_url = "https://publisher.example/legacy-story?x=1%2F2"
        encoded_bytes = (
            b'\x08\x13"'
            + bytes([len(original_url)])
            + original_url.encode("utf-8")
            + b"\xd2\x01\x00"
        )
        article_id = base64.urlsafe_b64encode(encoded_bytes).decode().rstrip("=")
        source_url = f"https://news.google.com/articles/{article_id}"
        session = QueueSession(
            get_responses=[FakeResponse(text="<html></html>")] * 2
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = module.GoogleNewsUrlResolver(
                session=session,
                db_path=str(Path(temp_dir) / "news.db"),
                min_interval_seconds=0,
            )

            result = resolver.resolve(source_url)

        self.assertEqual(original_url, result.url)
        self.assertEqual("legacy", result.status)
        self.assertEqual(article_id, result.article_id)
        self.assertEqual(0, len(session.get_calls))
        self.assertEqual(0, len(session.post_calls))

    def test_legacy_youtube_id_is_resolved_without_network(self):
        module = load_resolver_module()
        youtube_id = "AbCdEfGhI_1"
        encoded_bytes = (
            b'\x08 "\x0b' + youtube_id.encode("ascii") + b"\x98\x01\x01"
        )
        article_id = base64.urlsafe_b64encode(encoded_bytes).decode().rstrip("=")
        source_url = f"https://news.google.com/articles/{article_id}"
        session = QueueSession(
            get_responses=[FakeResponse(text="<html></html>")] * 2
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = module.GoogleNewsUrlResolver(
                session=session,
                db_path=str(Path(temp_dir) / "news.db"),
                min_interval_seconds=0,
            )
            result = resolver.resolve(source_url)

        self.assertEqual(
            f"https://www.youtube.com/watch?v={youtube_id}",
            result.url,
        )
        self.assertEqual("legacy", result.status)
        self.assertEqual(0, len(session.get_calls))

    def test_rate_limit_stops_additional_resolution_requests_for_the_run(self):
        module = load_resolver_module()
        first_url = "https://news.google.com/rss/articles/CBMiRateLimited?oc=5"
        second_url = "https://news.google.com/rss/articles/CBMiAfterLimit?oc=5"
        session = QueueSession(
            get_responses=[
                FakeResponse(
                    status_code=429,
                    text="rate limited",
                    headers={"Retry-After": "120"},
                )
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = module.GoogleNewsUrlResolver(
                session=session,
                db_path=str(Path(temp_dir) / "news.db"),
                min_interval_seconds=0,
            )

            first_result = resolver.resolve(first_url)
            self.assertEqual("fallback", first_result.status)
            self.assertEqual("http_429", first_result.error_code)

            second_result = resolver.resolve(second_url)

        self.assertEqual("fallback", second_result.status)
        self.assertEqual("circuit_open", second_result.error_code)
        self.assertEqual(1, len(session.get_calls))
        self.assertEqual(0, len(session.post_calls))

    def test_network_resolution_budget_falls_back_without_an_extra_request(self):
        module = load_resolver_module()
        first_url = "https://news.google.com/rss/articles/CBMiBudgetOne?oc=5"
        second_url = "https://news.google.com/rss/articles/CBMiBudgetTwo?oc=5"
        get_response, post_response = self._successful_responses(
            "https://publisher.example/first"
        )
        session = QueueSession(
            get_responses=[get_response],
            post_responses=[post_response],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = module.GoogleNewsUrlResolver(
                session=session,
                db_path=str(Path(temp_dir) / "news.db"),
                min_interval_seconds=0,
                max_network_resolutions=1,
            )

            first_result = resolver.resolve(first_url)
            second_result = resolver.resolve(second_url)
            stats = resolver.get_stats()

        self.assertEqual("resolved", first_result.status)
        self.assertEqual("fallback", second_result.status)
        self.assertEqual("budget_exhausted", second_result.error_code)
        self.assertEqual(1, len(session.get_calls))
        self.assertEqual(1, len(session.post_calls))
        self.assertEqual(2, stats["resolution_calls"])
        self.assertEqual(1, stats["network_resolution_attempts"])
        self.assertEqual(1, stats["budget_exhausted"])
        self.assertEqual(1, stats["fallbacks"])

    def test_related_resolution_uses_cache_without_new_network_requests(self):
        module = load_resolver_module()
        source_url = "https://news.google.com/rss/articles/CBMiRelatedCached?oc=5"
        original_url = "https://publisher.example/related-cached"
        get_response, post_response = self._successful_responses(original_url)

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "news.db")
            priming_session = QueueSession(
                get_responses=[get_response],
                post_responses=[post_response],
            )
            priming_resolver = module.GoogleNewsUrlResolver(
                session=priming_session,
                db_path=db_path,
                min_interval_seconds=0,
            )
            self.assertEqual("resolved", priming_resolver.resolve(source_url).status)

            resolver = module.GoogleNewsUrlResolver(
                session=UnexpectedSession(),
                db_path=db_path,
                min_interval_seconds=0,
            )
            result = resolver.resolve_related(source_url)

        self.assertEqual("cache_hit", result.status)
        self.assertEqual(original_url, result.url)

    def test_related_uncached_modern_url_uses_one_bounded_network_resolution(self):
        module = load_resolver_module()
        source_url = "https://news.google.com/rss/articles/CBMiRelatedUncached?oc=5"
        original_url = "https://publisher.example/related-uncached"
        get_response, post_response = self._successful_responses(original_url)
        session = QueueSession(
            get_responses=[get_response],
            post_responses=[post_response],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = module.GoogleNewsUrlResolver(
                session=session,
                db_path=str(Path(temp_dir) / "news.db"),
                min_interval_seconds=0,
                max_network_resolutions=1,
            )
            result = resolver.resolve_related(source_url)
            stats = resolver.get_stats()

        self.assertEqual("resolved", result.status)
        self.assertEqual(original_url, result.url)
        self.assertEqual(1, len(session.get_calls))
        self.assertEqual(1, len(session.post_calls))
        self.assertEqual(1, stats["network_resolution_attempts"])

    def test_rate_limit_circuit_is_reused_by_a_new_resolver(self):
        module = load_resolver_module()
        first_url = "https://news.google.com/rss/articles/CBMiPersistentLimit?oc=5"
        second_url = "https://news.google.com/rss/articles/CBMiPersistentNext?oc=5"
        fixed_now = datetime(2026, 8, 31, 3, 0, tzinfo=timezone.utc)

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "news.db")
            first_session = QueueSession(
                get_responses=[
                    FakeResponse(status_code=429, headers={"Retry-After": "120"})
                ]
            )
            with mock.patch.object(
                module.GoogleNewsUrlResolver,
                "_utc_now",
                return_value=fixed_now,
            ):
                first_resolver = module.GoogleNewsUrlResolver(
                    session=first_session,
                    db_path=db_path,
                    min_interval_seconds=0,
                )
                first_result = first_resolver.resolve(first_url)

                second_session = QueueSession()
                second_resolver = module.GoogleNewsUrlResolver(
                    session=second_session,
                    db_path=db_path,
                    min_interval_seconds=0,
                )
                second_result = second_resolver.resolve(second_url)
                stats = second_resolver.get_stats()

            with sqlite3.connect(db_path) as connection:
                state = connection.execute(
                    """
                    SELECT blocked_until, last_error_code
                    FROM google_news_resolver_state
                    WHERE state_key = 'global'
                    """
                ).fetchone()

        self.assertEqual("http_429", first_result.error_code)
        self.assertEqual("circuit_open", second_result.error_code)
        self.assertEqual(0, len(second_session.get_calls))
        self.assertEqual(
            fixed_now + timedelta(seconds=120),
            datetime.fromisoformat(state[0]),
        )
        self.assertEqual("http_429", state[1])
        self.assertEqual(1, stats["circuit_skipped"])
        self.assertEqual(
            (fixed_now + timedelta(seconds=120)).isoformat(),
            stats["circuit_blocked_until"],
        )

    def test_retry_after_http_date_is_honored_and_large_delay_is_capped(self):
        module = load_resolver_module()
        fixed_now = datetime(2026, 8, 31, 3, 0, tzinfo=timezone.utc)
        cases = (
            (format_datetime(fixed_now + timedelta(minutes=10), usegmt=True), 600),
            ("999999", 6 * 60 * 60),
            (None, 60 * 60),
        )

        for index, (header, expected_seconds) in enumerate(cases):
            with self.subTest(header=header), tempfile.TemporaryDirectory() as temp_dir:
                headers = {"Retry-After": header} if header is not None else {}
                session = QueueSession(
                    get_responses=[FakeResponse(status_code=429, headers=headers)]
                )
                db_path = str(Path(temp_dir) / f"news-{index}.db")
                with mock.patch.object(
                    module.GoogleNewsUrlResolver,
                    "_utc_now",
                    return_value=fixed_now,
                ):
                    resolver = module.GoogleNewsUrlResolver(
                        session=session,
                        db_path=db_path,
                        min_interval_seconds=0,
                    )
                    resolver.resolve(
                        f"https://news.google.com/rss/articles/CBMiRetry{index}?oc=5"
                    )

                with sqlite3.connect(db_path) as connection:
                    blocked_until = connection.execute(
                        "SELECT blocked_until FROM google_news_resolver_state"
                    ).fetchone()[0]

                self.assertEqual(
                    fixed_now + timedelta(seconds=expected_seconds),
                    datetime.fromisoformat(blocked_until),
                )

    def test_http_403_opens_the_persistent_circuit(self):
        module = load_resolver_module()
        source_url = "https://news.google.com/rss/articles/CBMiForbidden?oc=5"
        fixed_now = datetime(2026, 8, 31, 3, 0, tzinfo=timezone.utc)
        session = QueueSession(get_responses=[FakeResponse(status_code=403)])

        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(
            module.GoogleNewsUrlResolver,
            "_utc_now",
            return_value=fixed_now,
        ):
            resolver = module.GoogleNewsUrlResolver(
                session=session,
                db_path=str(Path(temp_dir) / "news.db"),
                min_interval_seconds=0,
            )
            result = resolver.resolve(source_url)
            stats = resolver.get_stats()

        self.assertEqual("fallback", result.status)
        self.assertEqual("http_403", result.error_code)
        self.assertEqual(1, stats["circuit_opened"])
        self.assertEqual(1, stats["fallbacks"])

    def test_stats_snapshot_contains_only_sanitized_counts_and_timestamp(self):
        module = load_resolver_module()
        source_url = (
            "https://news.google.com/rss/articles/CBMiNoLeak"
            "?secret_query=must-not-appear"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = module.GoogleNewsUrlResolver(
                session=UnexpectedSession(),
                db_path=str(Path(temp_dir) / "news.db"),
                min_interval_seconds=0,
                max_network_resolutions=0,
            )
            resolver.resolve_related(source_url)
            stats = resolver.get_stats()

        serialized = json.dumps(stats, sort_keys=True)
        self.assertNotIn(source_url, serialized)
        self.assertNotIn("secret_query", serialized)
        self.assertEqual(
            {
                "budget_exhausted",
                "cache_hits",
                "circuit_blocked_until",
                "circuit_opened",
                "circuit_skipped",
                "fallbacks",
                "legacy",
                "network_resolution_attempts",
                "related_network_skipped",
                "resolution_calls",
                "resolved",
            },
            set(stats),
        )

    def test_failed_resolution_is_deferred_in_sqlite_cache(self):
        module = load_resolver_module()
        article_id = "CBMiDeferredArticle"
        source_url = f"https://news.google.com/rss/articles/{article_id}?oc=5"

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "news.db")
            first_session = QueueSession(
                get_responses=[FakeResponse(status_code=429, text="rate limited")]
            )
            first_resolver = module.GoogleNewsUrlResolver(
                session=first_session,
                db_path=db_path,
                min_interval_seconds=0,
            )

            first_result = first_resolver.resolve(source_url)

            with sqlite3.connect(db_path) as connection:
                cache_row = connection.execute(
                    """
                    SELECT status, attempt_count, last_error_code,
                           next_retry_at, updated_at
                    FROM google_news_url_cache
                    WHERE article_id = ?
                    """,
                    (article_id,),
                ).fetchone()

            retry_session = QueueSession(
                get_responses=[
                    FakeResponse(
                        text=(
                            '<c-wiz><div jscontroller="abc" '
                            'data-n-a-sg="signature" '
                            'data-n-a-ts="1725891265"></div></c-wiz>'
                        )
                    )
                ]
            )
            second_resolver = module.GoogleNewsUrlResolver(
                session=retry_session,
                db_path=db_path,
                min_interval_seconds=0,
            )
            second_result = second_resolver.resolve(source_url)

        self.assertEqual("fallback", first_result.status)
        self.assertIsNotNone(cache_row)
        self.assertEqual("failed", cache_row[0])
        self.assertEqual(1, cache_row[1])
        self.assertEqual("http_429", cache_row[2])
        retry_at = datetime.fromisoformat(cache_row[3])
        updated_at = datetime.fromisoformat(cache_row[4])
        self.assertEqual(30 * 60, int((retry_at - updated_at).total_seconds()))
        self.assertEqual("fallback", second_result.status)
        self.assertEqual("http_429", second_result.error_code)
        self.assertEqual(0, len(retry_session.get_calls))

    def test_transient_get_failure_retries_same_endpoint_once(self):
        module = load_resolver_module()
        article_id = "CBMiTransientArticle"
        source_url = f"https://news.google.com/rss/articles/{article_id}?oc=5"
        original_url = "https://publisher.example/retried-story"
        html = (
            '<c-wiz><div jscontroller="abc" data-n-a-sg="signature" '
            'data-n-a-ts="1725891265"></div></c-wiz>'
        )
        rpc_payload = [
            [
                "wrb.fr",
                "Fbv4je",
                json.dumps(["garturlres", original_url]),
                None,
                None,
                [3],
                "generic",
            ]
        ]
        session = QueueSession(
            get_responses=[requests.ConnectionError("temporary"), FakeResponse(text=html)],
            post_responses=[FakeResponse(text=")]}'\n\n" + json.dumps(rpc_payload))],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = module.GoogleNewsUrlResolver(
                session=session,
                db_path=str(Path(temp_dir) / "news.db"),
                min_interval_seconds=0,
            )
            with mock.patch("time.sleep") as sleep_mock:
                result = resolver.resolve(source_url)

        self.assertEqual("resolved", result.status)
        self.assertEqual(2, len(session.get_calls))
        self.assertEqual(
            session.get_calls[0]["url"],
            session.get_calls[1]["url"],
        )
        sleep_mock.assert_called_once_with(2.0)

    def test_uncached_articles_are_throttled_between_resolutions(self):
        module = load_resolver_module()
        article_ids = ["CBMiThrottleOne", "CBMiThrottleTwo"]
        html_responses = [
            FakeResponse(
                text=(
                    '<c-wiz><div jscontroller="abc" '
                    f'data-n-a-sg="signature-{index}" '
                    'data-n-a-ts="1725891265"></div></c-wiz>'
                )
            )
            for index in range(2)
        ]
        post_responses = []
        for index in range(2):
            rpc_payload = [
                [
                    "wrb.fr",
                    "Fbv4je",
                    json.dumps(
                        ["garturlres", f"https://publisher.example/story-{index}"]
                    ),
                    None,
                    None,
                    [3],
                    "generic",
                ]
            ]
            post_responses.append(
                FakeResponse(text=")]}'\n\n" + json.dumps(rpc_payload))
            )
        session = QueueSession(
            get_responses=html_responses,
            post_responses=post_responses,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = module.GoogleNewsUrlResolver(
                session=session,
                db_path=str(Path(temp_dir) / "news.db"),
                min_interval_seconds=1.0,
            )
            with mock.patch.object(module.time, "sleep") as sleep_mock:
                for article_id in article_ids:
                    result = resolver.resolve(
                        f"https://news.google.com/rss/articles/{article_id}?oc=5"
                    )
                    self.assertEqual("resolved", result.status)

        self.assertEqual(1, sleep_mock.call_count)
        throttle_delay = sleep_mock.call_args.args[0]
        self.assertGreater(throttle_delay, 0)
        self.assertLessEqual(throttle_delay, 1.0)


if __name__ == "__main__":
    unittest.main()
