"""IANA zones and calendar-boundary compatibility for feed filters."""

import json
from datetime import timezone
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from zoneinfo import ZoneInfo

# Preserve the first country zone previously selected by pytz 2026.3.post1.
# This is a country preference map, not a copy of timezone transition rules.
COUNTRY_TIMEZONES = json.loads(
    (Path(__file__).resolve().parents[1] / "config" / "feed_country_timezones.json")
    .read_text(encoding="utf-8")
)
_ZONE_NAMES = {
    name.casefold(): name
    for name in files("tzdata").joinpath("zones").read_text(encoding="utf-8").splitlines()
}


@lru_cache(maxsize=256)
def get_timezone(name):
    # Use the pinned IANA data on every OS, including systems without tzdb.
    if not isinstance(name, str) or not name or any(
        part in ("", ".", "..") for part in name.split("/")
    ) or "\\" in name:
        raise ValueError("invalid feed timezone")
    name = _ZONE_NAMES.get(name.casefold(), name)
    try:
        with files("tzdata.zoneinfo").joinpath(*name.split("/")).open("rb") as source:
            return ZoneInfo.from_file(source, key=name)
    except (OSError, ValueError, TypeError):
        raise ValueError("invalid feed timezone") from None


def localize_boundary(value, zone):
    """Match the old is_dst=False rule for naive calendar boundaries.

    Gaps use the pre-transition offset. Overlaps prefer a non-DST offset;
    if both sides have the same DST status, use the later UTC instant.
    """
    if value.tzinfo is not None:
        raise ValueError("calendar boundary must be naive")
    candidates = [value.replace(tzinfo=zone, fold=fold) for fold in (0, 1)]
    valid = [candidate for candidate in candidates
             if candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == value]
    if not valid:
        return candidates[0]
    standard = [candidate for candidate in valid if not candidate.dst()]
    return max(standard or valid, key=lambda candidate: candidate.astimezone(timezone.utc))
