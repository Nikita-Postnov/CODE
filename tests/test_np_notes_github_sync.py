"""GitHub sync regression tests; synthetic temporary notes, no network, no real Data."""
import io
import json
import os
import sys
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Other_dev"))
from noteapp.github_sync import (
    SyncEngine, SyncError, Offline, GitHubStore, atomic_bytes,
    decrypt_snapshot, encrypt_snapshot, enabled_config, snapshot_from_folder,
    unpack_snapshot, run_configured_sync,
)

PASSWORD = "test-passphrase-at-least-sixteen-characters"
REPO = "private-test/notes"


class FakePrivateGitHub:
    def __init__(self):
        self.repo = REPO
        self.files = {}
        self.online = True
        self.is_private = True
        self.sequence = 0

    def check_private(self):
        if not self.online:
            raise Offline("test network outage")
        if not self.is_private:
            raise SyncError("Private repository required")

    def list_notes(self):
        self.check_private()
        return {k: v[0] for k, v in self.files.items()}

    def download(self, sha):
        if not self.online:
            raise Offline("test network outage")
        for entry in self.files.values():
            if entry[0] == sha:
                return entry[1]
        raise SyncError("Missing remote blob")

    def upload(self, note_uuid, encrypted, sha):
        if not self.online:
            raise Offline("test network outage")
        old = self.files.get(note_uuid)
        if (old is None and sha is not None) or (old is not None and sha != old[0]):
            from noteapp.github_sync import Conflict
            raise Conflict("Synthetic concurrent update")
        self.sequence += 1
        new_sha = ("%040x" % self.sequence)
        self.files[note_uuid] = (new_sha, encrypted)
        return new_sha


class GithubSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = FakePrivateGitHub()
        self.device_a = self.root / "A"
        self.device_b = self.root / "B"
        self.note_uuid = str(uuid.uuid4())

    def note(self, device, title="Example", content="hello", attachment=True, secret="LOCAL_ONLY"):
        folder = device / "Notes" / ("Folder_" + self.note_uuid)
        folder.mkdir(parents=True, exist_ok=True)
        note = {"uuid": self.note_uuid, "title": title, "content": content,
                "password_manager": secret, "password_manager_visible": True}
        (folder / "note.json").write_text(json.dumps(note), encoding="utf-8")
        if attachment:
            (folder / "image.png").write_bytes(bytes([0x89, 80, 78, 71, 13, 10]) + b"SYNTHETIC")
        (folder / "note_cache.json").write_text('{"secret":"DO_NOT_EXPORT"}', encoding="utf-8")
        (folder / "note_backup_123.json").write_text('{"secret":"DO_NOT_EXPORT"}', encoding="utf-8")
        return folder

    def engine(self, device):
        return SyncEngine(device / "Notes", device / "NoteSync", self.store, PASSWORD)

    def test_encryption_roundtrip_and_wrong_key(self):
        data = b"confidential note content"
        encrypted = encrypt_snapshot(data, PASSWORD, REPO, self.note_uuid)
        self.assertNotIn(data, encrypted)
        self.assertEqual(decrypt_snapshot(encrypted, PASSWORD, REPO, self.note_uuid), data)
        with self.assertRaises(SyncError):
            decrypt_snapshot(encrypted, "incorrect-passphrase-long", REPO, self.note_uuid)
        with self.assertRaises(SyncError):
            decrypt_snapshot(encrypted, PASSWORD, REPO, str(uuid.uuid4()))

    def test_stable_snapshot_excludes_password_cache_and_backup(self):
        folder = self.note(self.device_a)
        uid, raw, digest = snapshot_from_folder(folder)
        self.assertEqual(uid, self.note_uuid)
        self.assertEqual(digest, snapshot_from_folder(folder)[2])
        self.assertEqual(raw, snapshot_from_folder(folder)[1])
        note, files = unpack_snapshot(raw, uid)
        self.assertNotIn("password_manager", note)
        self.assertNotIn("password_manager_visible", note)
        self.assertEqual(files["image.png"][:4], bytes([0x89, 80, 78, 71]))
        self.assertNotIn(b"DO_NOT_EXPORT", raw)

    def test_offline_preserves_local_and_resumes_after_network_returns(self):
        folder = self.note(self.device_a)
        before = (folder / "note.json").read_bytes()
        engine = self.engine(self.device_a)
        self.store.online = False
        self.assertEqual(engine.run().status, "offline")
        self.assertEqual(before, (folder / "note.json").read_bytes())
        self.assertEqual(self.store.files, {})
        self.store.online = True
        first = engine.run()
        self.assertEqual(first.uploaded, 1)
        self.assertEqual(engine.run().uploaded, 0)

    def test_sync_to_other_device_with_attachment(self):
        self.note(self.device_a)
        self.assertEqual(self.engine(self.device_a).run().uploaded, 1)
        outcome = self.engine(self.device_b).run()
        self.assertEqual(outcome.downloaded, 1)
        folder = self.device_b / "Notes" / ("Sync_" + self.note_uuid)
        self.assertTrue((folder / "image.png").exists())
        note = json.loads((folder / "note.json").read_text(encoding="utf-8"))
        self.assertEqual(note["content"], "hello")
        self.assertNotIn("password_manager", note)

    def test_remote_update_never_erases_existing_local_secret(self):
        a = self.note(self.device_a)
        self.engine(self.device_a).run()
        self.engine(self.device_b).run()
        note = json.loads((a / "note.json").read_text())
        note["content"] = "remote-change"
        (a / "note.json").write_text(json.dumps(note))
        self.engine(self.device_a).run()
        result = self.engine(self.device_b).run()
        self.assertEqual(result.downloaded, 1)
        self.assertEqual(json.loads((self.device_b / "Notes" / ("Sync_" + self.note_uuid) / "note.json").read_text())["content"], "remote-change")

    def test_concurrent_edits_preserve_both_and_record_conflict(self):
        a = self.note(self.device_a)
        self.engine(self.device_a).run()
        self.engine(self.device_b).run()
        b = self.device_b / "Notes" / ("Sync_" + self.note_uuid)
        for folder, value in ((a, "version-A"), (b, "version-B")):
            note = json.loads((folder / "note.json").read_text())
            note["content"] = value
            (folder / "note.json").write_text(json.dumps(note))
        self.engine(self.device_a).run()
        result = self.engine(self.device_b).run()
        self.assertEqual(result.conflicts, 1)
        self.assertEqual(json.loads((b / "note.json").read_text())["content"], "version-B")
        self.assertEqual(json.loads((a / "note.json").read_text())["content"], "version-A")
        self.assertEqual(len(list((self.device_b / "NoteSync" / "conflicts").glob("*.npn"))), 1)

    def test_selected_editor_note_is_not_overwritten(self):
        a = self.note(self.device_a)
        self.engine(self.device_a).run()
        self.engine(self.device_b).run()
        note = json.loads((a / "note.json").read_text())
        note["content"] = "remote update"
        (a / "note.json").write_text(json.dumps(note))
        self.engine(self.device_a).run()
        result = self.engine(self.device_b).run(protected_uuid=self.note_uuid)
        self.assertEqual(result.downloaded, 0)
        self.assertEqual(self.engine(self.device_b).run().downloaded, 1)

    def test_reject_public_repository_before_upload(self):
        folder = self.note(self.device_a)
        data = (folder / "note.json").read_bytes()
        self.store.is_private = False
        with self.assertRaises(SyncError):
            self.engine(self.device_a).run()
        self.assertEqual(data, (folder / "note.json").read_bytes())
        self.assertEqual(self.store.files, {})

    def test_deletion_not_propagated(self):
        folder = self.note(self.device_a)
        self.engine(self.device_a).run()
        self.engine(self.device_b).run()
        for p in folder.iterdir():
            p.unlink()
        folder.rmdir()
        self.assertEqual(self.engine(self.device_a).run().downloaded, 0)
        self.assertEqual(self.engine(self.device_b).run().uploaded, 0)

    def test_invalid_remote_paths_and_password_field_rejected(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr("note.json", json.dumps({"uuid": self.note_uuid, "content": "ok"}))
            z.writestr("attachments/../escape.txt", "evil")
        with self.assertRaises(SyncError):
            unpack_snapshot(buffer.getvalue(), self.note_uuid)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr("note.json", json.dumps({"uuid": self.note_uuid, "content": "ok", "password_manager": "oops"}))
        with self.assertRaises(SyncError):
            unpack_snapshot(buffer.getvalue(), self.note_uuid)

    def test_disabled_configuration_causes_no_network_or_data_reads(self):
        self.assertIsNone(enabled_config(self.device_a))
        self.assertEqual(run_configured_sync(self.device_a).status, "disabled")
        cfg = self.device_a / "NoteSync" / "config.json"
        atomic_bytes(cfg, json.dumps({"enabled": True, "interval_minutes": 5, "repository": REPO}).encode())
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(run_configured_sync(self.device_a).status, "needs_credentials")

    def test_offline_after_local_change_retries_later(self):
        folder = self.note(self.device_a)
        engine = self.engine(self.device_a)
        engine.run()
        note = json.loads((folder / "note.json").read_text())
        note["content"] = "edited without internet"
        (folder / "note.json").write_text(json.dumps(note))
        self.store.online = False
        self.assertEqual(engine.run().status, "offline")
        self.assertIn("edited without internet", (folder / "note.json").read_text())
        self.store.online = True
        self.assertEqual(engine.run().uploaded, 1)


if __name__ == "__main__":
    unittest.main()
