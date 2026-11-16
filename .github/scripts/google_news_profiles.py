"""Validated non-secret configuration for multi-channel Google News delivery."""

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Dict, List, Mapping
from urllib.parse import parse_qs, urlparse

from feed_filters import compile_feed_filter, resolve_feed_timezone
from feed_localization import resolve_display_language
from feed_timezones import COUNTRY_TIMEZONES


DEFAULT_MAX_NETWORK_RESOLUTIONS = 40
MAX_NETWORK_RESOLUTIONS = 1000
SUPPORTED_TOPICS = frozenset(
    {
        "ai", "american_football", "art_design", "automation", "automotive",
        "baseball", "basketball", "beauty", "business", "celebrity", "china",
        "cricket", "cycling", "digital_currency", "economy", "education",
        "energy", "entertainment", "environment", "fashion", "finance", "food",
        "gadgets", "games", "geography", "golf", "headlines", "health",
        "higher_education", "hockey", "home", "internet_security", "japan",
        "job_market", "korea", "martial_arts", "medicine", "mental_health",
        "mobile", "motorsports", "movies", "music", "neuroscience",
        "nutrition", "online_education", "outdoor", "paleontology",
        "personal_finance", "physics", "politics", "public_health", "robotics",
        "science", "science_technology", "shopping", "soccer", "social_science",
        "space", "sports", "sports_betting", "technology", "tennis", "theater",
        "travel", "tv", "us", "virtual_reality", "water_sports", "wildlife",
        "world",
    }
)
PROFILE_FIELDS = {
    "id",
    "handler",
    "webhook_env",
    "expected_webhook_name",
    "state_db",
    "visible_username",
    "environment",
}
HANDLER_ENVIRONMENT = {
    "top": {
        "required": {"TOP_MODE", "TOP_COUNTRY"},
        "allowed": {"TOP_MODE", "TOP_COUNTRY", "RSS_URL_TOP"},
    },
    "topic": {
        "required": {"TOPIC_MODE", "TOPIC_KEYWORD", "TOPIC_PARAMS"},
        "allowed": {"TOPIC_MODE", "TOPIC_KEYWORD", "TOPIC_PARAMS", "RSS_URL_TOPIC"},
    },
    "keyword": {
        "required": {"KEYWORD_MODE", "KEYWORD", "HL", "GL", "CEID"},
        "allowed": {
            "KEYWORD_MODE",
            "KEYWORD",
            "KEYWORD_DISPLAY_NAME",
            "HL",
            "GL",
            "CEID",
            "WHEN",
            "AFTER_DATE",
            "BEFORE_DATE",
            "RSS_URL_KEYWORD",
            "KEYWORD_MATCH_MODE",
            "KEYWORD_MATCH_ALIASES",
        },
    },
}
COMMON_PROFILE_ENVIRONMENT = {
    "DISPLAY_LANGUAGE",
    "FEED_COUNTRY",
    "FEED_DATE_FILTER",
    "FEED_KEYWORD_FILTER",
    "FEED_KEYWORD_SCOPE",
    "FEED_TIMEZONE",
}
for _contract in HANDLER_ENVIRONMENT.values():
    _contract["allowed"].update(COMMON_PROFILE_ENVIRONMENT)
BASE_ENV_ALLOWLIST = {
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "PYTHONIOENCODING",
    "PYTHONPATH",
    "PYTHONUNBUFFERED",
    "REQUESTS_CA_BUNDLE",
    "RUNNER_TEMP",
    "SSL_CERT_FILE",
    "TZ",
    "GOOGLE_NEWS_MAX_DELIVERIES_PER_PROFILE",
} | COMMON_PROFILE_ENVIRONMENT
CREDENTIAL_KEY = re.compile(
    r"(?:authorization|cookie|password|secret|token|webhook)", re.IGNORECASE
)
CREDENTIAL_VALUE = re.compile(
    r"(?:discord(?:app)?\.com/api/webhooks/|github_pat_|ghp_[A-Za-z0-9])",
    re.IGNORECASE,
)
SAFE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
SAFE_WEBHOOK_ENV = re.compile(r"^DISCORD_WEBHOOK_GN_[A-Z0-9_]+$")
SAFE_DATABASE = re.compile(r"^[a-z][a-z0-9_]*\.db$")


@dataclass(frozen=True)
class GoogleNewsProfile:
    profile_id: str
    handler: str
    webhook_env: str
    expected_webhook_name: str
    state_db: str
    visible_username: str
    environment: Mapping[str, str]


def _require_non_empty_string(item: Mapping[str, object], key: str, index: int) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("profile {} has invalid {}".format(index, key))
    return value


def _mode_is_true(value: Mapping[str, str], key: str, index: int) -> bool:
    item = value.get(key)
    if item not in {"true", "false"}:
        raise ValueError(
            "profile {} has invalid {} (expected true or false)".format(index, key)
        )
    return item == "true"


def _require_google_rss_url(
    value: Mapping[str, str], key: str, index: int
) -> None:
    candidate = value.get(key, "")
    parsed = urlparse(candidate)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "news.google.com"
        or parsed.netloc != "news.google.com"
        or parsed.username
        or parsed.password
    ):
        raise ValueError(
            "profile {} {} must be an HTTPS news.google.com URL".format(index, key)
        )


def _validate_handler_modes(
    handler: str, value: Mapping[str, str], index: int
) -> None:
    if handler == "top":
        if _mode_is_true(value, "TOP_MODE", index):
            if "RSS_URL_TOP" in value:
                raise ValueError(
                    "profile {} must not set RSS_URL_TOP when TOP_MODE is true".format(
                        index
                    )
                )
            country = value.get("TOP_COUNTRY", "")
            if not re.fullmatch(r"[A-Z]{2}", country) or country not in COUNTRY_TIMEZONES:
                raise ValueError("profile {} has invalid TOP_COUNTRY".format(index))
        else:
            _require_google_rss_url(value, "RSS_URL_TOP", index)
        return

    if handler == "topic":
        if _mode_is_true(value, "TOPIC_MODE", index):
            if "RSS_URL_TOPIC" in value:
                raise ValueError(
                    "profile {} must not set RSS_URL_TOPIC when TOPIC_MODE is true".format(
                        index
                    )
                )
            topic = value.get("TOPIC_KEYWORD", "")
            if topic not in SUPPORTED_TOPICS:
                raise ValueError("profile {} has invalid TOPIC_KEYWORD".format(index))
            params = value.get("TOPIC_PARAMS", "")
            if not params.startswith("?"):
                raise ValueError("profile {} has invalid TOPIC_PARAMS".format(index))
            query = parse_qs(params[1:], keep_blank_values=True)
            if set(query) != {"hl", "gl", "ceid"}:
                raise ValueError("profile {} has invalid TOPIC_PARAMS".format(index))
            if any(len(items) != 1 or not items[0] for items in query.values()):
                raise ValueError("profile {} has invalid TOPIC_PARAMS".format(index))
            if (
                not re.fullmatch(r"[A-Z]{2}", query["gl"][0])
                or query["gl"][0] not in COUNTRY_TIMEZONES
            ):
                raise ValueError("profile {} has invalid TOPIC_PARAMS".format(index))
        else:
            _require_google_rss_url(value, "RSS_URL_TOPIC", index)
        return

    if _mode_is_true(value, "KEYWORD_MODE", index):
        if "RSS_URL_KEYWORD" in value:
            raise ValueError(
                "profile {} must not set RSS_URL_KEYWORD when KEYWORD_MODE is true".format(
                    index
                )
            )
        for key in ("HL", "GL", "CEID"):
            if not value.get(key, "").strip():
                raise ValueError("profile {} has empty {}".format(index, key))
        gl = value.get("GL", "")
        if not re.fullmatch(r"[A-Z]{2}", gl) or gl not in COUNTRY_TIMEZONES:
            raise ValueError("profile {} has invalid GL".format(index))
        if not re.fullmatch(r"[A-Za-z0-9-]+:[A-Za-z0-9-]+", value.get("CEID", "")):
            raise ValueError("profile {} has invalid CEID".format(index))
        if value.get("CEID", "").split(":", 1)[0] != gl:
            raise ValueError("profile {} CEID must match GL".format(index))
        if not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z]{2,4})?", value.get("HL", "")):
            raise ValueError("profile {} has invalid HL".format(index))
        when = value.get("WHEN", "")
        after = value.get("AFTER_DATE", "")
        before = value.get("BEFORE_DATE", "")
        if when and (after or before):
            raise ValueError(
                "profile {} must not combine WHEN with AFTER_DATE or BEFORE_DATE".format(
                    index
                )
            )
        if when and not re.fullmatch(r"[1-9][0-9]*[hdwmy]", when):
            raise ValueError("profile {} has invalid WHEN".format(index))
        for key, item in (("AFTER_DATE", after), ("BEFORE_DATE", before)):
            if not item:
                continue
            try:
                datetime.strptime(item, "%Y-%m-%d")
            except ValueError:
                raise ValueError(
                    "profile {} has invalid {}".format(index, key)
                ) from None
    else:
        _require_google_rss_url(value, "RSS_URL_KEYWORD", index)


def _validate_environment(handler: str, value: object, index: int) -> Mapping[str, str]:
    if not isinstance(value, dict):
        raise ValueError("profile {} environment must be an object".format(index))
    if any(not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()):
        raise ValueError("profile {} environment values must be strings".format(index))
    for key, item in value.items():
        if CREDENTIAL_KEY.search(key) or CREDENTIAL_VALUE.search(item):
            raise ValueError("profile {} contains credential-like configuration".format(index))
        if item.lower().startswith("http://"):
            raise ValueError("profile {} URL configuration must use HTTPS".format(index))

    contract = HANDLER_ENVIRONMENT[handler]
    missing = contract["required"] - set(value)
    if missing:
        raise ValueError(
            "profile {} missing environment keys: {}".format(index, ", ".join(sorted(missing)))
        )
    unknown = set(value) - contract["allowed"]
    if unknown:
        raise ValueError(
            "profile {} has unknown environment keys: {}".format(
                index, ", ".join(sorted(unknown))
            )
        )
    country = value.get("FEED_COUNTRY", "")
    if country and (not re.fullmatch(r"[A-Z]{2}", country) or country not in COUNTRY_TIMEZONES):
        raise ValueError("profile {} has invalid FEED_COUNTRY".format(index))
    _validate_handler_modes(handler, value, index)
    if (
        handler == "keyword"
        and "KEYWORD_DISPLAY_NAME" in value
        and not value["KEYWORD_DISPLAY_NAME"].strip()
    ):
        raise ValueError("profile {} has invalid KEYWORD_DISPLAY_NAME".format(index))
    if handler == "keyword" and value.get("KEYWORD_MATCH_MODE", "title") not in {
        "title",
        "title_or_description",
    }:
        raise ValueError("profile {} has invalid KEYWORD_MATCH_MODE".format(index))
    scope = value.get("FEED_KEYWORD_SCOPE", "title")
    if scope not in {"title", "title_or_description"}:
        raise ValueError("profile {} has invalid FEED_KEYWORD_SCOPE".format(index))
    try:
        language = resolve_display_language(
            value.get("DISPLAY_LANGUAGE", ""),
            country_code=value.get("FEED_COUNTRY", ""),
        )
        timezone_name = resolve_feed_timezone(
            explicit_timezone=value.get("FEED_TIMEZONE", ""),
            country_code=value.get("FEED_COUNTRY", ""),
        )
        compile_feed_filter(
            date_filter=value.get("FEED_DATE_FILTER", ""),
            keyword_filter=value.get("FEED_KEYWORD_FILTER", ""),
            keyword_scope=scope,
            timezone_name=timezone_name,
            display_language=language,
        )
    except ValueError as error:
        raise ValueError("profile {} has invalid common feed settings: {}".format(index, error)) from None
    return MappingProxyType(dict(value))


def validate_common_feed_environment(value: Mapping[str, str]) -> None:
    """Validate merged global/profile feed settings before external requests."""

    scope = value.get("FEED_KEYWORD_SCOPE", "title")
    try:
        language = resolve_display_language(
            value.get("DISPLAY_LANGUAGE", ""),
            country_code=value.get("FEED_COUNTRY", ""),
        )
        timezone_name = resolve_feed_timezone(
            explicit_timezone=value.get("FEED_TIMEZONE", ""),
            country_code=value.get("FEED_COUNTRY", ""),
        )
        compile_feed_filter(
            date_filter=value.get("FEED_DATE_FILTER", ""),
            keyword_filter=value.get("FEED_KEYWORD_FILTER", ""),
            keyword_scope=scope,
            timezone_name=timezone_name,
            display_language=language,
        )
    except ValueError as error:
        raise ValueError("invalid common feed settings: {}".format(error)) from None


def validate_profile_data(raw: object) -> List[GoogleNewsProfile]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("profile registry must be a non-empty list")

    profiles = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError("profile {} must be an object".format(index))
        unknown_fields = set(item) - PROFILE_FIELDS
        missing_fields = PROFILE_FIELDS - set(item)
        if unknown_fields:
            raise ValueError(
                "profile {} has unknown fields: {}".format(
                    index, ", ".join(sorted(unknown_fields))
                )
            )
        if missing_fields:
            raise ValueError(
                "profile {} is missing fields: {}".format(
                    index, ", ".join(sorted(missing_fields))
                )
            )

        handler = _require_non_empty_string(item, "handler", index)
        if handler not in HANDLER_ENVIRONMENT:
            raise ValueError("profile {} has invalid handler".format(index))
        profile_id = _require_non_empty_string(item, "id", index)
        webhook_env = _require_non_empty_string(item, "webhook_env", index)
        expected_webhook_name = _require_non_empty_string(
            item, "expected_webhook_name", index
        )
        state_db = _require_non_empty_string(item, "state_db", index)
        visible_username = _require_non_empty_string(item, "visible_username", index)

        if not SAFE_IDENTIFIER.fullmatch(profile_id):
            raise ValueError("profile {} id is not a safe identifier".format(index))
        if not SAFE_WEBHOOK_ENV.fullmatch(webhook_env):
            raise ValueError("profile {} webhook_env is invalid".format(index))
        if not SAFE_DATABASE.fullmatch(state_db) or os.path.basename(state_db) != state_db:
            raise ValueError("profile {} state_db must be a safe database filename".format(index))
        if visible_username != "Google News":
            raise ValueError("profile {} visible_username must be Google News".format(index))

        environment = _validate_environment(handler, item["environment"], index)
        profiles.append(
            GoogleNewsProfile(
                profile_id=profile_id,
                handler=handler,
                webhook_env=webhook_env,
                expected_webhook_name=expected_webhook_name,
                state_db=state_db,
                visible_username=visible_username,
                environment=environment,
            )
        )

    for field in ("profile_id", "webhook_env", "expected_webhook_name", "state_db"):
        values = [getattr(profile, field) for profile in profiles]
        if len(values) != len(set(values)):
            source_field = "id" if field == "profile_id" else field
            raise ValueError("duplicate {} in profile registry".format(source_field))
    return profiles


def load_profiles(path: str) -> List[GoogleNewsProfile]:
    with open(path, "r", encoding="utf-8") as handle:
        return validate_profile_data(json.load(handle))


def parse_max_network_resolutions(value: str = "40") -> int:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,4}", value):
        raise ValueError("invalid_google_news_max_network_resolutions")
    parsed = int(value)
    if parsed > MAX_NETWORK_RESOLUTIONS:
        raise ValueError("invalid_google_news_max_network_resolutions")
    return parsed


def build_handler_environment(
    profile: GoogleNewsProfile,
    base_env: Mapping[str, str],
    state_dir: str,
    resolver_db: str,
    manual_test: bool,
) -> Dict[str, str]:
    webhook_url = base_env.get(profile.webhook_env, "").strip()
    if not webhook_url:
        raise ValueError("missing webhook environment: {}".format(profile.webhook_env))

    environment = {
        key: value
        for key, value in base_env.items()
        if key in BASE_ENV_ALLOWLIST and isinstance(value, str)
    }
    environment.update(profile.environment)
    environment.update(
        {
            "GOOGLE_NEWS_PROFILE_ID": profile.profile_id,
            "GOOGLE_NEWS_DB_PATH": os.path.join(state_dir, profile.state_db),
            "GOOGLE_NEWS_RESOLVER_DB_PATH": resolver_db,
            "GOOGLE_NEWS_MAX_NETWORK_RESOLUTIONS": str(
                parse_max_network_resolutions(
                    base_env.get(
                        "GOOGLE_NEWS_MAX_NETWORK_RESOLUTIONS",
                        str(DEFAULT_MAX_NETWORK_RESOLUTIONS),
                    )
                )
            ),
            "GOOGLE_NEWS_MAX_DELIVERIES_PER_PROFILE": base_env.get(
                "GOOGLE_NEWS_MAX_DELIVERIES_PER_PROFILE", "25"
            ),
            "GOOGLE_NEWS_DELIVERY_ORDER": base_env.get(
                "GOOGLE_NEWS_DELIVERY_ORDER", "feed_oldest_first"
            ),
            "MANUAL_TEST_MODE": "true" if manual_test else "false",
        }
    )
    admin_webhook = base_env.get("DISCORD_WEBHOOK_ADMIN", "").strip()
    if admin_webhook:
        environment["DISCORD_WEBHOOK_ADMIN"] = admin_webhook

    handler_key = profile.handler.upper()
    environment["DISCORD_WEBHOOK_{}".format(handler_key)] = webhook_url
    environment["DISCORD_USERNAME_{}".format(handler_key)] = profile.visible_username
    environment["ORIGIN_LINK_{}".format(handler_key)] = "true"
    environment["INITIALIZE_MODE_{}".format(handler_key)] = "false"
    return environment
