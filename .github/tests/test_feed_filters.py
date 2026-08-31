import importlib
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pytz


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def load_module():
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        sys.modules.pop("feed_filters", None)
        return importlib.import_module("feed_filters")
    finally:
        sys.path.pop(0)


class FeedFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def compile(self, date_filter="", keyword_filter="", scope="title", now=None):
        return self.module.compile_feed_filter(
            date_filter=date_filter,
            keyword_filter=keyword_filter,
            keyword_scope=scope,
            timezone_name="Asia/Seoul",
            display_language="ko",
            now=now or datetime(2026, 9, 1, 12, 0, tzinfo=pytz.timezone("Asia/Seoul")),
        )

    def test_timezone_precedence_is_explicit_then_service_then_country_then_utc(self):
        self.assertEqual(
            "Europe/Paris",
            self.module.resolve_feed_timezone(
                explicit_timezone="Europe/Paris",
                service_timezone="Asia/Tokyo",
                country_code="KR",
            ),
        )
        self.assertEqual(
            "Asia/Tokyo",
            self.module.resolve_feed_timezone(
                service_timezone="Asia/Tokyo",
                country_code="KR",
            ),
        )
        self.assertEqual(
            "Asia/Seoul",
            self.module.resolve_feed_timezone(country_code="KR"),
        )
        self.assertEqual(
            "Asia/Tokyo",
            self.module.resolve_feed_timezone(country_code="JP"),
        )
        self.assertEqual("UTC", self.module.resolve_feed_timezone(country_code="ZZ"))

    def test_invalid_explicit_or_service_timezone_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "invalid feed timezone"):
            self.module.resolve_feed_timezone(explicit_timezone="Not/AZone")
        with self.assertRaisesRegex(ValueError, "invalid feed timezone"):
            self.module.resolve_feed_timezone(service_timezone="Not/AZone")

    def test_calendar_one_day_uses_local_midnight(self):
        compiled = self.compile(
            "calendar:1d",
            now=pytz.timezone("Asia/Seoul").localize(datetime(2026, 9, 1, 12, 0)),
        )

        self.assertTrue(compiled.matches("2026-08-31T15:00:00Z", "title", "").matched)
        self.assertFalse(compiled.matches("2026-08-31T14:59:59Z", "title", "").matched)

    def test_calendar_seven_days_includes_today_and_six_previous_dates(self):
        compiled = self.compile(
            "calendar:7d",
            now=pytz.timezone("Asia/Seoul").localize(datetime(2026, 9, 1, 12, 0)),
        )

        self.assertTrue(compiled.matches("2026-08-25T15:00:00Z", "title", "").matched)
        self.assertFalse(compiled.matches("2026-08-25T14:59:59Z", "title", "").matched)

    def test_calendar_month_clamps_month_end_and_leap_day(self):
        seoul = pytz.timezone("Asia/Seoul")
        march_2026 = self.compile(
            "calendar:1mo",
            now=seoul.localize(datetime(2026, 3, 31, 12, 0)),
        )
        march_2024 = self.compile(
            "calendar:1mo",
            now=seoul.localize(datetime(2024, 3, 31, 12, 0)),
        )

        self.assertTrue(march_2026.matches("2026-02-27T15:00:00Z", "title", "").matched)
        self.assertFalse(march_2026.matches("2026-02-27T14:59:59Z", "title", "").matched)
        self.assertTrue(march_2024.matches("2024-02-28T15:00:00Z", "title", "").matched)
        self.assertFalse(march_2024.matches("2024-02-28T14:59:59Z", "title", "").matched)

    def test_rolling_windows_use_exact_elapsed_time(self):
        now = datetime(2026, 9, 1, 3, 0, tzinfo=timezone.utc)
        cases = (
            ("rolling:24h", "2026-08-31T03:00:00Z", "2026-08-31T02:59:59Z"),
            ("rolling:168h", "2026-08-25T03:00:00Z", "2026-08-25T02:59:59Z"),
            ("rolling:30d", "2026-08-02T03:00:00Z", "2026-08-02T02:59:59Z"),
        )
        for expression, included, excluded in cases:
            with self.subTest(expression=expression):
                compiled = self.compile(expression, now=now)
                self.assertTrue(compiled.matches(included, "title", "").matched)
                self.assertFalse(compiled.matches(excluded, "title", "").matched)

    def test_fixed_range_includes_both_korean_calendar_boundaries(self):
        compiled = self.compile(
            "from:2026-06-01 to:2026-08-15",
            now=datetime(2026, 9, 1, 3, 0, tzinfo=timezone.utc),
        )

        self.assertTrue(compiled.matches("2026-05-31T15:00:00Z", "title", "").matched)
        self.assertTrue(compiled.matches("2026-08-15T14:59:59Z", "title", "").matched)
        self.assertFalse(compiled.matches("2026-05-31T14:59:59Z", "title", "").matched)
        self.assertFalse(compiled.matches("2026-08-15T15:00:00Z", "title", "").matched)

    def test_one_sided_fixed_ranges_are_supported(self):
        after = self.compile("from:2026-06-01")
        before = self.compile("to:2026-08-15")

        self.assertTrue(after.matches("2026-06-01T00:00:00+09:00", "title", "").matched)
        self.assertFalse(after.matches("2026-05-31T23:59:59+09:00", "title", "").matched)
        self.assertTrue(before.matches("2026-08-15T23:59:59+09:00", "title", "").matched)
        self.assertFalse(before.matches("2026-08-16T00:00:00+09:00", "title", "").matched)

    def test_keyword_scope_and_date_are_combined_with_and(self):
        title_only = self.compile(
            "rolling:7d",
            "아이유 | IU",
            "title",
            now=datetime(2026, 9, 1, 3, 0, tzinfo=timezone.utc),
        )
        with_description = self.compile(
            "rolling:7d",
            "아이유 | IU",
            "title_or_description",
            now=datetime(2026, 9, 1, 3, 0, tzinfo=timezone.utc),
        )

        self.assertTrue(
            title_only.matches("2026-08-31T03:00:00Z", "아이유 콘서트", "").matched
        )
        self.assertFalse(
            title_only.matches("2026-08-31T03:00:00Z", "다른 제목", "아이유 소식").matched
        )
        self.assertTrue(
            with_description.matches(
                "2026-08-31T03:00:00Z", "다른 제목", "아이유 소식"
            ).matched
        )
        self.assertFalse(
            with_description.matches(
                "2026-08-20T03:00:00Z", "아이유 콘서트", "아이유 소식"
            ).matched
        )

    def test_fingerprint_changes_with_every_filter_setting(self):
        base = self.compile("rolling:7d", "아이유", "title")
        variants = (
            self.compile("rolling:30d", "아이유", "title"),
            self.compile("rolling:7d", "IU", "title"),
            self.compile("rolling:7d", "아이유", "title_or_description"),
            self.module.compile_feed_filter(
                date_filter="rolling:7d",
                keyword_filter="아이유",
                keyword_scope="title",
                timezone_name="Asia/Tokyo",
                display_language="ko",
                now=datetime(2026, 9, 1, 3, 0, tzinfo=timezone.utc),
            ),
            self.module.compile_feed_filter(
                date_filter="rolling:7d",
                keyword_filter="아이유",
                keyword_scope="title",
                timezone_name="Asia/Seoul",
                display_language="ja",
                now=datetime(2026, 9, 1, 3, 0, tzinfo=timezone.utc),
            ),
        )

        for variant in variants:
            self.assertNotEqual(base.fingerprint, variant.fingerprint)

    def test_invalid_date_scope_and_naive_now_fail_before_matching(self):
        invalid_values = ("calendar:0d", "calendar:1y", "rolling:month", "from:bad")
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError, "invalid feed date filter"
            ):
                self.compile(value)
        with self.assertRaisesRegex(ValueError, "invalid feed keyword scope"):
            self.compile(keyword_filter="news", scope="description")
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            self.compile("rolling:24h", now=datetime(2026, 9, 1, 12, 0))

    def test_legacy_date_filter_is_supported_but_new_setting_wins(self):
        self.assertEqual(
            "from:2026-06-01 to:2026-08-15",
            self.module.resolve_feed_date_filter(
                "",
                "since:2026-06-01 until:2026-08-15",
            ),
        )
        self.assertEqual(
            "rolling:7d",
            self.module.resolve_feed_date_filter("", "past:7d"),
        )
        self.assertEqual(
            "calendar:1d",
            self.module.resolve_feed_date_filter("calendar:1d", "past:7d"),
        )
        with self.assertRaisesRegex(ValueError, "invalid legacy date filter"):
            self.module.resolve_feed_date_filter("", "since:bad")

    def test_legacy_keyword_filter_is_converted_and_new_setting_wins(self):
        converted = self.module.resolve_feed_keyword_filter(
            "",
            '+아이유 "Lee Ji-eun" -루머',
        )
        compiled = self.module.compile_feed_filter(
            keyword_filter=converted,
            timezone_name="UTC",
        )

        self.assertTrue(
            compiled.matches(
                "2026-09-01T00:00:00Z",
                "아이유 Lee Ji-eun 콘서트",
                "",
            ).matched
        )
        self.assertFalse(
            compiled.matches(
                "2026-09-01T00:00:00Z",
                "아이유 Lee Ji-eun 루머",
                "",
            ).matched
        )
        self.assertEqual(
            "아이유 OR IU",
            self.module.resolve_feed_keyword_filter("아이유 OR IU", "+legacy"),
        )

    def test_multiple_filter_layers_have_one_stable_combined_fingerprint(self):
        first = self.module.combine_filter_fingerprints("service", "common")
        second = self.module.combine_filter_fingerprints("service", "common")
        changed = self.module.combine_filter_fingerprints("service", "changed")

        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)


if __name__ == "__main__":
    unittest.main()
