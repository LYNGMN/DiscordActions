import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from feed_filters import compile_feed_filter, resolve_feed_timezone


class TimezoneMigrationTests(unittest.TestCase):
    def test_filter_uses_standard_library_timezone(self):
        value = compile_feed_filter("calendar:1d", timezone_name="America/New_York")
        self.assertIsInstance(value.start_at.tzinfo, ZoneInfo)

    def test_rolling_window_keeps_24_hours_across_both_dst_changes(self):
        for now in (datetime(2026, 3, 8, 16, tzinfo=timezone.utc),
                    datetime(2026, 11, 1, 17, tzinfo=timezone.utc)):
            window = compile_feed_filter("rolling:24h", timezone_name="America/New_York", now=now)
            self.assertEqual(timedelta(hours=24), now - window.start_at.astimezone(timezone.utc))

    def test_midnight_overlap_uses_standard_time(self):
        window = compile_feed_filter("from:2026-11-01", timezone_name="America/Havana")
        self.assertEqual(datetime(2026, 11, 1, 5, tzinfo=timezone.utc), window.start_at.astimezone(timezone.utc))

    def test_missing_midnight_keeps_pre_transition_offset(self):
        window = compile_feed_filter("from:2018-11-04", timezone_name="America/Sao_Paulo")
        self.assertEqual(datetime(2018, 11, 4, 3, tzinfo=timezone.utc), window.start_at.astimezone(timezone.utc))

    def test_skipped_calendar_day_keeps_legacy_boundary_instant(self):
        window = compile_feed_filter("from:2011-12-30", timezone_name="Pacific/Apia")
        self.assertEqual(datetime(2011, 12, 30, 10, tzinfo=timezone.utc), window.start_at.astimezone(timezone.utc))

    def test_country_defaults_preserve_existing_choices(self):
        for country, name in {"KR":"Asia/Seoul", "JP":"Asia/Tokyo", "CN":"Asia/Shanghai", "US":"America/New_York", "AU":"Australia/Lord_Howe", "DE":"Europe/Berlin"}.items():
            self.assertEqual(name, resolve_feed_timezone(country_code=country))

    def test_invalid_zone_paths_fail_with_safe_message(self):
        for name in ("/etc/passwd", "../UTC", "No/SuchZone"):
            with self.assertRaisesRegex(ValueError, "invalid feed timezone"):
                compile_feed_filter(timezone_name=name)

    def test_negative_dst_overlap_keeps_legacy_standard_time_choice(self):
        from feed_timezones import get_timezone, localize_boundary
        result = localize_boundary(datetime(2026, 10, 25, 1, 30), get_timezone("Europe/Dublin"))
        self.assertEqual(datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc), result.astimezone(timezone.utc))

    def test_timezone_names_remain_case_insensitive(self):
        from feed_timezones import get_timezone
        for name in ("asia/seoul", "utc", "us/eastern"):
            self.assertIsInstance(get_timezone(name), ZoneInfo)
