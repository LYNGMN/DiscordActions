import re
import unittest
from pathlib import Path


WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / "workflows"
NODE24_ACTION_MAJORS = {
    "actions/checkout": "7",
    "actions/setup-python": "7",
    "actions/github-script": "9",
    "actions/download-artifact": "8",
    "actions/upload-artifact": "7",
}
ACTION_REFERENCE = re.compile(
    r"uses:\s+(actions/(?:checkout|setup-python|github-script|download-artifact|upload-artifact))"
    r"@([0-9a-f]{40})\s+#\s+v(\d+)"
)
MUTABLE_TAG = re.compile(r"uses:\s+actions/[^\s@]+@v\d+")


class GitHubActionRuntimeVersionTests(unittest.TestCase):
    def test_all_first_party_actions_use_the_approved_node24_major(self):
        references = []
        for workflow in sorted(WORKFLOWS_DIR.glob("*.yml")):
            source = workflow.read_text(encoding="utf-8")
            references.extend(
                (workflow.name, action, commit, major)
                for action, commit, major in ACTION_REFERENCE.findall(source)
            )

        self.assertTrue(references)
        for workflow_name, action, commit, major in references:
            with self.subTest(workflow=workflow_name, action=action):
                self.assertRegex(commit, r"^[0-9a-f]{40}$")
                self.assertEqual(NODE24_ACTION_MAJORS[action], major)

    def test_no_action_uses_a_mutable_tag(self):
        for workflow in sorted(WORKFLOWS_DIR.glob("*.yml")):
            with self.subTest(workflow=workflow.name):
                source = workflow.read_text(encoding="utf-8")
                self.assertNotRegex(source, MUTABLE_TAG)


if __name__ == "__main__":
    unittest.main()
