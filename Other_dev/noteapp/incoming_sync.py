"""Receive encrypted NP Notes safely: only import never-before-seen UUIDs.

Existing local notes are NEVER overwritten here. Conflicting encrypted blobs
are quarantined for later resolution, without exposing plaintext on disk.
"""
from __future__ import annotations
import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import UUID
from .encrypted_sync import unseal
from .sync_snapshot import unpack_to_memory, UnsafeSnapshot


class IncomingConflict(RuntimeError):
    pass


def _folder_name(note: dict, note_id: str):
    """Equivalent to NP Notes safe_folder_name for ISO timestamp strings."""
    if str(UUID(note_id)) != note_id:
        raise IncomingConflict("Invalid note identity")
    title = note.get("title")
    timestamp = note.get("timestamp")
    if not isinstance(title, str) or not isinstance(timestamp, str):
        raise IncomingConflict("Missing title or timestamp")
    try:
        date = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IncomingConflict("Invalid note timestamp") from exc
    safe_title = re.sub(r"[^\w\-_ ]", "_", title)[:40].strip()
    return f"{safe_title} от {date:%d.%m.%Y %H-%M}, UUID({note_id[:8]})"


def stage_conflict(state_dir: Path, note_id: str, sha: str, ciphertext: bytes):
    """Keep encrypted conflicting remote revision, never local plaintext."""
    if str(UUID(note_id)) != note_id or not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise IncomingConflict("Invalid remote revision")
    folder = Path(state_dir) / "remote_conflicts" / note_id
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / (sha + ".enc")
    if destination.exists():
        return destination
    tmp = destination.with_suffix(".tmp")
    try:
        with tmp.open("xb") as output:
            output.write(ciphertext)
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp, destination)
    finally:
        tmp.unlink(missing_ok=True)
    return destination


def import_new_note(notes_root: Path, state_dir: Path, note_id: str,
                    encrypted: bytes, secret: str):
    """Atomic folder creation for an absent note; never replace existing data."""
    decrypted = unseal(encrypted, secret, note_id)
    note, attachments = unpack_to_memory(decrypted, note_id)
    target_root = Path(notes_root)
    if not target_root.is_dir() or target_root.is_symlink():
        raise IncomingConflict("Notes root is unsafe")
    target = target_root / _folder_name(note, note_id)
    if target.exists() or target.is_symlink():
        raise IncomingConflict("Target note folder already exists")
    stage_root = Path(state_dir) / "incoming_staging"
    stage_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="incoming-", dir=stage_root))
    try:
        for name, raw in attachments.items():
            with (temporary / name).open("xb") as out:
                out.write(raw)
                out.flush()
                os.fsync(out.fileno())
        note_raw = json.dumps(note, ensure_ascii=False, indent=4).encode("utf-8")
        with (temporary / "note.json").open("xb") as out:
            out.write(note_raw)
            out.flush()
            os.fsync(out.fileno())
        if target.exists() or target.is_symlink():
            raise IncomingConflict("Target created by another process")
        os.rename(temporary, target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return target
