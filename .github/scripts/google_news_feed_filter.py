"""Combined service and user filters for Google News RSS items."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from feed_filters import (
    CompiledFeedFilter,
    combine_filter_fingerprints,
    compile_feed_filter,
    resolve_feed_date_filter,
    resolve_feed_keyword_filter,
    resolve_feed_timezone,
)
from feed_localization import normalize_display_language
from google_news_keyword_matcher import (
    CompiledKeywordMatch,
    compile_keyword_match,
    google_news_article_titles,
    keyword_filter_fingerprint,
    match_google_news_item,
)


@dataclass(frozen=True)
class GoogleNewsFilterResult:
    matched: bool
    reason: Optional[str]


@dataclass(frozen=True)
class CompiledGoogleNewsFeedFilter:
    common: CompiledFeedFilter
    service_keyword: Optional[CompiledKeywordMatch]
    service_mode: str
    legacy_keyword: Optional[CompiledKeywordMatch]
    fingerprint: str
    timezone_name: str
    display_language: str

    def matches(
        self,
        published_at: str,
        title: str,
        description_html: str,
    ) -> GoogleNewsFilterResult:
        main_title, related_article_titles = google_news_article_titles(
            title,
            description_html,
        )
        related_titles = "\n".join(related_article_titles)
        common_result = self.common.matches(
            published_at,
            main_title,
            "",
        )
        if not common_result.matched:
            related_keyword_match = (
                common_result.reason == "keyword"
                and self.common.keyword_scope == "title_or_description"
                and self.common.compiled_keyword is not None
                and any(
                    self.common.compiled_keyword.matches(related_title)
                    for related_title in related_article_titles
                )
            )
            if not related_keyword_match:
                return GoogleNewsFilterResult(False, common_result.reason)
        if self.service_keyword is not None:
            service_result = match_google_news_item(
                title,
                description_html,
                self.service_keyword,
                self.service_mode,
            )
            if not service_result.matched:
                return GoogleNewsFilterResult(False, "service_keyword")
        if self.legacy_keyword is not None:
            legacy_text = "{}\n{}".format(main_title, related_titles)
            if not self.legacy_keyword.matches(legacy_text):
                return GoogleNewsFilterResult(False, "legacy_keyword")
        return GoogleNewsFilterResult(True, None)


def compile_google_news_feed_filter(
    common_date: str = "",
    common_keyword: str = "",
    common_scope: str = "title",
    legacy_date: str = "",
    legacy_keyword: str = "",
    service_keyword: str = "",
    service_aliases: str = "",
    service_mode: str = "title",
    explicit_timezone: str = "",
    service_timezone: str = "",
    country_code: str = "",
    display_language: str = "en",
    now: Optional[datetime] = None,
) -> CompiledGoogleNewsFeedFilter:
    if service_mode not in {"title", "title_or_description"}:
        raise ValueError("invalid Google News service keyword mode")
    language = normalize_display_language(display_language)
    timezone_name = resolve_feed_timezone(
        explicit_timezone=explicit_timezone,
        service_timezone=service_timezone,
        country_code=country_code,
    )
    date_filter = resolve_feed_date_filter(common_date, legacy_date)
    common = compile_feed_filter(
        date_filter=date_filter,
        keyword_filter=common_keyword,
        keyword_scope=common_scope,
        timezone_name=timezone_name,
        display_language=language,
        now=now,
    )
    service_compiled = (
        compile_keyword_match(service_keyword, service_aliases)
        if service_keyword.strip()
        else None
    )
    if service_compiled is not None:
        service_fingerprint = keyword_filter_fingerprint(
            service_compiled,
            service_mode,
        )
    else:
        service_fingerprint = ""
    legacy_expression = resolve_feed_keyword_filter("", legacy_keyword)
    legacy_compiled = (
        compile_keyword_match(legacy_expression)
        if legacy_expression
        else None
    )
    fingerprint = combine_filter_fingerprints(
        common.fingerprint,
        service_fingerprint,
        legacy_expression,
    )
    return CompiledGoogleNewsFeedFilter(
        common=common,
        service_keyword=service_compiled,
        service_mode=service_mode,
        legacy_keyword=legacy_compiled,
        fingerprint=fingerprint,
        timezone_name=timezone_name,
        display_language=language,
    )
