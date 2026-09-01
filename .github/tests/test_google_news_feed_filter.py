import importlib
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def load_module():
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        for name in ("google_news_feed_filter", "feed_filters"):
            sys.modules.pop(name, None)
        return importlib.import_module("google_news_feed_filter")
    finally:
        sys.path.pop(0)


class GoogleNewsFeedFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_service_keyword_title_mode_rejects_related_only_match(self):
        compiled = self.module.compile_google_news_feed_filter(
            service_keyword="아이유",
            service_aliases="IU",
            service_mode="title",
            country_code="KR",
            display_language="ko",
        )
        description = '<a href="https://example.com">아이유 새 앨범</a>'

        result = compiled.matches(
            "Tue, 01 Sep 2026 00:00:00 GMT",
            "이솔이 비키니 화제 - 네이트",
            description,
        )

        self.assertFalse(result.matched)
        self.assertEqual("service_keyword", result.reason)

    def test_common_description_scope_reads_related_titles_only(self):
        compiled = self.module.compile_google_news_feed_filter(
            common_keyword="아이유",
            common_scope="title_or_description",
            country_code="KR",
            display_language="ko",
        )
        description = """
          <a href="https://example.com/iu">전혀 다른 기사</a>
          <font>아이유 뉴스</font>
          <li><a href="https://example.com/related">아이유 새 앨범</a></li>
        """

        self.assertTrue(
            compiled.matches(
                "Tue, 01 Sep 2026 00:00:00 GMT",
                "다른 제목 - 언론사",
                description,
            ).matched
        )

    def test_common_boolean_terms_must_match_the_same_related_headline(self):
        compiled = self.module.compile_google_news_feed_filter(
            common_keyword="AI AND chip",
            common_scope="title_or_description",
            country_code="KR",
            display_language="en",
        )
        split_across_headlines = """
          <a href="https://example.com/ai">AI industry update</a>
          <a href="https://example.com/chip">Chip manufacturing update</a>
        """
        same_headline = """
          <a href="https://example.com/ai-chip">AI chip industry update</a>
        """

        self.assertFalse(
            compiled.matches(
                "Tue, 01 Sep 2026 00:00:00 GMT",
                "Unrelated headline - Publisher",
                split_across_headlines,
            ).matched
        )
        self.assertTrue(
            compiled.matches(
                "Tue, 01 Sep 2026 00:00:00 GMT",
                "Unrelated headline - Publisher",
                same_headline,
            ).matched
        )

    def test_title_only_negative_filter_ignores_related_headlines(self):
        compiled = self.module.compile_google_news_feed_filter(
            common_keyword="NOT 운세",
            common_scope="title",
            country_code="KR",
            display_language="ko",
        )
        related_fortune = (
            '<li><a href="https://example.com/fortune">오늘의 운세</a></li>'
        )

        self.assertFalse(
            compiled.matches(
                "Tue, 01 Sep 2026 00:00:00 GMT",
                "오늘의 운세 - 언론사",
                "",
            ).matched
        )
        self.assertTrue(
            compiled.matches(
                "Tue, 01 Sep 2026 00:00:00 GMT",
                "연예계 소식 - 언론사",
                "",
            ).matched
        )
        self.assertTrue(
            compiled.matches(
                "Tue, 01 Sep 2026 00:00:00 GMT",
                "연예계 소식 - 언론사",
                related_fortune,
            ).matched
        )

    def test_common_date_keyword_and_legacy_filter_all_must_match(self):
        compiled = self.module.compile_google_news_feed_filter(
            common_date="rolling:7d",
            common_keyword="아이유 | IU",
            common_scope="title",
            legacy_keyword="-루머",
            explicit_timezone="Asia/Seoul",
            display_language="ko",
            now=datetime(2026, 9, 1, 3, 0, tzinfo=timezone.utc),
        )

        self.assertTrue(
            compiled.matches(
                "Mon, 31 Aug 2026 03:00:00 GMT",
                "아이유 콘서트 - 언론사",
                "",
            ).matched
        )
        self.assertEqual(
            "legacy_keyword",
            compiled.matches(
                "Mon, 31 Aug 2026 03:00:00 GMT",
                "아이유 콘서트 루머 - 언론사",
                "",
            ).reason,
        )
        self.assertEqual(
            "date",
            compiled.matches(
                "Thu, 20 Aug 2026 03:00:00 GMT",
                "아이유 콘서트 - 언론사",
                "",
            ).reason,
        )

    def test_filter_fingerprint_changes_for_each_layer(self):
        base = self.module.compile_google_news_feed_filter(
            service_keyword="아이유",
            common_date="calendar:7d",
            country_code="KR",
            display_language="ko",
        )
        variants = (
            self.module.compile_google_news_feed_filter(
                service_keyword="IU",
                common_date="calendar:7d",
                country_code="KR",
                display_language="ko",
            ),
            self.module.compile_google_news_feed_filter(
                service_keyword="아이유",
                common_date="calendar:1d",
                country_code="KR",
                display_language="ko",
            ),
            self.module.compile_google_news_feed_filter(
                service_keyword="아이유",
                common_date="calendar:7d",
                legacy_keyword="-루머",
                country_code="KR",
                display_language="ko",
            ),
        )
        for variant in variants:
            self.assertNotEqual(base.fingerprint, variant.fingerprint)

    def test_country_selects_calendar_timezone_without_language_inference(self):
        japan = self.module.compile_google_news_feed_filter(
            common_date="calendar:1d",
            country_code="JP",
            display_language="en",
            now=datetime(2026, 9, 1, 3, 0, tzinfo=timezone.utc),
        )
        no_country = self.module.compile_google_news_feed_filter(
            common_date="calendar:1d",
            display_language="ja",
            now=datetime(2026, 9, 1, 3, 0, tzinfo=timezone.utc),
        )

        self.assertEqual("Asia/Tokyo", japan.timezone_name)
        self.assertEqual("UTC", no_country.timezone_name)

    def test_invalid_service_keyword_mode_fails_during_preflight(self):
        with self.assertRaisesRegex(ValueError, "service keyword mode"):
            self.module.compile_google_news_feed_filter(
                service_keyword="news",
                service_mode="description",
                display_language="en",
            )


if __name__ == "__main__":
    unittest.main()
