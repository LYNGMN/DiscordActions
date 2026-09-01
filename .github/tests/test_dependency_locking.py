import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GITHUB_DIR = ROOT / ".github"
WORKFLOWS_DIR = GITHUB_DIR / "workflows"

COMMON_DIRECT = (
    "requests==2.34.2",
    "python-dateutil==2.9.0.post0",
    "beautifulsoup4==4.15.0",
    "pytz==2026.3.post1",
    "Babel==2.18.0",
)
YOUTUBE_DIRECT = (
    "-r requirements.in",
    "google-api-python-client==2.199.0",
    "isodate==0.7.2",
)


def meaningful_lines(path):
    return tuple(
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


class DependencyLockingTests(unittest.TestCase):
    def test_direct_dependency_inputs_are_exactly_pinned(self):
        self.assertEqual(
            COMMON_DIRECT,
            meaningful_lines(GITHUB_DIR / "requirements.in"),
        )
        self.assertEqual(
            YOUTUBE_DIRECT,
            meaningful_lines(GITHUB_DIR / "requirements-youtube.in"),
        )

    def test_lock_files_include_hashes_and_direct_dependencies(self):
        common_lock = (GITHUB_DIR / "requirements.txt").read_text(encoding="utf-8")
        youtube_lock = (GITHUB_DIR / "requirements-youtube.txt").read_text(
            encoding="utf-8"
        )

        for lock in (common_lock, youtube_lock):
            self.assertIn("--generate-hashes", lock)
            self.assertIn("--hash=sha256:", lock)
            self.assertNotRegex(
                lock,
                re.compile(r"(?m)^[a-zA-Z0-9_.-]+\s*(?:\\)?$"),
            )

        for requirement in COMMON_DIRECT:
            self.assertIn(requirement.lower(), common_lock.lower())
            self.assertIn(requirement.lower(), youtube_lock.lower())
        for requirement in YOUTUBE_DIRECT[1:]:
            self.assertIn(requirement.lower(), youtube_lock.lower())

    def test_all_python_workflows_use_python_312_and_hashed_locks(self):
        expected_locks = {
            "googlenews-to-discord.yml": ".github/requirements.txt",
            "youtube_to_discord.yml": ".github/requirements-youtube.txt",
            "test.yml": ".github/requirements-youtube.txt",
        }

        for workflow_name, lock_path in expected_locks.items():
            source = (WORKFLOWS_DIR / workflow_name).read_text(encoding="utf-8")
            with self.subTest(workflow=workflow_name):
                self.assertIn("python-version: '3.12'", source)
                self.assertIn("cache: pip", source)
                self.assertIn("cache-dependency-path: {}".format(lock_path), source)
                self.assertIn(
                    "python -m pip install --require-hashes -r {}".format(lock_path),
                    source,
                )
                self.assertIn("python -m pip check", source)
                self.assertNotIn("pip install --upgrade", source)

    def test_dependabot_groups_python_and_actions_updates_without_auto_merge(self):
        source = (GITHUB_DIR / "dependabot.yml").read_text(encoding="utf-8")

        self.assertIn('package-ecosystem: "pip"', source)
        self.assertIn('package-ecosystem: "github-actions"', source)
        self.assertEqual(2, source.count("interval: \"weekly\""))
        self.assertIn("python-dependencies:", source)
        self.assertIn("github-actions:", source)
        self.assertNotIn("automerge", source.lower())

    def test_lock_regeneration_script_pins_the_tool_and_python_runtime(self):
        source = (GITHUB_DIR / "scripts" / "compile_requirements.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn('REQUIRED_PIP_TOOLS_VERSION="7.6.1"', source)
        self.assertIn('PYTHON_BIN="${PYTHON_BIN:-python3.12}"', source)
        self.assertIn("requires Python 3.12", source)
        self.assertEqual(2, source.count("CUSTOM_COMPILE_COMMAND="))
        self.assertIn("requirements.in", source)
        self.assertIn("requirements-youtube.in", source)


if __name__ == "__main__":
    unittest.main()
