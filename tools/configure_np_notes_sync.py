"""Interactive, opt-in per-device enrollment for encrypted NP Notes sync.

No arguments -> read-only usage. Never reads or uploads existing notes.
Credentials are prompted without echo and encrypted using Windows DPAPI.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "Other_dev"
sys.path.insert(0, str(ROOT))

from noteapp.github_sync import GitHubStore, SyncError, atomic_bytes
from noteapp.sync_secrets import save_credentials


def main(argv=None):
    parser = argparse.ArgumentParser(description="Configure encrypted NP Notes sync on this Windows user profile")
    parser.add_argument("--launcher-root", required=True, type=Path)
    parser.add_argument("--repository", required=True, help="Private owner/repository")
    parser.add_argument("--apply", action="store_true", help="Opt in; no files changed without this flag")
    args = parser.parse_args(argv)
    if not args.apply:
        print("MODE=DRY_RUN")
        print("REPOSITORY=" + args.repository)
        print("NOTES_NOT_READ=TRUE")
        return 0
    if os.name != "nt":
        raise SyncError("Device enrollment requires Windows DPAPI")
    if not (args.launcher_root / "Data" / "Notes").is_dir():
        raise SyncError("Launcher Notes directory not found")
    state_dir = args.launcher_root / "Data" / "NoteSync"
    if (state_dir / "config.json").exists() or (state_dir / "credentials.dpapi").exists():
        raise SyncError("Sync already configured; refusing to replace credentials automatically")

    token = getpass.getpass("GitHub fine-grained token (private repository Contents read/write): ")
    password = getpass.getpass("Sync encryption passphrase (at least 16 characters): ")
    repeated = getpass.getpass("Repeat the encryption passphrase: ")
    if not password or len(password) < 16 or password != repeated:
        raise SyncError("Passphrase mismatch or too short")
    # Verify PRIVACY first; never create local state for public repos.
    store = GitHubStore(args.repository, token)
    store.check_private()
    state_dir.mkdir(parents=True, exist_ok=True)
    save_credentials(state_dir, token, password)
    atomic_bytes(state_dir / "config.json", json.dumps(
        {"version": 1, "enabled": True, "repository": args.repository,
         "interval_minutes": 5, "attachments": True},
        ensure_ascii=False,
    ).encode("utf-8"))
    print("CONFIGURED=TRUE")
    print("REPOSITORY=" + args.repository)
    print("INTERVAL_MINUTES=5")
    print("OFFLINE_MODE=LOCAL_ONLY_WITH_RETRY")
    print("NOTES_NOT_READ=TRUE")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (SyncError, OSError) as exc:
        print("SETUP_FAILED=" + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
