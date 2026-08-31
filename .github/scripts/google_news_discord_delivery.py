"""Bounded Discord webhook delivery shared by Google News handlers."""

import math
import time
from typing import Callable, Dict, List, Optional

import requests


MAX_RATE_LIMIT_WAIT_SECONDS = 60.0
MAX_DISCORD_CONTENT_CHARACTERS = 2000
GOOGLE_NEWS_USERNAME = "Google News"
GOOGLE_NEWS_AVATAR_URL = (
    "https://discordactions.github.io/logo/media/original/news/googlenews.png"
)
TRUNCATION_MARKER = "\n…"
DATE_MARKER = "\n📅 "


class DiscordMessageId(str):
    def __new__(
        cls,
        value: str,
        ambiguous_retry: bool = False,
        attempt_count: int = 1,
    ):
        instance = str.__new__(cls, value)
        instance.ambiguous_retry = bool(ambiguous_retry)
        instance.attempt_count = int(attempt_count)
        return instance


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


def split_discord_content(
    content: str,
    limit: int = MAX_DISCORD_CONTENT_CHARACTERS,
) -> List[str]:
    """Split content without dropping lines, using Discord's UTF-16 limit."""
    if not isinstance(content, str) or not content:
        raise ValueError("content must be a non-empty string")
    if limit <= 0:
        raise ValueError("limit must be positive")
    if _discord_character_count(content) <= limit:
        return [content]

    chunks = []
    current = ""
    for line in content.split("\n"):
        candidate = line if not current else current + "\n" + line
        if _discord_character_count(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        remaining = line
        while _discord_character_count(remaining) > limit:
            piece = _truncate_to_character_limit(remaining, limit)
            if not piece:
                raise ValueError("unable to split Discord content")
            chunks.append(piece)
            remaining = remaining[len(piece):]
        current = remaining
    if current or not chunks:
        chunks.append(current)
    return chunks


def send_webhook_message(
    webhook_url: str,
    payload: Dict[str, str],
    sleep: Callable[[float], None] = time.sleep,
    max_rate_limit_wait_seconds: float = MAX_RATE_LIMIT_WAIT_SECONDS,
) -> str:
    """Post with one bounded retry and preserve response-unknown evidence."""
    safe_payload = dict(payload)
    safe_payload["username"] = GOOGLE_NEWS_USERNAME
    safe_payload["avatar_url"] = GOOGLE_NEWS_AVATAR_URL
    content = safe_payload.get("content")
    if isinstance(content, str):
        safe_payload["content"] = _limit_content(content)

    ambiguous_retry = False
    for attempt in range(2):
        try:
            response = requests.post(
                webhook_url,
                json=safe_payload,
                headers={"Content-Type": "application/json"},
                params={"wait": "true"},
                timeout=(5.0, 15.0),
            )
        except requests.RequestException as error:
            if attempt == 0:
                ambiguous_retry = True
                sleep(2.0)
                continue
            _annotate_delivery_error(error, ambiguous_retry, attempt + 1)
            raise
        if response.status_code == 429 and attempt == 0:
            retry_after = _retry_after_seconds(response)
            if (
                retry_after is None
                or retry_after > max_rate_limit_wait_seconds
            ):
                response.raise_for_status()
            sleep(retry_after)
            continue
        if response.status_code >= 500 and attempt == 0:
            sleep(2.0)
            continue

        try:
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, TypeError, ValueError) as error:
            _annotate_delivery_error(error, ambiguous_retry, attempt + 1)
            raise
        message_id = body.get("id") if isinstance(body, dict) else None
        if not isinstance(message_id, str) or not message_id.isdigit():
            error = ValueError("invalid message id")
            _annotate_delivery_error(error, ambiguous_retry, attempt + 1)
            raise error
        return DiscordMessageId(message_id, ambiguous_retry, attempt + 1)

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


def _annotate_delivery_error(
    error: Exception,
    ambiguous_retry: bool,
    attempt_count: int,
) -> None:
    error.error_code = "ambiguous_retry" if ambiguous_retry else "final_failure"
    error.attempt_count = int(attempt_count)
