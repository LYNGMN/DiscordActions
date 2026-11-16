"""Store the approved Google News logo as each webhook's default avatar.

Discord applies ``avatar_url`` on a best-effort basis: when it cannot fetch or
resolve the image it keeps the webhook's default avatar and returns no error.
This maintenance command uploads the approved logo to each configured webhook,
so the fallback shows the same image instead of the generic Discord icon.

It changes Discord state, so it stays a dry run unless ``--confirm SET`` is
given. Webhook URLs are never printed.
"""

import argparse
import json
import os
import re
import sys
import time
from typing import Callable, Dict, List, Mapping, Optional, Sequence
from urllib.parse import urlsplit

import requests

from google_news_discord_delivery import GOOGLE_NEWS_AVATAR_URL
from google_news_profiles import GoogleNewsProfile, load_profiles


CONFIRMATION = "SET"
MAX_AVATAR_BYTES = 8 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
WEBHOOK_PATH = re.compile(r"^/api/webhooks/[0-9]+/[A-Za-z0-9._-]+$")
DEFAULT_PROFILES_PATH = (
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    + "/config/google_news_profiles.json"
)
TIMEOUT = (5.0, 20.0)
MAX_RATE_LIMIT_WAIT_SECONDS = 5.0


class AvatarImageError(ValueError):
    """The approved logo could not be used as a Discord avatar."""


class AvatarNotApplied(RuntimeError):
    """Discord accepted the update but still reports no avatar."""


def fetch_avatar_image(url: str, get: Callable = None) -> bytes:
    """Download and validate the approved avatar image."""
    response = (get or requests.get)(url, timeout=TIMEOUT)
    response.raise_for_status()
    content_type = str(response.headers.get("Content-Type", "")).lower()
    if not content_type.startswith("image/"):
        raise AvatarImageError("avatar_url_not_an_image")
    image = response.content
    if not image or len(image) > MAX_AVATAR_BYTES:
        raise AvatarImageError("avatar_image_size_invalid")
    if not image.startswith(PNG_SIGNATURE):
        raise AvatarImageError("avatar_image_not_png")
    return image


def _valid_webhook_url(value: str) -> bool:
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname in {"discord.com", "discordapp.com"}
        and parsed.netloc == parsed.hostname
        and not parsed.query
        and not parsed.fragment
        and bool(WEBHOOK_PATH.fullmatch(parsed.path))
    )


def _retry_after_seconds(response) -> Optional[float]:
    raw = response.headers.get("Retry-After")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return value


def _patch_avatar(
    webhook_url: str,
    image: bytes,
    patch: Callable,
    sleep: Callable[[float], None],
) -> None:
    fields = {
        "data": {"payload_json": json.dumps({})},
        "files": {"avatar": ("avatar.png", image, "image/png")},
        "timeout": TIMEOUT,
    }
    response = patch(webhook_url, **fields)
    retry_after = _retry_after_seconds(response) if response.status_code == 429 else None
    if (
        response.status_code == 429
        and retry_after is not None
        and retry_after <= MAX_RATE_LIMIT_WAIT_SECONDS
    ):
        sleep(retry_after)
        response = patch(webhook_url, **fields)
    response.raise_for_status()


def _verify_avatar(webhook_url: str, get: Callable) -> None:
    response = get(webhook_url, timeout=TIMEOUT)
    response.raise_for_status()
    try:
        metadata = response.json()
    except (TypeError, ValueError):
        raise AvatarNotApplied("webhook_metadata_invalid") from None
    if not isinstance(metadata, dict) or not metadata.get("avatar"):
        raise AvatarNotApplied("avatar_not_applied")


def set_webhook_avatar(
    webhook_url: str,
    image: bytes,
    patch: Callable = None,
    get: Callable = None,
    sleep: Callable[[float], None] = None,
) -> None:
    """Replace one webhook's default avatar and verify Discord stored it."""
    _patch_avatar(
        webhook_url,
        image,
        patch or requests.patch,
        sleep or time.sleep,
    )
    _verify_avatar(webhook_url, get or requests.get)


def select_profiles(
    profiles: Sequence[GoogleNewsProfile], selection: str
) -> List[GoogleNewsProfile]:
    """Return the requested profiles, keeping the registry order."""
    wanted = (selection or "all").strip()
    if wanted == "all":
        return list(profiles)
    requested = [value.strip() for value in wanted.split(",") if value.strip()]
    known = {profile.profile_id: profile for profile in profiles}
    unknown = [value for value in requested if value not in known]
    if unknown:
        raise ValueError("unknown profile: {}".format(",".join(unknown)))
    if not requested:
        raise ValueError("no profile selected")
    return [profile for profile in profiles if profile.profile_id in set(requested)]


def apply_avatars(
    profiles: Sequence[GoogleNewsProfile],
    env: Mapping[str, str],
    image: bytes,
    dry_run: bool = False,
    patch: Callable = None,
    get: Callable = None,
    sleep: Callable[[float], None] = None,
) -> List[Dict[str, str]]:
    """Set the avatar for every profile and return safe per-profile results."""
    results = []
    for profile in profiles:
        webhook_url = str(env.get(profile.webhook_env, "")).strip()
        if not webhook_url:
            results.append({"profile_id": profile.profile_id, "status": "missing_webhook"})
            continue
        if not _valid_webhook_url(webhook_url):
            results.append({"profile_id": profile.profile_id, "status": "invalid_webhook"})
            continue
        if dry_run:
            results.append({"profile_id": profile.profile_id, "status": "would_set"})
            continue
        try:
            set_webhook_avatar(webhook_url, image, patch=patch, get=get, sleep=sleep)
        except requests.RequestException as error:
            status_code = getattr(getattr(error, "response", None), "status_code", None)
            error_code = "request_error"
            if isinstance(status_code, int):
                error_code = "http_{}".format(status_code)
            results.append(
                {"profile_id": profile.profile_id, "status": "failed", "error": error_code}
            )
            continue
        except AvatarNotApplied as error:
            results.append(
                {"profile_id": profile.profile_id, "status": "failed", "error": str(error)}
            )
            continue
        results.append({"profile_id": profile.profile_id, "status": "set"})
    return results


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Set the approved logo as each Google News webhook avatar."
    )
    parser.add_argument(
        "--profiles-file",
        default=DEFAULT_PROFILES_PATH,
        help="profile registry JSON path",
    )
    parser.add_argument(
        "--profile",
        default="all",
        help="all, one profile id, or comma-separated profile ids",
    )
    parser.add_argument(
        "--confirm",
        default="",
        help="type SET to change Discord; anything else is a dry run",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report the target profiles without changing Discord",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        profiles = select_profiles(load_profiles(args.profiles_file), args.profile)
    except (OSError, ValueError) as error:
        print("::error title=Webhook avatar setup failed::{}".format(error))
        return 2

    dry_run = args.dry_run or args.confirm != CONFIRMATION
    try:
        image = fetch_avatar_image(GOOGLE_NEWS_AVATAR_URL)
    except AvatarImageError as error:
        print("::error title=Webhook avatar image unavailable::{}".format(error))
        return 1
    except requests.RequestException:
        print("::error title=Webhook avatar image unavailable::avatar_url_unreachable")
        return 1

    results = apply_avatars(profiles, os.environ, image, dry_run=dry_run)
    for result in results:
        if "error" in result:
            print("profile={} status={} error={}".format(
                result["profile_id"], result["status"], result["error"]
            ))
        else:
            print("profile={} status={}".format(result["profile_id"], result["status"]))

    failed = sum(1 for result in results if result["status"] == "failed")
    print(
        "summary mode={} total={} changed={} failed={}".format(
            "dry_run" if dry_run else "apply",
            len(results),
            sum(1 for result in results if result["status"] == "set"),
            failed,
        )
    )
    if dry_run:
        print("::notice title=Dry run::Pass confirm=SET to change the Discord webhooks.")
    if failed:
        print("::error title=Webhook avatar setup failed::{} webhook(s) failed".format(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
