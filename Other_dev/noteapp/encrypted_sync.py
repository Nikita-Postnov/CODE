"""Opt-in encrypted GitHub transport for synthetic NP Notes snapshots.

No credentials, notes or network activity at import time. Existing remote files
are never overwritten without the exact previously observed GitHub blob SHA.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from uuid import UUID

ITERATIONS = 600_000
MAX_BYTES = 25 * 1024 * 1024


class SyncSecurityError(RuntimeError):
    pass


class SyncConflict(RuntimeError):
    pass


def _note_id(value):
    try:
        normalized = str(UUID(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise SyncSecurityError("Invalid note ID") from exc
    if normalized != value:
        raise SyncSecurityError("Noncanonical note ID")
    return value


def _aes():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise SyncSecurityError("cryptography dependency required") from exc
    return AESGCM


def seal(data: bytes, password: str, note_id: str) -> bytes:
    _note_id(note_id)
    if not isinstance(password, str) or len(password) < 16:
        raise SyncSecurityError("Sync passphrase must be at least 16 characters")
    if not isinstance(data, bytes) or len(data) > MAX_BYTES:
        raise SyncSecurityError("Invalid snapshot size")
    salt, nonce = os.urandom(16), os.urandom(12)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS, 32)
    cipher = _aes()(key).encrypt(nonce, data, ("NPNotes-v1:" + note_id).encode())
    return json.dumps({"v": 1, "s": base64.b64encode(salt).decode(),
                       "n": base64.b64encode(nonce).decode(),
                       "c": base64.b64encode(cipher).decode()},
                      separators=(",", ":")).encode()


def unseal(envelope: bytes, password: str, note_id: str) -> bytes:
    _note_id(note_id)
    if not isinstance(envelope, bytes) or len(envelope) > MAX_BYTES * 2:
        raise SyncSecurityError("Encrypted payload too large")
    if not isinstance(password, str) or not password:
        raise SyncSecurityError("Missing passphrase")
    try:
        record = json.loads(envelope)
        if record["v"] != 1:
            raise ValueError("Unsupported envelope")
        salt = base64.b64decode(record["s"], validate=True)
        nonce = base64.b64decode(record["n"], validate=True)
        cipher = base64.b64decode(record["c"], validate=True)
        if len(salt) != 16 or len(nonce) != 12 or len(cipher) > MAX_BYTES + 16:
            raise ValueError("Malformed encryption payload")
        key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS, 32)
        return _aes()(key).decrypt(nonce, cipher, ("NPNotes-v1:" + note_id).encode())
    except Exception as exc:
        raise SyncSecurityError("Decryption or authentication failed") from exc


class GitHubTransport:
    """GitHub Contents API with optimistic concurrency (sha precondition).

    A token scoped only to a dedicated private notes repository is required.
    expected_sha=None allows creation only, not blind remote replacement.
    """
    def __init__(self, owner: str, repo: str, token: str, branch="main", opener=None):
        for name in (owner, repo, branch):
            if not isinstance(name, str) or not re.fullmatch(r"[\w.-]{1,100}", name):
                raise SyncSecurityError("Invalid GitHub repository reference")
        if not token or not isinstance(token, str):
            raise SyncSecurityError("Missing GitHub token")
        self.url = "https://api.github.com/repos/" + owner + "/" + repo
        self.branch = branch
        self.token = token
        self.opener = opener or urllib.request.urlopen

    def assert_private(self):
        """Fail closed: never publish encrypted note metadata to a public repo."""
        request = urllib.request.Request(
            self.url,
            headers={"Accept": "application/vnd.github+json",
                     "Authorization": "Bearer " + self.token,
                     "X-GitHub-Api-Version": "2022-11-28"},
        )
        with self.opener(request, timeout=15) as response:
            metadata = json.load(response)
        if metadata.get("private") is not True:
            raise SyncSecurityError("Refusing NP Notes sync to a non-private repository")
        return True

    def _call(self, path: str, method="GET", document=None):
        headers = {"Accept": "application/vnd.github+json",
                   "Authorization": "Bearer " + self.token,
                   "X-GitHub-Api-Version": "2022-11-28"}
        data = None
        if document is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(document).encode()
        url = self.url + "/contents/" + path
        if method == "GET":
            url += "?ref=" + urllib.parse.quote(self.branch, safe="")
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        with self.opener(request, timeout=15) as response:
            return json.load(response)

    def list_note_ids(self):
        """List encrypted note UUIDs only; ignore unrelated repository files."""
        try:
            entries = self._call("encrypted")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return []
            raise
        if not isinstance(entries, list):
            raise SyncSecurityError("Encrypted directory is not a file listing")
        note_ids = []
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("type") != "file":
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not name.endswith(".json"):
                continue
            candidate = name[:-5]
            try:
                _note_id(candidate)
            except SyncSecurityError:
                continue
            note_ids.append(candidate)
        return sorted(set(note_ids))

    def read(self, note_id: str):
        return self._read_remote_file("encrypted", note_id)

    def read_tombstone(self, note_id: str):
        """Read a durable deletion marker; it contains encrypted metadata only."""
        return self._read_remote_file("tombstones", note_id)

    def list_tombstone_ids(self):
        """List UUIDs with remote deletion markers (never return note content)."""
        try:
            entries = self._call("tombstones")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return []
            raise
        if not isinstance(entries, list):
            raise SyncSecurityError("Tombstone directory is not a file listing")
        ids = []
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("type") != "file":
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not name.endswith(".json"):
                continue
            candidate = name[:-5]
            try:
                _note_id(candidate)
            except SyncSecurityError:
                continue
            ids.append(candidate)
        return sorted(set(ids))

    def _read_remote_file(self, directory: str, note_id: str):
        if directory not in ("encrypted", "tombstones"):
            raise SyncSecurityError("Unsupported remote directory")
        path = directory + "/" + _note_id(note_id) + ".json"
        try:
            record = self._call(path)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None, None
            raise
        if record.get("type") != "file" or not isinstance(record.get("sha"), str):
            raise SyncSecurityError("Unexpected remote file")
        if record.get("encoding") == "none":
            # GitHub Contents API omits inline content for files >1 MiB.
            blob_sha = record["sha"]
            if not re.fullmatch(r"[a-f0-9]{40}", blob_sha):
                raise SyncSecurityError("Invalid remote Git blob SHA")
            request = urllib.request.Request(
                self.url + "/git/blobs/" + blob_sha,
                headers={"Accept": "application/vnd.github+json",
                         "Authorization": "Bearer " + self.token,
                         "X-GitHub-Api-Version": "2022-11-28"},
            )
            with self.opener(request, timeout=30) as response:
                blob = json.load(response)
            if blob.get("encoding") != "base64":
                raise SyncSecurityError("Unsupported large file encoding")
            content = base64.b64decode(blob["content"], validate=False)
        else:
            if record.get("encoding") != "base64":
                raise SyncSecurityError("Unsupported remote content encoding")
            content = base64.b64decode(record["content"], validate=False)
        if len(content) > MAX_BYTES * 2:
            raise SyncSecurityError("Remote file too large")
        return content, record["sha"]

    def write(self, note_id: str, sealed: bytes, expected_sha=None):
        if not isinstance(sealed, bytes) or len(sealed) > MAX_BYTES * 2:
            raise SyncSecurityError("Invalid encrypted content")
        path = "encrypted/" + _note_id(note_id) + ".json"
        record = {"message": "Sync encrypted NP Notes snapshot",
                  "branch": self.branch, "content": base64.b64encode(sealed).decode()}
        if expected_sha is not None:
            if not isinstance(expected_sha, str) or not re.fullmatch(r"[a-f0-9]{40}", expected_sha):
                raise SyncSecurityError("Invalid expected GitHub SHA")
            record["sha"] = expected_sha
        try:
            result = self._call(path, "PUT", record)
        except urllib.error.HTTPError as exc:
            if exc.code in (409, 412, 422):
                raise SyncConflict("Remote revision changed; retain local revision") from exc
            raise
        return result["content"]["sha"]

    def write_tombstone(self, note_id: str, sealed: bytes):
        """Create-only encrypted deletion marker; never overwrite an existing marker."""
        if not isinstance(sealed, bytes) or len(sealed) > MAX_BYTES * 2:
            raise SyncSecurityError("Invalid encrypted tombstone")
        record = {
            "message": "Record permanent NP Notes deletion",
            "branch": self.branch,
            "content": base64.b64encode(sealed).decode(),
        }
        try:
            result = self._call("tombstones/" + _note_id(note_id) + ".json", "PUT", record)
        except urllib.error.HTTPError as exc:
            if exc.code in (409, 412, 422):
                raise SyncConflict("Concurrent tombstone update") from exc
            raise
        return result["content"]["sha"]

    def delete_note(self, note_id: str, expected_sha: str):
        """Remove only the exact encrypted GitHub blob observed by caller.

        Deletion markers are separate and must be committed before this call.
        Git retains historical commits, even after deleting a file from HEAD.
        """
        if not isinstance(expected_sha, str) or not re.fullmatch(r"[a-f0-9]{40}", expected_sha):
            raise SyncSecurityError("Expected blob SHA is required for deletion")
        record = {
            "message": "Permanently delete encrypted NP Notes snapshot",
            "branch": self.branch,
            "sha": expected_sha,
        }
        try:
            self._call("encrypted/" + _note_id(note_id) + ".json", "DELETE", record)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return True
            if exc.code in (409, 412, 422):
                raise SyncConflict("Remote note changed before deletion") from exc
            raise
        return True
