"""Bounded Discord webhook delivery shared by Google News handlers."""

import math
import os
import re
import sqlite3
import time
from typing import Callable, Dict, List, Optional
from urllib.parse import urlsplit

import requests


MAX_RATE_LIMIT_WAIT_SECONDS = 300.0
MAX_RATE_LIMIT_RETRIES = 4
DEFAULT_RATE_LIMIT_WAIT_SECONDS = 1.0
MAX_DISCORD_CONTENT_CHARACTERS = 2000
DISCORD_HARMFUL_LINK_CODE = 240000
GOOGLE_NEWS_USERNAME = "Google News"
GOOGLE_NEWS_AVATAR_URL = (
    "https://discordactions.github.io/logo/media/original/news/googlenews.png"
)
TRUNCATION_MARKER = "\n…"
DATE_MARKER = "\n📅 "
URL_TOKEN = re.compile(r"https?://[^\s<>]+")


class DiscordMessageId(str):
    def __new__(
        cls,
        value: str,
        ambiguous_retry: bool = False,
        attempt_count: int = 1,
        google_news_fallback: bool = False,
    ):
        instance = str.__new__(cls, value)
        instance.ambiguous_retry = bool(ambiguous_retry)
        instance.attempt_count = int(attempt_count)
        instance.google_news_fallback = bool(google_news_fallback)
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
    resolver_db_path: Optional[str] = None,
) -> str:
    """Post with bounded retries and preserve response-unknown evidence."""
    safe_payload = dict(payload)
    safe_payload["username"] = GOOGLE_NEWS_USERNAME
    safe_payload["avatar_url"] = GOOGLE_NEWS_AVATAR_URL
    content = safe_payload.get("content")
    if isinstance(content, str):
        safe_payload["content"] = _limit_content(content)

    ambiguous_retry = False
    transient_retry_used = False
    rate_limit_retries = 0
    attempt_count = 0
    google_news_fallback = False
    while True:
        attempt_count += 1
        try:
            response = requests.post(
                webhook_url,
                json=safe_payload,
                headers={"Content-Type": "application/json"},
                params={"wait": "true"},
                timeout=(5.0, 15.0),
            )
        except requests.RequestException as error:
            if not transient_retry_used:
                ambiguous_retry = True
                transient_retry_used = True
                sleep(2.0)
                continue
            _annotate_delivery_error(error, ambiguous_retry, attempt_count)
            raise

        if response.status_code == 429:
            retry_after = _retry_after_seconds(response)
            if retry_after is None:
                retry_after = DEFAULT_RATE_LIMIT_WAIT_SECONDS
            if (
                rate_limit_retries < MAX_RATE_LIMIT_RETRIES
                and retry_after <= max_rate_limit_wait_seconds
            ):
                rate_limit_retries += 1
                sleep(retry_after)
                continue
            try:
                response.raise_for_status()
            except requests.RequestException as error:
                error_code = (
                    "discord_rate_limit_wait_exceeded"
                    if retry_after > max_rate_limit_wait_seconds
                    else "discord_rate_limited"
                )
                _annotate_delivery_error(
                    error,
                    ambiguous_retry,
                    attempt_count,
                    error_code=error_code,
                )
                raise

        if response.status_code >= 500 and not transient_retry_used:
            transient_retry_used = True
            sleep(2.0)
            continue

        discord_api_code = _discord_api_code(response)
        if (
            response.status_code == 400
            and discord_api_code == DISCORD_HARMFUL_LINK_CODE
            and not google_news_fallback
        ):
            fallback_payload = _payload_with_google_news_fallback(
                safe_payload, resolver_db_path
            )
            if fallback_payload is not None:
                safe_payload = fallback_payload
                google_news_fallback = True
                continue

        try:
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, TypeError, ValueError) as error:
            status_code = getattr(response, "status_code", None)
            error_code = None
            if isinstance(status_code, int) and 400 <= status_code <= 599:
                error_code = "discord_http_{}".format(status_code)
                if discord_api_code is not None:
                    error_code += "_api_{}".format(discord_api_code)
            _annotate_delivery_error(
                error,
                ambiguous_retry,
                attempt_count,
                error_code=error_code,
                http_status_code=status_code,
                discord_api_code=discord_api_code,
            )
            raise
        message_id = body.get("id") if isinstance(body, dict) else None
        if not isinstance(message_id, str) or not message_id.isdigit():
            error = ValueError("invalid message id")
            _annotate_delivery_error(error, ambiguous_retry, attempt_count)
            raise error
        bucket_wait = _exhausted_bucket_wait_seconds(response)
        if bucket_wait is not None:
            sleep(min(bucket_wait, max_rate_limit_wait_seconds))
        return DiscordMessageId(
            message_id,
            ambiguous_retry,
            attempt_count,
            google_news_fallback,
        )


def _discord_api_code(response) -> Optional[int]:
    try:
        body = response.json()
    except (TypeError, ValueError):
        return None
    if not isinstance(body, dict):
        return None
    code = body.get("code")
    if isinstance(code, bool) or not isinstance(code, int):
        return None
    return code


def _payload_with_google_news_fallback(
    payload: Dict[str, str],
    resolver_db_path: Optional[str],
) -> Optional[Dict[str, str]]:
    content = payload.get("content")
    if (
        not isinstance(content, str)
        or not content
        or not isinstance(resolver_db_path, str)
        or not os.path.isfile(resolver_db_path)
    ):
        return None

    content_urls = sorted(set(URL_TOKEN.findall(content)))
    if not content_urls:
        return None
    placeholders = ", ".join("?" for _value in content_urls)
    try:
        with sqlite3.connect(resolver_db_path) as connection:
            rows = connection.execute(
                "SELECT resolved_url, google_url FROM google_news_url_cache "
                "WHERE status = 'resolved' AND resolved_url IN ({}) "
                "ORDER BY article_id".format(
                    placeholders
                ),
                content_urls,
            ).fetchall()
    except sqlite3.Error:
        return None

    replacements = {}
    for resolved_url, google_url in rows:
        if not _valid_original_url(resolved_url):
            continue
        if not _valid_google_news_url(google_url):
            continue
        replacements.setdefault(resolved_url, google_url)
    if not replacements:
        return None

    fallback_content = URL_TOKEN.sub(
        lambda match: replacements.get(match.group(0), match.group(0)),
        content,
    )
    if fallback_content == content:
        return None

    fallback_payload = dict(payload)
    fallback_payload["content"] = _limit_content(fallback_content)
    return fallback_payload


def _valid_original_url(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        hostname = (parsed.hostname or "").rstrip(".").lower()
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and bool(hostname)
        and hostname != "news.google.com"
        and not hostname.endswith(".news.google.com")
        and not parsed.username
        and not parsed.password
        and not any(character.isspace() for character in value)
    )


def _valid_google_news_url(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == "news.google.com"
        and parsed.netloc == "news.google.com"
        and not parsed.username
        and not parsed.password
        and not any(character.isspace() for character in value)
    )


def _retry_after_seconds(response) -> Optional[float]:
    values = []
    for header_name in ("Retry-After", "X-RateLimit-Reset-After"):
        header_value = response.headers.get(header_name)
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


def _exhausted_bucket_wait_seconds(response) -> Optional[float]:
    remaining = response.headers.get("X-RateLimit-Remaining")
    try:
        exhausted = float(remaining) <= 0
    except (TypeError, ValueError, OverflowError):
        exhausted = False
    if not exhausted:
        return None
    reset_after = response.headers.get("X-RateLimit-Reset-After")
    try:
        parsed = float(reset_after)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return parsed


def _annotate_delivery_error(
    error: Exception,
    ambiguous_retry: bool,
    attempt_count: int,
    error_code: Optional[str] = None,
    http_status_code: Optional[int] = None,
    discord_api_code: Optional[int] = None,
) -> None:
    error.error_code = (
        "ambiguous_retry" if ambiguous_retry else error_code or "final_failure"
    )
    error.attempt_count = int(attempt_count)
    if isinstance(http_status_code, int):
        error.http_status_code = http_status_code
    if isinstance(discord_api_code, int) and not isinstance(discord_api_code, bool):
        error.discord_api_code = discord_api_code
