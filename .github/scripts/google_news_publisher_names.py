"""Canonical publisher names used in Google News Discord messages."""

import re
from urllib.parse import urlsplit


DOMAIN_NAMES = {
    "biz.chosun.com": "조선비즈",
    "daum.net": "다음",
    "koreadaily.com": "미주중앙일보",
    "mydaily.co.kr": "마이데일리",
    "xportsnews.com": "엑스포츠뉴스",
}

LABEL_NAMES = {
    "biz.chosun.com": "조선비즈",
    "chosunbiz": "조선비즈",
    "daum.net": "다음",
    "v.daum.net": "다음",
    "koreadaily.com": "미주중앙일보",
    "mydaily.co.kr": "마이데일리",
    "xportsnews.com": "엑스포츠뉴스",
}


def normalize_publisher_name(publisher_name: str, article_url: str = "") -> str:
    """Return a known Korean publisher name while preserving unknown labels."""
    normalized_label = (publisher_name or "").strip()
    hostname = _hostname(article_url)
    for domain in sorted(DOMAIN_NAMES, key=len, reverse=True):
        if hostname == domain or hostname.endswith("." + domain):
            return DOMAIN_NAMES[domain]
    return LABEL_NAMES.get(normalized_label.casefold(), normalized_label)


def normalize_article_title(title: str, article_url: str = "") -> str:
    """Normalize the final publisher suffix in a Google News article title."""
    headline, separator, publisher_name = (title or "").rpartition(" - ")
    if not separator or not headline or not publisher_name:
        return title
    normalized_name = normalize_publisher_name(publisher_name, article_url)
    if not normalized_name or normalized_name == publisher_name:
        return title
    return "{} - {}".format(headline, normalized_name)


def normalize_message_publisher_names(content: str) -> str:
    """Upgrade publisher labels in messages already stored in a delivery queue."""
    normalized_content = content
    for label in sorted(LABEL_NAMES, key=len, reverse=True):
        canonical_name = LABEL_NAMES[label]
        escaped_label = re.escape(label)
        normalized_content = re.sub(
            r"( - ){}(?=\*\*(?:\n|$))".format(escaped_label),
            lambda match: match.group(1) + canonical_name,
            normalized_content,
            flags=re.IGNORECASE,
        )
        normalized_content = re.sub(
            r"(\|\s*){}(?=\s*(?:\n|$))".format(escaped_label),
            lambda match: match.group(1) + canonical_name,
            normalized_content,
            flags=re.IGNORECASE,
        )
    return normalized_content


def _hostname(article_url: str) -> str:
    try:
        return (urlsplit(article_url).hostname or "").rstrip(".").casefold()
    except (TypeError, ValueError):
        return ""
