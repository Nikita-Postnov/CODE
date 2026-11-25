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
import os as _sync_os
import shutil
from uuid import uuid4
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from .encrypted_sync import GitHubTransport, SyncConflict, seal, unseal
from .offline_sync import OfflineSyncQueue, OfflineSyncWorker
from .sync_snapshot import pack_note, UnsafeSnapshot
from .incoming_sync import import_new_note, stage_conflict, restore_conflict_as_copy, IncomingConflict
from .incoming_apply import stage_pending_update, apply_clean_remote_revision


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
        self._operation_lock = threading.Lock()
        self._db_path = self.state_directory / "remote_revisions.sqlite3"
        self._init_db()
        self.received_count = 0
        # Deletions are durable, explicit user actions. Mere Trash moves are not
        # GitHub deletions. Older clients must be upgraded before using this.
        self.worker = OfflineSyncWorker(
            self.queue, self._online, self._send, receive_encrypted=self._receive
        )

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self._db_path), timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def _init_db(self):
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS remote_revisions
                          (note_id TEXT PRIMARY KEY, blob_sha TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS local_content
                          (note_id TEXT PRIMARY KEY, content_sha256 TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS deletions
                          (note_id TEXT PRIMARY KEY,
                           status TEXT NOT NULL CHECK(
                             status IN ('prepared','pending','done','remote')))""")

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

    def _deletion_status(self, note_id):
        with self._lock, self._connect() as db:
            row = db.execute("SELECT status FROM deletions WHERE note_id=?",
                             (note_id,)).fetchone()
            return row[0] if row else None

    def _set_deletion_status(self, note_id, status):
        if status not in ("prepared", "pending", "done", "remote"):
            raise ValueError("Invalid deletion status")
        note_id = str(UUID(note_id))
        with self._lock, self._connect() as db:
            db.execute("""INSERT INTO deletions(note_id,status) VALUES (?,?)
                          ON CONFLICT(note_id) DO UPDATE SET status=excluded.status""",
                       (note_id, status))

    def _folder_in_trash(self, note_id):
        root = self.repository_root / "Trash"
        if not root.is_dir() or root.is_symlink():
            return None
        for folder in root.iterdir():
            if not folder.is_dir() or folder.is_symlink():
                continue
            meta = folder / "note.json"
            if meta.is_symlink() or not meta.is_file():
                continue
            try:
                if meta.stat().st_size > 15 * 1024 * 1024:
                    continue
                if json.loads(meta.read_bytes()).get("uuid") == note_id:
                    return folder
            except (OSError, ValueError, UnicodeDecodeError, AttributeError):
                continue
        return None

    def moved_to_trash(self, note_id):
        """Cancel queued upload only AFTER the local Trash move is complete."""
        note_id = str(UUID(note_id))
        if self._folder_in_trash(note_id) is None:
            raise ValueError("Cannot acknowledge nonexistent Trash move")
        with self._operation_lock:
            if self._find_folder(note_id) is not None:
                raise ValueError("Note still active")
            self.queue.discard(note_id)

    def restored_from_trash(self, note_id):
        """A tombstoned UUID cannot be silently resurrected in the cloud."""
        note_id = str(UUID(note_id))
        if self._deletion_status(note_id) is not None:
            raise ValueError("Deleted note requires restoration as a new UUID")
        self.saved(note_id)

    def prepare_permanent_delete(self, note_id):
        """Write intent before removing a local Trash folder (crash-safe)."""
        note_id = str(UUID(note_id))
        with self._operation_lock:
            if self._folder_in_trash(note_id) is None:
                raise ValueError("Permanent deletion requires local Trash entry")
            if self._find_folder(note_id) is not None:
                raise ValueError("Active note with same UUID exists")
            if self._deletion_status(note_id) not in (None, "prepared"):
                raise ValueError("Deletion already recorded")
            self._set_deletion_status(note_id, "prepared")
        return True

    def commit_permanent_delete(self, note_id):
        """Only enqueue a remote deletion AFTER local physical deletion."""
        note_id = str(UUID(note_id))
        with self._operation_lock:
            if self._find_folder(note_id) is not None or self._folder_in_trash(note_id) is not None:
                raise ValueError("Note is still present on disk")
            if self._deletion_status(note_id) not in ("prepared", "pending"):
                raise ValueError("Unprepared permanent deletion")
            self._set_deletion_status(note_id, "pending")
            self.queue.mark_changed(note_id)
        return True

    def cancel_prepared_delete(self, note_id):
        """Allowed only while the Trash copy still exists."""
        note_id = str(UUID(note_id))
        with self._operation_lock:
            if self._folder_in_trash(note_id) is None:
                raise ValueError("Cannot cancel deletion after files disappeared")
            with self._lock, self._connect() as db:
                db.execute("DELETE FROM deletions WHERE note_id=? AND status='prepared'",
                           (note_id,))

    def _reconcile_prepared_deletions(self):
        """Recover a crash between local removal and queue commit."""
        with self._lock, self._connect() as db:
            ids = [row[0] for row in db.execute(
                "SELECT note_id FROM deletions WHERE status='prepared'")]
        for note_id in ids:
            if self._find_folder(note_id) is None and self._folder_in_trash(note_id) is None:
                self._set_deletion_status(note_id, "pending")
                self.queue.mark_changed(note_id)

    def _decode_tombstone(self, note_id, encrypted):
        try:
            record = json.loads(unseal(encrypted, self.passphrase, note_id))
            if record != {"v": 1, "uuid": note_id}:
                raise ValueError("Invalid deletion marker")
        except Exception as exc:
            raise SyncConflict("Invalid authenticated deletion marker") from exc

    def _send_permanent_delete(self, note_id):
        self.transport.assert_private()
        encrypted, remote_sha = self.transport.read(note_id)
        known = self._known_sha(note_id)
        # Never delete an unknown or concurrently changed remote revision.
        if remote_sha is not None and known != remote_sha:
            raise SyncConflict("Remote note not acknowledged for deletion")
        marker, _ = self.transport.read_tombstone(note_id)
        if marker is not None:
            self._decode_tombstone(note_id, marker)
        else:
            payload = json.dumps({"v": 1, "uuid": note_id}, separators=(",", ":")).encode()
            try:
                self.transport.write_tombstone(
                    note_id, seal(payload, self.passphrase, note_id)
                )
            except SyncConflict:
                marker, _ = self.transport.read_tombstone(note_id)
                if marker is None:
                    raise
                self._decode_tombstone(note_id, marker)
        if remote_sha is not None:
            self.transport.delete_note(note_id, remote_sha)
        # Do not acknowledge until GitHub confirms the note is absent.
        if self.transport.read(note_id)[1] is not None:
            raise SyncConflict("Remote note still exists after deletion")
        self._set_deletion_status(note_id, "done")
        return True

    def _receive_tombstones(self):
        tombstones = set(self.transport.list_tombstone_ids())
        for note_id in tombstones:
            encrypted, _ = self.transport.read_tombstone(note_id)
            if encrypted is None:
                continue
            self._decode_tombstone(note_id, encrypted)
            status = self._deletion_status(note_id)
            if status not in ("pending", "done"):
                self._set_deletion_status(note_id, "remote")
            folder = self._find_folder(note_id)
            if folder is not None:
                # Worker never moves files while UI is reading them. GUI will
                # move this note to Trash only when it is safe to do so.
                target = self.state_directory / "pending_remote_deletions"
                target.mkdir(parents=True, exist_ok=True)
                marker = target / (note_id + ".delete")
                if not marker.exists():
                    marker.write_bytes(b"NPNotes remote deletion v1")
        return tombstones

    def apply_staged_remote_deletions(self, protected_ids=()):
        """GUI-thread, reversible soft-delete of notes deleted in GitHub.

        No local note is permanently destroyed. The active note is deferred.
        """
        if not self._operation_lock.acquire(blocking=False):
            return []
        removed = []
        try:
            root = self.state_directory / "pending_remote_deletions"
            if not root.is_dir():
                return removed
            blocked = set(protected_ids)
            for marker in sorted(root.glob("*.delete")):
                if marker.is_symlink():
                    continue
                note_id = marker.stem
                if note_id in blocked or self._deletion_status(note_id) != "remote":
                    continue
                folder = self._find_folder(note_id)
                if folder is not None:
                    trash = self.repository_root / "Trash"
                    trash.mkdir(parents=True, exist_ok=True)
                    if trash.is_symlink():
                        continue
                    destination = trash / folder.name
                    if destination.exists() or destination.is_symlink():
                        # Preserve both local copies and retain the marker.
                        continue
                    shutil.move(str(folder), str(destination))
                self.queue.discard(note_id)
                marker.unlink()
                removed.append(note_id)
        finally:
            self._operation_lock.release()
        return removed

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
        if len(matches) > 1:
            raise UnsafeSnapshot("Duplicate local note UUID")
        return matches[0] if matches else None

    def _online(self):
        """Probe the *configured private repository*, not the GitHub API root.

        A browser having internet access does not guarantee the configured
        repository is reachable through Python's proxy/VPN. The actual
        authenticated metadata endpoint is authoritative for sync readiness.
        Never log the token or the HTTP request headers.
        """
        try:
            return self.transport.assert_private() is True
        except Exception as exc:
            # A failed probe must not drop queued local changes. Keep only
            # a sanitized error class for diagnostics; never include the
            # exception text, which may contain URLs or proxy credentials.
            self.last_probe_error = type(exc).__name__
            return False

    def _send(self, note_id):
        with self._operation_lock:
            return self._send_unlocked(note_id)

    def _send_unlocked(self, note_id):
        status = self._deletion_status(note_id)
        if status == "pending":
            return self._send_permanent_delete(note_id)
        if status in ("prepared", "done", "remote"):
            return True
        if self._folder_in_trash(note_id) is not None:
            # The user moved the note to local Trash, not permanently deleted.
            return True
        marker, _ = self.transport.read_tombstone(note_id)
        if marker is not None:
            self._decode_tombstone(note_id, marker)
            self._set_deletion_status(note_id, "remote")
            return True
        folder = self._find_folder(note_id)
        if folder is None:
            raise UnsafeSnapshot("Local note deleted or not found")
        self.transport.assert_private()
        plain = pack_note(folder, note_id)
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

    def _receive(self):
        with self._operation_lock:
            return self._receive_unlocked()

    def _receive_unlocked(self):
        """Import absent notes only; quarantine all divergent remote revisions."""
        self.transport.assert_private()
        remote_deleted = self._receive_tombstones()
        for note_id in self.transport.list_note_ids():
            if note_id in remote_deleted or self._folder_in_trash(note_id) is not None:
                continue
            encrypted, sha = self.transport.read(note_id)
            if encrypted is None or sha is None:
                continue
            known = self._known_sha(note_id)
            if known == sha:
                continue
            folder = self._find_folder(note_id)
            if folder is not None:
                if known is None:
                    # Another device can already have identical note data.
                    local_plain = pack_note(folder, note_id)
                    if unseal(encrypted, self.passphrase, note_id) == local_plain:
                        self._remember_sha(note_id, sha)
                        self._remember_digest(
                            note_id, hashlib.sha256(local_plain).hexdigest()
                        )
                        continue
                # Existing revisions can advance automatically ONLY when
                # this disk snapshot equals the previously acknowledged one.
                baseline = self._digest(note_id)
                try:
                    local_clean = (
                        known is not None and baseline is not None
                        and hashlib.sha256(pack_note(folder, note_id)).hexdigest()
                            == baseline
                    )
                except (OSError, ValueError, UnsafeSnapshot):
                    local_clean = False
                if local_clean:
                    pending = stage_pending_update(
                        self.state_directory, note_id, sha, encrypted
                    )
                    # Never apply filesystem changes from the sync worker.
                    for obsolete in pending.parent.glob("*.enc"):
                        if obsolete != pending:
                            obsolete.unlink(missing_ok=True)
                else:
                    stage_conflict(self.state_directory, note_id, sha, encrypted)
                continue
            if known is not None:
                # A locally deleted existing note must not be resurrected.
                stage_conflict(self.state_directory, note_id, sha, encrypted)
                continue
            # Incoming new UUID: never overwrite any local folder.
            import_new_note(
                self.repository_root, self.state_directory, note_id,
                encrypted, self.passphrase,
            )
            self._remember_sha(note_id, sha)
            self._remember_digest(
                note_id, hashlib.sha256(
                    unseal(encrypted, self.passphrase, note_id)
                ).hexdigest()
            )
            self.received_count += 1
        return True

    def apply_staged_remote_updates(self, protected_ids=()):
        """Apply clean revisions on the GUI thread; never modify open notes.

        A busy worker makes this a quick no-op rather than blocking the UI.
        Returns local paths for explicit in-memory model refresh.
        """
        if not self._operation_lock.acquire(blocking=False):
            return []
        changed = []
        try:
            root = self.state_directory / "pending_remote_updates"
            if not root.is_dir():
                return changed
            blocked = set(protected_ids)
            for staged in sorted(root.glob("*/*.enc")):
                note_id, sha = staged.parent.name, staged.stem
                if note_id in blocked or staged.is_symlink():
                    continue
                try:
                    known = self._known_sha(note_id)
                    if known == sha:
                        staged.unlink(missing_ok=True)
                        continue
                    if known is None:
                        raise IncomingConflict("No acknowledged baseline")
                    folder = self._find_folder(note_id)
                    if folder is None:
                        raise IncomingConflict("Local note missing")
                    encrypted = staged.read_bytes()
                    updated = apply_clean_remote_revision(
                        folder, self.state_directory, note_id, encrypted,
                        self.passphrase, self._digest(note_id),
                    )
                    self._remember_sha(note_id, sha)
                    self._remember_digest(
                        note_id, hashlib.sha256(pack_note(updated, note_id)).hexdigest()
                    )
                    changed.append((note_id, updated))
                    staged.unlink(missing_ok=True)
                except Exception:
                    # The staged version remains encrypted and recoverable.
                    # Never hide unexpected data failures or drop user edits.
                    try:
                        if staged.exists():
                            stage_conflict(
                                self.state_directory, note_id, sha,
                                staged.read_bytes()
                            )
                            staged.unlink(missing_ok=True)
                    except Exception:
                        pass
            return changed
        finally:
            self._operation_lock.release()

    def restore_conflict_copy(self, note_id, sha):
        """User-requested restoration as a separate note, never an overwrite."""
        target = restore_conflict_as_copy(
            self.repository_root, self.state_directory, note_id, sha,
            self.passphrase,
        )
        note = json.loads((target / "note.json").read_bytes())
        self.saved(note["uuid"])
        self.received_count += 1
        return target

    def saved(self, note_id):
        self.queue.mark_changed(str(UUID(note_id)))
        # The worker batches writes on its 5-minute interval; no upload
        # is triggered by every keystroke/autosave.

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
        self._reconcile_prepared_deletions()
        self.enqueue_existing()
        self.worker.start()

    def stop(self):
        self.worker.stop()


def configure_from_environment(state_directory: Path, notes_root: Path):
    """Fail closed until a deliberate, backed-up activation is present."""
    marker = Path(state_directory) / "sync_enabled.json"
    enabled = os.environ.get("NP_NOTES_SYNC_ENABLE") == "1"
    if not enabled and marker.is_file() and not marker.is_symlink():
        try:
            enabled = json.loads(marker.read_text(encoding="utf-8")) == {
                "version": 1, "enabled": True
            }
        except (OSError, ValueError, UnicodeDecodeError):
            enabled = False
    if not enabled:
        return None
    from .sync_credentials import load_dpapi_credentials
    config = load_dpapi_credentials(state_directory)
    if config:
        return EncryptedOutboundService(
            state_directory, notes_root, config["owner"], config["repository"],
            config["token"], config["passphrase"],
            branch=config.get("branch", "main"),
        )
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
