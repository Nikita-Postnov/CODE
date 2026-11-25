"""Safe note folder snapshotter: supports existing title-based NP Notes folders.

Only explicitly supplied note folders are read. Never imports application config,
never touches real Data automatically and never follows symbolic links.
"""
from __future__ import annotations
import base64
import json
from pathlib import Path
from uuid import UUID

MAX_FILE_BYTES = 15 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 24 * 1024 * 1024
IGNORED_NAMES = {"note_cache.json", "note.json"}
IGNORED_PREFIXES = ("note_backup_", ".")


class UnsafeSnapshot(ValueError):
    pass


def _valid_uuid(value):
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except (TypeError, ValueError, AttributeError) as exc:
        raise UnsafeSnapshot("Invalid UUID") from exc


def pack_note(note_folder: Path, note_id: str) -> bytes:
    """Create in-memory snapshot of one saved note and its attachments.

    Called after atomic local save; no local note is modified.
    """
    _valid_uuid(note_id)
    folder = Path(note_folder)
    if folder.is_symlink() or not folder.is_dir():
        raise UnsafeSnapshot("Unsafe note folder")
    meta = folder / "note.json"
    if meta.is_symlink() or not meta.is_file() or meta.stat().st_size > MAX_FILE_BYTES:
        raise UnsafeSnapshot("Missing or unsafe note.json")
    try:
        note = json.loads(meta.read_bytes())
    except (ValueError, UnicodeDecodeError) as exc:
        raise UnsafeSnapshot("Invalid note JSON") from exc
    if not isinstance(note, dict) or note.get("uuid") != note_id:
        raise UnsafeSnapshot("Wrong note UUID")
    files = {}
    total = len(json.dumps(note, ensure_ascii=False).encode())
    for child in sorted(folder.iterdir()):
        if child.name in IGNORED_NAMES or child.name.startswith(IGNORED_PREFIXES):
            continue
        if child.is_symlink() or not child.is_file() or child.resolve().parent != folder.resolve():
            raise UnsafeSnapshot("Unsafe attachment")
        if child.stat().st_size > MAX_FILE_BYTES:
            raise UnsafeSnapshot("Attachment too large")
        raw = child.read_bytes()
        total += len(raw) * 2
        if total > MAX_SNAPSHOT_BYTES:
            raise UnsafeSnapshot("Too many attachment bytes")
        files[child.name] = base64.b64encode(raw).decode("ascii")
    result = json.dumps({"version": 1, "note": note, "attachments": files},
                        ensure_ascii=False, separators=(",", ":")).encode()
    if len(result) > MAX_SNAPSHOT_BYTES:
        raise UnsafeSnapshot("Snapshot too large")
    return result


def unpack_to_memory(snapshot: bytes, note_id: str):
    """Parse and validate without overwriting any existing local data."""
    _valid_uuid(note_id)
    if not isinstance(snapshot, bytes) or len(snapshot) > MAX_SNAPSHOT_BYTES:
        raise UnsafeSnapshot("Invalid snapshot size")
    try:
        data = json.loads(snapshot)
    except (ValueError, UnicodeDecodeError) as exc:
        raise UnsafeSnapshot("Corrupted snapshot") from exc
    if not isinstance(data, dict) or data.get("version") != 1:
        raise UnsafeSnapshot("Invalid snapshot version")
    note = data.get("note")
    attachments = data.get("attachments")
    if not isinstance(note, dict) or note.get("uuid") != note_id or not isinstance(attachments, dict):
        raise UnsafeSnapshot("Wrong snapshot identity")
    files = {}
    for filename, encoded in attachments.items():
        if (not isinstance(filename, str) or filename in ("", ".", "..")
                or filename.startswith(".") or "/" in filename or chr(92) in filename
                or not isinstance(encoded, str)):
            raise UnsafeSnapshot("Unsafe filename")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, UnicodeError) as exc:
            raise UnsafeSnapshot("Invalid attachment encoding") from exc
        if len(raw) > MAX_FILE_BYTES:
            raise UnsafeSnapshot("Attachment size limit")
        files[filename] = raw
    return note, files
