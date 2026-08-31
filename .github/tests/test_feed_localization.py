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
        for language, expected in expected_duration_labels.items():
            with self.subTest(language=language):
                labels = self.localization.labels_for(language)
                self.assertEqual(expected, labels["duration"])
                for key in (
                    "published_date",
                    "category",
                    "thumbnail",
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

    def test_rss_message_omits_unavailable_duration_and_category(self):
        message = self.messages.build_youtube_message(
            self.video,
            source_type="channels",
            display_language="en",
            timezone_name="UTC",
            include_api_details=False,
        )

        self.assertNotIn("Duration:", message)
        self.assertNotIn("Category:", message)
        self.assertIn("📅 Published: `June 29, 2026`", message)
        self.assertIn(
            "🖼️ [Thumbnail](https://i.ytimg.com/vi/qdq9GpInFLY/hqdefault.jpg)",
            message,
        )

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
