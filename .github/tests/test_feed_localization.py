import importlib
import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def load_module(name):
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        sys.modules.pop(name, None)
        return importlib.import_module(name)
    finally:
        sys.path.pop(0)


class FeedLocalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.localization = load_module("feed_localization")
        cls.messages = load_module("youtube_messages")

    def setUp(self):
        self.video = {
            "channel_title": "BBC News 코리아",
            "channel_id": "UCWpY0eSJtyO-qNAPbKFRSSg",
            "title": "2030 청년들 올림픽 공원 시위를 말하다- BBC News 코리아",
            "video_id": "dv74X0spCm0",
            "video_url": "https://youtu.be/dv74X0spCm0",
            "published_at": "2026-06-29T03:00:00Z",
            "duration": "07:13",
            "category_name": "뉴스 및 정치",
            "thumbnail_url": "https://i.ytimg.com/vi/qdq9GpInFLY/hqdefault.jpg",
        }

    def test_supported_languages_and_legacy_names_are_normalized(self):
        self.assertEqual(
            {"ko", "en", "ja", "zh-CN", "zh-TW", "es", "pt-BR", "fr", "de", "id"},
            set(self.localization.SUPPORTED_LANGUAGES),
        )
        self.assertEqual("ko", self.localization.normalize_display_language("Korean"))
        self.assertEqual("en", self.localization.normalize_display_language("English"))
        self.assertEqual("pt-BR", self.localization.normalize_display_language("pt-br"))
        self.assertEqual(
            "ja",
            self.localization.resolve_display_language("", "ja-JP", "JP"),
        )
        self.assertEqual(
            "ko",
            self.localization.resolve_display_language("", "", "KR"),
        )
        self.assertEqual(
            "en",
            self.localization.resolve_display_language("", "unsupported", "US"),
        )
        with self.assertRaisesRegex(ValueError, "unsupported display language"):
            self.localization.normalize_display_language("xx")

    def test_dates_use_selected_language_and_timezone(self):
        published = "2026-06-28T15:30:00Z"

        self.assertEqual(
            "2026년 6월 29일",
            self.localization.format_feed_date(published, "ko", "Asia/Seoul"),
        )
        self.assertEqual(
            "June 29, 2026",
            self.localization.format_feed_date(published, "en", "Asia/Tokyo"),
        )
        self.assertEqual(
            "2026年6月29日",
            self.localization.format_feed_date(published, "ja", "Asia/Tokyo"),
        )

    def test_every_language_has_all_required_labels(self):
        expected_duration_labels = {
            "ko": "재생시간",
            "en": "Duration",
            "ja": "再生時間",
            "zh-CN": "时长",
            "zh-TW": "片長",
            "es": "Duración",
            "pt-BR": "Duração",
            "fr": "Durée",
            "de": "Dauer",
            "id": "Durasi",
        }
        expected_channel_labels = {
            "ko": "채널명",
            "en": "Channel",
            "ja": "チャンネル",
            "zh-CN": "频道",
            "zh-TW": "頻道",
            "es": "Canal",
            "pt-BR": "Canal",
            "fr": "Chaîne",
            "de": "Kanal",
            "id": "Saluran",
        }
        for language, expected in expected_duration_labels.items():
            with self.subTest(language=language):
                labels = self.localization.labels_for(language)
                self.assertEqual(expected, labels["duration"])
                self.assertEqual(expected_channel_labels[language], labels["channel"])
                for key in (
                    "video_id",
                    "tags",
                    "published_date",
                    "category",
                    "subtitle",
                    "thumbnail",
                    "play_video",
                    "download",
                    "embed",
                    "not_available",
                    "playlist",
                    "search_results",
                    "google_news",
                    "top_news",
                    "topics",
                ):
                    self.assertTrue(labels[key])

    def test_google_news_country_and_datetime_are_localized(self):
        published = "2026-08-31T10:11:06Z"

        self.assertEqual(
            "대한민국",
            self.localization.localized_country_name("KR", "ko"),
        )
        self.assertEqual(
            "Japan",
            self.localization.localized_country_name("JP", "en"),
        )
        self.assertIn(
            "2026",
            self.localization.format_feed_datetime(
                published,
                "ja",
                "Asia/Tokyo",
            ),
        )

    def test_google_news_datetime_uses_country_specific_formats(self):
        cases = (
            (
                "2026-08-31T08:41:00Z",
                "KR",
                "Asia/Seoul",
                "ko",
                "2026년 08월 31일 오후 05:41:00 (KST)",
            ),
            (
                "2026-09-01T04:51:11Z",
                "JP",
                "Asia/Tokyo",
                "ja",
                "2026年09月01日 13:51:11 (JST)",
            ),
            (
                "2026-09-01T01:50:00Z",
                "CN",
                "Asia/Shanghai",
                "zh-CN",
                "2026年09月01日 09:50:00 (CST)",
            ),
            (
                "2026-08-31T21:41:00Z",
                "US",
                "America/New_York",
                "en",
                "August 31, 2026, 05:41:00 PM (EDT)",
            ),
        )

        for value, country, timezone_name, language, expected in cases:
            with self.subTest(country=country):
                actual = self.localization.format_google_news_datetime(
                    value,
                    country,
                    timezone_name,
                    language,
                )
                self.assertEqual(expected, actual)
                self.assertNotIn("\n", actual)

    def test_google_news_datetime_handles_korean_periods_and_us_dst(self):
        self.assertEqual(
            "2026년 01월 02일 오전 12:03:04 (KST)",
            self.localization.format_google_news_datetime(
                "2026-01-01T15:03:04Z",
                "KR",
                "Asia/Seoul",
                "ko",
            ),
        )
        self.assertEqual(
            "2026년 01월 02일 오후 12:03:04 (KST)",
            self.localization.format_google_news_datetime(
                "2026-01-02T03:03:04Z",
                "KR",
                "Asia/Seoul",
                "ko",
            ),
        )
        self.assertEqual(
            "January 02, 2026, 05:03:04 AM (EST)",
            self.localization.format_google_news_datetime(
                "2026-01-02T10:03:04Z",
                "US",
                "America/New_York",
                "en",
            ),
        )
        self.assertEqual(
            "July 02, 2026, 06:03:04 AM (EDT)",
            self.localization.format_google_news_datetime(
                "2026-07-02T10:03:04Z",
                "US",
                "America/New_York",
                "en",
            ),
        )

    def test_google_news_datetime_falls_back_without_changing_general_dates(self):
        published = "2026-06-28T15:30:00Z"

        self.assertEqual(
            self.localization.format_feed_datetime(
                published,
                "fr",
                "Europe/Paris",
            ),
            self.localization.format_google_news_datetime(
                published,
                "FR",
                "Europe/Paris",
                "fr",
            ),
        )
        self.assertEqual(
            "2026년 6월 29일",
            self.localization.format_feed_date(
                published,
                "ko",
                "Asia/Seoul",
            ),
        )

    def test_korean_api_channel_message_matches_requested_markdown(self):
        message = self.messages.build_youtube_message(
            self.video,
            source_type="channels",
            display_language="ko",
            timezone_name="Asia/Seoul",
            include_api_details=True,
        )

        self.assertEqual(
            "`BBC News 코리아 - YouTube`\n"
            "**2030 청년들 올림픽 공원 시위를 말하다- BBC News 코리아**\n"
            "https://youtu.be/dv74X0spCm0\n\n"
            "⏳ 재생시간: `07:13`\n"
            "📅 게시일자: `2026년 6월 29일`\n"
            "📁 카테고리: `뉴스 및 정치`\n"
            "🖼️ [썸네일](https://i.ytimg.com/vi/qdq9GpInFLY/hqdefault.jpg)",
            message,
        )

    def test_playlist_layouts_have_a_blank_line_after_the_first_line(self):
        playlist = {
            "title": "미나미의 뿌리를 찾아서",
            "owner_title": "안녕하세요원이입니다잘부탁드립니다",
        }
        channel_message = self.messages.build_youtube_message(
            self.video,
            source_type="playlists",
            display_language="ko",
            timezone_name="Asia/Seoul",
            include_api_details=True,
            playlist=playlist,
            playlist_layout="channel",
        )
        curated_message = self.messages.build_youtube_message(
            self.video,
            source_type="playlists",
            display_language="ko",
            timezone_name="Asia/Seoul",
            include_api_details=True,
            playlist=playlist,
            playlist_layout="curated",
        )

        self.assertTrue(
            channel_message.startswith(
                "`📃 미나미의 뿌리를 찾아서 by. BBC News 코리아 - YouTube 재생목록`\n\n"
                "`BBC News 코리아 - YouTube`"
            )
        )
        self.assertTrue(
            curated_message.startswith(
                "`📃 미나미의 뿌리를 찾아서 - YouTube 재생목록 by. "
                "안녕하세요원이입니다잘부탁드립니다`\n\n"
                "`BBC News 코리아 - YouTube`"
            )
        )

    def test_auto_playlist_layout_detects_single_and_mixed_channels(self):
        self.assertEqual(
            "channel",
            self.messages.resolve_playlist_layout("auto", ["same", "same"]),
        )
        self.assertEqual(
            "curated",
            self.messages.resolve_playlist_layout("auto", ["first", "second"]),
        )
        self.assertEqual(
            "curated",
            self.messages.resolve_playlist_layout("curated", ["same"]),
        )
        with self.assertRaisesRegex(ValueError, "invalid YouTube playlist layout"):
            self.messages.resolve_playlist_layout("unknown", ["same"])

    def test_rss_channel_message_contains_only_available_lower_metadata(self):
        message = self.messages.build_youtube_message(
            self.video,
            source_type="channels",
            display_language="en",
            timezone_name="UTC",
            include_api_details=False,
        )

        self.assertEqual(
            "`BBC News 코리아 - YouTube`\n"
            "**2030 청년들 올림픽 공원 시위를 말하다- BBC News 코리아**\n"
            "https://youtu.be/dv74X0spCm0\n\n"
            "📅 Published: `June 29, 2026`\n"
            "🖼️ [Thumbnail](https://i.ytimg.com/vi/qdq9GpInFLY/hqdefault.jpg)",
            message,
        )

    def test_rss_playlist_message_links_channel_without_api_only_fields(self):
        message = self.messages.build_youtube_message(
            self.video,
            source_type="playlists",
            display_language="en",
            timezone_name="UTC",
            include_api_details=False,
            playlist={
                "title": "RESCENE Archive",
                "owner_title": "RESCENE",
            },
            playlist_layout="curated",
        )

        self.assertEqual(
            "`📃 RESCENE Archive - YouTube Playlist by. RESCENE`\n\n"
            "`BBC News 코리아 - YouTube`\n"
            "**2030 청년들 올림픽 공원 시위를 말하다- BBC News 코리아**\n"
            "https://youtu.be/dv74X0spCm0\n\n"
            "👤 Channel: [BBC News 코리아]"
            "(https://www.youtube.com/channel/UCWpY0eSJtyO-qNAPbKFRSSg)\n"
            "📅 Published: `June 29, 2026`\n"
            "🖼️ [Thumbnail](https://i.ytimg.com/vi/qdq9GpInFLY/hqdefault.jpg)",
            message,
        )
        self.assertNotIn("Duration:", message)
        self.assertNotIn("Category:", message)
        self.assertNotIn("feeds/videos.xml", message)

    def test_search_header_is_localized_without_translating_titles(self):
        message = self.messages.build_youtube_message(
            self.video,
            source_type="search",
            display_language="ja",
            timezone_name="Asia/Tokyo",
            include_api_details=True,
            search_keyword="BBC",
        )

        self.assertTrue(message.startswith("`🔎 BBC - YouTube 検索結果`\n\n"))
        self.assertIn("`BBC News 코리아 - YouTube`", message)
        self.assertIn("**2030 청년들", message)


if __name__ == "__main__":
    unittest.main()
