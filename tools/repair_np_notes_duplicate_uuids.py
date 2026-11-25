"""Conservative two-folder duplicate UUID repair for NP Notes.

Requires NP Notes stopped and a separately verified full Notes-only backup.
No network or credentials. Keeps the canonical version, imports the other
as a NEW note with a NEW UUID, then archives the original duplicate folder.
Never overwrites existing folders; fails closed on ambiguity or unsafe files.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

def _is_file_safe(folder):
    if folder.is_symlink() or not folder.is_dir():
        return False
    for path in folder.iterdir():
        if path.is_symlink() or not path.is_file():
            return False
    return True

def _load(path):
    return json.loads(path.read_bytes())

def recover(root: Path, backup: Path, *, apply: bool = False):
    root = root.resolve(strict=True)
    backup = backup.resolve(strict=True)
    if not (backup / "SHA256-manifest.json").is_file():
        raise RuntimeError("VERIFIED_BACKUP_MANIFEST_MISSING")
    notes = root / "Data" / "Notes"
    if notes.is_symlink() or not notes.is_dir():
        raise RuntimeError("UNSAFE_NOTES_FOLDER")
    sys.path.insert(0, str(root))
    from noteapp.incoming_sync import _folder_name
    from noteapp.sync_snapshot import pack_note, unpack_to_memory, restore_attachment_links

    if apply:
        # Strictly NP Notes app, no broad Python/Choice process termination.
        if os.name != "nt":
            raise RuntimeError("APPLY_REQUIRES_WINDOWS")

    by_id = {}
    for folder in notes.iterdir():
        if not folder.is_dir() or folder.is_symlink() or folder.name == "Trash":
            continue
        meta = folder / "note.json"
        if meta.is_symlink() or not meta.is_file() or meta.stat().st_size > 15*1024*1024:
            continue
        try:
            record = _load(meta)
            uid = record.get("uuid")
            if not isinstance(uid, str) or str(UUID(uid)) != uid:
                continue
            by_id.setdefault(uid, []).append((folder, record))
        except (ValueError, KeyError, TypeError, OSError, UnicodeDecodeError):
            continue
    duplicates = [items for items in by_id.values() if len(items)>1]
    print("DUPLICATE_UUID_GROUPS=" + str(len(duplicates)))
    print("DRY_RUN=" + str(not apply).upper())
    if len(duplicates) != 1 or len(duplicates[0]) != 2:
        raise RuntimeError("REQUIRES_EXACTLY_ONE_TWO_FOLDER_DUPLICATE")

    pair = duplicates[0]
    canonical = []
    for folder, record in pair:
        try:
            if folder.name == _folder_name(record, record["uuid"]):
                canonical.append(folder)
        except Exception:
            pass
    print("CANONICAL_FOLDER_MATCHES=" + str(len(canonical)))
    if len(canonical) != 1:
        raise RuntimeError("AMBIGUOUS_PRIMARY_NOTE_REFUSING_CHANGES")
    primary = canonical[0]
    secondary, original = next((f,d) for f,d in pair if f != primary)
    note_id = original["uuid"]

    # Verify both *original* note.json files exist, unchanged, in the backed-up Notes tree.
    for folder, _ in pair:
        source = folder / "note.json"
        backed = backup / "Notes" / folder.name / "note.json"
        if not backed.is_file() or hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(backed.read_bytes()).digest():
            raise RuntimeError("BACKUP_MISMATCH_OR_INCOMPLETE")

    # Enforce a snapshot-safe payload, including attachments.
    plaintext = pack_note(secondary, note_id)
    note, attachments = unpack_to_memory(plaintext, note_id)
    for folder, _ in pair:
        if not _is_file_safe(folder):
            raise RuntimeError("UNSAFE_OR_NONFILE_ENTRY")
    print("SECONDARY_SNAPSHOT=VALID")
    print("BACKUP_VERIFIED_FOR_DUPLICATES=TRUE")
    if not apply:
        print("ACTION=RETAIN_CANONICAL_AND_RESTORE_SECONDARY_AS_NEW_NOTE")
        return

    new_id = str(uuid4())
    replacement = dict(note)
    replacement["uuid"] = new_id
    replacement["title"] = str(replacement.get("title", "")) + " (восстановлено)"
    target = notes / _folder_name(replacement, new_id)
    archive = root / "Data" / "NPNotesSync" / "duplicate_archive" / note_id / uuid4().hex
    if target.exists() or archive.exists():
        raise RuntimeError("DESTINATION_ALREADY_EXISTS")
    archive.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".npnotes-recovered-", dir=str(notes)))
    completed = False
    try:
        replacement["content"] = restore_attachment_links(
            replacement.get("content"), target, attachments
        )
        for filename, payload in attachments.items():
            with (stage / filename).open("xb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
        with (stage / "note.json").open("xb") as output:
            output.write(json.dumps(replacement, ensure_ascii=False, indent=4).encode("utf-8"))
            output.flush()
            os.fsync(output.fileno())
        if target.exists():
            raise RuntimeError("TARGET_APPEARED")
        os.rename(stage, target)
        completed = True
        # Archive after the independently readable restored note exists.
        if not (target / "note.json").is_file():
            raise RuntimeError("RESTORE_NOT_VERIFIED")
        os.rename(secondary, archive)
        print("RECOVERED_NOTE_CREATED=TRUE")
        print("OLD_SECONDARY_ARCHIVED=TRUE")
        print("ORIGINAL_PRIMARY_UNCHANGED=TRUE")
        print("ORIGINAL_SECONDARY_PRESERVED_IN_BACKUP_AND_ARCHIVE=TRUE")
    finally:
        if not completed and stage.exists():
            shutil.rmtree(stage)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--launcher-root", required=True, type=Path)
    p.add_argument("--backup-root", required=True, type=Path)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    try:
        recover(args.launcher_root, args.backup_root, apply=args.apply)
    except Exception as exc:
        print("REPAIR_STATUS=REFUSED_OR_FAILED")
        print("REASON_TYPE=" + (str(exc) if str(exc).isupper() and len(str(exc)) < 75 else type(exc).__name__))
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
