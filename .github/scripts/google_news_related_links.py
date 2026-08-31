"""Validation boundary for publisher URLs shown as related Google News items."""

from typing import Optional
from urllib.parse import urlsplit


SAFE_GOOGLE_ARTICLE_PATHS = ("/articles/", "/rss/articles/", "/read/")


def resolve_related_url(resolver, source_url: str) -> Optional[str]:
    result = resolver.resolve_related(source_url)
    url = result.url
    if _is_valid_publisher_url(url):
        return url
    if _is_safe_google_article_url(source_url):
        return source_url
    return None


def _is_valid_publisher_url(url: str) -> bool:
    if not isinstance(url, str) or not url.strip():
        return False
    try:
        parsed = urlsplit(url.strip())
        hostname = (parsed.hostname or "").rstrip(".").lower()
    except ValueError:
        return False
    if parsed.scheme.lower() not in {"http", "https"} or not hostname:
        return False
    if hostname == "news.google.com" or hostname.endswith(".news.google.com"):
        return False
    return True


def _is_safe_google_article_url(url: str) -> bool:
    if not isinstance(url, str) or not url.strip():
        return False
    try:
        parsed = urlsplit(url.strip())
        hostname = (parsed.hostname or "").rstrip(".").lower()
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == "https"
        and hostname == "news.google.com"
        and any(parsed.path.startswith(prefix) for prefix in SAFE_GOOGLE_ARTICLE_PATHS)
    )
