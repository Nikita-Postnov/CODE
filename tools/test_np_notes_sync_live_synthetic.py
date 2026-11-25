"""Live synthetic-only encrypted GitHub round-trip test.

This tool does not inspect, enumerate, load, save, alter, or upload any user's
notes. Reads only the Windows DPAPI sync-credential file whose path is given.
Creates one random encrypted dummy record in the dedicated private repository,
validates it, and deletes that dummy file with a SHA precondition.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

PACKAGE_PARENT = Path(__file__).resolve().parents[1] / "Other_dev"
sys.path.insert(0, str(PACKAGE_PARENT))

from noteapp.encrypted_sync import GitHubTransport, seal, unseal
from noteapp.sync_credentials import load_dpapi_credentials


def delete_dummy(transport: GitHubTransport, note_id: str, sha: str):
    """Delete only the exact randomly generated test object and its SHA."""
    payload = json.dumps({
        "message": "Remove synthetic NP Notes encryption test",
        "sha": sha,
        "branch": transport.branch,
    }).encode("utf-8")
    req = urllib.request.Request(
        transport.url + "/contents/encrypted/" + note_id + ".json",
        data=payload,
        method="DELETE",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + transport.token,
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    with transport.opener(req, timeout=20) as response:
        return response.status in (200, 201)


def main():
    parser = argparse.ArgumentParser(description="NP Notes synthetic-only cloud test")
    parser.add_argument("--credential-directory", required=True, type=Path)
    args = parser.parse_args()
    creds = load_dpapi_credentials(args.credential_directory)
    if not creds:
        raise RuntimeError("Encrypted DPAPI credentials missing")
    transport = GitHubTransport(
        creds["owner"], creds["repository"], creds["token"],
        branch=creds.get("branch", "main"),
    )
    transport.assert_private()
    print("PRIVATE_REPOSITORY=PASS")
    note_id = str(uuid4())
    dummy = json.dumps({
        "version": 1,
        "note": {
            "uuid": note_id, "title": "SYNTHETIC TEST ONLY",
            "content": "Fake content; no real notes read",
            "timestamp": "2026-11-25T09:00:00",
        },
        "attachments": {"fake.txt": base64.b64encode(b"dummy attachment").decode()},
    }).encode()
    sealed = seal(dummy, creds["passphrase"], note_id)
    if b"Fake content" in sealed or b"dummy attachment" in sealed:
        raise RuntimeError("Encryption must hide synthetic plaintext")
    remote, sha = transport.read(note_id)
    if remote is not None:
        raise RuntimeError("Random test UUID unexpectedly occupied")
    created_sha = None
    try:
        created_sha = transport.write(note_id, sealed, expected_sha=None)
        received, downloaded_sha = transport.read(note_id)
        if downloaded_sha != created_sha or unseal(received, creds["passphrase"], note_id) != dummy:
            raise RuntimeError("Encrypted GitHub round trip mismatch")
        print("ENCRYPTED_SYNTHETIC_ROUNDTRIP=PASS")
        print("FAKE_ATTACHMENT=PASS")
    finally:
        if created_sha:
            try:
                if delete_dummy(transport, note_id, created_sha):
                    print("SYNTHETIC_TEST_FILE_CLEANED=TRUE")
                else:
                    print("SYNTHETIC_TEST_FILE_CLEANED=FALSE")
            except Exception:
                print("SYNTHETIC_TEST_FILE_CLEANED=FALSE")
                print("Synthetic encrypted test object may remain. No actual note data was uploaded.")
    print("REAL_NOTES_ACCESSED=FALSE")


if __name__ == "__main__":
    main()
