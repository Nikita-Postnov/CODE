# -*- coding: utf-8 -*-
"""
LaptopCare — обслуживание домашнего ноутбука (Windows 10/11).

Вкладки:
  1. Автозагрузка  — реестр Run, папки Startup, задачи планировщика, сторонние службы.
                     Отключение как в Диспетчере задач (StartupApproved), журнал + откат.
  2. Очистка       — temp, кэши pip/npm/uv, __pycache__, старые venv, кэши браузеров,
                     дампы, кэш обновлений Windows, корзина. Сначала скан, потом удаление.
  3. Питание       — автопереключение схемы/режима: от сети / от батареи / по процессам.
  4. Батарея и сон — износ батареи по powercfg /batteryreport (история + график),
                     кто мешает спать, что разбудило, какие устройства могут будить.
  5. Процессы      — фоновый журнал прожорливых процессов (CPU/RAM/диск) в SQLite.

Запуск:       положить в Launcher\\ рядом с Choice.exe и добавить в Choice
              (или: python laptop_care.py [--tray]).
Portable:     корень Launcher ищется как в остальных скриптах (LAUNCHER_ROOT / Choice.exe),
              данные — Launcher\\Data\\LaptopCare\\, пути в настройках относительные.
              Из Runtime\\ скрипт сам делает себе Runtime\\NP_LaptopCare.exe (копия pythonw,
              через rcedit — с названием и иконкой) и прописывается в Runtime\\apps.json,
              чтобы Choice запускал его этим exe и закрывал вместе с собой.
Зависимости:  PySide6, psutil (psutil можно поставить кнопкой на вкладке «Процессы»).
"""
from __future__ import annotations

import ctypes
import datetime as dt
import json
import logging
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

IS_WIN = sys.platform == "win32"
if IS_WIN:
    import winreg
else:  # модуль должен импортироваться и вне Windows (тесты парсеров)
    winreg = None

try:
    import psutil
except ImportError:
    psutil = None

try:
    from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal, Slot
    from PySide6.QtGui import (QAction, QActionGroup, QColor, QFont, QIcon, QPainter, QPainterPath,
                               QPalette, QPen, QPixmap)
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
                                   QDialog, QFileDialog, QFormLayout, QGridLayout,
                                   QGroupBox, QHBoxLayout, QHeaderView, QInputDialog,
                                   QLabel, QLineEdit, QListWidget, QMainWindow, QMenu,
                                   QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
                                   QSplitter, QStyleFactory, QSystemTrayIcon, QTableWidget,
                                   QTableWidgetItem, QTabWidget, QToolButton, QVBoxLayout,
                                   QWidget)
except ImportError:
    _py = os.path.join(os.path.dirname(sys.executable), "python.exe")
    _msg = ("Для LaptopCare нужен PySide6.\n\nУстановите в тот Python, которым запускается скрипт:\n"
            f'"{_py if os.path.isfile(_py) else sys.executable}" -m pip install PySide6 psutil')
    if sys.platform == "win32":   # под pythonw консоли нет — показываем окно
        ctypes.windll.user32.MessageBoxW(None, _msg, "LaptopCare", 0x10)
    else:
        print(_msg)
    raise SystemExit(1)


# ═══════════════════════════════════════════════════════════════════════════
#  Константы и общие помощники
# ═══════════════════════════════════════════════════════════════════════════
APP_NAME = "LaptopCare"
APP_VERSION = "1.0"
SIGNATURE = ">_ np::core"
SERVER_NAME = "npcore-laptopcare"
AUTOSTART_VALUE = "NPCore LaptopCare"

OWN_EXE = "NP_LaptopCare"     # своя копия pythonw.exe в Runtime\ (как NP_Notes.exe и др.)

if getattr(sys, "frozen", False):
    SCRIPT_PATH = Path(sys.executable).resolve()
else:
    SCRIPT_PATH = Path(__file__).resolve()


# ── корень Launcher: та же логика, что в Screenshot.py / noteapp/config.py ──
def _is_launcher_dir(p: Path) -> bool:
    return any((p / n).exists() for n in ("launcher_config.json", "Choice.exe", "Choice.pyw"))


def _not_data_dir(p: Path) -> Path:
    """Choice передаёт LAUNCHER_ROOT=...\\Data — корень тогда её родитель (иначе Data\\Data)."""
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
    for p in [SCRIPT_PATH.parent] + list(SCRIPT_PATH.parents):
        if _is_launcher_dir(p):
            return _not_data_dir(p)
    return SCRIPT_PATH.parent


ROOT = launcher_root()
RUNTIME_DIR = ROOT / "Runtime"
UNDER_LAUNCHER = (ROOT / "Choice.exe").exists() or (ROOT / "Choice.pyw").exists()
BASE_DIR = ROOT
DATA_DIR = Path(os.environ.get("LAPTOPCARE_DATA") or ROOT / "Data" / APP_NAME)


def running_from_runtime() -> bool:
    """Запущены portable-интерпретатором из Launcher\\Runtime (pythonw/python/NP_*.exe)."""
    try:
        return Path(sys.executable).resolve().parent == RUNTIME_DIR.resolve()
    except OSError:
        return False


def to_portable_path(p: str) -> str:
    """Путь для настроек: внутри Launcher — относительный, в профиле — через %USERPROFILE%."""
    try:
        ap = Path(os.path.expandvars(p)).resolve()
    except (OSError, ValueError):
        return p
    try:
        rel = ap.relative_to(ROOT.resolve())
        return str(rel) if str(rel) != "." else "."
    except ValueError:
        pass
    try:
        return str(Path("%USERPROFILE%") / ap.relative_to(Path.home().resolve()))
    except ValueError:
        return str(ap)


def from_portable_path(s: str) -> str:
    p = Path(os.path.expandvars(str(s).strip()))
    if not p.is_absolute():
        p = ROOT / p
    return os.path.normpath(str(p))

CREATE_NO_WINDOW = 0x08000000
MB = 1024 * 1024

ACCENT = "#4ade80"
WARN = "#facc15"
BAD = "#f87171"
MUTED = "#8b949e"

log = logging.getLogger("laptopcare")


def _oem_encoding() -> str:
    if IS_WIN:
        try:
            return f"cp{ctypes.windll.kernel32.GetOEMCP()}"
        except Exception:
            pass
    return "utf-8"


OEM = _oem_encoding()


def run_cmd(args: list[str], timeout: float = 120, encoding: str | None = None) -> tuple[int, str]:
    """Запуск консольной команды без окна. Возвращает (код, вывод)."""
    kw = {"creationflags": CREATE_NO_WINDOW} if IS_WIN else {}
    try:
        p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           stdin=subprocess.DEVNULL, timeout=timeout, **kw)
    except FileNotFoundError:
        return 127, f"Команда не найдена: {args[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"Превышено время ожидания ({timeout:.0f} с): {' '.join(args)}"
    return p.returncode, _decode_command_output(p.stdout, encoding or OEM)


def _decode_command_output(raw: bytes, encoding: str) -> str:
    """Decode PowerShell diagnostics even when Windows emits OEM/ANSI instead of UTF-8."""
    text = raw.decode(encoding, errors="replace")
    if "\ufffd" not in text or not encoding.casefold().startswith("utf-8"):
        return text.strip()
    alternatives = [text]
    for codec in (OEM, "cp1251"):
        try:
            candidate = raw.decode(codec, errors="replace")
        except LookupError:
            continue
        alternatives.append(candidate)
    def quality(value: str) -> tuple[int, int]:
        cyrillic = sum("\u0400" <= c <= "\u052f" for c in value)
        garbage = value.count("\ufffd") * 10 + sum("\u2500" <= c <= "\u259f" for c in value) * 2
        return (cyrillic - garbage, -garbage)
    return max(alternatives, key=quality).strip()


def run_ps(script: str, timeout: float = 120) -> tuple[int, str]:
    prefix = ("[Console]::OutputEncoding=(New-Object System.Text.UTF8Encoding($false));"
              "$OutputEncoding=[Console]::OutputEncoding;"
              "$ProgressPreference='SilentlyContinue';$ErrorActionPreference='Stop';")
    return run_cmd(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                    "Bypass", "-Command", prefix + script], timeout, "utf-8-sig")


def ps_quote(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def ps_json(script: str, timeout: float = 120) -> list[dict]:
    code, out = run_ps(script + " | ConvertTo-Json -Depth 3 -Compress", timeout)
    if code != 0:
        raise RuntimeError(out or f"PowerShell вернул {code}")
    out = out.strip().lstrip("\ufeff")
    if not out:
        return []
    data = json.loads(out)
    return data if isinstance(data, list) else [data]


def is_admin() -> bool:
    if not IS_WIN:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin(extra_args: list[str]) -> bool:
    if getattr(sys, "frozen", False):
        params = subprocess.list2cmdline(extra_args)
    else:
        params = subprocess.list2cmdline([str(Path(__file__).resolve()), *extra_args])
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params,
                                             str(BASE_DIR), 1)
    return rc > 32


def human_size(n: float) -> str:
    n = float(n or 0)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if abs(n) < 1024:
            return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} ТБ"


def explorer_select(path: str) -> None:
    if not IS_WIN or not path:
        return
    if os.path.exists(path):
        subprocess.Popen(f'explorer /select,"{path}"')
    elif os.path.isdir(os.path.dirname(path)):
        os.startfile(os.path.dirname(path))


def running_process_names() -> set[str]:
    if psutil is None:
        return set()
    names = set()
    for p in psutil.process_iter(["name"]):
        n = p.info.get("name")
        if n:
            names.add(n.lower())
    return names


# ═══════════════════════════════════════════════════════════════════════════
#  Настройки
# ═══════════════════════════════════════════════════════════════════════════
DEFAULT_SETTINGS: dict = {
    "minimize_to_tray": True,
    "start_in_tray": True,
    "tray_hint_shown": False,
    "clean_roots": None,          # None → заполнить по умолчанию при первом запуске
    "clean_checked": {},
    "temp_min_age_h": 24,
    "venv_days": 90,
    "power_auto": False,
    "power_ac": "",
    "power_dc": "",
    "power_rules": [],            # [{"process": "game.exe", "profile": "plan:GUID"}]
    "power_interval_s": 5,
    "power_dup_done": [],
    "mon_enabled": True,
    "mon_interval_s": 5,
    "mon_cpu": 60,
    "mon_mem": 85,
    "mon_io_mb": 40,
    "mon_keep_days": 30,
    "battery_auto_days": 7,
}


class Settings:
    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(json.dumps(DEFAULT_SETTINGS))
        try:
            loaded = json.loads(path.read_text("utf-8"))
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except FileNotFoundError:
            pass
        except Exception:
            log.exception("Не удалось прочитать настройки, беру значения по умолчанию")
        if not self.data.get("clean_roots"):
            self.data["clean_roots"] = default_dev_roots()

    def __getitem__(self, key):
        return self.data.get(key, DEFAULT_SETTINGS.get(key))

    def __setitem__(self, key, value):
        self.data[key] = value
        self.save()

    def save(self) -> None:
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), "utf-8")
            os.replace(tmp, self.path)
        except Exception:
            log.exception("Не удалось сохранить настройки")


def default_dev_roots() -> list[str]:
    """Папки проектов по умолчанию — в переносимом виде (относительно Launcher / %USERPROFILE%)."""
    home = Path.home()
    cands = [ROOT, Path(r"C:\WORK"), home / "Desktop", home / "Documents", home / "Projects",
             home / "PycharmProjects", home / "source" / "repos"]
    out, seen = [], set()
    for c in cands:
        try:
            if c.is_dir():
                key = os.path.normcase(str(c.resolve()))
                if key not in seen:
                    seen.add(key)
                    out.append(to_portable_path(str(c)))
        except OSError:
            pass
    return out


# ═══════════════════════════════════════════════════════════════════════════
#  Фоновые задачи: функция в потоке, результат — в GUI-потоке
# ═══════════════════════════════════════════════════════════════════════════
class AsyncCall(QObject):
    _sig_done = Signal(object)
    _sig_fail = Signal(str)
    _sig_progress = Signal(object)

    def __init__(self, parent: QObject, fn: Callable, on_done=None, on_fail=None, on_progress=None):
        super().__init__(parent)
        self._fn, self._on_done, self._on_fail, self._on_progress = fn, on_done, on_fail, on_progress
        self._sig_done.connect(self._handle_done)
        self._sig_fail.connect(self._handle_fail)
        self._sig_progress.connect(self._handle_progress)

    def start(self) -> "AsyncCall":
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def _run(self) -> None:
        try:
            res = self._fn(self._sig_progress.emit)
        except Exception as e:
            log.exception("Ошибка фоновой задачи")
            self._sig_fail.emit(f"{type(e).__name__}: {e}")
        else:
            self._sig_done.emit(res)

    @Slot(object)
    def _handle_done(self, res) -> None:
        try:
            if self._on_done:
                self._on_done(res)
        finally:
            self.deleteLater()

    @Slot(str)
    def _handle_fail(self, msg: str) -> None:
        try:
            if self._on_fail:
                self._on_fail(msg)
        finally:
            self.deleteLater()

    @Slot(object)
    def _handle_progress(self, obj) -> None:
        if self._on_progress:
            self._on_progress(obj)


def run_async(parent, fn, on_done=None, on_fail=None, on_progress=None) -> AsyncCall:
    """fn(report) выполняется в потоке; report(obj) → on_progress(obj) в GUI-потоке."""
    return AsyncCall(parent, fn, on_done, on_fail, on_progress).start()


# ═══════════════════════════════════════════════════════════════════════════
#  1. Автозагрузка
# ═══════════════════════════════════════════════════════════════════════════
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"
_REG_SOURCES = [
    # (куст, ключ Run, подключ StartupApproved, подпись)
    ("HKCU", RUN_KEY, "Run", "Реестр HKCU"),
    ("HKLM", RUN_KEY, "Run", "Реестр HKLM"),
    ("HKLM", r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run", "Run32", "Реестр HKLM (32-бит)"),
]
KIND_TITLES = {"reg": "Реестр", "folder": "Папка", "task": "Планировщик", "service": "Служба"}
_TRIGGERS = {
    "MSFT_TaskLogonTrigger": "при входе", "MSFT_TaskBootTrigger": "при загрузке",
    "MSFT_TaskDailyTrigger": "ежедневно", "MSFT_TaskWeeklyTrigger": "еженедельно",
    "MSFT_TaskTimeTrigger": "по времени", "MSFT_TaskIdleTrigger": "при простое",
    "MSFT_TaskSessionStateChangeTrigger": "смена сеанса", "MSFT_TaskEventTrigger": "по событию",
    "MSFT_TaskRegistrationTrigger": "при создании", "MSFT_TaskTrigger": "по расписанию",
}


@dataclass
class StartupItem:
    kind: str                 # reg | folder | task | service
    name: str
    command: str
    enabled: bool
    location: str
    publisher: str = ""
    target: str = ""          # путь к исполняемому файлу (для «открыть расположение»)
    ref: dict = field(default_factory=dict)


def _hive(name: str):
    return winreg.HKEY_CURRENT_USER if name == "HKCU" else winreg.HKEY_LOCAL_MACHINE


def _reg_values(hive: str, subkey: str) -> list[tuple]:
    try:
        with winreg.OpenKey(_hive(hive), subkey, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            out, i = [], 0
            while True:
                try:
                    out.append(winreg.EnumValue(k, i))
                except OSError:
                    return out
                i += 1
    except OSError:
        return []


def _approved_enabled(hive: str, approved: str, value: str) -> bool:
    try:
        with winreg.OpenKey(_hive(hive), APPROVED_KEY + "\\" + approved, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            data, _ = winreg.QueryValueEx(k, value)
    except OSError:
        return True
    # чётный первый байт (02, 06) — включено, нечётный (03, 07) — отключено
    return not (isinstance(data, (bytes, bytearray)) and len(data) > 0 and data[0] & 1)


def _filetime_now() -> bytes:
    return int((time.time() + 11644473600) * 10_000_000).to_bytes(8, "little")


def _set_approved(hive: str, approved: str, value: str, enabled: bool) -> None:
    data = (b"\x02" + b"\x00" * 11) if enabled else (b"\x03\x00\x00\x00" + _filetime_now())
    with winreg.CreateKeyEx(_hive(hive), APPROVED_KEY + "\\" + approved, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
        winreg.SetValueEx(k, value, 0, winreg.REG_BINARY, data)


_EXE_RE = re.compile(r'^\s*"([^"]+)"|^\s*(\S.*?\.(?:exe|com|bat|cmd|ps1|vbs|lnk|pyw?))(?=\s|$)', re.I)


def extract_exe(command: str) -> str:
    """Путь к исполняемому файлу из командной строки (с кавычками или без)."""
    if not command:
        return ""
    cmd = os.path.expandvars(command.strip())
    if cmd.startswith("\\??\\"):
        cmd = cmd[4:]
    m = _EXE_RE.match(cmd)
    if m:
        return (m.group(1) or m.group(2)).strip()
    return cmd.split()[0] if cmd.split() else ""


_company_cache: dict[str, str] = {}


def file_company(path: str) -> str:
    """CompanyName из ресурса версии файла."""
    if not IS_WIN or not path:
        return ""
    key = path.lower()
    if key in _company_cache:
        return _company_cache[key]
    res = ""
    try:
        if os.path.isfile(path):
            ver = ctypes.windll.version
            size = ver.GetFileVersionInfoSizeW(path, None)
            if size:
                buf = ctypes.create_string_buffer(size)
                if ver.GetFileVersionInfoW(path, 0, size, buf):
                    lp, ln = ctypes.c_void_p(), ctypes.c_uint()
                    langs = []
                    if ver.VerQueryValueW(buf, "\\VarFileInfo\\Translation",
                                          ctypes.byref(lp), ctypes.byref(ln)) and ln.value >= 4:
                        w = (ctypes.c_ushort * 2).from_address(lp.value)
                        langs.append(f"{w[0]:04x}{w[1]:04x}")
                    langs += ["040904b0", "041904b0", "040904e4", "000004b0"]
                    for lc in langs:
                        if ver.VerQueryValueW(buf, f"\\StringFileInfo\\{lc}\\CompanyName",
                                              ctypes.byref(lp), ctypes.byref(ln)) and ln.value:
                            res = ctypes.wstring_at(lp.value, ln.value).rstrip("\x00").strip()
                            if res:
                                break
    except Exception:
        res = ""
    _company_cache[key] = res
    return res


def _startup_folders() -> list[tuple[str, Path, str]]:
    out = []
    if os.environ.get("APPDATA"):
        out.append(("HKCU", Path(os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs\Startup"),
                    "Папка автозагрузки (пользователь)"))
    if os.environ.get("PROGRAMDATA"):
        out.append(("HKLM", Path(os.environ["PROGRAMDATA"], r"Microsoft\Windows\Start Menu\Programs\StartUp"),
                    "Папка автозагрузки (общая)"))
    return out


def resolve_shortcuts(paths: list[str]) -> dict[str, tuple[str, str]]:
    if not paths:
        return {}
    arr = ",".join(ps_quote(p) for p in paths)
    script = ("$s=New-Object -ComObject WScript.Shell;"
              f"@({arr}) | ForEach-Object {{ $l=$s.CreateShortcut($_); "
              "[pscustomobject]@{P=[string]$_;T=[string]$l.TargetPath;A=[string]$l.Arguments} }")
    try:
        rows = ps_json(script, 60)
    except Exception:
        log.exception("Не удалось разобрать ярлыки")
        return {}
    return {r.get("P", ""): (r.get("T") or "", r.get("A") or "") for r in rows}


_TASKS_PS = r"""
Get-ScheduledTask | Where-Object { $_.TaskPath -notlike '\Microsoft\*' } | ForEach-Object {
  $t = $_
  $acts = @($t.Actions | ForEach-Object { if ($_.Execute) { ('"' + $_.Execute.Trim('"') + '" ' + $_.Arguments).Trim() } else { '[COM]' } }) -join ' ; '
  $trg = @($t.Triggers | ForEach-Object { [string]$_.CimClass.CimClassName }) -join ','
  [pscustomobject]@{ Name=[string]$t.TaskName; Path=[string]$t.TaskPath; State=[string]$t.State; Author=[string]$t.Author; Cmd=$acts; Trg=$trg }
}
"""

_SERVICES_PS = r"""
Get-CimInstance Win32_Service | Where-Object { $_.StartMode -ne 'Disabled' } | ForEach-Object {
  [pscustomobject]@{ Name=[string]$_.Name; Disp=[string]$_.DisplayName; Path=[string]$_.PathName; State=[string]$_.State; Mode=[string]$_.StartMode; Delayed=[bool]$_.DelayedAutoStart }
}
"""


class StartupJournal:
    """Журнал изменений автозагрузки — для отката."""

    def __init__(self, path: Path):
        self.path = path
        try:
            self.entries: list[dict] = json.loads(path.read_text("utf-8"))
        except FileNotFoundError:
            self.entries = []
        except Exception:
            log.exception("Журнал автозагрузки повреждён, начинаю новый")
            self.entries = []

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.entries, ensure_ascii=False, indent=1), "utf-8")
        os.replace(tmp, self.path)

    def add(self, it: StartupItem, was: bool, now: bool) -> None:
        self.entries.append({"ts": dt.datetime.now().isoformat(timespec="seconds"), "kind": it.kind,
                             "name": it.name, "location": it.location, "ref": it.ref,
                             "was": was, "now": now, "rolled_back": False})
        self.save()

    def service_restore_modes(self) -> dict[str, str]:
        res = {}
        for e in self.entries:
            if e["kind"] == "service" and not e.get("rolled_back"):
                res[e["ref"]["name"].lower()] = e["ref"].get("restore", "auto")
        return res


def scan_startup(journal_services: dict[str, str], report) -> tuple[list[StartupItem], list[str]]:
    items: list[StartupItem] = []
    errors: list[str] = []

    report("Реестр…")
    for hive, sub, approved, title in _REG_SOURCES:
        for name, value, _typ in _reg_values(hive, sub):
            if not name or not str(value).strip():
                continue
            cmd = str(value)
            exe = extract_exe(cmd)
            items.append(StartupItem("reg", name, cmd, _approved_enabled(hive, approved, name), title,
                                     file_company(exe), exe,
                                     {"hive": hive, "approved": approved, "value": name}))

    report("Папки автозагрузки…")
    folder_items, lnks = [], []
    for hive, folder, title in _startup_folders():
        if not folder.is_dir():
            continue
        for p in folder.iterdir():
            if p.is_dir() or p.name.lower() == "desktop.ini":
                continue
            folder_items.append(StartupItem(
                "folder", p.stem, str(p), _approved_enabled(hive, "StartupFolder", p.name), title,
                ref={"hive": hive, "approved": "StartupFolder", "value": p.name, "path": str(p)}))
            if p.suffix.lower() == ".lnk":
                lnks.append(str(p))
    targets = resolve_shortcuts(lnks)
    for it in folder_items:
        exe, args = targets.get(it.ref["path"], ("", ""))
        if exe:
            it.command = f'"{exe}" {args}'.strip()
            it.target = exe
        else:
            it.target = it.ref["path"]
        it.publisher = file_company(it.target)
    items += folder_items

    report("Планировщик заданий…")
    try:
        for r in ps_json(_TASKS_PS, 120):
            cmd = r.get("Cmd") or ""
            exe = extract_exe(cmd.split(" ; ")[0])
            trg = ", ".join(_TRIGGERS.get(t, t.replace("MSFT_Task", "")) for t in (r.get("Trg") or "").split(",") if t)
            items.append(StartupItem(
                "task", r.get("Name", ""), cmd, (r.get("State") or "") != "Disabled",
                f"Планировщик {r.get('Path', '')}" + (f" · {trg}" if trg else ""),
                file_company(exe) or (r.get("Author") or ""), exe,
                {"path": r.get("Path", "\\"), "name": r.get("Name", "")}))
    except Exception as e:
        errors.append(f"Планировщик: {e}")

    report("Службы…")
    try:
        sysroot = os.environ.get("SystemRoot", r"C:\Windows").lower()
        for r in ps_json(_SERVICES_PS, 120):
            name = r.get("Name", "")
            mode = r.get("Mode", "")
            touched = name.lower() in journal_services
            if mode != "Auto" and not touched:
                continue
            exe = extract_exe(r.get("Path", ""))
            company = file_company(exe)
            if not touched and ("microsoft" in company.lower() or
                                (not company and exe.lower().startswith(sysroot))):
                continue
            restore = journal_services.get(name.lower()) or ("delayed-auto" if r.get("Delayed") else "auto")
            items.append(StartupItem(
                "service", r.get("Disp") or name, r.get("Path", ""), mode == "Auto",
                f"Служба {name} · {'работает' if r.get('State') == 'Running' else 'остановлена'}",
                company, exe, {"name": name, "restore": restore}))
    except Exception as e:
        errors.append(f"Службы: {e}")

    return items, errors


def set_startup_enabled(it: StartupItem, enabled: bool) -> None:
    if it.kind in ("reg", "folder"):
        _set_approved(it.ref["hive"], it.ref["approved"], it.ref["value"], enabled)
    elif it.kind == "task":
        verb = "Enable" if enabled else "Disable"
        code, out = run_ps(f"{verb}-ScheduledTask -TaskPath {ps_quote(it.ref['path'])} "
                           f"-TaskName {ps_quote(it.ref['name'])} | Out-Null")
        if code != 0:
            raise PermissionError(out) if "0x80070005" in out or "Access" in out else RuntimeError(out)
    elif it.kind == "service":
        mode = (it.ref.get("restore") or "auto") if enabled else "demand"
        code, out = run_cmd(["sc.exe", "config", it.ref["name"], "start=", mode])
        if code != 0:
            raise PermissionError(out) if code == 5 else RuntimeError(out)


# ═══════════════════════════════════════════════════════════════════════════
#  2. Очистка
# ═══════════════════════════════════════════════════════════════════════════
def _is_link_entry(e: os.DirEntry) -> bool:
    try:
        if e.is_symlink():
            return True
        j = getattr(e, "is_junction", None)
        return bool(j and j())
    except OSError:
        return True


def _is_link_path(p: str) -> bool:
    try:
        return os.path.islink(p) or bool(getattr(os.path, "isjunction", lambda _p: False)(p))
    except OSError:
        return False


def tree_size(path: Path) -> tuple[int, int]:
    """(байт, файлов). Ссылки и junction не раскрываются."""
    p = str(path)
    try:
        st = os.lstat(p)
    except OSError:
        return 0, 0
    if not stat.S_ISDIR(st.st_mode) or _is_link_path(p):
        return (st.st_size if stat.S_ISREG(st.st_mode) else 0), 1
    total = files = 0
    stack = [p]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if _is_link_entry(e):
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                            files += 1
                    except OSError:
                        pass
        except OSError:
            pass
    return total, files


def _force_remove(fn: Callable[[str], None], p: str) -> bool:
    try:
        fn(p)
        return True
    except FileNotFoundError:
        return True
    except PermissionError:
        try:
            os.chmod(p, stat.S_IWRITE)
            fn(p)
            return True
        except OSError:
            return False
    except OSError:
        return False


def _remove_link(p: str) -> bool:
    try:
        os.unlink(p)
        return True
    except OSError:
        try:
            os.rmdir(p)
            return True
        except OSError:
            return False


def delete_path(path: Path) -> tuple[int, int]:
    """Удаляет файл или папку. Занятые файлы пропускает. Возвращает (освобождено байт, ошибок)."""
    p = str(path)
    try:
        st = os.lstat(p)
    except FileNotFoundError:
        return 0, 0
    except OSError:
        return 0, 1
    if _is_link_path(p):
        return (0, 0) if _remove_link(p) else (0, 1)
    if not stat.S_ISDIR(st.st_mode):
        return (st.st_size, 0) if _force_remove(os.unlink, p) else (0, 1)

    freed = errors = 0
    dirs, files, stack = [p], [], [p]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    if _is_link_entry(e):
                        files.append((e.path, 0, True))
                        continue
                    try:
                        isdir = e.is_dir(follow_symlinks=False)
                    except OSError:
                        isdir = False
                    if isdir:
                        stack.append(e.path)
                        dirs.append(e.path)
                    else:
                        try:
                            sz = e.stat(follow_symlinks=False).st_size
                        except OSError:
                            sz = 0
                        files.append((e.path, sz, False))
        except OSError:
            errors += 1
    for fp, sz, is_link in files:
        ok = _remove_link(fp) if is_link else _force_remove(os.unlink, fp)
        if ok:
            freed += sz
        else:
            errors += 1
    for d in reversed(dirs):        # дети всегда добавлены после родителя
        try:
            os.rmdir(d)
        except OSError:
            pass
    return freed, errors


def _env(var: str, *parts: str) -> Path | None:
    v = os.environ.get(var)
    return Path(v, *parts) if v else None


def _children(folder: Path | None, min_age_h: float = 0) -> list[Path]:
    if not folder or not folder.is_dir():
        return []
    cutoff = time.time() - min_age_h * 3600
    out = []
    try:
        with os.scandir(folder) as it:
            for e in it:
                try:
                    if min_age_h <= 0 or e.stat(follow_symlinks=False).st_mtime < cutoff:
                        out.append(Path(e.path))
                except OSError:
                    pass
    except OSError:
        pass
    return out


_CHROMIUM = [
    ("Chrome", r"Google\Chrome\User Data", "chrome.exe"),
    ("Edge", r"Microsoft\Edge\User Data", "msedge.exe"),
    ("Яндекс", r"Yandex\YandexBrowser\User Data", "browser.exe"),
    ("Brave", r"BraveSoftware\Brave-Browser\User Data", "brave.exe"),
    ("Vivaldi", r"Vivaldi\User Data", "vivaldi.exe"),
]
BROWSER_EXES = tuple(x[2] for x in _CHROMIUM) + ("firefox.exe",)


def _browser_caches(_ctx) -> list:
    out = []
    la = os.environ.get("LOCALAPPDATA")
    if not la:
        return out
    for title, rel, _exe in _CHROMIUM:
        ud = Path(la, rel)
        if not ud.is_dir():
            continue
        try:
            profiles = [p for p in ud.iterdir() if p.is_dir() and (
                p.name in ("Default", "Guest Profile", "System Profile") or p.name.startswith("Profile "))]
        except OSError:
            profiles = []
        for prof in profiles:
            for c in ("Cache", "Code Cache", "GPUCache"):
                if (prof / c).is_dir():
                    out.append((prof / c, f"{title} · {prof.name}"))
        for c in ("ShaderCache", "GrShaderCache", "GraphiteDawnCache"):
            if (ud / c).is_dir():
                out.append((ud / c, title))
    ff = Path(la, r"Mozilla\Firefox\Profiles")
    if ff.is_dir():
        for prof in ff.iterdir():
            for c in ("cache2", "startupCache", "thumbnails"):
                if (prof / c).is_dir():
                    out.append((prof / c, f"Firefox · {prof.name}"))
    return out


def _pkg_caches(_ctx) -> list:
    la, home = os.environ.get("LOCALAPPDATA"), Path.home()
    cands = []
    if la:
        cands += [(Path(la, "pip", "cache"), "pip"), (Path(la, "npm-cache"), "npm"),
                  (Path(la, "uv", "cache"), "uv"), (Path(la, "Yarn", "Cache"), "yarn"),
                  (Path(la, "pnpm-cache"), "pnpm")]
    cands += [(home / ".cache" / "pip", "pip")]
    out = []
    for folder, title in cands:
        out += [(p, title) for p in _children(folder)]
    return out


_DEV_SKIP = {"node_modules", ".git", ".hg", ".svn", "$recycle.bin", "system volume information",
             "appdata", "windows", "program files", "program files (x86)", "programdata",
             ".idea", ".vs", ".vscode", "site-packages", ".mypy_cache", ".tox", "runtime"}


def _is_interpreter_dir(entries: list) -> bool:
    """Папка с установленным Python (в т.ч. Launcher\\Runtime) — её кэши не трогаем."""
    names = {e.name.lower() for e in entries}
    return ("python.exe" in names or "pythonw.exe" in names) and "lib" in names


def _project_activity(project: Path, venv: Path, depth: int = 3) -> float:
    """Последнее изменение файлов проекта (без самого venv)."""
    latest = 0.0
    venv_s = os.path.normcase(str(venv))
    stack = [(str(project), 0)]
    while stack:
        d, lvl = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if (lvl < depth and os.path.normcase(e.path) != venv_s
                                    and e.name.lower() not in ("__pycache__", ".git", "node_modules")
                                    and not os.path.isfile(os.path.join(e.path, "pyvenv.cfg"))):
                                stack.append((e.path, lvl + 1))
                        else:
                            latest = max(latest, e.stat(follow_symlinks=False).st_mtime)
                    except OSError:
                        pass
        except OSError:
            pass
    if not latest:
        try:
            latest = os.lstat(venv).st_mtime
        except OSError:
            pass
    return latest


def scan_dev_roots(roots: list[str]) -> tuple[list[Path], list[Path]]:
    """Ищет __pycache__ и виртуальные окружения (папки с pyvenv.cfg)."""
    pycache, venvs, seen = [], [], set()
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        stack = [root]
        while stack:
            d = stack.pop()
            key = os.path.normcase(os.path.abspath(d))
            if key in seen:
                continue
            seen.add(key)
            try:
                with os.scandir(d) as it:
                    entries = list(it)
            except OSError:
                continue
            if any(e.name == "pyvenv.cfg" for e in entries):
                venvs.append(Path(d))
                continue
            if _is_interpreter_dir(entries):
                continue
            for e in entries:
                try:
                    if _is_link_entry(e) or not e.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                n = e.name.lower()
                if n == "__pycache__":
                    pycache.append(Path(e.path))
                elif n not in _DEV_SKIP:
                    stack.append(e.path)
    return pycache, venvs


def _dev(ctx: dict) -> tuple[list[Path], list[Path]]:
    if ctx.get("_dev") is None:
        ctx["_dev"] = scan_dev_roots(ctx["roots"])
    return ctx["_dev"]


def _pycache(ctx) -> list:
    return _dev(ctx)[0]


def _old_venvs(ctx) -> list:
    out = []
    limit = time.time() - ctx["venv_days"] * 86400
    for v in _dev(ctx)[1]:
        act = _project_activity(v.parent, v)
        if act and act < limit:
            days = int((time.time() - act) / 86400)
            out.append((v, f"проект {v.parent.name}: без изменений {days} дн."))
    return out


def _dumps(_ctx) -> list:
    out = []
    for folder in (_env("LOCALAPPDATA", "CrashDumps"), _env("SystemRoot", "Minidump"),
                   _env("LOCALAPPDATA", r"Microsoft\Windows\WER\ReportArchive"),
                   _env("LOCALAPPDATA", r"Microsoft\Windows\WER\ReportQueue"),
                   _env("PROGRAMDATA", r"Microsoft\Windows\WER\ReportArchive"),
                   _env("PROGRAMDATA", r"Microsoft\Windows\WER\ReportQueue")):
        out += _children(folder)
    mem = _env("SystemRoot", "MEMORY.DMP")
    if mem and mem.is_file():
        out.append(mem)
    return out


@dataclass
class CleanTarget:
    key: str
    title: str
    note: str
    collect: Callable[[dict], list] | None
    admin: bool = False
    default_on: bool = True
    warn_procs: tuple = ()
    items: list = field(default_factory=list)   # [(Path, size, files, note)]
    size: int = 0
    count: int = 0
    scanned: bool = False
    error: str = ""


def build_clean_targets() -> list[CleanTarget]:
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    return [
        CleanTarget("temp", "Временные файлы пользователя", "%TEMP%, только старше заданного возраста",
                    lambda c: _children(_env("TEMP") or _env("TMP"), c["temp_age"])),
        CleanTarget("pkg", "Кэши pip / npm / uv / yarn", "скачаются заново при необходимости", _pkg_caches),
        CleanTarget("pycache", "__pycache__ в папках проектов", "Python пересоздаст при запуске", _pycache),
        CleanTarget("venv", "Заброшенные виртуальные окружения", "смотрите «Подробнее» перед удалением",
                    _old_venvs, default_on=False),
        CleanTarget("browser", "Кэши браузеров", "Chrome, Edge, Яндекс, Brave, Vivaldi, Firefox; закройте браузеры",
                    _browser_caches, default_on=False, warn_procs=BROWSER_EXES),
        CleanTarget("dumps", "Дампы и отчёты об ошибках", "CrashDumps, Minidump, WER",
                    _dumps, admin=True),
        CleanTarget("wintemp", "Временные файлы Windows", r"C:\Windows\Temp",
                    lambda c: _children(Path(sysroot, "Temp"), c["temp_age"]), admin=True),
        CleanTarget("wu", "Загрузки Центра обновления", "SoftwareDistribution\\Download",
                    lambda c: _children(Path(sysroot, "SoftwareDistribution", "Download")), admin=True),
        CleanTarget("do", "Кэш оптимизации доставки", "раздача обновлений другим ПК",
                    lambda c: _children(Path(sysroot, r"ServiceProfiles\NetworkService\AppData\Local"
                                                      r"\Microsoft\Windows\DeliveryOptimization\Cache")),
                    admin=True),
        CleanTarget("recycle", "Корзина", "все диски", None, default_on=False),
    ]


class SHQUERYRBINFO(ctypes.Structure):
    if ctypes.sizeof(ctypes.c_void_p) == 4:   # в 32-битном shellapi.h структура упакована
        _pack_ = 1
    _fields_ = [("cbSize", ctypes.c_uint32), ("i64Size", ctypes.c_int64), ("i64NumItems", ctypes.c_int64)]


def recycle_bin_info() -> tuple[int, int]:
    info = SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(info)
    if ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info)) != 0:
        return 0, 0
    return int(info.i64Size), int(info.i64NumItems)


def empty_recycle_bin() -> bool:
    hr = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x1 | 0x2 | 0x4)
    return hr in (0, -2147418113)  # S_OK или E_UNEXPECTED (уже пуста)


def scan_targets(targets: list[CleanTarget], ctx: dict, report) -> None:
    for t in targets:
        report(("start", t.key))
        try:
            if t.key == "recycle":
                t.size, t.count = recycle_bin_info()
                t.items = []
            else:
                items = []
                for x in t.collect(ctx):
                    p, note = x if isinstance(x, tuple) else (x, "")
                    sz, n = tree_size(p)
                    items.append((p, sz, n, note))
                items.sort(key=lambda i: i[1], reverse=True)
                t.items = items
                t.size = sum(i[1] for i in items)
                t.count = sum(i[2] for i in items)
            t.error = ""
        except Exception as e:
            log.exception("Скан %s", t.key)
            t.error = str(e)
        t.scanned = True
        report(("done", t.key))


def clean_selected(targets: list[CleanTarget], report) -> dict[str, tuple[int, int]]:
    res = {}
    for t in targets:
        report(("start", t.key))
        freed = errors = 0
        if t.key == "recycle":
            if empty_recycle_bin():
                freed = t.size
            else:
                errors = 1
        else:
            for p, _sz, _n, _note in t.items:
                f, e = delete_path(p)
                freed += f
                errors += e
        res[t.key] = (freed, errors)
        report(("done", t.key))
    return res


# ═══════════════════════════════════════════════════════════════════════════
#  3. Питание
# ═══════════════════════════════════════════════════════════════════════════
BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"
KNOWN_PLANS = {
    BALANCED: "Сбалансированная",
    "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c": "Высокая производительность",
    "a1841308-3541-4fab-bc81-f71556f20b4a": "Экономия энергии",
    "e9a42b02-d5df-448d-aa00-03f14749eb61": "Максимальная производительность",
}
# Режим питания = ползунок «Параметры → Система → Питание». Работает поверх схемы
# «Сбалансированная»; от экономного к производительному.
OVERLAY_MODES = {
    "961cc777-2547-4f9d-8174-7d86181b8a7a": "Энергоэффективность",
    "00000000-0000-0000-0000-000000000000": "Сбалансированный",
    "ded574b5-45a0-4f42-8737-46345c09c238": "Максимальная производительность",
}
MODE_TIPS = {
    "961cc777-2547-4f9d-8174-7d86181b8a7a": "Дольше от батареи, тише и холоднее; под нагрузкой медленнее.",
    "00000000-0000-0000-0000-000000000000": "Обычный режим Windows по умолчанию.",
    "ded574b5-45a0-4f42-8737-46345c09c238": "Процессор охотнее разгоняется под нагрузкой; в простое частота "
                                            "по-прежнему снижается. Лучший выбор «от сети».",
}
PLAN_TIP = ("Схема электропитания — полный набор настроек из Панели управления. "
            "Пока выбрана не «Сбалансированная», ползунок режима Windows недоступен.")


def _plan_rank(guid: str, name: str) -> int:
    """Порядок схем: экономия → сбалансированная → высокая → максимальная → свои."""
    order = {"a1841308-3541-4fab-bc81-f71556f20b4a": 0, BALANCED: 1,
             "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c": 2, "e9a42b02-d5df-448d-aa00-03f14749eb61": 3}
    if guid in order:
        return order[guid]
    n = name.lower()   # копии, сделанные «Добавить скрытые схемы», получают новые GUID
    for rank, words in ((0, ("эконом", "saver")), (1, ("сбаланс", "balanced")),
                        (3, ("максимал", "ultimate")), (2, ("высок", "high"))):
        if any(w in n for w in words):
            return rank
    return 4
_GUID_RE = re.compile(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")


def parse_powercfg_list(text: str) -> list[tuple[str, str, bool]]:
    """Разбор `powercfg /list` → [(guid, имя, активна)]. Не зависит от языка системы."""
    out = []
    for line in text.splitlines():
        m = _GUID_RE.search(line)
        if not m:
            continue
        guid = m.group(1).lower()
        rest = line[m.end():]
        nm = re.search(r"\((.*)\)", rest)
        name = nm.group(1).strip() if nm else KNOWN_PLANS.get(guid, guid)
        out.append((guid, name, rest.rstrip().endswith("*")))
    return out


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def from_str(cls, s: str) -> "GUID":
        return cls.from_buffer_copy(uuid.UUID(s).bytes_le)

    def __str__(self) -> str:
        return str(uuid.UUID(bytes_le=bytes(self)))


def overlay_supported() -> bool:
    if not IS_WIN:
        return False
    try:
        pp = ctypes.windll.powrprof
        return hasattr(pp, "PowerSetActiveOverlayScheme") and hasattr(pp, "PowerGetEffectiveOverlayScheme")
    except OSError:
        return False


def set_overlay(guid: str) -> None:
    fn = ctypes.windll.powrprof.PowerSetActiveOverlayScheme
    fn.argtypes, fn.restype = [GUID], ctypes.c_uint32
    rc = fn(GUID.from_str(guid))
    if rc != 0:
        raise OSError(f"PowerSetActiveOverlayScheme: код {rc}")


def get_overlay() -> str | None:
    fn = ctypes.windll.powrprof.PowerGetEffectiveOverlayScheme
    fn.argtypes, fn.restype = [ctypes.POINTER(GUID)], ctypes.c_uint32
    g = GUID()
    return str(g) if fn(ctypes.byref(g)) == 0 else None


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", ctypes.c_uint32), ("BatteryFullLifeTime", ctypes.c_uint32)]


def power_status() -> tuple[bool | None, int | None, bool]:
    """(от сети?, процент заряда, есть батарея)."""
    if not IS_WIN:
        return None, None, False
    s = SYSTEM_POWER_STATUS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)):
        return None, None, False
    on_ac = {0: False, 1: True}.get(s.ACLineStatus)
    pct = None if s.BatteryLifePercent == 255 else int(s.BatteryLifePercent)
    has_batt = s.BatteryFlag != 255 and not (s.BatteryFlag & 128)
    return on_ac, pct, has_batt


class PowerManager(QObject):
    event = Signal(str)

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.plans: list[tuple[str, str, bool]] = []
        self.has_overlay = overlay_supported()
        self.history: deque[str] = deque(maxlen=300)
        self._last_target: str | None = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.refresh_plans()
        self.apply_settings()

    def refresh_plans(self) -> None:
        code, out = run_cmd(["powercfg", "/list"], 30)
        self.plans = parse_powercfg_list(out) if code == 0 else []

    def active_plan(self) -> str | None:
        code, out = run_cmd(["powercfg", "/getactivescheme"], 15)
        m = _GUID_RE.search(out) if code == 0 else None
        return m.group(1).lower() if m else None

    def mode_items(self) -> list[tuple[str, str]]:
        """[(id, короткое имя)] режимов-ползунка, если Windows их поддерживает."""
        return [(f"mode:{g}", n) for g, n in OVERLAY_MODES.items()] if self.has_overlay else []

    def plan_items(self) -> list[tuple[str, str]]:
        """[(id, имя схемы)] по порядку от экономной к производительной."""
        plans = sorted(self.plans, key=lambda p: (_plan_rank(p[0], p[1]), p[1].lower()))
        return [(f"plan:{g}", n) for g, n, _a in plans]

    def profiles(self) -> list[tuple[str, str]]:
        """Полные подписи — для журнала и закрытых списков: «Режим: …» / «Схема: …»."""
        return ([(pid, f"Режим: {n}") for pid, n in self.mode_items()]
                + [(pid, f"Схема: {n}") for pid, n in self.plan_items()])

    def profile_name(self, pid: str) -> str:
        return dict(self.profiles()).get(pid, pid or "—")

    def current_profile(self) -> tuple[str | None, str]:
        """(id активного профиля, подпись). Режим считается активным только на «Сбалансированной»."""
        act = self.active_plan()
        if act and self.has_overlay and act == BALANCED:
            try:
                ov = get_overlay()
            except Exception:
                ov = None
            if ov in OVERLAY_MODES:
                pid = f"mode:{ov}"
                return pid, self.profile_name(pid)
        if act:
            pid = f"plan:{act}"
            return pid, self.profile_name(pid)
        return None, "—"

    def apply_settings(self) -> None:
        self._last_target = None
        if self.settings["power_auto"]:
            self.timer.start(max(2, int(self.settings["power_interval_s"])) * 1000)
            self.tick()
        else:
            self.timer.stop()

    def desired(self) -> tuple[str, str]:
        rules = [r for r in self.settings["power_rules"] if r.get("process") and r.get("profile")]
        if rules:
            running = running_process_names()
            for r in rules:
                if r["process"].lower() in running:
                    return r["profile"], f"запущен {r['process']}"
        on_ac, _pct, _hb = power_status()
        if on_ac is False:
            return self.settings["power_dc"], "от батареи"
        return self.settings["power_ac"], "от сети"

    def _emit(self, msg: str) -> None:
        line = f"{dt.datetime.now():%d.%m %H:%M:%S}  {msg}"
        self.history.appendleft(line)
        self.event.emit(line)

    def tick(self) -> None:
        try:
            target, reason = self.desired()
        except Exception as e:
            log.exception("Питание: desired")
            self._emit(f"Ошибка: {e}")
            return
        if not target or target == self._last_target:
            return
        self._last_target = target
        try:
            self.apply_profile(target)
            self._emit(f"{reason} → {self.profile_name(target)}")
        except Exception as e:
            self._emit(f"{reason}: не удалось применить «{self.profile_name(target)}»: {e}")

    def apply_profile(self, pid: str) -> None:
        kind, guid = pid.split(":", 1)
        if kind == "plan":
            code, out = run_cmd(["powercfg", "/setactive", guid], 30)
            if code != 0:
                raise RuntimeError(out)
        elif kind == "mode":
            # ползунок режима работает поверх «Сбалансированной» схемы
            if any(g == BALANCED for g, _n, _a in self.plans):
                run_cmd(["powercfg", "/setactive", BALANCED], 30)
            set_overlay(guid)

    def add_hidden_plans(self) -> str:
        have = {g for g, _n, _a in self.plans}
        done = set(self.settings["power_dup_done"])
        lines = []
        for guid, name in KNOWN_PLANS.items():
            if guid in have or guid in done:
                continue
            code, out = run_cmd(["powercfg", "-duplicatescheme", guid], 30)
            lines.append(f"{name}: {'добавлена' if code == 0 else out}")
            if code == 0:
                done.add(guid)
        self.settings["power_dup_done"] = sorted(done)
        self.refresh_plans()
        return "\n".join(lines) or "Все стандартные схемы уже есть."


# ═══════════════════════════════════════════════════════════════════════════
#  4. Батарея и сон
# ═══════════════════════════════════════════════════════════════════════════
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _fields(el: ET.Element) -> dict[str, str]:
    d = {k.lower(): v for k, v in el.attrib.items()}
    for c in el:
        if len(c) == 0 and c.text is not None:
            d.setdefault(_local(c.tag).lower(), c.text.strip())
    return d


def _int(v) -> int:
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return 0


def parse_battery_xml(text: str) -> dict:
    root = ET.fromstring(text)
    res = {"batteries": [], "history": [], "scan_time": ""}
    for el in root.iter():
        t = _local(el.tag)
        if t == "LocalScanTime" and el.text:
            res["scan_time"] = el.text.strip()
        elif t == "Batteries":
            for b in el:
                if _local(b.tag) == "Battery":
                    f = _fields(b)
                    res["batteries"].append({
                        "id": f.get("id", ""), "manufacturer": f.get("manufacturer", ""),
                        "chemistry": f.get("chemistry", ""),
                        "design": _int(f.get("designcapacity")), "full": _int(f.get("fullchargecapacity")),
                        "cycles": _int(f.get("cyclecount")),
                    })
        elif t == "HistoryEntry":
            f = _fields(el)
            date = (f.get("localstartdate") or f.get("startdate") or "")[:10]
            design, full = _int(f.get("designcapacity")), _int(f.get("fullchargecapacity"))
            if date and design > 0 and full > 0:
                res["history"].append({"date": date, "design": design, "full": full,
                                       "cycles": _int(f.get("cyclecount"))})
    return res


def battery_snapshot(report) -> dict:
    report("Формирую отчёт powercfg…")
    xml_path = DATA_DIR / "battery_report.xml"
    code, out = run_cmd(["powercfg", "/batteryreport", "/xml", "/output", str(xml_path)], 120)
    if code != 0 or not xml_path.exists():
        raise RuntimeError(out or "powercfg не создал отчёт")
    data = parse_battery_xml(xml_path.read_text("utf-8", errors="replace"))
    if not data["batteries"]:
        raise RuntimeError("Батарея не найдена (стационарный ПК или драйвер не отдаёт данные).")
    hist_path = DATA_DIR / "battery_history.json"
    try:
        hist = json.loads(hist_path.read_text("utf-8"))
    except Exception:
        hist = []
    design = sum(b["design"] for b in data["batteries"])
    full = sum(b["full"] for b in data["batteries"])
    cycles = max(b["cycles"] for b in data["batteries"])
    today = dt.date.today().isoformat()
    hist = [h for h in hist if not (h.get("date") == today and h.get("source") == "snapshot")]
    hist.append({"date": today, "design": design, "full": full, "cycles": cycles, "source": "snapshot"})
    hist_path.write_text(json.dumps(hist, ensure_ascii=False, indent=1), "utf-8")
    data["own_history"] = hist
    return data


def load_own_battery_history() -> list[dict]:
    try:
        return json.loads((DATA_DIR / "battery_history.json").read_text("utf-8"))
    except Exception:
        return []


def merge_battery_points(report_hist: list[dict], own: list[dict]) -> list[tuple[str, float]]:
    by_date: dict[str, float] = {}
    for h in report_hist:
        if h["design"] > 0:
            by_date[h["date"]] = 100.0 * h["full"] / h["design"]
    for h in own:                      # собственные замеры приоритетнее
        if h.get("design", 0) > 0:
            by_date[h["date"]] = 100.0 * h["full"] / h["design"]
    return sorted(by_date.items())


# ═══════════════════════════════════════════════════════════════════════════
#  5. Монитор процессов
# ═══════════════════════════════════════════════════════════════════════════
class ProcMonitor(QObject):
    tick = Signal(object)

    def __init__(self, settings: Settings, db_path: Path, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.db_path = db_path
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if psutil is None or self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="procmon", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self) -> None:
        con = sqlite3.connect(str(self.db_path), timeout=10)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("CREATE TABLE IF NOT EXISTS samples(ts REAL, reason TEXT, name TEXT, pid INTEGER,"
                        " cpu REAL, rss INTEGER, io REAL)")
            con.execute("CREATE INDEX IF NOT EXISTS ix_samples_ts ON samples(ts)")
            con.execute("DELETE FROM samples WHERE ts < ?",
                        (time.time() - int(self.settings["mon_keep_days"]) * 86400,))
            con.commit()
            ncpu = psutil.cpu_count() or 1
            psutil.cpu_percent(None)
            prev_io: dict[int, int] = {}
            prev_disk = psutil.disk_io_counters()
            last_t, last_log = time.time(), 0.0
            for p in psutil.process_iter(["cpu_percent"]):   # прогрев счётчиков CPU
                pass
            while not self._stop.wait(max(2, int(self.settings["mon_interval_s"]))):
                try:
                    now = time.time()
                    span = max(0.001, now - last_t)
                    last_t = now
                    sys_cpu = psutil.cpu_percent(None)
                    mem = psutil.virtual_memory().percent
                    disk = psutil.disk_io_counters()
                    disk_rate = 0.0
                    if disk and prev_disk:
                        disk_rate = max(0, (disk.read_bytes + disk.write_bytes)
                                        - (prev_disk.read_bytes + prev_disk.write_bytes)) / span
                    prev_disk = disk
                    procs, cur_io = [], {}
                    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info", "io_counters"],
                                                 ad_value=None):
                        i = p.info
                        if not i["pid"]:
                            continue          # «Бездействие системы»
                        io_rate = 0.0
                        ioc = i["io_counters"]
                        if ioc:
                            tot = ioc.read_bytes + ioc.write_bytes
                            cur_io[i["pid"]] = tot
                            prev = prev_io.get(i["pid"])
                            if prev is not None and tot >= prev:
                                io_rate = (tot - prev) / span
                        mi = i["memory_info"]
                        procs.append((i["name"] or f"pid {i['pid']}", i["pid"],
                                      (i["cpu_percent"] or 0.0) / ncpu, mi.rss if mi else 0, io_rate))
                    prev_io = cur_io

                    reasons = []
                    if sys_cpu >= self.settings["mon_cpu"]:
                        reasons.append("cpu")
                    if mem >= self.settings["mon_mem"]:
                        reasons.append("ram")
                    if disk_rate >= self.settings["mon_io_mb"] * MB:
                        reasons.append("disk")
                    logged = False
                    if reasons and self.settings["mon_enabled"] and now - last_log >= 30:
                        pick = {}
                        for x in sorted(procs, key=lambda x: x[2], reverse=True)[:5]:
                            pick[x[1]] = x
                        for x in sorted(procs, key=lambda x: x[3], reverse=True)[:5]:
                            pick[x[1]] = x
                        for x in sorted(procs, key=lambda x: x[4], reverse=True)[:3]:
                            if x[4] > 0:
                                pick[x[1]] = x
                        reason = ",".join(reasons)
                        con.executemany("INSERT INTO samples VALUES(?,?,?,?,?,?,?)",
                                        [(now, reason, n, pid, c, r, io) for n, pid, c, r, io in pick.values()])
                        con.commit()
                        last_log, logged = now, True
                    procs.sort(key=lambda x: x[2], reverse=True)
                    self.tick.emit({"cpu": sys_cpu, "mem": mem, "disk": disk_rate, "procs": procs,
                                    "reasons": reasons, "logged": logged})
                except Exception:
                    log.exception("Монитор процессов: ошибка шага")
        finally:
            con.close()


def top_offenders(db_path: Path, since: float) -> tuple[int, list[tuple]]:
    if not db_path.exists():
        return 0, []
    con = sqlite3.connect(str(db_path), timeout=5)
    try:
        con.execute("CREATE TABLE IF NOT EXISTS samples(ts REAL, reason TEXT, name TEXT, pid INTEGER,"
                    " cpu REAL, rss INTEGER, io REAL)")
        incidents = con.execute("SELECT COUNT(DISTINCT ts) FROM samples WHERE ts >= ?", (since,)).fetchone()[0]
        rows = con.execute(
            "SELECT name, COUNT(DISTINCT ts) AS hits, AVG(cpu), MAX(cpu), MAX(rss), MAX(io),"
            " GROUP_CONCAT(DISTINCT reason), MAX(ts) FROM samples WHERE ts >= ?"
            " GROUP BY name ORDER BY hits DESC, MAX(cpu) DESC LIMIT 80", (since,)).fetchall()
    finally:
        con.close()
    return incidents, rows


# ═══════════════════════════════════════════════════════════════════════════
#  GUI: общие элементы
# ═══════════════════════════════════════════════════════════════════════════
SORT_ROLE = Qt.ItemDataRole.UserRole + 1
DATA_ROLE = Qt.ItemDataRole.UserRole


class SortItem(QTableWidgetItem):
    def __lt__(self, other) -> bool:
        a, b = self.data(SORT_ROLE), other.data(SORT_ROLE)
        if a is None or b is None:
            return super().__lt__(other)
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


def cell(text, key=None, data=None, right=False, color: str | None = None, tip: str | None = None) -> SortItem:
    it = SortItem(str(text))
    if key is not None:
        it.setData(SORT_ROLE, key)
    if data is not None:
        it.setData(DATA_ROLE, data)
    if right:
        it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    if color:
        it.setForeground(QColor(color))
    if tip:
        it.setToolTip(tip)
    return it


def make_table(headers: list[str], sortable: bool = True) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(24)
    t.setAlternatingRowColors(True)
    t.setWordWrap(False)
    t.horizontalHeader().setStretchLastSection(True)
    t.horizontalHeader().setHighlightSections(False)
    t.setSortingEnabled(sortable)
    return t


def selected_rows(t: QTableWidget) -> list[int]:
    return sorted({i.row() for i in t.selectedIndexes()})


def mono_font() -> QFont:
    f = QFont("Cascadia Mono")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPointSize(9)
    return f


def make_icon(size: int = 64) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 64, size / 64)
    p.setBrush(QColor("#0d1117"))
    p.setPen(QPen(QColor(ACCENT), 3))
    p.drawRoundedRect(QRectF(3, 3, 58, 58), 12, 12)
    f = QFont("Consolas")
    f.setBold(True)
    f.setPixelSize(30)
    p.setFont(f)
    p.setPen(QColor(ACCENT))
    p.drawText(QRectF(0, 0, 64, 62), Qt.AlignmentFlag.AlignCenter, ">_")
    p.end()
    return QIcon(pm)


def apply_dark_theme(app: QApplication) -> None:
    app.setStyle(QStyleFactory.create("Fusion"))
    pal = QPalette()
    c = {
        QPalette.ColorRole.Window: "#0d1117", QPalette.ColorRole.WindowText: "#e6edf3",
        QPalette.ColorRole.Base: "#161b22", QPalette.ColorRole.AlternateBase: "#1b222c",
        QPalette.ColorRole.ToolTipBase: "#161b22", QPalette.ColorRole.ToolTipText: "#e6edf3",
        QPalette.ColorRole.Text: "#e6edf3", QPalette.ColorRole.Button: "#21262d",
        QPalette.ColorRole.ButtonText: "#e6edf3", QPalette.ColorRole.BrightText: BAD,
        QPalette.ColorRole.Highlight: "#1f6f43", QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.Link: ACCENT, QPalette.ColorRole.PlaceholderText: MUTED,
    }
    for role, col in c.items():
        pal.setColor(role, QColor(col))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor("#5a636e"))
    app.setPalette(pal)
    app.setStyleSheet(f"""
        QWidget {{ font-size: 9.5pt; }}
        QTabWidget::pane {{ border: 1px solid #30363d; border-radius: 6px; top: -1px; }}
        QTabBar::tab {{ background: #161b22; color: #9da7b3; padding: 7px 16px; border: 1px solid #30363d;
                        border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }}
        QTabBar::tab:selected {{ background: #0d1117; color: {ACCENT}; }}
        QPushButton, QToolButton {{ background: #21262d; border: 1px solid #30363d; border-radius: 6px; padding: 5px 12px; }}
        QPushButton:hover, QToolButton:hover {{ border-color: {ACCENT}; }}
        QPushButton:disabled {{ color: #5a636e; }}
        QPushButton#primary {{ background: #1f6f43; border-color: #2ea043; color: white; }}
        QGroupBox {{ border: 1px solid #30363d; border-radius: 6px; margin-top: 10px; padding-top: 8px; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {ACCENT}; }}
        QHeaderView::section {{ background: #161b22; color: #9da7b3; border: none;
                                border-right: 1px solid #30363d; border-bottom: 1px solid #30363d; padding: 4px 6px; }}
        QTableWidget {{ gridline-color: #21262d; border: 1px solid #30363d; border-radius: 6px; }}
        QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QListWidget {{ background: #161b22; border: 1px solid #30363d;
                                border-radius: 5px; padding: 3px 6px; }}
        QStatusBar {{ color: {MUTED}; }}
        QLabel#big {{ font-size: 13pt; font-weight: 600; }}
        QLabel#muted {{ color: {MUTED}; }}
    """)


def msg_info(parent, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)


def msg_warn(parent, title: str, text: str) -> None:
    QMessageBox.warning(parent, title, text)


def ask(parent, title: str, text: str) -> bool:
    return QMessageBox.question(parent, title, text) == QMessageBox.StandardButton.Yes


def admin_hint() -> str:
    return "" if is_admin() else "\n\nЧасть действий требует прав администратора — кнопка внизу окна."


# ═══════════════════════════════════════════════════════════════════════════
#  Вкладка 1 — Автозагрузка
# ═══════════════════════════════════════════════════════════════════════════
class StartupTab(QWidget):
    COLS = ["Сост.", "Название", "Тип", "Издатель", "Команда", "Где"]

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.items: list[StartupItem] = []
        self.journal = StartupJournal(DATA_DIR / "startup_journal.json")
        self._loaded = False

        self.btn_refresh = QPushButton("Обновить")
        self.btn_off = QPushButton("Отключить")
        self.btn_on = QPushButton("Включить")
        self.btn_loc = QPushButton("Открыть расположение")
        self.btn_journal = QPushButton("Журнал и откат…")
        self.filter = QLineEdit(placeholderText="Фильтр по названию, издателю, команде…")
        top = QHBoxLayout()
        for b in (self.btn_refresh, self.btn_off, self.btn_on, self.btn_loc, self.btn_journal):
            top.addWidget(b)
        top.addWidget(self.filter, 1)

        self.table = make_table(self.COLS)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(1, 230)
        self.table.setColumnWidth(2, 95)
        self.table.setColumnWidth(3, 170)
        self.table.setColumnWidth(4, 360)
        self.table.doubleClicked.connect(self.open_location)

        self.status = QLabel("Нажмите «Обновить».", objectName="muted")
        hint = QLabel("Отключение не удаляет программы: пункт остаётся на месте и включается обратно "
                      "одной кнопкой. Службы переводятся в ручной запуск, а не отключаются.",
                      objectName="muted", wordWrap=True)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.status)
        lay.addWidget(hint)

        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_off.clicked.connect(lambda: self.toggle(False))
        self.btn_on.clicked.connect(lambda: self.toggle(True))
        self.btn_loc.clicked.connect(self.open_location)
        self.btn_journal.clicked.connect(self.show_journal)
        self.filter.textChanged.connect(self.apply_filter)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if not self._loaded:
            self._loaded = True
            self.refresh()

    def _busy(self, busy: bool) -> None:
        for b in (self.btn_refresh, self.btn_off, self.btn_on, self.btn_journal):
            b.setEnabled(not busy)

    def refresh(self) -> None:
        self._busy(True)
        self.status.setText("Сканирую…")
        modes = self.journal.service_restore_modes()
        run_async(self, lambda report: scan_startup(modes, report), self._on_scanned,
                  self._on_fail, self.status.setText)

    def _on_fail(self, msg: str) -> None:
        self._busy(False)
        self.status.setText(f"Ошибка: {msg}")

    def _on_scanned(self, res) -> None:
        self._busy(False)
        self.items, errors = res
        self.fill()
        on = sum(1 for i in self.items if i.enabled)
        txt = f"Всего {len(self.items)}, включено {on}."
        if errors:
            txt += "  Не удалось прочитать: " + "; ".join(e.splitlines()[0][:120] for e in errors)
        self.status.setText(txt)

    def fill(self) -> None:
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(self.items))
        order = {"reg": 0, "folder": 1, "task": 2, "service": 3}
        for r, it in enumerate(self.items):
            fg = None if it.enabled else MUTED
            t.setItem(r, 0, cell("вкл" if it.enabled else "выкл", key=int(not it.enabled), data=r,
                                 color=ACCENT if it.enabled else MUTED))
            t.setItem(r, 1, cell(it.name, key=it.name.lower(), color=fg, tip=it.name))
            t.setItem(r, 2, cell(KIND_TITLES[it.kind], key=order[it.kind], color=fg))
            t.setItem(r, 3, cell(it.publisher or "—", key=(it.publisher or "~").lower(), color=fg))
            t.setItem(r, 4, cell(it.command, color=fg, tip=it.command))
            t.setItem(r, 5, cell(it.location, color=fg, tip=it.location))
        t.setSortingEnabled(True)
        self.apply_filter()

    def apply_filter(self) -> None:
        q = self.filter.text().strip().lower()
        for r in range(self.table.rowCount()):
            it = self.items[self.table.item(r, 0).data(DATA_ROLE)]
            hay = f"{it.name} {it.publisher} {it.command} {it.location}".lower()
            self.table.setRowHidden(r, bool(q) and q not in hay)

    def _selected_items(self) -> list[StartupItem]:
        return [self.items[self.table.item(r, 0).data(DATA_ROLE)] for r in selected_rows(self.table)]

    def toggle(self, enable: bool) -> None:
        sel = [i for i in self._selected_items() if i.enabled != enable]
        if not sel:
            return
        if not enable and any(i.kind == "service" for i in sel):
            if not ask(self, "Службы", "Выбранные службы будут переведены в ручной запуск. "
                                        "Если программа без них работает некорректно — включите обратно. Продолжить?"):
                return
        self._busy(True)

        def work(_report):
            ok, fail = [], []
            for it in sel:
                try:
                    set_startup_enabled(it, enable)
                    ok.append(it)
                except PermissionError:
                    fail.append(f"{it.name}: нужны права администратора")
                except Exception as e:
                    fail.append(f"{it.name}: {str(e).splitlines()[0] if str(e) else type(e).__name__}")
            return ok, fail

        def done(res):
            ok, fail = res
            for it in ok:
                self.journal.add(it, it.enabled, enable)
            if fail:
                msg_warn(self, "Не всё получилось", "\n".join(fail[:15]) + admin_hint())
            self.refresh()

        run_async(self, work, done, self._on_fail)

    def open_location(self, *_a) -> None:
        sel = self._selected_items()
        if not sel:
            return
        it = sel[0]
        if it.target and os.path.exists(it.target):
            explorer_select(it.target)
        elif it.kind == "task":
            os.startfile("taskschd.msc")
        elif it.kind == "service":
            os.startfile("services.msc")
        elif it.kind == "reg":
            msg_info(self, "Расположение", f"{it.location}\nЗначение: {it.name}\n\n{it.command}")

    def show_journal(self) -> None:
        JournalDialog(self).exec()

    def rollback(self, entries: list[dict]) -> None:
        todo = [e for e in reversed(entries) if not e.get("rolled_back")]
        if not todo:
            return
        self._busy(True)

        def work(_report):
            fail = []
            for e in todo:
                it = StartupItem(e["kind"], e["name"], "", e["now"], e["location"], ref=e["ref"])
                try:
                    set_startup_enabled(it, e["was"])
                    e["rolled_back"] = True
                except PermissionError:
                    fail.append(f"{e['name']}: нужны права администратора")
                except Exception as ex:
                    fail.append(f"{e['name']}: {ex}")
            return fail

        def done(fail):
            self.journal.save()
            if fail:
                msg_warn(self, "Откат", "\n".join(fail[:15]) + admin_hint())
            self.refresh()

        run_async(self, work, done, self._on_fail)


class JournalDialog(QDialog):
    def __init__(self, tab: StartupTab):
        super().__init__(tab)
        self.tab = tab
        self.setWindowTitle("Журнал изменений автозагрузки")
        self.resize(900, 460)
        self.table = make_table(["Когда", "Действие", "Пункт", "Где", "Статус"], sortable=False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        b_sel = QPushButton("Откатить выбранное")
        b_all = QPushButton("Откатить всё")
        b_close = QPushButton("Закрыть")
        row = QHBoxLayout()
        row.addWidget(b_sel)
        row.addWidget(b_all)
        row.addStretch(1)
        row.addWidget(b_close)
        lay = QVBoxLayout(self)
        lay.addWidget(self.table, 1)
        lay.addLayout(row)
        b_close.clicked.connect(self.accept)
        b_sel.clicked.connect(self.rollback_selected)
        b_all.clicked.connect(self.rollback_all)
        self.fill()

    def fill(self) -> None:
        ent = list(reversed(self.tab.journal.entries))
        self.table.setRowCount(len(ent))
        for r, e in enumerate(ent):
            act = "включено" if e["now"] else "отключено"
            st = "откачено" if e.get("rolled_back") else "действует"
            self.table.setItem(r, 0, cell(e["ts"].replace("T", " "), data=e))
            self.table.setItem(r, 1, cell(act, color=ACCENT if e["now"] else WARN))
            self.table.setItem(r, 2, cell(e["name"]))
            self.table.setItem(r, 3, cell(e["location"]))
            self.table.setItem(r, 4, cell(st, color=MUTED if e.get("rolled_back") else None))
        self.table.resizeColumnsToContents()

    def rollback_selected(self) -> None:
        rows = selected_rows(self.table)
        ent = list(reversed(self.tab.journal.entries))
        chosen = [ent[r] for r in rows]
        chosen.sort(key=lambda e: self.tab.journal.entries.index(e))
        if chosen:
            self.tab.rollback(chosen)
            self.accept()

    def rollback_all(self) -> None:
        if ask(self, "Откат", "Вернуть все изменения автозагрузки в исходное состояние?"):
            self.tab.rollback(self.tab.journal.entries)
            self.accept()


# ═══════════════════════════════════════════════════════════════════════════
#  Вкладка 2 — Очистка
# ═══════════════════════════════════════════════════════════════════════════
class CleanTab(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.s = win.settings
        self.targets = build_clean_targets()
        self._busy_flag = False

        self.table = make_table(["", "Категория", "Найдено", "Файлов", "Примечание"], sortable=False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(1, 300)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 80)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.doubleClicked.connect(self.show_details)

        self.btn_scan = QPushButton("Сканировать")
        self.btn_clean = QPushButton("Очистить отмеченное", objectName="primary")
        self.btn_details = QPushButton("Подробнее…")
        self.btn_dism = QPushButton("Сжать хранилище компонентов (DISM)")
        self.total = QLabel("", objectName="big")
        top = QHBoxLayout()
        for b in (self.btn_scan, self.btn_clean, self.btn_details):
            top.addWidget(b)
        top.addStretch(1)
        top.addWidget(self.total)

        self.roots = QLineEdit("; ".join(from_portable_path(x) for x in self.s["clean_roots"]))
        self.roots.setToolTip("В настройках пути хранятся переносимо: внутри Launcher — относительно его папки, "
                              "в профиле — через %USERPROFILE%.")
        b_add = QPushButton("Добавить папку…")
        self.sp_age = QSpinBox(minimum=0, maximum=24 * 30, suffix=" ч", value=int(self.s["temp_min_age_h"]))
        self.sp_venv = QSpinBox(minimum=7, maximum=3650, suffix=" дн.", value=int(self.s["venv_days"]))
        box = QGroupBox("Параметры")
        g = QGridLayout(box)
        g.addWidget(QLabel("Папки с проектами (для __pycache__ и venv):"), 0, 0)
        g.addWidget(self.roots, 0, 1)
        g.addWidget(b_add, 0, 2)
        g.addWidget(QLabel("Временные файлы старше:"), 1, 0)
        r2 = QHBoxLayout()
        r2.addWidget(self.sp_age)
        r2.addSpacing(20)
        r2.addWidget(QLabel("venv считается заброшенным, если проект не менялся:"))
        r2.addWidget(self.sp_venv)
        r2.addStretch(1)
        r2.addWidget(self.btn_dism)
        g.addLayout(r2, 1, 1, 1, 2)

        self.status = QLabel("Нажмите «Сканировать» — ничего не удаляется без подтверждения.", objectName="muted")
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.table, 1)
        lay.addWidget(box)
        lay.addWidget(self.status)

        self.btn_scan.clicked.connect(self.scan)
        self.btn_clean.clicked.connect(self.clean)
        self.btn_details.clicked.connect(self.show_details)
        self.btn_dism.clicked.connect(self.run_dism)
        b_add.clicked.connect(self.add_root)
        self.roots.editingFinished.connect(self._save_params)
        self.sp_age.valueChanged.connect(self._save_params)
        self.sp_venv.valueChanged.connect(self._save_params)
        self.fill()

    def _save_params(self) -> None:
        self.s.data["clean_roots"] = [to_portable_path(x.strip()) for x in self.roots.text().split(";") if x.strip()]
        self.s.data["temp_min_age_h"] = self.sp_age.value()
        self.s["venv_days"] = self.sp_venv.value()

    def add_root(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Папка с проектами")
        if d:
            roots = [x.strip() for x in self.roots.text().split(";") if x.strip()]
            roots.append(os.path.normpath(d))
            self.roots.setText("; ".join(roots))
            self._save_params()

    def _checked_keys(self) -> set[str]:
        st = self.s["clean_checked"]
        return {t.key for t in self.targets if st.get(t.key, t.default_on)}

    def fill(self) -> None:
        t = self.table
        t.blockSignals(True)
        t.setRowCount(len(self.targets))
        checked = self._checked_keys()
        adm = is_admin()
        for r, tg in enumerate(self.targets):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            chk.setCheckState(Qt.CheckState.Checked if tg.key in checked else Qt.CheckState.Unchecked)
            t.setItem(r, 0, chk)
            t.setItem(r, 1, cell(tg.title))
            if tg.scanned:
                size_txt, cnt_txt = human_size(tg.size), f"{tg.count:,}".replace(",", " ")
            else:
                size_txt, cnt_txt = "—", "—"
            col = ACCENT if tg.scanned and tg.size > 200 * MB else None
            t.setItem(r, 2, cell(size_txt, right=True, color=col))
            t.setItem(r, 3, cell(cnt_txt, right=True))
            note = tg.note
            if tg.admin and not adm:
                note += " · часть требует прав администратора"
            if tg.error:
                note = f"ошибка: {tg.error}"
            t.setItem(r, 4, cell(note, color=BAD if tg.error else MUTED, tip=note))
        t.blockSignals(False)
        self.update_total()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        st = dict(self.s["clean_checked"])
        st[self.targets[item.row()].key] = item.checkState() == Qt.CheckState.Checked
        self.s["clean_checked"] = st
        self.update_total()

    def update_total(self) -> None:
        keys = self._checked_keys()
        sel = [t for t in self.targets if t.key in keys and t.scanned]
        if sel:
            self.total.setText(f"К очистке: {human_size(sum(t.size for t in sel))}")
        else:
            self.total.setText("")

    def _busy(self, busy: bool) -> None:
        self._busy_flag = busy
        for b in (self.btn_scan, self.btn_clean, self.btn_dism):
            b.setEnabled(not busy)

    def _row_status(self, key: str, text: str) -> None:
        for r, t in enumerate(self.targets):
            if t.key == key:
                self.table.item(r, 2).setText(text)

    def _progress(self, ev) -> None:
        kind, key = ev
        if kind == "start":
            self._row_status(key, "…")
            title = next(t.title for t in self.targets if t.key == key)
            self.status.setText(f"{title}…")

    def scan(self) -> None:
        self._save_params()
        self._busy(True)
        ctx = {"roots": [from_portable_path(x) for x in self.s["clean_roots"]], "temp_age": self.s["temp_min_age_h"],
               "venv_days": self.s["venv_days"], "_dev": None}
        targets = self.targets
        run_async(self, lambda report: scan_targets(targets, ctx, report), self._scanned,
                  self._fail, self._progress)

    def _scanned(self, _res) -> None:
        self._busy(False)
        self.fill()
        total = sum(t.size for t in self.targets if t.scanned)
        self.status.setText(f"Скан завершён. Всего найдено {human_size(total)}. "
                            "Отметьте категории и нажмите «Очистить отмеченное».")

    def _fail(self, msg: str) -> None:
        self._busy(False)
        self.status.setText(f"Ошибка: {msg}")

    def clean(self) -> None:
        keys = self._checked_keys()
        sel = [t for t in self.targets if t.key in keys and t.scanned and (t.items or t.key == "recycle")]
        if not sel:
            msg_info(self, "Очистка", "Сначала просканируйте, затем отметьте непустые категории.")
            return
        running = running_process_names()
        busy_browsers = sorted({p for t in sel for p in t.warn_procs if p in running})
        text = "Будет удалено:\n\n" + "\n".join(f"• {t.title} — {human_size(t.size)}" for t in sel)
        if busy_browsers:
            text += f"\n\nЗапущены браузеры ({', '.join(busy_browsers)}): часть их кэша не удалится."
        if any(t.key == "venv" for t in sel):
            text += "\n\nВиртуальные окружения удаляются целиком — потом их можно пересоздать из requirements."
        if not ask(self, "Подтвердите очистку", text + "\n\nПродолжить?"):
            return
        self._busy(True)
        run_async(self, lambda report: clean_selected(sel, report), self._cleaned, self._fail, self._progress)

    def _cleaned(self, res: dict) -> None:
        freed = sum(f for f, _e in res.values())
        errs = sum(e for _f, e in res.values())
        msg = f"Освобождено {human_size(freed)}."
        if errs:
            msg += f" Пропущено занятых/защищённых объектов: {errs}."
        self.status.setText(msg + " Пересканирую…")
        self.scan()

    def show_details(self, *_a) -> None:
        rows = selected_rows(self.table)
        if not rows:
            return
        tg = self.targets[rows[0]]
        if not tg.scanned or not tg.items:
            msg_info(self, tg.title, "Нет данных: категория пуста или ещё не сканировалась.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(tg.title)
        dlg.resize(980, 520)
        tbl = make_table(["Путь", "Размер", "Файлов", "Примечание"])
        items = tg.items[:2000]
        tbl.setSortingEnabled(False)
        tbl.setRowCount(len(items))
        for r, (p, sz, n, note) in enumerate(items):
            tbl.setItem(r, 0, cell(str(p), key=str(p).lower(), data=str(p), tip=str(p)))
            tbl.setItem(r, 1, cell(human_size(sz), key=sz, right=True))
            tbl.setItem(r, 2, cell(n, key=n, right=True))
            tbl.setItem(r, 3, cell(note))
        tbl.setSortingEnabled(True)
        tbl.setColumnWidth(0, 600)
        tbl.doubleClicked.connect(lambda idx: explorer_select(tbl.item(idx.row(), 0).data(DATA_ROLE)))
        lay = QVBoxLayout(dlg)
        extra = f" (показаны первые {len(items)})" if len(tg.items) > len(items) else ""
        lay.addWidget(QLabel(f"{len(tg.items)} объектов, {human_size(tg.size)}{extra}. "
                             "Двойной щелчок — показать в проводнике.", objectName="muted"))
        lay.addWidget(tbl, 1)
        dlg.exec()

    def run_dism(self) -> None:
        if not is_admin():
            msg_warn(self, "DISM", "Нужны права администратора." + admin_hint())
            return
        if not ask(self, "DISM", "Очистка хранилища компонентов WinSxS занимает 5–30 минут, "
                                 "ноутбук лучше подключить к сети. Запустить?"):
            return
        self._busy(True)
        self.status.setText("DISM работает, это надолго…")

        def done(res):
            self._busy(False)
            code, out = res
            self.status.setText("DISM завершён." if code == 0 else f"DISM: код {code}")
            OutputDialog(self, "DISM", out).exec()

        run_async(self, lambda _r: run_cmd(["Dism.exe", "/Online", "/Cleanup-Image",
                                            "/StartComponentCleanup"], 3600), done, self._fail)


class OutputDialog(QDialog):
    def __init__(self, parent, title: str, text: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 480)
        ed = QPlainTextEdit(text, readOnly=True)
        ed.setFont(mono_font())
        b = QPushButton("Закрыть")
        b.clicked.connect(self.accept)
        lay = QVBoxLayout(self)
        lay.addWidget(ed, 1)
        lay.addWidget(b, alignment=Qt.AlignmentFlag.AlignRight)


# ═══════════════════════════════════════════════════════════════════════════
#  Вкладка 3 — Питание
# ═══════════════════════════════════════════════════════════════════════════
class PowerTab(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.s = win.settings
        self.pm: PowerManager = win.power

        self.lbl_state = QLabel("", objectName="big")
        self.lbl_active = QLabel("", objectName="muted")
        b_refresh = QPushButton("Обновить")
        b_hidden = QPushButton("Добавить скрытые схемы")
        b_cpl = QPushButton("Электропитание Windows")
        head = QHBoxLayout()
        vv = QVBoxLayout()
        vv.addWidget(self.lbl_state)
        vv.addWidget(self.lbl_active)
        head.addLayout(vv, 1)
        for b in (b_refresh, b_hidden, b_cpl):
            head.addWidget(b)

        self.chk_auto = QCheckBox("Автопереключение (работает, пока программа запущена — в том числе в трее)")
        self.chk_auto.setChecked(bool(self.s["power_auto"]))
        self.cb_ac, self.cb_dc, self.cb_now = QComboBox(), QComboBox(), QComboBox()
        b_apply = QPushButton("Применить сейчас")
        form = QGroupBox("Правила")
        fl = QFormLayout(form)
        fl.addRow(self.chk_auto)
        fl.addRow("От сети:", self.cb_ac)
        fl.addRow("От батареи:", self.cb_dc)
        now_row = QHBoxLayout()
        now_row.addWidget(self.cb_now, 1)
        now_row.addWidget(b_apply)
        fl.addRow("Вручную:", now_row)

        self.rules = make_table(["Процесс (.exe)", "Профиль, пока процесс запущен"], sortable=False)
        self.rules.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self.rules.setColumnWidth(0, 240)
        b_add_run = QPushButton("Добавить из запущенных…")
        b_add = QPushButton("Добавить вручную")
        b_del = QPushButton("Удалить")
        rules_box = QGroupBox("Профили для программ (приоритетнее правил выше; сверху вниз)")
        rl = QVBoxLayout(rules_box)
        rl.addWidget(self.rules, 1)
        rb = QHBoxLayout()
        for b in (b_add_run, b_add, b_del):
            rb.addWidget(b)
        rb.addStretch(1)
        rl.addLayout(rb)

        self.events = QListWidget()
        self.events.setFont(mono_font())
        ev_box = QGroupBox("Журнал переключений")
        QVBoxLayout(ev_box).addWidget(self.events)

        if self.pm.has_overlay:
            note_text = ("<b>Режим</b> — ползунок Windows (Параметры → Система → Питание). Работает поверх схемы "
                         "«Сбалансированная»; на современных ноутбуках именно к нему привязаны разгон процессора "
                         "и профили вентиляторов. Рекомендуется: от сети — «Режим: Максимальная производительность», "
                         "от батареи — «Режим: Сбалансированный» или «Энергоэффективность».<br>"
                         "<b>Схема</b> — полный набор настроек из Панели управления. «Высокая производительность» "
                         "держит частоту процессора высокой даже в простое — ноутбук сильнее греется и быстрее "
                         "разряжается; пока выбрана не «Сбалансированная», ползунок Windows недоступен.")
        else:
            note_text = ("Режимы-ползунок Windows на этой системе недоступны — переключаются только схемы. "
                         "Если нужной схемы нет в списке — «Добавить скрытые схемы».")
        note = QLabel(note_text, objectName="muted", wordWrap=True)
        note.setTextFormat(Qt.TextFormat.RichText)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(form)
        ll.addWidget(rules_box, 1)
        split.addWidget(left)
        split.addWidget(ev_box)
        split.setSizes([640, 380])

        lay = QVBoxLayout(self)
        lay.addLayout(head)
        lay.addWidget(split, 1)
        lay.addWidget(note)

        for line in self.pm.history:
            self.events.addItem(line)
        self.fill_combos()
        self.fill_rules()

        self.pm.event.connect(self._on_event)
        b_refresh.clicked.connect(self.refresh)
        b_hidden.clicked.connect(self.add_hidden)
        b_cpl.clicked.connect(lambda: os.startfile("powercfg.cpl") if IS_WIN else None)
        b_apply.clicked.connect(self.apply_now)
        self.chk_auto.toggled.connect(self._auto_toggled)
        self.cb_ac.currentIndexChanged.connect(self._save_combos)
        self.cb_dc.currentIndexChanged.connect(self._save_combos)
        b_add_run.clicked.connect(self.add_from_running)
        b_add.clicked.connect(lambda: self.add_rule(""))
        b_del.clicked.connect(self.del_rule)
        self.rules.itemChanged.connect(lambda _i: self.save_rules())

        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self.update_state)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.update_state()
        self.ui_timer.start(10_000)

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self.ui_timer.stop()

    def _fill_combo(self, cb: QComboBox, current: str, with_none: bool) -> None:
        """Сначала режимы-ползунок, черта, затем схемы; подписи с префиксом, подсказки на пунктах."""
        cb.blockSignals(True)
        cb.clear()
        if with_none:
            cb.addItem("— не менять —", "")
        groups = [
            [(pid, f"Режим: {n}", MODE_TIPS.get(pid.split(":", 1)[1], "")) for pid, n in self.pm.mode_items()],
            [(pid, f"Схема: {n}", PLAN_TIP) for pid, n in self.pm.plan_items()],
        ]
        for group in groups:
            if not group:
                continue
            if cb.count():
                cb.insertSeparator(cb.count())
            for pid, text, tip in group:
                cb.addItem(text, pid)
                cb.setItemData(cb.count() - 1, tip, Qt.ItemDataRole.ToolTipRole)
        i = cb.findData(current)
        if i < 0 and current:          # в настройках профиль, которого в системе уже нет
            cb.addItem(f"⚠ нет в системе: {current}", current)
            i = cb.count() - 1
        cb.setMinimumContentsLength(30)
        cb.setCurrentIndex(max(0, i))
        cb.blockSignals(False)

    def fill_combos(self) -> None:
        self._fill_combo(self.cb_ac, self.s["power_ac"], True)
        self._fill_combo(self.cb_dc, self.s["power_dc"], True)
        self._fill_combo(self.cb_now, self.pm.current_profile()[0] or "", False)

    def fill_rules(self) -> None:
        self.rules.blockSignals(True)
        rules = self.s["power_rules"]
        self.rules.setRowCount(len(rules))
        for r, rule in enumerate(rules):
            self.rules.setItem(r, 0, QTableWidgetItem(rule.get("process", "")))
            cb = QComboBox()
            self._fill_combo(cb, rule.get("profile", ""), True)
            cb.currentIndexChanged.connect(lambda _i: self.save_rules())
            self.rules.setCellWidget(r, 1, cb)
        self.rules.blockSignals(False)

    def save_rules(self) -> None:
        rules = []
        for r in range(self.rules.rowCount()):
            it = self.rules.item(r, 0)
            cb = self.rules.cellWidget(r, 1)
            proc = (it.text().strip() if it else "")
            if proc and not proc.lower().endswith(".exe"):
                proc += ".exe"
            rules.append({"process": proc, "profile": cb.currentData() if cb else ""})
        self.s["power_rules"] = rules
        self.pm.apply_settings()

    def add_rule(self, proc: str) -> None:
        rules = list(self.s["power_rules"])
        rules.append({"process": proc, "profile": ""})
        self.s["power_rules"] = rules
        self.fill_rules()
        if not proc:
            self.rules.editItem(self.rules.item(len(rules) - 1, 0))

    def add_from_running(self) -> None:
        names = sorted(running_process_names())
        if not names:
            return
        name, ok = QInputDialog.getItem(self, "Процесс", "Выберите программу:", names, 0, True)
        if ok and name.strip():
            self.add_rule(name.strip())

    def del_rule(self) -> None:
        rows = selected_rows(self.rules)
        if not rows:
            return
        rules = [r for i, r in enumerate(self.s["power_rules"]) if i not in rows]
        self.s["power_rules"] = rules
        self.fill_rules()
        self.pm.apply_settings()

    def _save_combos(self) -> None:
        self.s.data["power_ac"] = self.cb_ac.currentData() or ""
        self.s["power_dc"] = self.cb_dc.currentData() or ""
        self.pm.apply_settings()

    def _auto_toggled(self, on: bool) -> None:
        self.s["power_auto"] = on
        self.pm.apply_settings()
        self.win.update_tray_menu()

    def _on_event(self, line: str) -> None:
        self.events.insertItem(0, line)
        while self.events.count() > 300:
            self.events.takeItem(self.events.count() - 1)
        self.update_state()

    def apply_now(self) -> None:
        pid = self.cb_now.currentData()
        if not pid:
            return
        try:
            self.pm.apply_profile(pid)
            self.pm._emit(f"вручную → {self.pm.profile_name(pid)}")
        except Exception as e:
            msg_warn(self, "Питание", str(e))

    def refresh(self) -> None:
        self.pm.refresh_plans()
        self.fill_combos()
        self.fill_rules()
        self.update_state()

    def add_hidden(self) -> None:
        msg_info(self, "Схемы питания", self.pm.add_hidden_plans())
        self.refresh()
        self.win.update_tray_menu()

    def update_state(self) -> None:
        on_ac, pct, has_batt = power_status()
        if on_ac is None:
            src = "Питание: неизвестно"
        else:
            src = "От сети" if on_ac else "От батареи"
        if has_batt and pct is not None:
            src += f" · заряд {pct}%"
        self.lbl_state.setText(src)
        act = self.pm.active_plan()
        plan = dict(self.pm.plan_items()).get(f"plan:{act}", act or "—")
        cur = f"plan:{act}" if act else ""
        if self.pm.has_overlay and act == BALANCED:
            try:
                ov = get_overlay()
            except Exception:
                ov = None
            if ov in OVERLAY_MODES:
                cur = f"mode:{ov}"
            now = f"Сейчас: режим «{OVERLAY_MODES.get(ov, 'нестандартный')}» (схема «{plan}»)"
        elif self.pm.has_overlay:
            now = f"Сейчас: схема «{plan}» — ползунок режима Windows при ней не действует"
        else:
            now = f"Сейчас: схема «{plan}»"
        i = self.cb_now.findData(cur)
        if i >= 0 and not self.cb_now.view().isVisible():
            self.cb_now.setCurrentIndex(i)          # «Вручную» показывает то, что действует сейчас
        auto = "автопереключение " + ("включено" if self.s["power_auto"] else "выключено")
        self.lbl_active.setText(f"{now}  ·  {auto}")


# ═══════════════════════════════════════════════════════════════════════════
#  Вкладка 4 — Батарея и сон
# ═══════════════════════════════════════════════════════════════════════════
class WearChart(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(220)
        self.points: list[tuple[str, float]] = []

    def set_points(self, pts: list[tuple[str, float]]) -> None:
        self.points = pts
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#161b22"))
        r = QRectF(self.rect()).adjusted(52, 18, -20, -30)
        p.setPen(QColor(MUTED))
        if not self.points:
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Нет данных — нажмите «Снять показания».")
            return
        vals = [v for _d, v in self.points]
        lo = min(80.0, (int(min(vals)) // 10) * 10.0)
        hi = max(105.0, max(vals) + 3)
        dates = [dt.date.fromisoformat(d) for d, _v in self.points]
        d0, d1 = dates[0].toordinal(), dates[-1].toordinal()

        def X(d: dt.date) -> float:
            return r.center().x() if d1 == d0 else r.left() + (d.toordinal() - d0) / (d1 - d0) * r.width()

        def Y(v: float) -> float:
            return r.bottom() - (v - lo) / (hi - lo) * r.height()

        grid = QPen(QColor("#2a313a"))
        for g in range(int(lo), int(hi) + 1, 10):
            p.setPen(grid)
            p.drawLine(int(r.left()), int(Y(g)), int(r.right()), int(Y(g)))
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(0, Y(g) - 9, 46, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{g}%")
        p.drawText(QRectF(r.left(), r.bottom() + 6, 140, 18), Qt.AlignmentFlag.AlignLeft, f"{dates[0]:%d.%m.%Y}")
        p.drawText(QRectF(r.right() - 140, r.bottom() + 6, 140, 18), Qt.AlignmentFlag.AlignRight,
                   f"{dates[-1]:%d.%m.%Y}")
        path = QPainterPath()
        for i, (d, v) in enumerate(zip(dates, vals)):
            (path.moveTo if i == 0 else path.lineTo)(X(d), Y(v))
        p.setPen(QPen(QColor(ACCENT), 2))
        p.drawPath(path)
        p.setBrush(QColor(ACCENT))
        for d, v in zip(dates, vals):
            p.drawEllipse(QRectF(X(d) - 3, Y(v) - 3, 6, 6))
        last = vals[-1]
        p.setPen(QColor("#e6edf3"))
        p.drawText(QRectF(X(dates[-1]) - 70, Y(last) - 24, 66, 18),
                   Qt.AlignmentFlag.AlignRight, f"{last:.1f}%")


class BatteryTab(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.s = win.settings
        self._report_hist: list[dict] = []

        self.lbl_health = QLabel("—", objectName="big")
        self.lbl_info = QLabel("", objectName="muted", wordWrap=True)
        self.chart = WearChart()
        b_snap = QPushButton("Снять показания")
        b_html = QPushButton("Полный HTML-отчёт")
        top = QHBoxLayout()
        vv = QVBoxLayout()
        vv.addWidget(self.lbl_health)
        vv.addWidget(self.lbl_info)
        top.addLayout(vv, 1)
        top.addWidget(b_snap)
        top.addWidget(b_html)
        bat_box = QGroupBox("Батарея: здоровье = текущая полная ёмкость / проектная")
        bl = QVBoxLayout(bat_box)
        bl.addLayout(top)
        bl.addWidget(self.chart, 1)

        sleep_box = QGroupBox("Сон и пробуждение")
        sl = QGridLayout(sleep_box)
        buttons = [
            ("Кто мешает уснуть", ["powercfg", "/requests"], "Нужны права администратора."),
            ("Что разбудило последним", ["powercfg", "/lastwake"], ""),
            ("Таймеры пробуждения", ["powercfg", "/waketimers"], ""),
            ("Устройства, которые могут будить", ["powercfg", "/devicequery", "wake_armed"], ""),
        ]
        for i, (title, cmd, tip) in enumerate(buttons):
            b = QPushButton(title)
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(lambda _c=False, c=cmd, t=title: self.run_diag(t, c))
            sl.addWidget(b, i // 2, i % 2)
        b_dis = QPushButton("Запретить выбранному устройству будить")
        b_study = QPushButton("Sleep Study (HTML)")
        sl.addWidget(b_dis, 2, 0)
        sl.addWidget(b_study, 2, 1)
        self.out = QPlainTextEdit(readOnly=True)
        self.out.setFont(mono_font())
        self.out.setPlaceholderText("Результат команды появится здесь. Для запрета пробуждения выделите "
                                    "строку с именем устройства после «Устройства, которые могут будить».")
        sl.addWidget(self.out, 3, 0, 1, 2)
        sl.setRowStretch(3, 1)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(bat_box)
        split.addWidget(sleep_box)
        split.setSizes([360, 340])
        lay = QVBoxLayout(self)
        lay.addWidget(split)

        b_snap.clicked.connect(lambda: self.snapshot(quiet=False))
        b_html.clicked.connect(self.open_html)
        b_dis.clicked.connect(self.disable_wake)
        b_study.clicked.connect(self.sleep_study)
        self.show_points()

    def show_points(self) -> None:
        own = load_own_battery_history()
        self.chart.set_points(merge_battery_points(self._report_hist, own))
        if own and not self._report_hist:
            last = own[-1]
            self._set_health(last["design"], last["full"], last.get("cycles", 0), last["date"])

    def _set_health(self, design: int, full: int, cycles: int, when: str) -> None:
        if design <= 0:
            return
        h = 100.0 * full / design
        col = ACCENT if h >= 80 else WARN if h >= 60 else BAD
        self.lbl_health.setText(f"Здоровье батареи: <span style='color:{col}'>{h:.1f}%</span>"
                                f"  ·  износ {max(0.0, 100 - h):.1f}%")
        def num(v: int) -> str:
            return f"{v:,}".replace(",", " ")
        txt = f"Проектная ёмкость {num(design)} мВт·ч, сейчас {num(full)} мВт·ч"
        if cycles:
            txt += f", циклов зарядки: {cycles}"
        txt += f". Замер: {when}."
        self.lbl_info.setText(txt)

    def auto_snapshot(self) -> None:
        own = load_own_battery_history()
        snaps = [h for h in own if h.get("source") == "snapshot"]
        if snaps:
            try:
                last = dt.date.fromisoformat(snaps[-1]["date"])
                if (dt.date.today() - last).days < int(self.s["battery_auto_days"]):
                    return
            except ValueError:
                pass
        _on_ac, _pct, has_batt = power_status()
        if has_batt:
            self.snapshot(quiet=True)

    def snapshot(self, quiet: bool) -> None:
        def done(data):
            self._report_hist = data["history"]
            b = data["batteries"]
            design, full = sum(x["design"] for x in b), sum(x["full"] for x in b)
            self._set_health(design, full, max(x["cycles"] for x in b), dt.date.today().isoformat())
            extra = ", ".join(filter(None, [b[0].get("manufacturer"), b[0].get("id"), b[0].get("chemistry")]))
            if extra:
                self.lbl_info.setText(self.lbl_info.text() + f"  {extra}")
            self.show_points()

        def fail(msg):
            if not quiet:
                msg_warn(self, "Батарея", msg)
            else:
                log.warning("Автозамер батареи: %s", msg)

        run_async(self, battery_snapshot, done, fail)

    def open_html(self) -> None:
        path = DATA_DIR / "battery_report.html"

        def done(res):
            code, out = res
            if code == 0 and path.exists():
                os.startfile(str(path))
            else:
                msg_warn(self, "Батарея", out)

        run_async(self, lambda _r: run_cmd(["powercfg", "/batteryreport", "/output", str(path)], 120), done)

    def run_diag(self, title: str, cmd: list[str]) -> None:
        self.out.setPlainText(f"{title}…")

        def done(res):
            code, out = res
            txt = f"> {' '.join(cmd)}\n\n{out or '(пусто)'}"
            if code != 0 and not is_admin():
                txt += "\n\nВозможно, нужны права администратора."
            self.out.setPlainText(txt)

        run_async(self, lambda _r: run_cmd(cmd, 60), done)

    def disable_wake(self) -> None:
        name = self.out.textCursor().selectedText().strip()
        if not name:
            line = self.out.textCursor().block().text().strip()
            name = line
        if not name or name.startswith(">"):
            msg_info(self, "Пробуждение", "Сначала нажмите «Устройства, которые могут будить» и "
                                          "поставьте курсор на строку с нужным устройством.")
            return
        if not ask(self, "Пробуждение", f"Запретить устройству будить компьютер?\n\n{name}"):
            return
        code, out = run_cmd(["powercfg", "/devicedisablewake", name], 30)
        if code == 0:
            msg_info(self, "Пробуждение", "Готово. Вернуть: powercfg /deviceenablewake \"имя\"")
            self.run_diag("Устройства, которые могут будить", ["powercfg", "/devicequery", "wake_armed"])
        else:
            msg_warn(self, "Пробуждение", (out or f"код {code}") + admin_hint())

    def sleep_study(self) -> None:
        path = DATA_DIR / "sleepstudy.html"

        def done(res):
            code, out = res
            if code == 0 and path.exists():
                os.startfile(str(path))
            else:
                msg_warn(self, "Sleep Study", (out or f"код {code}") +
                         "\n\nОтчёт доступен только на ноутбуках с Modern Standby." + admin_hint())

        run_async(self, lambda _r: run_cmd(["powercfg", "/sleepstudy", "/output", str(path)], 120), done)


# ═══════════════════════════════════════════════════════════════════════════
#  Вкладка 5 — Процессы
# ═══════════════════════════════════════════════════════════════════════════
class ProcTab(QWidget):
    PERIODS = [("24 часа", 86400), ("7 дней", 7 * 86400), ("30 дней", 30 * 86400)]

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.s = win.settings
        self.mon: ProcMonitor = win.monitor

        self.lbl_live = QLabel("Монитор запускается…", objectName="big")
        self.btn_pip = QPushButton("Установить psutil в этот Python")
        self.btn_pip.setVisible(psutil is None)
        self.btn_pip.clicked.connect(self.install_psutil)
        if psutil is None:
            self.lbl_live.setText("Для монитора процессов и правил питания по программам нужен psutil.")

        self.live = make_table(["Процесс", "PID", "CPU %", "RAM", "Диск/с"], sortable=False)
        self.live.setColumnWidth(0, 260)
        for c in (1, 2, 3):
            self.live.setColumnWidth(c, 90)
        b_kill = QPushButton("Завершить процесс")
        b_loc = QPushButton("Открыть расположение")
        live_box = QGroupBox("Сейчас")
        ll = QVBoxLayout(live_box)
        ll.addWidget(self.live, 1)
        r1 = QHBoxLayout()
        r1.addWidget(b_kill)
        r1.addWidget(b_loc)
        r1.addStretch(1)
        ll.addLayout(r1)

        self.cb_period = QComboBox()
        for title, sec in self.PERIODS:
            self.cb_period.addItem(title, sec)
        b_upd = QPushButton("Обновить")
        b_clear = QPushButton("Очистить журнал")
        self.lbl_hist = QLabel("", objectName="muted")
        self.hist = make_table(["Процесс", "Раз в топе", "Ср. CPU", "Макс. CPU", "Макс. RAM",
                                "Макс. диск/с", "Причины", "Последний раз"])
        self.hist.setColumnWidth(0, 220)
        hist_box = QGroupBox("Кто грузил систему (записывается при высокой нагрузке)")
        hl = QVBoxLayout(hist_box)
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("За период:"))
        r2.addWidget(self.cb_period)
        r2.addWidget(b_upd)
        r2.addWidget(b_clear)
        r2.addStretch(1)
        r2.addWidget(self.lbl_hist)
        hl.addLayout(r2)
        hl.addWidget(self.hist, 1)

        self.chk_on = QCheckBox("Вести журнал")
        self.chk_on.setChecked(bool(self.s["mon_enabled"]))
        self.sp_cpu = QSpinBox(minimum=10, maximum=100, suffix=" %", value=int(self.s["mon_cpu"]))
        self.sp_mem = QSpinBox(minimum=10, maximum=100, suffix=" %", value=int(self.s["mon_mem"]))
        self.sp_io = QSpinBox(minimum=1, maximum=5000, suffix=" МБ/с", value=int(self.s["mon_io_mb"]))
        self.sp_int = QSpinBox(minimum=2, maximum=120, suffix=" с", value=int(self.s["mon_interval_s"]))
        cfg = QHBoxLayout()
        cfg.addWidget(self.chk_on)
        for label, w in (("Порог CPU", self.sp_cpu), ("RAM", self.sp_mem), ("диск", self.sp_io),
                         ("интервал", self.sp_int)):
            cfg.addSpacing(10)
            cfg.addWidget(QLabel(label + ":"))
            cfg.addWidget(w)
        cfg.addStretch(1)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(live_box)
        split.addWidget(hist_box)
        split.setSizes([330, 330])
        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        head.addWidget(self.lbl_live, 1)
        head.addWidget(self.btn_pip)
        lay.addLayout(head)
        lay.addWidget(split, 1)
        lay.addLayout(cfg)

        self.mon.tick.connect(self.on_tick)
        b_kill.clicked.connect(self.kill)
        b_loc.clicked.connect(self.open_loc)
        b_upd.clicked.connect(self.load_history)
        b_clear.clicked.connect(self.clear_history)
        self.cb_period.currentIndexChanged.connect(self.load_history)
        self.chk_on.toggled.connect(lambda v: self._set("mon_enabled", v))
        self.sp_cpu.valueChanged.connect(lambda v: self._set("mon_cpu", v))
        self.sp_mem.valueChanged.connect(lambda v: self._set("mon_mem", v))
        self.sp_io.valueChanged.connect(lambda v: self._set("mon_io_mb", v))
        self.sp_int.valueChanged.connect(lambda v: self._set("mon_interval_s", v))

    def _set(self, key: str, value) -> None:
        self.s[key] = value

    def install_psutil(self) -> None:
        cmd = pip_install_cmd(["psutil"])
        if not ask(self, "psutil", "Установить psutil командой:\n\n" + subprocess.list2cmdline(cmd)
                   + "\n\nВ portable-режиме пакет ляжет в Launcher\\Runtime и переедет вместе с папкой."):
            return
        self.btn_pip.setEnabled(False)
        self.lbl_live.setText("Устанавливаю psutil…")

        def done(res):
            code, out = res
            self.btn_pip.setEnabled(True)
            if code == 0:
                self.lbl_live.setText("psutil установлен — перезапустите LaptopCare (Выход в трее и снова из Choice).")
            else:
                self.lbl_live.setText("Не удалось установить psutil.")
                OutputDialog(self, "pip", out).exec()

        run_async(self, lambda _r: run_cmd(cmd, 600), done)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.load_history()

    def on_tick(self, d: dict) -> None:
        col = BAD if d["reasons"] else ACCENT
        self.lbl_live.setText(f"CPU {d['cpu']:.0f}%  ·  RAM {d['mem']:.0f}%  ·  диск {human_size(d['disk'])}/с"
                              + ("  ·  " + ("записано в журнал" if d["logged"] else "высокая нагрузка")
                                 if d["reasons"] else ""))
        self.lbl_live.setStyleSheet(f"color: {col if d['reasons'] else '#e6edf3'}")
        if not (self.isVisible() and self.window().isVisible()):
            return
        sel_pid = None
        rows = selected_rows(self.live)
        if rows:
            it = self.live.item(rows[0], 1)
            sel_pid = it.data(DATA_ROLE) if it else None
        procs = d["procs"][:60]
        t = self.live
        t.setUpdatesEnabled(False)
        t.setRowCount(len(procs))
        for r, (name, pid, cpu, rss, io) in enumerate(procs):
            hot = cpu >= 25
            t.setItem(r, 0, cell(name, color=WARN if hot else None))
            t.setItem(r, 1, cell(pid, data=pid, right=True))
            t.setItem(r, 2, cell(f"{cpu:.1f}", right=True, color=WARN if hot else None))
            t.setItem(r, 3, cell(human_size(rss), right=True))
            t.setItem(r, 4, cell(human_size(io) if io else "—", right=True))
            if pid == sel_pid:
                t.selectRow(r)
        t.setUpdatesEnabled(True)

    def _sel_pid(self) -> int | None:
        rows = selected_rows(self.live)
        if not rows:
            return None
        it = self.live.item(rows[0], 1)
        return it.data(DATA_ROLE) if it else None

    def kill(self) -> None:
        pid = self._sel_pid()
        if pid is None or psutil is None:
            return
        try:
            p = psutil.Process(pid)
            name = p.name()
        except psutil.Error as e:
            msg_warn(self, "Процесс", str(e))
            return
        if not ask(self, "Завершить процесс", f"Завершить {name} (PID {pid})? Несохранённые данные пропадут."):
            return
        try:
            p.terminate()
        except psutil.AccessDenied:
            msg_warn(self, "Процесс", "Отказано в доступе." + admin_hint())
        except psutil.Error as e:
            msg_warn(self, "Процесс", str(e))

    def open_loc(self) -> None:
        pid = self._sel_pid()
        if pid is None or psutil is None:
            return
        try:
            explorer_select(psutil.Process(pid).exe())
        except psutil.Error as e:
            msg_warn(self, "Процесс", f"{e}" + admin_hint())

    def load_history(self) -> None:
        since = time.time() - (self.cb_period.currentData() or 86400)
        try:
            incidents, rows = top_offenders(DATA_DIR / "procmon.sqlite", since)
        except sqlite3.Error as e:
            self.lbl_hist.setText(f"Ошибка базы: {e}")
            return
        self.lbl_hist.setText(f"Эпизодов высокой нагрузки: {incidents}")
        names = {"cpu": "CPU", "ram": "RAM", "disk": "диск"}
        t = self.hist
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        for r, (name, hits, avg_cpu, max_cpu, max_rss, max_io, reasons, last_ts) in enumerate(rows):
            rs = sorted({x for part in (reasons or "").split(",") for x in [part.strip()] if x})
            t.setItem(r, 0, cell(name, key=name.lower()))
            t.setItem(r, 1, cell(hits, key=hits, right=True))
            t.setItem(r, 2, cell(f"{avg_cpu or 0:.1f}%", key=avg_cpu or 0, right=True))
            t.setItem(r, 3, cell(f"{max_cpu or 0:.1f}%", key=max_cpu or 0, right=True))
            t.setItem(r, 4, cell(human_size(max_rss or 0), key=max_rss or 0, right=True))
            t.setItem(r, 5, cell(human_size(max_io or 0), key=max_io or 0, right=True))
            t.setItem(r, 6, cell(", ".join(names.get(x, x) for x in rs)))
            t.setItem(r, 7, cell(f"{dt.datetime.fromtimestamp(last_ts):%d.%m %H:%M}", key=last_ts))
        t.setSortingEnabled(True)

    def clear_history(self) -> None:
        if not ask(self, "Журнал", "Удалить все записи журнала нагрузки?"):
            return
        try:
            con = sqlite3.connect(str(DATA_DIR / "procmon.sqlite"), timeout=5)
            con.execute("DELETE FROM samples")
            con.commit()
            con.close()
        except sqlite3.Error as e:
            msg_warn(self, "Журнал", str(e))
        self.load_history()


# ═══════════════════════════════════════════════════════════════════════════
#  Главное окно, трей, автозапуск
# ═══════════════════════════════════════════════════════════════════════════
def autostart_command() -> str:
    exe = Path(sys.executable)
    if getattr(sys, "frozen", False):
        return f'"{exe}" --tray'
    own = RUNTIME_DIR / f"{OWN_EXE}.exe"
    if running_from_runtime() and own.is_file():
        exe = own
    elif exe.stem.lower() == "python":
        pyw = exe.with_name("pythonw.exe")
        exe = pyw if pyw.exists() else exe
    return f'"{exe}" "{SCRIPT_PATH}" --tray'


def _autostart_value() -> str | None:
    if not IS_WIN:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return str(winreg.QueryValueEx(k, AUTOSTART_VALUE)[0])
    except OSError:
        return None


def autostart_enabled() -> bool:
    return _autostart_value() is not None


def heal_autostart() -> None:
    """Папку Launcher перенесли — запись автозапуска указывает в старое место. Чиним."""
    val = _autostart_value()
    if val is not None and val != autostart_command():
        try:
            set_autostart(True)
            log.info("Автозапуск: путь обновлён (%s)", autostart_command())
        except OSError:
            log.exception("Автозапуск: не удалось обновить путь")


def set_autostart(on: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, AUTOSTART_VALUE, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(k, AUTOSTART_VALUE)
            except FileNotFoundError:
                pass


# ── portable: своя копия pythonw в Runtime и регистрация для Choice ──────
def pip_install_cmd(pkgs: list[str]) -> list[str]:
    exe = Path(sys.executable)
    py = exe.with_name("python.exe")
    return [str(py if py.is_file() else exe), "-m", "pip", "install",
            "--disable-pip-version-check", "--no-warn-script-location", *pkgs]


def _script_key() -> str:
    """Ключ в Runtime\\apps.json — путь скрипта относительно Launcher (как пишет make_portable)."""
    try:
        return SCRIPT_PATH.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(SCRIPT_PATH)


def register_in_runtime_apps() -> None:
    """Choice читает Runtime\\apps.json и запускает скрипт сразу его exe — тогда он виден
    в «Запущенных» и закрывается вместе с Choice. make_portable --force файл перезаписывает,
    поэтому прописываемся при каждом запуске из Runtime."""
    path = RUNTIME_DIR / "apps.json"
    try:
        apps = json.loads(path.read_text("utf-8")) if path.exists() else {}
    except Exception:
        log.warning("Runtime\\apps.json не читается — не трогаю его")
        return
    if not isinstance(apps, dict):
        return
    key, val = _script_key(), f"{OWN_EXE}.exe"
    norm = os.path.normcase(key.replace("\\", "/"))
    if any(os.path.normcase(str(k).replace("\\", "/")) == norm and v == val for k, v in apps.items()):
        return
    apps[key] = val
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(apps, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, path)
    log.info("Прописан в %s: %s → %s", path, key, val)


def _find_rcedit() -> Path | None:
    for p in (ROOT / "Data" / "rcedit-x64.exe", ROOT / "rcedit-x64.exe", ROOT / "Tools" / "rcedit-x64.exe",
              RUNTIME_DIR / "rcedit-x64.exe"):
        if p.is_file():
            return p
    return None


def _brand_exe(exe: Path) -> None:
    rcedit = _find_rcedit()
    if rcedit is None:
        return
    ico = DATA_DIR / "laptopcare.ico"
    try:
        if not ico.exists():
            make_icon(256).pixmap(256, 256).save(str(ico), "ICO")
    except Exception:
        log.exception("Не удалось сохранить иконку")
    args = [str(rcedit), str(exe), "--set-version-string", "FileDescription", "LaptopCare",
            "--set-version-string", "ProductName", "LaptopCare"]
    if ico.is_file():
        args += ["--set-icon", str(ico)]
    code, out = run_cmd(args, 60)
    if code != 0:
        log.warning("rcedit: %s", out)


def ensure_own_exe() -> Path | None:
    exe = RUNTIME_DIR / f"{OWN_EXE}.exe"
    if exe.is_file():
        return exe
    pyw = RUNTIME_DIR / "pythonw.exe"
    if not pyw.is_file():
        return None
    try:
        shutil.copy2(pyw, exe)
    except OSError:
        log.exception("Не удалось создать %s", exe)
        return None
    _brand_exe(exe)
    log.info("Создан %s", exe)
    return exe


def relaunch_under_own_exe(launcher: tuple[int, int] | None) -> bool:
    """Как у NP_Notes/NP_Screenshot: свой exe → своё имя и значок в трее и Диспетчере задач.
    Возвращает True, если запущена копия под своим exe и этот процесс должен завершиться."""
    if not IS_WIN or getattr(sys, "frozen", False) or not running_from_runtime():
        return False
    try:
        register_in_runtime_apps()
    except Exception:
        log.exception("Регистрация в Runtime\\apps.json")
    if Path(sys.executable).stem.lower() == OWN_EXE.lower():
        return False
    exe = ensure_own_exe()
    if exe is None:
        return False
    # копия отцепляется от Choice — передаём ей, за каким процессом Choice следить
    cmd = [str(exe), str(SCRIPT_PATH), *strip_launcher_arg(sys.argv[1:]), *launcher_arg(launcher)]
    try:
        # первый запуск: выходим из Job Object лаунчера, иначе он закроет нас вместе с этим процессом
        subprocess.Popen(cmd, cwd=str(Path.cwd()), close_fds=True, creationflags=0x01000000)
    except OSError:
        try:
            subprocess.Popen(cmd, cwd=str(Path.cwd()), close_fds=True)
        except OSError:
            return False
    return True


# ── связь с Choice: закрываемся вместе с ним ──────────────────────────────
# Choice закрывает «свои» процессы (WM_CLOSE, через 3 с — taskkill /F). Но копия,
# которая отцепилась при первом запуске или перезапустилась от администратора,
# ему не видна. Поэтому LaptopCare сам держит дескриптор процесса Choice и выходит,
# когда тот завершается. Процесс опознаётся по PID + времени создания (PID могут
# переиспользовать).
SYNCHRONIZE = 0x00100000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WAIT_OBJECT_0 = 0
LAUNCHER_EXE_NAMES = {"choice.exe"}
WM_SYSCOMMAND = 0x0112
SC_CLOSE = 0xF060


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", ctypes.c_uint32), ("cntUsage", ctypes.c_uint32),
                ("th32ProcessID", ctypes.c_uint32), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", ctypes.c_uint32), ("cntThreads", ctypes.c_uint32),
                ("th32ParentProcessID", ctypes.c_uint32), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", ctypes.c_uint32), ("szExeFile", ctypes.c_wchar * 260)]


class _MSG(ctypes.Structure):
    _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint), ("wParam", ctypes.c_size_t),
                ("lParam", ctypes.c_ssize_t)]


_K32 = None


def k32():
    """Отдельный экземпляр kernel32 со своими argtypes (не трогаем общий windll.kernel32)."""
    global _K32
    if _K32 is None:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        k.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        k.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
        k.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
        k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        k.OpenProcess.restype = ctypes.c_void_p
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        k.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k.WaitForSingleObject.restype = ctypes.c_uint32
        k.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(ctypes.c_ulonglong)] * 4
        _K32 = k
    return _K32


def process_table() -> dict[int, tuple[int, str]]:
    """pid → (pid родителя, имя exe)."""
    k = k32()
    snap = k.CreateToolhelp32Snapshot(0x2, 0)   # TH32CS_SNAPPROCESS
    if not snap or snap == ctypes.c_void_p(-1).value:
        return {}
    out = {}
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(e)
        ok = k.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            out[int(e.th32ProcessID)] = (int(e.th32ParentProcessID), e.szExeFile)
            ok = k.Process32NextW(snap, ctypes.byref(e))
    finally:
        k.CloseHandle(snap)
    return out


def open_process(pid: int):
    return k32().OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, 0, pid) or None


def process_ctime(handle) -> int:
    c, x, kt, ut = (ctypes.c_ulonglong() for _ in range(4))
    ok = k32().GetProcessTimes(handle, ctypes.byref(c), ctypes.byref(x), ctypes.byref(kt), ctypes.byref(ut))
    return int(c.value) if ok else 0


def pid_ctime(pid: int) -> int:
    h = open_process(pid)
    if not h:
        return 0
    try:
        return process_ctime(h)
    finally:
        k32().CloseHandle(h)


def _looks_like_choice(pid: int, exe_name: str) -> bool:
    if exe_name.lower() in LAUNCHER_EXE_NAMES:
        return True
    if psutil is not None and exe_name.lower() in ("python.exe", "pythonw.exe"):
        try:   # Choice.pyw, запущенный обычным Python
            cmd = " ".join(psutil.Process(pid).cmdline()).lower()
            return "choice.pyw" in cmd or "choice_dev" in cmd
        except psutil.Error:
            return False
    return False


def find_launcher_ancestor() -> tuple[int, int] | None:
    """Ищет Choice среди предков текущего процесса → (pid, время создания)."""
    if not IS_WIN:
        return None
    try:
        table = process_table()
        pid = os.getpid()
        child_ct = pid_ctime(pid)
        seen = set()
        for _ in range(12):
            entry = table.get(pid)
            if not entry:
                return None
            ppid = entry[0]
            if not ppid or ppid in seen or ppid not in table:
                return None
            seen.add(ppid)
            pct = pid_ctime(ppid)
            if not pct or (child_ct and pct > child_ct):
                return None            # родитель давно умер, его PID занял другой процесс
            if _looks_like_choice(ppid, table[ppid][1]):
                return ppid, pct
            pid, child_ct = ppid, pct
    except Exception:
        log.exception("Поиск Choice среди родителей")
    return None


def launcher_from_args(argv: list[str]) -> tuple[int, int] | None:
    for a in argv:
        if a.startswith("--launcher="):
            try:
                p, c = a.split("=", 1)[1].split(":")
                return int(p), int(c)
            except ValueError:
                return None
    return None


def strip_launcher_arg(argv: list[str]) -> list[str]:
    return [a for a in argv if not a.startswith("--launcher=")]


def launcher_arg(launcher: tuple[int, int] | None) -> list[str]:
    return [f"--launcher={launcher[0]}:{launcher[1]}"] if launcher else []


class LauncherWatch(QObject):
    """Держит дескриптор процесса Choice; когда тот завершается — сигнал gone."""
    gone = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.handle = None
        self.pid = 0
        self.ctime = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._check)

    @property
    def spec(self) -> tuple[int, int] | None:
        return (self.pid, self.ctime) if self.handle else None

    def attach(self, pid: int, ctime: int) -> bool:
        if not IS_WIN or not pid:
            return False
        h = open_process(pid)
        if not h:
            return False
        real = process_ctime(h)
        if (ctime and real != ctime) or k32().WaitForSingleObject(h, 0) == WAIT_OBJECT_0:
            k32().CloseHandle(h)
            return False
        self.detach()
        self.handle, self.pid, self.ctime = h, pid, real
        self.timer.start(1500)
        log.info("Связан с Choice (PID %s): выйду вместе с ним", pid)
        return True

    def detach(self) -> None:
        self.timer.stop()
        if self.handle:
            k32().CloseHandle(self.handle)
        self.handle, self.pid, self.ctime = None, 0, 0

    def _check(self) -> None:
        if self.handle and k32().WaitForSingleObject(self.handle, 0) == WAIT_OBJECT_0:
            log.info("Choice (PID %s) завершился — выхожу", self.pid)
            self.detach()
            self.gone.emit()


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, server: QLocalServer):
        super().__init__()
        self.settings = settings
        self.server = server
        self._really_quit = False
        self._user_close = False      # закрытие крестиком/Alt+F4 (WM_SYSCOMMAND SC_CLOSE)
        self._profile_actions: dict[str, QAction] = {}
        self.watch = LauncherWatch(self)
        self.watch.gone.connect(self.quit_app)
        self.icon = make_icon()
        self.setWindowIcon(self.icon)
        self.setWindowTitle(f"LaptopCare · np::core{'  [администратор]' if is_admin() else ''}")
        self.resize(1180, 760)

        self.power = PowerManager(settings, self)
        self.monitor = ProcMonitor(settings, DATA_DIR / "procmon.sqlite", self)

        self.tabs = QTabWidget()
        self.tab_startup = StartupTab(self)
        self.tab_clean = CleanTab(self)
        self.tab_power = PowerTab(self)
        self.tab_battery = BatteryTab(self)
        self.tab_proc = ProcTab(self)
        self.tabs.addTab(self.tab_startup, "Автозагрузка")
        self.tabs.addTab(self.tab_clean, "Очистка")
        self.tabs.addTab(self.tab_power, "Питание")
        self.tabs.addTab(self.tab_battery, "Батарея и сон")
        self.tabs.addTab(self.tab_proc, "Процессы")

        gear = QToolButton(text="⚙")
        gear.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        m = QMenu(gear)
        self.act_tray = QAction("Сворачивать в трей при закрытии", m, checkable=True,
                                checked=bool(settings["minimize_to_tray"]))
        self.act_tray.toggled.connect(lambda v: settings.__setitem__("minimize_to_tray", v))
        self.act_start_tray = QAction("Запускаться свёрнутым в трей", m, checkable=True,
                                      checked=bool(settings["start_in_tray"]))
        self.act_start_tray.toggled.connect(lambda v: settings.__setitem__("start_in_tray", v))
        self.act_auto = QAction("Запускать вместе с Windows (в трее)", m, checkable=True,
                                checked=autostart_enabled())
        self.act_auto.toggled.connect(self._toggle_autostart)
        act_data = QAction("Открыть папку данных", m)
        act_data.triggered.connect(lambda: os.startfile(str(DATA_DIR)) if IS_WIN else None)
        act_about = QAction("О программе", m)
        mode = "portable (Launcher\\Runtime)" if running_from_runtime() else sys.executable
        act_about.triggered.connect(lambda: msg_info(
            self, "О программе", f"LaptopCare {APP_VERSION}\n{SIGNATURE}\n\nLauncher: {ROOT}\n"
                                 f"Данные: {DATA_DIR}\nPython: {mode}\nChoice: "
                                 + (f"PID {self.watch.pid} — закроюсь вместе с ним" if self.watch.spec
                                    else "не связан (запущено не из Choice)")))
        m.addAction(self.act_start_tray)
        m.addAction(self.act_tray)
        if UNDER_LAUNCHER and not autostart_enabled():
            # в portable-сборке автозапуском управляет Choice — без записей в реестр
            hint = QAction("Автозапуск — через список автозапуска Choice", m)
            hint.setEnabled(False)
            m.addAction(hint)
        else:
            m.addAction(self.act_auto)
        m.addSeparator()
        m.addAction(act_data)
        m.addAction(act_about)
        gear.setMenu(m)
        self.tabs.setCornerWidget(gear, Qt.Corner.TopRightCorner)
        self.setCentralWidget(self.tabs)

        sig = QLabel(SIGNATURE)
        sig.setStyleSheet(f"color: {ACCENT}; font-family: Consolas, 'Cascadia Mono', monospace;")
        self.statusBar().addPermanentWidget(sig)
        if is_admin():
            self.statusBar().showMessage("Запущено с правами администратора.")
        else:
            b = QPushButton("Перезапустить от администратора")
            b.clicked.connect(self.restart_admin)
            self.statusBar().addWidget(QLabel("Обычные права: часть очистки, службы и диагностика сна недоступны."))
            self.statusBar().addWidget(b)

        self.tray: QSystemTrayIcon | None = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.icon, self)
            self.tray.setToolTip("LaptopCare")
            self.tray.activated.connect(self._tray_activated)
            self.update_tray_menu()
            self.tray.show()
            self.power.event.connect(lambda _line: self._refresh_profile_checks())
            QTimer.singleShot(0, self._refresh_profile_checks)

        self.server.newConnection.connect(self._on_local_connection)
        self.winId()           # окно существует и в трее — Choice сможет прислать ему WM_CLOSE
        self.monitor.start()   # живые данные нужны всегда; запись в журнал — по флажку mon_enabled
        QTimer.singleShot(4000, self.tab_battery.auto_snapshot)

    # ── трей ────────────────────────────────────────────────────────────
    def update_tray_menu(self) -> None:
        if not self.tray:
            return
        m = QMenu()
        m.addAction("Открыть", self.show_normal)
        sub = m.addMenu("Профиль питания")
        group = QActionGroup(sub)
        group.setExclusive(True)
        self._profile_actions: dict[str, QAction] = {}
        sections = []
        if self.power.mode_items():
            sections.append(("Режим Windows (рекомендуется)", self.power.mode_items(), MODE_TIPS))
        sections.append(("Схема электропитания", self.power.plan_items(), {}))
        for i, (title, items, tips) in enumerate(sections):
            if i:
                sub.addSeparator()
            hdr = sub.addAction(title)
            hdr.setEnabled(False)
            f = hdr.font()
            f.setBold(True)
            hdr.setFont(f)
            for pid, name in items:
                a = sub.addAction(name)
                a.setCheckable(True)
                a.setToolTip(tips.get(pid.split(":", 1)[1], PLAN_TIP))
                a.triggered.connect(lambda _c=False, p=pid: self._tray_profile(p))
                group.addAction(a)
                self._profile_actions[pid] = a
        sub.setToolTipsVisible(True)
        sub.aboutToShow.connect(self._refresh_profile_checks)
        act = m.addAction("Автопереключение питания")
        act.setCheckable(True)
        act.setChecked(bool(self.settings["power_auto"]))
        act.toggled.connect(self.tab_power.chk_auto.setChecked)
        m.addSeparator()
        m.addAction("Выход", self.quit_app)
        old = self.tray.contextMenu()
        self.tray.setContextMenu(m)
        self._tray_menu = m
        if old:
            old.deleteLater()

    def _refresh_profile_checks(self) -> None:
        """Галочка на том, что сейчас реально действует (режим — только на «Сбалансированной»)."""
        pid, name = self.power.current_profile()
        for p, a in self._profile_actions.items():
            a.setChecked(p == pid)
        if self.tray:
            self.tray.setToolTip(f"LaptopCare\n{name}")

    def _tray_profile(self, pid: str) -> None:
        try:
            self.power.apply_profile(pid)
            self.power._emit(f"из трея → {self.power.profile_name(pid)}")
        except Exception as e:
            if self.tray:
                self.tray.showMessage("LaptopCare", str(e), QSystemTrayIcon.MessageIcon.Warning)
        self._refresh_profile_checks()

    def _tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.show_normal()

    def show_normal(self) -> None:
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def _on_local_connection(self) -> None:
        sock = self.server.nextPendingConnection()
        if not sock:
            return
        sock.disconnected.connect(sock.deleteLater)
        sock.readyRead.connect(lambda s=sock: self._on_local_message(s))
        if sock.bytesAvailable():
            self._on_local_message(sock)

    def _on_local_message(self, sock: QLocalSocket) -> None:
        """Повторный запуск передаёт свои аргументы: show [--tray] [--launcher=PID:CTIME]."""
        args = bytes(sock.readAll().data()).decode("utf-8", "replace").split()
        if not args or args[0] != "show":
            return
        spec = launcher_from_args(args[1:])
        if spec and spec != self.watch.spec:
            # запустили из Choice, а работает «чужая» копия — привязываемся к этому Choice
            self.watch.attach(*spec)
        if "--tray" not in args:
            self.show_normal()

    def nativeEvent(self, eventType, message):
        try:
            if IS_WIN:
                et = bytes(eventType.data()) if hasattr(eventType, "data") else bytes(eventType)
                if et == b"windows_generic_MSG":
                    msg = _MSG.from_address(int(message))
                    if msg.message == WM_SYSCOMMAND and (msg.wParam & 0xFFF0) == SC_CLOSE:
                        self._user_close = True
        except Exception:
            pass
        return super().nativeEvent(eventType, message)

    def _toggle_autostart(self, on: bool) -> None:
        try:
            set_autostart(on)
        except OSError as e:
            msg_warn(self, "Автозапуск", str(e))

    def closeEvent(self, e) -> None:
        # Крестик/Alt+F4 → в трей. «Голый» WM_CLOSE без SC_CLOSE — это Choice
        # (закрывается или нажали «Стоп») или Windows: выходим по-настоящему,
        # иначе через 3 с будет taskkill /F и в трее останется «мёртвый» значок.
        by_user, self._user_close = self._user_close, False
        if not self._really_quit and by_user and self.tray and self.settings["minimize_to_tray"]:
            e.ignore()
            self.hide()
            self.tray_hint_once()
            return
        if not self._really_quit:
            log.info("Закрытие по запросу извне — выхожу")
        self._really_quit = True
        self._shutdown()
        e.accept()
        QApplication.quit()

    def tray_hint_once(self) -> None:
        if self.tray and not self.settings["tray_hint_shown"]:
            self.tray.showMessage("LaptopCare", "Работаю в трее: питание и журнал нагрузки продолжают работать. "
                                                "Окно — щелчок по значку >_, выход — через его меню.",
                                  QSystemTrayIcon.MessageIcon.Information, 6000)
            self.settings["tray_hint_shown"] = True

    def _shutdown(self) -> None:
        self.watch.detach()
        self.monitor.stop()
        self.server.close()
        if self.tray:
            self.tray.hide()

    def quit_app(self) -> None:
        self._really_quit = True
        self.close()

    def restart_admin(self) -> None:
        self.server.close()
        # копия с правами администратора Choice не видна (и закрыть её он не может) —
        # передаём, за каким Choice ей следить
        args = (["--show"] if self.isVisible() else ["--tray"]) + launcher_arg(self.watch.spec)
        if relaunch_as_admin(args):
            self._really_quit = True
            self.close()
        else:
            QLocalServer.removeServer(SERVER_NAME)
            self.server.listen(SERVER_NAME)


# ═══════════════════════════════════════════════════════════════════════════
#  Точка входа
# ═══════════════════════════════════════════════════════════════════════════
def activate_existing_instance(launcher: tuple[int, int] | None) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if sock.waitForConnected(300):
        args = ["show", *(["--tray"] if "--tray" in sys.argv[1:] else []), *launcher_arg(launcher)]
        sock.write(" ".join(args).encode())
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True
    return False


def start_hidden(argv: list[str], start_in_tray: bool, has_tray: bool) -> bool:
    """Как остальные программы Launcher — стартуем в трее. Окно: щелчок по значку,
    повторный запуск из Choice или ключ --show."""
    if not has_tray or "--show" in argv:
        return False
    return "--tray" in argv or bool(start_in_tray)


def main() -> int:
    if sys.stdout:
        try:
            print(SIGNATURE)
        except Exception:
            pass
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(DATA_DIR / "laptopcare.log"), level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not IS_WIN:
        print("LaptopCare рассчитан на Windows.")
        return 1
    log.info("Старт: python=%s root=%s data=%s", sys.executable, ROOT, DATA_DIR)

    # Choice, из которого нас запустили (напрямую или через перезапуск под своим exe)
    launcher = launcher_from_args(sys.argv[1:]) or find_launcher_ancestor()
    log.info("Choice: %s", f"PID {launcher[0]}" if launcher else "не найден")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    if activate_existing_instance(launcher):
        return 0
    if relaunch_under_own_exe(launcher):
        return 0
    try:   # своя группа на панели задач, а не значок python.exe
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("NPCore.LaptopCare")
    except Exception:
        pass
    heal_autostart()
    QLocalServer.removeServer(SERVER_NAME)
    server = QLocalServer()
    server.listen(SERVER_NAME)

    apply_dark_theme(app)
    settings = Settings(DATA_DIR / "settings.json")
    win = MainWindow(settings, server)
    if launcher and not win.watch.attach(*launcher):
        log.info("Choice (PID %s) уже не работает — живу сам по себе", launcher[0])
    if start_hidden(sys.argv[1:], settings["start_in_tray"], bool(win.tray)):
        win.hide()
        QTimer.singleShot(1500, win.tray_hint_once)
    else:
        win.show()
    rc = app.exec()
    if not win._really_quit:
        win._shutdown()
    return rc


if __name__ == "__main__":
    sys.exit(main())
