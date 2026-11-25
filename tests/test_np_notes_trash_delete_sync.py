"""Synthetic-only tests for permanent deletion; never open Launcher/Data or real GitHub.

The fake transport is in memory; all note folders and SQLite databases are
created under a temporary directory. No credentials, secrets or production notes.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Other_dev"))
from noteapp.sync_service import EncryptedOutboundService, SyncConflict
from noteapp.encrypted_sync import unseal


class FakeTransport:
    def __init__(self):
        self.notes = {}
        self.tombstones = {}
        self.counter = 0
        self.deletes = 0
        self.online = True

    def assert_private(self):
        if not self.online:
            raise ConnectionError("synthetic offline")
        return True

    def _sha(self):
        self.counter += 1
        return f"{self.counter:040x}"

    def list_note_ids(self):
        self.assert_private()
        return sorted(self.notes)

    def list_tombstone_ids(self):
        self.assert_private()
        return sorted(self.tombstones)

    def read(self, note_id):
        self.assert_private()
        return self.notes.get(note_id, (None, None))

    def read_tombstone(self, note_id):
        self.assert_private()
        return self.tombstones.get(note_id, (None, None))

    def write(self, note_id, sealed, expected_sha=None):
        self.assert_private()
        if expected_sha != self.notes.get(note_id, (None, None))[1]:
            raise SyncConflict("Synthetic concurrent update")
        sha = self._sha()
        self.notes[note_id] = (sealed, sha)
        return sha

    def write_tombstone(self, note_id, sealed):
        self.assert_private()
        if note_id in self.tombstones:
            raise SyncConflict("Synthetic duplicate tombstone")
        sha = self._sha()
        self.tombstones[note_id] = (sealed, sha)
        return sha

    def delete_note(self, note_id, expected_sha):
        self.assert_private()
        if self.notes.get(note_id, (None, None))[1] != expected_sha:
            raise SyncConflict("Synthetic stale deletion SHA")
        del self.notes[note_id]
        self.deletes += 1
        return True


class SyntheticTrashDeletionTests(unittest.TestCase):
    secret = "synthetic password no real credentials"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="synthetic-np-notes-delete-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.transport = FakeTransport()
        self.note_id = str(uuid4())
        self.a = self.make_device("a")
        self.note_folder = self.a.repository_root / "Sample note"
        self.note_folder.mkdir()
        (self.note_folder / "note.json").write_text(json.dumps({
            "uuid": self.note_id, "title": "Synthetic",
            "content": "only test text",
            "timestamp": "2026-11-25T12:00:00"
        }), encoding="utf-8")

    def make_device(self, name):
        root = self.root / name
        notes = root / "Notes"
        notes.mkdir(parents=True)
        service = EncryptedOutboundService(
            root / "sync", notes, "fake", "fake", "fake-token", self.secret
        )
        service.transport = self.transport
        return service

    def to_trash(self, service, folder):
        trash = service.repository_root / "Trash"
        trash.mkdir(exist_ok=True)
        target = trash / folder.name
        shutil.move(str(folder), str(target))
        service.moved_to_trash(self.note_id)
        return target

    def test_soft_trash_cancels_queue_without_remote_deletion(self):
        self.assertTrue(self.a._send(self.note_id))
        self.a.saved(self.note_id)
        target = self.to_trash(self.a, self.note_folder)
        self.assertTrue(target.is_dir())
        self.assertEqual(self.a.queue.count(), 0)
        self.assertTrue(self.a._receive())
        self.assertIsNone(self.a._find_folder(self.note_id))
        self.assertIsNotNone(self.transport.read(self.note_id)[0])
        self.assertEqual(self.transport.deletes, 0)

    def test_explicit_final_delete_removes_github_and_leaves_tombstone(self):
        self.assertTrue(self.a._send(self.note_id))
        target = self.to_trash(self.a, self.note_folder)
        self.a.prepare_permanent_delete(self.note_id)
        shutil.rmtree(target)
        self.a.commit_permanent_delete(self.note_id)
        self.assertEqual(self.a.queue.count(), 1)
        self.assertTrue(self.a.worker.sync_once())
        self.assertEqual(self.a.queue.count(), 0)
        self.assertEqual(self.transport.deletes, 1)
        self.assertIsNone(self.transport.read(self.note_id)[0])
        marker, sha = self.transport.read_tombstone(self.note_id)
        self.assertIsNotNone(sha)
        self.assertEqual(
            json.loads(unseal(marker, self.secret, self.note_id)),
            {"v": 1, "uuid": self.note_id}
        )
        self.assertEqual(self.a._deletion_status(self.note_id), "done")

    def test_offline_delete_stays_queued_and_retries_without_resurrection(self):
        self.a._send(self.note_id)
        target = self.to_trash(self.a, self.note_folder)
        self.a.prepare_permanent_delete(self.note_id)
        shutil.rmtree(target)
        self.a.commit_permanent_delete(self.note_id)
        self.transport.online = False
        self.assertFalse(self.a.worker.sync_once())
        self.assertEqual(self.a.queue.count(), 1)
        self.assertIn(self.note_id, self.transport.notes)
        self.transport.online = True
        self.assertTrue(self.a.worker.sync_once())
        self.assertEqual(self.a.queue.count(), 0)
        self.assertNotIn(self.note_id, self.transport.notes)

    def test_remote_tombstone_stages_safe_soft_delete_on_second_device(self):
        self.a._send(self.note_id)
        b = self.make_device("b")
        self.assertTrue(b._receive())
        self.assertIsNotNone(b._find_folder(self.note_id))
        target = self.to_trash(self.a, self.note_folder)
        self.a.prepare_permanent_delete(self.note_id)
        shutil.rmtree(target)
        self.a.commit_permanent_delete(self.note_id)
        self.assertTrue(self.a.worker.sync_once())
        self.assertTrue(b._receive())
        self.assertEqual(b._deletion_status(self.note_id), "remote")
        self.assertEqual(b.apply_staged_remote_deletions([self.note_id]), [])
        self.assertIsNotNone(b._find_folder(self.note_id))
        self.assertEqual(b.apply_staged_remote_deletions([]), [self.note_id])
        self.assertIsNone(b._find_folder(self.note_id))
        self.assertIsNotNone(b._folder_in_trash(self.note_id))
        with self.assertRaises(ValueError):
            b.restored_from_trash(self.note_id)
        b.saved(self.note_id)
        self.assertTrue(b.worker.sync_once())
        self.assertNotIn(self.note_id, self.transport.notes)

    def test_prepared_crash_recovers_only_if_trash_folder_gone(self):
        self.a._send(self.note_id)
        target = self.to_trash(self.a, self.note_folder)
        self.a.prepare_permanent_delete(self.note_id)
        self.a._reconcile_prepared_deletions()
        self.assertEqual(self.a._deletion_status(self.note_id), "prepared")
        shutil.rmtree(target)
        self.a._reconcile_prepared_deletions()
        self.assertEqual(self.a._deletion_status(self.note_id), "pending")
        self.assertEqual(self.a.queue.count(), 1)

    def test_remote_changed_revision_is_not_deleted(self):
        self.a._send(self.note_id)
        target = self.to_trash(self.a, self.note_folder)
        self.a.prepare_permanent_delete(self.note_id)
        shutil.rmtree(target)
        self.a.commit_permanent_delete(self.note_id)
        # Another device committed newer ciphertext. SHA precondition fails closed.
        self.transport.notes[self.note_id] = (b"fake-new-version", self.transport._sha())
        self.assertFalse(self.a.worker.sync_once())
        self.assertIn(self.note_id, self.transport.notes)
        self.assertNotIn(self.note_id, self.transport.tombstones)
        self.assertEqual(self.a.queue.count(), 1)

    def test_uncommitted_prepared_deletion_never_deletes_github(self):
        self.a._send(self.note_id)
        self.to_trash(self.a, self.note_folder)
        self.a.prepare_permanent_delete(self.note_id)
        self.assertTrue(self.a.worker.sync_once())
        self.assertEqual(self.transport.deletes, 0)
        self.assertIn(self.note_id, self.transport.notes)


if __name__ == "__main__":
    unittest.main()
