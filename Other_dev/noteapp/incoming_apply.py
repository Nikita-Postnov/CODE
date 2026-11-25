"""Conservative fast-forward of unchanged NP Notes on GUI thread.

Never runs on a note being edited. Existing-note updates require a stored
baseline digest matching the current disk snapshot. A durable full-folder
backup is made before modifying any local file. All partial changes are
rolled back on failure; the immutable backup remains available.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from uuid import UUID, uuid4

from .encrypted_sync import unseal
from .incoming_sync import IncomingConflict
from .sync_snapshot import pack_note, unpack_to_memory, restore_attachment_links


def _revision_path(state_dir, note_id, sha, kind):
    if str(UUID(note_id)) != note_id or not re.fullmatch("[a-f0-9]{40}", sha):
        raise IncomingConflict("Invalid revision identifier")
    if kind not in ("pending_remote_updates", "remote_conflicts"):
        raise IncomingConflict("Invalid staging kind")
    return Path(state_dir) / kind / note_id / (sha + ".enc")


def stage_pending_update(state_dir, note_id, sha, encrypted):
    """Durably stage authenticated ciphertext; no local note is altered."""
    destination = _revision_path(state_dir, note_id, sha, "pending_remote_updates")
    if not isinstance(encrypted, bytes) or len(encrypted) > 50 * 1024 * 1024:
        raise IncomingConflict("Invalid encrypted revision")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return destination
    tmp = destination.with_name(destination.name + "." + uuid4().hex + ".tmp")
    try:
        with tmp.open("xb") as stream:
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, destination)
    finally:
        tmp.unlink(missing_ok=True)
    return destination


def _atomic_write(path, raw):
    temp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temp.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def apply_clean_remote_revision(note_folder, state_dir, note_id, encrypted,
                                secret, baseline_digest):
    """Fast-forward only unchanged disk state, with backup and rollback.

    Caller must synchronize the in-memory NotesApp objects, and must never
    invoke this for the currently open note or during an outstanding edit.
    """
    folder = Path(note_folder)
    if folder.is_symlink() or not folder.is_dir():
        raise IncomingConflict("Local note folder is unsafe")
    before = pack_note(folder, note_id)
    if not baseline_digest or hashlib.sha256(before).hexdigest() != baseline_digest:
        raise IncomingConflict("Local note has unmerged edits")
    _, prior_files = unpack_to_memory(before, note_id)
    remote = unseal(encrypted, secret, note_id)
    updated, next_files = unpack_to_memory(remote, note_id)
    updated = dict(updated)
    updated["content"] = restore_attachment_links(
        updated.get("content"), folder, next_files
    )
    for candidate in folder.iterdir():
        if candidate.is_symlink():
            raise IncomingConflict("Symlink in note folder cannot be backed up")
    parent = Path(state_dir) / "remote_update_backups" / note_id
    parent.mkdir(parents=True, exist_ok=True)
    backup = parent / uuid4().hex
    shutil.copytree(folder, backup)
    # Keep a complete pre-update copy even after success, for manual recovery.
    original_note = (folder / "note.json").read_bytes()
    changed = False
    try:
        for filename, raw in next_files.items():
            _atomic_write(folder / filename, raw)
            changed = True
        _atomic_write(
            folder / "note.json",
            json.dumps(updated, ensure_ascii=False, indent=4).encode("utf-8")
        )
        changed = True
        # Drop only tracked attachment files after the new metadata is durable.
        for filename in prior_files.keys() - next_files.keys():
            (folder / filename).unlink()
        return folder
    except Exception as exc:
        if changed:
            try:
                for filename, raw in prior_files.items():
                    _atomic_write(folder / filename, raw)
                for filename in next_files.keys() - prior_files.keys():
                    (folder / filename).unlink(missing_ok=True)
                _atomic_write(folder / "note.json", original_note)
            except Exception as recovery_exc:
                raise IncomingConflict(
                    "Remote update failed; rollback also failed; durable "
                    "backup retained at " + str(backup)
                ) from recovery_exc
        raise IncomingConflict("Remote update failed; old files restored") from exc
