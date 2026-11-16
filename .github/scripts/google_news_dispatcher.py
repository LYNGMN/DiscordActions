"""Sequential, preflighted dispatcher for all configured Google News profiles."""

import argparse
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse

import requests

from delivery_admin_alert import current_actions_url, notify_admin_text

from google_news_delivery_state import (
    DEFAULT_RETENTION_DAYS,
    DEFAULT_URL_CACHE_RETENTION_DAYS,
    apply_state_retention,
    count_unfinished_deliveries,
    expire_stale_deliveries,
    state_retention_days,
    url_cache_retention_days as parse_url_cache_retention_days,
)
from google_news_profile_result import ERROR_CODE, STATUSES
from google_news_publisher_names import PublisherRegistry, load_default_registry
from google_news_publisher_review import (
    export_unmapped_publishers,
    unmapped_publisher_keys,
)
from google_news_profiles import (
    GoogleNewsProfile,
    build_handler_environment,
    load_profiles,
    validate_common_feed_environment,
)
from google_news_request_guard import CircuitState, GoogleNewsRequestGuard
from run_events import emit_event, truncate_events_file


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
    "filtered_count",
    "duplicate_count",
    "queued_count",
    "deferred_count",
    "truncated_count",
    "error_code",
}
ANNOTATION_LIMIT = 10
PREFLIGHT_ATTEMPTS = 2
PREFLIGHT_RETRY_DELAY_SECONDS = 2.0
DEFAULT_RUN_BUDGET_SECONDS = 1080
MIN_RUN_BUDGET_SECONDS = 60
MAX_RUN_BUDGET_SECONDS = 1200
MIN_PROFILE_BUDGET_SECONDS = 60
DEFAULT_BACKLOG_LIMIT = 500
MIN_BACKLOG_LIMIT = 1
MAX_BACKLOG_LIMIT = 10000
DEFAULT_BACKLOG_AGE_DAYS = 3
MIN_BACKLOG_AGE_DAYS = 1
MAX_BACKLOG_AGE_DAYS = 30


def parse_backlog_limit(value: str = "500") -> int:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,4}", value):
        raise ValueError("invalid_google_news_backlog_limit")
    parsed = int(value)
    if parsed > MAX_BACKLOG_LIMIT:
        raise ValueError("invalid_google_news_backlog_limit")
    return parsed


def parse_backlog_age_days(value: str = "3") -> int:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]?", value):
        raise ValueError("invalid_google_news_backlog_age")
    parsed = int(value)
    if parsed > MAX_BACKLOG_AGE_DAYS:
        raise ValueError("invalid_google_news_backlog_age")
    return parsed


def run_budget_seconds(value: str = "1080") -> int:
    """Bound one run so state is uploaded before the job timeout."""
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,3}", value):
        raise ValueError("invalid_google_news_run_budget")
    parsed = int(value)
    if not MIN_RUN_BUDGET_SECONDS <= parsed <= MAX_RUN_BUDGET_SECONDS:
        raise ValueError("invalid_google_news_run_budget")
    return parsed


@dataclass(frozen=True)
class ProfileRunResult:
    profile_id: str
    status: str
    processed_count: int
    pending_count: int
    ambiguous_retry_count: int
    error_code: Optional[str]
    filtered_count: int = 0
    duplicate_count: int = 0
    queued_count: int = 0
    deferred_count: int = 0
    truncated_count: int = 0

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
            "filtered_count": self.filtered_count,
            "duplicate_count": self.duplicate_count,
            "queued_count": self.queued_count,
            "deferred_count": self.deferred_count,
            "truncated_count": self.truncated_count,
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
    unmapped_publisher_count: int = 0
    new_unmapped_publisher_count: int = 0
    retention: Mapping[str, int] = field(default_factory=dict)
    circuit_error_code: Optional[str] = None
    circuit_blocked_until: Optional[str] = None
    run_id: Optional[str] = None
    backlog_expired: int = 0
    backlog: Sequence[Mapping[str, object]] = ()

    def to_dict(self):
        return {
            "status": self.status,
            "manual_test": self.manual_test,
            "validate_only": self.validate_only,
            "error_code": self.error_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "profiles": [profile.to_dict() for profile in self.profiles],
            "unmapped_publisher_count": self.unmapped_publisher_count,
            "new_unmapped_publisher_count": self.new_unmapped_publisher_count,
            "retention": dict(self.retention),
            "circuit_error_code": self.circuit_error_code,
            "circuit_blocked_until": self.circuit_blocked_until,
            "run_id": self.run_id,
            "backlog_expired": self.backlog_expired,
            "backlog": [dict(item) for item in self.backlog],
        }


def preflight_profiles(
    profiles: Sequence[GoogleNewsProfile],
    env: Mapping[str, str],
    session: requests.Session,
    sleep: Callable[[float], None] = time.sleep,
) -> Tuple[List[GoogleNewsProfile], List[ProfileRunResult]]:
    """Check each webhook independently and keep the usable profiles.

    A broken or missing webhook must never stop delivery for every other
    channel, so only the affected profile is marked failed.
    """
    validated_urls = []
    failures = []
    for profile in profiles:
        value = env.get(profile.webhook_env, "")
        if not isinstance(value, str) or not value.strip():
            LOGGER.error(
                "Discord webhook preflight failed: profile_id=%s reason=missing_webhook",
                profile.profile_id,
            )
            failures.append(ProfileRunResult.failed(profile.profile_id, "missing_webhook"))
            continue
        parsed = urlparse(value.strip())
        if (
            parsed.scheme != "https"
            or parsed.hostname not in {"discord.com", "discordapp.com"}
            or parsed.netloc != parsed.hostname
            or parsed.query
            or parsed.fragment
            or not WEBHOOK_PATH.fullmatch(parsed.path)
        ):
            LOGGER.error(
                "Discord webhook preflight failed: profile_id=%s reason=invalid_webhook",
                profile.profile_id,
            )
            failures.append(ProfileRunResult.failed(profile.profile_id, "invalid_webhook"))
            continue
        validated_urls.append((profile, value.strip()))

    usable = []
    for profile, webhook_url in validated_urls:
        response, request_error = _fetch_webhook_metadata(
            session, webhook_url, sleep
        )
        error_code, reason = _webhook_metadata_error(
            profile, response, request_error
        )
        if error_code is None:
            usable.append(profile)
            continue
        LOGGER.error(
            "Discord webhook preflight failed: profile_id=%s reason=%s",
            profile.profile_id,
            reason,
        )
        failures.append(ProfileRunResult.failed(profile.profile_id, error_code))

    return usable, failures


def _webhook_metadata_error(
    profile: GoogleNewsProfile,
    response,
    request_error: Optional[str],
) -> Tuple[Optional[str], Optional[str]]:
    if request_error is not None:
        return "webhook_preflight_failed", request_error
    if response is None:
        return "webhook_preflight_failed", "request_error"
    if response.status_code == 429:
        return "webhook_rate_limited", "http_429"
    if response.status_code != 200:
        return "webhook_preflight_failed", "http_{}".format(response.status_code)
    try:
        payload = response.json()
    except (TypeError, ValueError):
        return "webhook_metadata_invalid", "invalid_json"
    if not isinstance(payload, dict) or not isinstance(payload.get("name"), str):
        return "webhook_metadata_invalid", "invalid_metadata"
    if payload["name"] != profile.expected_webhook_name:
        return "webhook_name_mismatch", "name_mismatch"
    return None, None


def _fetch_webhook_metadata(
    session: requests.Session,
    webhook_url: str,
    sleep: Callable[[float], None],
):
    """Retry one transient network or 5xx failure before failing the run."""
    last_error = "request_error"
    for attempt in range(PREFLIGHT_ATTEMPTS):
        try:
            response = session.get(webhook_url, timeout=(5.0, 15.0))
        except Exception:
            last_error = "request_error"
        else:
            if response.status_code < 500:
                return response, None
            last_error = "http_{}".format(response.status_code)
        if attempt + 1 < PREFLIGHT_ATTEMPTS:
            sleep(PREFLIGHT_RETRY_DELAY_SECONDS)
    return None, last_error


def run_profiles(
    profiles: Sequence[GoogleNewsProfile],
    env: Mapping[str, str],
    state_dir: str,
    manual_test: bool,
    validate_only: bool = False,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    subprocess_runner: Callable = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
    publisher_registry: Optional[PublisherRegistry] = None,
    profile_databases: Optional[Mapping[str, str]] = None,
    preflight_results: Sequence[ProfileRunResult] = (),
    run_deadline: Optional[float] = None,
    backlog_limit: int = DEFAULT_BACKLOG_LIMIT,
    backlog_age_days: int = DEFAULT_BACKLOG_AGE_DAYS,
    admin_notifier: Callable[[str, str], bool] = notify_admin_text,
    url_cache_retention_days: int = DEFAULT_URL_CACHE_RETENTION_DAYS,
) -> DispatchSummary:
    if (
        isinstance(backlog_limit, bool)
        or not isinstance(backlog_limit, int)
        or not MIN_BACKLOG_LIMIT <= backlog_limit <= MAX_BACKLOG_LIMIT
        or isinstance(backlog_age_days, bool)
        or not isinstance(backlog_age_days, int)
        or not MIN_BACKLOG_AGE_DAYS <= backlog_age_days <= MAX_BACKLOG_AGE_DAYS
    ):
        raise ValueError("invalid backlog settings")
    started_at = _utc_timestamp()
    state_path = Path(state_dir)
    state_path.mkdir(parents=True, exist_ok=True)
    _remove_stale_result_dirs(state_path)
    registry = publisher_registry or load_default_registry()
    database_map = dict(
        profile_databases
        or {profile.profile_id: profile.state_db for profile in profiles}
    )
    before_unmapped = unmapped_publisher_keys(
        state_path, database_map, registry
    )
    resolver_db = str(state_path / "resolver.db")
    circuit_reader = GoogleNewsRequestGuard(requests.Session(), resolver_db)
    results: List[ProfileRunResult] = list(preflight_results)
    for preflight_result in preflight_results:
        emit_event(
            "profile_result",
            profile=preflight_result.profile_id,
            status=preflight_result.status,
            code=preflight_result.error_code,
        )
    backlog_events: List[Dict[str, object]] = []
    backlog_now = datetime.now(timezone.utc)

    with tempfile.TemporaryDirectory(prefix="google-news-results-", dir=state_dir) as result_dir:
        for index, profile in enumerate(profiles):
            if not manual_test and not validate_only:
                event = _expire_profile_backlog(
                    profile,
                    state_path,
                    backlog_limit,
                    backlog_age_days,
                    backlog_now,
                )
                if event is not None:
                    backlog_events.append(event)
                    emit_event(
                        "backlog_expired",
                        profile=event["profile_id"],
                        expired=event["expired"],
                        pending=event["pending"],
                    )
            if (
                run_deadline is not None
                and run_deadline - time.time() < MIN_PROFILE_BUDGET_SECONDS
            ):
                results.extend(
                    ProfileRunResult.skipped(item.profile_id, "time_budget_exhausted")
                    for item in profiles[index:]
                )
                break
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
            except ValueError as error:
                LOGGER.error(
                    "Google News profile configuration invalid: profile_id=%s detail=%s",
                    profile.profile_id,
                    str(error),
                )
                emit_event(
                    "profile_config_invalid",
                    profile=profile.profile_id,
                    detail=str(error),
                )
                results.append(ProfileRunResult.failed(profile.profile_id, "invalid_environment"))
                continue
            result_path = str(Path(result_dir) / "{}.json".format(profile.profile_id))
            profile_started = time.monotonic()
            child_env.update(
                {
                    "GOOGLE_NEWS_RESULT_PATH": result_path,
                    "GOOGLE_NEWS_VALIDATE_ONLY": "true" if validate_only else "false",
                }
            )
            if run_deadline is not None:
                child_env["GOOGLE_NEWS_RUN_DEADLINE"] = "{:.3f}".format(run_deadline)
            try:
                completed = subprocess_runner(
                    [sys.executable, str(HANDLERS[profile.handler])],
                    env=child_env,
                    check=False,
                )
            except Exception:
                emit_event(
                    "profile_start_failed",
                    profile=profile.profile_id,
                    code="handler_start_failed",
                )
                results.append(ProfileRunResult.failed(profile.profile_id, "handler_start_failed"))
                continue

            profile_result = _read_profile_result(
                profile.profile_id, result_path, completed.returncode
            )
            results.append(profile_result)
            emit_event(
                "profile_result",
                profile=profile.profile_id,
                status=profile_result.status,
                processed=profile_result.processed_count,
                pending=profile_result.pending_count,
                filtered=profile_result.filtered_count,
                duplicates=profile_result.duplicate_count,
                queued=profile_result.queued_count,
                deferred=profile_result.deferred_count,
                truncated=profile_result.truncated_count,
                code=profile_result.error_code,
                duration_ms=int((time.monotonic() - profile_started) * 1000),
            )
            if (
                index + 1 < len(profiles)
                and circuit_reader.get_open_circuit() is None
            ):
                sleep(1.0)

    circuit_state = circuit_reader.get_open_circuit()
    retention = _prune_state_databases(
        state_path,
        database_map,
        retention_days,
        url_cache_retention_days,
    )
    emit_event(
        "state_pruned",
        items=retention.get("items", 0),
        messages=retention.get("messages", 0),
        identities=retention.get("identities", 0),
        url_cache=retention.get("url_cache", 0),
        databases=retention.get("databases", 0),
    )
    emitted = _emit_profile_annotations(results, circuit_state)
    _emit_backlog_annotations(backlog_events, emitted)
    _notify_backlog_expiry(backlog_events, env, admin_notifier)
    backlog_expired = sum(int(event["expired"]) for event in backlog_events)
    status = "failed" if any(result.status == "failed" for result in results) else "success"
    error_code = None
    if (
        status == "success"
        and results
        and all(result.status == "skipped" for result in results)
    ):
        status = "failed"
        error_code = "all_profiles_skipped"
    review_payload = export_unmapped_publishers(
        state_path, database_map, registry
    )
    after_unmapped = unmapped_publisher_keys(
        state_path, database_map, registry
    )
    summary = DispatchSummary(
        status=status,
        manual_test=bool(manual_test),
        validate_only=bool(validate_only),
        error_code=error_code,
        started_at=started_at,
        finished_at=_utc_timestamp(),
        profiles=tuple(results),
        unmapped_publisher_count=review_payload[
            "unmapped_publisher_count"
        ],
        new_unmapped_publisher_count=len(
            after_unmapped - before_unmapped
        ),
        retention=retention,
        circuit_error_code=(
            circuit_state.error_code if circuit_state is not None else None
        ),
        circuit_blocked_until=(
            circuit_state.blocked_until.isoformat()
            if circuit_state is not None
            else None
        ),
        run_id=os.environ.get("GITHUB_RUN_ID"),
        backlog_expired=backlog_expired,
        backlog=tuple(backlog_events),
    )
    _write_summary(state_path / "run-summary.json", summary)
    _report_run_totals(
        summary,
        results,
        env,
        state_path,
        manual_test,
        validate_only,
        admin_notifier,
    )
    return summary


def run_dispatch(
    profiles: Sequence[GoogleNewsProfile],
    env: Mapping[str, str],
    state_dir: str,
    manual_test: bool,
    validate_only: bool = False,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    run_deadline: Optional[float] = None,
    backlog_limit: int = DEFAULT_BACKLOG_LIMIT,
    backlog_age_days: int = DEFAULT_BACKLOG_AGE_DAYS,
    url_cache_retention_days: int = DEFAULT_URL_CACHE_RETENTION_DAYS,
    session: Optional[requests.Session] = None,
    subprocess_runner: Callable = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
    publisher_registry: Optional[PublisherRegistry] = None,
    profile_databases: Optional[Mapping[str, str]] = None,
) -> DispatchSummary:
    registry = publisher_registry or load_default_registry()
    database_map = dict(
        profile_databases
        or {profile.profile_id: profile.state_db for profile in profiles}
    )
    for profile in profiles:
        merged_environment = dict(env)
        merged_environment.update(profile.environment)
        validate_common_feed_environment(merged_environment)
    export_unmapped_publishers(state_dir, database_map, registry)
    usable_profiles = list(profiles)
    preflight_results: List[ProfileRunResult] = []
    if not validate_only:
        usable_profiles, preflight_results = preflight_profiles(
            profiles,
            env,
            session or requests.Session(),
            sleep=sleep,
        )
    return run_profiles(
        usable_profiles,
        env,
        state_dir,
        manual_test,
        validate_only=validate_only,
        retention_days=retention_days,
        subprocess_runner=subprocess_runner,
        sleep=sleep,
        publisher_registry=registry,
        profile_databases=database_map,
        preflight_results=preflight_results,
        run_deadline=run_deadline,
        backlog_limit=backlog_limit,
        backlog_age_days=backlog_age_days,
        url_cache_retention_days=url_cache_retention_days,
    )


def _remove_stale_result_dirs(state_path: Path) -> None:
    for path in state_path.glob("google-news-results-*"):
        if not path.is_dir():
            continue
        try:
            shutil.rmtree(path)
        except OSError as error:
            LOGGER.warning(
                "Could not remove a stale result directory (오류 유형: %s)",
                type(error).__name__,
            )


def _expire_profile_backlog(
    profile: GoogleNewsProfile,
    state_path: Path,
    backlog_limit: int,
    backlog_age_days: int,
    now: datetime,
) -> Optional[Dict[str, object]]:
    database_path = state_path / profile.state_db
    if not database_path.is_file():
        return None
    pending = count_unfinished_deliveries(str(database_path))
    if pending < backlog_limit:
        return None
    expired = expire_stale_deliveries(
        str(database_path), backlog_age_days, now
    )
    if expired <= 0:
        return None
    return {
        "profile_id": profile.profile_id,
        "pending": pending,
        "expired": expired,
        "remaining": pending - expired,
    }


def _emit_backlog_annotations(
    events: Sequence[Mapping[str, object]],
    emitted: int,
) -> int:
    for event in events:
        emitted = _emit_annotation(
            "warning",
            "Google News backlog expired",
            "profile={} expired={} pending={}".format(
                event["profile_id"],
                event["expired"],
                event["pending"],
            ),
            emitted,
        )
    return emitted


def _notify_backlog_expiry(
    events: Sequence[Mapping[str, object]],
    env: Mapping[str, str],
    notifier: Callable[[str, str], bool],
) -> None:
    if not events:
        return
    webhook = env.get("DISCORD_WEBHOOK_ADMIN", "")
    if not isinstance(webhook, str) or not webhook.strip():
        return
    lines = ["Google News backlog expired"]
    lines.extend(
        "profile={} expired={} remaining={}".format(
            event["profile_id"], event["expired"], event["remaining"]
        )
        for event in events
    )
    run_url = current_actions_url()
    if run_url:
        lines.append("run: {}".format(run_url))
    try:
        notifier(webhook.strip(), "\n".join(lines))
    except Exception as error:
        LOGGER.warning(
            "Google News backlog alert skipped (오류 유형: %s)",
            type(error).__name__,
        )


def _prune_state_databases(
    state_path: Path,
    database_map: Mapping[str, str],
    retention_days: int,
    url_cache_retention_days: int,
) -> Dict[str, int]:
    paths = [str(state_path / name) for name in database_map.values()]
    paths.append(str(state_path / "resolver.db"))
    try:
        return apply_state_retention(
            paths,
            retention_days=retention_days,
            url_cache_retention_days=url_cache_retention_days,
        )
    except (OSError, sqlite3.Error, ValueError) as error:
        LOGGER.warning(
            "Google News state retention skipped (오류 유형: %s)",
            type(error).__name__,
        )
        return {
            "items": 0,
            "messages": 0,
            "identities": 0,
            "url_cache": 0,
            "databases": 0,
        }


def _emit_profile_annotations(
    results: Sequence[ProfileRunResult],
    circuit_state: Optional[CircuitState],
) -> int:
    emitted = 0
    failed = [result for result in results if result.status == "failed"]
    if len(failed) > ANNOTATION_LIMIT - 1:
        emitted = _emit_annotation(
            "error",
            "Google News profiles failed",
            _failure_summary(failed),
            emitted,
        )
    else:
        for result in failed:
            emitted = _emit_annotation(
                "error",
                "Google News profile failed",
                "profile={} code={} pending={}".format(
                    result.profile_id,
                    result.error_code or "unknown_failure",
                    result.pending_count,
                ),
                emitted,
            )
    skipped_by_code: Dict[str, List[str]] = {}
    for result in results:
        if result.status != "skipped":
            continue
        skipped_by_code.setdefault(
            result.error_code or "unknown", []
        ).append(result.profile_id)
    for code, profile_ids in sorted(skipped_by_code.items()):
        body = "profiles={} code={}".format(",".join(profile_ids), code)
        if code == "circuit_open" and circuit_state is not None:
            body += " until={}".format(circuit_state.blocked_until.isoformat())
        emitted = _emit_annotation(
            "warning",
            "Google News delivery deferred",
            body,
            emitted,
        )
    return emitted


def _failure_summary(failed: Sequence[ProfileRunResult]) -> str:
    parts = ["count={}".format(len(failed))]
    parts.extend(
        "{}={}".format(result.profile_id, result.error_code or "unknown_failure")
        for result in failed
    )
    body = " ".join(parts)
    return body[:900] + ("..." if len(body) > 900 else "")


def _emit_annotation(level: str, title: str, body: str, emitted: int) -> int:
    if emitted >= ANNOTATION_LIMIT:
        return emitted
    print("::{} title={}::{}".format(level, title, body))
    return emitted + 1


STALL_STREAK_FILE = "delivery-stall.json"
STALL_ALERT_EVERY = 4


def _profile_totals(results: Sequence[ProfileRunResult]) -> Dict[str, int]:
    return {
        "processed": sum(result.processed_count for result in results),
        "pending": sum(result.pending_count for result in results),
        "filtered": sum(getattr(result, "filtered_count", 0) for result in results),
        "duplicates": sum(getattr(result, "duplicate_count", 0) for result in results),
        "truncated": sum(getattr(result, "truncated_count", 0) for result in results),
    }


def _run_duration_ms(summary: DispatchSummary) -> Optional[int]:
    try:
        started = datetime.fromisoformat(summary.started_at)
        finished = datetime.fromisoformat(summary.finished_at)
    except (TypeError, ValueError):
        return None
    return max(0, int((finished - started).total_seconds() * 1000))


def _update_stall_streak(state_path: Path, stalled: bool) -> int:
    path = state_path / STALL_STREAK_FILE
    streak = 0
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        payload = {}
    value = payload.get("streak") if isinstance(payload, dict) else None
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        streak = value
    streak = streak + 1 if stalled else 0
    try:
        temporary_path = path.with_suffix(".tmp")
        with open(temporary_path, "w", encoding="utf-8") as handle:
            json.dump({"streak": streak, "updated_at": _utc_timestamp()}, handle)
            handle.write("\n")
        os.replace(temporary_path, path)
    except OSError:
        pass
    return streak


def _report_run_totals(
    summary: DispatchSummary,
    results: Sequence[ProfileRunResult],
    env: Mapping[str, str],
    state_path: Path,
    manual_test: bool,
    validate_only: bool,
    notifier: Callable[[str, str], bool],
) -> None:
    totals = _profile_totals(results)
    emit_event(
        "run_summary",
        status=summary.status,
        profiles=len(results),
        processed=totals["processed"],
        pending=totals["pending"],
        filtered=totals["filtered"],
        duplicates=totals["duplicates"],
        truncated=totals["truncated"],
        duration_ms=_run_duration_ms(summary),
    )
    stalled = (
        summary.status == "success"
        and not manual_test
        and not validate_only
        and totals["processed"] == 0
        and totals["pending"] > 0
    )
    streak = _update_stall_streak(state_path, stalled)
    if not stalled:
        return
    emit_event("delivery_stalled", pending=totals["pending"], streak=streak)
    print(
        "::warning title=Google News delivery stalled::0 delivered while {} "
        "deliveries are pending".format(totals["pending"])
    )
    if streak != 1 and streak % STALL_ALERT_EVERY != 0:
        return
    webhook = env.get("DISCORD_WEBHOOK_ADMIN", "")
    if not isinstance(webhook, str) or not webhook.strip():
        return
    lines = [
        "Google News delivery stalled",
        "delivered=0 pending={} streak={}".format(totals["pending"], streak),
    ]
    run_url = current_actions_url()
    if run_url:
        lines.append("run: {}".format(run_url))
    try:
        notifier(webhook.strip(), "\n".join(lines))
    except Exception as error:
        LOGGER.warning(
            "Google News stall alert skipped (오류 유형: %s)",
            type(error).__name__,
        )


def _record_dispatch_failure(arguments, error_code: str) -> None:
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
        run_id=os.environ.get("GITHUB_RUN_ID"),
    )
    _write_summary(state_path / "run-summary.json", failed_summary)
    emit_event("run_failed", code=error_code)
    LOGGER.error("Google News 디스패처 실패 (코드: %s)", error_code)
    print(
        "::error title=Google News dispatcher failed::code={}".format(error_code)
    )


def _unexpected_error_code(error: Exception) -> str:
    name = re.sub(r"(?<!^)(?=[A-Z])", "_", type(error).__name__).lower()
    name = re.sub(r"[^a-z0-9_]+", "_", name).strip("_") or "error"
    return ("unexpected_" + name)[:64]


def select_profiles(
    profiles: Sequence[GoogleNewsProfile], profile_id: Optional[str]
) -> Sequence[GoogleNewsProfile]:
    if profile_id is None:
        return profiles
    for profile in profiles:
        if profile.profile_id == profile_id:
            return [profile]
    raise ValueError("unknown_profile_id")


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
    metrics = {
        key: payload.get(key)
        for key in (
            "filtered_count",
            "duplicate_count",
            "queued_count",
            "deferred_count",
            "truncated_count",
        )
    }
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
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in metrics.values()
        )
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
        filtered_count=metrics["filtered_count"],
        duplicate_count=metrics["duplicate_count"],
        queued_count=metrics["queued_count"],
        deferred_count=metrics["deferred_count"],
        truncated_count=metrics["truncated_count"],
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
    parser.add_argument("--profile-id")
    parser.add_argument("--validate-only", action="store_true")
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    truncate_events_file(os.environ.get("RUN_EVENTS_PATH", ""))
    try:
        retention_days = state_retention_days(
            os.environ.get(
                "GOOGLE_NEWS_STATE_RETENTION_DAYS",
                str(DEFAULT_RETENTION_DAYS),
            )
        )
        budget_seconds = run_budget_seconds(
            os.environ.get(
                "GOOGLE_NEWS_RUN_BUDGET_SECONDS",
                str(DEFAULT_RUN_BUDGET_SECONDS),
            )
        )
        backlog_limit = parse_backlog_limit(
            os.environ.get(
                "GOOGLE_NEWS_BACKLOG_LIMIT", str(DEFAULT_BACKLOG_LIMIT)
            )
        )
        backlog_age_days = parse_backlog_age_days(
            os.environ.get(
                "GOOGLE_NEWS_BACKLOG_AGE_DAYS",
                str(DEFAULT_BACKLOG_AGE_DAYS),
            )
        )
        url_cache_days = parse_url_cache_retention_days(
            os.environ.get(
                "GOOGLE_NEWS_URL_CACHE_RETENTION_DAYS",
                str(DEFAULT_URL_CACHE_RETENTION_DAYS),
            )
        )
        all_profiles = load_profiles(arguments.profiles)
        profiles = select_profiles(all_profiles, arguments.profile_id)
        emit_event(
            "run_start",
            profiles=len(profiles),
            manual=arguments.manual_test,
            validate=arguments.validate_only,
        )
        summary = run_dispatch(
            profiles,
            os.environ,
            arguments.state_dir,
            arguments.manual_test,
            validate_only=arguments.validate_only,
            retention_days=retention_days,
            run_deadline=time.time() + budget_seconds,
            backlog_limit=backlog_limit,
            backlog_age_days=backlog_age_days,
            url_cache_retention_days=url_cache_days,
            profile_databases={
                profile.profile_id: profile.state_db
                for profile in all_profiles
            },
        )
    except (OSError, ValueError, RuntimeError) as error:
        error_code = str(error)
        if not ERROR_CODE.fullmatch(error_code):
            error_code = "dispatch_failed"
        _record_dispatch_failure(arguments, error_code)
        return 1
    except Exception as error:
        _record_dispatch_failure(arguments, _unexpected_error_code(error))
        return 1
    LOGGER.info(
        "Google News 디스패처 완료: status=%s profiles=%s",
        summary.status,
        len(summary.profiles),
    )
    return 1 if summary.status == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
