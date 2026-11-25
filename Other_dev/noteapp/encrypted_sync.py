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

    def read(self, note_id: str):
        path = "encrypted/" + _note_id(note_id) + ".json"
        try:
            record = self._call(path)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None, None
            raise
        if record.get("type") != "file" or not isinstance(record.get("sha"), str):
            raise SyncSecurityError("Unexpected remote file")
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
