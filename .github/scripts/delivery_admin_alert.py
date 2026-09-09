"""Best-effort admin alerts that never expose webhook URLs or item queries."""

import hashlib
import os
import re
from typing import Callable, Optional

import requests
from discord_rate_limit_state import RateLimitStore, retry_after_seconds, rate_limit_scope


SAFE_LABEL = re.compile(r"[^A-Za-z0-9_. -]+")


def current_actions_url() -> Optional[str]:
    server = os.environ.get("GITHUB_SERVER_URL", "").rstrip("/")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if server.startswith("https://") and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) and run_id.isdigit():
        return "{}/{}/actions/runs/{}".format(server, repository, run_id)
    return None


def notify_admin(
    webhook_url: str,
    service: str,
    profile: str,
    item_identifier: str,
    error_code: str,
    actions_url: Optional[str] = None,
    post: Callable = requests.post,
) -> bool:
    if not webhook_url:
        return False
    safe_service = _safe_label(service)
    safe_profile = _safe_label(profile)
    safe_error = _safe_label(error_code)
    item_hash = hashlib.sha256(str(item_identifier).encode("utf-8")).hexdigest()[:12]
    run_url = actions_url or current_actions_url()
    lines = [
        "Discord Actions delivery warning",
        "service: {}".format(safe_service),
        "profile: {}".format(safe_profile),
        "item: {}".format(item_hash),
        "error: {}".format(safe_error),
    ]
    if run_url:
        lines.append("run: {}".format(run_url))
    try:
        state_path = os.environ.get("GOOGLE_NEWS_RESOLVER_DB_PATH") if service == "Google News" else None
        rate_limits = RateLimitStore(state_path) if state_path else None
        if rate_limits:
            rate_limits.check(webhook_url)
        response = post(
            webhook_url,
            json={"content": "\n".join(lines), "username": "Discord Actions"},
            headers={"Content-Type": "application/json"},
            timeout=(5.0, 15.0),
        )
        if rate_limits and response.status_code == 429:
            delay = retry_after_seconds(response)
            if delay is not None:
                rate_limits.save(webhook_url, delay, rate_limit_scope(response), 1)
        response.raise_for_status()
        return True
    except Exception:
        return False


def _safe_label(value: str) -> str:
    return SAFE_LABEL.sub("_", str(value))[:64] or "unknown"
