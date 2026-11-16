import re
import unittest
from pathlib import Path


WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / "workflows"
WORKFLOW = WORKFLOWS_DIR / "googlenews-to-discord.yml"
MANUAL_WORKFLOW = WORKFLOWS_DIR / "googlenews-manual-test.yml"
HEALTH_WORKFLOW = WORKFLOWS_DIR / "googlenews-health.yml"
RESET_WORKFLOW = WORKFLOWS_DIR / "googlenews-reset.yml"
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
def step_block(source: str, name: str) -> str:
    marker = "- name: {}".format(name)
    start = source.index(marker)
    end = source.find("\n      - name:", start + len(marker))
    return source[start:] if end == -1 else source[start:end]




class GoogleNewsUnifiedWorkflowTests(unittest.TestCase):
    def source(self):
        return WORKFLOW.read_text(encoding="utf-8")

    def test_scheduled_workflow_accepts_external_dispatch(self):
        source = self.source()
        self.assertIn("cron: '*/15 * * * *'", source)
        self.assertNotIn("timezone:", source)
        self.assertIn("GOOGLE_NEWS_DELIVERY_ORDER", source)
        self.assertIn("workflow_dispatch:", source)
        self.assertNotIn("inputs:", source)
        self.assertNotIn("manual_test:", source)
        self.assertNotIn("--manual-test", source)
        self.assertNotIn("validate_only:", source)
        self.assertIn("group: google-news-to-discord", source)
        self.assertIn("cancel-in-progress: false", source)
        self.assertNotIn("GOOGLE_NEWS_SCHEDULE_ENABLED", source)

    def test_unified_workflow_maps_all_webhook_secrets(self):
        source = self.source()
        for secret_name in EXPECTED_WEBHOOK_SECRETS:
            self.assertIn("secrets.{}".format(secret_name), source)
        self.assertNotRegex(
            source,
            re.compile(r"https://discord(?:app)?\.com/api/webhooks/[0-9]+/"),
        )

    def test_unified_workflow_maps_common_filter_language_and_timezone_settings(self):
        source = self.source()
        for setting in (
            "FEED_DATE_FILTER",
            "FEED_KEYWORD_FILTER",
            "FEED_KEYWORD_SCOPE",
            "FEED_TIMEZONE",
            "FEED_COUNTRY",
            "DISPLAY_LANGUAGE",
        ):
            self.assertIn("{}:".format(setting), source)

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
        self.assertNotIn("--manual-test", source)

    def test_restore_uses_latest_completed_run_with_a_state_artifact(self):
        source = self.source()
        self.assertIn("status: 'completed'", source)
        self.assertIn("'googlenews-to-discord.yml'", source)
        self.assertIn("'googlenews-manual-test.yml'", source)
        self.assertIn("new Date(right.created_at) - new Date(left.created_at)", source)
        self.assertIn("google-news-state", source)
        self.assertIn("artifact-id", source)
        self.assertRegex(source, r"actions/download-artifact@[0-9a-f]{40}  # v8")
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
        self.assertIn("const runs = [];", source)
        self.assertIn("runs.push(...runPage.workflow_runs);", source)
        self.assertNotIn(
            "github.paginate(\n              github.rest.actions.listWorkflowRuns",
            source,
        )

    def test_state_is_uploaded_even_after_failure(self):
        source = self.source()
        upload_section = step_block(source, "Upload updated state")
        self.assertIn("if: always()", upload_section)
        self.assertIn("retention-days: 3", upload_section)
        self.assertIn("path: .google-news-state/", upload_section)
        self.assertIn("include-hidden-files: true", upload_section)

    def test_state_restore_failure_does_not_publish_empty_state(self):
        for workflow, upload_name in (
            (WORKFLOW, "Upload updated state"),
            (MANUAL_WORKFLOW, "Upload updated state"),
            (RESET_WORKFLOW, "Upload reset state"),
        ):
            with self.subTest(workflow=workflow.name):
                source = workflow.read_text(encoding="utf-8")
                self.assertIn("id: restore_state", source)
                self.assertIn("id: retry_restore", source)
                self.assertIn("Fail when state restore failed", source)
                upload_section = step_block(source, upload_name)
                self.assertIn(
                    "steps.previous_state.outcome == 'success'", upload_section
                )
                self.assertIn(
                    "steps.restore_state.outcome == 'success'", upload_section
                )
                self.assertIn(
                    "steps.retry_restore.outcome == 'success'", upload_section
                )
                self.assertIn(
                    "steps.previous_state.outputs.artifact-id == ''", upload_section
                )

    def test_scheduled_and_manual_workflows_upload_safe_publisher_review(self):
        for workflow in (WORKFLOW, MANUAL_WORKFLOW):
            with self.subTest(workflow=workflow.name):
                source = workflow.read_text(encoding="utf-8")
                self.assertIn(
                    "name: google-news-unmapped-publishers", source
                )
                self.assertIn(
                    "path: .google-news-state/unmapped-google-news-publishers.json",
                    source,
                )
                self.assertIn("retention-days: 90", source)
                self.assertIn("Unmapped publishers:", source)
                self.assertIn("New unmapped publishers:", source)

    def test_scheduled_and_manual_summaries_show_only_safe_failure_fields(self):
        for workflow in (WORKFLOW, MANUAL_WORKFLOW):
            with self.subTest(workflow=workflow.name):
                source = workflow.read_text(encoding="utf-8")
                self.assertIn("Failed profiles", source)
                self.assertIn("item.profile_id", source)
                self.assertIn("item.error_code", source)
                self.assertIn("item.pending_count", source)
                self.assertNotIn("error.message", source)
                self.assertNotIn("response.body", source)

    def test_ci_compiles_every_script_and_runs_static_checks(self):
        source = CI_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("python-version: '3.12'", source)
        self.assertIn("python -m compileall -q .github/scripts", source)
        self.assertIn("ruff check .github/scripts .github/tests", source)
        self.assertIn("yamllint -c .yamllint .github/workflows", source)
        self.assertIn("node --test ops/state-trigger/test/*.test.mjs", source)


    def test_summaries_ignore_a_stale_run_summary(self):
        for workflow in (WORKFLOW, MANUAL_WORKFLOW):
            with self.subTest(workflow=workflow.name):
                source = workflow.read_text(encoding="utf-8")
                self.assertIn("summary.run_id", source)
                self.assertIn("context.runId", source)
                self.assertIn("No run summary was produced for this run.", source)

    def test_summaries_show_a_backlog_table(self):
        for workflow in (WORKFLOW, MANUAL_WORKFLOW):
            with self.subTest(workflow=workflow.name):
                source = workflow.read_text(encoding="utf-8")
                self.assertIn("const backlogProfiles", source)
                self.assertIn("item.pending_count >= 100", source)
                self.assertIn("addHeading('Backlog', 2)", source)

    def test_state_upload_is_retried_once_and_fails_closed(self):
        for workflow in (WORKFLOW, MANUAL_WORKFLOW):
            with self.subTest(workflow=workflow.name):
                source = workflow.read_text(encoding="utf-8")
                self.assertIn("id: upload_state", source)
                self.assertIn("continue-on-error: true", source)
                self.assertIn("Retry state upload", source)
                self.assertIn("steps.upload_state.outcome == 'failure'", source)
                self.assertIn("overwrite: true", source)
                self.assertIn("Note recovered state upload", source)
                self.assertIn("Fail when state upload failed", source)
                self.assertIn("exit 1", source)

    def test_run_budget_is_configured_and_reported(self):
        for workflow in (WORKFLOW, MANUAL_WORKFLOW):
            with self.subTest(workflow=workflow.name):
                source = workflow.read_text(encoding="utf-8")
                self.assertIn("GOOGLE_NEWS_RUN_BUDGET_SECONDS", source)
                self.assertIn("time_budget_exhausted", source)
                self.assertIn("Time budget reached for", source)

    def test_reset_workflow_is_guarded_and_restores_state(self):
        source = RESET_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("Google News Backlog Reset", source)
        self.assertIn("confirmation", source)
        self.assertIn('"$CONFIRMATION" != "RESET"', source)
        self.assertIn("google_news_reset.py", source)
        self.assertIn("name: google-news-state", source)
        self.assertIn("overwrite: true", source)
        self.assertIn("'googlenews-reset.yml'", source)
        self.assertIn("if: failure()", source)

    def test_url_cache_retention_is_configured(self):
        for workflow in (WORKFLOW, MANUAL_WORKFLOW):
            with self.subTest(workflow=workflow.name):
                source = workflow.read_text(encoding="utf-8")
                self.assertIn("GOOGLE_NEWS_URL_CACHE_RETENTION_DAYS", source)
                self.assertIn("|| '7'", source)

    def test_auto_backlog_expiry_is_configured_and_reported(self):
        for workflow in (WORKFLOW, MANUAL_WORKFLOW):
            with self.subTest(workflow=workflow.name):
                source = workflow.read_text(encoding="utf-8")
                self.assertIn("GOOGLE_NEWS_BACKLOG_LIMIT", source)
                self.assertIn("GOOGLE_NEWS_BACKLOG_AGE_DAYS", source)
                self.assertIn("summary.backlog_expired", source)
                self.assertIn("Auto-expired backlog", source)
                self.assertIn("'Auto-expired backlog', 2", source)

    def test_restore_lists_include_backlog_reset(self):
        for workflow in (WORKFLOW, MANUAL_WORKFLOW, RESET_WORKFLOW):
            with self.subTest(workflow=workflow.name):
                source = workflow.read_text(encoding="utf-8")
                self.assertIn("'googlenews-reset.yml'", source)

    def test_health_workflow_alerts_when_scheduled_runs_stop(self):
        source = HEALTH_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("cron: '0 */6 * * *'", source)
        self.assertIn("workflow_dispatch:", source)
        self.assertIn("googlenews-to-discord.yml", source)
        self.assertIn("youtube_to_discord.yml", source)
        self.assertIn("status: 'completed'", source)
        self.assertIn("per_page: 5", source)
        self.assertIn("GOOGLE_NEWS_HEALTH_MAX_AGE_HOURS", source)
        self.assertIn("latestSuccess", source)
        self.assertIn("actions: read", source)
        self.assertIn("secrets.DISCORD_WEBHOOK_ADMIN", source)
        self.assertIn("fetch(webhook", source)
        self.assertIn("allowed_mentions", source)
        self.assertNotIn("console.log(webhook", source)

    def test_workflows_notify_admin_on_failure(self):
        for workflow in (WORKFLOW, MANUAL_WORKFLOW):
            with self.subTest(workflow=workflow.name):
                source = workflow.read_text(encoding="utf-8")
                self.assertIn("Notify admin of failed run", source)
                self.assertIn("if: failure()", source)
                self.assertIn("secrets.DISCORD_WEBHOOK_ADMIN", source)
                self.assertIn("type(error).__name__", source)
                self.assertNotIn("print(webhook", source)

    def test_repeated_failure_alerts_are_throttled(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("id: alert_gate", source)
        self.assertIn("previous.conclusion === 'failure'", source)
        self.assertIn("60 * 60 * 1000", source)
        self.assertIn("steps.alert_gate.outputs.notify == 'true'", source)
        self.assertIn("Skipping duplicate admin alert", source)


if __name__ == "__main__":
    unittest.main()
