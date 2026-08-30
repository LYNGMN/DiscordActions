import importlib
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

    def test_preflight_mismatch_runs_zero_handlers(self):
        session = QueueSession([FakeResponse(payload={"name": "wrong-name"})])
        runner = mock.Mock()

        with self.assertRaisesRegex(RuntimeError, "webhook_name_mismatch"):
            self.dispatcher.run_dispatch(
                self.profiles,
                self.env,
                self.state_dir,
                manual_test=True,
                session=session,
                subprocess_runner=runner,
                sleep=lambda _: None,
            )

        runner.assert_not_called()

    def test_preflight_rejects_missing_or_non_https_secrets_before_network(self):
        cases = (
            (None, "missing_webhook"),
            ("http://example.com", "invalid_webhook"),
            ("https://name@discord.com/api/webhooks/1/token", "invalid_webhook"),
            ("https://discord.com:444/api/webhooks/1/token", "invalid_webhook"),
        )
        for value, expected_code in cases:
            with self.subTest(value=value):
                env = dict(self.env)
                if value is None:
                    env.pop(self.profiles[0].webhook_env)
                else:
                    env[self.profiles[0].webhook_env] = value
                session = QueueSession([])
                with self.assertRaisesRegex(RuntimeError, expected_code):
                    self.dispatcher.validate_webhooks(self.profiles, env, session)
                self.assertEqual([], session.calls)

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

    def test_preflight_rejects_rate_limit_and_invalid_json_with_safe_codes(self):
        cases = (
            (FakeResponse(status_code=429), "webhook_rate_limited"),
            (FakeResponse(json_error=ValueError("body must not leak")), "webhook_metadata_invalid"),
        )
        for response, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                with self.assertRaisesRegex(RuntimeError, expected_code) as raised:
                    self.dispatcher.validate_webhooks(
                        self.profiles, self.env, QueueSession([response])
                    )
                self.assertNotIn("body must not leak", str(raised.exception))

    def test_preflight_reports_every_failed_profile_without_secret_values(self):
        profiles = self.profiles[:2]
        session = QueueSession(
            [
                FakeResponse(status_code=401),
                FakeResponse(payload={"name": "wrong-name"}),
            ]
        )

        with self.assertLogs(self.dispatcher.LOGGER, level="ERROR") as captured:
            with self.assertRaisesRegex(RuntimeError, "webhook_preflight_failed"):
                self.dispatcher.validate_webhooks(profiles, self.env, session)

        logs = "\n".join(captured.output)
        self.assertEqual(2, len(session.calls))
        self.assertIn("profile_id=top_us reason=http_401", logs)
        self.assertIn("profile_id=top_kr reason=name_mismatch", logs)
        self.assertNotIn("discord.com", logs)
        self.assertNotIn("token1", logs)
        self.assertNotIn("token2", logs)

    def test_preflight_rate_limit_stops_remaining_metadata_requests(self):
        profiles = self.profiles[:2]
        session = QueueSession(
            [
                FakeResponse(status_code=429),
                FakeResponse(payload={"name": profiles[1].expected_webhook_name}),
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "webhook_rate_limited"):
            self.dispatcher.validate_webhooks(profiles, self.env, session)

        self.assertEqual(1, len(session.calls))

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
            self.assertEqual("3", child_env["GOOGLE_NEWS_MAX_ITEMS"])
            self.assertEqual("120", child_env["GOOGLE_NEWS_MAX_AGE_MINUTES"])
            other_secret_names = {item.webhook_env for item in self.profiles} - {
                profile.webhook_env
            }
            self.assertTrue(other_secret_names.isdisjoint(child_env))

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


if __name__ == "__main__":
    unittest.main()
