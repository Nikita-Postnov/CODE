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
    unpack_snapshot, run_configured_sync, portable_note_folder,
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
                "password_manager": secret, "password_manager_visible": True,
                "timestamp": "2026-11-25T10:00:00"}
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
        folder = self.device_b / "Notes" / portable_note_folder({"uuid": self.note_uuid, "title": "Example", "timestamp": "2026-11-25T10:00:00"})
        self.assertTrue((folder / "image.png").exists())
        note = json.loads((folder / "note.json").read_text(encoding="utf-8"))
        self.assertEqual(note["content"], "hello")
        self.assertNotIn("password_manager", note)

    def test_attachment_links_are_portable_across_devices(self):
        original = self.note(self.device_a)
        note_path = original / "note.json"
        note = json.loads(note_path.read_text())
        note["content"] = '<a href="' + (original / "image.png").resolve().as_uri() + '">File</a>'
        note_path.write_text(json.dumps(note))
        local_snapshot = snapshot_from_folder(original)[1]
        portable_note, _ = unpack_snapshot(local_snapshot, self.note_uuid)
        self.assertIn("npnotes-attachment:", portable_note["content"])
        self.assertNotIn(str(self.device_a), portable_note["content"])
        self.assertEqual(self.engine(self.device_a).run().uploaded, 1)
        self.assertEqual(self.engine(self.device_b).run().downloaded, 1)
        target = self.device_b / "Notes" / portable_note_folder({
            "uuid": self.note_uuid, "title": "Example", "timestamp": "2026-11-25T10:00:00"})
        incoming = json.loads((target / "note.json").read_text())
        self.assertIn((target / "image.png").resolve().as_uri(), incoming["content"])
        self.assertEqual(snapshot_from_folder(target)[1], local_snapshot)
        self.assertEqual(self.engine(self.device_b).run().uploaded, 0)

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
        self.assertEqual(json.loads((self.device_b / "Notes" / portable_note_folder({"uuid": self.note_uuid, "title": "Example", "timestamp": "2026-11-25T10:00:00"}) / "note.json").read_text())["content"], "remote-change")

    def test_concurrent_edits_preserve_both_and_record_conflict(self):
        a = self.note(self.device_a)
        self.engine(self.device_a).run()
        self.engine(self.device_b).run()
        b = self.device_b / "Notes" / portable_note_folder({"uuid": self.note_uuid, "title": "Example", "timestamp": "2026-11-25T10:00:00"})
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

    def test_encrypted_staging_does_not_touch_editor_until_main_thread(self):
        self.note(self.device_a)
        self.engine(self.device_a).run()
        b = self.engine(self.device_b)
        b.stage_downloads = True
        self.assertEqual(b.run().downloaded, 1)
        inbox = self.device_b / "NoteSync" / "inbox"
        blob = (inbox / (self.note_uuid + ".npn")).read_bytes()
        self.assertTrue(blob.startswith(b"NPNS1"))
        self.assertNotIn(b"hello", blob)
        self.assertFalse((self.device_b / "Notes").exists())
        self.assertEqual(b.apply_pending(protected_uuid=self.note_uuid), ())
        self.assertFalse((self.device_b / "Notes").exists())
        self.assertEqual(b.apply_pending(), (self.note_uuid,))
        target = self.device_b / "Notes" / portable_note_folder({
            "uuid": self.note_uuid, "title": "Example",
            "timestamp": "2026-11-25T10:00:00"})
        self.assertTrue((target / "image.png").exists())
        self.assertFalse((inbox / (self.note_uuid + ".npn")).exists())

    def test_local_edit_while_remote_staged_is_preserved(self):
        self.note(self.device_a)
        self.engine(self.device_a).run()
        self.engine(self.device_b).run()
        a = self.device_a / "Notes" / ("Folder_" + self.note_uuid)
        note = json.loads((a / "note.json").read_text())
        note["content"] = "remote version"
        (a / "note.json").write_text(json.dumps(note))
        self.engine(self.device_a).run()
        b = self.engine(self.device_b)
        b.stage_downloads = True
        self.assertEqual(b.run().downloaded, 1)
        target = self.device_b / "Notes" / portable_note_folder({
            "uuid": self.note_uuid, "title": "Example",
            "timestamp": "2026-11-25T10:00:00"})
        note = json.loads((target / "note.json").read_text())
        note["content"] = "local version"
        (target / "note.json").write_text(json.dumps(note))
        self.assertEqual(b.apply_pending(), ())
        self.assertEqual(json.loads((target / "note.json").read_text())["content"], "local version")
        self.assertEqual(len(list((self.device_b / "NoteSync" / "conflicts").glob("*.npn"))), 1)

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI only")
    def test_enrolled_credentials_are_dpapi_protected(self):
        from noteapp.sync_secrets import save_credentials, load_credentials
        state = self.device_a / "NoteSync"
        save_credentials(state, "synthetic-token-only", PASSWORD)
        blob = (state / "credentials.dpapi").read_bytes()
        self.assertNotIn(b"synthetic-token-only", blob)
        self.assertEqual(load_credentials(state), ("synthetic-token-only", PASSWORD))
        with self.assertRaises(SyncError):
            save_credentials(state, "synthetic-token-only", PASSWORD)

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

    def test_zip_bomb_is_rejected_before_any_local_write(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("note.json", json.dumps({"uuid": self.note_uuid, "content": "safe"}))
            z.writestr("attachments/bomb.bin", b"X" * (21 * 1024 * 1024))
        self.assertLess(len(buf.getvalue()), 1024 * 1024)
        with self.assertRaises(SyncError):
            unpack_snapshot(buf.getvalue(), self.note_uuid)
        self.assertFalse((self.device_a / "Notes").exists())

    def test_disabled_configuration_causes_no_network_or_data_reads(self):
        self.assertIsNone(enabled_config(self.device_a))
        self.assertEqual(run_configured_sync(self.device_a).status, "disabled")
        cfg = self.device_a / "NoteSync" / "config.json"
        atomic_bytes(cfg, json.dumps({"enabled": True, "interval_minutes": 5, "repository": REPO, "attachments": True}).encode())
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(run_configured_sync(self.device_a).status, "needs_credentials")

    def test_disabled_attachment_policy_cannot_silently_export_files(self):
        cfg = self.device_a / "NoteSync" / "config.json"
        atomic_bytes(cfg, json.dumps({"enabled": True, "interval_minutes": 5,
                                     "repository": REPO, "attachments": False}).encode())
        with self.assertRaises(SyncError):
            enabled_config(self.device_a)

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


class GitHubRestAdapterTests(unittest.TestCase):
    def test_private_metadata_blob_and_encrypted_upload(self):
        import base64
        calls = []
        note_id = str(uuid.uuid4())
        binary = b"NPNS1" + b"x" * 42

        class Response:
            def __init__(self, payload):
                self.payload = payload
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, limit=-1):
                return json.dumps(self.payload).encode("utf-8")

        def fake_http(request, timeout):
            self.assertEqual(timeout, 12)
            self.assertEqual(request.get_header("Authorization"), "Bearer SYNTHETIC_TOKEN")
            calls.append((request.get_method(), request.full_url, request.data))
            if request.full_url.endswith("/repos/private-test/notes"):
                return Response({"private": True})
            if request.full_url.endswith("/contents/notes"):
                return Response([{"name": note_id + ".npn", "sha": "a" * 40, "type": "file"}])
            if request.full_url.endswith("/git/blobs/" + "a" * 40):
                return Response({"encoding": "base64", "content": base64.b64encode(binary).decode()})
            if "/contents/notes/" in request.full_url and request.get_method() == "PUT":
                body = json.loads(request.data)
                self.assertEqual(base64.b64decode(body["content"]), binary)
                self.assertEqual(body["sha"], "a" * 40)
                return Response({"content": {"sha": "b" * 40}})
            raise AssertionError("Unexpected URL: " + request.full_url)

        store = GitHubStore(REPO, "SYNTHETIC_TOKEN", request=fake_http)
        store.check_private()
        self.assertEqual(store.list_notes()[note_id], "a" * 40)
        self.assertEqual(store.download("a" * 40), binary)
        self.assertEqual(store.upload(note_id, binary, "a" * 40), "b" * 40)
        self.assertEqual([call[0] for call in calls], ["GET", "GET", "GET", "PUT"])

    def test_offline_adapter_returns_offline_without_touching_files(self):
        import urllib.error
        def offline(request, timeout):
            raise urllib.error.URLError("synthetic connection lost")
        store = GitHubStore(REPO, "SYNTHETIC_TOKEN", request=offline)
        with self.assertRaises(Offline):
            store.check_private()


if __name__ == "__main__":
    unittest.main()
