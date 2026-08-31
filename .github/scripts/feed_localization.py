"""Localized fixed labels and dates for feed notifications."""

from typing import Dict

import pytz
from babel import Locale
from babel.dates import format_date, format_datetime
from dateutil import parser as date_parser


SUPPORTED_LANGUAGES = (
    "ko",
    "en",
    "ja",
    "zh-CN",
    "zh-TW",
    "es",
    "pt-BR",
    "fr",
    "de",
    "id",
)

_LANGUAGE_ALIASES = {
    "korean": "ko",
    "english": "en",
    "zh-cn": "zh-CN",
    "zh-tw": "zh-TW",
    "pt-br": "pt-BR",
}

_COUNTRY_DISPLAY_LANGUAGES = {
    "KR": "ko",
    "JP": "ja",
    "CN": "zh-CN",
    "TW": "zh-TW",
    "ES": "es",
    "MX": "es",
    "BR": "pt-BR",
    "FR": "fr",
    "DE": "de",
    "ID": "id",
}

_BABEL_LOCALES = {
    "ko": "ko",
    "en": "en",
    "ja": "ja",
    "zh-CN": "zh_CN",
    "zh-TW": "zh_TW",
    "es": "es",
    "pt-BR": "pt_BR",
    "fr": "fr",
    "de": "de",
    "id": "id",
}

_LABELS = {
    "ko": {
        "channel": "채널명",
        "duration": "재생시간",
        "published_date": "게시일자",
        "category": "카테고리",
        "thumbnail": "썸네일",
        "playlist": "재생목록",
        "search_results": "검색 결과",
        "google_news": "Google 뉴스",
        "top_news": "주요 뉴스",
        "topics": "주제",
    },
    "en": {
        "channel": "Channel",
        "duration": "Duration",
        "published_date": "Published",
        "category": "Category",
        "thumbnail": "Thumbnail",
        "playlist": "Playlist",
        "search_results": "Search Results",
        "google_news": "Google News",
        "top_news": "Top Stories",
        "topics": "Topics",
    },
    "ja": {
        "channel": "チャンネル",
        "duration": "再生時間",
        "published_date": "公開日",
        "category": "カテゴリ",
        "thumbnail": "サムネイル",
        "playlist": "再生リスト",
        "search_results": "検索結果",
        "google_news": "Google ニュース",
        "top_news": "トップニュース",
        "topics": "トピック",
    },
    "zh-CN": {
        "channel": "频道",
        "duration": "时长",
        "published_date": "发布日期",
        "category": "类别",
        "thumbnail": "缩略图",
        "playlist": "播放列表",
        "search_results": "搜索结果",
        "google_news": "Google 新闻",
        "top_news": "焦点新闻",
        "topics": "主题",
    },
    "zh-TW": {
        "channel": "頻道",
        "duration": "片長",
        "published_date": "發布日期",
        "category": "類別",
        "thumbnail": "縮圖",
        "playlist": "播放清單",
        "search_results": "搜尋結果",
        "google_news": "Google 新聞",
        "top_news": "焦點新聞",
        "topics": "主題",
    },
    "es": {
        "channel": "Canal",
        "duration": "Duración",
        "published_date": "Fecha de publicación",
        "category": "Categoría",
        "thumbnail": "Miniatura",
        "playlist": "Lista de reproducción",
        "search_results": "Resultados de búsqueda",
        "google_news": "Google Noticias",
        "top_news": "Noticias destacadas",
        "topics": "Temas",
    },
    "pt-BR": {
        "channel": "Canal",
        "duration": "Duração",
        "published_date": "Data de publicação",
        "category": "Categoria",
        "thumbnail": "Miniatura",
        "playlist": "Playlist",
        "search_results": "Resultados da pesquisa",
        "google_news": "Google Notícias",
        "top_news": "Principais notícias",
        "topics": "Tópicos",
    },
    "fr": {
        "channel": "Chaîne",
        "duration": "Durée",
        "published_date": "Date de publication",
        "category": "Catégorie",
        "thumbnail": "Miniature",
        "playlist": "Playlist",
        "search_results": "Résultats de recherche",
        "google_news": "Google Actualités",
        "top_news": "À la une",
        "topics": "Thèmes",
    },
    "de": {
        "channel": "Kanal",
        "duration": "Dauer",
        "published_date": "Veröffentlichungsdatum",
        "category": "Kategorie",
        "thumbnail": "Vorschaubild",
        "playlist": "Playlist",
        "search_results": "Suchergebnisse",
        "google_news": "Google News",
        "top_news": "Top-Meldungen",
        "topics": "Themen",
    },
    "id": {
        "channel": "Saluran",
        "duration": "Durasi",
        "published_date": "Tanggal publikasi",
        "category": "Kategori",
        "thumbnail": "Thumbnail",
        "playlist": "Daftar putar",
        "search_results": "Hasil pencarian",
        "google_news": "Google Berita",
        "top_news": "Berita utama",
        "topics": "Topik",
    },
}


def normalize_display_language(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("unsupported display language")
    candidate = value.strip()
    normalized = _LANGUAGE_ALIASES.get(candidate.casefold(), candidate)
    if normalized not in SUPPORTED_LANGUAGES:
        raise ValueError("unsupported display language")
    return normalized


def resolve_display_language(
    explicit_language: str = "",
    service_language: str = "",
    country_code: str = "",
) -> str:
    if isinstance(explicit_language, str) and explicit_language.strip():
        return normalize_display_language(explicit_language)
    service = service_language.strip() if isinstance(service_language, str) else ""
    service_aliases = {
        "zh": "zh-CN",
        "zh-hans": "zh-CN",
        "zh-hant": "zh-TW",
        "pt": "pt-BR",
    }
    candidate = service_aliases.get(service.casefold(), service.split("-", 1)[0])
    try:
        return normalize_display_language(candidate)
    except ValueError:
        pass
    country = country_code.strip().upper() if isinstance(country_code, str) else ""
    return _COUNTRY_DISPLAY_LANGUAGES.get(country, "en")


def labels_for(language: str) -> Dict[str, str]:
    normalized = normalize_display_language(language)
    return dict(_LABELS[normalized])


def format_feed_date(value: str, language: str, timezone_name: str) -> str:
    normalized = normalize_display_language(language)
    try:
        zone = pytz.timezone(timezone_name)
    except (AttributeError, pytz.UnknownTimeZoneError):
        raise ValueError("invalid feed timezone") from None
    try:
        parsed = date_parser.parse(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("invalid feed publication date") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("invalid feed publication date")
    local_date = parsed.astimezone(zone).date()
    return format_date(
        local_date,
        format="long",
        locale=_BABEL_LOCALES[normalized],
    )


def format_feed_datetime(value: str, language: str, timezone_name: str) -> str:
    normalized = normalize_display_language(language)
    zone = _timezone(timezone_name)
    parsed = _aware_datetime(value)
    return format_datetime(
        parsed,
        format="long",
        tzinfo=zone,
        locale=_BABEL_LOCALES[normalized],
    )


def localized_country_name(country_code: str, language: str) -> str:
    normalized = normalize_display_language(language)
    code = country_code.strip().upper() if isinstance(country_code, str) else ""
    if len(code) != 2:
        raise ValueError("invalid feed country")
    locale = Locale.parse(_BABEL_LOCALES[normalized])
    value = locale.territories.get(code)
    if not value:
        raise ValueError("invalid feed country")
    return value


def _timezone(timezone_name: str):
    try:
        return pytz.timezone(timezone_name)
    except (AttributeError, pytz.UnknownTimeZoneError):
        raise ValueError("invalid feed timezone") from None


def _aware_datetime(value: str):
    try:
        parsed = date_parser.parse(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("invalid feed publication date") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("invalid feed publication date")
    return parsed
