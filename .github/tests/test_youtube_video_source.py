import importlib
import sys
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
