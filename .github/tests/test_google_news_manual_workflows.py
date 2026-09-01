import unittest
from pathlib import Path


WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / "workflows"
ROOT = Path(__file__).resolve().parents[2]
UNIFIED_WORKFLOW = WORKFLOWS_DIR / "googlenews-to-discord.yml"
MANUAL_WORKFLOW = WORKFLOWS_DIR / "googlenews-manual-test.yml"
REMOVED_WORKFLOWS = (
    "googlenews-keyword_to_discord.yml",
    "googlenews-top_to_discord.yml",
    "googlenews-topic_to_discord.yml",
    "keepalive.yml",
)


class GoogleNewsManualWorkflowTests(unittest.TestCase):
    def test_manual_workflow_exposes_profile_choice_and_no_schedule(self):
        source = MANUAL_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("name: Google News Manual Delivery Test", source)
        self.assertIn("workflow_dispatch:", source)
        self.assertNotIn("schedule:", source)
        self.assertIn("profile:", source)
        self.assertIn("type: choice", source)
        self.assertIn("default: top_kr", source)
        for profile_id in (
            "all",
            "top_us",
            "top_kr",
            "top_jp",
            "top_cn",
            "topic_korea",
            "topic_seoul",
            "topic_ent",
            "topic_tech",
            "topic_scitech",
            "keyword_nocode",
            "keyword_iu",
        ):
            self.assertIn("- {}".format(profile_id), source)
        self.assertIn("up to 11", source)
        self.assertIn("최대 11", source)

    def test_manual_workflow_selects_one_profile_or_all_and_sends_real_messages(self):
        source = MANUAL_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("--manual-test", source)
        self.assertIn("--profile-id", source)
        self.assertIn("inputs.profile", source)
        self.assertNotIn("--validate-only", source)

    def test_scheduled_and_manual_workflows_share_state_and_concurrency(self):
        scheduled = UNIFIED_WORKFLOW.read_text(encoding="utf-8")
        manual = MANUAL_WORKFLOW.read_text(encoding="utf-8")

        for source in (scheduled, manual):
            self.assertIn("group: google-news-to-discord", source)
            self.assertIn("cancel-in-progress: false", source)
            self.assertIn("'googlenews-to-discord.yml'", source)
            self.assertIn("'googlenews-manual-test.yml'", source)
            self.assertIn("new Date(right.created_at) - new Date(left.created_at)", source)
            self.assertIn("name: google-news-state", source)
            self.assertIn("if: always()", source)

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

    def test_english_and_korean_guides_explain_real_delivery_limits(self):
        english = (ROOT / "README.md").read_text(encoding="utf-8")
        korean = (ROOT / "README.ko.md").read_text(encoding="utf-8")

        for source in (english, korean):
            self.assertIn("Google News Manual Delivery Test", source)
            self.assertIn("YouTube Manual Delivery Test", source)
            self.assertIn("top_kr", source)
            self.assertIn("11", source)
        self.assertIn("real Discord messages", english)
        self.assertIn("one primary message and one detail message", english)
        self.assertIn("실제 Discord", korean)
        self.assertIn("기본 메시지 1개와 상세 메시지 1개", korean)


if __name__ == "__main__":
    unittest.main()
