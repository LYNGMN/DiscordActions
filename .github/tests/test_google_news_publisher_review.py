import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from google_news_publisher_names import load_default_registry  # noqa: E402
from google_news_publisher_review import (  # noqa: E402
    backfill_unmapped_publishers,
    export_unmapped_publishers,
    record_unmapped_publisher,
)


class GoogleNewsPublisherReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.state_dir = Path(self.temporary_directory.name)
        self.db_path = self.state_dir / "top_kr.db"
        self.registry = load_default_registry()
        self.observed_at = datetime(2026, 9, 2, 1, 2, 3, tzinfo=timezone.utc)

    def test_unknown_domain_is_recorded_once_without_article_or_url_data(self):
        resolution = self.registry.resolve(
            "news.example.com",
            "https://news.example.com/story?id=secret",
        )

        first = record_unmapped_publisher(
            self.db_path,
            "top_kr",
            "article-guid:main",
            "main",
            resolution,
            observed_at=self.observed_at,
        )
        second = record_unmapped_publisher(
            self.db_path,
            "top_kr",
            "article-guid:main",
            "main",
            resolution,
            observed_at=self.observed_at,
        )

        self.assertTrue(first)
        self.assertFalse(second)
        with sqlite3.connect(self.db_path) as connection:
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(google_news_unmapped_publisher_occurrences)"
                )
            }
            row = connection.execute(
                "SELECT normalized_label, display_label, hostname, profile_id, location "
                "FROM google_news_unmapped_publisher_occurrences"
            ).fetchone()
        self.assertEqual(
            ("news.example.com", "news.example.com", "news.example.com", "top_kr", "main"),
            row,
        )
        self.assertNotIn("article_url", columns)
        self.assertNotIn("article_title", columns)
        self.assertNotIn("guid", columns)

    def test_mapped_and_human_publishers_are_not_recorded(self):
        mapped = self.registry.resolve("v.daum.net", "https://v.daum.net/v/1")
        human = self.registry.resolve("Example Press", "https://example.com/story")

        self.assertFalse(
            record_unmapped_publisher(
                self.db_path, "top_kr", "1", "main", mapped, self.observed_at
            )
        )
        self.assertFalse(
            record_unmapped_publisher(
                self.db_path, "top_kr", "2", "related", human, self.observed_at
            )
        )

    def test_backfill_reads_structured_history_without_duplicate_occurrences(self):
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "CREATE TABLE news_items (guid TEXT PRIMARY KEY, title TEXT, link TEXT, related_news TEXT)"
            )
            connection.execute(
                "INSERT INTO news_items VALUES (?, ?, ?, ?)",
                (
                    "private-guid",
                    "Main title - news.example.com",
                    "https://news.example.com/main?token=private",
                    json.dumps(
                        [
                            {
                                "title": "Related title",
                                "link": "https://media.example.org/story?secret=1",
                                "press": "media.example.org",
                            },
                            {
                                "title": "Known title",
                                "link": "https://v.daum.net/v/1",
                                "press": "v.daum.net",
                            },
                        ]
                    ),
                ),
            )

        self.assertEqual(
            2,
            backfill_unmapped_publishers(
                self.db_path, "top_kr", self.registry, self.observed_at
            ),
        )
        self.assertEqual(
            0,
            backfill_unmapped_publishers(
                self.db_path,
                "top_kr",
                self.registry,
                datetime(2026, 9, 3, 1, 2, 3, tzinfo=timezone.utc),
            ),
        )
        with sqlite3.connect(self.db_path) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM google_news_unmapped_publisher_occurrences"
            ).fetchone()[0]
            last_seen = connection.execute(
                "SELECT DISTINCT last_seen_at FROM "
                "google_news_unmapped_publisher_occurrences"
            ).fetchall()
            self.assertEqual("ok", connection.execute("PRAGMA integrity_check").fetchone()[0])
        self.assertEqual(2, count)
        self.assertEqual([(self.observed_at.isoformat(),)], last_seen)

    def test_export_is_deterministic_safe_and_excludes_newly_mapped_entries(self):
        for occurrence, label, hostname, location in (
            ("a", "z.example.net", "z.example.net", "related"),
            ("b", "a.example.org", "a.example.org", "main"),
            ("c", "a.example.org", "a.example.org", "related"),
        ):
            resolution = self.registry.resolve(label, "https://{}/story?secret=1".format(hostname))
            record_unmapped_publisher(
                self.db_path,
                "top_kr",
                occurrence,
                location,
                resolution,
                self.observed_at,
            )

        output_path = self.state_dir / "unmapped-google-news-publishers.json"
        payload = export_unmapped_publishers(
            self.state_dir,
            {"top_kr": "top_kr.db"},
            self.registry,
            output_path,
            generated_at=self.observed_at,
        )

        self.assertEqual(2, payload["unmapped_publisher_count"])
        self.assertEqual(
            ["a.example.org", "z.example.net"],
            [item["label"] for item in payload["publishers"]],
        )
        self.assertEqual(2, payload["publishers"][0]["occurrence_count"])
        serialized = output_path.read_text(encoding="utf-8")
        self.assertNotIn("secret", serialized)
        self.assertNotIn("private-guid", serialized)
        self.assertNotIn("Main title", serialized)

        custom_path = self.state_dir / "custom.json"
        custom_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "publishers": [
                        {
                            "canonical_name": "A Example",
                            "domains": ["a.example.org"],
                            "aliases": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        from google_news_publisher_names import PublisherRegistry

        updated_registry = PublisherRegistry.from_path(custom_path)
        updated = export_unmapped_publishers(
            self.state_dir,
            {"top_kr": "top_kr.db"},
            updated_registry,
            output_path,
            generated_at=self.observed_at,
        )
        self.assertEqual(["z.example.net"], [item["label"] for item in updated["publishers"]])


if __name__ == "__main__":
    unittest.main()
