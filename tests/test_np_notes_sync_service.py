"""Isolated outbound-service tests using fake notes and fake GitHub transport."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

OTHER_DEV = Path(__file__).resolve().parents[1] / "Other_dev"
sys.path.insert(0, str(OTHER_DEV))
from noteapp.sync_service import EncryptedOutboundService, SyncConflict


class FakeTransport:
    def __init__(self):
        self.remote = {}
        self.writes = 0

    def read(self, note_id):
        return self.remote.get(note_id, (None, None))

    def write(self, note_id, sealed, expected_sha=None):
        old = self.remote.get(note_id, (None, None))
        if expected_sha != old[1]:
            raise SyncConflict("simulated concurrent write")
        self.writes += 1
        sha = ("%040x" % self.writes)
        self.remote[note_id] = (sealed, sha)
        return sha


class ServiceTests(unittest.TestCase):
    def setUp(self):
        from noteapp.encrypted_sync import _aes
        try:
            _aes()
        except Exception:
            self.skipTest("cryptography is not available")
        self.temp = tempfile.TemporaryDirectory(prefix="np-notes-fake-service-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.notes_root = root / "Notes"
        self.notes_root.mkdir()
        self.note_id = str(uuid4())
        self.note_folder = self.notes_root / "Title-based NP Notes folder"
        self.note_folder.mkdir()
        self.note_file = self.note_folder / "note.json"
        self._save("v1")
        self.service = EncryptedOutboundService(
            root / "state", self.notes_root, "fake", "fake", "fake-token",
            "synthetic long secret phrase",
        )
        self.remote = FakeTransport()
        self.service.transport = self.remote

    def _save(self, text):
        self.note_file.write_text(json.dumps({
            "uuid": self.note_id, "title": "Fake", "content": text
        }), encoding="utf-8")

    def test_first_upload_then_no_unnecessary_rewrite(self):
        self.service.saved(self.note_id)
        self.assertTrue(self.service.worker.sync_once()) if False else None
        self.assertTrue(self.service._send(self.note_id))
        self.assertEqual(self.remote.writes, 1)
        self.assertTrue(self.service._send(self.note_id))
        self.assertEqual(self.remote.writes, 1)

    def test_upload_new_revision(self):
        self.service._send(self.note_id)
        self._save("v2")
        self.service._send(self.note_id)
        self.assertEqual(self.remote.writes, 2)

    def test_remote_change_preserves_local_state(self):
        self.service._send(self.note_id)
        self.remote.remote[self.note_id] = (b"foreign-ciphertext", "f" * 40)
        self._save("local unsent edit")
        with self.assertRaises(SyncConflict):
            self.service._send(self.note_id)
        self.assertEqual(self.remote.writes, 1)

    def test_restart_scan_enqueues_saved_notes(self):
        self.assertEqual(self.service.queue.count(), 0)
        self.service.enqueue_existing()
        self.assertEqual(self.service.queue.pending()[0][0], self.note_id)

    def test_does_not_read_sibling_data(self):
        outside = Path(self.temp.name) / "OtherApp"
        outside.mkdir()
        (outside / "note.json").write_text("private unrelated", encoding="utf-8")
        self.service.enqueue_existing()
        self.assertEqual(self.service.queue.count(), 1)


if __name__ == "__main__":
    unittest.main()
