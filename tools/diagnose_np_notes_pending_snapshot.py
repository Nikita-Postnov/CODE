"""Local read-only NP Notes pending upload diagnostic.

Runs the installed snapshot validator, never prints note contents, titles,
UUIDs, attachment paths, file names, tokens or raw exceptions. No network.
"""
from __future__ import annotations
import argparse
import sqlite3
import sys
from pathlib import Path
from uuid import UUID


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--launcher-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.launcher_root.resolve(strict=True)
    sys.path.insert(0, str(root))
    from noteapp.sync_snapshot import pack_note, UnsafeSnapshot
    from noteapp.sync_service import EncryptedOutboundService

    state = root / "Data" / "NPNotesSync"
    notes = root / "Data" / "Notes"
    database = state / "pending_sync.sqlite3"
    print("READ_ONLY=TRUE")
    print("NETWORK_ACCESSED=FALSE")
    print("TOKEN_ACCESSED=FALSE")
    print("NOTE_CONTENT_PRINTED=FALSE")
    print("ATTACHMENT_CONTENT_PRINTED=FALSE")
    if not database.is_file():
        print("QUEUE_DATABASE=MISSING")
        return 2
    # Use SQLite read-only mode. Never change the live sync queue.
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=3) as db:
        rows = db.execute("SELECT item_id FROM pending ORDER BY modified_ns").fetchall()
    print("PENDING_COUNT=" + str(len(rows)))
    if not notes.is_dir():
        print("NOTES_DIRECTORY=MISSING")
        return 2
    # Construct an uninitialized service strictly for reuse of the installed
    # folder locator: no network transport, credentials or worker is created.
    locator = object.__new__(EncryptedOutboundService)
    locator.repository_root = notes
    for index, (note_id,) in enumerate(rows, start=1):
        prefix = "PENDING_" + str(index) + "_"
        try:
            UUID(note_id)
            folder = locator._find_folder(note_id)
            if folder is None:
                print(prefix + "RESULT=LOCAL_NOTE_NOT_FOUND")
                continue
            pack_note(folder, note_id)
            print(prefix + "RESULT=SNAPSHOT_VALID")
        except UnsafeSnapshot as exc:
            # This exception is internal fixed-phrase validation reason, not
            # raw paths, note titles or user data.
            allowed = {
                "Duplicate local note UUID", "Unsafe note folder",
                "Missing or unsafe note.json", "Invalid note JSON",
                "Wrong note UUID", "Unsafe attachment",
                "Attachment too large", "Too many attachment bytes",
                "Snapshot too large", "Invalid UUID"
            }
            reason = str(exc)
            print(prefix + "RESULT=UNSAFE_SNAPSHOT")
            print(prefix + "REASON=" + (reason if reason in allowed else "Other unsafe snapshot"))
        except Exception as exc:
            print(prefix + "RESULT=OTHER_ERROR")
            print(prefix + "ERROR_CLASS=" + type(exc).__name__)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
