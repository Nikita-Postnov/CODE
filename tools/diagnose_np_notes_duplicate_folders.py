"""Read-only classification of duplicate note UUIDs pending synchronization.

No mutation; no network; no secrets; no note names, UUIDs, content, file names,
file paths, file hashes, or attachment contents in output.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

MAX_FILE = 15 * 1024 * 1024

def signature(folder):
    records = []
    for file in folder.iterdir():
        if file.is_symlink() or not file.is_file() or file.stat().st_size > MAX_FILE:
            return None
        if file.name.startswith(".") or file.name.startswith("note_backup_") or file.name == "note_cache.json":
            continue
        records.append((file.name, hashlib.sha256(file.read_bytes()).digest()))
    return tuple(sorted(records))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--launcher-root", type=Path, required=True)
    args = parser.parse_args()
    data = args.launcher_root / "Data"
    notes = data / "Notes"
    db_file = data / "NPNotesSync" / "pending_sync.sqlite3"
    print("READ_ONLY=TRUE")
    print("NETWORK_ACCESSED=FALSE")
    print("NOTE_CONTENT_PRINTED=FALSE")
    print("FILE_NAMES_PRINTED=FALSE")
    print("TOKEN_ACCESSED=FALSE")
    if not db_file.is_file() or not notes.is_dir():
        print("RESULT=REQUIRED_DIRECTORIES_MISSING")
        return 2
    with sqlite3.connect(db_file.as_uri()+"?mode=ro", uri=True) as db:
        identifiers = [row[0] for row in db.execute("SELECT item_id FROM pending ORDER BY modified_ns")]
    print("PENDING_COUNT=" + str(len(identifiers)))
    for ordinal, note_id in enumerate(identifiers, 1):
        prefix = "PENDING_" + str(ordinal) + "_"
        folders = []
        for folder in notes.iterdir():
            if folder.is_symlink() or not folder.is_dir() or folder.name == "Trash":
                continue
            meta = folder / "note.json"
            if meta.is_symlink() or not meta.is_file() or meta.stat().st_size > MAX_FILE:
                continue
            try:
                record = json.loads(meta.read_bytes())
                if isinstance(record, dict) and record.get("uuid") == note_id:
                    folders.append((folder, record))
            except (OSError, ValueError, UnicodeDecodeError):
                continue
        print(prefix + "FOLDER_COUNT=" + str(len(folders)))
        if not folders:
            print(prefix + "CLASS=LOCAL_NOTE_MISSING")
            continue
        if len(folders) == 1:
            print(prefix + "CLASS=UNIQUE")
            continue
        # Compare all sync-relevant files, without emitting digests or names.
        sig = [signature(folder) for folder, _ in folders]
        same = all(s is not None and s == sig[0] for s in sig)
        print(prefix + "EXACT_FILE_COPIES=" + str(same).upper())
        if same:
            print(prefix + "CLASS=IDENTICAL_DUPLICATE_FOLDERS")
        else:
            print(prefix + "CLASS=DIFFERENT_VERSIONS_PRESERVE_ALL")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
