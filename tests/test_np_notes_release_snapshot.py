"""Verify the release manifest against a pinned source Git tree, not user data."""
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tools" / "np_notes_release.json"


class ManifestSnapshotTests(unittest.TestCase):
    def test_source_commit_and_all_package_hashes_are_exact(self):
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        sha = data["source_commit"]
        def git(*args):
            return subprocess.check_output(
                ["git", "-C", str(ROOT), *args], text=True
            ).strip()

        self.assertEqual(len(sha), 40)
        self.assertEqual(git("rev-parse", sha + "^{commit}"), sha)
        source = "Other_dev/"
        actual = set(git("ls-tree", "-r", "--name-only", sha, source).splitlines())
        declared = {
            source + record["path"]
            for record in data["files"]
        }
        self.assertEqual(actual, declared)
        for item in data["files"]:
            path = source + item["path"]
            blob = git("rev-parse", sha + ":" + path)
            self.assertEqual(blob, item["git_blob_sha"], path)


if __name__ == "__main__":
    unittest.main()
