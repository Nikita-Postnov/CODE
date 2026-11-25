"""Note and attachment snapshot tests, strictly limited to temporary dummy data."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

SOURCE = Path(__file__).resolve().parents[1] / "Other_dev/noteapp/sync_snapshot.py"
spec = importlib.util.spec_from_file_location("np_sync_snapshot", SOURCE)
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="np-notes-snapshot-fake-")
        self.addCleanup(self.temp.cleanup)
        self.note_id = str(uuid4())
        self.folder = Path(self.temp.name) / "Example note title"
        self.folder.mkdir()
        (self.folder / "note.json").write_text(
            json.dumps({"uuid": self.note_id, "title": "Fake note", "content": "Fake text"}),
            encoding="utf-8",
        )
        (self.folder / "photo.png").write_bytes(b"FAKE-IMAGE\x00\xff")
        (self.folder / "document.txt").write_bytes(b"fake attachment")
        (self.folder / "note_cache.json").write_text("{}", encoding="utf-8")
        (self.folder / "note_backup_123.json").write_text("{}", encoding="utf-8")

    def test_all_fake_attachments_round_trip(self):
        packed = snapshot.pack_note(self.folder, self.note_id)
        note, files = snapshot.unpack_to_memory(packed, self.note_id)
        self.assertEqual(note["title"], "Fake note")
        self.assertEqual(files["photo.png"], b"FAKE-IMAGE\x00\xff")
        self.assertEqual(files["document.txt"], b"fake attachment")
        self.assertNotIn("note_cache.json", files)
        self.assertNotIn("note_backup_123.json", files)

    def test_wrong_note_identifier_rejected(self):
        with self.assertRaises(snapshot.UnsafeSnapshot):
            snapshot.pack_note(self.folder, str(uuid4()))

    def test_mutated_identity_rejected(self):
        packed = snapshot.pack_note(self.folder, self.note_id)
        with self.assertRaises(snapshot.UnsafeSnapshot):
            snapshot.unpack_to_memory(packed, str(uuid4()))

    def test_attachment_path_traversal_rejected(self):
        packed = json.dumps({
            "version": 1, "note": {"uuid": self.note_id},
            "attachments": {"../danger": "ZmFrZQ=="},
        }).encode()
        with self.assertRaises(snapshot.UnsafeSnapshot):
            snapshot.unpack_to_memory(packed, self.note_id)

    def test_read_does_not_modify_source(self):
        before = {p.name: p.read_bytes() for p in self.folder.iterdir()}
        snapshot.pack_note(self.folder, self.note_id)
        after = {p.name: p.read_bytes() for p in self.folder.iterdir()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
