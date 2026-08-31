import importlib
import sys
import unittest
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "workflows" / "youtube_to_discord.yml"
CI_WORKFLOW = ROOT / "workflows" / "test.yml"
SCRIPT = ROOT / "scripts" / "youtube_to_discord.py"


def load_youtube_script():
    google_api = ModuleType("googleapiclient")
    discovery = ModuleType("googleapiclient.discovery")
    discovery.build = lambda *args, **kwargs: None
    google_api.discovery = discovery
    isodate = ModuleType("isodate")
    isodate.parse_duration = lambda value: None
    stubs = {
        "googleapiclient": google_api,
        "googleapiclient.discovery": discovery,
        "isodate": isodate,
    }
    previous = {name: sys.modules.get(name) for name in stubs}
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        sys.modules.update(stubs)
        sys.modules.pop("youtube_to_discord", None)
        return importlib.import_module("youtube_to_discord")
    finally:
        sys.path.pop(0)
        for name, module in previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


class FailingRequest:
    def execute(self):
        raise OSError("redacted API failure")


class FailingVideosResource:
    def list(self, **kwargs):
        return FailingRequest()


class FailingYouTubeClient:
    def videos(self):
        return FailingVideosResource()


class YouTubeWorkflowTests(unittest.TestCase):
    def source(self):
        return WORKFLOW.read_text(encoding="utf-8")

    def test_schedule_manual_input_and_concurrency_are_safe(self):
        source = self.source()

        self.assertIn("cron: '11,26,41,56 * * * *'", source)
        self.assertIn("timezone: 'Asia/Seoul'", source)
        self.assertIn("YOUTUBE_DELIVERY_ORDER", source)
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
        self.assertIn("merge-multiple: true", source)
        self.assertNotIn("status: 'success'", source)

    def test_missing_state_always_baselines_and_manual_mode_is_one_item(self):
        source = self.source()

        self.assertIn(
            "YOUTUBE_BASELINE_ONLY: ${{ steps.state.outputs.restored != 'true' }}",
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

    def test_actions_summary_reports_pending_and_ambiguous_retries(self):
        source = self.source()
        self.assertIn("Write safe run summary", source)
        self.assertIn("Pending deliveries", source)
        self.assertIn("Ambiguous retries", source)
        self.assertIn("YOUTUBE_RUN_SUMMARY_PATH", source)

    def test_script_saves_baseline_before_delivery_and_exits_nonzero_on_error(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("partition_youtube_items(", source)
        self.assertIn("YOUTUBE_BASELINE_ONLY", source)
        self.assertIn("YOUTUBE_MANUAL_TEST_MODE", source)
        self.assertLess(
            source.index("for video in baseline_videos:"),
            source.index("for video in delivery_videos:"),
        )
        self.assertLess(
            source.index("queued_videos.append"),
            source.index("for video_id, video_title in queued_videos:"),
        )
        self.assertIn("sys.exit(1)", source)

    def test_video_detail_api_failure_is_not_reported_as_an_empty_success(self):
        module = load_youtube_script()

        with self.assertRaisesRegex(RuntimeError, "youtube_video_details_failed"):
            module.fetch_video_details(FailingYouTubeClient(), ["video-id"])

    def test_ci_compiles_youtube_runtime_modules(self):
        source = CI_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn(".github/scripts/youtube_delivery_state.py", source)
        self.assertIn(".github/scripts/youtube_discord_delivery.py", source)
        self.assertIn(".github/scripts/youtube_video_source.py", source)
        self.assertIn(".github/scripts/youtube_to_discord.py", source)


if __name__ == "__main__":
    unittest.main()
