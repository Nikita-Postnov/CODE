"""Store GitHub sync credentials with Windows DPAPI (never plaintext on disk).

The encrypted blob is bound to the Windows user profile. Each additional
computer must be enrolled separately with the same sync passphrase.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .github_sync import SyncError, atomic_bytes


def save_credentials(state_dir: Path, token: str, passphrase: str) -> None:
    if os.name != "nt":
        raise SyncError("Credential enrollment requires Windows DPAPI")
    if not token or len(passphrase) < 16:
        raise SyncError("GitHub token and a passphrase of at least 16 characters are required")
    from .recovery import _crypt
    raw = json.dumps(
        {"version": 1, "token": token, "passphrase": passphrase},
        ensure_ascii=False,
    ).encode("utf-8")
    if len(raw) > 8192:
        raise SyncError("Unexpectedly large credentials")
    encrypted = _crypt(raw, decrypt=False)
    target = Path(state_dir) / "credentials.dpapi"
    if target.exists():
        raise SyncError("Credentials already enrolled; backup before replacing")
    atomic_bytes(target, encrypted)


def load_credentials(state_dir: Path) -> tuple[str, str] | None:
    path = Path(state_dir) / "credentials.dpapi"
    if not path.is_file():
        return None
    if os.name != "nt":
        raise SyncError("Windows DPAPI credentials cannot be opened on this device")
    from .recovery import _crypt
    if path.stat().st_size > 16384:
        raise SyncError("Invalid credential size")
    try:
        record = json.loads(_crypt(path.read_bytes(), decrypt=True).decode("utf-8"))
    except Exception as exc:
        raise SyncError("Cannot unlock device-specific GitHub credentials") from exc
    if not isinstance(record, dict) or record.get("version") != 1:
        raise SyncError("Unrecognized GitHub credential envelope")
    token, passphrase = record.get("token"), record.get("passphrase")
    if not isinstance(token, str) or not token or not isinstance(passphrase, str) or len(passphrase) < 16:
        raise SyncError("Invalid unlocked GitHub credentials")
    return token, passphrase
