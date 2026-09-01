import unittest
from pathlib import Path


WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / "workflows"
UNIFIED_WORKFLOW = WORKFLOWS_DIR / "googlenews-to-discord.yml"
REMOVED_WORKFLOWS = (
    "googlenews-keyword_to_discord.yml",
    "googlenews-top_to_discord.yml",
    "googlenews-topic_to_discord.yml",
    "keepalive.yml",
)


class GoogleNewsManualWorkflowTests(unittest.TestCase):
    def test_unified_workflow_exposes_safe_manual_test_inputs(self):
        source = UNIFIED_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("manual_test:", source)
        self.assertIn("validate_only:", source)
        self.assertGreaterEqual(source.count("type: boolean"), 2)
        self.assertGreaterEqual(source.count("default: true"), 2)

    def test_ci_compiles_manual_test_module(self):
        source = (WORKFLOWS_DIR / "test.yml").read_text(encoding="utf-8")

        self.assertIn(
            ".github/scripts/google_news_manual_test.py",
            source,
        )

    def test_obsolete_and_blocked_workflows_are_removed(self):
        for workflow_name in REMOVED_WORKFLOWS:
            with self.subTest(workflow=workflow_name):
                self.assertFalse((WORKFLOWS_DIR / workflow_name).exists())

    def test_unified_google_news_workflow_prevents_overlapping_runs(self):
        source = UNIFIED_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("concurrency:", source)
        self.assertIn("group: google-news-to-discord", source)
        self.assertIn("cancel-in-progress: false", source)


if __name__ == "__main__":
    unittest.main()
