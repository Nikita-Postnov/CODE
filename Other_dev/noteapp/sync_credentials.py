"""Load GitHub sync credentials from Windows DPAPI, never plaintext files.

Optional config resides only in an explicit directory, is decrypted for the
current Windows user account and never printed or uploaded.
"""
from __future__ import annotations
import json
from pathlib import Path

CONFIG_FILE = "credentials.dpapi"


def load_dpapi_credentials(state_directory: Path):
    path = Path(state_directory) / CONFIG_FILE
    if not path.is_file():
        return None
    from .recovery import _crypt, DraftUnavailable
    raw = _crypt(path.read_bytes(), decrypt=True)
    config = json.loads(raw.decode("utf-8"))
    required = ("owner", "repository", "token", "passphrase")
    if (not isinstance(config, dict)
            or not all(isinstance(config.get(key), str) and config[key]
                       for key in required)
            or len(config["passphrase"]) < 16):
        raise ValueError("Invalid encrypted NP Notes sync configuration")
    return config
