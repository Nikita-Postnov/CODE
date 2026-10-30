from __future__ import annotations

from pathlib import Path
from typing import Any

PORTABLE_ROOT = "$LAUNCHER"
PORTABLE_PREFIX = PORTABLE_ROOT + "/"
PATH_FIELDS = (
    "python_executable",
    "scripts_folder",
    "last_script_path",
    "last_workdir",
)
LIST_PATH_FIELDS = ("autostart_scripts", "favorites")
KEY_PATH_FIELDS = (
    "per_script_workdir",
    "per_script_args",
    "per_script_shortcut",
    "per_script_icon",
)
VALUE_PATH_FIELDS = ("per_script_workdir", "per_script_shortcut", "per_script_icon")
RECENT_PATH_FIELDS = ("script", "workdir", "py")


def encode_path(value: str, root: Path) -> str:
    value = str(value or "")
    if not value or value == PORTABLE_ROOT or value.startswith(PORTABLE_PREFIX):
        return value
    path = Path(value).expanduser()
    if not path.is_absolute():
        return value
    try:
        relative = path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, ValueError):
        return value
    return PORTABLE_ROOT if str(relative) == "." else PORTABLE_PREFIX + relative.as_posix()


def decode_path(value: str, root: Path) -> str:
    value = str(value or "")
    root = Path(root).absolute()
    if value == PORTABLE_ROOT:
        return str(root)
    if value.startswith(PORTABLE_PREFIX):
        relative = Path(value[len(PORTABLE_PREFIX):])
        if relative.is_absolute() or ".." in relative.parts:
            return value
        return str(root / relative)
    if not value:
        return value
    path = Path(value).expanduser()
    if not path.is_absolute():
        return value
    parts = path.parts
    for index in range(len(parts) - 1, -1, -1):
        if parts[index].casefold() != root.name.casefold():
            continue
        candidate = root.joinpath(*parts[index + 1:])
        if candidate.exists():
            return str(candidate)
    return value



def locate_portable_python(root: Path, configured: str = "") -> str:
    configured = str(configured or "").strip().strip('"')
    if configured and Path(configured).is_file():
        return configured
    root = Path(root)
    for suffix in (
        ("Runtime", "python.exe"),
        ("Runtime", "pythonw.exe"),
        ("Runtime", "Python", "python.exe"),
        ("Runtime", "Python", "pythonw.exe"),
        ("Runtime", "python", "python.exe"),
        ("Runtime", "python", "pythonw.exe"),
        ("python.exe",),
        ("pythonw.exe",),
    ):
        candidate = root.joinpath(*suffix)
        if candidate.is_file():
            return str(candidate)
    return configured



def convert_settings_paths(data: dict[str, Any], root: Path, *, encode: bool) -> dict[str, Any]:
    convert = encode_path if encode else decode_path
    result = dict(data)
    for field in PATH_FIELDS:
        if isinstance(result.get(field), str):
            result[field] = convert(result[field], root)
    for field in LIST_PATH_FIELDS:
        values = result.get(field)
        if isinstance(values, list):
            result[field] = [
                convert(value, root) if isinstance(value, str) else value
                for value in values
            ]
    for field in KEY_PATH_FIELDS:
        mapping = result.get(field)
        if not isinstance(mapping, dict):
            continue
        result[field] = {
            convert(key, root) if isinstance(key, str) else key:
            convert(value, root) if field in VALUE_PATH_FIELDS and isinstance(value, str) else value
            for key, value in mapping.items()
        }
    cards = result.get("home_cards")
    if isinstance(cards, list):
        result["home_cards"] = [
            {
                **card,
                "path": convert(card["path"], root),
            }
            if isinstance(card, dict) and isinstance(card.get("path"), str)
            else card
            for card in cards
        ]
    entries = result.get("recent_runs")
    if isinstance(entries, list):
        result["recent_runs"] = [
            {
                key: convert(value, root)
                if key in RECENT_PATH_FIELDS and isinstance(value, str) else value
                for key, value in entry.items()
            }
            if isinstance(entry, dict) else entry
            for entry in entries
        ]
    return result
