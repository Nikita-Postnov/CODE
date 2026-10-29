"""Пути, каталоги и низкоуровневые константы приложения.

Модуль не зависит от Qt и от остального пакета — его можно импортировать
откуда угодно, не рискуя циклами. Все остальные модули берут пути отсюда,
а не переопределяют их у себя.
"""

import os
import sys
from pathlib import Path


def _is_launcher_dir(p: Path) -> bool:
    return (p / "launcher_config.json").exists() or (p / "Choice.exe").exists()


def _not_data_dir(p: Path) -> Path:
    """Если корнем оказалась сама папка Data — берём её родителя.

    launcher_config.json лежит в Data, поэтому при запуске с рабочей папкой
    Data корнем считалась Data, и данные уезжали в Data\\Data.
    """
    if p.name.lower() == "data" and _is_launcher_dir(p.parent):
        return p.parent
    return p


def launcher_root() -> Path:
    env = (os.environ.get("LAUNCHER_ROOT") or "").strip()
    if env:
        return _not_data_dir(Path(env).resolve())
    cwd = Path.cwd().resolve()
    if _is_launcher_dir(cwd):
        return _not_data_dir(cwd)
    here = Path(__file__).resolve()
    for p in [here.parent] + list(here.parents):
        if _is_launcher_dir(p):
            return _not_data_dir(p)
    return here.parent


APPDIR = launcher_root()

# Все данные приложения — в одной папке Data.
DATA_DIR = APPDIR / "Data"
NOTES_DIR = DATA_DIR / "Notes"
PASSWORDS_DIR = DATA_DIR / "Passwords"
PLUGINS_DIR = DATA_DIR / "Plugins"

NOTES_ORDER_PATH = DATA_DIR / "notes_order.json"

STANDBY_CLEANER_PATH = DATA_DIR / "rammap.exe"
SALT_PATH = DATA_DIR / "salt.bin"
SETTINGS_PATH = DATA_DIR / "settings.ini"
ICON_PATH = DATA_DIR / "icon.ico"
TRAY_ICON_PATH = DATA_DIR / "tray_icon.ico"
FILE_ICON_PATH = DATA_DIR / "file.ico"
USER_DICT_PATH = DATA_DIR / "user_dictionary.txt"
NOTES_WIDGET_PATH = DATA_DIR / "desktop_notes.json"
NOTES_WIDGET_BAK = DATA_DIR / "desktop_notes.json.bak"

LOG_PATH = DATA_DIR / "crash.log"

PROCESS_PRIORITY_LEVELS = ("low", "below_normal", "normal", "above_normal", "high")

_WIN_PRIORITY_CLASS = {
    "low": 0x00000040,
    "below_normal": 0x00004000,
    "normal": 0x00000020,
    "above_normal": 0x00008000,
    "high": 0x00000080,
}


def qt_path(p: "Path | str") -> str:
    return str(p)


def resolve_rammap_exe() -> "Path | None":
    candidates: list[Path] = []

    try:
        candidates.append(STANDBY_CLEANER_PATH)
    except Exception:
        pass

    try:
        candidates.append(DATA_DIR / "rammap.exe")
    except Exception:
        pass

    bases: list[Path] = []
    try:
        bases.append(Path(sys.argv[0]).resolve().parent)
    except Exception:
        pass
    try:
        bases.append(Path(sys.executable).resolve().parent)
    except Exception:
        pass
    try:
        bases.append(Path(__file__).resolve().parent)
    except Exception:
        pass
    try:
        bases.append(Path.cwd().resolve())
    except Exception:
        pass

    for b in bases:
        candidates.append(b / "Data" / "rammap.exe")
        candidates.append(b / "rammap.exe")

    seen: set[str] = set()
    uniq: list[Path] = []
    for p in candidates:
        sp = str(p)
        if sp in seen:
            continue
        seen.add(sp)
        uniq.append(p)

    for p in uniq:
        try:
            if p.is_file():
                return p
        except Exception:
            continue

    folders: set[Path] = set()
    for p in uniq:
        try:
            folders.add(p.parent)
        except Exception:
            pass

    for folder in folders:
        try:
            if not folder.is_dir():
                continue
            for f in folder.iterdir():
                try:
                    if f.is_file() and f.name.lower() == "rammap.exe":
                        return f
                except Exception:
                    continue
        except Exception:
            continue

    return None
