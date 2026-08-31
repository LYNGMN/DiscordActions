import importlib
import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def load_module():
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        sys.modules.pop("delivery_admin_alert", None)
        return importlib.import_module("delivery_admin_alert")
    finally:
        sys.path.pop(0)


class Response:
    def raise_for_status(self):
        return None


class AdminAlertTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_missing_admin_webhook_is_a_noop(self):
        calls = []
        self.assertFalse(
            self.module.notify_admin(
                "", "Google News", "keyword_iu", "secret-guid", "final_failure",
                post=lambda *args, **kwargs: calls.append((args, kwargs)),
            )
        )
        self.assertEqual([], calls)

    def test_alert_contains_only_safe_hash_and_actions_link(self):
        calls = []

        result = self.module.notify_admin(
            "https://discord.example/secret-webhook",
            "YouTube",
            "channel",
            "https://example.com/watch?v=private-query",
            "ambiguous_retry",
            actions_url="https://github.com/owner/repo/actions/runs/123",
            post=lambda *args, **kwargs: calls.append((args, kwargs)) or Response(),
        )

        self.assertTrue(result)
        self.assertEqual(1, len(calls))
        posted_url = calls[0][0][0]
        content = calls[0][1]["json"]["content"]
        self.assertEqual("https://discord.example/secret-webhook", posted_url)
        self.assertIn("YouTube", content)
        self.assertIn("channel", content)
        self.assertIn("ambiguous_retry", content)
        self.assertIn("https://github.com/owner/repo/actions/runs/123", content)
        self.assertNotIn("private-query", content)
        self.assertNotIn("secret-webhook", content)

    def test_alert_failure_never_masks_original_delivery_failure(self):
        self.assertFalse(
            self.module.notify_admin(
                "https://discord.example/webhook",
                "Google News",
                "top_us",
                "guid",
                "final_failure",
                post=lambda *args, **kwargs: (_ for _ in ()).throw(OSError("down")),
            )
        )


if __name__ == "__main__":
    unittest.main()
