"""Validated non-secret configuration for multi-channel Google News delivery."""

import json
import os
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Dict, List, Mapping


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
}
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
    if handler == "keyword" and value.get("KEYWORD_MATCH_MODE", "title") not in {
        "title",
        "title_or_description",
    }:
        raise ValueError("profile {} has invalid KEYWORD_MATCH_MODE".format(index))
    return MappingProxyType(dict(value))


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
            "GOOGLE_NEWS_MAX_NETWORK_RESOLUTIONS": "1000",
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
