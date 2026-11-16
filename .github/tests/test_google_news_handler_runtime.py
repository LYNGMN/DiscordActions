import importlib
import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def load_module():
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        sys.modules.pop("google_news_handler_runtime", None)
        return importlib.import_module("google_news_handler_runtime")
    finally:
        sys.path.pop(0)


class DeliveryError(Exception):
    def __init__(self, error_code):
        super().__init__(error_code)
        self.error_code = error_code


class GoogleNewsHandlerRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_delivers_only_up_to_the_limit(self):
        delivered = []

        result = self.module.deliver_queued_items(
            [("a", "A"), ("b", "B"), ("c", "C")],
            delivery_limit=2,
            deliver=delivered.append,
            profile_label="top_us",
            admin_webhook="https://discord.example/webhook",
            notify=lambda *args: self.fail("must not notify"),
        )

        self.assertEqual(["a", "b"], delivered)
        self.assertEqual(2, result.processed_count)
        self.assertFalse(result.failed)
        self.assertIsNone(result.error_code)

    def test_deadline_stops_without_an_admin_alert(self):
        delivered = []
        calls = []

        def deliver(guid):
            delivered.append(guid)
            if guid == "b":
                raise DeliveryError("run_deadline_exceeded")

        result = self.module.deliver_queued_items(
            [("a", "A"), ("b", "B"), ("c", "C")],
            delivery_limit=3,
            deliver=deliver,
            profile_label="top_us",
            admin_webhook="https://discord.example/webhook",
            notify=lambda *args: calls.append(args),
        )

        self.assertEqual(["a", "b"], delivered)
        self.assertEqual(1, result.processed_count)
        self.assertTrue(result.failed)
        self.assertEqual("run_deadline_exceeded", result.error_code)
        self.assertEqual([], calls)

    def test_permanent_failure_alerts_once_and_stops(self):
        calls = []

        def deliver(guid):
            raise DeliveryError("discord_http_400")

        result = self.module.deliver_queued_items(
            [("a", "A"), ("b", "B")],
            delivery_limit=2,
            deliver=deliver,
            profile_label="keyword_iu",
            admin_webhook="https://discord.example/webhook",
            notify=lambda *args: calls.append(args) or False,
        )

        self.assertEqual(0, result.processed_count)
        self.assertTrue(result.failed)
        self.assertEqual("discord_http_400", result.error_code)
        self.assertEqual(1, len(calls))
        self.assertEqual("Google News", calls[0][1])
        self.assertEqual("keyword_iu", calls[0][2])
        self.assertEqual("a", calls[0][3])
        self.assertEqual("discord_http_400", calls[0][4])

    def test_unknown_error_uses_the_profile_failure_code(self):
        def deliver(guid):
            raise RuntimeError("boom")

        result = self.module.deliver_queued_items(
            [("a", "A")],
            delivery_limit=1,
            deliver=deliver,
            profile_label="top_us",
            admin_webhook="",
            notify=lambda *args: False,
        )

        self.assertTrue(result.failed)
        self.assertEqual("profile_run_failed", result.error_code)

    def test_empty_queue_is_a_success(self):
        result = self.module.deliver_queued_items(
            [],
            delivery_limit=5,
            deliver=lambda guid: None,
            profile_label="top_us",
            admin_webhook="",
            notify=lambda *args: False,
        )

        self.assertEqual(0, result.processed_count)
        self.assertFalse(result.failed)


if __name__ == "__main__":
    unittest.main()
