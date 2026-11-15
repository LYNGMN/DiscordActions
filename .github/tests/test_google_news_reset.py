import importlib
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def load_module(name):
    scripts_path = str(SCRIPTS_DIR)
    sys.path.insert(0, scripts_path)
    try:
        sys.modules.pop(name, None)
        return importlib.import_module(name)
    finally:
        sys.path.pop(0)


class GoogleNewsResetTests(unittest.TestCase):
    def setUp(self):
        self.delivery = load_module("google_news_delivery_state")
        self.reset = load_module("google_news_reset")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.state_dir = str(Path(self.temp_dir.name) / "state")
        Path(self.state_dir).mkdir(parents=True, exist_ok=True)
        self.alpha = SimpleNamespace(
            profile_id="alpha",
            state_db="alpha.db",
            webhook_env="WEBHOOK_A",
        )
        self.beta = SimpleNamespace(
            profile_id="beta",
            state_db="beta.db",
            webhook_env="WEBHOOK_B",
        )
        self.env = {
            "WEBHOOK_A": "https://discord.com/api/webhooks/1/token-a",
            "WEBHOOK_B": "https://discord.com/api/webhooks/2/token-b",
        }
        self.now = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)

    def database_path(self, profile):
        return str(Path(self.state_dir) / profile.state_db)

    def add_pending(self, profile, guid):
        with sqlite3.connect(self.database_path(profile)) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS news_items ("
                "pub_date TEXT, guid TEXT PRIMARY KEY, title TEXT, "
                "link TEXT, related_news TEXT)"
            )
        self.assertTrue(
            self.delivery.reserve_delivery_with_messages(
                self.database_path(profile),
                guid,
                "Title {}".format(guid),
                "https://publisher.example/{}".format(guid),
                ["message"],
            )
        )

    def add_sent(self, profile, guid):
        self.add_pending(profile, guid)
        with sqlite3.connect(self.database_path(profile)) as connection:
            connection.execute(
                "UPDATE news_items SET delivery_status = 'sent' WHERE guid = ?",
                (guid,),
            )
            connection.execute(
                "UPDATE google_news_delivery_messages SET status = 'sent' "
                "WHERE guid = ?",
                (guid,),
            )

    def test_reset_expires_pending_and_sends_one_divider(self):
        self.add_pending(self.alpha, "alpha-1")
        self.add_pending(self.alpha, "alpha-2")
        self.add_sent(self.beta, "beta-sent")
        sent = []

        summary = self.reset.reset_state(
            self.state_dir,
            [self.alpha, self.beta],
            self.env,
            divider_scope="pending",
            send_divider=True,
            confirm=True,
            webhook_sender=lambda url, content: sent.append((url, content)),
            now=self.now,
        )

        self.assertEqual(2, summary["total_expired"])
        self.assertEqual("sent", summary["profiles"][0]["divider"])
        self.assertEqual("skipped", summary["profiles"][1]["divider"])
        self.assertEqual(
            [(self.env["WEBHOOK_A"], "---")], sent
        )
        self.assertEqual(
            0, self.delivery.count_unfinished_deliveries(self.database_path(self.alpha))
        )
        with sqlite3.connect(self.database_path(self.alpha)) as connection:
            self.assertEqual(
                0,
                connection.execute(
                    "SELECT COUNT(*) FROM google_news_delivery_messages"
                ).fetchone()[0],
            )
        summary_path = Path(self.state_dir) / "backlog-reset.json"
        self.assertEqual(summary, json.loads(summary_path.read_text(encoding="utf-8")))
        self.assertEqual(
            self.now.isoformat(),
            self.delivery.read_state_metadata(
                self.database_path(self.alpha), "backlog_reset_at"
            ),
        )

    def test_second_reset_does_not_resend_the_divider(self):
        self.add_pending(self.alpha, "alpha-1")
        sent = []

        self.reset.reset_state(
            self.state_dir,
            [self.alpha],
            self.env,
            send_divider=True,
            confirm=True,
            webhook_sender=lambda url, content: sent.append((url, content)),
            now=self.now,
        )
        second = self.reset.reset_state(
            self.state_dir,
            [self.alpha],
            self.env,
            send_divider=True,
            confirm=True,
            webhook_sender=lambda url, content: sent.append((url, content)),
            now=self.now,
        )

        self.assertEqual(1, len(sent))
        self.assertEqual("already_sent", second["profiles"][0]["divider"])

    def test_all_scope_sends_divider_to_a_profile_without_backlog(self):
        self.add_sent(self.beta, "beta-sent")
        sent = []

        summary = self.reset.reset_state(
            self.state_dir,
            [self.beta],
            self.env,
            divider_scope="all",
            send_divider=True,
            confirm=True,
            webhook_sender=lambda url, content: sent.append((url, content)),
            now=self.now,
        )

        self.assertEqual(0, summary["total_expired"])
        self.assertEqual("sent", summary["profiles"][0]["divider"])
        self.assertEqual([(self.env["WEBHOOK_B"], "---")], sent)

    def test_dry_run_changes_nothing_and_sends_nothing(self):
        self.add_pending(self.alpha, "alpha-1")
        sent = []

        summary = self.reset.reset_state(
            self.state_dir,
            [self.alpha],
            self.env,
            send_divider=True,
            dry_run=True,
            webhook_sender=lambda url, content: sent.append((url, content)),
            now=self.now,
        )

        self.assertEqual(1, summary["total_expired"])
        self.assertEqual("dry_run", summary["profiles"][0]["divider"])
        self.assertEqual([], sent)
        self.assertEqual(
            1, self.delivery.count_unfinished_deliveries(self.database_path(self.alpha))
        )
        self.assertFalse((Path(self.state_dir) / "backlog-reset.json").exists())

    def test_missing_webhook_is_reported(self):
        self.add_pending(self.alpha, "alpha-1")

        summary = self.reset.reset_state(
            self.state_dir,
            [self.alpha],
            {},
            send_divider=True,
            confirm=True,
            webhook_sender=lambda url, content: None,
            now=self.now,
        )

        self.assertEqual("missing_webhook", summary["profiles"][0]["divider"])
        self.assertEqual("missing_webhook", summary["profiles"][0]["error"])

    def test_reset_requires_confirmation(self):
        with self.assertRaisesRegex(ValueError, "reset_confirmation_required"):
            self.reset.reset_state(
                self.state_dir,
                [self.alpha],
                self.env,
                confirm=False,
                now=self.now,
            )


if __name__ == "__main__":
    unittest.main()
