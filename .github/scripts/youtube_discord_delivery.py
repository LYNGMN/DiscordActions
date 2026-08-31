"""Final branding and transport boundary for YouTube Discord webhooks."""

import copy

import requests


YOUTUBE_USERNAME = "YouTube"
YOUTUBE_AVATAR_URL = (
    "https://discordactions.github.io/logo/media/original/youtube/"
    "youtube_social_circle_red.png"
)
DISCORD_TIMEOUT = (5.0, 15.0)


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
) -> None:
    response = post(
        webhook_url,
        json=branded_youtube_payload(payload),
        headers={"Content-Type": "application/json"},
        timeout=DISCORD_TIMEOUT,
    )
    response.raise_for_status()
