"""Shared date and keyword filters for RSS and API feed items."""

import calendar
import hashlib
import json
import re
import shlex
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

import pytz
from dateutil import parser as date_parser

from google_news_keyword_matcher import CompiledKeywordMatch, compile_keyword_match


KEYWORD_SCOPES = {"title", "title_or_description"}
_CALENDAR_FILTER = re.compile(r"^calendar:(\d+)(d|mo)$")
_ROLLING_FILTER = re.compile(r"^rolling:(\d+)(h|d)$")
_FIXED_TOKEN = re.compile(r"^(from|to):(\d{4}-\d{2}-\d{2})$")
_LEGACY_FIXED_TOKEN = re.compile(r"^(since|until):(\d{4}-\d{2}-\d{2})$")
_LEGACY_PAST_TOKEN = re.compile(r"^past:(\d+)(h|d|m|y)$")


@dataclass(frozen=True)
class FeedFilterResult:
    matched: bool
    date_matched: bool
    keyword_matched: bool
    reason: Optional[str]


@dataclass(frozen=True)
class CompiledFeedFilter:
    date_filter: str
    keyword_filter: str
    keyword_scope: str
    timezone_name: str
    display_language: str
    start_at: Optional[datetime]
    end_at: Optional[datetime]
    compiled_keyword: Optional[CompiledKeywordMatch]
    fingerprint: str

    def matches(
        self,
        published_at: str,
        title: str,
        description: str,
    ) -> FeedFilterResult:
        published = _parse_item_datetime(published_at)
        date_matched = (
            (self.start_at is None or published >= self.start_at)
            and (self.end_at is None or published <= self.end_at)
        )
        if not date_matched:
            return FeedFilterResult(False, False, True, "date")

        keyword_matched = True
        if self.compiled_keyword is not None:
            keyword_matched = self.compiled_keyword.matches(title)
            if not keyword_matched and self.keyword_scope == "title_or_description":
                keyword_matched = self.compiled_keyword.matches(description)
        if not keyword_matched:
            return FeedFilterResult(False, True, False, "keyword")
        return FeedFilterResult(True, True, True, None)


def resolve_feed_timezone(
    explicit_timezone: str = "",
    service_timezone: str = "",
    country_code: str = "",
) -> str:
    """Resolve a calendar timezone without inferring a country from language."""

    for candidate in (explicit_timezone, service_timezone):
        value = candidate.strip() if isinstance(candidate, str) else ""
        if value:
            try:
                pytz.timezone(value)
            except pytz.UnknownTimeZoneError:
                raise ValueError("invalid feed timezone") from None
            return value

    country = country_code.strip().upper() if isinstance(country_code, str) else ""
    zones = pytz.country_timezones.get(country, ())
    return zones[0] if zones else "UTC"


def resolve_feed_date_filter(new_value: str = "", legacy_value: str = "") -> str:
    new_filter = new_value.strip() if isinstance(new_value, str) else ""
    if new_filter:
        return new_filter
    legacy_filter = legacy_value.strip() if isinstance(legacy_value, str) else ""
    if not legacy_filter:
        return ""
    tokens = legacy_filter.split()
    past_match = _LEGACY_PAST_TOKEN.fullmatch(legacy_filter)
    if past_match:
        value = int(past_match.group(1))
        unit = past_match.group(2)
        if value <= 0:
            raise ValueError("invalid legacy date filter")
        if unit == "h":
            return "rolling:{}h".format(value)
        multiplier = {"d": 1, "m": 30, "y": 365}[unit]
        return "rolling:{}d".format(value * multiplier)

    converted = []
    seen = set()
    for token in tokens:
        match = _LEGACY_FIXED_TOKEN.fullmatch(token)
        if not match or match.group(1) in seen:
            raise ValueError("invalid legacy date filter")
        try:
            datetime.strptime(match.group(2), "%Y-%m-%d")
        except ValueError:
            raise ValueError("invalid legacy date filter") from None
        seen.add(match.group(1))
        key = "from" if match.group(1) == "since" else "to"
        converted.append("{}:{}".format(key, match.group(2)))
    if not converted:
        raise ValueError("invalid legacy date filter")
    return " ".join(converted)


def resolve_feed_keyword_filter(new_value: str = "", legacy_value: str = "") -> str:
    new_filter = new_value.strip() if isinstance(new_value, str) else ""
    if new_filter:
        return new_filter
    legacy_filter = legacy_value.strip() if isinstance(legacy_value, str) else ""
    if not legacy_filter:
        return ""
    try:
        tokens = shlex.split(legacy_filter)
    except ValueError:
        raise ValueError("invalid legacy keyword filter") from None
    converted = []
    for token in tokens:
        negative = token.startswith("-")
        value = token[1:] if token[:1] in {"+", "-"} else token
        if not value:
            raise ValueError("invalid legacy keyword filter")
        if any(character.isspace() for character in value):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            value = '"{}"'.format(escaped)
        converted.append("NOT {}".format(value) if negative else value)
    if not converted:
        raise ValueError("invalid legacy keyword filter")
    return " AND ".join(converted)


def combine_filter_fingerprints(*values: str) -> str:
    normalized = [value if isinstance(value, str) else "" for value in values]
    payload = json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compile_feed_filter(
    date_filter: str = "",
    keyword_filter: str = "",
    keyword_scope: str = "title",
    timezone_name: str = "UTC",
    display_language: str = "en",
    now: Optional[datetime] = None,
) -> CompiledFeedFilter:
    normalized_date = date_filter.strip() if isinstance(date_filter, str) else ""
    normalized_keyword = (
        keyword_filter.strip() if isinstance(keyword_filter, str) else ""
    )
    normalized_scope = keyword_scope.strip().lower() if isinstance(keyword_scope, str) else ""
    if normalized_scope not in KEYWORD_SCOPES:
        raise ValueError("invalid feed keyword scope")

    try:
        zone = pytz.timezone(timezone_name)
    except (AttributeError, pytz.UnknownTimeZoneError):
        raise ValueError("invalid feed timezone") from None

    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None or reference.utcoffset() is None:
        raise ValueError("feed filter now must be timezone-aware")
    reference = reference.astimezone(zone)
    start_at, end_at = _compile_date_window(normalized_date, zone, reference)
    compiled_keyword = (
        compile_keyword_match(normalized_keyword)
        if normalized_keyword
        else None
    )
    fingerprint = _fingerprint(
        normalized_date,
        normalized_keyword,
        normalized_scope,
        timezone_name,
        display_language,
    )
    return CompiledFeedFilter(
        date_filter=normalized_date,
        keyword_filter=normalized_keyword,
        keyword_scope=normalized_scope,
        timezone_name=timezone_name,
        display_language=display_language,
        start_at=start_at,
        end_at=end_at,
        compiled_keyword=compiled_keyword,
        fingerprint=fingerprint,
    )


def _compile_date_window(
    expression: str,
    zone,
    reference: datetime,
):
    if not expression:
        return None, None

    calendar_match = _CALENDAR_FILTER.fullmatch(expression)
    if calendar_match:
        value = int(calendar_match.group(1))
        unit = calendar_match.group(2)
        if value <= 0:
            raise ValueError("invalid feed date filter")
        if unit == "d":
            start_date = reference.date() - timedelta(days=value - 1)
        else:
            start_date = _subtract_calendar_months(reference.date(), value)
        return _local_midnight(zone, start_date), reference

    rolling_match = _ROLLING_FILTER.fullmatch(expression)
    if rolling_match:
        value = int(rolling_match.group(1))
        unit = rolling_match.group(2)
        if value <= 0:
            raise ValueError("invalid feed date filter")
        delta = timedelta(hours=value) if unit == "h" else timedelta(days=value)
        return reference - delta, reference

    tokens = expression.split()
    if not tokens or len(tokens) > 2:
        raise ValueError("invalid feed date filter")
    boundaries = {}
    for token in tokens:
        match = _FIXED_TOKEN.fullmatch(token)
        if not match or match.group(1) in boundaries:
            raise ValueError("invalid feed date filter")
        try:
            boundaries[match.group(1)] = datetime.strptime(
                match.group(2), "%Y-%m-%d"
            ).date()
        except ValueError:
            raise ValueError("invalid feed date filter") from None
    if not boundaries:
        raise ValueError("invalid feed date filter")
    start_at = (
        _local_midnight(zone, boundaries["from"])
        if "from" in boundaries
        else None
    )
    end_at = (
        _local_end_of_day(zone, boundaries["to"])
        if "to" in boundaries
        else None
    )
    if start_at is not None and end_at is not None and start_at > end_at:
        raise ValueError("invalid feed date filter")
    return start_at, end_at


def _subtract_calendar_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 - months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _local_midnight(zone, value: date) -> datetime:
    return zone.localize(datetime.combine(value, time.min))


def _local_end_of_day(zone, value: date) -> datetime:
    return zone.localize(datetime.combine(value, time.max))


def _parse_item_datetime(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid feed publication date")
    try:
        parsed = date_parser.parse(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("invalid feed publication date") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("invalid feed publication date")
    return parsed


def _fingerprint(
    date_filter: str,
    keyword_filter: str,
    keyword_scope: str,
    timezone_name: str,
    display_language: str,
) -> str:
    payload = json.dumps(
        {
            "date_filter": date_filter,
            "display_language": display_language,
            "keyword_filter": keyword_filter,
            "keyword_scope": keyword_scope,
            "timezone": timezone_name,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
