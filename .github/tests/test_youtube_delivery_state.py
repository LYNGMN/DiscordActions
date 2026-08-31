import importlib
import sqlite3
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def load_module():
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        sys.modules.pop("youtube_delivery_state", None)
        return importlib.import_module("youtube_delivery_state")
    finally:
        sys.path.pop(0)


def video(video_id, published_at):
    return {"video_id": video_id, "published_at": published_at}


def full_video(video_id="video-atomic"):
    return {
        "published_at": "2026-09-01T00:00:00Z",
        "channel_title": "Channel",
        "channel_id": "channel-1",
        "title": "Atomic video",
        "video_id": video_id,
        "video_url": "https://youtu.be/{}".format(video_id),
        "description": "Description",
        "category_id": "22",
        "category_name": "People & Blogs",
        "duration": "1m 0s",
        "thumbnail_url": "https://i.ytimg.com/vi/{}/hqdefault.jpg".format(video_id),
        "tags": "",
        "live_broadcast_content": "none",
        "scheduled_start_time": "",
        "caption": "false",
        "source": "channels",
    }


def create_full_videos_table(connection):
    connection.execute(
        "CREATE TABLE videos ("
        "published_at TEXT, channel_title TEXT, channel_id TEXT, title TEXT, "
        "video_id TEXT PRIMARY KEY, video_url TEXT, description TEXT, "
        "category_id TEXT, category_name TEXT, duration TEXT, thumbnail_url TEXT, "
        "tags TEXT, live_broadcast_content TEXT, scheduled_start_time TEXT, "
        "caption TEXT, source TEXT, delivery_status TEXT NOT NULL DEFAULT 'sent', "
        "delivery_sequence INTEGER)"
    )


class YouTubeDeliveryStateTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.items = [
            video("newest", "2026-08-31T12:30:00Z"),
            video("oldest", "2026-08-31T10:00:00+00:00"),
            video("middle", "2026-08-31T11:15:00Z"),
        ]

    def test_missing_state_scheduled_mode_baselines_all_without_delivery(self):
        original = deepcopy(self.items)

        delivery, baseline = self.module.partition_youtube_items(
            self.items,
            baseline_only=True,
            manual_test=False,
        )

        self.assertEqual([], delivery)
        self.assertEqual(["middle", "oldest", "newest"], self.ids(baseline))
        self.assertEqual(original, self.items)

    def test_manual_mode_delivers_first_feed_item_and_baselines_the_rest(self):
        delivery, baseline = self.module.partition_youtube_items(
            self.items,
            baseline_only=True,
            manual_test=True,
        )

        self.assertEqual(["newest"], self.ids(delivery))
        self.assertEqual(["oldest", "middle"], self.ids(baseline))

    def test_normal_mode_delivers_oldest_feed_position_first(self):
        delivery, baseline = self.module.partition_youtube_items(
            self.items,
            baseline_only=False,
            manual_test=False,
        )

        self.assertEqual(["middle", "oldest", "newest"], self.ids(delivery))
        self.assertEqual([], baseline)

    def test_feed_newest_first_preserves_api_order(self):
        delivery, baseline = self.module.partition_youtube_items(
            self.items,
            baseline_only=False,
            manual_test=False,
            delivery_order="feed_newest_first",
        )

        self.assertEqual(["newest", "oldest", "middle"], self.ids(delivery))
        self.assertEqual([], baseline)

    def test_empty_input_is_safe(self):
        self.assertEqual(
            ([], []),
            self.module.partition_youtube_items([], False, False),
        )

    def test_invalid_delivery_order_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "delivery order"):
            self.module.partition_youtube_items(
                self.items, False, False, delivery_order="published_at"
            )

    def test_legacy_database_is_extended_without_losing_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "youtube.db")
            with sqlite3.connect(db_path) as connection:
                connection.execute(
                    "CREATE TABLE videos (video_id TEXT PRIMARY KEY, title TEXT)"
                )
                connection.execute(
                    "INSERT INTO videos (video_id, title) VALUES ('legacy', 'Legacy')"
                )

            self.module.initialize_delivery_state(db_path)

            with sqlite3.connect(db_path) as connection:
                row = connection.execute(
                    "SELECT video_id, title, delivery_status FROM videos"
                ).fetchone()
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            self.assertEqual(("legacy", "Legacy", "sent"), row)
            self.assertEqual("ok", integrity)

    def test_filtered_video_is_rechecked_only_when_filter_fingerprint_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "youtube.db")
            with sqlite3.connect(db_path) as connection:
                create_full_videos_table(connection)

            self.module.record_filtered_youtube_video(
                db_path,
                full_video("filtered-video"),
                "fingerprint-a",
            )

            self.assertTrue(
                self.module.is_youtube_item_handled(
                    db_path, "filtered-video", "fingerprint-a"
                )
            )
            self.assertFalse(
                self.module.is_youtube_item_handled(
                    db_path, "filtered-video", "fingerprint-b"
                )
            )

    def test_filtered_video_can_be_reserved_after_filter_change(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "youtube.db")
            with sqlite3.connect(db_path) as connection:
                create_full_videos_table(connection)

            video_data = full_video("filtered-video")
            self.module.record_filtered_youtube_video(
                db_path,
                video_data,
                "fingerprint-a",
            )
            self.module.queue_youtube_delivery(
                db_path,
                "filtered-video",
                [("primary", {"content": "now matched"})],
                video_data=video_data,
            )

            with sqlite3.connect(db_path) as connection:
                row = connection.execute(
                    "SELECT delivery_status, filter_fingerprint "
                    "FROM videos WHERE video_id = ?",
                    ("filtered-video",),
                ).fetchone()
            self.assertEqual(("pending", None), row)

    def test_switching_between_rss_and_api_does_not_resend_the_same_video_id(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "youtube.db")
            with sqlite3.connect(db_path) as connection:
                create_full_videos_table(connection)

            rss_video = full_video("shared-video")
            rss_video["source"] = "rss:channels"
            self.module.save_youtube_video(db_path, rss_video, delivery_status="sent")

            self.assertTrue(
                self.module.is_youtube_item_handled(
                    db_path,
                    "shared-video",
                    "new-filter-fingerprint",
                )
            )

    def test_delivery_targets_resume_at_exact_unsent_target(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "youtube.db")
            with sqlite3.connect(db_path) as connection:
                connection.execute(
                    "CREATE TABLE videos (video_id TEXT PRIMARY KEY, title TEXT)"
                )
                connection.execute(
                    "INSERT INTO videos (video_id, title) VALUES ('video-1', 'Video')"
                )
            self.module.initialize_delivery_state(db_path)
            self.module.queue_youtube_delivery(
                db_path,
                "video-1",
                [("primary", {"content": "plain"}), ("detail", {"embeds": []})],
            )

            self.module.mark_youtube_target_sent(
                db_path,
                "video-1",
                "primary",
                "123456789012345678",
                last_error_code="ambiguous_retry",
            )

            self.assertEqual(
                {"pending_count": 1, "ambiguous_retry_count": 1},
                self.module.youtube_delivery_metrics(db_path),
            )

            self.assertEqual(["video-1"], self.module.pending_youtube_video_ids(db_path))
            self.assertEqual(
                [("detail", {"embeds": []})],
                self.module.pending_youtube_targets(db_path, "video-1"),
            )
            self.assertFalse(self.module.finalize_youtube_delivery(db_path, "video-1"))

            self.module.mark_youtube_target_sent(
                db_path, "video-1", "detail", "223456789012345678"
            )
            self.assertTrue(self.module.finalize_youtube_delivery(db_path, "video-1"))
            self.assertEqual([], self.module.pending_youtube_video_ids(db_path))

    def test_failed_ambiguous_target_remains_pending_with_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "youtube.db")
            with sqlite3.connect(db_path) as connection:
                connection.execute("CREATE TABLE videos (video_id TEXT PRIMARY KEY)")
                connection.execute("INSERT INTO videos (video_id) VALUES ('video-1')")
            self.module.initialize_delivery_state(db_path)
            self.module.queue_youtube_delivery(
                db_path, "video-1", [("primary", {"content": "plain"})]
            )

            self.module.mark_youtube_target_failed(
                db_path,
                "video-1",
                "primary",
                "ambiguous_retry",
                attempt_count=2,
            )

            with sqlite3.connect(db_path) as connection:
                row = connection.execute(
                    "SELECT status, attempt_count, last_error_code "
                    "FROM youtube_delivery_targets WHERE video_id = 'video-1'"
                ).fetchone()
            self.assertEqual(("pending", 2, "ambiguous_retry"), row)
            self.assertEqual(
                {"pending_count": 1, "ambiguous_retry_count": 1},
                self.module.youtube_delivery_metrics(db_path),
            )

            self.module.mark_youtube_target_sent(
                db_path,
                "video-1",
                "primary",
                "123456789012345678",
            )
            self.assertEqual(
                {"pending_count": 1, "ambiguous_retry_count": 1},
                self.module.youtube_delivery_metrics(db_path),
            )

    def test_existing_target_payload_is_not_replaced_during_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "youtube.db")
            with sqlite3.connect(db_path) as connection:
                connection.execute("CREATE TABLE videos (video_id TEXT PRIMARY KEY)")
                connection.execute("INSERT INTO videos (video_id) VALUES ('video-1')")
            self.module.initialize_delivery_state(db_path)

            self.module.queue_youtube_delivery(
                db_path, "video-1", [("primary", {"content": "original"})]
            )
            self.module.queue_youtube_delivery(
                db_path, "video-1", [("primary", {"content": "changed"})]
            )

            self.assertEqual(
                [("primary", {"content": "original"})],
                self.module.pending_youtube_targets(db_path, "video-1"),
            )

    def test_new_video_and_delivery_targets_are_reserved_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "youtube.db")
            with sqlite3.connect(db_path) as connection:
                create_full_videos_table(connection)

            self.module.queue_youtube_delivery(
                db_path,
                "video-atomic",
                [("primary", {"content": "plain"})],
                video_data=full_video(),
            )

            with sqlite3.connect(db_path) as connection:
                video_row = connection.execute(
                    "SELECT title, delivery_status FROM videos WHERE video_id = ?",
                    ("video-atomic",),
                ).fetchone()
                target_row = connection.execute(
                    "SELECT target, status FROM youtube_delivery_targets "
                    "WHERE video_id = ?",
                    ("video-atomic",),
                ).fetchone()
            self.assertEqual(("Atomic video", "pending"), video_row)
            self.assertEqual(("primary", "pending"), target_row)

    def test_target_failure_rolls_back_new_video_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "youtube.db")
            with sqlite3.connect(db_path) as connection:
                create_full_videos_table(connection)
            self.module.initialize_delivery_state(db_path)
            with sqlite3.connect(db_path) as connection:
                connection.execute(
                    "CREATE TRIGGER fail_target_insert BEFORE INSERT "
                    "ON youtube_delivery_targets BEGIN "
                    "SELECT RAISE(ABORT, 'target failure'); END"
                )

            with self.assertRaises(sqlite3.IntegrityError):
                self.module.queue_youtube_delivery(
                    db_path,
                    "video-atomic",
                    [("primary", {"content": "plain"})],
                    video_data=full_video(),
                )

            with sqlite3.connect(db_path) as connection:
                row = connection.execute(
                    "SELECT video_id FROM videos WHERE video_id = ?",
                    ("video-atomic",),
                ).fetchone()
            self.assertIsNone(row)

    def test_search_checkpoint_uses_overlap_and_updates_only_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "youtube.db")
            with sqlite3.connect(db_path) as connection:
                connection.execute("CREATE TABLE videos (video_id TEXT PRIMARY KEY)")
            self.module.initialize_delivery_state(db_path)

            self.assertIsNone(self.module.get_search_published_after(db_path))
            self.module.mark_search_checkpoint(db_path, "2026-09-01T00:00:00Z")

            self.assertEqual(
                "2026-08-31T00:00:00Z",
                self.module.get_search_published_after(db_path, overlap_hours=24),
            )

    @staticmethod
    def ids(items):
        return [item["video_id"] for item in items]


if __name__ == "__main__":
    unittest.main()
