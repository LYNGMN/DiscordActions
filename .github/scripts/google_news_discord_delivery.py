"""Bounded Discord webhook delivery shared by Google News handlers."""

import math
import time
from typing import Callable, Dict, Optional

import requests


MAX_RATE_LIMIT_WAIT_SECONDS = 60.0


def send_webhook_message(
    webhook_url: str,
    payload: Dict[str, str],
    sleep: Callable[[float], None] = time.sleep,
    max_rate_limit_wait_seconds: float = MAX_RATE_LIMIT_WAIT_SECONDS,
) -> str:
    """Post once, or retry one HTTP 429 after Discord's bounded delay."""
    for attempt in range(2):
        response = requests.post(
            webhook_url,
            json=payload,
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
