import contextlib
import importlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
PROFILES_PATH = Path(__file__).resolve().parents[1] / "config" / "google_news_profiles.json"


def load_module(name):
    scripts_path = str(SCRIPTS_DIR)
    sys.path.insert(0, scripts_path)
    try:
        sys.modules.pop(name, None)
        return importlib.import_module(name)
    finally:
        sys.path.pop(0)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, json_error=None):
        self.status_code = status_code
        self.payload = payload
        self.json_error = json_error

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("unsafe upstream detail")

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload


class QueueSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected webhook metadata request")
        return self.responses.pop(0)


class GoogleNewsDispatcherTests(unittest.TestCase):
    def setUp(self):
        self.dispatcher = load_module("google_news_dispatcher")
        self.profiles_module = load_module("google_news_profiles")
        self.result_module = load_module("google_news_profile_result")
        self.profiles = self.profiles_module.load_profiles(str(PROFILES_PATH))
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.state_dir = str(Path(self.temp_dir.name) / "state")
        self.env = {"PATH": os.environ.get("PATH", "/usr/bin")}
        for index, profile in enumerate(self.profiles, start=1):
            self.env[profile.webhook_env] = (
                "https://discord.com/api/webhooks/{}/token{}".format(index, index)
            )

    def metadata_session(self, profiles=None):
        selected = profiles or self.profiles
        return QueueSession(
            [FakeResponse(payload={"name": profile.expected_webhook_name}) for profile in selected]
        )

    def successful_runner(self, calls):
        def run(command, env, check):
            calls.append((command, env, check))
            self.result_module.write_profile_result(
                env["GOOGLE_NEWS_RESULT_PATH"],
                env["GOOGLE_NEWS_PROFILE_ID"],
                "success",
                1,
                0,
            )
            return SimpleNamespace(returncode=0)

        return run

    def test_preflight_mismatch_skips_only_that_profile(self):
        profiles = self.profiles[:2]
        session = QueueSession(
            [
                FakeResponse(payload={"name": "wrong-name"}),
                FakeResponse(payload={"name": profiles[1].expected_webhook_name}),
            ]
        )
        calls = []

        summary = self.dispatcher.run_dispatch(
            profiles,
            self.env,
            self.state_dir,
            manual_test=True,
            session=session,
            subprocess_runner=self.successful_runner(calls),
            sleep=lambda _: None,
        )

        self.assertEqual(1, len(calls))
        self.assertEqual(
            [profiles[1].profile_id],
            [call[1]["GOOGLE_NEWS_PROFILE_ID"] for call in calls],
        )
        self.assertEqual(["failed", "success"], [item.status for item in summary.profiles])
        self.assertEqual("webhook_name_mismatch", summary.profiles[0].error_code)
        self.assertEqual("failed", summary.status)

    def test_preflight_failure_for_every_profile_records_each_one(self):
        profiles = self.profiles[:2]
        session = QueueSession(
            [FakeResponse(payload={"name": "wrong-name"}) for _ in profiles]
        )
        runner = mock.Mock()

        summary = self.dispatcher.run_dispatch(
            profiles,
            self.env,
            self.state_dir,
            manual_test=True,
            session=session,
            subprocess_runner=runner,
            sleep=lambda _: None,
        )

        runner.assert_not_called()
        self.assertEqual("failed", summary.status)
        self.assertEqual(2, len(summary.profiles))
        self.assertTrue(all(item.status == "failed" for item in summary.profiles))
        self.assertEqual(
            ["webhook_name_mismatch", "webhook_name_mismatch"],
            [item.error_code for item in summary.profiles],
        )

    def test_invalid_common_feed_settings_stop_before_webhook_network(self):
        env = dict(self.env)
        env["FEED_DATE_FILTER"] = "calendar:yesterday"
        session = QueueSession([])
        runner = mock.Mock()

        with self.assertRaisesRegex(ValueError, "invalid common feed settings"):
            self.dispatcher.run_dispatch(
                self.profiles,
                env,
                self.state_dir,
                manual_test=True,
                session=session,
                subprocess_runner=runner,
                sleep=lambda _: None,
            )

        self.assertEqual([], session.calls)
        runner.assert_not_called()

    def test_invalid_publisher_registry_stops_before_webhook_network(self):
        session = QueueSession([])
        runner = mock.Mock()

        with mock.patch.object(
            self.dispatcher,
            "load_default_registry",
            side_effect=ValueError("invalid publisher registry"),
        ), self.assertRaisesRegex(ValueError, "invalid publisher registry"):
            self.dispatcher.run_dispatch(
                self.profiles,
                self.env,
                self.state_dir,
                manual_test=True,
                session=session,
                subprocess_runner=runner,
                sleep=lambda _: None,
            )

        self.assertEqual([], session.calls)
        runner.assert_not_called()

    def test_preflight_reports_invalid_webhook_values_without_network(self):
        cases = (
            (None, "missing_webhook"),
            ("http://example.com", "invalid_webhook"),
            ("https://name@discord.com/api/webhooks/1/token", "invalid_webhook"),
            ("https://discord.com:444/api/webhooks/1/token", "invalid_webhook"),
        )
        profile = self.profiles[0]
        for value, expected_code in cases:
            with self.subTest(value=value):
                env = dict(self.env)
                if value is None:
                    env.pop(profile.webhook_env)
                else:
                    env[profile.webhook_env] = value
                session = QueueSession([])
                usable, failures = self.dispatcher.preflight_profiles(
                    [profile], env, session, sleep=lambda _: None
                )
                self.assertEqual([], usable)
                self.assertEqual([], session.calls)
                self.assertEqual(1, len(failures))
                self.assertEqual(expected_code, failures[0].error_code)

    def test_invalid_child_result_is_reported_without_exposing_its_values(self):
        profile = self.profiles[0]

        def runner(command, env, check):
            Path(env["GOOGLE_NEWS_RESULT_PATH"]).write_text(
                json.dumps(
                    {
                        "profile_id": profile.profile_id,
                        "status": "failed",
                        "processed_count": 0,
                        "pending_count": 0,
                        "ambiguous_retry_count": 0,
                        "error_code": 123,
                    }
                ),
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=1)

        summary = self.dispatcher.run_profiles(
            [profile],
            self.env,
            self.state_dir,
            manual_test=False,
            subprocess_runner=runner,
            sleep=lambda _: None,
        )

        self.assertEqual("invalid_result", summary.profiles[0].error_code)

    def test_preflight_reports_rate_limit_and_invalid_json_with_safe_codes(self):
        cases = (
            (FakeResponse(status_code=429), "webhook_rate_limited"),
            (FakeResponse(json_error=ValueError("body must not leak")), "webhook_metadata_invalid"),
        )
        profile = self.profiles[0]
        for response, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                usable, failures = self.dispatcher.preflight_profiles(
                    [profile],
                    self.env,
                    QueueSession([response]),
                    sleep=lambda _: None,
                )
                self.assertEqual([], usable)
                self.assertEqual(1, len(failures))
                self.assertEqual(expected_code, failures[0].error_code)
                self.assertNotIn("body must not leak", repr(failures))

    def test_preflight_reports_every_failed_profile_without_secret_values(self):
        profiles = self.profiles[:2]
        session = QueueSession(
            [
                FakeResponse(status_code=401),
                FakeResponse(payload={"name": "wrong-name"}),
            ]
        )

        with self.assertLogs(self.dispatcher.LOGGER, level="ERROR") as captured:
            usable, failures = self.dispatcher.preflight_profiles(
                profiles, self.env, session, sleep=lambda _: None
            )

        logs = "\n".join(captured.output)
        self.assertEqual([], usable)
        self.assertEqual(2, len(failures))
        self.assertEqual(
            ["webhook_preflight_failed", "webhook_name_mismatch"],
            [item.error_code for item in failures],
        )
        self.assertEqual(2, len(session.calls))
        self.assertIn("profile_id=top_us reason=http_401", logs)
        self.assertIn("profile_id=top_kr reason=name_mismatch", logs)
        self.assertNotIn("discord.com", logs)
        self.assertNotIn("token1", logs)
        self.assertNotIn("token2", logs)

    def test_rate_limited_preflight_does_not_stop_other_profiles(self):
        profiles = self.profiles[:2]
        session = QueueSession(
            [
                FakeResponse(status_code=429),
                FakeResponse(payload={"name": profiles[1].expected_webhook_name}),
            ]
        )

        usable, failures = self.dispatcher.preflight_profiles(
            profiles, self.env, session, sleep=lambda _: None
        )

        self.assertEqual([profiles[1]], usable)
        self.assertEqual(
            ["webhook_rate_limited"], [item.error_code for item in failures]
        )
        self.assertEqual(2, len(session.calls))

    def test_preflight_failure_annotation_has_no_secret_values(self):
        profiles = self.profiles[:2]
        session = QueueSession(
            [
                FakeResponse(payload={"name": "wrong-name"}),
                FakeResponse(payload={"name": profiles[1].expected_webhook_name}),
            ]
        )

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.dispatcher.run_dispatch(
                profiles,
                self.env,
                self.state_dir,
                manual_test=True,
                session=session,
                subprocess_runner=self.successful_runner([]),
                sleep=lambda _: None,
            )

        rendered = output.getvalue()
        self.assertIn("::error title=Google News profile failed::", rendered)
        self.assertIn("profile={}".format(profiles[0].profile_id), rendered)
        self.assertIn("code=webhook_name_mismatch", rendered)
        self.assertNotIn("discord.com", rendered)
        self.assertNotIn("token1", rendered)

    def test_handlers_run_in_exact_registry_order_with_isolated_environments(self):
        calls = []
        summary = self.dispatcher.run_profiles(
            self.profiles,
            self.env,
            self.state_dir,
            manual_test=True,
            subprocess_runner=self.successful_runner(calls),
            sleep=lambda _: None,
        )

        self.assertEqual(
            [profile.profile_id for profile in self.profiles],
            [result.profile_id for result in summary.profiles],
        )
        self.assertEqual(11, len(calls))
        for profile, (_, child_env, check) in zip(self.profiles, calls):
            self.assertFalse(check)
            self.assertEqual(profile.profile_id, child_env["GOOGLE_NEWS_PROFILE_ID"])
            self.assertEqual("true", child_env["MANUAL_TEST_MODE"])
            self.assertEqual(
                "feed_oldest_first", child_env["GOOGLE_NEWS_DELIVERY_ORDER"]
            )
            self.assertNotIn("GOOGLE_NEWS_MAX_ITEMS", child_env)
            self.assertNotIn("GOOGLE_NEWS_MAX_AGE_MINUTES", child_env)
            other_secret_names = {item.webhook_env for item in self.profiles} - {
                profile.webhook_env
            }
            self.assertTrue(other_secret_names.isdisjoint(child_env))

    def test_run_profiles_exports_safe_unmapped_publisher_counts(self):
        calls = []
        profile = self.profiles[0]
        registry = self.dispatcher.load_default_registry()
        review = load_module("google_news_publisher_review")

        def runner(command, env, check):
            calls.append((command, env, check))
            resolution = registry.resolve(
                "news.example.com",
                "https://news.example.com/private/path?secret=value",
            )
            review.record_unmapped_publisher(
                env["GOOGLE_NEWS_DB_PATH"],
                env["GOOGLE_NEWS_PROFILE_ID"],
                "private-guid:related:0",
                "related",
                resolution,
            )
            self.result_module.write_profile_result(
                env["GOOGLE_NEWS_RESULT_PATH"],
                env["GOOGLE_NEWS_PROFILE_ID"],
                "success",
                1,
                0,
            )
            return SimpleNamespace(returncode=0)

        summary = self.dispatcher.run_profiles(
            [profile],
            self.env,
            self.state_dir,
            manual_test=False,
            subprocess_runner=runner,
            sleep=lambda _: None,
            publisher_registry=registry,
        )

        self.assertEqual(1, summary.unmapped_publisher_count)
        self.assertEqual(1, summary.new_unmapped_publisher_count)
        review_path = Path(self.state_dir) / "unmapped-google-news-publishers.json"
        payload = json.loads(review_path.read_text(encoding="utf-8"))
        self.assertEqual(1, payload["unmapped_publisher_count"])
        serialized = review_path.read_text(encoding="utf-8")
        self.assertNotIn("private/path", serialized)
        self.assertNotIn("secret=value", serialized)
        self.assertNotIn("private-guid", serialized)

    def test_profile_selection_supports_all_or_one_exact_profile(self):
        self.assertEqual(
            self.profiles,
            self.dispatcher.select_profiles(self.profiles, None),
        )
        selected = self.dispatcher.select_profiles(self.profiles, "top_kr")
        self.assertEqual(["top_kr"], [profile.profile_id for profile in selected])

    def test_unknown_profile_id_fails_before_webhook_preflight(self):
        with mock.patch.object(
            self.dispatcher, "load_profiles", return_value=self.profiles
        ), mock.patch.object(self.dispatcher, "run_dispatch") as run_dispatch:
            exit_code = self.dispatcher.main(
                [
                    "--state-dir",
                    self.state_dir,
                    "--manual-test",
                    "--profile-id",
                    "missing_profile",
                ]
            )

        self.assertEqual(1, exit_code)
        run_dispatch.assert_not_called()
        payload = json.loads(
            (Path(self.state_dir) / "run-summary.json").read_text(encoding="utf-8")
        )
        self.assertEqual("unknown_profile_id", payload["error_code"])

    def test_validation_mode_skips_webhook_preflight_and_marks_child_environments(self):
        calls = []
        session = QueueSession([])
        env = {"PATH": self.env["PATH"]}
        summary = self.dispatcher.run_dispatch(
            self.profiles[:2],
            env,
            self.state_dir,
            manual_test=True,
            validate_only=True,
            session=session,
            subprocess_runner=self.successful_runner(calls),
            sleep=lambda _: None,
        )

        self.assertEqual([], session.calls)
        self.assertTrue(summary.validate_only)
        self.assertEqual(2, len(calls))
        self.assertTrue(
            all(call[1]["GOOGLE_NEWS_VALIDATE_ONLY"] == "true" for call in calls)
        )

    def test_local_profile_failure_does_not_stop_later_profiles(self):
        profiles = self.profiles[:2]
        call_count = 0

        def runner(command, env, check):
            nonlocal call_count
            call_count += 1
            status = "failed" if call_count == 1 else "success"
            error_code = "profile_run_failed" if call_count == 1 else None
            self.result_module.write_profile_result(
                env["GOOGLE_NEWS_RESULT_PATH"],
                env["GOOGLE_NEWS_PROFILE_ID"],
                status,
                0 if call_count == 1 else 1,
                0,
                error_code,
            )
            return SimpleNamespace(returncode=1 if call_count == 1 else 0)

        summary = self.dispatcher.run_profiles(
            profiles,
            self.env,
            self.state_dir,
            manual_test=False,
            subprocess_runner=runner,
            sleep=lambda _: None,
        )

        self.assertEqual(2, call_count)
        self.assertEqual(["failed", "success"], [item.status for item in summary.profiles])
        self.assertEqual("failed", summary.status)

    def test_shared_google_circuit_skips_remaining_subprocesses(self):
        profiles = self.profiles[:3]
        calls = []

        def runner(command, env, check):
            calls.append(env["GOOGLE_NEWS_PROFILE_ID"])
            with sqlite3.connect(env["GOOGLE_NEWS_RESOLVER_DB_PATH"]) as connection:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO google_news_resolver_state (
                        state_key, blocked_until, last_error_code, updated_at
                    ) VALUES ('global', ?, 'http_429', ?)
                    """,
                    (
                        (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
            self.result_module.write_profile_result(
                env["GOOGLE_NEWS_RESULT_PATH"],
                env["GOOGLE_NEWS_PROFILE_ID"],
                "failed",
                0,
                0,
                "http_429",
            )
            return SimpleNamespace(returncode=1)

        summary = self.dispatcher.run_profiles(
            profiles,
            self.env,
            self.state_dir,
            manual_test=False,
            subprocess_runner=runner,
            sleep=lambda _: None,
        )

        self.assertEqual([profiles[0].profile_id], calls)
        self.assertEqual(
            ["failed", "skipped", "skipped"],
            [item.status for item in summary.profiles],
        )
        self.assertTrue(
            all(item.error_code == "circuit_open" for item in summary.profiles[1:])
        )

    def test_dispatch_summary_contains_no_urls_or_environment_values(self):
        calls = []
        summary = self.dispatcher.run_dispatch(
            self.profiles[:1],
            self.env,
            self.state_dir,
            manual_test=True,
            session=self.metadata_session(self.profiles[:1]),
            subprocess_runner=self.successful_runner(calls),
            sleep=lambda _: None,
        )

        serialized = json.dumps(summary.to_dict(), sort_keys=True)
        self.assertNotIn("discord.com", serialized)
        self.assertNotIn("token1", serialized)
        self.assertNotIn(self.env["PATH"], serialized)
        summary_path = Path(self.state_dir) / "run-summary.json"
        self.assertEqual(summary.to_dict(), json.loads(summary_path.read_text(encoding="utf-8")))

    def test_cli_preflight_failure_still_writes_a_safe_state_summary(self):
        with mock.patch.object(
            self.dispatcher, "load_profiles", return_value=self.profiles
        ), mock.patch.object(
            self.dispatcher,
            "run_dispatch",
            side_effect=RuntimeError("webhook_name_mismatch"),
        ):
            exit_code = self.dispatcher.main(
                ["--state-dir", self.state_dir, "--manual-test"]
            )

        self.assertEqual(1, exit_code)
        payload = json.loads(
            (Path(self.state_dir) / "run-summary.json").read_text(encoding="utf-8")
        )
        self.assertEqual("failed", payload["status"])
        self.assertEqual("webhook_name_mismatch", payload["error_code"])
        self.assertEqual([], payload["profiles"])

    def test_failed_profile_emits_safe_error_annotation(self):
        profile = self.profiles[0]

        def runner(command, env, check):
            self.result_module.write_profile_result(
                env["GOOGLE_NEWS_RESULT_PATH"],
                env["GOOGLE_NEWS_PROFILE_ID"],
                "failed",
                0,
                3,
                "http_429",
            )
            return SimpleNamespace(returncode=1)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.dispatcher.run_profiles(
                [profile],
                self.env,
                self.state_dir,
                manual_test=False,
                subprocess_runner=runner,
                sleep=lambda _: None,
            )

        rendered = output.getvalue()
        self.assertIn("::error title=Google News profile failed::", rendered)
        self.assertIn("profile={}".format(profile.profile_id), rendered)
        self.assertIn("code=http_429", rendered)
        self.assertIn("pending=3", rendered)
        self.assertNotIn("discord.com", rendered)
        self.assertNotIn("token1", rendered)

    def test_shared_circuit_emits_deferred_warning_with_resume_time(self):
        profiles = self.profiles[:2]
        blocked_until = datetime.now(timezone.utc) + timedelta(hours=1)

        def runner(command, env, check):
            if env["GOOGLE_NEWS_PROFILE_ID"] == profiles[0].profile_id:
                with sqlite3.connect(env["GOOGLE_NEWS_RESOLVER_DB_PATH"]) as connection:
                    connection.execute(
                        """
                        INSERT OR REPLACE INTO google_news_resolver_state (
                            state_key, blocked_until, last_error_code, updated_at
                        ) VALUES ('global', ?, 'http_429', ?)
                        """,
                        (blocked_until.isoformat(), datetime.now(timezone.utc).isoformat()),
                    )
                self.result_module.write_profile_result(
                    env["GOOGLE_NEWS_RESULT_PATH"],
                    env["GOOGLE_NEWS_PROFILE_ID"],
                    "failed",
                    0,
                    0,
                    "http_429",
                )
                return SimpleNamespace(returncode=1)
            raise AssertionError("deferred profile must not start a handler")

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            summary = self.dispatcher.run_profiles(
                profiles,
                self.env,
                self.state_dir,
                manual_test=False,
                subprocess_runner=runner,
                sleep=lambda _: None,
            )

        rendered = output.getvalue()
        self.assertIn("::warning title=Google News delivery deferred::", rendered)
        self.assertIn("profiles={}".format(profiles[1].profile_id), rendered)
        self.assertIn(blocked_until.isoformat(), rendered)
        self.assertEqual(blocked_until.isoformat(), summary.circuit_blocked_until)
        self.assertEqual("http_429", summary.circuit_error_code)

    def test_unexpected_dispatch_error_is_summarized_without_raw_message(self):
        with mock.patch.object(
            self.dispatcher, "load_profiles", return_value=self.profiles
        ), mock.patch.object(
            self.dispatcher,
            "run_dispatch",
            side_effect=sqlite3.OperationalError("disk I/O error: /private/path"),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = self.dispatcher.main(
                    ["--state-dir", self.state_dir, "--manual-test"]
                )

        self.assertEqual(1, exit_code)
        payload = json.loads(
            (Path(self.state_dir) / "run-summary.json").read_text(encoding="utf-8")
        )
        self.assertEqual("failed", payload["status"])
        self.assertEqual("unexpected_operational_error", payload["error_code"])
        rendered = output.getvalue()
        self.assertIn("::error title=Google News dispatcher failed::", rendered)
        self.assertIn("unexpected_operational_error", rendered)
        self.assertNotIn("/private/path", rendered)

    def test_preflight_retries_transient_server_error_once(self):
        profile = self.profiles[0]
        session = QueueSession(
            [
                FakeResponse(503),
                FakeResponse(payload={"name": profile.expected_webhook_name}),
            ]
        )
        calls = []

        summary = self.dispatcher.run_dispatch(
            [profile],
            self.env,
            self.state_dir,
            manual_test=True,
            session=session,
            subprocess_runner=self.successful_runner(calls),
            sleep=lambda _: None,
        )

        self.assertEqual("success", summary.status)
        self.assertEqual(2, len(session.calls))
        self.assertEqual(1, len(calls))

    def test_preflight_retry_exhaustion_is_annotated_and_fails_closed(self):
        profile = self.profiles[0]
        session = QueueSession([FakeResponse(503), FakeResponse(503)])

        output = io.StringIO()
        with self.assertLogs(self.dispatcher.LOGGER, level="ERROR") as captured:
            with contextlib.redirect_stdout(output):
                summary = self.dispatcher.run_dispatch(
                    [profile],
                    self.env,
                    self.state_dir,
                    manual_test=True,
                    session=session,
                    subprocess_runner=mock.Mock(),
                    sleep=lambda _: None,
                )

        self.assertEqual("failed", summary.status)
        self.assertEqual(
            "webhook_preflight_failed", summary.profiles[0].error_code
        )
        rendered = output.getvalue()
        self.assertIn("::error title=Google News profile failed::", rendered)
        self.assertIn("profile={}".format(profile.profile_id), rendered)
        self.assertIn("code=webhook_preflight_failed", rendered)
        self.assertIn("reason=http_503", "\n".join(captured.output))
        self.assertNotIn("discord.com", rendered)

    def test_dispatch_prunes_expired_state_before_summary(self):
        profile = self.profiles[0]
        state_path = Path(self.state_dir)
        state_path.mkdir(parents=True, exist_ok=True)
        database_path = state_path / profile.state_db
        with sqlite3.connect(str(database_path)) as connection:
            connection.execute(
                "CREATE TABLE news_items (pub_date TEXT, guid TEXT PRIMARY KEY, "
                "title TEXT, link TEXT, related_news TEXT)"
            )
            connection.execute(
                "INSERT INTO news_items (pub_date, guid, title, link, related_news) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    (
                        datetime.now(timezone.utc) - timedelta(days=40)
                    ).strftime("%a, %d %b %Y %H:%M:%S GMT"),
                    "expired-guid",
                    "Expired article",
                    "https://publisher.example/expired",
                    "[]",
                ),
            )

        calls = []
        summary = self.dispatcher.run_profiles(
            [profile],
            self.env,
            self.state_dir,
            manual_test=False,
            subprocess_runner=self.successful_runner(calls),
            sleep=lambda _: None,
        )

        with sqlite3.connect(str(database_path)) as connection:
            remaining = connection.execute(
                "SELECT COUNT(*) FROM news_items WHERE guid = 'expired-guid'"
            ).fetchone()[0]
        self.assertEqual(0, remaining)
        self.assertEqual(1, summary.retention["items"])
        self.assertEqual(1, summary.to_dict()["retention"]["items"])

    def test_all_skipped_run_fails_with_error_code(self):
        profiles = self.profiles[:2]
        state_path = Path(self.state_dir)
        state_path.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(state_path / "resolver.db")) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS google_news_resolver_state ("
                "state_key TEXT PRIMARY KEY, blocked_until TEXT, "
                "last_error_code TEXT, updated_at TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT OR REPLACE INTO google_news_resolver_state "
                "(state_key, blocked_until, last_error_code, updated_at) "
                "VALUES ('global', ?, 'http_429', ?)",
                (
                    (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        runner = mock.Mock()

        summary = self.dispatcher.run_profiles(
            profiles,
            self.env,
            self.state_dir,
            manual_test=False,
            subprocess_runner=runner,
            sleep=lambda _: None,
        )

        runner.assert_not_called()
        self.assertEqual(["skipped", "skipped"], [item.status for item in summary.profiles])
        self.assertEqual("failed", summary.status)
        self.assertEqual("all_profiles_skipped", summary.error_code)

    def test_summary_records_github_run_id(self):
        with mock.patch.dict(os.environ, {"GITHUB_RUN_ID": "43669743020"}):
            summary = self.dispatcher.run_profiles(
                [self.profiles[0]],
                self.env,
                self.state_dir,
                manual_test=False,
                subprocess_runner=self.successful_runner([]),
                sleep=lambda _: None,
            )

        self.assertEqual("43669743020", summary.run_id)
        self.assertEqual("43669743020", summary.to_dict()["run_id"])


if __name__ == "__main__":
    unittest.main()
