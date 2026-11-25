"""Windows-only encrypted crash-draft storage.

Drafts are temporary and *local to the Windows user profile*: DPAPI protects
HTML drafts at rest. They must never be used as cross-device backup. No plaintext
fallback exists on unsupported platforms. The regular note.json format is unchanged.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import tempfile
import time
from ctypes import wintypes
from pathlib import Path
from uuid import UUID

MAX_DRAFT_BYTES = 2 * 1024 * 1024


class DraftUnavailable(RuntimeError):
    """Draft encryption is unavailable or the profile cannot decrypt it."""


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _crypt(data: bytes, *, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise DraftUnavailable("Encrypted recovery requires Windows DPAPI")
    if not data or len(data) > MAX_DRAFT_BYTES + 65536:
        raise ValueError("Invalid recovery draft size")
    source_buffer = ctypes.create_string_buffer(data)
    source = _Blob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    result = _Blob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if decrypt:
        fn = crypt32.CryptUnprotectData
        fn.argtypes = [
            ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob),
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(_Blob),
        ]
        fn.restype = wintypes.BOOL
        ok = fn(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result))
    else:
        fn = crypt32.CryptProtectData
        fn.argtypes = [
            ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.POINTER(_Blob),
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(_Blob),
        ]
        fn.restype = wintypes.BOOL
        ok = fn(ctypes.byref(source), "NP Notes crash recovery", None, None, None,
                0x00000001, ctypes.byref(result))
    if not ok:
        raise DraftUnavailable("Windows could not protect or decrypt recovery draft")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(ctypes.cast(result.pbData, ctypes.c_void_p))


def _uuid(value: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Invalid note UUID") from exc


def draft_path(directory: Path, note_uuid: str) -> Path:
    return Path(directory) / (_uuid(note_uuid) + ".dpapi")


def save_draft(directory: Path, note_uuid: str, html: str) -> Path:
    if not isinstance(html, str):
        raise TypeError("HTML content must be a string")
    record = {
        "version": 1,
        "uuid": _uuid(note_uuid),
        "html": html,
        "timestamp_ns": time.time_ns(),
    }
    raw = json.dumps(record, ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_DRAFT_BYTES:
        raise ValueError("Recovery draft is too large")
    ciphertext = _crypt(raw, decrypt=False)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = draft_path(directory, note_uuid)
    fd, name = tempfile.mkstemp(prefix=".draft_", suffix=".tmp", dir=str(directory))
    staging = Path(name)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(ciphertext)
            out.flush()
            os.fsync(out.fileno())
        os.replace(staging, target)
    finally:
        staging.unlink(missing_ok=True)
    return target


def read_draft(directory: Path, note_uuid: str) -> dict | None:
    source = draft_path(directory, note_uuid)
    if not source.is_file():
        return None
    raw = source.read_bytes()
    if len(raw) > MAX_DRAFT_BYTES + 65536:
        raise ValueError("Recovery draft is too large")
    record = json.loads(_crypt(raw, decrypt=True).decode("utf-8"))
    if (not isinstance(record, dict) or record.get("version") != 1
            or record.get("uuid") != _uuid(note_uuid)
            or not isinstance(record.get("html"), str)):
        raise ValueError("Invalid recovery draft structure")
    return record


def clear_draft(directory: Path, note_uuid: str) -> None:
    draft_path(directory, note_uuid).unlink(missing_ok=True)


def list_drafts(directory: Path) -> list[str]:
    directory = Path(directory)
    if not directory.is_dir():
        return []
    result = []
    for path in directory.glob("*.dpapi"):
        try:
            uuid = _uuid(path.stem)
        except ValueError:
            continue
        if path.is_file() and not path.is_symlink():
            result.append(uuid)
    return sorted(set(result))
