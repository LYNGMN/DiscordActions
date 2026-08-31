import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "workflows" / "youtube_to_discord.yml"
CI_WORKFLOW = ROOT / "workflows" / "test.yml"
SCRIPT = ROOT / "scripts" / "youtube_to_discord.py"


class YouTubeWorkflowTests(unittest.TestCase):
    def source(self):
        return WORKFLOW.read_text(encoding="utf-8")

    def test_schedule_manual_input_and_concurrency_are_safe(self):
        source = self.source()

        self.assertIn("cron: '11,26,41,56 * * * *'", source)
        self.assertNotIn("cron: '0 * * * *'", source)
        self.assertIn("manual_test:", source)
        self.assertIn("default: true", source)
        self.assertIn("type: boolean", source)
        self.assertIn("group: youtube-to-discord", source)
        self.assertIn("cancel-in-progress: false", source)

    def test_restore_selects_a_real_unexpired_database_artifact(self):
        source = self.source()

        self.assertIn("status: 'completed'", source)
        self.assertIn("artifact.name === 'youtube_database'", source)
        self.assertIn("!artifact.expired", source)
        self.assertIn("core.setOutput('artifact-id'", source)
        self.assertIn("core.setOutput('source-run-id'", source)
        self.assertIn("artifact-ids: ${{ steps.previous_state.outputs.artifact-id }}", source)
        self.assertIn("run-id: ${{ steps.previous_state.outputs.source-run-id }}", source)
        self.assertNotIn("status: 'success'", source)

    def test_missing_scheduled_state_baselines_and_manual_mode_is_one_item(self):
        source = self.source()

        self.assertIn(
            "YOUTUBE_BASELINE_ONLY: ${{ github.event_name == 'schedule' "
            "&& steps.state.outputs.restored != 'true' }}",
            source,
        )
        self.assertIn(
            "YOUTUBE_MANUAL_TEST_MODE: ${{ github.event_name == 'workflow_dispatch' "
            "&& inputs.manual_test == true }}",
            source,
        )
        self.assertNotIn("touch youtube_videos.db", source)

    def test_state_upload_runs_even_when_delivery_fails(self):
        source = self.source()
        upload_index = source.index("- name: Upload updated database")
        upload_section = source[upload_index:]

        self.assertIn("if: always()", upload_section)
        self.assertIn("if-no-files-found: error", upload_section)

    def test_script_saves_baseline_before_delivery_and_exits_nonzero_on_error(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("partition_youtube_items(", source)
        self.assertIn("YOUTUBE_BASELINE_ONLY", source)
        self.assertIn("YOUTUBE_MANUAL_TEST_MODE", source)
        self.assertLess(
            source.index("for video in baseline_videos:"),
            source.index("for video in delivery_videos:"),
        )
        self.assertIn("sys.exit(1)", source)

    def test_ci_compiles_youtube_runtime_modules(self):
        source = CI_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn(".github/scripts/youtube_delivery_state.py", source)
        self.assertIn(".github/scripts/youtube_discord_delivery.py", source)
        self.assertIn(".github/scripts/youtube_to_discord.py", source)


if __name__ == "__main__":
    unittest.main()
