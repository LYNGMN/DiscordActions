"""Validated publisher names used in Google News Discord messages."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Tuple
from urllib.parse import urlsplit


DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "google_news_publishers.json"
)
DOMAIN_LABEL = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?\.?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PublisherResolution:
    display_name: str
    normalized_label: str
    hostname: str
    mapped: bool
    domain_like: bool


class PublisherRegistry:
    """Resolve publisher domains and aliases from a validated JSON registry."""

    def __init__(self, domains: Dict[str, str], aliases: Dict[str, str]):
        self._domains = dict(domains)
        self._aliases = dict(aliases)

    @classmethod
    def from_path(cls, path) -> "PublisherRegistry":
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError) as error:
            raise ValueError("invalid publisher registry") from error
        if not isinstance(payload, dict) or set(payload) != {
            "schema_version",
            "publishers",
        }:
            raise ValueError("invalid publisher registry")
        if payload.get("schema_version") != 1 or not isinstance(
            payload.get("publishers"), list
        ):
            raise ValueError("invalid publisher registry")

        domains: Dict[str, str] = {}
        aliases: Dict[str, str] = {}
        seen_aliases = set()
        for item in payload["publishers"]:
            if not isinstance(item, dict) or set(item) != {
                "canonical_name",
                "domains",
                "aliases",
            }:
                raise ValueError("invalid publisher registry")
            canonical_name = item.get("canonical_name")
            domain_values = item.get("domains")
            alias_values = item.get("aliases")
            if (
                not isinstance(canonical_name, str)
                or not canonical_name.strip()
                or not isinstance(domain_values, list)
                or not domain_values
                or not isinstance(alias_values, list)
            ):
                raise ValueError("invalid publisher registry")
            canonical_name = canonical_name.strip()
            for domain in domain_values:
                normalized_domain = _normalized_domain(domain)
                if not normalized_domain or normalized_domain in domains:
                    raise ValueError("duplicate or invalid publisher domain")
                domains[normalized_domain] = canonical_name
            for alias in alias_values:
                if not isinstance(alias, str) or not alias.strip():
                    raise ValueError("invalid publisher alias")
                normalized_alias = alias.strip().casefold()
                if normalized_alias in seen_aliases:
                    raise ValueError("duplicate publisher alias")
                seen_aliases.add(normalized_alias)
                aliases[normalized_alias] = canonical_name
        return cls(domains, aliases)

    def resolve(self, label: str, article_url: str = "") -> PublisherResolution:
        display_label = label.strip() if isinstance(label, str) else ""
        normalized_label = display_label.casefold()
        domain_like = bool(DOMAIN_LABEL.fullmatch(normalized_label))
        article_hostname = _hostname(article_url)
        label_hostname = normalized_label.rstrip(".") if domain_like else ""

        canonical_name = self._match_domain(article_hostname)
        if canonical_name is None:
            canonical_name = self._aliases.get(normalized_label)
        if canonical_name is None and label_hostname:
            canonical_name = self._match_domain(label_hostname)

        safe_hostname = article_hostname
        if _is_google_news_hostname(safe_hostname) or not safe_hostname:
            safe_hostname = label_hostname
        return PublisherResolution(
            display_name=canonical_name or display_label,
            normalized_label=normalized_label,
            hostname=safe_hostname,
            mapped=canonical_name is not None,
            domain_like=domain_like,
        )

    def publisher_labels(self) -> Iterable[Tuple[str, str]]:
        for domain, canonical_name in self._domains.items():
            yield domain, canonical_name
        for alias, canonical_name in self._aliases.items():
            yield alias, canonical_name

    def _match_domain(self, hostname: str):
        for domain in sorted(self._domains, key=len, reverse=True):
            if hostname == domain or hostname.endswith("." + domain):
                return self._domains[domain]
        return None


def load_default_registry() -> PublisherRegistry:
    return PublisherRegistry.from_path(DEFAULT_REGISTRY_PATH)


def normalize_article_title(
    title: str,
    article_url: str = "",
    registry: PublisherRegistry = None,
) -> str:
    headline, separator, publisher_name = (title or "").rpartition(" - ")
    if not separator or not headline or not publisher_name:
        return title
    resolution = (registry or load_default_registry()).resolve(
        publisher_name, article_url
    )
    if not resolution.display_name or resolution.display_name == publisher_name:
        return title
    return "{} - {}".format(headline, resolution.display_name)


def normalize_message_publisher_names(
    content: str,
    registry: PublisherRegistry = None,
) -> str:
    active_registry = registry or load_default_registry()
    normalized_lines = []
    for line in (content or "").splitlines(keepends=True):
        newline = ""
        body = line
        if line.endswith("\r\n"):
            body, newline = line[:-2], "\r\n"
        elif line.endswith("\n"):
            body, newline = line[:-1], "\n"

        if body.startswith("**") and body.endswith("**"):
            inner = body[2:-2]
            body = "**{}**".format(
                normalize_article_title(inner, registry=active_registry)
            )
        related = re.match(r"^(.*\|\s*)([^|]+?)\s*$", body)
        if related:
            resolution = active_registry.resolve(related.group(2))
            if resolution.mapped:
                body = related.group(1) + resolution.display_name
        normalized_lines.append(body + newline)
    return "".join(normalized_lines)


def publisher_label_from_title(title: str) -> str:
    headline, separator, publisher_name = (title or "").rpartition(" - ")
    if not separator or not headline:
        return ""
    return publisher_name.strip()


def _normalized_domain(value) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip().rstrip(".").casefold()
    return normalized if DOMAIN_LABEL.fullmatch(normalized) else ""


def _hostname(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").rstrip(".").casefold()
    except (TypeError, ValueError):
        return ""


def _is_google_news_hostname(hostname: str) -> bool:
    return hostname == "news.google.com" or hostname.endswith(".news.google.com")
