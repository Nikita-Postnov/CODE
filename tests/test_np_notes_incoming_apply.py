"""Synthetic rollback tests for backup-first incoming revisions."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Other_dev"))
from noteapp.encrypted_sync import seal
from noteapp.incoming_apply import apply_clean_remote_revision
from noteapp.incoming_sync import IncomingConflict
from noteapp.sync_snapshot import pack_note


class IncomingApplyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="np-notes-rollback-fake-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.folder = root / "Notes" / "fake-note"
        self.folder.mkdir(parents=True)
        self.state = root / "state"
        self.note_id = str(uuid4())
        self.secret = "synthetic passphrase for automated tests"
        self._write(self.folder, "original local note", b"original-attachment")
        before = pack_note(self.folder, self.note_id)
        self.baseline = hashlib.sha256(before).hexdigest()
        remote = root / "remote-note"
        remote.mkdir()
        self._write(remote, "remote revision", b"updated-attachment")
        self.cipher = seal(pack_note(remote, self.note_id), self.secret, self.note_id)

    def _write(self, folder, text, attachment):
        (folder / "attachment.bin").write_bytes(attachment)
        (folder / "note.json").write_text(json.dumps({
            "uuid": self.note_id, "title": "Fake",
            "content": text, "timestamp": "2026-11-25T10:00:00",
        }), encoding="utf-8")

    def test_clean_revision_backed_up_before_update(self):
        target = apply_clean_remote_revision(
            self.folder, self.state, self.note_id, self.cipher,
            self.secret, self.baseline
        )
        self.assertEqual(target, self.folder)
        self.assertEqual((target / "attachment.bin").read_bytes(), b"updated-attachment")
        backup = list((self.state / "remote_update_backups").rglob("note.json"))
        self.assertEqual(len(backup), 1)
        self.assertEqual(json.loads(backup[0].read_text())["content"],
                         "original local note")

    def test_disk_error_rolls_back_both_attachment_and_note(self):
        from noteapp import incoming_apply
        real = incoming_apply._atomic_write
        attempts = [0]
        def fail_second(path, raw):
            attempts[0] += 1
            if attempts[0] == 2:
                raise OSError("simulated disk failure after first file")
            return real(path, raw)
        with patch("noteapp.incoming_apply._atomic_write", side_effect=fail_second):
            with self.assertRaises(IncomingConflict):
                apply_clean_remote_revision(
                    self.folder, self.state, self.note_id, self.cipher,
                    self.secret, self.baseline
                )
        self.assertEqual((self.folder / "attachment.bin").read_bytes(),
                         b"original-attachment")
        self.assertEqual(json.loads((self.folder / "note.json").read_text())["content"],
                         "original local note")
        backup = list((self.state / "remote_update_backups").rglob("note.json"))
        self.assertEqual(len(backup), 1)

    def test_unsaved_local_change_prevents_all_writes(self):
        data = json.loads((self.folder / "note.json").read_text())
        data["content"] = "unsaved changed elsewhere"
        (self.folder / "note.json").write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(IncomingConflict):
            apply_clean_remote_revision(
                self.folder, self.state, self.note_id, self.cipher,
                self.secret, self.baseline
            )
        self.assertFalse((self.state / "remote_update_backups").exists())
        self.assertEqual((self.folder / "attachment.bin").read_bytes(),
                         b"original-attachment")


if __name__ == "__main__":
    unittest.main()
