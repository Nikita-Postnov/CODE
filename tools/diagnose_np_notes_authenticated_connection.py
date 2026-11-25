"""Read-only authenticated GitHub probe for NP Notes.

Loads only locally protected DPAPI configuration (CurrentUser), checks
private repository metadata through the SAME transport as synchronization,
and never opens notes, snapshots, uploads, or exposes any secrets.
"""
from __future__ import annotations
import argparse
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Other_dev"))

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--launcher-root", type=Path, required=True)
    options = parser.parse_args()
    from noteapp.sync_credentials import load_dpapi_credentials
    from noteapp.encrypted_sync import GitHubTransport

    print("NOTE_CONTENT_ACCESSED=FALSE")
    print("UPLOAD_ATTEMPTED=FALSE")
    print("TOKEN_PRINTED=FALSE")

    directory = options.launcher_root / "Data" / "NPNotesSync"
    try:
        config = load_dpapi_credentials(directory)
    except Exception as error:
        print("CREDENTIALS=UNAVAILABLE")
        print("CREDENTIAL_ERROR_CLASS=" + type(error).__name__)
        return 2
    if not config:
        print("CREDENTIALS=MISSING")
        return 2

    print("CREDENTIALS=DPAPI_OK")
    transport = GitHubTransport(
        config["owner"], config["repository"], config["token"],
        branch=config.get("branch", "main"),
    )
    try:
        transport.assert_private()
    except urllib.error.HTTPError as error:
        print("AUTHENTICATED_GITHUB=HTTP_" + str(error.code))
        if error.code == 401:
            print("DIAGNOSIS=TOKEN_REJECTED_OR_EXPIRED")
        elif error.code == 403:
            print("DIAGNOSIS=FORBIDDEN_OR_RATE_LIMIT_OR_NETWORK_POLICY")
        elif error.code == 404:
            print("DIAGNOSIS=REPOSITORY_NOT_FOUND_OR_TOKEN_SCOPE")
        else:
            print("DIAGNOSIS=GITHUB_HTTP_ERROR")
        return 3
    except Exception as error:
        print("AUTHENTICATED_GITHUB=FAILED")
        print("ERROR_CLASS=" + type(error).__name__)
        return 4

    print("AUTHENTICATED_GITHUB=PASS")
    print("REPOSITORY_PRIVATE=TRUE")
    print("READY_FOR_ENCRYPTED_SYNC=TRUE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
