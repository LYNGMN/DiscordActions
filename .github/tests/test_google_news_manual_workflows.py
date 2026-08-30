import unittest
from pathlib import Path


WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / "workflows"
WORKFLOW_PATHS = (
    WORKFLOWS_DIR / "googlenews-keyword_to_discord.yml",
    WORKFLOWS_DIR / "googlenews-top_to_discord.yml",
    WORKFLOWS_DIR / "googlenews-topic_to_discord.yml",
)
MANUAL_TEST_EXPRESSION = (
    "${{ github.event_name == 'workflow_dispatch' "
    "&& inputs.manual_test == true }}"
)


class GoogleNewsManualWorkflowTests(unittest.TestCase):
    def test_all_workflows_expose_safe_manual_test_input(self):
        for workflow_path in WORKFLOW_PATHS:
            with self.subTest(workflow=workflow_path.name):
                source = workflow_path.read_text(encoding="utf-8")

                self.assertIn("manual_test:", source)
                self.assertIn("type: boolean", source)
                self.assertIn("default: true", source)
                self.assertIn(
                    f"MANUAL_TEST_MODE: {MANUAL_TEST_EXPRESSION}",
                    source,
                )

    def test_ci_compiles_manual_test_module(self):
        source = (WORKFLOWS_DIR / "test.yml").read_text(encoding="utf-8")

        self.assertIn(
            ".github/scripts/google_news_manual_test.py",
            source,
        )


if __name__ == "__main__":
    unittest.main()
