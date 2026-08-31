import importlib
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


class TestMessageId(str):
    def __new__(cls, value, ambiguous_retry=False):
        instance = str.__new__(cls, value)
        instance.ambiguous_retry = ambiguous_retry
        return instance


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

    def test_scheduled_mode_uses_feed_position_not_publication_date(self):
        items = [
            make_item("feed-first", "Sun, 30 Aug 2026 08:00:00 GMT"),
            make_item("feed-middle", "Sun, 30 Aug 2026 12:00:00 GMT"),
            make_item("feed-last", "Sun, 30 Aug 2026 10:00:00 GMT"),
        ]

        selected = self.module.prepare_scheduled_items(
            items,
            self.db_path,
            delivery_order="feed_oldest_first",
        )

        self.assertEqual(
            ["feed-last", "feed-middle", "feed-first"],
            item_guids(selected),
        )
        self.assertEqual([], self.rows())

    def test_feed_newest_first_preserves_source_order(self):
        items = [
            make_item("first", "not-a-date"),
            make_item("second", "also-not-a-date"),
        ]

        selected = self.module.prepare_scheduled_items(
            items,
            self.db_path,
            delivery_order="feed_newest_first",
        )

        self.assertEqual(["first", "second"], item_guids(selected))

    def test_invalid_delivery_order_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "delivery order"):
            self.module.prepare_scheduled_items(
                [make_item("one", "Sun, 30 Aug 2026 08:00:00 GMT")],
                self.db_path,
                delivery_order="publication_date",
            )

    def test_filtered_item_is_rechecked_only_when_fingerprint_changes(self):
        item = make_item("filtered-guid", "Sun, 30 Aug 2026 11:40:00 GMT")
        self.module.record_filtered_item(self.db_path, item, "fingerprint-a")

        self.assertTrue(
            self.module.is_item_handled(
                self.db_path, "filtered-guid", "fingerprint-a"
            )
        )
        self.assertFalse(
            self.module.is_item_handled(
                self.db_path, "filtered-guid", "fingerprint-b"
            )
        )

    def test_filtered_item_can_be_reserved_after_filter_change(self):
        item = make_item("filtered-guid", "Sun, 30 Aug 2026 11:40:00 GMT")
        self.module.record_filtered_item(self.db_path, item, "fingerprint-a")

        self.assertTrue(
            self.module.reserve_delivery(
                self.db_path,
                "filtered-guid",
                "Title filtered-guid",
                "https://publisher.example/story",
            )
        )
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT delivery_status, filter_fingerprint FROM news_items "
                "WHERE guid = ?",
                ("filtered-guid",),
            ).fetchone()
        self.assertEqual(("pending", None), row)

    def test_pending_resume_uses_reservation_order_not_legacy_row_order(self):
        old_item = make_item("filtered-guid", "Sun, 30 Aug 2026 11:40:00 GMT")
        self.module.record_filtered_item(self.db_path, old_item, "fingerprint-a")

        self.assertTrue(
            self.module.reserve_delivery_with_messages(
                self.db_path,
                "new-guid",
                "New first",
                "https://news.google.com/rss/articles/new-guid",
                ["new"],
            )
        )
        self.assertTrue(
            self.module.reserve_delivery_with_messages(
                self.db_path,
                "filtered-guid",
                "Filtered second",
                "https://news.google.com/rss/articles/filtered-guid",
                ["filtered"],
            )
        )

        self.assertEqual(
            ["new-guid", "filtered-guid"],
            self.module.pending_delivery_guids(self.db_path),
        )

    def test_reserve_is_idempotent_for_pending_resume(self):
        self.assertTrue(self.module.reserve_delivery(self.db_path, "guid-1"))
        self.assertTrue(self.module.reserve_delivery(self.db_path, "guid-1"))
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

    def test_message_queue_resumes_at_first_unsent_chunk(self):
        self.assertTrue(self.module.reserve_delivery(self.db_path, "guid-1"))
        self.module.enqueue_delivery_messages(
            self.db_path,
            "guid-1",
            ["main", "related-1", "related-2"],
        )
        self.assertFalse(self.module.is_item_handled(self.db_path, "guid-1"))

        self.module.mark_delivery_message_sent(
            self.db_path,
            "guid-1",
            0,
            "123456789012345678",
            last_error_code="ambiguous_retry",
        )
        self.assertEqual(1, self.module.count_ambiguous_retries(self.db_path))

        self.assertEqual(
            [(1, "related-1"), (2, "related-2")],
            self.module.pending_delivery_messages(self.db_path, "guid-1"),
        )
        self.assertFalse(self.module.finalize_delivery(self.db_path, "guid-1"))

        self.module.mark_delivery_message_sent(
            self.db_path, "guid-1", 1, "223456789012345678"
        )
        self.module.mark_delivery_message_sent(
            self.db_path, "guid-1", 2, "323456789012345678"
        )
        self.assertTrue(self.module.finalize_delivery(self.db_path, "guid-1"))
        self.assertEqual(0, self.module.count_pending_deliveries(self.db_path))

    def test_failed_ambiguous_delivery_is_recorded_while_remaining_pending(self):
        self.assertTrue(
            self.module.reserve_delivery_with_messages(
                self.db_path, "guid-1", "Title", "", ["message"]
            )
        )
        failure = RuntimeError("response unknown")
        failure.error_code = "ambiguous_retry"
        failure.attempt_count = 2

        with self.assertRaises(RuntimeError):
            self.module.deliver_queued_item(
                self.db_path,
                "guid-1",
                lambda _content: (_ for _ in ()).throw(failure),
            )

        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT status, attempt_count, last_error_code "
                "FROM google_news_delivery_messages WHERE guid = ?",
                ("guid-1",),
            ).fetchone()
        self.assertEqual(("pending", 2, "ambiguous_retry"), row)
        self.assertEqual(1, self.module.count_ambiguous_retries(self.db_path))

        self.module.mark_delivery_message_sent(
            self.db_path,
            "guid-1",
            0,
            "123456789012345678",
        )
        self.assertEqual(1, self.module.count_ambiguous_retries(self.db_path))

    def test_existing_queued_content_is_not_replaced_during_resume(self):
        self.assertTrue(self.module.reserve_delivery(self.db_path, "guid-1"))
        self.module.enqueue_delivery_messages(self.db_path, "guid-1", ["original"])

        self.assertTrue(self.module.reserve_delivery(self.db_path, "guid-1"))
        self.module.enqueue_delivery_messages(self.db_path, "guid-1", ["changed"])

        self.assertEqual(
            [(0, "original")],
            self.module.pending_delivery_messages(self.db_path, "guid-1"),
        )

    def test_reservation_and_messages_are_created_atomically(self):
        reserved = self.module.reserve_delivery_with_messages(
            self.db_path,
            "guid-atomic",
            "Atomic headline",
            "https://news.google.com/rss/articles/atomic",
            ["first", "second"],
        )

        self.assertTrue(reserved)
        with sqlite3.connect(self.db_path) as connection:
            article = connection.execute(
                "SELECT delivery_status FROM news_items WHERE guid = ?",
                ("guid-atomic",),
            ).fetchone()
            messages = connection.execute(
                "SELECT sequence, content, status "
                "FROM google_news_delivery_messages WHERE guid = ? ORDER BY sequence",
                ("guid-atomic",),
            ).fetchall()
        self.assertEqual(("pending",), article)
        self.assertEqual(
            [(0, "first", "pending"), (1, "second", "pending")],
            messages,
        )

    def test_message_insert_failure_rolls_back_article_reservation(self):
        with sqlite3.connect(self.db_path) as connection:
            self.module._ensure_message_table(connection)
            connection.execute(
                "CREATE TRIGGER fail_message_insert BEFORE INSERT "
                "ON google_news_delivery_messages BEGIN "
                "SELECT RAISE(ABORT, 'message failure'); END"
            )

        with self.assertRaises(sqlite3.IntegrityError):
            self.module.reserve_delivery_with_messages(
                self.db_path,
                "guid-atomic",
                "Atomic headline",
                "https://news.google.com/rss/articles/atomic",
                ["first"],
            )

        with sqlite3.connect(self.db_path) as connection:
            article = connection.execute(
                "SELECT guid FROM news_items WHERE guid = ?",
                ("guid-atomic",),
            ).fetchone()
        self.assertIsNone(article)

    def test_pending_item_can_resume_without_being_present_in_the_feed(self):
        self.assertTrue(
            self.module.reserve_delivery(
                self.db_path, "guid-1", "Stored title", "https://example.com/story"
            )
        )
        self.module.enqueue_delivery_messages(
            self.db_path, "guid-1", ["first", "second"]
        )
        delivered = []

        outcome = self.module.deliver_queued_item(
            self.db_path,
            "guid-1",
            lambda content: delivered.append(content)
            or TestMessageId(
                str(100 + len(delivered)),
                ambiguous_retry=(content == "second"),
            ),
        )

        self.assertEqual(["first", "second"], delivered)
        self.assertEqual(1, outcome.ambiguous_retry_count)
        self.assertEqual([], self.module.pending_delivery_guids(self.db_path))
        self.assertEqual("Stored title", self.rows()[0][2])

    def test_orphaned_pending_article_is_released_for_safe_requeue(self):
        self.assertTrue(
            self.module.reserve_delivery(
                self.db_path,
                "orphaned-guid",
                "Stored title",
                "https://example.com/story",
            )
        )

        self.assertEqual([], self.module.pending_delivery_guids(self.db_path))
        self.assertEqual(0, self.module.count_pending_deliveries(self.db_path))
        self.assertFalse(self.module.is_item_handled(self.db_path, "orphaned-guid"))

        self.assertTrue(
            self.module.reserve_delivery_with_messages(
                self.db_path,
                "orphaned-guid",
                "Stored title",
                "https://example.com/story",
                ["reconstructed message"],
            )
        )
        self.assertEqual(
            ["orphaned-guid"],
            self.module.pending_delivery_guids(self.db_path),
        )

    def test_released_orphan_can_be_recorded_as_filtered(self):
        self.assertTrue(
            self.module.reserve_delivery(
                self.db_path,
                "orphaned-guid",
                "Stored title",
                "https://example.com/story",
            )
        )
        self.assertEqual([], self.module.pending_delivery_guids(self.db_path))

        item = make_item(
            "orphaned-guid",
            "Sun, 30 Aug 2026 11:40:00 GMT",
        )
        self.module.record_filtered_item(self.db_path, item, "fingerprint-a")

        self.assertTrue(
            self.module.is_item_handled(
                self.db_path,
                "orphaned-guid",
                "fingerprint-a",
            )
        )

    def test_canonical_url_ignores_tracking_query_fragment_and_host_case(self):
        first = (
            "https://Publisher.Example/story?id=7&utm_source=google#section"
        )
        second = (
            "https://publisher.example/story?utm_medium=rss&id=7"
        )

        self.assertEqual(
            self.module.canonicalize_article_url(first),
            self.module.canonicalize_article_url(second),
        )

    def test_changed_guid_and_tracking_query_are_one_article(self):
        first = "https://publisher.example/story?id=7&utm_source=google"
        second = "https://PUBLISHER.example/story?utm_medium=rss&id=7#section"

        self.assertTrue(
            self.module.reserve_delivery(self.db_path, "g1", "Same - Press", first)
        )
        self.assertFalse(
            self.module.reserve_delivery(self.db_path, "g2", "Same - Press", second)
        )

    def test_changed_google_wrapper_is_deduped_by_normalized_title(self):
        self.assertTrue(
            self.module.reserve_delivery(
                self.db_path,
                "g1",
                "아이유   새 소식 - 언론사",
                "https://news.google.com/rss/articles/first",
            )
        )
        self.assertFalse(
            self.module.reserve_delivery(
                self.db_path,
                "g2",
                "아이유 새 소식 - 언론사",
                "https://news.google.com/rss/articles/second",
            )
        )

    def test_distinct_titles_with_google_wrappers_are_deliverable(self):
        self.assertTrue(
            self.module.reserve_delivery(
                self.db_path,
                "g1",
                "첫 번째 기사 - 언론사",
                "https://news.google.com/rss/articles/first",
            )
        )
        self.assertTrue(
            self.module.reserve_delivery(
                self.db_path,
                "g2",
                "두 번째 기사 - 언론사",
                "https://news.google.com/rss/articles/second",
            )
        )

    def test_existing_news_rows_are_backfilled_before_reservation(self):
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "INSERT INTO news_items (pub_date, guid, title, link, related_news) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    "Sun, 30 Aug 2026 12:00:00 GMT",
                    "legacy-guid",
                    "이미 게시된 기사 - 언론사",
                    "https://publisher.example/already-posted?utm_source=google",
                    "[]",
                ),
            )

        self.assertFalse(
            self.module.reserve_delivery(
                self.db_path,
                "new-guid",
                "이미 게시된 기사 - 언론사",
                "https://publisher.example/already-posted?utm_medium=rss",
            )
        )


if __name__ == "__main__":
    unittest.main()
