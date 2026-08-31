import re
import unittest
from pathlib import Path


WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / "workflows"
WORKFLOW = WORKFLOWS_DIR / "googlenews-to-discord.yml"
CI_WORKFLOW = WORKFLOWS_DIR / "test.yml"
EXPECTED_WEBHOOK_SECRETS = (
    "DISCORD_WEBHOOK_GN_TOP_US",
    "DISCORD_WEBHOOK_GN_TOP_KR",
    "DISCORD_WEBHOOK_GN_TOP_JP",
    "DISCORD_WEBHOOK_GN_TOP_CN",
    "DISCORD_WEBHOOK_GN_TOPIC_KOREA",
    "DISCORD_WEBHOOK_GN_TOPIC_SEOUL",
    "DISCORD_WEBHOOK_GN_TOPIC_ENT",
    "DISCORD_WEBHOOK_GN_TOPIC_TECH",
    "DISCORD_WEBHOOK_GN_TOPIC_SCITECH",
    "DISCORD_WEBHOOK_GN_KEYWORD_NOCODE",
    "DISCORD_WEBHOOK_GN_KEYWORD_IU",
)
NEW_MODULES = (
    "delivery_admin_alert.py",
    "google_news_delivery_state.py",
    "google_news_discord_delivery.py",
    "google_news_dispatcher.py",
    "google_news_keyword_matcher.py",
    "google_news_manual_test.py",
    "google_news_profile_result.py",
    "google_news_profiles.py",
    "google_news_related_links.py",
    "google_news_request_guard.py",
    "google_news_url_resolver.py",
    "youtube_delivery_state.py",
    "youtube_discord_delivery.py",
    "youtube_video_source.py",
    "youtube_to_discord.py",
)


class GoogleNewsUnifiedWorkflowTests(unittest.TestCase):
    def source(self):
        return WORKFLOW.read_text(encoding="utf-8")

    def test_schedule_manual_input_and_concurrency_are_safe(self):
        source = self.source()
        self.assertIn("cron: '7,22,37,52 * * * *'", source)
        self.assertIn("timezone: 'Asia/Seoul'", source)
        self.assertIn("GOOGLE_NEWS_DELIVERY_ORDER", source)
        self.assertNotIn("cron: '7,37 * * * *'", source)
        self.assertIn("manual_test:", source)
        self.assertIn("type: boolean", source)
        self.assertIn("default: true", source)
        self.assertIn("group: google-news-to-discord", source)
        self.assertIn("cancel-in-progress: false", source)
        self.assertIn(
            "if: github.event_name == 'workflow_dispatch' || "
            "vars.GOOGLE_NEWS_SCHEDULE_ENABLED == 'true'",
            source,
        )

    def test_unified_workflow_maps_all_webhook_secrets(self):
        source = self.source()
        for secret_name in EXPECTED_WEBHOOK_SECRETS:
            self.assertIn("secrets.{}".format(secret_name), source)
        self.assertNotRegex(
            source,
            re.compile(r"https://discord(?:app)?\.com/api/webhooks/[0-9]+/"),
        )

    def test_webhook_secrets_are_scoped_only_to_the_dispatcher_step(self):
        source = self.source()
        dispatcher_index = source.index("- name: Run unified Google News dispatcher")
        summary_index = source.index("- name: Write safe run summary")
        before_dispatcher = source[:dispatcher_index]
        dispatcher_section = source[dispatcher_index:summary_index]

        self.assertNotIn("secrets.DISCORD_WEBHOOK_GN_", before_dispatcher)
        for secret_name in EXPECTED_WEBHOOK_SECRETS:
            self.assertIn("secrets.{}".format(secret_name), dispatcher_section)

    def test_dispatcher_is_the_only_google_news_execution_command(self):
        source = self.source()
        self.assertEqual(1, source.count(".github/scripts/google_news_dispatcher.py"))
        self.assertNotIn("googlenews-top_to_discord.py", source)
        self.assertNotIn("googlenews-topic_to_discord.py", source)
        self.assertNotIn("googlenews-keyword_to_discord.py", source)
        self.assertIn("--manual-test", source)

    def test_restore_uses_latest_completed_run_with_a_state_artifact(self):
        source = self.source()
        self.assertIn("status: 'completed'", source)
        self.assertIn("google-news-state", source)
        self.assertIn("artifact-id", source)
        self.assertIn("actions/download-artifact@v5", source)
        self.assertIn("merge-multiple: true", source)
        self.assertNotIn("status: 'success'", source)

    def test_restore_downloads_from_the_run_that_owns_the_artifact(self):
        source = self.source()
        self.assertIn(
            "run-id: ${{ steps.previous_state.outputs.source-run-id }}",
            source,
        )

    def test_restore_search_is_bounded_to_one_page_of_recent_runs(self):
        source = self.source()
        self.assertIn(
            "const { data: runPage } = await github.rest.actions.listWorkflowRuns",
            source,
        )
        self.assertIn("const runs = runPage.workflow_runs;", source)
        self.assertNotIn(
            "github.paginate(\n              github.rest.actions.listWorkflowRuns",
            source,
        )

    def test_state_is_uploaded_even_after_failure(self):
        source = self.source()
        upload_index = source.index("- name: Upload updated state")
        upload_section = source[upload_index:]
        self.assertIn("if: always()", upload_section)
        self.assertIn("retention-days: 90", upload_section)
        self.assertIn("path: .google-news-state/", upload_section)
        self.assertIn("include-hidden-files: true", upload_section)

    def test_ci_compiles_every_new_runtime_module_on_python_38(self):
        source = CI_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("python-version: '3.8'", source)
        for module_name in NEW_MODULES:
            self.assertIn(".github/scripts/{}".format(module_name), source)


if __name__ == "__main__":
    unittest.main()
