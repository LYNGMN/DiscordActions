import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def load_module():
    scripts_path = str(SCRIPTS_DIR)
    sys.path.insert(0, scripts_path)
    try:
        sys.modules.pop("run_events", None)
        return importlib.import_module("run_events")
    finally:
        sys.path.pop(0)


class RunEventsTests(unittest.TestCase):
    def setUp(self):
        self.events = load_module()
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.path = os.path.join(self.tempdir.name, "events", "run-events.jsonl")

    def read_records(self):
        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def test_item_ref_is_stable_short_and_distinct(self):
        first = self.events.item_ref("https://news.google.com/rss/articles/AAA")
        same = self.events.item_ref("https://news.google.com/rss/articles/AAA")
        other = self.events.item_ref("https://news.google.com/rss/articles/BBB")

        self.assertEqual(first, same)
        self.assertNotEqual(first, other)
        self.assertEqual(8, len(first))

    def test_emit_keeps_sorted_safe_fields_and_redacts_urls(self):
        with self.assertLogs("delivery_events", level="INFO") as captured:
            self.events.emit_event(
                "message_failed",
                profile="top_kr",
                code="http_400",
                url="https://discord.com/api/webhooks/1/secret",
                attempt=2,
                sequence=3,
            )

        line = captured.output[0]
        self.assertIn("event=message_failed", line)
        self.assertIn("profile=top_kr", line)
        self.assertIn("code=http_400", line)
        self.assertIn("attempt=2", line)
        self.assertNotIn("webhooks", line)
        self.assertNotIn("secret", line)
        self.assertLess(line.index("attempt="), line.index("code="))

    def test_jsonl_record_has_run_and_profile_context(self):
        env = {
            "RUN_EVENTS_PATH": self.path,
            "GITHUB_RUN_ID": "12345",
            "GOOGLE_NEWS_PROFILE_ID": "top_kr",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with self.assertLogs("delivery_events", level="INFO"):
                self.events.emit_event("item_skip", reason="duplicate", item="abc12345")
                self.events.emit_event("item_done", item="abc12345")

        records = self.read_records()
        self.assertEqual(2, len(records))
        self.assertEqual("12345", records[0]["run"])
        self.assertEqual("top_kr", records[0]["profile"])
        self.assertEqual("item_skip", records[0]["event"])
        self.assertEqual("duplicate", records[0]["reason"])
        self.assertIn("ts", records[0])
        self.assertNotIn(": ", records[0]["ts"])

    def test_explicit_profile_is_not_overwritten_by_the_environment(self):
        env = {"RUN_EVENTS_PATH": self.path, "GOOGLE_NEWS_PROFILE_ID": "top_us"}
        with mock.patch.dict(os.environ, env, clear=False), self.assertLogs(
            "delivery_events", level="INFO"
        ):
            self.events.emit_event("profile_result", profile="top_kr", status="success")

        records = self.read_records()
        self.assertEqual("top_kr", records[0]["profile"])

    def test_invalid_key_and_blank_values_are_skipped(self):
        with self.assertLogs("delivery_events", level="INFO") as captured:
            self.events.emit_event(
                "item_skip",
                reason="duplicate",
                **{"bad key": "value", "empty": ""},
            )

        self.assertNotIn("bad", captured.output[0])
        self.assertNotIn("empty", captured.output[0])

    def test_truncate_events_file_starts_an_empty_file(self):
        self.events.truncate_events_file(self.path)
        with mock.patch.dict(os.environ, {"RUN_EVENTS_PATH": self.path}, clear=False):
            with self.assertLogs("delivery_events", level="INFO"):
                self.events.emit_event("run_start", profiles=11)

        self.assertEqual(1, len(self.read_records()))
        self.events.truncate_events_file(self.path)
        self.assertEqual([], self.read_records())

    def test_missing_path_does_not_create_a_file(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RUN_EVENTS_PATH", None)
            with self.assertLogs("delivery_events", level="INFO"):
                self.events.emit_event("run_start", profiles=1)

        self.assertFalse(os.path.exists(self.path))


if __name__ == "__main__":
    unittest.main()
