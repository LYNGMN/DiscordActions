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
    r"uses:\s+(actions/(?:checkout|setup-python|github-script|download-artifact|upload-artifact))@v(\d+)"
)


class GitHubActionRuntimeVersionTests(unittest.TestCase):
    def test_all_first_party_actions_use_the_approved_node24_major(self):
        references = []
        for workflow in sorted(WORKFLOWS_DIR.glob("*.yml")):
            source = workflow.read_text(encoding="utf-8")
            references.extend(
                (workflow.name, action, major)
                for action, major in ACTION_REFERENCE.findall(source)
            )

        self.assertTrue(references)
        for workflow_name, action, major in references:
            with self.subTest(workflow=workflow_name, action=action):
                self.assertEqual(NODE24_ACTION_MAJORS[action], major)


if __name__ == "__main__":
    unittest.main()
