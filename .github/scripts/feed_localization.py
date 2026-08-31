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
        "video_id": "영상 ID",
        "duration": "재생시간",
        "published_date": "게시일자",
        "category": "카테고리",
        "tags": "태그",
        "subtitle": "자막",
        "thumbnail": "썸네일",
        "play_video": "영상 재생",
        "download": "다운로드",
        "embed": "임베드",
        "not_available": "정보 없음",
        "playlist": "재생목록",
        "search_results": "검색 결과",
        "google_news": "Google 뉴스",
        "top_news": "주요 뉴스",
        "topics": "주제",
    },
    "en": {
        "channel": "Channel",
        "video_id": "Video ID",
        "duration": "Duration",
        "published_date": "Published",
        "category": "Category",
        "tags": "Tags",
        "subtitle": "Subtitle",
        "thumbnail": "Thumbnail",
        "play_video": "Play Video",
        "download": "Download",
        "embed": "Embed",
        "not_available": "N/A",
        "playlist": "Playlist",
        "search_results": "Search Results",
        "google_news": "Google News",
        "top_news": "Top Stories",
        "topics": "Topics",
    },
    "ja": {
        "channel": "チャンネル",
        "video_id": "動画 ID",
        "duration": "再生時間",
        "published_date": "公開日",
        "category": "カテゴリ",
        "tags": "タグ",
        "subtitle": "字幕",
        "thumbnail": "サムネイル",
        "play_video": "動画を再生",
        "download": "ダウンロード",
        "embed": "埋め込み",
        "not_available": "該当なし",
        "playlist": "再生リスト",
        "search_results": "検索結果",
        "google_news": "Google ニュース",
        "top_news": "トップニュース",
        "topics": "トピック",
    },
    "zh-CN": {
        "channel": "频道",
        "video_id": "视频 ID",
        "duration": "时长",
        "published_date": "发布日期",
        "category": "类别",
        "tags": "标签",
        "subtitle": "字幕",
        "thumbnail": "缩略图",
        "play_video": "播放视频",
        "download": "下载",
        "embed": "嵌入",
        "not_available": "暂无",
        "playlist": "播放列表",
        "search_results": "搜索结果",
        "google_news": "Google 新闻",
        "top_news": "焦点新闻",
        "topics": "主题",
    },
    "zh-TW": {
        "channel": "頻道",
        "video_id": "影片 ID",
        "duration": "片長",
        "published_date": "發布日期",
        "category": "類別",
        "tags": "標籤",
        "subtitle": "字幕",
        "thumbnail": "縮圖",
        "play_video": "播放影片",
        "download": "下載",
        "embed": "嵌入",
        "not_available": "無資料",
        "playlist": "播放清單",
        "search_results": "搜尋結果",
        "google_news": "Google 新聞",
        "top_news": "焦點新聞",
        "topics": "主題",
    },
    "es": {
        "channel": "Canal",
        "video_id": "ID del video",
        "duration": "Duración",
        "published_date": "Fecha de publicación",
        "category": "Categoría",
        "tags": "Etiquetas",
        "subtitle": "Subtítulos",
        "thumbnail": "Miniatura",
        "play_video": "Reproducir video",
        "download": "Descargar",
        "embed": "Insertar",
        "not_available": "No disponible",
        "playlist": "Lista de reproducción",
        "search_results": "Resultados de búsqueda",
        "google_news": "Google Noticias",
        "top_news": "Noticias destacadas",
        "topics": "Temas",
    },
    "pt-BR": {
        "channel": "Canal",
        "video_id": "ID do vídeo",
        "duration": "Duração",
        "published_date": "Data de publicação",
        "category": "Categoria",
        "tags": "Tags",
        "subtitle": "Legendas",
        "thumbnail": "Miniatura",
        "play_video": "Reproduzir vídeo",
        "download": "Baixar",
        "embed": "Incorporar",
        "not_available": "Não disponível",
        "playlist": "Playlist",
        "search_results": "Resultados da pesquisa",
        "google_news": "Google Notícias",
        "top_news": "Principais notícias",
        "topics": "Tópicos",
    },
    "fr": {
        "channel": "Chaîne",
        "video_id": "ID de la vidéo",
        "duration": "Durée",
        "published_date": "Date de publication",
        "category": "Catégorie",
        "tags": "Tags",
        "subtitle": "Sous-titres",
        "thumbnail": "Miniature",
        "play_video": "Lire la vidéo",
        "download": "Télécharger",
        "embed": "Intégrer",
        "not_available": "Non disponible",
        "playlist": "Playlist",
        "search_results": "Résultats de recherche",
        "google_news": "Google Actualités",
        "top_news": "À la une",
        "topics": "Thèmes",
    },
    "de": {
        "channel": "Kanal",
        "video_id": "Video-ID",
        "duration": "Dauer",
        "published_date": "Veröffentlichungsdatum",
        "category": "Kategorie",
        "tags": "Tags",
        "subtitle": "Untertitel",
        "thumbnail": "Vorschaubild",
        "play_video": "Video abspielen",
        "download": "Herunterladen",
        "embed": "Einbetten",
        "not_available": "Nicht verfügbar",
        "playlist": "Playlist",
        "search_results": "Suchergebnisse",
        "google_news": "Google News",
        "top_news": "Top-Meldungen",
        "topics": "Themen",
    },
    "id": {
        "channel": "Saluran",
        "video_id": "ID video",
        "duration": "Durasi",
        "published_date": "Tanggal publikasi",
        "category": "Kategori",
        "tags": "Tag",
        "subtitle": "Subtitel",
        "thumbnail": "Thumbnail",
        "play_video": "Putar video",
        "download": "Unduh",
        "embed": "Sematkan",
        "not_available": "Tidak tersedia",
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
