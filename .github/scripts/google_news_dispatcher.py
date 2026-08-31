"""Sequential, preflighted dispatcher for all configured Google News profiles."""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Mapping, Optional, Sequence
from urllib.parse import urlparse

import requests

from google_news_profile_result import ERROR_CODE, STATUSES
from google_news_profiles import (
    GoogleNewsProfile,
    build_handler_environment,
    load_profiles,
    validate_common_feed_environment,
)
from google_news_request_guard import GoogleNewsRequestGuard


LOGGER = logging.getLogger(__name__)
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_PROFILES_PATH = SCRIPT_DIR.parent / "config" / "google_news_profiles.json"
HANDLERS = {
    "top": SCRIPT_DIR / "googlenews-top_to_discord.py",
    "topic": SCRIPT_DIR / "googlenews-topic_to_discord.py",
    "keyword": SCRIPT_DIR / "googlenews-keyword_to_discord.py",
}
WEBHOOK_PATH = re.compile(r"^/api/webhooks/[0-9]+/[A-Za-z0-9._-]+$")
RESULT_FIELDS = {
    "profile_id",
    "status",
    "processed_count",
    "pending_count",
    "ambiguous_retry_count",
    "error_code",
}


@dataclass(frozen=True)
class ProfileRunResult:
    profile_id: str
    status: str
    processed_count: int
    pending_count: int
    ambiguous_retry_count: int
    error_code: Optional[str]

    @classmethod
    def skipped(cls, profile_id: str, error_code: str) -> "ProfileRunResult":
        return cls(profile_id, "skipped", 0, 0, 0, error_code)

    @classmethod
    def failed(cls, profile_id: str, error_code: str) -> "ProfileRunResult":
        return cls(profile_id, "failed", 0, 0, 0, error_code)

    def to_dict(self):
        return {
            "profile_id": self.profile_id,
            "status": self.status,
            "processed_count": self.processed_count,
            "pending_count": self.pending_count,
            "ambiguous_retry_count": self.ambiguous_retry_count,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class DispatchSummary:
    status: str
    manual_test: bool
    validate_only: bool
    error_code: Optional[str]
    started_at: str
    finished_at: str
    profiles: Sequence[ProfileRunResult]

    def to_dict(self):
        return {
            "status": self.status,
            "manual_test": self.manual_test,
            "validate_only": self.validate_only,
            "error_code": self.error_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "profiles": [profile.to_dict() for profile in self.profiles],
        }


def validate_webhooks(
    profiles: Sequence[GoogleNewsProfile],
    env: Mapping[str, str],
    session: requests.Session,
) -> None:
    validated_urls = []
    for profile in profiles:
        value = env.get(profile.webhook_env, "")
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError("missing_webhook")
        parsed = urlparse(value.strip())
        if (
            parsed.scheme != "https"
            or parsed.hostname not in {"discord.com", "discordapp.com"}
            or parsed.netloc != parsed.hostname
            or parsed.query
            or parsed.fragment
            or not WEBHOOK_PATH.fullmatch(parsed.path)
        ):
            raise RuntimeError("invalid_webhook")
        validated_urls.append((profile, value.strip()))

    first_error_code = None
    for profile, webhook_url in validated_urls:
        error_code = None
        reason = None
        try:
            response = session.get(webhook_url, timeout=(5.0, 15.0))
        except Exception:
            error_code = "webhook_preflight_failed"
            reason = "request_error"
        else:
            if response.status_code == 429:
                error_code = "webhook_rate_limited"
                reason = "http_429"
            elif response.status_code != 200:
                error_code = "webhook_preflight_failed"
                reason = "http_{}".format(response.status_code)
            else:
                try:
                    payload = response.json()
                except (TypeError, ValueError):
                    error_code = "webhook_metadata_invalid"
                    reason = "invalid_json"
                else:
                    if not isinstance(payload, dict) or not isinstance(
                        payload.get("name"), str
                    ):
                        error_code = "webhook_metadata_invalid"
                        reason = "invalid_metadata"
                    elif payload["name"] != profile.expected_webhook_name:
                        error_code = "webhook_name_mismatch"
                        reason = "name_mismatch"

        if error_code is not None:
            LOGGER.error(
                "Discord webhook preflight failed: profile_id=%s reason=%s",
                profile.profile_id,
                reason,
            )
            if first_error_code is None:
                first_error_code = error_code
            if error_code == "webhook_rate_limited":
                break

    if first_error_code is not None:
        raise RuntimeError(first_error_code)


def run_profiles(
    profiles: Sequence[GoogleNewsProfile],
    env: Mapping[str, str],
    state_dir: str,
    manual_test: bool,
    validate_only: bool = False,
    subprocess_runner: Callable = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
) -> DispatchSummary:
    started_at = _utc_timestamp()
    state_path = Path(state_dir)
    state_path.mkdir(parents=True, exist_ok=True)
    resolver_db = str(state_path / "resolver.db")
    circuit_reader = GoogleNewsRequestGuard(requests.Session(), resolver_db)
    results: List[ProfileRunResult] = []

    with tempfile.TemporaryDirectory(prefix="google-news-results-", dir=state_dir) as result_dir:
        for index, profile in enumerate(profiles):
            if circuit_reader.get_open_circuit() is not None:
                results.append(ProfileRunResult.skipped(profile.profile_id, "circuit_open"))
                continue

            try:
                profile_env = dict(env)
                if validate_only:
                    profile_env[profile.webhook_env] = "validation-only"
                child_env = build_handler_environment(
                    profile, profile_env, state_dir, resolver_db, manual_test
                )
            except ValueError:
                results.append(ProfileRunResult.failed(profile.profile_id, "invalid_environment"))
                continue
            result_path = str(Path(result_dir) / "{}.json".format(profile.profile_id))
            child_env.update(
                {
                    "GOOGLE_NEWS_RESULT_PATH": result_path,
                    "GOOGLE_NEWS_VALIDATE_ONLY": "true" if validate_only else "false",
                }
            )
            try:
                completed = subprocess_runner(
                    [sys.executable, str(HANDLERS[profile.handler])],
                    env=child_env,
                    check=False,
                )
            except Exception:
                results.append(ProfileRunResult.failed(profile.profile_id, "handler_start_failed"))
                continue

            results.append(
                _read_profile_result(profile.profile_id, result_path, completed.returncode)
            )
            if (
                index + 1 < len(profiles)
                and circuit_reader.get_open_circuit() is None
            ):
                sleep(1.0)

    status = "failed" if any(result.status == "failed" for result in results) else "success"
    summary = DispatchSummary(
        status=status,
        manual_test=bool(manual_test),
        validate_only=bool(validate_only),
        error_code=None,
        started_at=started_at,
        finished_at=_utc_timestamp(),
        profiles=tuple(results),
    )
    _write_summary(state_path / "run-summary.json", summary)
    return summary


def run_dispatch(
    profiles: Sequence[GoogleNewsProfile],
    env: Mapping[str, str],
    state_dir: str,
    manual_test: bool,
    validate_only: bool = False,
    session: Optional[requests.Session] = None,
    subprocess_runner: Callable = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
) -> DispatchSummary:
    for profile in profiles:
        merged_environment = dict(env)
        merged_environment.update(profile.environment)
        validate_common_feed_environment(merged_environment)
    if not validate_only:
        validate_webhooks(profiles, env, session or requests.Session())
    return run_profiles(
        profiles,
        env,
        state_dir,
        manual_test,
        validate_only=validate_only,
        subprocess_runner=subprocess_runner,
        sleep=sleep,
    )


def _read_profile_result(
    expected_profile_id: str, path: str, return_code: int
) -> ProfileRunResult:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return ProfileRunResult.failed(expected_profile_id, "missing_result")
    if not isinstance(payload, dict) or set(payload) != RESULT_FIELDS:
        return ProfileRunResult.failed(expected_profile_id, "invalid_result")
    if payload.get("profile_id") != expected_profile_id:
        return ProfileRunResult.failed(expected_profile_id, "invalid_result")
    status = payload.get("status")
    error_code = payload.get("error_code")
    processed_count = payload.get("processed_count")
    pending_count = payload.get("pending_count")
    ambiguous_retry_count = payload.get("ambiguous_retry_count")
    if (
        status not in STATUSES
        or isinstance(processed_count, bool)
        or not isinstance(processed_count, int)
        or processed_count < 0
        or isinstance(pending_count, bool)
        or not isinstance(pending_count, int)
        or pending_count < 0
        or isinstance(ambiguous_retry_count, bool)
        or not isinstance(ambiguous_retry_count, int)
        or ambiguous_retry_count < 0
        or (
            error_code is not None
            and (not isinstance(error_code, str) or not ERROR_CODE.fullmatch(error_code))
        )
    ):
        return ProfileRunResult.failed(expected_profile_id, "invalid_result")
    if return_code != 0 and status == "success":
        return ProfileRunResult.failed(expected_profile_id, "handler_exit_nonzero")
    return ProfileRunResult(
        expected_profile_id,
        status,
        processed_count,
        pending_count,
        ambiguous_retry_count,
        error_code,
    )


def _write_summary(path: Path, summary: DispatchSummary) -> None:
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=".run-summary-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = handle.name
            json.dump(summary.to_dict(), handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_path, str(path))
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run configured Google News profiles")
    parser.add_argument("--profiles", default=str(DEFAULT_PROFILES_PATH))
    parser.add_argument("--state-dir", default=".google-news-state")
    parser.add_argument("--manual-test", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    try:
        profiles = load_profiles(arguments.profiles)
        summary = run_dispatch(
            profiles,
            os.environ,
            arguments.state_dir,
            arguments.manual_test,
            validate_only=arguments.validate_only,
        )
    except (OSError, ValueError, RuntimeError) as error:
        error_code = str(error)
        if not ERROR_CODE.fullmatch(error_code):
            error_code = "dispatch_failed"
        state_path = Path(arguments.state_dir)
        state_path.mkdir(parents=True, exist_ok=True)
        failed_summary = DispatchSummary(
            status="failed",
            manual_test=bool(arguments.manual_test),
            validate_only=bool(arguments.validate_only),
            error_code=error_code,
            started_at=_utc_timestamp(),
            finished_at=_utc_timestamp(),
            profiles=tuple(),
        )
        _write_summary(state_path / "run-summary.json", failed_summary)
        LOGGER.error("Google News 디스패처 실패 (코드: %s)", error_code)
        return 1
    LOGGER.info(
        "Google News 디스패처 완료: status=%s profiles=%s",
        summary.status,
        len(summary.profiles),
    )
    return 1 if summary.status == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
