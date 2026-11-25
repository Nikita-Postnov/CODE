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

    def assert_private(self):
        return True

    def list_note_ids(self):
        return list(self.remote)

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
            "uuid": self.note_id, "title": "Fake", "content": text,
            "timestamp": "2026-11-25T10:45:00"
        }), encoding="utf-8")

    def test_first_upload_then_no_unnecessary_rewrite(self):
        self.service.saved(self.note_id)
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

    def test_encrypted_attachment_survives_between_fake_devices(self):
        attachment = self.note_folder / "synthetic-image.bin"
        payload = b"\x00TEST-ONLY-BINARY\xff" * 50
        attachment.write_bytes(payload)
        self.service._send(self.note_id)
        second_root = Path(self.temp.name) / "attachment_device"
        second_notes = second_root / "Notes"
        second_notes.mkdir(parents=True)
        device_b = EncryptedOutboundService(
            second_root / "state", second_notes, "fake", "fake",
            "fake-token", "synthetic long secret phrase",
        )
        device_b.transport = self.remote
        self.assertTrue(device_b._receive())
        received = list(second_notes.glob("*/synthetic-image.bin"))
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].read_bytes(), payload)

    def test_restart_scan_enqueues_saved_notes(self):
        self.assertEqual(self.service.queue.count(), 0)
        self.service.enqueue_existing()
        self.assertEqual(self.service.queue.pending()[0][0], self.note_id)

    def test_two_devices_import_without_overwrite(self):
        # Device A uploads a fake note. Device B starts with empty notes.
        self.service._send(self.note_id)
        second_root = Path(self.temp.name) / "other_device"
        second_notes = second_root / "Notes"
        second_notes.mkdir(parents=True)
        device_b = EncryptedOutboundService(
            second_root / "state", second_notes, "fake", "fake",
            "fake-token", "synthetic long secret phrase",
        )
        device_b.transport = self.remote
        self.assertTrue(device_b._receive())
        imported = list(second_notes.glob("*/note.json"))
        self.assertEqual(len(imported), 1)
        self.assertEqual(json.loads(imported[0].read_text())["content"], "v1")

        # A later remote edit must not overwrite B's existing note.
        self._save("edited on A")
        self.service._send(self.note_id)
        self.assertTrue(device_b._receive())
        self.assertEqual(json.loads(imported[0].read_text())["content"], "v1")
        conflicts = list((second_root / "state" / "remote_conflicts").rglob("*.enc"))
        self.assertEqual(len(conflicts), 1)

    def test_conflict_can_be_restored_as_non_destructive_copy(self):
        from noteapp.incoming_sync import restore_conflict_as_copy
        self.service._send(self.note_id)
        second_root = Path(self.temp.name) / "conflict_device"
        second_notes = second_root / "Notes"
        second_notes.mkdir(parents=True)
        device_b = EncryptedOutboundService(
            second_root / "state", second_notes, "fake", "fake",
            "fake-token", "synthetic long secret phrase",
        )
        device_b.transport = self.remote
        self.assertTrue(device_b._receive())
        originals = list(second_notes.glob("*/note.json"))
        self.assertEqual(len(originals), 1)

        self._save("edited remotely on device A")
        self.service._send(self.note_id)
        self.assertTrue(device_b._receive())
        conflicts = list((second_root / "state" / "remote_conflicts").rglob("*.enc"))
        self.assertEqual(len(conflicts), 1)
        restored = restore_conflict_as_copy(
            second_notes, second_root / "state", self.note_id,
            conflicts[0].stem, "synthetic long secret phrase"
        )
        self.assertTrue(restored.is_dir())
        copied = json.loads((restored / "note.json").read_text(encoding="utf-8"))
        original = json.loads(originals[0].read_text(encoding="utf-8"))
        self.assertEqual(copied["content"], "edited remotely on device A")
        self.assertNotEqual(copied["uuid"], self.note_id)
        self.assertEqual(original["content"], "v1")
        self.assertEqual(original["uuid"], self.note_id)
        self.assertTrue(conflicts[0].is_file())
        self.assertEqual(self.remote.writes, 2)

    def test_service_restore_conflict_copy_is_queued_for_future_sync(self):
        self.service._send(self.note_id)
        second_root = Path(self.temp.name) / "restore_device"
        second_notes = second_root / "Notes"
        second_notes.mkdir(parents=True)
        device_b = EncryptedOutboundService(
            second_root / "state", second_notes, "fake", "fake",
            "fake-token", "synthetic long secret phrase",
        )
        device_b.transport = self.remote
        self.assertTrue(device_b._receive())
        self._save("new remote revision")
        self.service._send(self.note_id)
        self.assertTrue(device_b._receive())
        pending_conflicts = list(
            (second_root / "state" / "remote_conflicts").rglob("*.enc")
        )
        self.assertEqual(len(pending_conflicts), 1)
        target = device_b.restore_conflict_copy(
            self.note_id, pending_conflicts[0].stem
        )
        new_note_id = json.loads((target / "note.json").read_text())["uuid"]
        self.assertNotEqual(new_note_id, self.note_id)
        self.assertEqual(device_b.queue.pending(), [(new_note_id, 1)])
        self.assertEqual(device_b.received_count, 2)

    def test_does_not_read_sibling_data(self):
        outside = Path(self.temp.name) / "OtherApp"
        outside.mkdir()
        (outside / "note.json").write_text("private unrelated", encoding="utf-8")
        self.service.enqueue_existing()
        self.assertEqual(self.service.queue.count(), 1)


if __name__ == "__main__":
    unittest.main()
