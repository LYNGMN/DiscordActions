"""YouTube API and Atom RSS source boundaries with stable source ordering."""

import html
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional, Sequence, Set, Tuple
from urllib.parse import urlencode
from xml.etree import ElementTree

import requests


VideoSourceItem = Tuple[str, Dict]
RSS_TIMEOUT = (5.0, 15.0)
ATOM = "http://www.w3.org/2005/Atom"
YOUTUBE = "http://www.youtube.com/xml/schemas/2015"
MEDIA = "http://search.yahoo.com/mrss/"


def fetch_rss_videos(
    mode: str,
    channel_id: Optional[str] = None,
    playlist_id: Optional[str] = None,
    get=requests.get,
    sleep=time.sleep,
):
    if mode == "channels":
        if not channel_id:
            raise ValueError("channel id is required")
        query = {"channel_id": channel_id}
    elif mode == "playlists":
        if not playlist_id:
            raise ValueError("playlist id is required")
        query = {"playlist_id": playlist_id}
    else:
        raise ValueError("YouTube RSS supports only channels and playlists")
    url = "https://www.youtube.com/feeds/videos.xml?{}".format(urlencode(query))
    content = _request_rss(url, get, sleep)
    return _parse_rss(content, mode)


def fetch_source_videos(
    youtube,
    mode: str,
    channel_id: Optional[str] = None,
    playlist_id: Optional[str] = None,
    search_keyword: Optional[str] = None,
    published_after: Optional[str] = None,
    known_video_ids: Optional[Set[str]] = None,
) -> List[VideoSourceItem]:
    if mode == "channels":
        uploads_playlist = _uploads_playlist_id(youtube, channel_id)
        items = _fetch_playlist_pages(
            youtube,
            uploads_playlist,
            stop_at_video_ids=known_video_ids or set(),
        )
    elif mode == "playlists":
        if not playlist_id:
            raise ValueError("playlist id is required")
        items = _fetch_playlist_pages(youtube, playlist_id)
    elif mode == "search":
        items = _fetch_search_pages(
            youtube,
            search_keyword=search_keyword,
            published_after=published_after,
        )
    else:
        raise ValueError("invalid YouTube mode")
    return _deduplicate(items)


def fetch_video_details(youtube, video_ids: Sequence[str]) -> List[Dict]:
    details = []
    for offset in range(0, len(video_ids), 50):
        batch = list(video_ids[offset : offset + 50])
        if not batch:
            continue
        response = youtube.videos().list(
            part="snippet,contentDetails,liveStreamingDetails",
            id=",".join(batch),
        ).execute()
        details.extend(response.get("items", []))
    return details


def _uploads_playlist_id(youtube, channel_id: Optional[str]) -> str:
    if not channel_id:
        raise ValueError("channel id is required")
    response = youtube.channels().list(
        part="contentDetails",
        id=channel_id,
    ).execute()
    try:
        return response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    except (IndexError, KeyError, TypeError):
        raise ValueError("channel uploads playlist was not found") from None


def _fetch_playlist_pages(
    youtube,
    playlist_id: str,
    stop_at_video_ids: Optional[Set[str]] = None,
) -> List[VideoSourceItem]:
    result = []
    page_token = None
    while True:
        response = youtube.playlistItems().list(
            part="snippet",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=page_token,
        ).execute()
        for item in response.get("items", []):
            snippet = item.get("snippet") or {}
            video_id = (snippet.get("resourceId") or {}).get("videoId")
            if video_id:
                if stop_at_video_ids and video_id in stop_at_video_ids:
                    return result
                result.append((video_id, snippet))
        page_token = response.get("nextPageToken")
        if not page_token:
            return result


def _fetch_search_pages(
    youtube,
    search_keyword: Optional[str],
    published_after: Optional[str],
) -> List[VideoSourceItem]:
    if not search_keyword:
        raise ValueError("search keyword is required")
    result = []
    page_token = None
    while True:
        arguments = {
            "q": search_keyword,
            "order": "date",
            "type": "video",
            "part": "snippet,id",
            "maxResults": 50,
            "pageToken": page_token,
        }
        if published_after:
            arguments["publishedAfter"] = published_after
        response = youtube.search().list(**arguments).execute()
        for item in response.get("items", []):
            video_id = (item.get("id") or {}).get("videoId")
            if video_id:
                result.append((video_id, item.get("snippet") or {}))
        page_token = response.get("nextPageToken")
        if not page_token:
            return result


def _deduplicate(items: Sequence[VideoSourceItem]) -> List[VideoSourceItem]:
    seen = set()
    unique = []
    for video_id, snippet in items:
        if video_id in seen:
            continue
        seen.add(video_id)
        unique.append((video_id, snippet))
    return unique


def _request_rss(url: str, get, sleep) -> bytes:
    for attempt in range(2):
        try:
            response = get(url, timeout=RSS_TIMEOUT)
        except requests.RequestException:
            if attempt == 0:
                sleep(2.0)
                continue
            raise
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code == 429 and attempt == 0:
            sleep(_retry_after_seconds(getattr(response, "headers", {})))
            continue
        if status_code >= 500 and attempt == 0:
            sleep(2.0)
            continue
        response.raise_for_status()
        content = getattr(response, "content", b"")
        if not isinstance(content, bytes) or not content:
            raise ValueError("invalid YouTube RSS feed")
        return content
    raise RuntimeError("YouTube RSS retry exhausted")


def _parse_rss(content: bytes, mode: str):
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        raise ValueError("invalid YouTube RSS feed") from None
    title = _element_text(root.find("{{{}}}title".format(ATOM)))
    owner_title = _element_text(
        root.find("{{{0}}}author/{{{0}}}name".format(ATOM))
    )
    if not title or not owner_title:
        raise ValueError("invalid YouTube RSS feed")

    items = []
    seen = set()
    for entry in root.findall("{{{}}}entry".format(ATOM)):
        video_id = _element_text(entry.find("{{{}}}videoId".format(YOUTUBE)))
        channel_id = _element_text(entry.find("{{{}}}channelId".format(YOUTUBE)))
        video_title = _element_text(entry.find("{{{}}}title".format(ATOM)))
        published_at = _element_text(entry.find("{{{}}}published".format(ATOM)))
        channel_title = _element_text(
            entry.find("{{{0}}}author/{{{0}}}name".format(ATOM))
        )
        description = _element_text(
            entry.find("{{{0}}}group/{{{0}}}description".format(MEDIA))
        )
        thumbnail = entry.find(
            "{{{0}}}group/{{{0}}}thumbnail".format(MEDIA)
        )
        thumbnail_url = (
            thumbnail.get("url", "").strip() if thumbnail is not None else ""
        )
        required = (
            video_id,
            channel_id,
            video_title,
            published_at,
            channel_title,
            thumbnail_url,
        )
        if not all(required):
            raise ValueError("invalid YouTube RSS item")
        if video_id in seen:
            continue
        seen.add(video_id)
        items.append(
            {
                "published_at": published_at,
                "channel_title": html.unescape(channel_title),
                "channel_id": channel_id,
                "title": html.unescape(video_title),
                "video_id": video_id,
                "video_url": "https://youtu.be/{}".format(video_id),
                "description": html.unescape(description),
                "category_id": "",
                "category_name": "",
                "duration": "",
                "thumbnail_url": thumbnail_url,
                "tags": "",
                "live_broadcast_content": "",
                "scheduled_start_time": "",
                "caption": "",
                "source": "rss:{}".format(mode),
            }
        )
    return items, {"title": title, "owner_title": owner_title}


def _element_text(element) -> str:
    if element is None or not isinstance(element.text, str):
        return ""
    return element.text.strip()


def _retry_after_seconds(headers) -> float:
    try:
        raw_value = headers.get("Retry-After", "1")
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            retry_at = parsedate_to_datetime(str(raw_value))
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            value = (retry_at - datetime.now(timezone.utc)).total_seconds()
    except (AttributeError, TypeError, ValueError, OverflowError):
        return 1.0
    return max(0.0, min(value, 60.0))
