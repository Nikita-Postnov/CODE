"""Synthetic duplicate UUID recovery tests; never read user notes."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "tools"))
from repair_np_notes_duplicate_uuids import recover
from importlib.util import spec_from_file_location, module_from_spec

class DuplicateRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="npnotes-duplicate-fake-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "Launcher"
        self.notes = self.root / "Data" / "Notes"
        self.notes.mkdir(parents=True)
        shutil.copytree(SOURCE / "Other_dev" / "noteapp", self.root / "noteapp",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        self.backup = Path(self.tmp.name) / "Backup"
        (self.backup / "Notes").mkdir(parents=True)
        (self.backup / "SHA256-manifest.json").write_text("[]")
        self.uid = str(uuid4())
        self.secondary = self.notes / "stale-source"
        self.secondary.mkdir()
        self.primary = self.notes / ("Main от 25.11.2026 10-45, UUID(" + self.uid[:8] + ")")
        self.primary.mkdir()
        for folder, title, text in [
            (self.primary, "Main", "current synthetic"),
            (self.secondary, "Old", "original synthetic"),
        ]:
            (folder / "note.json").write_text(json.dumps({
                "uuid": self.uid, "title": title,
                "timestamp": "2026-11-25T10:45:00", "content": text
            }), encoding="utf-8")
            (folder / "synthetic.txt").write_bytes(text.encode("utf-8"))
            backed = self.backup / "Notes" / folder.name
            shutil.copytree(folder, backed)
        self.original_primary = (self.primary / "note.json").read_bytes()
        self.original_secondary = (self.secondary / "note.json").read_bytes()

    def test_dry_run_never_changes_files(self):
        recover(self.root, self.backup, apply=False)
        self.assertEqual(len(list(self.notes.iterdir())), 2)
        self.assertEqual((self.primary / "note.json").read_bytes(), self.original_primary)

    @unittest.skipUnless(sys.platform == "win32", "apply explicitly Windows-only")
    def test_apply_preserves_versions_and_archive(self):
        recover(self.root, self.backup, apply=True)
        self.assertEqual((self.primary / "note.json").read_bytes(), self.original_primary)
        self.assertFalse(self.secondary.exists())
        restored = [folder for folder in self.notes.iterdir() if folder != self.primary]
        self.assertEqual(len(restored), 1)
        record = json.loads((restored[0] / "note.json").read_bytes())
        self.assertNotEqual(record["uuid"], self.uid)
        self.assertEqual(record["content"], "original synthetic")
        self.assertEqual((restored[0] / "synthetic.txt").read_bytes(), b"original synthetic")
        archive = list((self.root / "Data" / "NPNotesSync" / "duplicate_archive" / self.uid).glob("*/note.json"))
        self.assertEqual(len(archive), 1)
        self.assertEqual(archive[0].read_bytes(), self.original_secondary)

    def test_ambiguous_primary_refused_without_change(self):
        self.secondary.rename(self.notes / ("Old от 25.11.2026 10-45, UUID(" + self.uid[:8] + ")"))
        with self.assertRaisesRegex(RuntimeError, "AMBIGUOUS_PRIMARY"):
            recover(self.root, self.backup, apply=False)
        self.assertEqual((self.primary / "note.json").read_bytes(), self.original_primary)

if __name__ == "__main__":
    unittest.main()
