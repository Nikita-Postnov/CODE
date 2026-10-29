
from __future__ import annotations
import ctypes
import logging
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from ctypes import wintypes
from typing import Callable


# ============================================================
# БАЗОВАЯ ПРОВЕРКА ПЛАТФОРМЫ
# ============================================================

if sys.platform != "win32":
    print("Этот скрипт рассчитан только на Windows.")
    raise SystemExit(1)


# ============================================================
# ОТДЕЛЬНЫЙ ЗНАЧОК В ТРЕЕ
# ============================================================
# Windows различает значки трея по exe. Если скрипт запущен общим
# python.exe/pythonw.exe (например, из Choice), перезапускаем его под своей
# копией NP_LangIndicator.exe (их делает make_portable.py в папке Runtime). Нет копии — работаем как есть.

def _relaunch_under_own_exe(exe_name: str = "NP_LangIndicator") -> None:
    if sys.platform != "win32" or getattr(sys, "frozen", False):
        return
    current = Path(sys.executable)
    if current.stem.lower() == exe_name.lower():
        return
    target = current.parent / f"{exe_name}.exe"
    if not target.exists():
        return
    cmd = [str(target), str(Path(__file__).resolve()), *sys.argv[1:]]
    try:
        # Выходим из Job Object лаунчера, чтобы он не закрыл нас вместе с собой.
        subprocess.Popen(cmd, cwd=str(Path.cwd()), close_fds=True, creationflags=0x01000000)
    except OSError:
        try:
            subprocess.Popen(cmd, cwd=str(Path.cwd()), close_fds=True)
        except OSError:
            return  # не вышло — работаем под текущим интерпретатором
    raise SystemExit(0)


_relaunch_under_own_exe()


# ============================================================
# ЛОКАЛЬНЫЕ ПУТИ И ЛОГИ
# ============================================================

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "Data"
LOG_FILE = DATA_DIR / "language_indicator_error.log"


def setup_logging() -> None:
    """Создаёт папку Data и включает локальный лог с ротацией.

    Раньше файл рос без ограничений: каждый запуск, смена мониторов и сдвиг
    плашки дописывались навсегда. Теперь — до 1 МБ и две архивные копии.
    """
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            str(LOG_FILE), maxBytes=1_000_000, backupCount=2, encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.addHandler(handler)
        logging.info("Language Indicator started. App dir: %s", APP_DIR)
    except Exception:
        # В .pyw консоли обычно нет, поэтому здесь намеренно не падаем.
        pass


setup_logging()


# ============================================================
# WINAPI: БАЗОВЫЕ DLL И DPI
# ============================================================

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

try:
    shcore = ctypes.WinDLL("shcore", use_last_error=True)
except Exception:
    shcore = None


# MessageBoxW — чтобы показывать понятные ошибки даже при запуске через .pyw.
user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_uint]
user32.MessageBoxW.restype = ctypes.c_int

MB_OK = 0x00000000
MB_ICONINFORMATION = 0x00000040
MB_ICONWARNING = 0x00000030
MB_ICONERROR = 0x00000010


def show_message(title: str, text: str, icon: int = MB_ICONINFORMATION) -> None:
    """Показывает системное сообщение Windows. Ошибки MessageBox игнорируются."""
    try:
        user32.MessageBoxW(None, text, title, MB_OK | icon)
    except Exception:
        pass


def enable_dpi_awareness() -> None:
    """
    Включает DPI-awareness до создания QApplication.

    Это уменьшает риск смещения плашки на мониторах с масштабом 125/150%
    и при связке ноутбук + внешний монитор.
    """
    # Windows 10+: лучший вариант — Per Monitor V2.
    try:
        user32.SetProcessDpiAwarenessContext.argtypes = [wintypes.HANDLE]
        user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = wintypes.HANDLE(-4)
        if user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
            logging.info("DPI awareness: Per Monitor V2")
            return
    except Exception:
        pass

    # Windows 8.1+: запасной вариант.
    if shcore is not None:
        try:
            shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
            shcore.SetProcessDpiAwareness.restype = ctypes.c_long
            PROCESS_PER_MONITOR_DPI_AWARE = 2
            result = shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)
            logging.info("DPI awareness: shcore result=%s", result)
            return
        except Exception:
            pass

    # Старый fallback.
    try:
        user32.SetProcessDPIAware()
        logging.info("DPI awareness: SetProcessDPIAware")
    except Exception:
        pass


enable_dpi_awareness()


# ============================================================
# ЗАЩИТА ОТ ПОВТОРНОГО ЗАПУСКА
# ============================================================

kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.GetLastError.argtypes = []
kernel32.GetLastError.restype = wintypes.DWORD
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = "Local\\Nikita_LanguageIndicator_Taskbar_V4_Fixed"
_single_instance_mutex = None


def acquire_single_instance_lock() -> bool:
    """Не даёт случайно запустить второй экземпляр программы."""
    global _single_instance_mutex

    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        logging.warning("CreateMutexW failed, last_error=%s", kernel32.GetLastError())
        # Не блокируем запуск, если сама защита не сработала.
        return True

    _single_instance_mutex = handle
    last_error = kernel32.GetLastError()

    if last_error == ERROR_ALREADY_EXISTS:
        logging.info("Second instance blocked by mutex.")
        show_message(
            "Language Indicator",
            "Индикатор раскладки уже запущен.\n\n"
            "Второй экземпляр не будет открыт, чтобы не было двух плашек и двух значков в трее.",
            MB_ICONINFORMATION,
        )
        return False

    return True


def release_single_instance_lock() -> None:
    global _single_instance_mutex
    if _single_instance_mutex:
        try:
            kernel32.CloseHandle(_single_instance_mutex)
        except Exception:
            pass
        _single_instance_mutex = None


# ============================================================
# PYQT6 IMPORT
# ============================================================

try:
    from PyQt6.QtCore import QAbstractNativeEventFilter, QRect, QSize, Qt, QTimer
    from PyQt6.QtGui import QAction, QColor, QCursor, QFont, QIcon, QPainter, QPixmap
    from PyQt6.QtWidgets import QApplication, QLabel, QMenu, QSystemTrayIcon, QWidget
except Exception as exc:
    logging.exception("PyQt6 import failed")
    show_message(
        "Language Indicator — ошибка запуска",
        "Не удалось импортировать PyQt6.\n\n"
        "Установи зависимость командой:\n"
        "py -m pip install PyQt6\n\n"
        f"Подробности записаны в:\n{LOG_FILE}",
        MB_ICONERROR,
    )
    raise SystemExit(1) from exc


# ============================================================
# НАСТРОЙКИ
# ============================================================

@dataclass(frozen=True)
class AppConfig:
    # Режим расположения маленькой плашки:
    #   "taskbar" — поверх панели задач, левее области трея;
    #   "corners" — в правом нижнем углу каждого монитора.
    placement_mode: str = "taskbar"

    # False — показывать индикаторы на всех мониторах, где есть панель задач.
    # True  — показывать только на основном мониторе. Это чуть стабильнее, но хуже для второго монитора.
    taskbar_primary_only: bool = False

    # Маленькая плашка.
    small_width: int = 52
    small_height: int = 26
    small_right_offset: int = 20
    small_bottom_offset: int = 12
    small_font_size: int = 11

    # Позиционирование около системного трея.
    taskbar_gap_px: int = 8
    taskbar_fallback_offset_right: int = 185
    taskbar_fallback_height: int = 48

    # Прозрачность маленькой плашки.
    normal_alpha: int = 255
    fullscreen_alpha: int = 255

    # Большая плашка при смене языка.
    popup_width: int = 180
    popup_height: int = 100
    popup_font_size: int = 42
    popup_duration_ms: int = 700
    popup_normal_alpha: int = 255
    popup_fullscreen_alpha: int = 255

    # Частота проверки раскладки.
    update_interval_ms: int = 200

    topmost_reinforce_interval_ms: int = 0

    # Допуск при определении настоящего fullscreen.
    fullscreen_tolerance_px: int = 12

    # Считать обычное maximized-окно fullscreen-режимом или нет.
    # Рекомендую False: обычное развернутое окно не должно делать плашку прозрачнее.
    treat_maximized_as_fullscreen: bool = False

    # Цвета текста маленькой плашки.
    ru_text_color: str = "#FFFF00"
    en_text_color: str = "#00FFFF"
    unknown_text_color: str = "#FFFFFF"

    # Цвета большой плашки.
    ru_popup_bg: str = "#FFB000"
    en_popup_bg: str = "#00AEEF"
    unknown_popup_bg: str = "#404040"
    popup_text_color: str = "#000000"

    # Фон маленькой плашки.
    small_bg_color: str = "#000000"

    # Название приложения в трее.
    tray_title: str = "Language Indicator"

    # Значок в системном трее.
    tray_icon_bg_color: str = "#202020"
    tray_icon_border_color: str = "#303030"
    tray_icon_font_size: int = 30
    tray_icon_padding_ratio: float = 0.06


CONFIG = AppConfig()


# ============================================================
# WINAPI: ТИПЫ И ФУНКЦИИ
# ============================================================

class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]

    def to_qrect(self) -> QRect:
        return QRect(
            int(self.left),
            int(self.top),
            int(self.right - self.left),
            int(self.bottom - self.top),
        )


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


class ScreenTarget:
    """
    Один монитор. Источник истины — живой QScreen (логические координаты Qt).

    Дополнительно хранит соответствующий физический монитор WinAPI, чтобы
    корректно переводить координаты панели задач и трея из физических пикселей
    в логические. Без этого на мониторах с масштабом DPI != 100% индикатор
    уезжает за край экрана или вообще не виден.
    """

    def __init__(self, qt_screen, physical: "PhysicalMonitor | None"):
        self._screen = qt_screen
        self._physical = physical

    def name(self) -> str:
        try:
            return self._screen.name() or "Qt Screen"
        except Exception:
            return "Qt Screen"

    def qt_screen(self):
        """Живой QScreen — нужен, чтобы привязать к нему окно перед позиционированием."""
        return self._screen

    def geometry(self) -> QRect:
        return QRect(self._screen.geometry())

    def availableGeometry(self) -> QRect:
        return QRect(self._screen.availableGeometry())

    def physical_geometry(self) -> "QRect | None":
        """Полная геометрия монитора в физических пикселях (или None)."""
        if self._physical is None:
            return None
        return QRect(self._physical.monitor_rect)

    def physical_to_logical(self, rect: "QRect | None") -> "QRect | None":
        """
        Переводит прямоугольник из физических пикселей WinAPI в логические Qt
        для ИМЕННО этого монитора (учитывает его собственный масштаб и начало
        координат на виртуальном рабочем столе).
        """
        if rect is None:
            return None

        phys = self.physical_geometry()
        logi = self.geometry()

        # Нет данных для перевода или вырожденный прямоугольник —
        # считаем масштаб 100% и возвращаем как есть.
        if phys is None or phys.width() <= 0 or phys.height() <= 0:
            return QRect(rect)

        scale_x = logi.width() / phys.width()
        scale_y = logi.height() / phys.height()

        left = logi.left() + round((rect.left() - phys.left()) * scale_x)
        top = logi.top() + round((rect.top() - phys.top()) * scale_y)
        width = round(rect.width() * scale_x)
        height = round(rect.height() * scale_y)
        return QRect(int(left), int(top), int(width), int(height))


def qrect_to_tuple(rect: QRect) -> tuple[int, int, int, int]:
    return (rect.left(), rect.top(), rect.width(), rect.height())


def same_screen_geometry(first: QRect, second: QRect) -> bool:
    return qrect_to_tuple(first) == qrect_to_tuple(second)


user32.GetForegroundWindow.restype = wintypes.HWND

user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD

user32.GetKeyboardLayout.argtypes = [wintypes.DWORD]
user32.GetKeyboardLayout.restype = wintypes.HKL

user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wintypes.BOOL

user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HANDLE

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL

kernel32.GetLocaleInfoW.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.LPWSTR, ctypes.c_int]
kernel32.GetLocaleInfoW.restype = ctypes.c_int

user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND

user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowExW.restype = wintypes.HWND

user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int

user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL

user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_uint,
]
user32.SetWindowPos.restype = wintypes.BOOL

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL

user32.EnumChildWindows.argtypes = [wintypes.HWND, WNDENUMPROC, wintypes.LPARAM]
user32.EnumChildWindows.restype = wintypes.BOOL

MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HANDLE,
    wintypes.HDC,
    ctypes.POINTER(RECT),
    wintypes.LPARAM,
)

user32.EnumDisplayMonitors.argtypes = [
    wintypes.HDC,
    ctypes.c_void_p,
    MONITORENUMPROC,
    wintypes.LPARAM,
]
user32.EnumDisplayMonitors.restype = wintypes.BOOL

user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFOEXW)]
user32.GetMonitorInfoW.restype = wintypes.BOOL

# Для click-through окон.
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

if ctypes.sizeof(ctypes.c_void_p) == 8:
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_longlong
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_longlong]
    user32.SetWindowLongPtrW.restype = ctypes.c_longlong
else:
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowLongW.restype = ctypes.c_long

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
VK_Q = 0x51
VK_R = 0x52
MONITOR_DEFAULTTONEAREST = 0x00000002
LOCALE_SISO639LANGNAME = 0x00000059

HWND_TOPMOST = wintypes.HWND(-1)
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010


def _get_window_long(hwnd: int, index: int) -> int:
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        return int(user32.GetWindowLongPtrW(wintypes.HWND(hwnd), index))
    return int(user32.GetWindowLongW(wintypes.HWND(hwnd), index))


def _set_window_long(hwnd: int, index: int, value: int) -> None:
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        user32.SetWindowLongPtrW(wintypes.HWND(hwnd), index, ctypes.c_longlong(value))
    else:
        user32.SetWindowLongW(wintypes.HWND(hwnd), index, ctypes.c_long(value))


def make_window_click_through(widget: QWidget) -> None:
    """Делает окно некликабельным и неактивируемым на Windows."""
    hwnd = int(widget.winId())
    style = _get_window_long(hwnd, GWL_EXSTYLE)
    style |= WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    _set_window_long(hwnd, GWL_EXSTYLE, style)


def force_window_topmost(widget: QWidget) -> None:
    """Переводит окно в TOPMOST-слой без активации, показа и лишней перерисовки."""
    hwnd = int(widget.winId())
    user32.SetWindowPos(
        wintypes.HWND(hwnd),
        HWND_TOPMOST,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
    )


def get_foreground_hwnd() -> int:
    return int(user32.GetForegroundWindow() or 0)


def get_window_rect(hwnd: int) -> QRect | None:
    if not hwnd:
        return None

    rect = RECT()
    ok = user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))
    if not ok:
        return None

    qrect = rect.to_qrect()
    if qrect.width() <= 0 or qrect.height() <= 0:
        return None

    return qrect


# ============================================================
# ЛОГИКА ОПРЕДЕЛЕНИЯ РАСКЛАДКИ
# ============================================================

UWP_FRAME_CLASS = "ApplicationFrameWindow"
UWP_CORE_CLASS = "Windows.UI.Core.CoreWindow"


def get_input_thread_id(hwnd: int) -> int:
    """
    Поток, чья раскладка действует в окне hwnd.

    У UWP-приложений (Параметры, Калькулятор, Microsoft Store и т.п.) окно-рамка
    принадлежит процессу ApplicationFrameHost, а ввод идёт в дочернее
    CoreWindow самого приложения. Раньше бралась раскладка рамки — и индикатор
    показывал в таких окнах не тот язык.
    """
    thread_id = int(user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), None) or 0)
    if get_window_class(hwnd) == UWP_FRAME_CLASS:
        core = user32.FindWindowExW(wintypes.HWND(hwnd), None, UWP_CORE_CLASS, None)
        if core:
            core_thread = int(user32.GetWindowThreadProcessId(core, None) or 0)
            if core_thread:
                thread_id = core_thread
    return thread_id


_lang_code_cache: dict[int, str] = {}


def lang_code_from_langid(lang_id: int) -> str:
    """
    Короткий код языка по LANGID.

    RU — русский, EN — любой английский (как раньше). Для остальных — ISO-код
    языка из Windows: UK, BE, KK, DE… Раньше выводился HEX-код (0422), а в
    трее — его первые две цифры «04», по которым язык не узнать.
    """
    primary_lang_id = lang_id & 0x03FF
    # 0x19 — Russian, 0x09 — English.
    if primary_lang_id == 0x19:
        return "RU"
    if primary_lang_id == 0x09:
        return "EN"

    cached = _lang_code_cache.get(lang_id)
    if cached is not None:
        return cached

    code = f"{lang_id:04X}"
    try:
        buffer = ctypes.create_unicode_buffer(9)
        if kernel32.GetLocaleInfoW(lang_id, LOCALE_SISO639LANGNAME, buffer, len(buffer)) > 0 and buffer.value:
            code = buffer.value.upper()
    except Exception:
        logging.debug("GetLocaleInfoW failed for %04X", lang_id, exc_info=True)
    _lang_code_cache[lang_id] = code
    return code


def get_active_keyboard_lang() -> str:
    """
    Возвращает текущую раскладку активного окна.

    RU — русский, EN — любой английский primary language, не только US/UK.
    Для остальных языков — ISO-код (UK, DE…), если Windows его не знает — HEX.
    """
    hwnd = get_foreground_hwnd()
    if not hwnd:
        return ""

    thread_id = get_input_thread_id(hwnd)
    if not thread_id:
        return ""

    raw_hkl = user32.GetKeyboardLayout(thread_id)
    if not raw_hkl:
        return ""

    return lang_code_from_langid(int(raw_hkl) & 0xFFFF)


def get_small_text_color(lang: str) -> str:
    if lang == "RU":
        return CONFIG.ru_text_color
    if lang == "EN":
        return CONFIG.en_text_color
    return CONFIG.unknown_text_color


def get_popup_bg_color(lang: str) -> str:
    if lang == "RU":
        return CONFIG.ru_popup_bg
    if lang == "EN":
        return CONFIG.en_popup_bg
    return CONFIG.unknown_popup_bg


def normalize_lang_for_display(lang: str) -> str:
    """Возвращает короткий текст для плашки и значка трея."""
    if lang in ("RU", "EN"):
        return lang
    if lang and lang.isalpha():
        return lang[:3].upper()   # ISO-код: UK, DE, FIL
    if lang:
        return lang[:2].upper()
    return "??"


# ============================================================
# МОНИТОРЫ
# ============================================================

def rect_from_monitor_info_rect(rect: RECT) -> QRect:
    return QRect(
        int(rect.left),
        int(rect.top),
        int(rect.right - rect.left),
        int(rect.bottom - rect.top),
    )


@dataclass(frozen=True)
class PhysicalMonitor:
    """Монитор в ФИЗИЧЕСКИХ пикселях (как его отдаёт WinAPI)."""
    device_name: str
    monitor_rect: QRect  # весь монитор
    work_rect: QRect     # рабочая область (без панели задач)


def get_physical_monitors() -> list[PhysicalMonitor]:
    """Список мониторов в физических пикселях через WinAPI EnumDisplayMonitors."""
    monitors: list[PhysicalMonitor] = []

    @MONITORENUMPROC
    def callback(monitor_handle, _hdc, _rect, _lparam):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)

        if user32.GetMonitorInfoW(monitor_handle, ctypes.byref(info)):
            geometry = rect_from_monitor_info_rect(info.rcMonitor)
            work = rect_from_monitor_info_rect(info.rcWork)
            name = info.szDevice.strip()

            if geometry.width() > 0 and geometry.height() > 0:
                monitors.append(PhysicalMonitor(name, geometry, work))

        return True

    ok = user32.EnumDisplayMonitors(None, None, callback, 0)
    if not ok:
        logging.warning("EnumDisplayMonitors failed, last_error=%s", ctypes.get_last_error())

    return monitors


def get_window_monitor(hwnd: int) -> PhysicalMonitor | None:
    """Монитор, на котором окно hwnd (в физических пикселях, как и GetWindowRect)."""
    if not hwnd:
        return None
    monitor_handle = user32.MonitorFromWindow(wintypes.HWND(hwnd), MONITOR_DEFAULTTONEAREST)
    if not monitor_handle:
        return None
    info = MONITORINFOEXW()
    info.cbSize = ctypes.sizeof(MONITORINFOEXW)
    if not user32.GetMonitorInfoW(monitor_handle, ctypes.byref(info)):
        return None
    return PhysicalMonitor(
        info.szDevice.strip(),
        rect_from_monitor_info_rect(info.rcMonitor),
        rect_from_monitor_info_rect(info.rcWork),
    )


def merge_screen_targets(qt_app: QApplication) -> list[ScreenTarget]:
    """
    Источник истины — список экранов Qt (ровно по одному индикатору на монитор).

    К каждому Qt-экрану подбираем соответствующий физический монитор WinAPI:
      1) по имени устройства (QScreen.name() == MONITORINFOEXW.szDevice, напр. \\\\.\\DISPLAY1);
      2) запасной вариант — по позиции на виртуальном рабочем столе.

    Раньше здесь объединялись Qt- и WinAPI-списки с дедупликацией по точному
    совпадению геометрии. При масштабе DPI != 100% логическая (Qt) и физическая
    (WinAPI) геометрии не совпадают, поэтому один монитор попадал в список дважды,
    и второй индикатор уезжал за пределы экрана. Теперь дублей нет.
    """
    physical_monitors = get_physical_monitors()
    physical_by_name = {m.device_name: m for m in physical_monitors if m.device_name}
    physical_sorted = sorted(
        physical_monitors,
        key=lambda m: (m.monitor_rect.top(), m.monitor_rect.left()),
    )

    qt_screens = []
    for screen in qt_app.screens():
        try:
            geometry = screen.geometry()
        except Exception:
            continue
        if geometry.width() > 0 and geometry.height() > 0:
            qt_screens.append(screen)

    qt_screens.sort(key=lambda s: (s.geometry().top(), s.geometry().left()))

    targets: list[ScreenTarget] = []
    for index, screen in enumerate(qt_screens):
        physical = physical_by_name.get(screen.name())
        if physical is None and index < len(physical_sorted):
            physical = physical_sorted[index]
        targets.append(ScreenTarget(screen, physical))

    return targets


# ============================================================
# РАСПОЛОЖЕНИЕ НА ПАНЕЛИ ЗАДАЧ
# ============================================================

def get_window_class(hwnd: int) -> str:
    """Возвращает WinAPI class name окна."""
    if not hwnd:
        return ""

    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(wintypes.HWND(hwnd), buffer, len(buffer))
    return buffer.value


def enum_top_windows_by_class(class_names: set[str]) -> list[int]:
    """Ищет верхнеуровневые окна по class name."""
    found: list[int] = []

    @WNDENUMPROC
    def callback(hwnd, _lparam):
        class_name = get_window_class(int(hwnd))
        if class_name in class_names and user32.IsWindowVisible(hwnd):
            found.append(int(hwnd))
        return True

    user32.EnumWindows(callback, 0)
    return found


def find_child_window_by_class(parent_hwnd: int, target_class: str) -> int:
    """
    Рекурсивно ищет дочернее окно с нужным class name.

    Для области системного трея обычно нужен TrayNotifyWnd.
    В разных версиях Windows структура панели задач может отличаться,
    поэтому используем рекурсивный поиск.
    """
    if not parent_hwnd:
        return 0

    result = {"hwnd": 0}

    @WNDENUMPROC
    def callback(hwnd, _lparam):
        if get_window_class(int(hwnd)) == target_class:
            result["hwnd"] = int(hwnd)
            return False
        return True

    user32.EnumChildWindows(wintypes.HWND(parent_hwnd), callback, 0)
    return result["hwnd"]


def qrect_intersects(a: QRect, b: QRect) -> bool:
    return not (
        a.right() < b.left()
        or a.left() > b.right()
        or a.bottom() < b.top()
        or a.top() > b.bottom()
    )


# Hwnd панели задач и трея почти не меняются, а их поиск (EnumWindows /
# EnumChildWindows) — самая дорогая операция на горячем пути. Поэтому
# кэшируем результат перечисления с коротким TTL. Сами координаты
# (GetWindowRect по известному hwnd) остаются «живыми» и считаются каждый
# тик, так что плашка по-прежнему следует за изменением ширины трея.
_TASKBAR_CACHE_TTL_SEC = 1.5
_taskbar_windows_cache: dict[str, object] = {"time": 0.0, "value": []}
_tray_hwnd_cache: dict[int, tuple[float, int]] = {}


def get_taskbar_windows() -> list[int]:
    """
    Возвращает hwnd основной и вторичных панелей задач.

    Shell_TrayWnd — основная панель задач.
    Shell_SecondaryTrayWnd — дополнительные панели задач на других мониторах.

    Результат кэшируется на короткое время: перечисление всех окон системы
    слишком дорого выполнять 5+ раз в секунду. Пустой результат (например,
    в момент перезапуска Explorer) не кэшируется, чтобы быстро восстановиться.
    """
    now = time.monotonic()
    cached_value = _taskbar_windows_cache["value"]
    if cached_value and (now - float(_taskbar_windows_cache["time"])) < _TASKBAR_CACHE_TTL_SEC:
        return list(cached_value)  # type: ignore[arg-type]

    windows = enum_top_windows_by_class({"Shell_TrayWnd", "Shell_SecondaryTrayWnd"})
    if windows:
        _taskbar_windows_cache["time"] = now
        _taskbar_windows_cache["value"] = windows
    return windows


def get_tray_hwnd_cached(taskbar_hwnd: int) -> int:
    """
    Кэширует hwnd области трея (TrayNotifyWnd) для конкретной панели задач.

    Если закэшированный hwnd «умер» (Explorer перезапустился), GetWindowRect по
    нему вернёт None, расчёт уйдёт в fallback, а кэш обновится по истечении TTL.
    """
    now = time.monotonic()
    entry = _tray_hwnd_cache.get(taskbar_hwnd)
    if entry is not None and (now - entry[0]) < _TASKBAR_CACHE_TTL_SEC:
        return entry[1]

    tray_hwnd = find_child_window_by_class(taskbar_hwnd, "TrayNotifyWnd")
    if tray_hwnd:
        _tray_hwnd_cache[taskbar_hwnd] = (now, tray_hwnd)
    return tray_hwnd


def get_taskbar_physical_rect_for_screen(screen) -> QRect | None:
    """
    Прямоугольник панели задач в ФИЗИЧЕСКИХ пикселях для конкретного экрана.

    Сравнение ведётся с физической геометрией монитора, чтобы корректно
    различать панели задач на разных мониторах при любом масштабе DPI.
    """
    ref = screen.physical_geometry() or screen.geometry()

    for hwnd in get_taskbar_windows():
        rect = get_window_rect(hwnd)
        if rect is not None and qrect_intersects(rect, ref):
            return rect

    return None


def get_tray_physical_rect_for_screen(screen) -> QRect | None:
    """
    Прямоугольник области трея (TrayNotifyWnd) в ФИЗИЧЕСКИХ пикселях.

    Если Windows 11/Explorer не отдаёт ожидаемую структуру окон, вернёт None,
    и расчёт перейдёт на fallback-отступ от правого края панели задач.
    """
    ref = screen.physical_geometry() or screen.geometry()

    for taskbar_hwnd in get_taskbar_windows():
        taskbar_rect = get_window_rect(taskbar_hwnd)
        if taskbar_rect is None or not qrect_intersects(taskbar_rect, ref):
            continue

        tray_hwnd = get_tray_hwnd_cached(taskbar_hwnd)
        tray_rect = get_window_rect(tray_hwnd)
        if tray_rect is not None and qrect_intersects(tray_rect, ref):
            return tray_rect

    return None


def infer_taskbar_rect_from_qt(screen) -> QRect | None:
    """
    Запасной способ: вычисляет панель задач по разнице между geometry и availableGeometry.
    Работает для обычной панели задач без автоскрытия.
    """
    full = screen.geometry()
    avail = screen.availableGeometry()

    # Панель снизу.
    if avail.bottom() < full.bottom():
        top = avail.bottom() + 1
        return QRect(full.left(), top, full.width(), full.bottom() - top + 1)

    # Панель сверху.
    if avail.top() > full.top():
        return QRect(full.left(), full.top(), full.width(), avail.top() - full.top())

    # Панель слева.
    if avail.left() > full.left():
        return QRect(full.left(), full.top(), avail.left() - full.left(), full.height())

    # Панель справа.
    if avail.right() < full.right():
        left = avail.right() + 1
        return QRect(left, full.top(), full.right() - left + 1, full.height())

    return None


def detect_taskbar_edge(taskbar_rect: QRect, screen_rect: QRect) -> str:
    """Определяет, с какой стороны экрана находится панель задач."""
    if taskbar_rect.width() >= taskbar_rect.height():
        taskbar_center_y = taskbar_rect.center().y()
        screen_center_y = screen_rect.center().y()
        return "top" if taskbar_center_y < screen_center_y else "bottom"

    taskbar_center_x = taskbar_rect.center().x()
    screen_center_x = screen_rect.center().x()
    return "left" if taskbar_center_x < screen_center_x else "right"


def build_fallback_taskbar_rect(screen) -> QRect:
    """
    Последний запасной вариант для случая автоскрытия панели задач.
    Считаем, что панель находится снизу экрана.
    """
    full = screen.geometry()
    height = CONFIG.taskbar_fallback_height
    return QRect(full.left(), full.bottom() - height + 1, full.width(), height)


def calculate_taskbar_indicator_rect(screen) -> QRect:
    """
    Рассчитывает положение индикатора на панели задач в ЛОГИЧЕСКИХ координатах Qt.

    Все прямоугольники окон WinAPI приходят в физических пикселях и переводятся
    в логические через ScreenTarget.physical_to_logical. Без этого на мониторах
    с масштабом != 100% индикатор уезжает или вовсе не виден.

    Приоритет источника панели задач:
      1. WinAPI (физические -> логические) — точное положение и сторона панели;
      2. разница geometry/availableGeometry (уже логические) — для обычной панели;
      3. ручной fallback снизу — на случай автоскрытия.
    """
    screen_rect = screen.geometry()  # логические координаты

    taskbar_rect = screen.physical_to_logical(get_taskbar_physical_rect_for_screen(screen))
    if taskbar_rect is None:
        taskbar_rect = infer_taskbar_rect_from_qt(screen)
    if taskbar_rect is None:
        taskbar_rect = build_fallback_taskbar_rect(screen)

    tray_rect = screen.physical_to_logical(get_tray_physical_rect_for_screen(screen))
    edge = detect_taskbar_edge(taskbar_rect, screen_rect)

    width = CONFIG.small_width
    height = CONFIG.small_height
    gap = CONFIG.taskbar_gap_px

    if edge in ("bottom", "top"):
        if tray_rect is not None and qrect_intersects(tray_rect, screen_rect):
            x = tray_rect.left() - width - gap
        else:
            x = taskbar_rect.right() - CONFIG.taskbar_fallback_offset_right - width + 1

        y = taskbar_rect.top() + max(0, (taskbar_rect.height() - height) // 2)

    else:  # edge == "left" или "right": вертикальная панель задач сбоку
        x = taskbar_rect.left() + max(0, (taskbar_rect.width() - width) // 2)
        y = taskbar_rect.bottom() - CONFIG.taskbar_fallback_offset_right - height + 1

    # Ограничиваем координаты, чтобы индикатор не улетел за пределы экрана.
    x = max(screen_rect.left(), min(x, screen_rect.right() - width + 1))
    y = max(screen_rect.top(), min(y, screen_rect.bottom() - height + 1))

    return QRect(x, y, width, height)


# ============================================================
# ОКНА-ИНДИКАТОРЫ
# ============================================================

class SmallIndicator(QWidget):
    def __init__(self, screen_target):
        super().__init__()
        self._screen_target = screen_target
        self.screen_name = screen_target.name()
        self._overlay_styles_applied = False
        self._last_lang = ""
        self._last_alpha = -1
        self._last_rect: QRect | None = None

        self.setWindowTitle(f"{CONFIG.tray_title} - {self.screen_name}")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        self.label = QLabel("...", self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setFont(QFont("Segoe UI", CONFIG.small_font_size, QFont.Weight.Bold))
        self.label.setGeometry(0, 0, CONFIG.small_width, CONFIG.small_height)
        self.label.setStyleSheet(
            f"background-color: {CONFIG.small_bg_color}; "
            f"color: {CONFIG.unknown_text_color}; "
            "border: 1px solid #303030;"
        )

        self.resize(CONFIG.small_width, CONFIG.small_height)

    def _target_qt_screen(self):
        try:
            return self._screen_target.qt_screen()
        except Exception:
            return None

    def _bind_to_target_screen(self) -> None:
        """
        Привязывает окно к нужному QScreen ДО позиционирования.

        Без этого PyQt интерпретирует координаты под devicePixelRatio того экрана,
        на котором окно было изначально создано (обычно основного). На мониторе с
        другим масштабом DPI это уводит индикатор мимо панели задач или вообще за
        пределы экрана — ровно поэтому плашка не появлялась на втором мониторе.
        """
        screen = self._target_qt_screen()
        if screen is None:
            return

        self.winId()  # гарантирует, что нативный handle уже создан
        handle = self.windowHandle()
        if handle is None:
            return

        try:
            if handle.screen() is not screen:
                handle.setScreen(screen)
        except Exception:
            logging.exception("setScreen failed for %s", self.screen_name)

    def ensure_overlay(self, force_style: bool = False, force_topmost: bool = False) -> None:
        was_hidden = not self.isVisible()

        if was_hidden:
            self.show()

        self._bind_to_target_screen()

        if force_style or not self._overlay_styles_applied:
            make_window_click_through(self)
            self._overlay_styles_applied = True

        if force_topmost or was_hidden:
            force_window_topmost(self)

    def apply_geometry_if_changed(self, rect: QRect) -> bool:
        if self._last_rect is not None and self._last_rect == rect and self.geometry() == rect:
            return False

        self._last_rect = QRect(rect)
        self._bind_to_target_screen()
        self.setGeometry(rect)

        # Повторно: при переходе окна на монитор с другим DPI Qt мог пересчитать
        # координаты. Второй setGeometry ставит окно точно на нужное место.
        if self.geometry() != rect:
            self.setGeometry(rect)

        return True

    def show_corner_at(self, rect: QRect, force_topmost: bool = False) -> None:
        x = rect.right() - CONFIG.small_width - CONFIG.small_right_offset + 1
        y = rect.bottom() - CONFIG.small_height - CONFIG.small_bottom_offset + 1
        target_rect = QRect(x, y, CONFIG.small_width, CONFIG.small_height)

        # Сначала показываем и привязываем окно к экрану, потом позиционируем.
        self.ensure_overlay(force_topmost=force_topmost)
        geometry_changed = self.apply_geometry_if_changed(target_rect)
        if geometry_changed:
            self.ensure_overlay(force_topmost=True)

    def show_taskbar_at(self, screen, force_topmost: bool = False) -> None:
        self._screen_target = screen
        rect = calculate_taskbar_indicator_rect(screen)

        self.ensure_overlay(force_topmost=force_topmost)
        geometry_changed = self.apply_geometry_if_changed(rect)
        if geometry_changed:
            self.ensure_overlay(force_topmost=True)
            logging.info(
                "Indicator placed on %s: target=%s actual=%s",
                self.screen_name,
                qrect_to_tuple(rect),
                qrect_to_tuple(self.geometry()),
            )

    def set_lang(self, lang: str) -> None:
        if lang == self._last_lang:
            return

        self._last_lang = lang
        self.label.setText(lang)
        self.label.setStyleSheet(
            f"background-color: {CONFIG.small_bg_color}; "
            f"color: {get_small_text_color(lang)}; "
            "border: 1px solid #303030;"
        )

    def set_alpha(self, alpha: int) -> None:
        alpha = max(0, min(alpha, 255))
        if alpha == self._last_alpha:
            return

        self._last_alpha = alpha
        self.setWindowOpacity(alpha / 255.0)


class PopupIndicator(QWidget):
    def __init__(self):
        super().__init__()
        self._overlay_styles_applied = False
        self._last_rect: QRect | None = None
        self._last_alpha = -1
        self._last_lang = ""
        self._target_screen = None

        self.setWindowTitle(f"{CONFIG.tray_title} popup")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        self.label = QLabel("RU", self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setFont(QFont("Segoe UI", CONFIG.popup_font_size, QFont.Weight.Bold))
        self.label.setGeometry(0, 0, CONFIG.popup_width, CONFIG.popup_height)

        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide)

        self.resize(CONFIG.popup_width, CONFIG.popup_height)

    def ensure_overlay(self, force_style: bool = False, force_topmost: bool = True) -> None:
        was_hidden = not self.isVisible()

        if was_hidden:
            self.show()

        self._bind_to_screen()

        if force_style or not self._overlay_styles_applied:
            make_window_click_through(self)
            self._overlay_styles_applied = True

        if force_topmost or was_hidden:
            force_window_topmost(self)

    def _bind_to_screen(self) -> None:
        """Привязка к целевому экрану перед позиционированием (см. SmallIndicator)."""
        screen = self._target_screen
        if screen is None:
            return
        self.winId()
        handle = self.windowHandle()
        if handle is None:
            return
        try:
            if handle.screen() is not screen:
                handle.setScreen(screen)
        except Exception:
            pass

    def apply_geometry_if_changed(self, rect: QRect) -> bool:
        if self._last_rect is not None and self._last_rect == rect and self.geometry() == rect:
            return False

        self._last_rect = QRect(rect)
        self._bind_to_screen()
        self.setGeometry(rect)
        if self.geometry() != rect:
            self.setGeometry(rect)
        return True

    def show_lang(self, lang: str, screen, alpha: int) -> None:
        # screen — это QScreen активного окна; берём его геометрию и привязываемся к нему.
        self._target_screen = screen
        screen_rect = screen.geometry()
        x = screen_rect.left() + (screen_rect.width() - CONFIG.popup_width) // 2
        y = screen_rect.top() + (screen_rect.height() - CONFIG.popup_height) // 2
        target_rect = QRect(x, y, CONFIG.popup_width, CONFIG.popup_height)

        if lang != self._last_lang:
            self._last_lang = lang
            self.label.setText(lang)
            self.label.setStyleSheet(
                f"background-color: {get_popup_bg_color(lang)}; "
                f"color: {CONFIG.popup_text_color}; "
                "border: 1px solid #303030;"
            )

        self.ensure_overlay(force_topmost=True)
        geometry_changed = self.apply_geometry_if_changed(target_rect)

        alpha = max(0, min(alpha, 255))
        if alpha != self._last_alpha:
            self._last_alpha = alpha
            self.setWindowOpacity(alpha / 255.0)

        if geometry_changed:
            self.ensure_overlay(force_topmost=True)
        self.hide_timer.start(CONFIG.popup_duration_ms)


# ============================================================
# ГЛОБАЛЬНЫЕ ГОРЯЧИЕ КЛАВИШИ
# ============================================================

class GlobalHotkeys(QAbstractNativeEventFilter):
    """
    Глобальные хоткеи через RegisterHotKey.

    Раньше клавиши опрашивались через GetAsyncKeyState 12 раз в секунду: быстрое
    нажатие могло проскочить между опросами, сочетание одновременно уходило в
    активное приложение, а процесс просыпался даже в простое. Теперь Windows
    сама присылает WM_HOTKEY, и нажатие не доходит до других программ.
    """

    def __init__(self, qt_app: QApplication):
        super().__init__()
        self._qt_app = qt_app
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._next_id = 1
        self._installed = False

    def register(self, modifiers: int, vk: int, name: str, callback: Callable[[], None]) -> bool:
        hotkey_id = self._next_id
        self._next_id += 1
        if not user32.RegisterHotKey(None, hotkey_id, modifiers | MOD_NOREPEAT, vk):
            logging.warning("RegisterHotKey failed for %s (winerror=%s) — занято другой программой?",
                            name, ctypes.get_last_error())
            return False
        self._callbacks[hotkey_id] = callback
        if not self._installed:
            self._qt_app.installNativeEventFilter(self)
            self._installed = True
        logging.info("Hotkey registered: %s", name)
        return True

    def unregister_all(self) -> None:
        for hotkey_id in list(self._callbacks):
            user32.UnregisterHotKey(None, hotkey_id)
        self._callbacks.clear()
        if self._installed:
            self._qt_app.removeNativeEventFilter(self)
            self._installed = False

    def nativeEventFilter(self, event_type, message):
        # Второй элемент ответа — только число: PyQt6 падает (segfault), если
        # вернуть None, даже вместе с False.
        try:
            if bytes(event_type) != b"windows_generic_MSG" or not message:
                return False, 0
            msg = wintypes.MSG.from_address(int(message))
            if msg.message != WM_HOTKEY:
                return False, 0
            callback = self._callbacks.get(int(msg.wParam))
            if callback is None:
                return False, 0
            # Выход/перезапуск — не изнутри обработки нативного сообщения.
            QTimer.singleShot(0, callback)
            return True, 0
        except Exception:
            logging.exception("nativeEventFilter failed")
            return False, 0


# ============================================================
# ОСНОВНОЕ ПРИЛОЖЕНИЕ
# ============================================================

class LanguageIndicatorApp:
    def __init__(self, qt_app: QApplication):
        self.qt_app = qt_app
        self.widgets: list[tuple[object, SmallIndicator]] = []
        self.popup = PopupIndicator()
        self.last_lang = ""
        self.current_tray_lang = ""
        self.is_visible = True
        self._update_tick = 0
        self._all_targets: list[ScreenTarget] = []
        self._tray_icon_cache: dict[str, QIcon] = {}
        self._last_screen_signature: tuple[tuple[str, tuple[int, int, int, int], tuple[int, int, int, int]], ...] = tuple()

        self.tray_menu = self.create_tray_menu()

        self.tray = QSystemTrayIcon(self.create_tray_icon("??"), self.qt_app)
        self.tray.setToolTip(CONFIG.tray_title)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()

        # При открытии меню трея панель задач Windows перерисовывается и может
        # перехватить z-порядок, оставив плашку ЗА панелью задач (выглядит как
        # будто индикатор пропал). Поэтому переустанавливаем topmost вокруг
        # показа меню — сразу и с небольшой задержкой, когда панель уже осела.
        self.tray_menu.aboutToShow.connect(self.reinforce_indicators_now)
        self.tray_menu.aboutToHide.connect(self.reinforce_indicators_now)
        self.tray_menu.aboutToHide.connect(self.reinforce_indicators_deferred)

        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.safe_update_state)
        self.update_timer.start(CONFIG.update_interval_ms)

        self.hotkeys = GlobalHotkeys(self.qt_app)
        self.hotkeys.register(MOD_CONTROL | MOD_ALT, VK_Q, "Ctrl+Alt+Q (выход)", self.quit)
        self.hotkeys.register(MOD_CONTROL | MOD_ALT, VK_R, "Ctrl+Alt+R (перезапуск)", self.restart_app)

        self.screen_watch_timer = QTimer()
        self.screen_watch_timer.timeout.connect(self.safe_recreate_widgets_if_screens_changed)
        self.screen_watch_timer.start(2000)

        self.recreate_widgets()
        self.safe_update_state(force_no_popup=True)

        self.qt_app.screenAdded.connect(lambda _: self.safe_recreate_widgets())
        self.qt_app.screenRemoved.connect(lambda _: self.safe_recreate_widgets())

    def create_tray_icon(self, lang: str) -> QIcon:
        """Создаёт и кэширует крупный локальный значок для системного трея."""
        icon_text = normalize_lang_for_display(lang)
        cached_icon = self._tray_icon_cache.get(icon_text)
        if cached_icon is not None:
            return cached_icon

        text_color = get_small_text_color(icon_text)
        icon = QIcon()

        for size_px in (16, 20, 24, 32, 40, 48, 64, 128, 256):
            pixmap = QPixmap(QSize(size_px, size_px))
            pixmap.fill(QColor(CONFIG.tray_icon_bg_color))

            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(QColor(CONFIG.tray_icon_border_color))
            painter.drawRect(0, 0, size_px - 1, size_px - 1)
            painter.setPen(QColor(text_color))

            font = QFont("Segoe UI", CONFIG.tray_icon_font_size, QFont.Weight.Black)
            ratio = 0.68 if len(icon_text) <= 2 else 0.46  # три буквы (FIL, HAW) иначе не влезут
            font.setPixelSize(max(8, int(size_px * ratio)))
            painter.setFont(font)

            padding = max(1, int(size_px * CONFIG.tray_icon_padding_ratio))
            text_rect = pixmap.rect().adjusted(padding, 0, -padding, 0)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, icon_text)
            painter.end()

            icon.addPixmap(pixmap)

        self._tray_icon_cache[icon_text] = icon
        return icon

    def update_tray_icon(self, lang: str) -> None:
        """Обновляет значок и подсказку в трее только при реальной смене раскладки."""
        icon_text = normalize_lang_for_display(lang)
        if icon_text == self.current_tray_lang:
            return

        self.current_tray_lang = icon_text
        self.tray.setIcon(self.create_tray_icon(icon_text))
        self.tray.setToolTip(f"{CONFIG.tray_title}: {icon_text}")

    def create_tray_menu(self) -> QMenu:
        menu = QMenu()

        show_hide_action = QAction("Скрыть/показать индикаторы", menu)
        show_hide_action.triggered.connect(self.toggle_visibility)
        menu.addAction(show_hide_action)

        recreate_action = QAction("Пересоздать индикаторы", menu)
        recreate_action.triggered.connect(self.safe_recreate_widgets)
        menu.addAction(recreate_action)

        restart_action = QAction("Перезапустить скрипт", menu)
        restart_action.triggered.connect(self.restart_app)
        menu.addAction(restart_action)

        menu.addSeparator()

        exit_action = QAction("Выход", menu)
        exit_action.triggered.connect(self.quit)
        menu.addAction(exit_action)

        return menu

    def on_tray_activated(self, reason) -> None:
        """Не трогает окно индикатора при кликах по трею, чтобы не было моргания."""
        return

    def reinforce_indicators_deferred(self) -> None:
        for delay_ms in (250, 1000, 2500):
            QTimer.singleShot(delay_ms, self.reinforce_indicators_now)

    def reinforce_indicators_now(self) -> None:
        if not self.is_visible:
            return

        try:
            for screen, widget in self.widgets:
                if CONFIG.placement_mode == "taskbar":
                    widget.show_taskbar_at(screen, force_topmost=True)
                else:
                    widget.show_corner_at(screen.availableGeometry(), force_topmost=True)
        except Exception:
            # Вызывается таймерами и сигналами меню — без перехвата ошибка
            # превращалась бы в окно с сообщением на каждый вызов.
            logging.exception("reinforce_indicators_now failed")

    def get_indicator_screens(self) -> list[ScreenTarget]:
        """Возвращает все экраны, на которых нужно показывать маленькие индикаторы."""
        targets = merge_screen_targets(self.qt_app)
        self._all_targets = targets

        if CONFIG.placement_mode == "taskbar" and CONFIG.taskbar_primary_only:
            primary = self.qt_app.primaryScreen()
            if primary is None:
                return targets[:1]

            primary_geometry = primary.geometry()
            primary_target = next(
                (target for target in targets if same_screen_geometry(target.geometry(), primary_geometry)),
                None,
            )
            return [primary_target] if primary_target is not None else targets[:1]

        return targets

    def get_screen_signature(self) -> tuple[tuple[str, tuple[int, int, int, int], tuple[int, int, int, int]], ...]:
        return tuple(
            (
                screen.name(),
                qrect_to_tuple(screen.geometry()),
                qrect_to_tuple(screen.availableGeometry()),
            )
            for screen in self.get_indicator_screens()
        )

    def safe_recreate_widgets_if_screens_changed(self) -> None:
        try:
            current_signature = self.get_screen_signature()
        except Exception:
            logging.exception("screen signature check failed")
            return

        if current_signature != self._last_screen_signature:
            logging.info("Screen set changed: %s", current_signature)
            self.safe_recreate_widgets()

    def safe_recreate_widgets(self) -> None:
        try:
            self.recreate_widgets()
        except Exception:
            logging.exception("recreate_widgets failed")

    def recreate_widgets(self) -> None:
        for _, widget in self.widgets:
            widget.hide()
            widget.deleteLater()

        self.widgets.clear()

        screens = self.get_indicator_screens()
        self._last_screen_signature = tuple(
            (
                screen.name(),
                qrect_to_tuple(screen.geometry()),
                qrect_to_tuple(screen.availableGeometry()),
            )
            for screen in screens
        )
        logging.info("Indicator screens: %s", self._last_screen_signature)

        for screen in screens:
            if screen is None:
                continue

            widget = SmallIndicator(screen)

            if CONFIG.placement_mode == "taskbar":
                widget.show_taskbar_at(screen, force_topmost=True)
            else:
                widget.show_corner_at(screen.availableGeometry(), force_topmost=True)

            widget.set_alpha(CONFIG.normal_alpha)
            self.widgets.append((screen, widget))

        self.safe_update_state(force_no_popup=True)
        self.reinforce_indicators_deferred()

    def toggle_visibility(self) -> None:
        self.is_visible = not self.is_visible

        for _, widget in self.widgets:
            widget.setVisible(self.is_visible)

        if self.is_visible:
            self.reinforce_indicators_now()
        else:
            self.popup.hide()

    def restart_app(self) -> None:
        """
        Перезапуск: новый процесс + штатный выход текущего.

        Раньше был os.execl — на Windows он не берёт аргументы в кавычки, и
        скрипт из папки с пробелом в пути («C:\\My Tools\\...») не перезапускался.
        """
        logging.info("Restart requested")
        command = build_restart_command()
        self.hotkeys.unregister_all()
        self.tray.hide()
        release_single_instance_lock()
        try:
            subprocess.Popen(command, cwd=str(APP_DIR), close_fds=True)
        except Exception:
            logging.exception("Restart failed: %s", command)
            show_message(
                "Language Indicator — перезапуск",
                f"Не удалось запустить новый экземпляр.\n\nПодробности записаны в:\n{LOG_FILE}",
                MB_ICONERROR,
            )
        self.qt_app.quit()

    def quit(self) -> None:
        logging.info("Quit requested")
        self.hotkeys.unregister_all()
        self.tray.hide()
        release_single_instance_lock()
        self.qt_app.quit()

    def safe_update_state(self, force_no_popup: bool = False) -> None:
        try:
            self.update_state(force_no_popup=force_no_popup)
        except Exception:
            logging.exception("update_state failed")

    def should_force_topmost_now(self) -> bool:
        # Раз в ~2 секунды заново выставляем topmost, чтобы плашка сама
        # восстанавливалась, если её перекрыла панель задач (меню трея,
        # перерисовка Explorer, выход из полноэкранного приложения и т.п.).
        # Один SetWindowPos без перемещения/изменения размера — операция дешёвая.
        interval_ticks = max(1, 2000 // max(1, CONFIG.update_interval_ms))
        return self._update_tick % interval_ticks == 0

    def update_state(self, force_no_popup: bool = False) -> None:
        self._update_tick += 1

        lang = get_active_keyboard_lang()
        if not lang:
            lang = self.last_lang or "??"

        self.update_tray_icon(lang)

        if not self.is_visible:
            self.last_lang = lang
            return

        # Экран, на котором сейчас настоящее полноэкранное окно (или None).
        # Раньше это значение вычислялось как None и не использовалось — фича
        # затемнения в fullscreen была не подключена, из-за чего настройки
        # fullscreen_alpha / popup_fullscreen_alpha ни на что не влияли.
        fullscreen_screen = self.get_fullscreen_screen()
        fullscreen_name = fullscreen_screen.name() if fullscreen_screen is not None else None
        force_topmost = self.should_force_topmost_now()

        for screen, widget in self.widgets:
            if CONFIG.placement_mode == "taskbar":
                widget.show_taskbar_at(screen, force_topmost=force_topmost)
            else:
                widget.show_corner_at(screen.availableGeometry(), force_topmost=force_topmost)

            widget.set_lang(lang)

            on_fullscreen = fullscreen_name is not None and screen.name() == fullscreen_name
            widget.set_alpha(CONFIG.fullscreen_alpha if on_fullscreen else CONFIG.normal_alpha)

        if self.last_lang and lang != self.last_lang and not force_no_popup:
            active_screen = self.get_active_screen()

            if active_screen is not None:
                active_on_fullscreen = (
                    fullscreen_name is not None and active_screen.name() == fullscreen_name
                )
                popup_alpha = (
                    CONFIG.popup_fullscreen_alpha
                    if active_on_fullscreen
                    else CONFIG.popup_normal_alpha
                )
                self.popup.show_lang(lang, active_screen, popup_alpha)

        self.last_lang = lang

    def _qt_screen_for_monitor(self, monitor: PhysicalMonitor | None):
        """
        QScreen для физического монитора WinAPI.

        По порядку: физическая геометрия из сопоставления мониторов, имя
        устройства (\\\\.\\DISPLAY1), левый верхний угол (у экранов Qt он совпадает
        с нативным), а если экран один — он.
        """
        if monitor is None:
            return None
        for target in self._all_targets:
            if target.physical_geometry() == monitor.monitor_rect:
                return target.qt_screen()
        screens = self.qt_app.screens()
        for screen in screens:
            if monitor.device_name and screen.name() == monitor.device_name:
                return screen
        for screen in screens:
            if screen.geometry().topLeft() == monitor.monitor_rect.topLeft():
                return screen
        return screens[0] if len(screens) == 1 else None

    def get_active_screen(self):
        """
        Экран активного окна.

        GetWindowRect отдаёт физические пиксели, а screenAt ждёт логические Qt.
        При масштабе 125–150% это расходится: большая плашка появлялась не на
        том мониторе. Теперь монитор берётся у самой Windows (MonitorFromWindow).
        """
        screen = self._qt_screen_for_monitor(get_window_monitor(get_foreground_hwnd()))
        if screen is not None:
            return screen

        cursor_screen = self.qt_app.screenAt(QCursor.pos())  # QCursor — уже логические координаты
        if cursor_screen is not None:
            return cursor_screen

        return self.qt_app.primaryScreen()

    def get_fullscreen_screen(self):
        """
        Экран, на котором активное окно развёрнуто на весь монитор (или None).

        Сравнение — в физических пикселях с обеих сторон. Раньше физический
        прямоугольник окна сравнивался с логической геометрией экрана, и на
        мониторе с масштабом ≠ 100% полноэкранный режим не распознавался вовсе.
        """
        hwnd = get_foreground_hwnd()
        rect = get_window_rect(hwnd)
        monitor = get_window_monitor(hwnd)
        if rect is None or monitor is None:
            return None

        tolerance = CONFIG.fullscreen_tolerance_px

        # Настоящий fullscreen: окно занимает весь монитор, включая область панели задач.
        is_fullscreen = rects_are_close(rect, monitor.monitor_rect, tolerance)

        # Обычное maximized-окно занимает рабочую область, но это не всегда fullscreen.
        if not is_fullscreen and CONFIG.treat_maximized_as_fullscreen:
            is_fullscreen = rects_are_close(rect, monitor.work_rect, tolerance)

        return self._qt_screen_for_monitor(monitor) if is_fullscreen else None


def build_restart_command() -> list[str]:
    """Команда запуска нового экземпляра — та же, что запустила этот."""
    if getattr(sys, "frozen", False):  # собранный exe (PyInstaller и т.п.)
        return [sys.executable, *sys.argv[1:]]
    script = str(Path(sys.argv[0]).resolve()) if sys.argv and sys.argv[0] else str(Path(__file__).resolve())
    return [sys.executable, script, *sys.argv[1:]]


def rects_are_close(a: QRect, b: QRect, tolerance: int) -> bool:
    return (
        abs(a.left() - b.left()) <= tolerance
        and abs(a.top() - b.top()) <= tolerance
        and abs(a.right() - b.right()) <= tolerance
        and abs(a.bottom() - b.bottom()) <= tolerance
    )


# ============================================================
# ГЛОБАЛЬНАЯ ОБРАБОТКА ОШИБОК
# ============================================================

_ERROR_DIALOG_INTERVAL_SEC = 300.0
_last_error_dialog_at = 0.0


def handle_unhandled_exception(exc_type, exc_value, exc_tb) -> None:
    global _last_error_dialog_at
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logging.error("Unhandled exception:\n%s", text)

    # Если ошибка повторяется в таймере, раньше окна с сообщением шли одно за
    # другим. В лог пишем каждую, окно показываем не чаще раза в 5 минут.
    now = time.monotonic()
    if _last_error_dialog_at and now - _last_error_dialog_at < _ERROR_DIALOG_INTERVAL_SEC:
        return
    _last_error_dialog_at = now
    show_message(
        "Language Indicator — ошибка",
        "Произошла ошибка. Подробности записаны в локальный файл:\n\n"
        f"{LOG_FILE}",
        MB_ICONERROR,
    )


sys.excepthook = handle_unhandled_exception


# ============================================================
# ТОЧКА ВХОДА
# ============================================================

def main() -> int:
    if not acquire_single_instance_lock():
        return 0

    # Для Qt 6. Настройка должна быть до QApplication.
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    controller = LanguageIndicatorApp(app)
    app.aboutToQuit.connect(release_single_instance_lock)

    # Держим ссылку, чтобы сборщик мусора не уничтожил контроллер.
    app._language_indicator_controller = controller  # type: ignore[attr-defined]

    return app.exec()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        logging.exception("Fatal error in main")
        show_message(
            "Language Indicator — критическая ошибка",
            "Программа не смогла запуститься. Подробности записаны в локальный файл:\n\n"
            f"{LOG_FILE}",
            MB_ICONERROR,
        )
        raise SystemExit(1)
