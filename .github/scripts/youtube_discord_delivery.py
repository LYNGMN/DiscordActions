"""Final branding and transport boundary for YouTube Discord webhooks."""

import copy
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests


YOUTUBE_USERNAME = "YouTube"
YOUTUBE_AVATAR_URL = (
    "https://discordactions.github.io/logo/media/original/youtube/"
    "youtube_social_circle_red.png"
)
DISCORD_TIMEOUT = (5.0, 15.0)


@dataclass(frozen=True)
class YouTubeWebhookResult:
    message_id: str
    ambiguous_retry: bool = False
    attempt_count: int = 1


def branded_youtube_payload(payload: dict) -> dict:
    safe_payload = copy.deepcopy(payload)
    safe_payload["username"] = YOUTUBE_USERNAME
    safe_payload["avatar_url"] = YOUTUBE_AVATAR_URL
    for embed in safe_payload.get("embeds", []):
        footer = dict(embed.get("footer") or {})
        footer["icon_url"] = YOUTUBE_AVATAR_URL
        embed["footer"] = footer
    return safe_payload


def send_youtube_webhook(
    webhook_url: str,
    payload: dict,
    post=requests.post,
    sleep: Callable[[float], None] = time.sleep,
) -> YouTubeWebhookResult:
    delivery_url = _wait_url(webhook_url)
    branded_payload = branded_youtube_payload(payload)
    ambiguous_retry = False
    for attempt in range(2):
        try:
            response = post(
                delivery_url,
                json=branded_payload,
                headers={"Content-Type": "application/json"},
                timeout=DISCORD_TIMEOUT,
            )
        except requests.RequestException as error:
            if attempt == 0:
                ambiguous_retry = True
                sleep(2.0)
                continue
            _annotate_delivery_error(error, ambiguous_retry, attempt + 1)
            raise

        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code == 429 and attempt == 0:
            sleep(_retry_after_seconds(getattr(response, "headers", {})))
            continue
        if status_code >= 500 and attempt == 0:
            sleep(2.0)
            continue

        try:
            response.raise_for_status()
            response_data = response.json()
        except (requests.RequestException, TypeError, ValueError) as error:
            _annotate_delivery_error(error, ambiguous_retry, attempt + 1)
            raise
        message_id = response_data.get("id") if isinstance(response_data, dict) else None
        if not isinstance(message_id, str) or not message_id.isdigit():
            error = ValueError("invalid Discord message id")
            _annotate_delivery_error(error, ambiguous_retry, attempt + 1)
            raise error
        return YouTubeWebhookResult(message_id, ambiguous_retry, attempt + 1)
    raise RuntimeError("YouTube webhook retry exhausted")


def _wait_url(webhook_url: str) -> str:
    parsed = urlsplit(webhook_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["wait"] = "true"
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def _retry_after_seconds(headers) -> float:
    try:
        delay = float(headers.get("Retry-After", "1"))
    except (AttributeError, TypeError, ValueError):
        delay = 1.0
    return max(0.0, min(delay, 60.0))


def _annotate_delivery_error(
    error: Exception,
    ambiguous_retry: bool,
    attempt_count: int,
) -> None:
    error.error_code = "ambiguous_retry" if ambiguous_retry else "final_failure"
    error.attempt_count = int(attempt_count)
