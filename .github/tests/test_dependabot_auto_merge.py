import unittest
from pathlib import Path


WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / "workflows"
AUTO_MERGE = WORKFLOWS_DIR / "dependabot-auto-merge.yml"
FETCH_METADATA_SHA = "25dd0e34f4fe68f24cc83900b1fe3fe149efef98"
DEPENDABOT = Path(__file__).resolve().parents[1] / "dependabot.yml"


class DependabotAutoMergeTests(unittest.TestCase):
    def test_auto_merge_is_limited_to_non_security_pip_patches(self):
        source = AUTO_MERGE.read_text(encoding="utf-8")
        self.assertIn("pull_request_target:", source)
        self.assertIn("opened, synchronize, reopened, ready_for_review", source)
        self.assertIn("contents: write", source)
        self.assertIn("pull-requests: write", source)
        self.assertIn(
            "github.event.pull_request.user.login == 'dependabot[bot]'", source
        )
        self.assertIn(
            "startsWith(github.event.pull_request.head.ref, 'dependabot/pip/')",
            source,
        )
        self.assertIn(
            "dependabot/fetch-metadata@{} # v3.1.0".format(FETCH_METADATA_SHA),
            source,
        )
        self.assertIn(
            "steps.metadata.outputs.update-type == 'version-update:semver-patch'",
            source,
        )
        self.assertIn(
            "steps.metadata.outputs.dependency-group == 'python-patch'", source
        )
        self.assertIn('gh pr merge --auto --squash "$PR_URL"', source)
        self.assertIn('gh pr merge --disable-auto "$PR_URL"', source)
        self.assertIn("continue-on-error: true", source)
        self.assertNotIn("actions/checkout", source)

    def test_dependabot_splits_pip_patches_from_minor_and_major(self):
        source = DEPENDABOT.read_text(encoding="utf-8")
        self.assertIn("python-patch:", source)
        self.assertIn("python-minor-major:", source)
        self.assertIn('update-types:\n          - "patch"', source)
        self.assertIn('update-types:\n          - "minor"\n          - "major"', source)
        self.assertIn("applies-to: version-updates", source)


if __name__ == "__main__":
    unittest.main()
