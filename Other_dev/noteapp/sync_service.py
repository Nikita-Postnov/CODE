"""Encrypted outbound NP Notes sync service (opt-in; never changes local notes).

Only starts with explicit credentials and passphrase in process environment.
Changes are locally saved first. Preexisting unknown remote versions cause
conflicts, not silent overwrite. Incoming merge is intentionally separate.
"""
from __future__ import annotations

import os
import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from uuid import UUID

from .encrypted_sync import GitHubTransport, SyncConflict, seal, unseal
from .offline_sync import OfflineSyncQueue, OfflineSyncWorker
from .sync_snapshot import pack_note, UnsafeSnapshot


class EncryptedOutboundService:
    def __init__(self, state_directory: Path, repository_root: Path, owner: str,
                 repo: str, token: str, passphrase: str, branch="main"):
        self.state_directory = Path(state_directory)
        self.state_directory.mkdir(parents=True, exist_ok=True)
        self.repository_root = Path(repository_root)
        self.passphrase = passphrase
        self.transport = GitHubTransport(owner, repo, token, branch=branch)
        self.queue = OfflineSyncQueue(self.state_directory)
        self._lock = threading.RLock()
        self._db_path = self.state_directory / "remote_revisions.sqlite3"
        self._init_db()
        self.worker = OfflineSyncWorker(self.queue, self._online, self._send)

    def _connect(self):
        return sqlite3.connect(str(self._db_path), timeout=10)

    def _init_db(self):
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS remote_revisions
                          (note_id TEXT PRIMARY KEY, blob_sha TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS local_content
                          (note_id TEXT PRIMARY KEY, content_sha256 TEXT NOT NULL)""")

    def _digest(self, note_id):
        with self._lock, self._connect() as db:
            row = db.execute("SELECT content_sha256 FROM local_content WHERE note_id=?",
                             (note_id,)).fetchone()
        return row[0] if row else None

    def _remember_digest(self, note_id, digest):
        with self._lock, self._connect() as db:
            db.execute("""INSERT INTO local_content(note_id,content_sha256) VALUES (?,?)
                          ON CONFLICT(note_id) DO UPDATE SET
                          content_sha256=excluded.content_sha256""",
                       (note_id, digest))

    def _known_sha(self, note_id):
        with self._lock, self._connect() as db:
            row = db.execute("SELECT blob_sha FROM remote_revisions WHERE note_id=?",
                             (note_id,)).fetchone()
        return row[0] if row else None

    def _remember_sha(self, note_id, sha):
        with self._lock, self._connect() as db:
            db.execute("""INSERT INTO remote_revisions(note_id,blob_sha) VALUES (?,?)
                         ON CONFLICT(note_id) DO UPDATE SET blob_sha=excluded.blob_sha""",
                       (note_id, sha))

    def _find_folder(self, note_id):
        """The actual NP Notes folder names contain titles, not just UUIDs."""
        note_id = str(UUID(note_id))
        root = self.repository_root.resolve(strict=True)
        matches = []
        for folder in root.iterdir():
            if folder.is_symlink() or not folder.is_dir() or folder.name == "Trash":
                continue
            note_path = folder / "note.json"
            if note_path.is_symlink() or not note_path.is_file():
                continue
            try:
                if note_path.stat().st_size > 15 * 1024 * 1024:
                    continue
                if json.loads(note_path.read_bytes()).get("uuid") == note_id:
                    matches.append(folder)
            except (OSError, ValueError, UnicodeDecodeError):
                continue
        if len(matches) != 1:
            raise UnsafeSnapshot("Note UUID has zero or multiple matching folders")
        return matches[0]

    def _online(self):
        # No credential-bearing request as a mere connectivity probe.
        import socket
        try:
            with socket.create_connection(("api.github.com", 443), timeout=3):
                return True
        except OSError:
            return False

    def _send(self, note_id):
        plain = pack_note(self._find_folder(note_id), note_id)
        digest = hashlib.sha256(plain).hexdigest()
        known = self._known_sha(note_id)
        remote, current_sha = self.transport.read(note_id)
        if known is None and current_sha is not None:
            # Existing data must be manually reconciled before first push.
            # Identical data may be accepted without modifying the remote.
            if unseal(remote, self.passphrase, note_id) == plain:
                self._remember_sha(note_id, current_sha)
                self._remember_digest(note_id, digest)
                return True
            raise SyncConflict("Remote note already exists and differs")
        if known is not None and current_sha != known:
            raise SyncConflict("Remote note changed on another device")
        if known is not None and self._digest(note_id) == digest:
            return True
        sha = self.transport.write(
            note_id, seal(plain, self.passphrase, note_id), expected_sha=known
        )
        self._remember_sha(note_id, sha)
        self._remember_digest(note_id, digest)
        return True

    def saved(self, note_id):
        self.queue.mark_changed(str(UUID(note_id)))
        self.worker.wake()

    def enqueue_existing(self):
        """Recover changes saved before a prior queue update or crash."""
        root = self.repository_root
        if not root.is_dir():
            return
        for folder in root.iterdir():
            if not folder.is_dir() or folder.is_symlink() or folder.name == "Trash":
                continue
            source = folder / "note.json"
            if source.is_symlink() or not source.is_file():
                continue
            try:
                if source.stat().st_size > 15 * 1024 * 1024:
                    continue
                item = json.loads(source.read_bytes())
                identifier = str(UUID(item["uuid"]))
                if identifier == item["uuid"]:
                    self.queue.mark_changed(identifier)
            except (OSError, ValueError, TypeError, KeyError, UnicodeDecodeError):
                continue

    def start(self):
        self.enqueue_existing()
        self.worker.start()

    def stop(self):
        self.worker.stop()


def configure_from_environment(state_directory: Path, notes_root: Path):
    """No partial activation; environment variables contain no default secrets."""
    owner = os.environ.get("NP_NOTES_SYNC_OWNER")
    repo = os.environ.get("NP_NOTES_SYNC_REPOSITORY")
    token = os.environ.get("NP_NOTES_SYNC_TOKEN")
    secret = os.environ.get("NP_NOTES_SYNC_PASSPHRASE")
    if not all((owner, repo, token, secret)):
        return None
    if len(secret) < 16:
        raise ValueError("Sync passphrase must be at least 16 characters")
    return EncryptedOutboundService(
        state_directory, notes_root, owner, repo, token, secret,
        branch=os.environ.get("NP_NOTES_SYNC_BRANCH", "main"),
    )
