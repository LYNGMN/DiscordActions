import importlib
import sys
import unittest
from pathlib import Path

import requests


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def load_module():
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        sys.modules.pop("youtube_video_source", None)
        return importlib.import_module("youtube_video_source")
    finally:
        sys.path.pop(0)


class Request:
    def __init__(self, response):
        self.response = response

    def execute(self):
        return self.response


class Resource:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("unexpected API request")
        return Request(self.responses.pop(0))


class YouTubeClient:
    def __init__(self, channels=(), playlists=(), searches=(), videos=()):
        self.channels_resource = Resource(channels)
        self.playlist_resource = Resource(playlists)
        self.search_resource = Resource(searches)
        self.video_resource = Resource(videos)

    def channels(self):
        return self.channels_resource

    def playlistItems(self):
        return self.playlist_resource

    def search(self):
        return self.search_resource

    def videos(self):
        return self.video_resource


def playlist_page(start, count, next_token=None):
    result = {
        "items": [
            {
                "snippet": {
                    "position": index,
                    "resourceId": {"videoId": "video-{}".format(index)},
                }
            }
            for index in range(start, start + count)
        ]
    }
    if next_token:
        result["nextPageToken"] = next_token
    return result


def rss_feed(entries, title="Feed title", owner="Feed owner"):
    return """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom"
          xmlns:yt="http://www.youtube.com/xml/schemas/2015"
          xmlns:media="http://search.yahoo.com/mrss/">
      <title>{}</title>
      <author><name>{}</name></author>
      {}
    </feed>""".format(title, owner, "".join(entries)).encode("utf-8")


def rss_entry(video_id, channel_title, position):
    return """
      <entry>
        <yt:videoId>{video_id}</yt:videoId>
        <yt:channelId>channel-{position}</yt:channelId>
        <title>Video {position}</title>
        <link rel="alternate" href="https://www.youtube.com/watch?v={video_id}"/>
        <author><name>{channel_title}</name></author>
        <published>2026-08-{day:02d}T12:00:00+00:00</published>
        <media:group>
          <media:description>Description {position}</media:description>
          <media:thumbnail url="https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"/>
        </media:group>
      </entry>
    """.format(
        video_id=video_id,
        channel_title=channel_title,
        position=position,
        day=31 - position,
    )


class RssResponse:
    def __init__(self, content=b"", status_code=200, headers=None):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("HTTP {}".format(self.status_code))

    @property
    def text(self):
        raise AssertionError("RSS response text must not be logged")


class SequenceGet:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class YouTubeVideoSourceTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_channel_uses_uploads_playlist_and_reads_every_page(self):
        client = YouTubeClient(
            channels=[
                {
                    "items": [
                        {
                            "contentDetails": {
                                "relatedPlaylists": {"uploads": "uploads-id"}
                            }
                        }
                    ]
                }
            ],
            playlists=[
                playlist_page(0, 50, "page-2"),
                playlist_page(50, 50, "page-3"),
                playlist_page(100, 20),
            ],
        )

        videos = self.module.fetch_source_videos(
            client, "channels", channel_id="channel-id"
        )

        self.assertEqual(120, len(videos))
        self.assertEqual("video-0", videos[0][0])
        self.assertEqual("video-119", videos[-1][0])
        self.assertEqual("uploads-id", client.playlist_resource.calls[0]["playlistId"])
        self.assertEqual([None, "page-2", "page-3"], [
            call.get("pageToken") for call in client.playlist_resource.calls
        ])
        self.assertEqual([], client.search_resource.calls)

    def test_channel_stops_at_first_known_upload_boundary(self):
        client = YouTubeClient(
            channels=[
                {
                    "items": [
                        {
                            "contentDetails": {
                                "relatedPlaylists": {"uploads": "uploads-id"}
                            }
                        }
                    ]
                }
            ],
            playlists=[
                playlist_page(0, 50, "page-2"),
                playlist_page(50, 50, "page-3"),
            ],
        )

        videos = self.module.fetch_source_videos(
            client,
            "channels",
            channel_id="channel-id",
            known_video_ids={"video-60"},
        )

        self.assertEqual(60, len(videos))
        self.assertEqual("video-59", videos[-1][0])
        self.assertEqual(2, len(client.playlist_resource.calls))

    def test_playlist_reads_all_pages_and_preserves_api_position(self):
        client = YouTubeClient(
            playlists=[playlist_page(0, 2, "next"), playlist_page(2, 1)]
        )

        videos = self.module.fetch_source_videos(
            client, "playlists", playlist_id="playlist-id"
        )

        self.assertEqual(["video-0", "video-1", "video-2"], [row[0] for row in videos])

    def test_search_reads_all_pages_and_applies_overlap_checkpoint(self):
        client = YouTubeClient(
            searches=[
                {
                    "items": [
                        {"id": {"videoId": "new"}, "snippet": {"title": "new"}}
                    ],
                    "nextPageToken": "next",
                },
                {
                    "items": [
                        {"id": {"videoId": "old"}, "snippet": {"title": "old"}}
                    ]
                },
            ]
        )

        videos = self.module.fetch_source_videos(
            client,
            "search",
            search_keyword="keyword",
            published_after="2026-08-01T00:00:00Z",
        )

        self.assertEqual(["new", "old"], [row[0] for row in videos])
        self.assertEqual(2, len(client.search_resource.calls))
        self.assertEqual(
            "2026-08-01T00:00:00Z",
            client.search_resource.calls[0]["publishedAfter"],
        )

    def test_video_details_are_fetched_in_batches_of_fifty(self):
        client = YouTubeClient(
            videos=[
                {"items": [{"id": "batch-1"}]},
                {"items": [{"id": "batch-2"}]},
                {"items": [{"id": "batch-3"}]},
            ]
        )

        result = self.module.fetch_video_details(
            client, ["video-{}".format(index) for index in range(120)]
        )

        self.assertEqual(["batch-1", "batch-2", "batch-3"], [item["id"] for item in result])
        self.assertEqual([50, 50, 20], [len(call["id"].split(",")) for call in client.video_resource.calls])

    def test_duplicate_video_ids_are_removed_without_reordering(self):
        first = playlist_page(0, 2, "next")
        duplicate = playlist_page(1, 2)
        client = YouTubeClient(playlists=[first, duplicate])

        videos = self.module.fetch_source_videos(
            client, "playlists", playlist_id="playlist-id"
        )

        self.assertEqual(["video-0", "video-1", "video-2"], [row[0] for row in videos])

    def test_channel_rss_parses_current_feed_without_an_api_key(self):
        payload = rss_feed(
            [rss_entry("newest", "BBC News 코리아", 0), rss_entry("older", "BBC News 코리아", 1)],
            title="BBC News 코리아",
            owner="BBC News 코리아",
        )
        get = SequenceGet([RssResponse(payload)])

        items, metadata = self.module.fetch_rss_videos(
            "channels",
            channel_id="UC-channel",
            get=get,
        )

        self.assertEqual(["newest", "older"], [item["video_id"] for item in items])
        self.assertEqual("BBC News 코리아", metadata["title"])
        self.assertEqual("BBC News 코리아", metadata["owner_title"])
        self.assertEqual("rss:channels", items[0]["source"])
        self.assertEqual("", items[0]["duration"])
        self.assertEqual("", items[0]["category_name"])
        self.assertEqual((5.0, 15.0), get.calls[0][1]["timeout"])
        self.assertIn("channel_id=UC-channel", get.calls[0][0])

    def test_playlist_rss_preserves_mixed_channel_feed_positions(self):
        payload = rss_feed(
            [rss_entry("first", "Channel A", 0), rss_entry("second", "Channel B", 1)],
            title="Top videos",
            owner="Playlist owner",
        )

        items, metadata = self.module.fetch_rss_videos(
            "playlists",
            playlist_id="PL-playlist",
            get=SequenceGet([RssResponse(payload)]),
        )

        self.assertEqual(["Channel A", "Channel B"], [item["channel_title"] for item in items])
        self.assertEqual("Top videos", metadata["title"])
        self.assertEqual("Playlist owner", metadata["owner_title"])

    def test_rss_rejects_search_mode_and_malformed_entries(self):
        with self.assertRaisesRegex(ValueError, "RSS supports only"):
            self.module.fetch_rss_videos("search", get=SequenceGet([]))

        malformed = rss_feed(["<entry><title>Missing fields</title></entry>"])
        with self.assertRaisesRegex(ValueError, "invalid YouTube RSS item"):
            self.module.fetch_rss_videos(
                "channels",
                channel_id="UC-channel",
                get=SequenceGet([RssResponse(malformed)]),
            )

    def test_rss_retries_transient_network_server_and_rate_limit_failures_once(self):
        payload = rss_feed([rss_entry("video", "Channel", 0)])
        cases = (
            ([requests.Timeout("temporary"), RssResponse(payload)], [2.0]),
            ([RssResponse(status_code=503), RssResponse(payload)], [2.0]),
            (
                [
                    RssResponse(status_code=429, headers={"Retry-After": "1.5"}),
                    RssResponse(payload),
                ],
                [1.5],
            ),
        )
        for outcomes, expected_sleeps in cases:
            with self.subTest(outcome=type(outcomes[0]).__name__):
                get = SequenceGet(outcomes)
                sleeps = []
                items, _metadata = self.module.fetch_rss_videos(
                    "channels",
                    channel_id="UC-channel",
                    get=get,
                    sleep=sleeps.append,
                )
                self.assertEqual(["video"], [item["video_id"] for item in items])
                self.assertEqual(expected_sleeps, sleeps)
                self.assertEqual(2, len(get.calls))

    def test_rss_retry_after_accepts_http_date_format(self):
        seconds = self.module._retry_after_seconds(
            {"Retry-After": "Thu, 01 Jan 2099 00:00:00 GMT"}
        )

        self.assertEqual(60.0, seconds)


if __name__ == "__main__":
    unittest.main()
