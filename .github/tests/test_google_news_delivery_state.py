import importlib
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
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

    def test_scheduled_delivery_limit_is_bounded_and_validated(self):
        self.assertEqual(25, self.module.scheduled_delivery_limit())
        self.assertEqual(2, self.module.scheduled_delivery_limit("2"))
        self.assertEqual(100, self.module.scheduled_delivery_limit("100"))
        for invalid in ("0", "-1", "101", "nan", "2.5", " 25", "100000"):
            with self.subTest(value=invalid):
                with self.assertRaisesRegex(ValueError, "invalid_google_news_delivery_limit"):
                    self.module.scheduled_delivery_limit(invalid)

    def test_deferred_delivery_messages_remain_pending_across_runs(self):
        for index in range(5):
            guid = "queued-{}".format(index)
            self.assertTrue(self.module.reserve_delivery_with_messages(
                self.db_path, guid, "Title {}".format(index),
                "https://publisher.example/story/{}".format(index),
                ["Message {}".format(index)],
            ))
        delivered = []
        def send_message(content):
            delivered.append(content)
            return "123456789012345678"

        for _ in range(3):
            pending = self.module.pending_delivery_guids(self.db_path)[:2]
            for guid in pending:
                self.module.deliver_queued_item(self.db_path, guid, send_message)
        self.assertEqual(5, len(delivered))
        self.assertEqual([], self.module.pending_delivery_guids(self.db_path))
        self.assertEqual(0, self.module.count_pending_deliveries(self.db_path))

    def test_delivery_reports_message_counts_and_events(self):
        self.module.reserve_delivery_with_messages(
            self.db_path,
            "guid-events",
            "Title",
            "https://news.google.com/rss/articles/guid-events",
            ["first part", "second part"],
        )

        class MessageId(str):
            ambiguous_retry = False
            attempt_count = 1
            content_truncated = True

        with self.assertLogs("delivery_events", level="INFO") as captured:
            outcome = self.module.deliver_queued_item(
                self.db_path,
                "guid-events",
                lambda _content: MessageId("123456789012345678"),
                profile_id="top_kr",
            )

        self.assertEqual(2, outcome.message_count)
        self.assertEqual(2, outcome.truncated_count)
        sent = [line for line in captured.output if "event=message_sent" in line]
        truncated = [line for line in captured.output if "event=content_truncated" in line]
        self.assertEqual(2, len(sent))
        self.assertEqual(2, len(truncated))
        self.assertIn("profile=top_kr", sent[0])

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

    def test_failed_discord_status_code_is_preserved_while_remaining_pending(self):
        self.assertTrue(
            self.module.reserve_delivery_with_messages(
                self.db_path, "guid-http", "Title", "", ["message"]
            )
        )
        failure = RuntimeError("discord rejected the request")
        failure.error_code = "discord_http_400_api_240000"
        failure.attempt_count = 1

        with self.assertRaises(RuntimeError):
            self.module.deliver_queued_item(
                self.db_path,
                "guid-http",
                lambda _content: (_ for _ in ()).throw(failure),
            )

        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT status, attempt_count, last_error_code "
                "FROM google_news_delivery_messages WHERE guid = ?",
                ("guid-http",),
            ).fetchone()
        self.assertEqual(
            ("pending", 1, "discord_http_400_api_240000"),
            row,
        )

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

    def test_article_identity_backfill_runs_once_per_database(self):
        with mock.patch.object(
            self.module,
            "_backfill_article_identities",
            wraps=self.module._backfill_article_identities,
        ) as backfill:
            self.assertTrue(
                self.module.reserve_delivery(
                    self.db_path,
                    "first-guid",
                    "첫 번째 기사 - 언론사",
                    "https://publisher.example/first",
                )
            )
            self.assertTrue(
                self.module.reserve_delivery(
                    self.db_path,
                    "second-guid",
                    "두 번째 기사 - 언론사",
                    "https://publisher.example/second",
                )
            )

        self.assertEqual(1, backfill.call_count)

    def test_retention_days_is_bounded_and_validated(self):
        self.assertEqual(30, self.module.DEFAULT_RETENTION_DAYS)
        self.assertEqual(30, self.module.state_retention_days())
        self.assertEqual(1, self.module.state_retention_days("1"))
        self.assertEqual(365, self.module.state_retention_days("365"))
        for invalid in ("0", "-1", "366", "nan", "2.5", " 14", "140000"):
            with self.subTest(value=invalid):
                with self.assertRaisesRegex(
                    ValueError, "invalid_google_news_state_retention_days"
                ):
                    self.module.state_retention_days(invalid)

    def test_state_retention_prunes_expired_terminal_items_only(self):
        now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        expired = (now - timedelta(days=40)).isoformat()
        recent = (now - timedelta(days=1)).isoformat()
        for guid in ("expired-sent", "expired-pending", "recent-sent"):
            self.assertTrue(
                self.module.reserve_delivery_with_messages(
                    self.db_path,
                    guid,
                    "제목 {}".format(guid),
                    "https://publisher.example/{}".format(guid),
                    ["본문 {}".format(guid)],
                )
            )
        self.module.record_filtered_item(
            self.db_path,
            make_item("expired-filtered", "Sun, 30 Aug 2026 12:00:00 GMT"),
            "fingerprint",
        )
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE news_items SET delivery_status = 'sent' "
                "WHERE guid IN ('expired-sent', 'recent-sent')"
            )
            connection.execute(
                "UPDATE google_news_delivery_messages SET status = 'sent' "
                "WHERE guid IN ('expired-sent', 'recent-sent')"
            )
            connection.execute(
                "UPDATE news_items SET created_at = ? "
                "WHERE guid IN ('expired-sent', 'expired-pending', 'expired-filtered')",
                (expired,),
            )
            connection.execute(
                "UPDATE news_items SET created_at = ? WHERE guid = 'recent-sent'",
                (recent,),
            )

        stats = self.module.apply_state_retention(
            [self.db_path], retention_days=14, now=now
        )

        self.assertEqual(2, stats["items"])
        with sqlite3.connect(self.db_path) as connection:
            remaining = {
                row[0]
                for row in connection.execute("SELECT guid FROM news_items")
            }
            message_guids = {
                row[0]
                for row in connection.execute(
                    "SELECT guid FROM google_news_delivery_messages"
                )
            }
            identity_guids = {
                row[0]
                for row in connection.execute(
                    "SELECT guid FROM google_news_article_identity"
                )
            }
        self.assertEqual({"expired-pending", "recent-sent"}, remaining)
        self.assertEqual(remaining, message_guids)
        self.assertEqual(remaining, identity_guids)

    def test_state_retention_backfills_legacy_pub_dates(self):
        now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "INSERT INTO news_items (pub_date, guid, title, link, related_news) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    "Mon, 05 Jan 2026 00:00:00 GMT",
                    "legacy-guid",
                    "오래된 기사 - 언론사",
                    "https://publisher.example/legacy",
                    "[]",
                ),
            )

        stats = self.module.apply_state_retention(
            [self.db_path], retention_days=14, now=now
        )

        self.assertEqual(1, stats["items"])
        with sqlite3.connect(self.db_path) as connection:
            self.assertEqual(
                0, connection.execute("SELECT COUNT(*) FROM news_items").fetchone()[0]
            )

    def test_state_retention_prunes_only_stale_url_cache_rows(self):
        now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        resolver_path = str(Path(self.temp_dir.name) / "resolver.db")
        with sqlite3.connect(resolver_path) as connection:
            connection.execute(
                """
                CREATE TABLE google_news_url_cache (
                    article_id TEXT PRIMARY KEY,
                    google_url TEXT NOT NULL,
                    resolved_url TEXT,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_error_code TEXT,
                    next_retry_at TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.executemany(
                "INSERT INTO google_news_url_cache "
                "(article_id, google_url, resolved_url, status, updated_at) "
                "VALUES (?, ?, ?, 'resolved', ?)",
                [
                    (
                        "old-article",
                        "https://news.google.com/rss/articles/old",
                        "https://publisher.example/old",
                        (now - timedelta(days=40)).isoformat(),
                    ),
                    (
                        "recent-article",
                        "https://news.google.com/rss/articles/recent",
                        "https://publisher.example/recent",
                        (now - timedelta(days=1)).isoformat(),
                    ),
                ],
            )

        stats = self.module.apply_state_retention(
            [resolver_path], retention_days=14, now=now
        )

        self.assertEqual(1, stats["url_cache"])
        with sqlite3.connect(resolver_path) as connection:
            remaining = {
                row[0]
                for row in connection.execute(
                    "SELECT article_id FROM google_news_url_cache"
                )
            }
        self.assertEqual({"recent-article"}, remaining)

    def test_expire_pending_deliveries_clears_queue_and_keeps_history(self):
        self.assertTrue(
            self.module.reserve_delivery_with_messages(
                self.db_path, "pending-guid", "Pending", "", ["pending message"]
            )
        )
        self.assertTrue(
            self.module.reserve_delivery_with_messages(
                self.db_path, "sent-guid", "Sent", "", ["sent message"]
            )
        )
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE news_items SET delivery_status = 'sent' "
                "WHERE guid = 'sent-guid'"
            )
            connection.execute(
                "UPDATE google_news_delivery_messages SET status = 'sent' "
                "WHERE guid = 'sent-guid'"
            )

        self.assertEqual(1, self.module.count_unfinished_deliveries(self.db_path))
        expired = self.module.expire_pending_deliveries(self.db_path)

        self.assertEqual(1, expired)
        self.assertEqual(0, self.module.count_pending_deliveries(self.db_path))
        self.assertEqual(0, self.module.count_unfinished_deliveries(self.db_path))
        self.assertTrue(self.module.is_item_handled(self.db_path, "pending-guid"))
        with sqlite3.connect(self.db_path) as connection:
            statuses = dict(
                connection.execute(
                    "SELECT guid, delivery_status FROM news_items"
                ).fetchall()
            )
            message_guids = {
                row[0]
                for row in connection.execute(
                    "SELECT guid FROM google_news_delivery_messages"
                )
            }
        self.assertEqual(
            {"pending-guid": "expired", "sent-guid": "sent"}, statuses
        )
        self.assertEqual({"sent-guid"}, message_guids)

    def test_expire_pending_deliveries_handles_more_than_one_chunk(self):
        for index in range(5):
            self.assertTrue(
                self.module.reserve_delivery_with_messages(
                    self.db_path,
                    "chunk-{}".format(index),
                    "Title {}".format(index),
                    "https://publisher.example/chunk/{}".format(index),
                    ["message"],
                )
            )

        with mock.patch.object(self.module, "EXPIRY_CHUNK_SIZE", 2):
            expired = self.module.expire_pending_deliveries(self.db_path)

        self.assertEqual(5, expired)
        with sqlite3.connect(self.db_path) as connection:
            statuses = {
                row[0]
                for row in connection.execute(
                    "SELECT delivery_status FROM news_items"
                )
            }
            messages = connection.execute(
                "SELECT COUNT(*) FROM google_news_delivery_messages"
            ).fetchone()[0]
        self.assertEqual({"expired"}, statuses)
        self.assertEqual(0, messages)

    def test_state_retention_prunes_old_expired_items(self):
        now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        self.assertTrue(
            self.module.reserve_delivery_with_messages(
                self.db_path,
                "expired-guid",
                "Title",
                "https://publisher.example/expired",
                ["message"],
            )
        )
        self.module.expire_pending_deliveries(self.db_path)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE news_items SET created_at = ? WHERE guid = 'expired-guid'",
                ((now - timedelta(days=40)).isoformat(),),
            )

        stats = self.module.apply_state_retention(
            [self.db_path], retention_days=14, now=now
        )

        self.assertEqual(1, stats["items"])
        with sqlite3.connect(self.db_path) as connection:
            self.assertEqual(
                0,
                connection.execute(
                    "SELECT COUNT(*) FROM news_items WHERE guid = 'expired-guid'"
                ).fetchone()[0],
            )

    def test_state_retention_vacuums_at_most_once_per_day(self):
        now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        expired = (now - timedelta(days=40)).isoformat()

        def add_expired_sent_item(guid):
            self.assertTrue(
                self.module.reserve_delivery_with_messages(
                    self.db_path,
                    guid,
                    "제목",
                    "https://publisher.example/{}".format(guid),
                    ["본문"],
                )
            )
            with sqlite3.connect(self.db_path) as connection:
                connection.execute(
                    "UPDATE news_items SET delivery_status = 'sent', created_at = ? "
                    "WHERE guid = ?",
                    (expired, guid),
                )
                connection.execute(
                    "UPDATE google_news_delivery_messages SET status = 'sent' "
                    "WHERE guid = ?",
                    (guid,),
                )

        def vacuum_marker():
            with sqlite3.connect(self.db_path) as connection:
                row = connection.execute(
                    "SELECT value FROM google_news_state_metadata "
                    "WHERE metadata_key = 'last_vacuum_at'"
                ).fetchone()
            return row[0] if row else None

        add_expired_sent_item("vacuum-a")
        self.module.apply_state_retention(
            [self.db_path], retention_days=14, now=now
        )
        first_marker = vacuum_marker()
        self.assertIsNotNone(first_marker)

        add_expired_sent_item("vacuum-b")
        self.module.apply_state_retention(
            [self.db_path], retention_days=14, now=now + timedelta(hours=1)
        )
        self.assertEqual(first_marker, vacuum_marker())

        add_expired_sent_item("vacuum-c")
        self.module.apply_state_retention(
            [self.db_path], retention_days=14, now=now + timedelta(hours=25)
        )
        self.assertNotEqual(first_marker, vacuum_marker())

    def test_large_deletion_vacuums_within_the_same_day(self):
        now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        resolver_path = str(Path(self.temp_dir.name) / "resolver-large.db")
        with sqlite3.connect(resolver_path) as connection:
            connection.execute(
                """
                CREATE TABLE google_news_url_cache (
                    article_id TEXT PRIMARY KEY,
                    google_url TEXT NOT NULL,
                    resolved_url TEXT,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_error_code TEXT,
                    next_retry_at TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.executemany(
                "INSERT INTO google_news_url_cache "
                "(article_id, google_url, resolved_url, status, updated_at) "
                "VALUES (?, ?, ?, 'resolved', ?)",
                [
                    (
                        "old-{}".format(index),
                        "https://news.google.com/old-{}".format(index),
                        "https://publisher.example/old-{}".format(index),
                        (now - timedelta(days=40)).isoformat(),
                    )
                    for index in range(3)
                ],
            )
        with mock.patch.object(self.module, "VACUUM_ROW_THRESHOLD", 1):
            self.module.apply_state_retention(
                [resolver_path], retention_days=30, now=now
            )
            first = self.module.read_state_metadata(
                resolver_path, "last_vacuum_at"
            )
            connection = sqlite3.connect(resolver_path)
            connection.execute(
                "INSERT INTO google_news_url_cache "
                "(article_id, google_url, resolved_url, status, updated_at) "
                "VALUES ('later', 'https://news.google.com/later', "
                "'https://publisher.example/later', 'resolved', ?)",
                ((now - timedelta(days=40)).isoformat(),),
            )
            connection.commit()
            connection.close()
            self.module.apply_state_retention(
                [resolver_path], retention_days=30, now=now + timedelta(hours=1)
            )
        self.assertIsNotNone(first)
        self.assertNotEqual(
            first,
            self.module.read_state_metadata(resolver_path, "last_vacuum_at"),
        )

    def test_state_retention_prunes_old_abandoned_items(self):
        now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        self.assertTrue(
            self.module.reserve_delivery_with_messages(
                self.db_path,
                "abandoned-guid",
                "제목",
                "https://publisher.example/abandoned",
                ["본문"],
            )
        )
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE news_items SET delivery_status = 'failed', created_at = ? "
                "WHERE guid = 'abandoned-guid'",
                ((now - timedelta(days=40)).isoformat(),),
            )
            connection.execute(
                "UPDATE google_news_delivery_messages SET status = 'failed' "
                "WHERE guid = 'abandoned-guid'"
            )

        stats = self.module.apply_state_retention(
            [self.db_path], retention_days=14, now=now
        )

        self.assertEqual(1, stats["items"])
        with sqlite3.connect(self.db_path) as connection:
            self.assertEqual(
                0,
                connection.execute(
                    "SELECT COUNT(*) FROM news_items WHERE guid = 'abandoned-guid'"
                ).fetchone()[0],
            )

    def test_url_cache_retention_is_separate_from_article_history(self):
        now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "ALTER TABLE news_items ADD COLUMN delivery_status TEXT"
            )
            connection.execute(
                "ALTER TABLE news_items ADD COLUMN created_at TEXT"
            )
            connection.execute(
                "INSERT INTO news_items "
                "(pub_date, guid, title, link, related_news, delivery_status, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'sent', ?)",
                (
                    "Mon, 05 Nov 2026 00:00:00 GMT",
                    "ten-day-old",
                    "Ten day old",
                    "https://publisher.example/ten-day-old",
                    "[]",
                    (now - timedelta(days=10)).isoformat(),
                ),
            )
            connection.execute(
                """
                CREATE TABLE google_news_url_cache (
                    article_id TEXT PRIMARY KEY,
                    google_url TEXT NOT NULL,
                    resolved_url TEXT,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_error_code TEXT,
                    next_retry_at TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO google_news_url_cache "
                "(article_id, google_url, resolved_url, status, updated_at) "
                "VALUES ('ten-day-cache', 'https://news.google.com/x', "
                "'https://publisher.example/x', 'resolved', ?)",
                ((now - timedelta(days=10)).isoformat(),),
            )

        stats = self.module.apply_state_retention(
            [self.db_path],
            retention_days=30,
            url_cache_retention_days=7,
            now=now,
        )

        self.assertEqual(0, stats["items"])
        self.assertEqual(1, stats["url_cache"])
        with sqlite3.connect(self.db_path) as connection:
            self.assertEqual(
                1,
                connection.execute(
                    "SELECT COUNT(*) FROM news_items WHERE guid = 'ten-day-old'"
                ).fetchone()[0],
            )
            self.assertEqual(
                0,
                connection.execute(
                    "SELECT COUNT(*) FROM google_news_url_cache"
                ).fetchone()[0],
            )

    def test_url_cache_retention_days_is_bounded_and_validated(self):
        self.assertEqual(7, self.module.DEFAULT_URL_CACHE_RETENTION_DAYS)
        self.assertEqual(7, self.module.url_cache_retention_days())
        self.assertEqual(1, self.module.url_cache_retention_days("1"))
        self.assertEqual(365, self.module.url_cache_retention_days("365"))
        for invalid in ("0", "-1", "366", "nan", " 7"):
            with self.subTest(value=invalid):
                with self.assertRaisesRegex(
                    ValueError, "invalid_google_news_url_cache_retention_days"
                ):
                    self.module.url_cache_retention_days(invalid)

    def test_state_retention_is_idempotent_and_ignores_missing_files(self):
        now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        first = self.module.apply_state_retention(
            [self.db_path, str(Path(self.temp_dir.name) / "missing.db")],
            retention_days=14,
            now=now,
        )
        second = self.module.apply_state_retention(
            [self.db_path], retention_days=14, now=now
        )

        self.assertEqual(0, first["items"])
        self.assertEqual(0, second["items"])
        self.assertEqual(1, first["databases"])
        self.assertEqual(1, second["databases"])

    def test_message_is_abandoned_after_repeated_permanent_failures(self):
        self.assertTrue(
            self.module.reserve_delivery_with_messages(
                self.db_path, "poison-guid", "Title", "", ["message"]
            )
        )
        failure = RuntimeError("discord rejected the request")
        failure.error_code = "discord_http_400_api_240000"
        failure.attempt_count = 1

        def send(_content):
            raise failure

        for _ in range(self.module.MAX_DELIVERY_ATTEMPTS - 1):
            with self.assertRaises(RuntimeError):
                self.module.deliver_queued_item(self.db_path, "poison-guid", send)

        outcome = self.module.deliver_queued_item(self.db_path, "poison-guid", send)

        self.assertEqual(1, outcome.failed_count)
        self.assertEqual("discord_http_400_api_240000", outcome.last_error_code)
        with sqlite3.connect(self.db_path) as connection:
            article = connection.execute(
                "SELECT delivery_status FROM news_items WHERE guid = ?",
                ("poison-guid",),
            ).fetchone()
            message = connection.execute(
                "SELECT status, attempt_count, last_error_code "
                "FROM google_news_delivery_messages WHERE guid = ?",
                ("poison-guid",),
            ).fetchone()
        self.assertEqual(("failed",), article)
        self.assertEqual(
            ("failed", self.module.MAX_DELIVERY_ATTEMPTS, "discord_http_400_api_240000"),
            message,
        )
        self.assertEqual([], self.module.pending_delivery_guids(self.db_path))
        self.assertEqual(0, self.module.count_pending_deliveries(self.db_path))

    def test_exhausted_message_is_skipped_without_another_send(self):
        self.assertTrue(
            self.module.reserve_delivery_with_messages(
                self.db_path, "skipped-guid", "Title", "", ["message"]
            )
        )
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE google_news_delivery_messages SET attempt_count = ?, "
                "last_error_code = 'discord_http_400_api_240000' WHERE guid = ?",
                (self.module.MAX_DELIVERY_ATTEMPTS, "skipped-guid"),
            )

        send = mock.Mock(side_effect=AssertionError("must not send"))
        outcome = self.module.deliver_queued_item(
            self.db_path, "skipped-guid", send
        )

        send.assert_not_called()
        self.assertEqual(1, outcome.failed_count)
        self.assertEqual("max_attempts_exceeded", outcome.last_error_code)
        self.assertEqual([], self.module.pending_delivery_guids(self.db_path))

    def test_abandoned_item_does_not_block_other_pending_items(self):
        self.assertTrue(
            self.module.reserve_delivery_with_messages(
                self.db_path, "poison-guid", "Poison", "", ["message"]
            )
        )
        self.assertTrue(
            self.module.reserve_delivery_with_messages(
                self.db_path, "good-guid", "Good", "", ["message"]
            )
        )
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE google_news_delivery_messages SET attempt_count = ?, "
                "last_error_code = 'discord_http_400_api_240000' WHERE guid = ?",
                (self.module.MAX_DELIVERY_ATTEMPTS, "poison-guid"),
            )

        poison = self.module.deliver_queued_item(
            self.db_path, "poison-guid", mock.Mock()
        )
        self.assertEqual(1, poison.failed_count)
        self.assertEqual(["good-guid"], self.module.pending_delivery_guids(self.db_path))

        good = self.module.deliver_queued_item(
            self.db_path, "good-guid", lambda _content: "123456789012345678"
        )
        self.assertEqual(0, good.failed_count)
        with sqlite3.connect(self.db_path) as connection:
            statuses = dict(
                connection.execute(
                    "SELECT guid, delivery_status FROM news_items"
                ).fetchall()
            )
        self.assertEqual(
            {"poison-guid": "failed", "good-guid": "sent"}, statuses
        )

    def test_partially_delivered_item_is_marked_failed_after_abandonment(self):
        self.assertTrue(
            self.module.reserve_delivery_with_messages(
                self.db_path, "partial-guid", "Title", "", ["main", "related"]
            )
        )
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE google_news_delivery_messages SET attempt_count = ?, "
                "last_error_code = 'discord_http_400_api_240000' "
                "WHERE guid = ? AND sequence = ?",
                (self.module.MAX_DELIVERY_ATTEMPTS, "partial-guid", 1),
            )

        outcome = self.module.deliver_queued_item(
            self.db_path,
            "partial-guid",
            lambda _content: "123456789012345678",
        )

        self.assertEqual(1, outcome.failed_count)
        with sqlite3.connect(self.db_path) as connection:
            article = connection.execute(
                "SELECT delivery_status, discord_message_id FROM news_items "
                "WHERE guid = ?",
                ("partial-guid",),
            ).fetchone()
            messages = connection.execute(
                "SELECT sequence, status FROM google_news_delivery_messages "
                "WHERE guid = ? ORDER BY sequence",
                ("partial-guid",),
            ).fetchall()
        self.assertEqual(("failed", "123456789012345678"), article)
        self.assertEqual([(0, "sent"), (1, "failed")], messages)

    def test_transient_rate_limit_is_not_abandoned(self):
        self.assertTrue(
            self.module.reserve_delivery_with_messages(
                self.db_path, "limited-guid", "Title", "", ["message"]
            )
        )
        failure = RuntimeError("rate limited")
        failure.error_code = "discord_rate_limited"
        failure.attempt_count = 5

        with self.assertRaises(RuntimeError):
            self.module.deliver_queued_item(
                self.db_path,
                "limited-guid",
                lambda _content: (_ for _ in ()).throw(failure),
            )

        self.assertEqual(["limited-guid"], self.module.pending_delivery_guids(self.db_path))
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT status, attempt_count, last_error_code "
                "FROM google_news_delivery_messages WHERE guid = ?",
                ("limited-guid",),
            ).fetchone()
        self.assertEqual(("pending", 5, "discord_rate_limited"), row)


if __name__ == "__main__":
    unittest.main()
