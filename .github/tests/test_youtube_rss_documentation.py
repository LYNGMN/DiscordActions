import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
README_EN = ROOT / "README.md"
README_KO = ROOT / "README_KR.md"

CHANNEL_PAGE = "https://www.youtube.com/channel/UCtKtCiaWRz-d3EZn2xd1mdA"
CHANNEL_FEED = (
    "https://www.youtube.com/feeds/videos.xml?"
    "channel_id=UCtKtCiaWRz-d3EZn2xd1mdA"
)
PLAYLIST_PAGE = (
    "https://www.youtube.com/playlist?"
    "list=PL7zZDePsdYwPNu51o8b9MKQ_eGk520SFt"
)
PLAYLIST_FEED = (
    "https://www.youtube.com/feeds/videos.xml?"
    "playlist_id=PL7zZDePsdYwPNu51o8b9MKQ_eGk520SFt"
)


class YouTubeRssDocumentationTests(unittest.TestCase):
    def readmes(self):
        return (
            README_EN.read_text(encoding="utf-8"),
            README_KO.read_text(encoding="utf-8"),
        )

    def test_rescene_channel_and_playlist_examples_include_source_and_feed_urls(self):
        for source in self.readmes():
            with self.subTest(readme="ko" if "빠른 설정" in source else "en"):
                self.assertIn(CHANNEL_PAGE, source)
                self.assertIn(CHANNEL_FEED, source)
                self.assertIn(PLAYLIST_PAGE, source)
                self.assertIn(PLAYLIST_FEED, source)

    def test_examples_name_the_exact_repository_settings(self):
        for source in self.readmes():
            with self.subTest(readme="ko" if "빠른 설정" in source else "en"):
                self.assertIn("`YOUTUBE_SOURCE=rss`", source)
                self.assertIn("`YOUTUBE_MODE=channels`", source)
                self.assertIn("`YOUTUBE_MODE=playlists`", source)
                self.assertIn("`YOUTUBE_CHANNEL_ID=UCtKtCiaWRz-d3EZn2xd1mdA`", source)
                self.assertIn(
                    "`YOUTUBE_PLAYLIST_ID=PL7zZDePsdYwPNu51o8b9MKQ_eGk520SFt`",
                    source,
                )
                self.assertIn("`YOUTUBE_PLAYLIST_LAYOUT=curated`", source)

    def test_examples_show_the_actual_rescene_message_headers(self):
        english, korean = self.readmes()

        self.assertIn("`RESCENE - YouTube`", english)
        self.assertIn(
            "`📃 RESCENE Archive - YouTube Playlist by. RESCENE`",
            english,
        )
        self.assertIn("`RESCENE - YouTube`", korean)
        self.assertIn(
            "`📃 RESCENE Archive - YouTube 재생목록 by. RESCENE`",
            korean,
        )


if __name__ == "__main__":
    unittest.main()
