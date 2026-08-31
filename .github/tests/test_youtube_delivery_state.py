import importlib
import sys
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
        self.assertEqual(["oldest", "middle", "newest"], self.ids(baseline))
        self.assertEqual(original, self.items)

    def test_manual_mode_delivers_only_newest_and_baselines_the_rest(self):
        delivery, baseline = self.module.partition_youtube_items(
            self.items,
            baseline_only=True,
            manual_test=True,
        )

        self.assertEqual(["newest"], self.ids(delivery))
        self.assertEqual(["oldest", "middle"], self.ids(baseline))

    def test_normal_mode_delivers_all_in_publication_order(self):
        delivery, baseline = self.module.partition_youtube_items(
            self.items,
            baseline_only=False,
            manual_test=False,
        )

        self.assertEqual(["oldest", "middle", "newest"], self.ids(delivery))
        self.assertEqual([], baseline)

    def test_empty_input_is_safe(self):
        self.assertEqual(
            ([], []),
            self.module.partition_youtube_items([], False, False),
        )

    def test_missing_or_invalid_publication_date_is_rejected(self):
        for item in ({"video_id": "missing"}, video("invalid", "not-a-date")):
            with self.subTest(item=item), self.assertRaisesRegex(
                ValueError, "published_at"
            ):
                self.module.partition_youtube_items([item], False, False)

    @staticmethod
    def ids(items):
        return [item["video_id"] for item in items]


if __name__ == "__main__":
    unittest.main()
