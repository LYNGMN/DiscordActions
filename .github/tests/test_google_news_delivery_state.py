import importlib
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def load_delivery_module():
    scripts_path = str(SCRIPTS_DIR)
    sys.path.insert(0, scripts_path)
    try:
        sys.modules.pop("google_news_delivery_state", None)
        return importlib.import_module("google_news_delivery_state")
    finally:
        sys.path.pop(0)


def make_item(guid, pub_date, title=None, link=None):
    item = Element("item")
    values = {
        "guid": guid,
        "pubDate": pub_date,
        "title": title or "Title {}".format(guid),
        "link": link or "https://news.google.com/rss/articles/{}".format(guid),
    }
    for tag, value in values.items():
        if value is not None:
            SubElement(item, tag).text = value
    return item


def item_guids(items):
    return [item.findtext("guid") for item in items]


class GoogleNewsDeliveryStateTests(unittest.TestCase):
    def setUp(self):
        self.module = load_delivery_module()
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
                    related_news TEXT
                )
                """
            )

    def rows(self):
        with sqlite3.connect(self.db_path) as connection:
            return connection.execute(
                "SELECT guid, pub_date, title, link, related_news "
                "FROM news_items ORDER BY guid"
            ).fetchall()

    def test_scheduled_mode_selects_three_recent_items_and_baselines_the_rest(self):
        items = [
            make_item("r4", "Sun, 30 Aug 2026 11:40:00 GMT"),
            make_item("old", "Sun, 30 Aug 2026 08:00:00 GMT"),
            make_item("r2", "Sun, 30 Aug 2026 11:20:00 GMT"),
            make_item("r1", "Sun, 30 Aug 2026 11:10:00 GMT"),
            make_item("r3", "Sun, 30 Aug 2026 11:30:00 GMT"),
        ]

        selected = self.module.prepare_scheduled_items(
            items,
            self.db_path,
            datetime(2026, 8, 30, 12, tzinfo=timezone.utc),
        )

        self.assertEqual(["r2", "r3", "r4"], item_guids(selected))
        self.assertEqual(["old", "r1"], [row[0] for row in self.rows()])

    def test_existing_baseline_is_not_overwritten(self):
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "INSERT INTO news_items VALUES (?, ?, ?, ?, ?)",
                ("original-date", "r1", "Original", "https://example.com/original", "[]"),
            )
        items = [
            make_item("r1", "Sun, 30 Aug 2026 11:10:00 GMT", title="Changed"),
            make_item("r2", "Sun, 30 Aug 2026 11:20:00 GMT"),
        ]

        self.module.prepare_scheduled_items(
            items,
            self.db_path,
            datetime(2026, 8, 30, 12, tzinfo=timezone.utc),
            max_items=1,
        )

        self.assertEqual("Original", self.rows()[0][2])

    def test_invalid_item_rolls_back_all_baseline_writes(self):
        items = [
            make_item("valid", "Sun, 30 Aug 2026 08:00:00 GMT"),
            make_item("invalid", "not-a-date"),
            make_item("recent", "Sun, 30 Aug 2026 11:40:00 GMT"),
        ]

        with self.assertRaisesRegex(ValueError, "invalid required field: pubDate"):
            self.module.prepare_scheduled_items(
                items,
                self.db_path,
                datetime(2026, 8, 30, 12, tzinfo=timezone.utc),
            )

        self.assertEqual([], self.rows())

    def test_zero_limit_baselines_every_valid_item(self):
        items = [make_item("one", "Sun, 30 Aug 2026 11:40:00 GMT")]

        selected = self.module.prepare_scheduled_items(
            items,
            self.db_path,
            datetime(2026, 8, 30, 12, tzinfo=timezone.utc),
            max_items=0,
        )

        self.assertEqual([], selected)
        self.assertEqual(["one"], [row[0] for row in self.rows()])

    def test_reserve_is_atomic_and_pending_is_already_known(self):
        self.assertTrue(self.module.reserve_delivery(self.db_path, "guid-1"))
        self.assertFalse(self.module.reserve_delivery(self.db_path, "guid-1"))
        self.assertEqual(1, self.module.count_pending_deliveries(self.db_path))

        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT guid, delivery_status, discord_message_id "
                "FROM news_items WHERE guid = ?",
                ("guid-1",),
            ).fetchone()
        self.assertEqual(("guid-1", "pending", None), row)

    def test_mark_sent_accepts_only_numeric_discord_message_ids(self):
        self.module.reserve_delivery(self.db_path, "guid-1")

        with self.assertRaisesRegex(ValueError, "invalid Discord message id"):
            self.module.mark_delivery_sent(self.db_path, "guid-1", "not-numeric")
        self.assertEqual(1, self.module.count_pending_deliveries(self.db_path))

        self.module.mark_delivery_sent(self.db_path, "guid-1", "123456789012345678")

        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT delivery_status, discord_message_id "
                "FROM news_items WHERE guid = ?",
                ("guid-1",),
            ).fetchone()
        self.assertEqual(("sent", "123456789012345678"), row)
        self.assertEqual(0, self.module.count_pending_deliveries(self.db_path))

    def test_mark_sent_survives_the_legacy_article_replace(self):
        self.module.reserve_delivery(self.db_path, "guid-1")
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO news_items "
                "(pub_date, guid, title, link, related_news) VALUES (?, ?, ?, ?, ?)",
                (
                    "Sun, 30 Aug 2026 12:00:00 GMT",
                    "guid-1",
                    "Delivered article",
                    "https://publisher.example/article",
                    "[]",
                ),
            )

        self.module.mark_delivery_sent(self.db_path, "guid-1", "123456789012345678")

        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT title, delivery_status, discord_message_id "
                "FROM news_items WHERE guid = ?",
                ("guid-1",),
            ).fetchone()
        self.assertEqual(
            ("Delivered article", "sent", "123456789012345678"),
            row,
        )

    def test_mark_sent_rejects_an_unknown_guid(self):
        with self.assertRaisesRegex(ValueError, "delivery reservation not found"):
            self.module.mark_delivery_sent(self.db_path, "missing", "123456789012345678")


if __name__ == "__main__":
    unittest.main()
