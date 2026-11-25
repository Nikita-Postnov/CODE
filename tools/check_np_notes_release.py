"""Read-only version check for the complete NP Notes package.

The manifest pins an immutable GitHub commit and Git blob hashes for
notes_app.py AND every tracked noteapp file. Does not inspect Data or
credentials; does not modify app files. Suitable for Choice version status.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path, PurePosixPath

MANIFEST_URL = (
    "https://raw.githubusercontent.com/Nikita-Postnov/CODE/main/"
    "tools/np_notes_release.json"
)


class ReleaseManifestError(ValueError):
    pass


def load_manifest(source: str | Path | None = None):
    if source is None:
        request = urllib.request.Request(
            MANIFEST_URL, headers={"User-Agent": "NPNotes-ReleaseCheck/1.0"}
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.load(response)
    else:
        data = json.loads(Path(source).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise ReleaseManifestError("Unsupported release manifest")
    if (data.get("source_repository") != "Nikita-Postnov/CODE"
            or data.get("source_directory") != "Other_dev"
            or data.get("install_scope") != ["notes_app.py", "noteapp"]):
        raise ReleaseManifestError("Unexpected release target")
    if not re.fullmatch(r"[0-9a-f]{40}", str(data.get("source_commit", ""))):
        raise ReleaseManifestError("Invalid source commit")
    entries = data.get("files")
    if not isinstance(entries, list) or len(entries) < 2:
        raise ReleaseManifestError("Empty release manifest")
    known = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ReleaseManifestError("Malformed manifest entry")
        path, digest = entry.get("path"), entry.get("git_blob_sha")
        if not isinstance(path, str) or not isinstance(digest, str):
            raise ReleaseManifestError("Invalid manifest types")
        parts = PurePosixPath(path).parts
        if (not parts or any(part in ("", ".", "..") for part in parts)
                or "\\" in path or ":" in path or path.startswith("/")
                or (path != "notes_app.py" and
                    (parts[0] != "noteapp" or len(parts) < 2))
                or not re.fullmatch("[0-9a-f]{40}", digest)):
            raise ReleaseManifestError("Invalid release path or digest")
        unique_key = path.casefold()
        if unique_key in known:
            raise ReleaseManifestError("Duplicate release path")
        known.add(unique_key)
    if "notes_app.py" not in known or "noteapp/__init__.py" not in known:
        raise ReleaseManifestError("Missing NP Notes package entrypoints")
    return data


def local_blob_sha(path: Path):
    if not path.is_file() or path.is_symlink():
        return None
    # Git blob hashes are computed on file bytes, not on the Windows
    # filesystem timestamps, Git checkout metadata or Python caches.
    file_size = path.stat().st_size
    digest = hashlib.sha1()
    digest.update(f"blob {file_size}\0".encode("ascii"))
    with path.open("rb") as source:
        while True:
            buffer = source.read(1024 * 1024)
            if not buffer:
                break
            digest.update(buffer)
    return digest.hexdigest()


def check_installation(root: Path, manifest: dict):
    root = Path(root)
    mismatch = 0
    for entry in manifest["files"]:
        path = root.joinpath(*PurePosixPath(entry["path"]).parts)
        if local_blob_sha(path) != entry["git_blob_sha"]:
            mismatch += 1
    return {
        "status": "UP_TO_DATE" if mismatch == 0 else "UPDATE_AVAILABLE",
        "checked": len(manifest["files"]),
        "mismatched": mismatch,
        "commit": manifest["source_commit"],
    }


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--launcher-root", required=True, type=Path)
    p.add_argument("--manifest", type=Path, help="Local manifest (tests only)")
    args = p.parse_args(argv)
    print("MODE=READ_ONLY")
    print("NP_NOTES_DATA_ACCESSED=FALSE")
    print("SECRETS_ACCESSED=FALSE")
    try:
        release = load_manifest(args.manifest)
        outcome = check_installation(args.launcher_root, release)
    except Exception as exc:
        print("NP_NOTES_VERSION=UNKNOWN")
        print("CHECK_ERROR_CLASS=" + type(exc).__name__)
        return 2
    print("NP_NOTES_VERSION=" + outcome["status"])
    print("RELEASE_COMMIT=" + outcome["commit"])
    print("RELEASE_FILES_CHECKED=" + str(outcome["checked"]))
    print("RELEASE_FILES_DIFFERENT=" + str(outcome["mismatched"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
