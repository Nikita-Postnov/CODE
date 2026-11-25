"""Opt-in end-to-end encrypted NP Notes sync via a PRIVATE GitHub repository.

This module NEVER accesses Launcher/Data unless explicitly supplied a Notes path.
GitHub sees encrypted per-note snapshots; plaintext and credentials are never logged.
No remote deletions, no overwriting concurrent edits, no password-manager exports.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

MAX_SNAPSHOT = 20 * 1024 * 1024
MAX_NOTE_FILES = 200
MAX_REMOTE_FILES = 900
SYNC_INTERVAL_MS = 5 * 60 * 1000
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
IGNORED = re.compile(r"^(?:note_cache\.json|note_backup_.*\.json|.*\.tmp|.*\.dpapi)$", re.I)


class SyncError(Exception):
    pass


class Offline(SyncError):
    pass


class Conflict(SyncError):
    pass


def valid_uuid(value: str) -> str:
    try:
        value = str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise SyncError("Invalid note UUID") from exc
    if not UUID_RE.fullmatch(value):
        raise SyncError("Invalid note UUID")
    return value


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".np-sync-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def encrypt_snapshot(clear: bytes, password: str, repository: str, note_uuid: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not password or len(password) < 16:
        raise SyncError("Sync passphrase must contain at least 16 characters")
    if len(clear) > MAX_SNAPSHOT:
        raise SyncError("Note and attachments exceed sync limit")
    u = valid_uuid(note_uuid)
    salt = hashlib.sha256(("np-notes-sync-v1:" + repository.lower()).encode()).digest()[:16]
    key = hashlib.scrypt(password.encode(), salt=salt, n=2**15, r=8, p=1, dklen=32, maxmem=128 * 1024 * 1024)
    nonce = os.urandom(12)
    aad = ("np-notes-v1:" + u).encode()
    return b"NPNS1" + nonce + AESGCM(key).encrypt(nonce, clear, aad)


def decrypt_snapshot(blob: bytes, password: str, repository: str, note_uuid: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if len(blob) < 33 or not blob.startswith(b"NPNS1") or len(blob) > MAX_SNAPSHOT + 100:
        raise SyncError("Invalid encrypted sync snapshot")
    u = valid_uuid(note_uuid)
    salt = hashlib.sha256(("np-notes-sync-v1:" + repository.lower()).encode()).digest()[:16]
    key = hashlib.scrypt(password.encode(), salt=salt, n=2**15, r=8, p=1, dklen=32, maxmem=128 * 1024 * 1024)
    try:
        return AESGCM(key).decrypt(blob[5:17], blob[17:], ("np-notes-v1:" + u).encode())
    except Exception as exc:
        raise SyncError("Wrong sync passphrase or damaged encrypted content") from exc


def snapshot_from_folder(folder: Path) -> tuple[str, bytes, str]:
    """Capture note.json and attachments only. Excludes caches, backups and secrets."""
    if folder.is_symlink() or not folder.is_dir():
        raise SyncError("Unsafe note folder")
    source = folder / "note.json"
    if source.is_symlink() or not source.is_file():
        raise SyncError("Missing or unsafe note.json")
    original = json.loads(source.read_text(encoding="utf-8"))
    note_uuid = valid_uuid(original["uuid"])
    clean = dict(original)
    clean.pop("password_manager", None)
    clean.pop("password_manager_visible", None)
    # Do not include backup content or password manager data in transport.
    raw = json_bytes(clean)
    files = []
    for path in sorted(folder.iterdir()):
        if path.name == "note.json" or IGNORED.match(path.name):
            continue
        if path.is_symlink() or not path.is_file():
            raise SyncError("Unexpected folder or link in note attachments")
        if len(files) >= MAX_NOTE_FILES:
            raise SyncError("Too many note attachments")
        files.append(path)
    output = io.BytesIO()
    def add(archive, name: str, value: bytes):
        entry = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
        entry.compress_type = zipfile.ZIP_DEFLATED
        entry.external_attr = 0o600 << 16
        archive.writestr(entry, value, compress_type=zipfile.ZIP_DEFLATED, compresslevel=5)
    with zipfile.ZipFile(output, "w") as archive:
        add(archive, "note.json", raw)
        for path in files:
            if path.stat().st_size > MAX_SNAPSHOT:
                raise SyncError("Attachment too large for GitHub sync")
            add(archive, "attachments/" + path.name, path.read_bytes())
    data = output.getvalue()
    if len(data) > MAX_SNAPSHOT:
        raise SyncError("Snapshot is larger than the 20 MiB limit")
    return note_uuid, data, hashlib.sha256(data).hexdigest()


def unpack_snapshot(payload: bytes, note_uuid: str) -> tuple[dict, dict[str, bytes]]:
    """Validate entire remote archive before allowing any local mutations."""
    u = valid_uuid(note_uuid)
    if len(payload) > MAX_SNAPSHOT:
        raise SyncError("Oversized remote snapshot")
    files = {}
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = archive.infolist()
        if len(members) > MAX_NOTE_FILES + 1:
            raise SyncError("Too many remote entries")
        for item in members:
            name = item.filename
            if name != "note.json" and not name.startswith("attachments/"):
                raise SyncError("Unsafe remote archive path")
            suffix = name[12:] if name.startswith("attachments/") else ""
            if name != "note.json" and (
                not suffix or suffix in (".", "..") or "/" in suffix or "\\" in suffix or
                ":" in suffix or suffix.startswith(".np-sync-") or IGNORED.match(suffix)
            ):
                raise SyncError("Unsafe remote attachment name")
            if name in files or item.is_dir() or item.file_size > MAX_SNAPSHOT:
                raise SyncError("Duplicate, directory or oversized archive entry")
            files[name] = archive.read(item)
    if "note.json" not in files or sum(len(v) for v in files.values()) > MAX_SNAPSHOT:
        raise SyncError("Incomplete or oversized note")
    note = json.loads(files.pop("note.json").decode("utf-8"))
    if not isinstance(note, dict) or note.get("uuid") != u or not isinstance(note.get("content"), str):
        raise SyncError("Mismatched or invalid remote note")
    if "password_manager" in note or "password_manager_visible" in note:
        raise SyncError("Remote snapshot contains excluded password-manager field")
    return note, {name[12:]: value for name, value in files.items()}


class GitHubStore:
    """Minimal GitHub Contents API adapter; injectable request for offline tests."""

    def __init__(self, repo: str, token: str, request=None):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise SyncError("Invalid owner/repository")
        if not token:
            raise SyncError("GitHub token is not configured")
        self.repo = repo
        self.token = token
        self.request = request or urllib.request.urlopen
        self.base = "https://api.github.com/repos/" + repo

    def api(self, method: str, path: str, body: dict | None = None):
        encoded = json_bytes(body) if body is not None else None
        req = urllib.request.Request(
            self.base + path, data=encoded, method=method,
            headers={"Authorization": "Bearer " + self.token,
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     "Content-Type": "application/json",
                     "User-Agent": "NP-Notes-EncryptedSync/1"},
        )
        try:
            with self.request(req, timeout=12) as response:
                return json.loads(response.read(MAX_SNAPSHOT * 2).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code in (409, 412, 422):
                raise Conflict("Remote state changed; retry without overwriting") from None
            raise SyncError("GitHub HTTP error " + str(exc.code)) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            raise Offline("GitHub unavailable; local notes remain available") from exc

    def check_private(self):
        info = self.api("GET", "")
        if not isinstance(info, dict) or info.get("private") is not True:
            raise SyncError("Refusing to sync to a non-private or inaccessible repository")

    def list_notes(self) -> dict[str, str]:
        entries = self.api("GET", "/contents/notes")
        if entries is None:
            return {}
        if not isinstance(entries, list) or len(entries) >= MAX_REMOTE_FILES:
            raise SyncError("Remote note listing is too large")
        result = {}
        for item in entries:
            if not isinstance(item, dict) or item.get("type") != "file":
                raise SyncError("Unexpected remote repository contents")
            filename = item.get("name", "")
            if not filename.endswith(".npn"):
                continue
            name = valid_uuid(filename[:-4])
            if not re.fullmatch(r"[0-9a-f]{40}", item.get("sha", "")):
                raise SyncError("Invalid remote blob SHA")
            result[name] = item["sha"]
        return result

    def download(self, blob_sha: str) -> bytes:
        response = self.api("GET", "/git/blobs/" + blob_sha)
        if not isinstance(response, dict) or response.get("encoding") != "base64":
            raise SyncError("GitHub returned unsupported binary encoding")
        raw = base64.b64decode(response["content"], validate=False)
        if len(raw) > MAX_SNAPSHOT + 100:
            raise SyncError("Remote blob too large")
        return raw

    def upload(self, note_uuid: str, encrypted: bytes, sha: str | None) -> str:
        u = valid_uuid(note_uuid)
        body = {"message": "sync: encrypted note " + u,
                "content": base64.b64encode(encrypted).decode("ascii")}
        if sha:
            body["sha"] = sha
        result = self.api("PUT", "/contents/notes/" + u + ".npn", body)
        if not isinstance(result, dict) or not isinstance(result.get("content"), dict):
            raise SyncError("No confirmation from GitHub")
        new_sha = result["content"].get("sha")
        if not isinstance(new_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", new_sha):
            raise SyncError("Invalid GitHub upload confirmation")
        return new_sha


@dataclass
class SyncResult:
    status: str
    uploaded: int = 0
    downloaded: int = 0
    conflicts: int = 0


class SyncEngine:
    def __init__(self, notes: Path, state_dir: Path, store: GitHubStore, passphrase: str):
        self.notes = Path(notes)
        self.state_dir = Path(state_dir)
        self.store = store
        self.passphrase = passphrase
        self.state_file = self.state_dir / "state.json"
        self.conflict_dir = self.state_dir / "conflicts"

    def _state(self) -> dict:
        if not self.state_file.is_file():
            return {}
        info = json.loads(self.state_file.read_text(encoding="utf-8"))
        if info.get("version") != 1 or info.get("repository") != self.store.repo:
            raise SyncError("Sync state belongs to another repository")
        return info.get("notes", {})

    def _save_state(self, notes: dict):
        atomic_bytes(self.state_file, json_bytes(
            {"version": 1, "repository": self.store.repo, "notes": notes}))

    def _local(self) -> dict:
        result = {}
        if not self.notes.exists():
            return result
        for folder in self.notes.iterdir():
            if folder.name == "Trash" or not folder.is_dir():
                continue
            if folder.is_symlink():
                raise SyncError("Link in local notes root")
            file = folder / "note.json"
            if file.is_file():
                u, data, digest = snapshot_from_folder(folder)
                if u in result:
                    raise SyncError("Duplicate note UUID in local files")
                result[u] = (folder, data, digest)
        return result

    def _conflict(self, u: str, remote: bytes):
        self.conflict_dir.mkdir(parents=True, exist_ok=True)
        target = self.conflict_dir / (u + "-" + hashlib.sha256(remote).hexdigest()[:16] + ".npn")
        if not target.exists():
            atomic_bytes(target, remote)

    def _import(self, u: str, clear: bytes, folder: Path | None, expected_digest: str | None):
        note, attachments = unpack_snapshot(clear, u)
        if folder is None:
            folder = self.notes / ("Sync_" + u)
            if folder.exists():
                raise Conflict("Import destination already exists")
        else:
            _, _, actual = snapshot_from_folder(folder)
            if actual != expected_digest:
                raise Conflict("Local note changed during download")
        if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
            raise SyncError("Unsafe local import destination")
        # Check attachment collisions and reject untrusted paths before changes.
        for name, content in attachments.items():
            target = folder / name
            if target.is_symlink() or (target.exists() and target.read_bytes() != content):
                raise Conflict("Attachment changed locally")
        folder.mkdir(parents=True, exist_ok=True)
        if (folder / "note.json").exists():
            existing = json.loads((folder / "note.json").read_text(encoding="utf-8"))
            # Local-only password_manager fields must never be erased on remote import.
            for key in ("password_manager", "password_manager_visible"):
                if key in existing:
                    note[key] = existing[key]
            shutil.copy2(folder / "note.json", folder / ("note_backup_" + str(time.time_ns()) + ".json"))
        for name, content in attachments.items():
            target = folder / name
            if not target.exists():
                with target.open("xb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
        atomic_bytes(folder / "note.json", json_bytes(note))

    def run(self, *, protected_uuid: str | None = None) -> SyncResult:
        """Fail closed on network errors. Never remove any local note or attachment."""
        try:
            self.store.check_private()
            remote = self.store.list_notes()
        except Offline:
            return SyncResult("offline")
        previous = self._state()
        local = self._local()
        uploaded = downloaded = conflicts = 0
        ids = sorted(set(local) | set(remote))
        for u in ids:
            old = previous.get(u, {})
            entry = local.get(u)
            sha = remote.get(u)
            if sha is None and entry is None:
                continue
            if sha is None:
                # Remote deletion is never propagated; existing tracked items wait.
                if old.get("sha"):
                    continue
                try:
                    new_sha = self.store.upload(u, encrypt_snapshot(entry[1], self.passphrase, self.store.repo, u), None)
                except Offline:
                    return SyncResult("offline", uploaded, downloaded, conflicts)
                except Conflict:
                    conflicts += 1
                    continue
                previous[u] = {"sha": new_sha, "digest": entry[2]}
                self._save_state(previous)
                uploaded += 1
                continue
            if entry is None and old:
                # Missing local file could mean deletion; never silently resurrect.
                continue
            remote_changed = not old or old.get("sha") != sha
            local_changed = entry is not None and (not old or old.get("digest") != entry[2])
            if not remote_changed and not local_changed:
                continue
            if remote_changed:
                try:
                    encrypted = self.store.download(sha)
                except Offline:
                    return SyncResult("offline", uploaded, downloaded, conflicts)
                clear = decrypt_snapshot(encrypted, self.passphrase, self.store.repo, u)
                unpack_snapshot(clear, u)  # validate before conflict decisions
                # First encounter of independently edited files must not overwrite.
                if local_changed and entry is not None:
                    if clear != entry[1]:
                        self._conflict(u, encrypted)
                        conflicts += 1
                        continue
                elif protected_uuid == u:
                    # UI currently has this note selected; defer to later cycle.
                    continue
                else:
                    try:
                        self._import(u, clear, entry[0] if entry else None, entry[2] if entry else None)
                    except Conflict:
                        self._conflict(u, encrypted)
                        conflicts += 1
                        continue
                    downloaded += 1
                # Current local digest might differ due to local-only private fields.
                refreshed = self._local().get(u)
                if refreshed is not None:
                    previous[u] = {"sha": sha, "digest": refreshed[2]}
                    self._save_state(previous)
                continue
            if local_changed and entry:
                try:
                    new_sha = self.store.upload(u, encrypt_snapshot(entry[1], self.passphrase, self.store.repo, u), sha)
                except Offline:
                    return SyncResult("offline", uploaded, downloaded, conflicts)
                except Conflict:
                    conflicts += 1
                    continue
                previous[u] = {"sha": new_sha, "digest": entry[2]}
                self._save_state(previous)
                uploaded += 1
        return SyncResult("conflicts" if conflicts else "ok", uploaded, downloaded, conflicts)


def enabled_config(data_dir: Path) -> dict | None:
    """Disabled unless user explicitly creates NoteSync/config.json."""
    path = Path(data_dir) / "NoteSync" / "config.json"
    if not path.is_file():
        return None
    cfg = json.loads(path.read_text(encoding="utf-8"))
    if cfg.get("enabled") is not True or cfg.get("interval_minutes") != 5:
        return None
    repo = cfg.get("repository", "")
    if not isinstance(repo, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise SyncError("Invalid GitHub sync repository configuration")
    return cfg


def run_configured_sync(data_dir: Path, *, protected_uuid: str | None = None) -> SyncResult:
    cfg = enabled_config(data_dir)
    if cfg is None:
        return SyncResult("disabled")
    token = os.environ.get("NP_NOTES_GITHUB_TOKEN", "")
    secret = os.environ.get("NP_NOTES_SYNC_PASSPHRASE", "")
    if not token or len(secret) < 16:
        from .sync_secrets import load_credentials
        creds = load_credentials(Path(data_dir) / "NoteSync")
        if creds:
            token, secret = creds
    if not token or len(secret) < 16:
        return SyncResult("needs_credentials")
    store = GitHubStore(cfg["repository"], token)
    return SyncEngine(Path(data_dir) / "Notes", Path(data_dir) / "NoteSync", store, secret).run(
        protected_uuid=protected_uuid
    )
