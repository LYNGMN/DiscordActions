import importlib
import sqlite3
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def load_manual_test_module():
    scripts_path = str(SCRIPTS_DIR)
    sys.path.insert(0, scripts_path)
    try:
        sys.modules.pop("google_news_manual_test", None)
        return importlib.import_module("google_news_manual_test")
    finally:
        sys.path.pop(0)


def make_item(guid, pub_date, title=None, link=None):
    item = ET.Element("item")
    values = {
        "guid": guid,
        "pubDate": pub_date,
        "title": title or f"Title {guid}",
        "link": link or f"https://news.google.com/rss/articles/{guid}",
    }
    for tag, value in values.items():
        if value is not None:
            ET.SubElement(item, tag).text = value
    return item


class GoogleNewsManualTestTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = str(Path(self.temp_dir.name) / "news.db")
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE news_items (
                    pub_date TEXT,
                    guid TEXT PRIMARY KEY,
                    title TEXT,
                    link TEXT,
                    topic TEXT,
                    related_news TEXT
                )
                """
            )

    def fetch_rows(self):
        with sqlite3.connect(self.db_path) as connection:
            return connection.execute(
                """
                SELECT pub_date, guid, title, link, related_news
                FROM news_items
                ORDER BY guid
                """
            ).fetchall()

    def test_enabled_mode_selects_latest_item_and_seeds_the_rest(self):
        module = load_manual_test_module()
        items = [
            make_item("middle", "Sun, 30 Aug 2026 10:00:00 GMT"),
            make_item("newest", "Sun, 30 Aug 2026 12:00:00 GMT"),
            make_item("oldest", "Sun, 30 Aug 2026 08:00:00 GMT"),
        ]

        selected = module.prepare_manual_test_items(items, self.db_path, True)

        self.assertEqual(["newest"], [item.findtext("guid") for item in selected])
        self.assertEqual(
            [
                (
                    "Sun, 30 Aug 2026 10:00:00 GMT",
                    "middle",
                    "Title middle",
                    "https://news.google.com/rss/articles/middle",
                    "[]",
                ),
                (
                    "Sun, 30 Aug 2026 08:00:00 GMT",
                    "oldest",
                    "Title oldest",
                    "https://news.google.com/rss/articles/oldest",
                    "[]",
                ),
            ],
            self.fetch_rows(),
        )

    def test_disabled_mode_preserves_items_without_writing_database(self):
        module = load_manual_test_module()
        items = [
            make_item("first", "Sun, 30 Aug 2026 08:00:00 GMT"),
            make_item("second", "Sun, 30 Aug 2026 09:00:00 GMT"),
        ]

        selected = module.prepare_manual_test_items(items, self.db_path, False)

        self.assertEqual(items, selected)
        self.assertEqual([], self.fetch_rows())

    def test_empty_input_returns_empty_without_writing_database(self):
        module = load_manual_test_module()

        selected = module.prepare_manual_test_items([], self.db_path, True)

        self.assertEqual([], selected)
        self.assertEqual([], self.fetch_rows())

    def test_existing_baseline_row_is_not_overwritten(self):
        module = load_manual_test_module()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO news_items (
                    pub_date, guid, title, link, related_news
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "preserved-date",
                    "oldest",
                    "preserved-title",
                    "https://publisher.example/preserved",
                    "preserved-related",
                ),
            )
        items = [
            make_item("newest", "Sun, 30 Aug 2026 12:00:00 GMT"),
            make_item("oldest", "Sun, 30 Aug 2026 08:00:00 GMT"),
        ]

        module.prepare_manual_test_items(items, self.db_path, True)

        self.assertEqual(
            [
                (
                    "preserved-date",
                    "oldest",
                    "preserved-title",
                    "https://publisher.example/preserved",
                    "preserved-related",
                )
            ],
            self.fetch_rows(),
        )

    def test_missing_required_field_writes_no_partial_baseline(self):
        module = load_manual_test_module()
        items = [
            make_item("valid", "Sun, 30 Aug 2026 08:00:00 GMT"),
            make_item("missing-date", None),
            make_item("newest", "Sun, 30 Aug 2026 12:00:00 GMT"),
        ]

        with self.assertRaisesRegex(ValueError, "pubDate"):
            module.prepare_manual_test_items(items, self.db_path, True)

        self.assertEqual([], self.fetch_rows())

    def test_invalid_date_writes_no_partial_baseline(self):
        module = load_manual_test_module()
        items = [
            make_item("valid", "Sun, 30 Aug 2026 08:00:00 GMT"),
            make_item("invalid-date", "not-a-date"),
        ]

        with self.assertRaisesRegex(ValueError, "invalid required field: pubDate"):
            module.prepare_manual_test_items(items, self.db_path, True)

        self.assertEqual([], self.fetch_rows())

    def test_enabled_mode_rejects_missing_processed_item(self):
        module = load_manual_test_module()

        with self.assertRaisesRegex(RuntimeError, "expected 1, processed 0"):
            module.validate_manual_test_result(True, 1, 0)

    def test_result_validation_allows_disabled_or_matching_counts(self):
        module = load_manual_test_module()

        module.validate_manual_test_result(False, 1, 0)
        module.validate_manual_test_result(True, 0, 0)
        module.validate_manual_test_result(True, 1, 1)


if __name__ == "__main__":
    unittest.main()
