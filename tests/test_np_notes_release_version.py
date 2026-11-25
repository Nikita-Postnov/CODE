"""Synthetic tests of complete-package NP Notes release checks.

No real data, credentials or GitHub network access.
"""
import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
from check_np_notes_release import check_installation, load_manifest, ReleaseManifestError


def blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\x00" + raw).hexdigest()


class ReleaseChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="np-notes-release-fake-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.install = root / "Launcher"
        self.install.mkdir()
        a = self.install / "notes_app.py"
        b = self.install / "noteapp" / "__init__.py"
        c = self.install / "noteapp" / "app" / "settings.py"
        b.parent.mkdir(parents=True)
        c.parent.mkdir(parents=True)
        self.files = (a, b, c)
        for f in self.files:
            f.write_bytes(b"NP Notes test-only " + f.name.encode())
        paths = ("notes_app.py", "noteapp/__init__.py", "noteapp/app/settings.py")
        self.manifest = {
            "schema": 1, "app": "NP Notes",
            "source_repository": "Nikita-Postnov/CODE",
            "source_commit": "a" * 40,
            "source_directory": "Other_dev",
            "install_scope": ["notes_app.py", "noteapp"],
            "files": [
                {"path": path, "git_blob_sha": blob(f.read_bytes())}
                for path, f in zip(paths, self.files)
            ]
        }
        self.manifest_path = root / "release.json"
        self.save()

    def save(self):
        self.manifest_path.write_text(json.dumps(self.manifest))

    def test_current_complete_package(self):
        manifest = load_manifest(self.manifest_path)
        result = check_installation(self.install, manifest)
        self.assertEqual(result["status"], "UP_TO_DATE")
        self.assertEqual(result["checked"], 3)

    def test_change_inside_noteapp_triggers_update(self):
        self.files[2].write_bytes(b"older settings module")
        result = check_installation(self.install, load_manifest(self.manifest_path))
        self.assertEqual(result["status"], "UPDATE_AVAILABLE")
        self.assertEqual(result["mismatched"], 1)

    def test_entrypoint_only_is_not_enough(self):
        self.files[1].unlink()
        result = check_installation(self.install, load_manifest(self.manifest_path))
        self.assertEqual(result["status"], "UPDATE_AVAILABLE")

    def test_user_data_is_out_of_scope(self):
        data = self.install / "Data" / "Notes" / "fake"
        data.mkdir(parents=True)
        (data / "note.json").write_text("test only")
        result = check_installation(self.install, load_manifest(self.manifest_path))
        self.assertEqual(result["status"], "UP_TO_DATE")

    def test_rejects_path_traversal_and_duplicates(self):
        self.manifest["files"][2]["path"] = "noteapp/../../Data/Notes/note.json"
        self.save()
        with self.assertRaises(ReleaseManifestError):
            load_manifest(self.manifest_path)
        self.manifest["files"][2]["path"] = "noteapp/__init__.py"
        self.save()
        with self.assertRaises(ReleaseManifestError):
            load_manifest(self.manifest_path)


if __name__ == "__main__":
    unittest.main()
