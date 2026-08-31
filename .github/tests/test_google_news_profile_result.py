import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def load_result_module():
    scripts_path = str(SCRIPTS_DIR)
    sys.path.insert(0, scripts_path)
    try:
        sys.modules.pop("google_news_profile_result", None)
        return importlib.import_module("google_news_profile_result")
    finally:
        sys.path.pop(0)


class GoogleNewsProfileResultTests(unittest.TestCase):
    def setUp(self):
        self.module = load_result_module()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "nested" / "top_us.json"

    def test_writes_only_the_sanitized_result_contract(self):
        payload = self.module.write_profile_result(
            str(self.path),
            "top_us",
            "success",
            2,
            1,
            None,
        )

        self.assertEqual(
            {
                "profile_id": "top_us",
                "status": "success",
                "processed_count": 2,
                "pending_count": 1,
                "ambiguous_retry_count": 0,
                "error_code": None,
            },
            payload,
        )
        self.assertEqual(payload, json.loads(self.path.read_text(encoding="utf-8")))
        self.assertEqual([], list(self.path.parent.glob("*.tmp")))

    def test_rejects_unsafe_ids_statuses_counts_and_error_codes(self):
        cases = (
            ("../top", "success", 0, 0, None),
            ("top_us", "unknown", 0, 0, None),
            ("top_us", "success", -1, 0, None),
            ("top_us", "failed", 0, 0, "https://secret.example/value"),
        )
        for profile_id, status, processed, pending, error_code in cases:
            with self.subTest(profile_id=profile_id, status=status, error_code=error_code):
                with self.assertRaises(ValueError):
                    self.module.write_profile_result(
                        str(self.path),
                        profile_id,
                        status,
                        processed,
                        pending,
                        error_code,
                    )

    def test_replaces_an_existing_result_atomically(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"stale": true}', encoding="utf-8")

        self.module.write_profile_result(
            str(self.path), "top_us", "skipped", 0, 0, "circuit_open"
        )

        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual("skipped", payload["status"])
        self.assertEqual("circuit_open", payload["error_code"])


if __name__ == "__main__":
    unittest.main()
