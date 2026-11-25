"""Cross-device receiving tests: all notes are temporary synthetic fixtures."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Other_dev"))
from noteapp.encrypted_sync import seal, _aes
from noteapp.incoming_sync import import_new_note, stage_conflict, IncomingConflict
from noteapp.sync_snapshot import unpack_to_memory


class IncomingTests(unittest.TestCase):
    def setUp(self):
        try:
            _aes()
        except Exception:
            self.skipTest("cryptography unavailable")
        self.tmp = tempfile.TemporaryDirectory(prefix="np-notes-fake-incoming-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.notes = self.root / "Data" / "Notes"
        self.notes.mkdir(parents=True)
        self.state = self.root / "Data" / "NPNotesSync"
        self.identifier = str(uuid4())
        self.secret = "synthetic password 123456"
        self.note = {
            "uuid": self.identifier, "title": "Example",
            "timestamp": "2026-11-25T10:45:00", "content": "fake",
        }
        self.data = json.dumps({
            "version": 1, "note": self.note,
            "attachments": {"picture.png": "ZmFrZS1pbWFnZQ=="},
        }, ensure_ascii=False).encode()
        self.encrypted = seal(self.data, self.secret, self.identifier)

    def test_new_note_and_attachment_import(self):
        folder = import_new_note(
            self.notes, self.state, self.identifier, self.encrypted, self.secret
        )
        self.assertEqual(json.loads((folder / "note.json").read_text())["uuid"],
                         self.identifier)
        self.assertEqual((folder / "picture.png").read_bytes(), b"fake-image")

    def test_existing_folder_never_overwritten(self):
        folder = import_new_note(
            self.notes, self.state, self.identifier, self.encrypted, self.secret
        )
        marker = folder / "keep.txt"
        marker.write_text("do not touch")
        with self.assertRaises(IncomingConflict):
            import_new_note(
                self.notes, self.state, self.identifier, self.encrypted, self.secret
            )
        self.assertEqual(marker.read_text(), "do not touch")

    def test_wrong_key_never_creates_note(self):
        with self.assertRaises(Exception):
            import_new_note(
                self.notes, self.state, self.identifier, self.encrypted,
                "totally different password"
            )
        self.assertEqual(list(self.notes.iterdir()), [])

    def test_conflict_storage_remains_encrypted(self):
        path = stage_conflict(self.state, self.identifier, "a" * 40, self.encrypted)
        self.assertEqual(path.read_bytes(), self.encrypted)
        self.assertNotIn(b"fake-image", path.read_bytes())

    def test_invalid_attachment_name_does_not_write(self):
        snapshot = json.dumps({
            "version": 1, "note": self.note,
            "attachments": {"../../bad": "ZmFrZQ=="},
        }).encode()
        with self.assertRaises(Exception):
            import_new_note(
                self.notes, self.state, self.identifier,
                seal(snapshot, self.secret, self.identifier), self.secret
            )
        self.assertEqual(list(self.notes.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
