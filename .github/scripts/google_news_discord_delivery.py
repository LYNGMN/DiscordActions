"""Bounded Discord webhook delivery shared by Google News handlers."""

import math
import time
from typing import Callable, Dict, Optional

import requests


MAX_RATE_LIMIT_WAIT_SECONDS = 60.0
MAX_DISCORD_CONTENT_CHARACTERS = 2000
GOOGLE_NEWS_USERNAME = "Google News"
GOOGLE_NEWS_AVATAR_URL = (
    "https://discordactions.github.io/logo/media/original/news/googlenews.png"
)
TRUNCATION_MARKER = "\n…"
DATE_MARKER = "\n📅 "


def _discord_character_count(content: str) -> int:
    return sum(2 if ord(character) > 0xFFFF else 1 for character in content)


def _truncate_to_character_limit(content: str, limit: int) -> str:
    used = 0
    end = 0
    for character in content:
        width = 2 if ord(character) > 0xFFFF else 1
        if used + width > limit:
            break
        used += width
        end += 1
    return content[:end]


def _limit_content(content: str) -> str:
    if _discord_character_count(content) <= MAX_DISCORD_CONTENT_CHARACTERS:
        return content

    date_start = content.rfind(DATE_MARKER)
    if date_start > 0:
        suffix = content[date_start:]
        prefix_budget = (
            MAX_DISCORD_CONTENT_CHARACTERS
            - _discord_character_count(TRUNCATION_MARKER)
            - _discord_character_count(suffix)
        )
        if prefix_budget > 0:
            prefix = _truncate_to_character_limit(
                content[:date_start], prefix_budget
            ).rstrip()
            line_break = prefix.rfind("\n")
            if line_break >= len(prefix) // 2:
                prefix = prefix[:line_break].rstrip()
            return prefix + TRUNCATION_MARKER + suffix

    marker_budget = MAX_DISCORD_CONTENT_CHARACTERS - _discord_character_count("…")
    return _truncate_to_character_limit(content, marker_budget).rstrip() + "…"


def send_webhook_message(
    webhook_url: str,
    payload: Dict[str, str],
    sleep: Callable[[float], None] = time.sleep,
    max_rate_limit_wait_seconds: float = MAX_RATE_LIMIT_WAIT_SECONDS,
) -> str:
    """Post once, or retry one HTTP 429 after Discord's bounded delay."""
    safe_payload = dict(payload)
    safe_payload["username"] = GOOGLE_NEWS_USERNAME
    safe_payload["avatar_url"] = GOOGLE_NEWS_AVATAR_URL
    content = safe_payload.get("content")
    if isinstance(content, str):
        safe_payload["content"] = _limit_content(content)

    for attempt in range(2):
        response = requests.post(
            webhook_url,
            json=safe_payload,
            headers={"Content-Type": "application/json"},
            params={"wait": "true"},
            timeout=(5.0, 15.0),
        )
        if response.status_code == 429 and attempt == 0:
            retry_after = _retry_after_seconds(response)
            if (
                retry_after is None
                or retry_after > max_rate_limit_wait_seconds
            ):
                response.raise_for_status()
            sleep(retry_after)
            continue

        response.raise_for_status()
        body = response.json()
        message_id = body.get("id") if isinstance(body, dict) else None
        if not isinstance(message_id, str) or not message_id.isdigit():
            raise ValueError("invalid message id")
        return message_id

    raise requests.RequestException("discord_delivery_failed")


def _retry_after_seconds(response) -> Optional[float]:
    values = []
    header_value = response.headers.get("Retry-After")
    if header_value is not None:
        values.append(header_value)
    try:
        body = response.json()
    except (TypeError, ValueError):
        body = None
    if isinstance(body, dict) and "retry_after" in body:
        values.append(body["retry_after"])

    parsed_values = []
    for value in values:
        if isinstance(value, bool):
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(parsed) and parsed >= 0:
            parsed_values.append(parsed)
    return max(parsed_values) if parsed_values else None
