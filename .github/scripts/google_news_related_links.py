"""Validation boundary for publisher URLs shown as related Google News items."""

from typing import Optional
from urllib.parse import urlsplit


MAX_RELATED_ITEMS = 4


def resolve_related_url(resolver, source_url: str) -> Optional[str]:
    result = resolver.resolve_related(source_url)
    url = result.url
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parsed = urlsplit(url.strip())
        hostname = (parsed.hostname or "").rstrip(".").lower()
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not hostname:
        return None
    if hostname == "news.google.com" or hostname.endswith(".news.google.com"):
        return None
    return url
