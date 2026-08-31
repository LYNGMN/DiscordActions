"""YouTube API pagination boundary with stable source ordering."""

from typing import Dict, List, Optional, Sequence, Set, Tuple


VideoSourceItem = Tuple[str, Dict]


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
