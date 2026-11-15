"""One-time Google News backlog expiry and channel divider."""

import argparse
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from google_news_delivery_state import (
    count_unfinished_deliveries,
    expire_pending_deliveries,
    read_state_metadata,
    write_state_metadata,
)
from google_news_discord_delivery import send_webhook_message
from google_news_profiles import GoogleNewsProfile, load_profiles


DIVIDER_CONTENT = "---"
DIVIDER_SENT_KEY = "divider_sent_at"
RESET_AT_KEY = "backlog_reset_at"
SUMMARY_NAME = "backlog-reset.json"
DEFAULT_PROFILES_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "google_news_profiles.json"
)


def reset_state(
    state_dir: str,
    profiles: Sequence[GoogleNewsProfile],
    env: Mapping[str, str],
    divider_scope: str = "pending",
    send_divider: bool = True,
    confirm: bool = False,
    dry_run: bool = False,
    webhook_sender: Optional[Callable[[str, str], None]] = None,
    now: Optional[datetime] = None,
) -> dict:
    if divider_scope not in {"pending", "all"}:
        raise ValueError("invalid divider scope")
    if not dry_run and not confirm:
        raise ValueError("reset_confirmation_required")

    current = now or datetime.now(timezone.utc)
    sender = webhook_sender or (
        lambda webhook_url, content: send_webhook_message(
            webhook_url, {"content": content}
        )
    )
    state_path = Path(state_dir)
    results = []

    for profile in profiles:
        database_path = state_path / profile.state_db
        result = {
            "profile_id": profile.profile_id,
            "pending_before": 0,
            "expired": 0,
            "divider": "skipped",
            "error": None,
        }
        if not database_path.is_file():
            result["divider"] = "missing_database"
            results.append(result)
            continue

        pending_before = count_unfinished_deliveries(str(database_path))
        result["pending_before"] = pending_before
        had_reset_marker = bool(
            read_state_metadata(str(database_path), RESET_AT_KEY)
        )

        if dry_run:
            result["expired"] = pending_before
        else:
            result["expired"] = expire_pending_deliveries(str(database_path))
            if not had_reset_marker:
                write_state_metadata(
                    str(database_path), RESET_AT_KEY, current.isoformat()
                )

        should_send = send_divider and (
            divider_scope == "all" or pending_before > 0 or had_reset_marker
        )
        if not should_send:
            results.append(result)
            continue
        if dry_run:
            result["divider"] = "dry_run"
            results.append(result)
            continue
        if read_state_metadata(str(database_path), DIVIDER_SENT_KEY):
            result["divider"] = "already_sent"
            results.append(result)
            continue

        webhook_url = env.get(profile.webhook_env, "").strip()
        if not webhook_url:
            result["divider"] = "missing_webhook"
            result["error"] = "missing_webhook"
            results.append(result)
            continue
        try:
            sender(webhook_url, DIVIDER_CONTENT)
        except Exception as error:
            result["divider"] = "failed"
            result["error"] = getattr(
                error, "error_code", type(error).__name__
            )
            results.append(result)
            continue
        result["divider"] = "sent"
        write_state_metadata(
            str(database_path), DIVIDER_SENT_KEY, current.isoformat()
        )
        results.append(result)

    summary = {
        "reset_at": current.isoformat(),
        "divider_scope": divider_scope,
        "send_divider": bool(send_divider),
        "dry_run": bool(dry_run),
        "total_pending_before": sum(
            item["pending_before"] for item in results
        ),
        "total_expired": sum(item["expired"] for item in results),
        "profiles": results,
    }
    if not dry_run:
        _write_summary(state_path / SUMMARY_NAME, summary)
    return summary


def _write_summary(path: Path, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=".backlog-reset-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = handle.name
            json.dump(summary, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_path, str(path))
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Expire pending Google News deliveries and send a divider"
    )
    parser.add_argument("--profiles", default=str(DEFAULT_PROFILES_PATH))
    parser.add_argument("--state-dir", default=".google-news-state")
    parser.add_argument(
        "--divider-scope",
        choices=("pending", "all"),
        default="pending",
    )
    parser.add_argument("--send-divider", action="store_true")
    parser.add_argument("--confirm-reset", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args(argv)
    if not arguments.dry_run and not arguments.confirm_reset:
        parser.error("--confirm-reset is required unless --dry-run")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    try:
        profiles = load_profiles(arguments.profiles)
        summary = reset_state(
            arguments.state_dir,
            profiles,
            os.environ,
            divider_scope=arguments.divider_scope,
            send_divider=arguments.send_divider,
            confirm=arguments.confirm_reset,
            dry_run=arguments.dry_run,
        )
    except (OSError, ValueError, RuntimeError) as error:
        code = str(error)
        if not code.startswith("invalid_") and code != "reset_confirmation_required":
            code = "reset_failed"
        logging.error("Google News 백로그 리셋 실패 (코드: %s)", code)
        return 1

    for result in summary["profiles"]:
        logging.info(
            "profile=%s pending_before=%s expired=%s divider=%s",
            result["profile_id"],
            result["pending_before"],
            result["expired"],
            result["divider"],
        )
    if arguments.dry_run:
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0
    failed = [
        result
        for result in summary["profiles"]
        if result["divider"] in {"failed", "missing_webhook"}
    ]
    if failed:
        logging.error("Google News divider 전송 실패: %s명", len(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
