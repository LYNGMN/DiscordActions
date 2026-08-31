"""Plain Discord message formatting shared by YouTube RSS and API sources."""

from typing import Dict, Iterable, Optional
from urllib.parse import quote

from feed_localization import format_feed_date, labels_for, normalize_display_language


PLAYLIST_LAYOUTS = {"auto", "channel", "curated"}
SOURCE_TYPES = {"channels", "playlists", "search"}


def resolve_playlist_layout(requested: str, channel_titles: Iterable[str]) -> str:
    value = requested.strip().lower() if isinstance(requested, str) else ""
    if value not in PLAYLIST_LAYOUTS:
        raise ValueError("invalid YouTube playlist layout")
    if value != "auto":
        return value
    unique_channels = {
        title.strip()
        for title in channel_titles
        if isinstance(title, str) and title.strip()
    }
    return "channel" if len(unique_channels) == 1 else "curated"


def build_youtube_message(
    video: Dict[str, str],
    source_type: str,
    display_language: str,
    timezone_name: str,
    include_api_details: bool,
    playlist: Optional[Dict[str, str]] = None,
    playlist_layout: str = "auto",
    search_keyword: str = "",
) -> str:
    if source_type not in SOURCE_TYPES:
        raise ValueError("invalid YouTube source type")
    language = normalize_display_language(display_language)
    labels = labels_for(language)
    channel_title = _required(video, "channel_title")
    title = _required(video, "title")
    video_url = _required(video, "video_url")
    published_at = _required(video, "published_at")
    thumbnail_url = _required(video, "thumbnail_url")

    lines = []
    if source_type == "playlists":
        if not isinstance(playlist, dict):
            raise ValueError("YouTube playlist metadata is required")
        playlist_title = _required(playlist, "title")
        owner_title = _required(playlist, "owner_title")
        layout = resolve_playlist_layout(playlist_layout, [channel_title])
        if layout == "channel":
            header = "📃 {} by. {} - YouTube {}".format(
                playlist_title,
                channel_title,
                labels["playlist"],
            )
        else:
            header = "📃 {} - YouTube {} by. {}".format(
                playlist_title,
                labels["playlist"],
                owner_title,
            )
        lines.extend(("`{}`".format(header), ""))
    elif source_type == "search":
        if not isinstance(search_keyword, str) or not search_keyword.strip():
            raise ValueError("YouTube search keyword is required")
        lines.extend(
            (
                "`🔎 {} - YouTube {}`".format(
                    search_keyword.strip(), labels["search_results"]
                ),
                "",
            )
        )

    lines.extend(
        (
            "`{} - YouTube`".format(channel_title),
            "**{}**".format(title),
            video_url,
            "",
        )
    )
    if include_api_details:
        duration = video.get("duration", "").strip()
        category_name = video.get("category_name", "").strip()
        if duration:
            lines.append("⏳ {}: `{}`".format(labels["duration"], duration))
        lines.append(
            "📅 {}: `{}`".format(
                labels["published_date"],
                format_feed_date(published_at, language, timezone_name),
            )
        )
        if category_name:
            lines.append("📁 {}: `{}`".format(labels["category"], category_name))
    else:
        if source_type == "playlists":
            lines.append(
                "👤 {}: [{}]({})".format(
                    labels["channel"],
                    channel_title,
                    _youtube_channel_url(video),
                )
            )
        lines.append(
            "📅 {}: `{}`".format(
                labels["published_date"],
                format_feed_date(published_at, language, timezone_name),
            )
        )
    lines.append("🖼️ [{}]({})".format(labels["thumbnail"], thumbnail_url))
    return "\n".join(lines)


def _required(data: Dict[str, str], key: str) -> str:
    value = data.get(key) if isinstance(data, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing YouTube message field: {}".format(key))
    return value.strip()


def _youtube_channel_url(video: Dict[str, str]) -> str:
    channel_id = _required(video, "channel_id")
    return "https://www.youtube.com/channel/{}".format(
        quote(channel_id, safe="")
    )
