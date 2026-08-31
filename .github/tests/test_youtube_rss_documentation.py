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
GOOGLE_NEWS_ICON = (
    "https://discordactions.github.io/logo/media/original/news/googlenews.png"
)
YOUTUBE_ICON = (
    "https://discordactions.github.io/logo/media/original/youtube/"
    "youtube_social_circle_red.png"
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

    def test_playlist_examples_link_the_video_channel(self):
        english, korean = self.readmes()
        channel_url = (
            "https://www.youtube.com/channel/UCWpY0eSJtyO-qNAPbKFRSSg"
        )

        self.assertIn(
            "👤 Channel: [안녕하세요원이입니다잘부탁드립니다]({})".format(
                channel_url
            ),
            english,
        )
        self.assertIn(
            "👤 채널명: [안녕하세요원이입니다잘부탁드립니다]({})".format(
                channel_url
            ),
            korean,
        )

    def test_rss_and_api_field_sources_are_explicit(self):
        for source in self.readmes():
            with self.subTest(readme="ko" if "빠른 설정" in source else "en"):
                self.assertIn("contentDetails.duration", source)
                self.assertIn("snippet.categoryId", source)
                self.assertIn("videoCategories.list", source)
                self.assertIn(
                    "https://developers.google.com/youtube/v3/guides/push_notifications",
                    source,
                )
                self.assertNotIn("view-source:", source)

    def test_detail_embed_labels_follow_display_language_without_translating_values(self):
        english, korean = self.readmes()

        self.assertIn(
            "Across primary messages and API detail embeds, fixed field names "
            "and link labels follow "
            "`DISPLAY_LANGUAGE`.",
            english,
        )
        self.assertIn(
            "Video titles, channel names, descriptions, and tags are not "
            "translated by the formatter",
            english,
        )
        self.assertIn("Detail embeds remain available only in API mode.", english)

        self.assertIn(
            "일반 메시지와 API 상세 임베드의 고정 항목명 및 링크 문구는 "
            "모두 `DISPLAY_LANGUAGE`를 따릅니다.",
            korean,
        )
        self.assertIn(
            "영상 제목, 채널명, 설명, 태그는 메시지 작성 과정에서 "
            "번역하지 않으며",
            korean,
        )
        self.assertIn("상세 임베드는 API 방식에서만 사용할 수 있습니다.", korean)

    def test_branding_explains_discord_bot_identity_and_links_icons(self):
        english, korean = self.readmes()

        self.assertIn("Discord bot shown as the author", english)
        self.assertIn(
            "[Google News icon]({})".format(GOOGLE_NEWS_ICON),
            english,
        )
        self.assertIn("[YouTube icon]({})".format(YOUTUBE_ICON), english)

        self.assertIn("Discord 메시지 작성자로 표시되는 Google News 봇", korean)
        self.assertIn(
            "[Google News 아이콘]({})".format(GOOGLE_NEWS_ICON),
            korean,
        )
        self.assertIn("[YouTube 아이콘]({})".format(YOUTUBE_ICON), korean)


if __name__ == "__main__":
    unittest.main()
