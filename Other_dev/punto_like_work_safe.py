"""punto_like (work-safe build) — переключатель раскладки, автозамена и история буфера.

Модель потоков
──────────────
* main (поток хуков) — LL-хуки клавиатуры/мыши, RegisterHotKey, таймер watchdog'ов
  и цикл GetMessage. Колбэки хуков ничего тяжёлого не делают: только дешёвые
  локальные WinAPI-вызовы и постановка задач в очередь. Поэтому ввод в системе
  не тормозит, а Windows не снимает хук по LowLevelHooksTimeout.
* worker — единственный поток, который выполняет действия: конвертацию,
  автозамену, работу с буфером обмена, вставку из истории. Задачи идут строго
  по очереди, поэтому отдельный мьютекс «busy» больше не нужен.
* idle — планировщик отложенной автозамены (один поток вместо threading.Timer
  на каждое нажатие клавиши).
* tray — окно трея, его меню, слушатель буфера обмена (WM_CLIPBOARDUPDATE)
  и WinEvent-хук смены foreground-окна.
* tk-ui — единственный интерпретатор Tk: редактор правил и окно истории
  буфера открываются как Toplevel-окна этого потока.

Свои синтетические нажатия помечаются dwExtraInfo = _INJECT_TAG, и хук их
игнорирует: наши Ctrl+C / Shift+Left / Alt-трюк не путаются с вводом
пользователя.
"""
from __future__ import annotations

import base64
import ctypes
import faulthandler
import gc
import json
import logging
import operator
import os
import struct
import subprocess
import sys
import threading
import time
import zlib
from contextlib import contextmanager
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path
from queue import Queue as _Queue, Empty as _QueueEmpty, Full as _QueueFull
from typing import Callable, Final, Generator, Literal, Optional
from ctypes import wintypes


_IS_WINDOWS: Final[bool] = sys.platform == "win32"

if _IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    _WINFUNCTYPE = ctypes.WINFUNCTYPE
else:
    # Модуль импортируется и на других ОС — только чтобы гонять тесты чистой
    # логики (раскладка, правила, разбор DIB/PNG, настройки). WinAPI там нет.
    user32 = kernel32 = gdi32 = shell32 = None  # type: ignore[assignment]
    _WINFUNCTYPE = ctypes.CFUNCTYPE

IS_64BIT = ctypes.sizeof(ctypes.c_void_p) == 8
ULONG_PTR = ctypes.c_uint64 if IS_64BIT else ctypes.c_uint32
UINT_PTR = getattr(wintypes, "UINT_PTR", ULONG_PTR)
LONG_PTR = ctypes.c_int64 if IS_64BIT else ctypes.c_long
WPARAM = UINT_PTR
LPARAM = LONG_PTR
HANDLE = ctypes.c_void_p
HGLOBAL = ctypes.c_void_p

# ═══════════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════════

SM_REMOTESESSION: Final[int] = 0x1000

WM_DESTROY: Final[int] = 0x0002
WM_CLOSE: Final[int] = 0x0010
WM_GETTEXT: Final[int] = 0x000D
WM_GETTEXTLENGTH: Final[int] = 0x000E
WM_INPUTLANGCHANGEREQUEST: Final[int] = 0x0050
WM_KEYDOWN: Final[int] = 0x0100
WM_KEYUP: Final[int] = 0x0101
WM_SYSKEYDOWN: Final[int] = 0x0104
WM_SYSKEYUP: Final[int] = 0x0105
WM_TIMER: Final[int] = 0x0113
WM_LBUTTONDOWN: Final[int] = 0x0201
WM_RBUTTONDOWN: Final[int] = 0x0204
WM_RBUTTONUP: Final[int] = 0x0205
WM_MBUTTONDOWN: Final[int] = 0x0207
WM_HOTKEY: Final[int] = 0x0312
WM_CLIPBOARDUPDATE: Final[int] = 0x031D
WM_APP: Final[int] = 0x8000

# Собственные сообщения
_WM_TRAY_CALLBACK: Final[int] = WM_APP + 1   # уведомления иконки трея
_WM_TRAY_REFRESH: Final[int] = WM_APP + 2    # обновить подсказку иконки (пауза)
_WM_APP_EXIT: Final[int] = WM_APP + 3        # thread-message в main: завершиться

PM_NOREMOVE: Final[int] = 0x0000

_MOUSE_BUTTON_DOWN_MESSAGES: Final[frozenset[int]] = frozenset({
    WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN,
})

SMTO_BLOCK: Final[int] = 0x0001
SMTO_ABORTIFHUNG: Final[int] = 0x0002

EVENT_SYSTEM_FOREGROUND: Final[int] = 0x0003
WINEVENT_OUTOFCONTEXT: Final[int] = 0x0000
WINEVENT_SKIPOWNPROCESS: Final[int] = 0x0002

EM_GETSEL: Final[int] = 0x00B0
EM_SETSEL: Final[int] = 0x00B1
EM_REPLACESEL: Final[int] = 0x00C2

MOD_ALT: Final[int] = 0x0001
MOD_CONTROL: Final[int] = 0x0002
MOD_SHIFT: Final[int] = 0x0004
MOD_WIN: Final[int] = 0x0008
MOD_NOREPEAT: Final[int] = 0x4000

VK_BACK: Final[int] = 0x08
VK_TAB: Final[int] = 0x09
VK_SHIFT: Final[int] = 0x10
VK_CONTROL: Final[int] = 0x11
VK_MENU: Final[int] = 0x12
VK_CAPITAL: Final[int] = 0x14
VK_ESCAPE: Final[int] = 0x1B
VK_SPACE: Final[int] = 0x20
VK_PRIOR: Final[int] = 0x21
VK_NEXT: Final[int] = 0x22
VK_END: Final[int] = 0x23
VK_HOME: Final[int] = 0x24
VK_LEFT: Final[int] = 0x25
VK_UP: Final[int] = 0x26
VK_RIGHT: Final[int] = 0x27
VK_DOWN: Final[int] = 0x28
VK_INSERT: Final[int] = 0x2D
VK_DELETE: Final[int] = 0x2E
VK_C: Final[int] = 0x43
VK_V: Final[int] = 0x56
VK_Z: Final[int] = 0x5A
VK_LWIN: Final[int] = 0x5B
VK_RWIN: Final[int] = 0x5C
VK_F1: Final[int] = 0x70
VK_F6: Final[int] = 0x75
VK_F7: Final[int] = 0x76
VK_F8: Final[int] = 0x77
VK_F9: Final[int] = 0x78
VK_F10: Final[int] = 0x79
VK_F11: Final[int] = 0x7A
VK_F12: Final[int] = 0x7B
VK_LSHIFT: Final[int] = 0xA0
VK_RSHIFT: Final[int] = 0xA1
VK_LCONTROL: Final[int] = 0xA2
VK_RCONTROL: Final[int] = 0xA3
VK_LMENU: Final[int] = 0xA4
VK_RMENU: Final[int] = 0xA5
VK_PROCESSKEY: Final[int] = 0xE5
VK_PACKET: Final[int] = 0xE7

INPUT_KEYBOARD: Final[int] = 1
KEYEVENTF_EXTENDEDKEY: Final[int] = 0x0001
KEYEVENTF_KEYUP: Final[int] = 0x0002
KEYEVENTF_UNICODE: Final[int] = 0x0004
MAPVK_VK_TO_VSC: Final[int] = 0

WH_KEYBOARD_LL: Final[int] = 13
WH_MOUSE_LL: Final[int] = 14
HC_ACTION: Final[int] = 0

# Метка наших синтетических событий (dwExtraInfo). Хук пропускает такие
# события мимо всей логики — так свои Ctrl+C/Shift+Left не выглядят как ввод.
_INJECT_TAG: Final[int] = 0x50554E54  # "PUNT"

# Extended-клавиши (scancode с префиксом 0xE0). Без EXTENDED-флага keyup для
# правых Ctrl/Alt и Win может не сматчиться с keydown в приложении.
_EXTENDED_VKS: Final[frozenset[int]] = frozenset({
    VK_INSERT, VK_DELETE, VK_HOME, VK_END, VK_PRIOR, VK_NEXT,
    VK_LEFT, VK_RIGHT, VK_UP, VK_DOWN,
    VK_RCONTROL, VK_RMENU, VK_LWIN, VK_RWIN,
})

CF_BITMAP: Final[int] = 2
CF_METAFILEPICT: Final[int] = 3
CF_OEMTEXT: Final[int] = 7
CF_DIB: Final[int] = 8
CF_PALETTE: Final[int] = 9
CF_UNICODETEXT: Final[int] = 13
CF_ENHMETAFILE: Final[int] = 14
CF_DIBV5: Final[int] = 17
CF_TEXT: Final[int] = 1
CF_OWNERDISPLAY: Final[int] = 0x0080
CF_DSPBITMAP: Final[int] = 0x0082
CF_DSPMETAFILEPICT: Final[int] = 0x0083
CF_DSPENHMETAFILE: Final[int] = 0x008E
CF_PRIVATEFIRST: Final[int] = 0x0200
CF_GDIOBJLAST: Final[int] = 0x03FF
PNG_CLIPBOARD_FORMAT_NAME: Final[str] = "PNG"

DIB_RGB_COLORS: Final[int] = 0
BI_RGB: Final[int] = 0
BI_BITFIELDS: Final[int] = 3
GMEM_MOVEABLE: Final[int] = 0x0002

ERROR_ALREADY_EXISTS: Final[int] = 183
ERROR_HOTKEY_ALREADY_REGISTERED: Final[int] = 1409
PROCESS_QUERY_LIMITED_INFORMATION: Final[int] = 0x1000

LAYOUT_RU: Final[str] = "00000419"
LAYOUT_EN: Final[str] = "00000409"

GWL_STYLE: Final[int] = -16
ES_PASSWORD: Final[int] = 0x0020

IMAGE_ICON: Final[int] = 1
LR_LOADFROMFILE: Final[int] = 0x00000010
LR_DEFAULTSIZE: Final[int] = 0x00000040
IDI_APPLICATION: Final[int] = 32512
NIM_ADD: Final[int] = 0x00000000
NIM_MODIFY: Final[int] = 0x00000001
NIM_DELETE: Final[int] = 0x00000002
NIF_MESSAGE: Final[int] = 0x00000001
NIF_ICON: Final[int] = 0x00000002
NIF_TIP: Final[int] = 0x00000004
_TRAY_ICON_UID: Final[int] = 1

MF_STRING: Final[int] = 0x0000
MF_SEPARATOR: Final[int] = 0x0800
MF_CHECKED: Final[int] = 0x0008
TPM_RIGHTALIGN: Final[int] = 0x0008
TPM_BOTTOMALIGN: Final[int] = 0x0020
TPM_NONOTIFY: Final[int] = 0x0080
TPM_RETURNCMD: Final[int] = 0x0100

_TRAY_MENU_OPEN_RULES: Final[int] = 1001
_TRAY_MENU_EXIT: Final[int] = 1002
_TRAY_MENU_TOGGLE_ACTIVE_WINDOW: Final[int] = 1003
_TRAY_MENU_OPEN_DICT: Final[int] = 1004
_TRAY_MENU_TOGGLE_DISABLED_HERE: Final[int] = 1005
_TRAY_MENU_OPEN_DISABLED_LIST: Final[int] = 1006
_TRAY_MENU_OPEN_SETTINGS: Final[int] = 1007
_TRAY_MENU_OPEN_APP_SETTINGS: Final[int] = 1008

_CLIPBOARD_POLL_TIMER_ID: Final[int] = 1  # только fallback, если listener не встал

# Модификаторы, при которых пробел не запускает автозамену (Shift+Space и т.п.)
_SPACE_BLOCKING_MODIFIER_VKS: Final[frozenset[int]] = frozenset({
    VK_SHIFT, VK_LSHIFT, VK_RSHIFT,
    VK_CONTROL, VK_LCONTROL, VK_RCONTROL,
    VK_MENU, VK_LMENU, VK_RMENU,
    VK_LWIN, VK_RWIN,
})

# Ctrl/Alt/Win + буква — это команда (Ctrl+A, Ctrl+C...), а не набор текста.
_TEXT_SHORTCUT_MODIFIER_VKS: Final[frozenset[int]] = frozenset({
    VK_CONTROL, VK_LCONTROL, VK_RCONTROL,
    VK_MENU, VK_LMENU, VK_RMENU,
    VK_LWIN, VK_RWIN,
})

# Нажатия, которые не прерывают «набор слова»: сами модификаторы (Shift для
# заглавных) и CapsLock. Любая другая не-символьная клавиша (стрелки, Home/End,
# Backspace, Delete, Enter, Tab, Esc...) означает, что пользователь ушёл с места
# набора — отложенная idle-замена в этот момент отменяется.
_IDLE_NEUTRAL_VKS: Final[frozenset[int]] = _SPACE_BLOCKING_MODIFIER_VKS | {VK_CAPITAL}

# Модификаторы, которые могут быть физически зажаты в момент нашего батча.
_RELEASE_MODIFIER_VKS: Final[tuple[int, ...]] = (
    VK_LSHIFT, VK_RSHIFT,
    VK_LCONTROL, VK_RCONTROL,
    VK_LMENU, VK_RMENU,
    VK_LWIN, VK_RWIN,
)

WORD_SEPARATORS: Final[frozenset[str]] = frozenset(" \t\r\n.,!?;:\"'()[]{}\\/-—–")

# Exe-имена медиаплееров, в которых Space не должен вызывать обработку правил.
_MEDIA_PLAYER_EXES: Final[frozenset[str]] = frozenset({
    "mpv.exe", "mpv.com",
    "mpc-hc.exe", "mpc-hc64.exe", "mpc-be.exe", "mpc-be64.exe",
    "vlc.exe",
    "wmplayer.exe",
    "potplayer.exe", "potplayermini.exe", "potplayermini64.exe",
    "kmplayer.exe", "kmplayer64.exe",
    "smplayer.exe",
    "mediaplayerclassic.exe",
    "gom.exe", "gom64.exe", "gomplayer.exe",
    "bsplayer.exe",
    "daum.exe",  # устаревшее имя Daum PotPlayer
    "films & tv.exe", "video.ui.exe",  # Windows Movies & TV
    "msixvc.exe",
})

_CONSOLE_EXES: Final[frozenset[str]] = frozenset({
    "conhost.exe",
    "cmd.exe",
    "powershell.exe",
    "pwsh.exe",
    "windowsterminal.exe",
    "wt.exe",
    "alacritty.exe",
    "mintty.exe",
    "bash.exe",
    "wsl.exe",
    "wslhost.exe",
})

# ═══════════════════════════════════════════════════════════════════════════════
# WinAPI structures
# ═══════════════════════════════════════════════════════════════════════════════

class BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", wintypes.LONG),
        ("bmWidth", wintypes.LONG),
        ("bmHeight", wintypes.LONG),
        ("bmWidthBytes", wintypes.LONG),
        ("bmPlanes", wintypes.WORD),
        ("bmBitsPixel", wintypes.WORD),
        ("bmBits", ctypes.c_void_p),
    ]

class RGBQUAD(ctypes.Structure):
    _fields_ = [
        ("rgbBlue", wintypes.BYTE),
        ("rgbGreen", wintypes.BYTE),
        ("rgbRed", wintypes.BYTE),
        ("rgbReserved", wintypes.BYTE),
    ]

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", RGBQUAD * 1),
    ]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]

class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]

class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", INPUT_UNION),
    ]

class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", HANDLE),
        ("message", wintypes.UINT),
        ("wParam", WPARAM),
        ("lParam", LPARAM),
        ("time", wintypes.DWORD),
        ("pt_x", wintypes.LONG),
        ("pt_y", wintypes.LONG),
    ]

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]

class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", HANDLE),
        ("hwndFocus", HANDLE),
        ("hwndCapture", HANDLE),
        ("hwndMenuOwner", HANDLE),
        ("hwndMoveSize", HANDLE),
        ("hwndCaret", HANDLE),
        ("rcCaret_left", wintypes.LONG),
        ("rcCaret_top", wintypes.LONG),
        ("rcCaret_right", wintypes.LONG),
        ("rcCaret_bottom", wintypes.LONG),
    ]

class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]

class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", HANDLE),
        ("hIcon", HANDLE),
        ("hCursor", HANDLE),
        ("hbrBackground", HANDLE),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]

class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", HANDLE),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", HANDLE),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", HANDLE),
    ]

# Job Object (супервизор): структуры с правильной раскладкой для x86 и x64.
class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]

class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]

class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS: Final[int] = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: Final[int] = 0x00002000
# Дочерние процессы worker'а (блокнот, открытый из трея через os.startfile)
# в Job не попадают — иначе их убивало бы вместе с супервизором.
_JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK: Final[int] = 0x00001000

# Сигнатуры колбэков
_HOOKPROC = _WINFUNCTYPE(LONG_PTR, ctypes.c_int, WPARAM, LPARAM)
_WNDPROC = _WINFUNCTYPE(LONG_PTR, HANDLE, wintypes.UINT, WPARAM, LPARAM)
# void CALLBACK WinEventProc(HWINEVENTHOOK, DWORD event, HWND, LONG idObject,
#                            LONG idChild, DWORD idEventThread, DWORD dwmsEventTime)
_WINEVENTPROC = _WINFUNCTYPE(
    None, HANDLE, wintypes.DWORD, HANDLE, wintypes.LONG, wintypes.LONG,
    wintypes.DWORD, wintypes.DWORD,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

# Идентификаторы хоткеев (RegisterHotKey id)
_HK_CONVERT_SELECTED: Final[int] = 1
_HK_CONVERT_BEFORE_CARET: Final[int] = 2
_HK_TOGGLE_CASE: Final[int] = 3
_HK_CLIPBOARD_PICKER: Final[int] = 5
_HK_EXIT: Final[int] = 7
_HK_PAUSE: Final[int] = 9
_HK_RULES_EDITOR: Final[int] = 11
_HK_UNDO: Final[int] = 13
_HK_TOGGLE_CASE_BEFORE_CARET: Final[int] = 15

HotkeyCombo = tuple[int, int]  # (модификаторы MOD_*, VK)


@dataclass(frozen=True)
class Hotkeys:
    """Основные сочетания. Переопределяются в Data/punto_like_settings.json."""
    convert_selected: HotkeyCombo = (0, VK_INSERT)
    convert_before_caret: HotkeyCombo = (MOD_CONTROL, VK_INSERT)
    toggle_case: HotkeyCombo = (0, VK_F9)
    toggle_case_before_caret: HotkeyCombo = (MOD_CONTROL, VK_F9)
    clipboard_picker: HotkeyCombo = (0, VK_F10)
    rules_editor: HotkeyCombo = (MOD_CONTROL | MOD_ALT, VK_F7)
    undo: HotkeyCombo = (MOD_CONTROL | MOD_ALT, VK_Z)
    pause: HotkeyCombo = (MOD_CONTROL | MOD_ALT, VK_F11)
    exit: HotkeyCombo = (MOD_CONTROL | MOD_ALT, VK_F12)


@dataclass(frozen=True)
class Timings:
    between_key_events_seconds: float = 0.02
    open_clipboard_retries: int = 30
    open_clipboard_retry_delay_seconds: float = 0.01
    copy_poll_timeout_seconds: float = 0.9
    copy_poll_interval_seconds: float = 0.02
    max_selected_length: int = 10_000

    clipboard_history_max_chars_per_item: int = 20_000
    # 50 МБ на одну картинку покрывает скриншоты до 4K (3840×2160×4 ≈ 33 МБ).
    # При меньшем лимите крупные скриншоты от Win+Shift+S попадают в историю
    # как PNG-only, а Qt-приложения (Telegram и др.) формат «PNG» не читают.
    clipboard_history_max_image_bytes: int = 50_000_000
    clipboard_preview_max_px: int = 420

    # Снапшот буфера перед нашим Ctrl+C: сколько байт и времени готовы
    # потратить на чтение всех форматов (Excel умеет рендерить очень много).
    clipboard_snapshot_max_bytes: int = 128_000_000
    clipboard_snapshot_deadline_seconds: float = 1.0
    # Пауза между нашим Ctrl+V и восстановлением прежнего буфера: медленные
    # приложения (Electron, Qt) читают буфер не сразу после нажатия.
    paste_settle_seconds: float = 0.3
    # Набор через KEYEVENTF_UNICODE (если включён в настройках) — только для
    # однострочного текста не длиннее этого, иначе вставка через буфер.
    max_typed_chars: int = 2_000

    # Автозамена по пробелу выполняется в worker'е, а хук ждёт её не дольше
    # этого — ввод пользователя упорядочен после замены, но хук не висит.
    space_job_deadline_seconds: float = 0.25


ReplaceMethod = Literal["paste", "type"]


@dataclass(frozen=True)
class Settings:
    hotkeys: Hotkeys = field(default_factory=Hotkeys)
    select_word_chord: bool = True
    idle_replace_delay_seconds: float = 2.0
    clipboard_history_max_items: int = 30
    clipboard_history_max_total_bytes: int = 200_000_000
    # Как заменять выделение в «не-Edit» полях (браузеры, Word, IDE):
    # "paste" — через буфер (по умолчанию: не задевает автозамену Word/Outlook
    #           и автозакрытие скобок в IDE);
    # "type"  — набором через KEYEVENTF_UNICODE (буфер не трогается при замене).
    replace_method: ReplaceMethod = "paste"


_HOTKEY_MOD_NAMES: Final[dict[str, int]] = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
}

_HOTKEY_KEY_NAMES: Final[dict[str, int]] = {
    "ins": VK_INSERT, "insert": VK_INSERT,
    "del": VK_DELETE, "delete": VK_DELETE,
    "home": VK_HOME, "end": VK_END,
    "pgup": VK_PRIOR, "pageup": VK_PRIOR,
    "pgdn": VK_NEXT, "pagedown": VK_NEXT,
    "space": VK_SPACE, "tab": VK_TAB, "esc": VK_ESCAPE,
    "pause": 0x13, "scrolllock": 0x91,
    **{f"f{i}": VK_F1 + i - 1 for i in range(1, 25)},
    **{chr(c).lower(): c for c in range(ord("A"), ord("Z") + 1)},
    **{chr(c): c for c in range(ord("0"), ord("9") + 1)},
}

_HOTKEY_DISPLAY_NAMES: Final[dict[int, str]] = {
    VK_INSERT: "Ins", VK_DELETE: "Del", VK_HOME: "Home", VK_END: "End",
    VK_PRIOR: "PgUp", VK_NEXT: "PgDn", VK_SPACE: "Space", VK_TAB: "Tab",
    VK_ESCAPE: "Esc", 0x13: "Pause", 0x91: "ScrollLock",
    **{VK_F1 + i - 1: f"F{i}" for i in range(1, 25)},
    **{c: chr(c) for c in range(ord("A"), ord("Z") + 1)},
    **{c: chr(c) for c in range(ord("0"), ord("9") + 1)},
}


def _parse_hotkey(spec: str) -> Optional[HotkeyCombo]:
    """«Ctrl+Alt+F12» → (MOD_CONTROL|MOD_ALT, VK_F12). None, если не разобрать."""
    if not isinstance(spec, str):
        return None
    parts = [p.strip().lower() for p in spec.split("+")]
    if not parts or any(not p for p in parts):
        return None
    *mods, key = parts
    mod_mask = 0
    for m in mods:
        bit = _HOTKEY_MOD_NAMES.get(m)
        if bit is None or mod_mask & bit:
            return None
        mod_mask |= bit
    vk = _HOTKEY_KEY_NAMES.get(key)
    if vk is None:
        return None
    return mod_mask, vk


def _format_hotkey(mod: int, vk: int) -> str:
    parts: list[str] = []
    if mod & MOD_CONTROL:
        parts.append("Ctrl")
    if mod & MOD_ALT:
        parts.append("Alt")
    if mod & MOD_SHIFT:
        parts.append("Shift")
    if mod & MOD_WIN:
        parts.append("Win")
    parts.append(_HOTKEY_DISPLAY_NAMES.get(vk, f"VK_{vk:#04x}"))
    return "+".join(parts)


def _settings_to_dict(settings: Settings) -> dict:
    hk = settings.hotkeys
    return {
        "_comment": (
            "Изменения применяются после перезапуска. Хоткеи: модификаторы "
            "Ctrl/Alt/Shift/Win и клавиша (A-Z, 0-9, F1-F24, Ins, Del, Home, End, "
            "PgUp, PgDn, Space, Tab, Esc, Pause, ScrollLock), например \"Ctrl+Alt+F7\". "
            "replace_method: \"paste\" (через буфер) или \"type\" (набором символов)."
        ),
        "hotkeys": {
            name: _format_hotkey(*getattr(hk, name))
            for name in Hotkeys.__dataclass_fields__
        },
        "select_word_chord": settings.select_word_chord,
        "idle_replace_delay_seconds": settings.idle_replace_delay_seconds,
        "clipboard_history_max_items": settings.clipboard_history_max_items,
        "clipboard_history_max_total_mb": settings.clipboard_history_max_total_bytes // 1_000_000,
        "replace_method": settings.replace_method,
    }


def _settings_from_dict(data: object) -> tuple[Settings, list[str]]:
    """Разбирает JSON настроек. Невалидные поля заменяются значениями по умолчанию.

    Возвращает (настройки, список предупреждений для лога). Чистая функция.
    """
    defaults = Settings()
    warnings: list[str] = []
    if not isinstance(data, dict):
        return defaults, ["settings: корень JSON — не объект, взяты значения по умолчанию"]

    hk_values: dict[str, HotkeyCombo] = {}
    raw_hotkeys = data.get("hotkeys", {})
    if not isinstance(raw_hotkeys, dict):
        warnings.append("settings: hotkeys — не объект, взяты значения по умолчанию")
        raw_hotkeys = {}
    for name in Hotkeys.__dataclass_fields__:
        if name not in raw_hotkeys:
            continue
        parsed = _parse_hotkey(raw_hotkeys[name])
        if parsed is None:
            warnings.append(f"settings: не разобран хоткей {name}={raw_hotkeys[name]!r}")
            continue
        hk_values[name] = parsed
    for name in raw_hotkeys:
        if name not in Hotkeys.__dataclass_fields__:
            warnings.append(f"settings: неизвестный хоткей {name!r}")

    def number(key: str, default: float, lo: float, hi: float, cast: type) -> float:
        if key not in data:
            return default
        value = data[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not (lo <= value <= hi):
            warnings.append(f"settings: {key}={value!r} вне диапазона [{lo}, {hi}]")
            return default
        return cast(value)

    chord = data.get("select_word_chord", defaults.select_word_chord)
    if not isinstance(chord, bool):
        warnings.append(f"settings: select_word_chord={chord!r} — нужен true/false")
        chord = defaults.select_word_chord

    method = data.get("replace_method", defaults.replace_method)
    if method not in ("paste", "type"):
        warnings.append(f"settings: replace_method={method!r} — нужен \"paste\" или \"type\"")
        method = defaults.replace_method

    max_total_mb = number(
        "clipboard_history_max_total_mb",
        defaults.clipboard_history_max_total_bytes // 1_000_000, 10, 4000, int,
    )
    settings = Settings(
        hotkeys=Hotkeys(**hk_values),
        select_word_chord=chord,
        idle_replace_delay_seconds=number(
            "idle_replace_delay_seconds", defaults.idle_replace_delay_seconds, 0.3, 30.0, float,
        ),
        clipboard_history_max_items=number(
            "clipboard_history_max_items", defaults.clipboard_history_max_items, 1, 500, int,
        ),
        clipboard_history_max_total_bytes=int(max_total_mb) * 1_000_000,
        replace_method=method,
    )
    return settings, warnings

# ═══════════════════════════════════════════════════════════════════════════════
# Layout mapping tables
# ═══════════════════════════════════════════════════════════════════════════════

_EN_TO_RU: Final[dict[str, str]] = {
    # ── Буквы (нижний регистр; верхний восстанавливается в convert_keyboard_layout) ──
    "q": "й", "w": "ц", "e": "у", "r": "к", "t": "е", "y": "н", "u": "г", "i": "ш", "o": "щ", "p": "з",
    "[": "х", "]": "ъ",
    "a": "ф", "s": "ы", "d": "в", "f": "а", "g": "п", "h": "р", "j": "о", "k": "л", "l": "д",
    ";": "ж", "'": "э",
    "z": "я", "x": "ч", "c": "с", "v": "м", "b": "и", "n": "т", "m": "ь",
    ",": "б", ".": "ю", "/": ".",
    "`": "ё",
    # ── Знаки препинания на Shift, различающиеся между раскладками (символ↔символ) ──
    # Регистра нет — проходят через convert_char как есть. Обратная таблица
    # _RU_TO_EN строится автоматически и остаётся согласованной по физ. клавишам.
    "@": '"',   # Shift+2
    "#": "№",   # Shift+3
    "$": ";",   # Shift+4
    "^": ":",   # Shift+6
    "&": "?",   # Shift+7
    "?": ",",   # Shift+/
    "|": "/",   # Shift+\
    # ── Shift-клавиши, дающие в RU заглавную букву (EN→RU корректно; обратное
    # RU-направление для этих заглавных идёт через нижний регистр буквы) ──
    "~": "Ё", "{": "Х", "}": "Ъ", ":": "Ж", '"': "Э", "<": "Б", ">": "Ю",
}
_RU_TO_EN: Final[dict[str, str]] = {v: k for k, v in _EN_TO_RU.items()}

# ═══════════════════════════════════════════════════════════════════════════════
# Data files: rules, dictionary, disabled apps, settings
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class TextRule:
    trigger: str
    replacement: str
    is_enabled: bool = True

@dataclass(frozen=True)
class RulesConfig:
    replace_rules: tuple[TextRule, ...] = ()
    block_triggers: tuple[str, ...] = ()

_RULES_FILE_NAME: Final[str] = "punto_like_rules.json"
_DICTIONARY_FILE_NAME: Final[str] = "punto_like_dictionary.txt"
_DISABLED_APPS_FILE_NAME: Final[str] = "punto_like_disabled_apps.txt"
_SETTINGS_FILE_NAME: Final[str] = "punto_like_settings.json"

DATA_DIR: Final[Path] = Path(__file__).resolve().parent / "Data"

_rules_lock = threading.RLock()
_rules_config: RulesConfig = RulesConfig()
_settings: Settings = Settings()


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

def _atomic_write_text(path: Path, content: str) -> None:
    """Атомарная запись текста: пишем в `.tmp`-сосед, потом `os.replace`.

    Защищает от повреждения файла, если процесс убьют посередине записи.
    На одной FS `os.replace` — атомарный rename, на Windows тоже.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)

def _rules_path() -> Path:
    return DATA_DIR / _RULES_FILE_NAME

def _dictionary_path() -> Path:
    return DATA_DIR / _DICTIONARY_FILE_NAME

def _disabled_apps_path() -> Path:
    return DATA_DIR / _DISABLED_APPS_FILE_NAME

def _settings_path() -> Path:
    return DATA_DIR / _SETTINGS_FILE_NAME


def _load_settings() -> Settings:
    path = _settings_path()
    if not path.exists():
        settings = Settings()
        try:
            _atomic_write_text(path, json.dumps(_settings_to_dict(settings), ensure_ascii=False, indent=2) + "\n")
        except Exception:
            logging.warning("Не удалось создать файл настроек %s", path, exc_info=True)
        return settings
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logging.warning("Файл настроек %s не читается — взяты значения по умолчанию", path, exc_info=True)
        return Settings()
    settings, warnings = _settings_from_dict(data)
    for w in warnings:
        logging.warning(w)
    return settings


def _load_dictionary() -> list[str]:
    """Загружает пользовательский словарь из Data/punto_like_dictionary.txt.

    Формат: одно слово на строку, пустые строки и строки с # игнорируются.
    При первом запуске автоматически мигрирует block_triggers из rules.json.
    """
    dict_path = _dictionary_path()
    if dict_path.exists():
        words: list[str] = []
        for line in dict_path.read_text(encoding="utf-8").splitlines():
            w = line.strip()
            if w and not w.startswith("#"):
                words.append(w)
        return words

    # ── Миграция из старого rules.json ──────────────────────────────────────
    rules_path = _rules_path()
    migrated: list[str] = []
    if rules_path.exists():
        try:
            data = json.loads(rules_path.read_text(encoding="utf-8"))
            block_raw = data.get("block_triggers", [])
            if isinstance(block_raw, list):
                for x in block_raw:
                    t = str(x).strip()
                    if t:
                        migrated.append(t)
        except Exception:
            logging.debug("dictionary migration from rules.json failed", exc_info=True)
    # Сохраняем в новый файл (даже пустой — чтобы в следующий раз не мигрировать снова)
    try:
        _save_dictionary(migrated)
    except Exception:
        logging.debug("save migrated dictionary failed", exc_info=True)
    return migrated

def _save_dictionary(words: list[str]) -> None:
    """Сохраняет пользовательский словарь в Data/punto_like_dictionary.txt."""
    lines = ["# Пользовательский словарь punto_like — по одному слову на строку", ""]
    lines += sorted(set(w.strip() for w in words if w.strip()))
    _atomic_write_text(_dictionary_path(), "\n".join(lines) + "\n")


def _load_rules() -> RulesConfig:
    path = _rules_path()
    replace_rules: list[TextRule] = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            replace_rules_raw = data.get("replace_rules", []) if isinstance(data, dict) else []
            if isinstance(replace_rules_raw, list):
                for it in replace_rules_raw:
                    if not isinstance(it, dict):
                        continue
                    trigger = str(it.get("trigger", "")).strip()
                    replacement = str(it.get("replacement", ""))
                    is_enabled = bool(it.get("is_enabled", True))
                    if trigger:
                        replace_rules.append(TextRule(trigger=trigger, replacement=replacement, is_enabled=is_enabled))
        except Exception:
            logging.warning("Файл правил %s не читается", path, exc_info=True)
    else:
        try:
            _save_rules(RulesConfig())
        except Exception:
            logging.debug("create empty rules file failed", exc_info=True)
    block_triggers = _load_dictionary()
    return RulesConfig(replace_rules=tuple(replace_rules), block_triggers=tuple(block_triggers))

def _save_rules(cfg: RulesConfig) -> None:
    """Сохраняет правила автозамены в Data/punto_like_rules.json.

    Пользовательский словарь (block_triggers) хранится отдельно
    в Data/punto_like_dictionary.txt и сохраняется через _save_dictionary().
    """
    payload = {
        "replace_rules": [
            {"trigger": r.trigger, "replacement": r.replacement, "is_enabled": r.is_enabled}
            for r in cfg.replace_rules
        ],
    }
    _atomic_write_text(_rules_path(), json.dumps(payload, ensure_ascii=False, indent=2))

def _reload_rules() -> None:
    global _rules_config
    with _rules_lock:
        _rules_config = _load_rules()

def _reload_dictionary() -> None:
    """Перечитывает словарь с диска, сохраняя правила автозамены.

    Ручная правка Data/punto_like_dictionary.txt применяется без перезапуска:
    вызывается при открытии трей-меню, как и перечитывание списка отключённых
    приложений.
    """
    global _rules_config
    with _rules_lock:
        words = _load_dictionary()
        _rules_config = RulesConfig(
            replace_rules=_rules_config.replace_rules,
            block_triggers=tuple(words),
        )

def _get_rules_snapshot() -> RulesConfig:
    with _rules_lock:
        return _rules_config

# ── Disabled apps blacklist ───────────────────────────────────────────────────

_disabled_apps_lock = threading.Lock()
_disabled_apps: frozenset[str] = frozenset()  # lowercased exe names

# Кэш foreground-окна для горячего пути хука: (hwnd, exe, disabled).
# Один кортеж присваивается целиком — читатели в других потоках никогда не
# увидят «половину» обновления. Сбрасывается при смене foreground (WinEvent).
_fg_info_cache: tuple[int, str, bool] = (0, "", False)


def _load_disabled_apps() -> frozenset[str]:
    """Читает Data/punto_like_disabled_apps.txt — по одному exe-имени на строку.

    Если файла нет — создаёт пустой шаблон, чтобы его было видно в Data/.
    """
    path = _disabled_apps_path()
    if not path.exists():
        try:
            _save_disabled_apps(frozenset())
        except Exception:
            logging.debug("create empty disabled apps file failed", exc_info=True)
        return frozenset()
    result: set[str] = set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            name = line.strip()
            if name and not name.startswith("#"):
                result.add(name.lower())
    except Exception:
        logging.debug("_load_disabled_apps failed", exc_info=True)
    return frozenset(result)


def _save_disabled_apps(apps: frozenset[str]) -> None:
    lines = [
        "# punto_like — список приложений, в которых скрипт полностью отключён.",
        "# Одно имя exe-файла на строку (без пути), регистр не важен.",
        "# Строки, начинающиеся с #, игнорируются.",
        "# Пример:",
        "#   notepad.exe",
        "#   game.exe",
        "",
    ]
    lines += sorted(apps)
    _atomic_write_text(_disabled_apps_path(), "\n".join(lines) + "\n")


def _invalidate_fg_cache() -> None:
    global _fg_info_cache
    _fg_info_cache = (0, "", False)


def _reload_disabled_apps() -> None:
    global _disabled_apps
    new_set = _load_disabled_apps()
    with _disabled_apps_lock:
        _disabled_apps = new_set
    _invalidate_fg_cache()
    logging.info("disabled_apps reloaded: %d entries", len(new_set))


def _toggle_disabled_for_exe(exe_lower: str) -> Optional[bool]:
    """Тоглит exe в blacklist'е и сохраняет. Возвращает новое состояние (True=disabled)."""
    if not exe_lower:
        return None
    global _disabled_apps
    with _disabled_apps_lock:
        if exe_lower in _disabled_apps:
            new_set = _disabled_apps - {exe_lower}
            now_disabled = False
        else:
            new_set = _disabled_apps | {exe_lower}
            now_disabled = True
        _disabled_apps = new_set
    try:
        _save_disabled_apps(new_set)
    except Exception:
        logging.warning("Failed to save disabled apps list", exc_info=True)
    _invalidate_fg_cache()
    return now_disabled


def _is_exe_disabled(exe: str) -> bool:
    with _disabled_apps_lock:
        return bool(exe) and exe in _disabled_apps

# ═══════════════════════════════════════════════════════════════════════════════
# Threads: worker, idle scheduler, Tk UI
# ═══════════════════════════════════════════════════════════════════════════════

def _ensure_thread_message_queue() -> None:
    """Создаёт очередь сообщений текущего потока (нужна AttachThreadInput и т.п.)."""
    if user32 is None:
        return
    try:
        msg = MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)
    except Exception:
        logging.debug("PeekMessageW(PM_NOREMOVE) failed", exc_info=True)


class _SyncTicket:
    """Состояние задачи, которую вызывающий ждёт с дедлайном (см. run_sync)."""
    __slots__ = ("done", "_lock", "_state")
    _PENDING, _RUNNING, _EXPIRED = 0, 1, 2

    def __init__(self) -> None:
        self.done = threading.Event()
        self._lock = threading.Lock()
        self._state = self._PENDING

    def try_start(self) -> bool:
        with self._lock:
            if self._state != self._PENDING:
                return False
            self._state = self._RUNNING
            return True

    def expire(self) -> None:
        with self._lock:
            if self._state == self._PENDING:
                self._state = self._EXPIRED


class _JobWorker:
    """Один поток, который по очереди выполняет все «тяжёлые» действия.

    Очередь сериализует работу с буфером обмена и чужими окнами: конвертация,
    автозамена, захват истории буфера и вставка из неё никогда не идут
    параллельно — вместо прежнего мьютекса _is_busy.
    """

    def __init__(self, name: str, max_queue: int = 128) -> None:
        self._name = name
        self._q: _Queue[Optional[tuple[str, Callable[[], None], Optional[_SyncTicket]]]] = _Queue(maxsize=max_queue)
        self._thread: Optional[threading.Thread] = None
        self._job_started_at: float = 0.0
        self._job_name: str = ""

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
            self._thread.start()

    @property
    def busy(self) -> bool:
        return self._job_started_at != 0.0

    def current_job(self) -> tuple[str, float]:
        """(имя задачи, сколько секунд она уже выполняется) или ("", 0.0)."""
        started, name = self._job_started_at, self._job_name
        if started == 0.0:
            return "", 0.0
        return name, time.monotonic() - started

    def submit(self, name: str, fn: Callable[[], None]) -> bool:
        try:
            self._q.put_nowait((name, fn, None))
            return True
        except _QueueFull:
            logging.warning("%s: очередь заполнена, задача %s отброшена", self._name, name)
            return False

    def run_sync(self, name: str, fn: Callable[[], None], timeout: float) -> bool:
        """Выполняет fn в worker'е и ждёт до timeout секунд.

        Если worker занят чем-то другим — не ждём вовсе и возвращаем False
        (как прежняя проверка _is_busy в хуке). Если не успели к дедлайну —
        задача, ещё не начавшаяся, будет пропущена; уже начатая — доработает.
        """
        if self.busy or not self._q.empty():
            return False
        ticket = _SyncTicket()
        try:
            self._q.put_nowait((name, fn, ticket))
        except _QueueFull:
            return False
        if ticket.done.wait(timeout):
            return True
        ticket.expire()
        logging.debug("%s: %s не уложилась в %.0f мс", self._name, name, timeout * 1000)
        return False

    def stop(self, timeout: float = 2.0) -> None:
        thread = self._thread
        if thread is None:
            return
        try:
            self._q.put(None, timeout=0.5)
        except _QueueFull:
            pass
        thread.join(timeout)
        self._thread = None

    def _run(self) -> None:
        _ensure_thread_message_queue()
        while True:
            item = self._q.get()
            if item is None:
                break
            name, fn, ticket = item
            if ticket is not None and not ticket.try_start():
                continue  # вызывающий уже перестал ждать — задача устарела
            self._job_name = name
            self._job_started_at = time.monotonic()
            try:
                fn()
            except Exception:
                logging.exception("%s failed", name)
            finally:
                self._job_started_at = 0.0
                self._job_name = ""
                if ticket is not None:
                    ticket.done.set()


class _IdleScheduler:
    """Отложенный запуск одной задачи после паузы во вводе.

    Один поток вместо threading.Timer на каждое нажатие клавиши. schedule()
    переносит дедлайн, cancel() снимает задачу. Каждый вызов увеличивает
    «поколение»: задача, уже переданная в worker, перед запуском проверяет,
    что её не отменили после передачи.
    """

    def __init__(self, fire: Callable[[str, Callable[[], None]], object]) -> None:
        self._fire = fire
        self._cv = threading.Condition()
        self._gen = 0
        self._deadline: Optional[float] = None
        self._job: Optional[Callable[[], None]] = None
        self._stopped = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is None:
            self._stopped = False
            self._thread = threading.Thread(target=self._run, name="idle", daemon=True)
            self._thread.start()

    def schedule(self, delay: float, job: Callable[[], None]) -> None:
        with self._cv:
            self._gen += 1
            self._deadline = time.monotonic() + delay
            self._job = job
            self._cv.notify()

    def cancel(self) -> None:
        with self._cv:
            self._gen += 1
            if self._deadline is not None:
                self._deadline = None
                self._job = None
                self._cv.notify()

    def stop(self, timeout: float = 1.0) -> None:
        with self._cv:
            self._stopped = True
            self._gen += 1
            self._cv.notify()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def _is_current(self, gen: int) -> bool:
        return gen == self._gen

    def _run(self) -> None:
        while True:
            with self._cv:
                while not self._stopped and self._deadline is None:
                    self._cv.wait()
                if self._stopped:
                    return
                remaining = self._deadline - time.monotonic()
                if remaining > 0:
                    self._cv.wait(remaining)
                    continue
                job, gen = self._job, self._gen
                self._deadline = None
                self._job = None
            if job is None:
                continue

            def guarded(job: Callable[[], None] = job, gen: int = gen) -> None:
                if self._is_current(gen):
                    job()

            try:
                self._fire("idle-rules", guarded)
            except Exception:
                logging.debug("idle fire failed", exc_info=True)


class _TkUi:
    """Единственный интерпретатор Tk на своём потоке.

    Tk не терпит несколько интерпретаторов в разных потоках одновременно,
    поэтому все окна (редактор правил, история буфера) — Toplevel этого
    потока. Задачи передаются через очередь: call(lambda root: ...).
    """

    def __init__(self) -> None:
        self._q: _Queue[Optional[Callable[[object], None]]] = _Queue()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def call(self, fn: Callable[[object], None]) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="tk-ui", daemon=True)
                self._thread.start()
        self._q.put(fn)

    def stop(self, timeout: float = 2.0) -> None:
        with self._lock:
            thread = self._thread
        if thread is None or not thread.is_alive():
            return
        self._q.put(None)
        thread.join(timeout)

    def _run(self) -> None:
        global _picker_window, _rules_editor_window
        _picker_window = None
        _rules_editor_window = None
        try:
            import tkinter as tk
            root = tk.Tk()
        except Exception:
            logging.exception("Tk init failed")
            while True:  # не копим задачи, которые некому выполнить
                try:
                    self._q.get_nowait()
                except _QueueEmpty:
                    return
        root.withdraw()

        def pump() -> None:
            while True:
                try:
                    fn = self._q.get_nowait()
                except _QueueEmpty:
                    break
                if fn is None:
                    root.quit()
                    return
                _run_guarded("ui", lambda fn=fn: fn(root))
            root.after(50, pump)

        root.after(0, pump)
        try:
            root.mainloop()
        finally:
            try:
                root.destroy()
            except Exception:
                pass
            # Все Tk-объекты должны умереть в этом же потоке. Если последний
            # объект со ссылкой на интерпретатор достанется сборщику мусора
            # другого потока (обычно — главного при выходе), Tcl аварийно
            # завершит процесс: «Tcl_AsyncDelete: async handler deleted by the
            # wrong thread». Супервизор принял бы это за краш и перезапустил бы
            # worker сразу после штатного выхода.
            _picker_window = None
            _rules_editor_window = None
            root = pump = None  # noqa: F841 — отпускаем ссылки до gc.collect()
            gc.collect()


def _worker_submit(name: str, fn: Callable[[], None]) -> bool:
    return _worker.submit(name, fn)


_worker = _JobWorker("worker")
_idle = _IdleScheduler(_worker_submit)
_ui = _TkUi()
_picker_window: object | None = None
_rules_editor_window: object | None = None

# ═══════════════════════════════════════════════════════════════════════════════
# Process-level helpers: logging, session, single instance
# ═══════════════════════════════════════════════════════════════════════════════

_WORKER_EXIT_OK: Final[int] = 0
_WORKER_EXIT_ALREADY_RUNNING: Final[int] = 10
_WORKER_EXIT_CRASH: Final[int] = 100
_SUPERVISOR_RESTART_BASE_DELAY_SECONDS: Final[float] = 1.5
_SUPERVISOR_RESTART_MAX_DELAY_SECONDS: Final[float] = 15.0
_SUPERVISOR_STABLE_UPTIME_SECONDS: Final[float] = 60.0
_fault_handler_stream: Optional[object] = None


def _raise_last_error(prefix: str) -> None:
    err = ctypes.get_last_error()
    raise OSError(err, f"{prefix} (winerror={err})")

def _show_message_box(title: str, text: str) -> None:
    try:
        user32.MessageBoxW(None, text, title, 0)
    except Exception:
        pass

def _get_session_id() -> int:
    try:
        session_id = wintypes.DWORD(0)
        pid = kernel32.GetCurrentProcessId()
        if kernel32.ProcessIdToSessionId(wintypes.DWORD(pid), ctypes.byref(session_id)):
            return int(session_id.value)
    except Exception:
        pass
    # Fallback: хотя бы различить консоль и RDP
    try:
        return 10000 if bool(user32.GetSystemMetrics(SM_REMOTESESSION)) else 0
    except Exception:
        return 0

def _is_rdp_session() -> bool:
    try:
        return bool(user32.GetSystemMetrics(SM_REMOTESESSION))
    except Exception:
        return False

def _session_suffix() -> str:
    return f"_sess{_get_session_id()}"

def _ensure_single_instance(name: str) -> HANDLE:
    full_name = f"Local\\{name}_sess{_get_session_id()}"
    h = kernel32.CreateMutexW(None, False, full_name)
    if not h:
        _raise_last_error("CreateMutexW failed")
    # ctypes.get_last_error(), а не kernel32.GetLastError(): DLL загружена с use_last_error=True
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(h)
        raise RuntimeError("Another instance is already running")
    return h

def _setup_logging() -> None:
    logger = logging.getLogger()
    if logger.handlers:
        return
    _ensure_data_dir()
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        str(DATA_DIR / f"punto_like{_session_suffix()}.log"),
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(message)s"))
    logger.addHandler(handler)

def _configure_stdio_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

def _setup_threading_excepthook() -> None:
    if getattr(_setup_threading_excepthook, "_installed", False):
        return

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is SystemExit:
            return
        logging.error(
            "Unhandled thread exception in %s",
            getattr(args.thread, "name", "thread"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = _thread_hook
    _setup_threading_excepthook._installed = True

def _setup_fault_handler() -> None:
    global _fault_handler_stream
    if getattr(_setup_fault_handler, "_installed", False):
        return
    try:
        _ensure_data_dir()
        crash_log_path = DATA_DIR / f"punto_like_fault{_session_suffix()}.log"
        _fault_handler_stream = crash_log_path.open("a", encoding="utf-8")
        faulthandler.enable(_fault_handler_stream, all_threads=True)
        _setup_fault_handler._installed = True
    except Exception:
        logging.debug("Failed to enable faulthandler", exc_info=True)

def _run_guarded(action_name: str, func: Callable[[], None]) -> None:
    try:
        func()
    except Exception:
        logging.exception("%s failed", action_name)

# ═══════════════════════════════════════════════════════════════════════════════
# WinAPI prototypes (все в одном месте)
# ═══════════════════════════════════════════════════════════════════════════════

_prototypes_ready: bool = False
_get_window_long_ptr: Optional[Callable[..., int]] = None

def _proto(dll: object, name: str, restype: object, *argtypes: object) -> None:
    fn = getattr(dll, name)
    fn.argtypes = list(argtypes)
    fn.restype = restype

def _setup_winapi_prototypes() -> None:
    global _prototypes_ready, _get_window_long_ptr
    if _prototypes_ready:
        return
    BOOL, UINT, DWORD, INT = wintypes.BOOL, wintypes.UINT, wintypes.DWORD, ctypes.c_int
    LPCWSTR, LPWSTR = wintypes.LPCWSTR, wintypes.LPWSTR
    VOIDP = ctypes.c_void_p

    # ── user32: сообщения, хоткеи, таймеры ──
    _proto(user32, "RegisterHotKey", BOOL, HANDLE, INT, UINT, UINT)
    _proto(user32, "UnregisterHotKey", BOOL, HANDLE, INT)
    _proto(user32, "GetMessageW", INT, ctypes.POINTER(MSG), HANDLE, UINT, UINT)
    _proto(user32, "PeekMessageW", BOOL, ctypes.POINTER(MSG), HANDLE, UINT, UINT, UINT)
    _proto(user32, "TranslateMessage", BOOL, ctypes.POINTER(MSG))
    _proto(user32, "DispatchMessageW", LPARAM, ctypes.POINTER(MSG))
    _proto(user32, "PostMessageW", BOOL, HANDLE, UINT, WPARAM, LPARAM)
    _proto(user32, "PostThreadMessageW", BOOL, DWORD, UINT, WPARAM, LPARAM)
    _proto(user32, "PostQuitMessage", None, INT)
    _proto(user32, "SendMessageTimeoutW", LPARAM,
           HANDLE, UINT, WPARAM, LPARAM, UINT, UINT, ctypes.POINTER(ctypes.c_ulonglong))
    _proto(user32, "SetTimer", UINT_PTR, HANDLE, UINT_PTR, UINT, VOIDP)
    _proto(user32, "KillTimer", BOOL, HANDLE, UINT_PTR)
    _proto(user32, "GetLastInputInfo", BOOL, ctypes.POINTER(LASTINPUTINFO))
    _proto(user32, "MessageBeep", BOOL, UINT)
    _proto(user32, "MessageBoxW", INT, HANDLE, LPCWSTR, LPCWSTR, UINT)
    _proto(user32, "GetSystemMetrics", INT, INT)

    # ── user32: ввод ──
    _proto(user32, "SendInput", UINT, UINT, ctypes.POINTER(INPUT), INT)
    _proto(user32, "MapVirtualKeyW", UINT, UINT, UINT)
    _proto(user32, "GetAsyncKeyState", wintypes.SHORT, INT)
    _proto(user32, "SetWindowsHookExW", HANDLE, INT, VOIDP, HANDLE, DWORD)
    _proto(user32, "CallNextHookEx", LONG_PTR, HANDLE, INT, WPARAM, LPARAM)
    _proto(user32, "UnhookWindowsHookEx", BOOL, HANDLE)
    _proto(user32, "SetWinEventHook", HANDLE, DWORD, DWORD, HANDLE, VOIDP, DWORD, DWORD, DWORD)
    _proto(user32, "UnhookWinEvent", BOOL, HANDLE)

    # ── user32: буфер обмена ──
    _proto(user32, "OpenClipboard", BOOL, HANDLE)
    _proto(user32, "CloseClipboard", BOOL)
    _proto(user32, "EmptyClipboard", BOOL)
    _proto(user32, "IsClipboardFormatAvailable", BOOL, UINT)
    _proto(user32, "GetClipboardData", HGLOBAL, UINT)
    _proto(user32, "SetClipboardData", HANDLE, UINT, HGLOBAL)
    _proto(user32, "RegisterClipboardFormatW", UINT, LPCWSTR)
    _proto(user32, "GetClipboardSequenceNumber", DWORD)
    _proto(user32, "EnumClipboardFormats", UINT, UINT)
    _proto(user32, "GetClipboardFormatNameW", INT, UINT, LPWSTR, INT)
    _proto(user32, "AddClipboardFormatListener", BOOL, HANDLE)
    _proto(user32, "RemoveClipboardFormatListener", BOOL, HANDLE)

    # ── user32: окна, фокус, раскладка ──
    _proto(user32, "LoadKeyboardLayoutW", HANDLE, LPCWSTR, UINT)
    _proto(user32, "GetForegroundWindow", HANDLE)
    _proto(user32, "SetForegroundWindow", BOOL, HANDLE)
    _proto(user32, "BringWindowToTop", BOOL, HANDLE)
    _proto(user32, "AttachThreadInput", BOOL, DWORD, DWORD, BOOL)
    _proto(user32, "GetWindowThreadProcessId", DWORD, HANDLE, ctypes.POINTER(DWORD))
    _proto(user32, "GetClassNameW", INT, HANDLE, LPWSTR, INT)
    _proto(user32, "GetGUIThreadInfo", BOOL, DWORD, ctypes.POINTER(GUITHREADINFO))
    if hasattr(user32, "GetWindowLongPtrW"):
        _proto(user32, "GetWindowLongPtrW", LONG_PTR, HANDLE, INT)
        _get_window_long_ptr = user32.GetWindowLongPtrW
    else:  # 32-битный user32 экспортирует только GetWindowLongW
        _proto(user32, "GetWindowLongW", wintypes.LONG, HANDLE, INT)
        _get_window_long_ptr = user32.GetWindowLongW
    _proto(user32, "RegisterClassW", wintypes.ATOM, ctypes.POINTER(WNDCLASSW))
    _proto(user32, "UnregisterClassW", BOOL, LPCWSTR, HANDLE)
    _proto(user32, "CreateWindowExW", HANDLE,
           DWORD, LPCWSTR, LPCWSTR, DWORD, INT, INT, INT, INT, HANDLE, HANDLE, HANDLE, VOIDP)
    _proto(user32, "DestroyWindow", BOOL, HANDLE)
    _proto(user32, "DefWindowProcW", LONG_PTR, HANDLE, UINT, WPARAM, LPARAM)
    _proto(user32, "RegisterWindowMessageW", UINT, LPCWSTR)
    _proto(user32, "LoadImageW", HANDLE, HANDLE, LPCWSTR, UINT, INT, INT, UINT)
    _proto(user32, "LoadIconW", HANDLE, HANDLE, VOIDP)
    _proto(user32, "DestroyIcon", BOOL, HANDLE)
    _proto(user32, "CreatePopupMenu", HANDLE)
    _proto(user32, "AppendMenuW", BOOL, HANDLE, UINT, ctypes.c_size_t, LPCWSTR)
    _proto(user32, "TrackPopupMenu", BOOL, HANDLE, UINT, INT, INT, INT, HANDLE, VOIDP)
    _proto(user32, "DestroyMenu", BOOL, HANDLE)
    _proto(user32, "GetCursorPos", BOOL, ctypes.POINTER(POINT))
    _proto(user32, "GetDC", HANDLE, HANDLE)
    _proto(user32, "ReleaseDC", INT, HANDLE, HANDLE)

    # ── kernel32 ──
    _proto(kernel32, "GlobalAlloc", HGLOBAL, UINT, ctypes.c_size_t)
    _proto(kernel32, "GlobalFree", HGLOBAL, HGLOBAL)
    _proto(kernel32, "GlobalLock", VOIDP, HGLOBAL)
    _proto(kernel32, "GlobalUnlock", BOOL, HGLOBAL)
    _proto(kernel32, "GlobalSize", ctypes.c_size_t, HGLOBAL)
    _proto(kernel32, "GetModuleHandleW", HANDLE, LPCWSTR)
    _proto(kernel32, "CreateMutexW", HANDLE, VOIDP, BOOL, LPCWSTR)
    _proto(kernel32, "CloseHandle", BOOL, HANDLE)
    _proto(kernel32, "GetCurrentProcessId", DWORD)
    _proto(kernel32, "GetCurrentThreadId", DWORD)
    _proto(kernel32, "ProcessIdToSessionId", BOOL, DWORD, ctypes.POINTER(DWORD))
    _proto(kernel32, "OpenProcess", HANDLE, DWORD, BOOL, DWORD)
    _proto(kernel32, "QueryFullProcessImageNameW", BOOL, HANDLE, DWORD, LPWSTR, ctypes.POINTER(DWORD))
    _proto(kernel32, "GetTickCount", DWORD)
    _proto(kernel32, "CreateJobObjectW", HANDLE, VOIDP, LPCWSTR)
    _proto(kernel32, "SetInformationJobObject", BOOL, HANDLE, INT, VOIDP, DWORD)
    _proto(kernel32, "AssignProcessToJobObject", BOOL, HANDLE, HANDLE)

    # ── gdi32 ──
    _proto(gdi32, "GetObjectW", INT, HANDLE, INT, VOIDP)
    _proto(gdi32, "GetDIBits", INT, HANDLE, HANDLE, UINT, UINT, VOIDP, VOIDP, UINT)
    _proto(gdi32, "CreateDIBSection", HANDLE, HANDLE, VOIDP, UINT, ctypes.POINTER(VOIDP), HANDLE, DWORD)
    _proto(gdi32, "DeleteObject", BOOL, HANDLE)

    # ── shell32 ──
    _proto(shell32, "Shell_NotifyIconW", BOOL, DWORD, ctypes.POINTER(NOTIFYICONDATAW))

    _prototypes_ready = True


def _hwnd_value(h: object) -> int:
    """HWND/HANDLE в любом представлении (int, None, c_void_p) → int."""
    if not h:
        return 0
    if isinstance(h, int):
        return h
    return int(ctypes.cast(h, ctypes.c_void_p).value or 0)

# ═══════════════════════════════════════════════════════════════════════════════
# Windows, focus, processes
# ═══════════════════════════════════════════════════════════════════════════════

def _get_class_name(hwnd: object) -> str:
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    n = user32.GetClassNameW(hwnd, buf, len(buf))
    if n <= 0:
        return ""
    return buf.value

def _is_edit_like_class(class_name: str) -> bool:
    c = (class_name or "").lower()
    return c == "edit" or c.startswith("richedit")

def _get_focused_control_hwnd() -> int:
    """hwnd контрола с фокусом в foreground-потоке (0, если не определить).

    Только локальные вызовы (GetGUIThreadInfo, GetClassNameW) — безопасно
    звать из колбэка хука.
    """
    hwnd_fg = user32.GetForegroundWindow()
    if not hwnd_fg:
        return 0
    tid = user32.GetWindowThreadProcessId(hwnd_fg, None)
    if tid == 0:
        return 0
    gti = GUITHREADINFO()
    gti.cbSize = ctypes.sizeof(GUITHREADINFO)
    if not user32.GetGUIThreadInfo(tid, ctypes.byref(gti)):
        return 0
    focus = _hwnd_value(gti.hwndFocus)
    caret = _hwnd_value(gti.hwndCaret)
    for hwnd in (focus, caret):
        if hwnd and _is_edit_like_class(_get_class_name(hwnd)):
            return hwnd
    return focus or caret

def _is_password_edit(hwnd: object) -> bool:
    """True, если контрол — поле пароля (стиль ES_PASSWORD).

    Читается через GetWindowLongPtrW без оконных сообщений — дёшево и безопасно
    на горячем пути хука. Редкую маску через EM_SETPASSWORDCHAR без ES_PASSWORD
    намеренно не ловим, чтобы не слать сообщение на каждое нажатие.
    """
    if not hwnd or _get_window_long_ptr is None:
        return False
    try:
        return bool(int(_get_window_long_ptr(hwnd, GWL_STYLE)) & ES_PASSWORD)
    except Exception:
        return False

def _is_text_input_focus(hwnd: object) -> bool:
    """Стандартный Edit/RichEdit, но не поле пароля.

    По полям пароля не читаем текст и не применяем правила — ни по пробелу,
    ни по таймауту.
    """
    if not hwnd:
        return False
    if not _is_edit_like_class(_get_class_name(hwnd)):
        return False
    return not _is_password_edit(hwnd)

def _get_exe_name_for_hwnd(hwnd_value: int) -> str:
    """Имя exe-файла (lowercase, без пути) для hwnd."""
    if hwnd_value == 0:
        return ""
    pid = wintypes.DWORD(0)
    tid = user32.GetWindowThreadProcessId(hwnd_value, ctypes.byref(pid))
    if tid == 0 or pid.value == 0:
        return ""
    hproc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not hproc:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if not kernel32.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(size)) or size.value == 0:
            return ""
        full = buf.value
        return full[full.rfind("\\") + 1:].lower()
    except Exception:
        return ""
    finally:
        kernel32.CloseHandle(hproc)

def _foreground_info() -> tuple[int, str, bool]:
    """(hwnd, exe, отключён_ли) для foreground-окна.

    Горячий путь хука: при попадании в кэш — один GetForegroundWindow, без
    OpenProcess. Кэш сбрасывается WinEvent-хуком при смене foreground.
    """
    global _fg_info_cache
    hwnd = _hwnd_value(user32.GetForegroundWindow())
    if hwnd == 0:
        return 0, "", False
    cached = _fg_info_cache
    if cached[0] == hwnd:
        return cached
    exe = _get_exe_name_for_hwnd(hwnd)
    info = (hwnd, exe, _is_exe_disabled(exe))
    _fg_info_cache = info
    return info

# ── Foreground tracking (поток трея) ─────────────────────────────────────────
#
# При правом клике по иконке трея foreground уже успевает уйти на
# Shell_TrayWnd, и GetForegroundWindow() возвращает explorer.exe. Поэтому
# слушаем EVENT_SYSTEM_FOREGROUND и запоминаем последнее «настоящее» окно.

_SHELL_WINDOW_CLASSES: Final[frozenset[str]] = frozenset({
    "Shell_TrayWnd",
    "Shell_SecondaryTrayWnd",
    "NotifyIconOverflowWindow",
    "WorkerW",
    "Progman",
    "Button",  # Start button popup
})

# explorer.exe сюда не кладём: окна Проводника (CabinetWClass) — полноценные
# пользовательские окна, их отсекаем по классу выше.
_SHELL_EXES_FOR_FG_TRACKING: Final[frozenset[str]] = frozenset({
    "searchhost.exe",
    "searchapp.exe",
    "startmenuexperiencehost.exe",
    "shellexperiencehost.exe",
    "textinputhost.exe",
})

_last_real_fg_hwnd: int = 0
_fg_event_hook: int = 0
_fg_event_proc_ref: object | None = None


def _is_shell_window(hwnd_value: int) -> bool:
    if hwnd_value == 0:
        return True
    if _get_class_name(hwnd_value) in _SHELL_WINDOW_CLASSES:
        return True
    return _get_exe_name_for_hwnd(hwnd_value) in _SHELL_EXES_FOR_FG_TRACKING


def _on_foreground_event(hook, event, hwnd, id_object, id_child, thread_id, time_stamp) -> None:
    global _last_real_fg_hwnd
    try:
        if event != EVENT_SYSTEM_FOREGROUND or id_object != 0:  # OBJECT_WINDOW
            return
        _invalidate_fg_cache()
        hwnd_value = _hwnd_value(hwnd)
        if hwnd_value == 0 or hwnd_value == _hwnd_value(_tray_window_handle):
            return
        if _is_shell_window(hwnd_value):
            return
        _last_real_fg_hwnd = hwnd_value
    except Exception:
        logging.debug("foreground event handler error", exc_info=True)


def _install_foreground_event_hook() -> None:
    global _fg_event_hook, _fg_event_proc_ref
    if _fg_event_hook:
        return
    _fg_event_proc_ref = _WINEVENTPROC(_on_foreground_event)
    handle = user32.SetWinEventHook(
        EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND,
        None, ctypes.cast(_fg_event_proc_ref, ctypes.c_void_p),
        0, 0, WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
    )
    _fg_event_hook = _hwnd_value(handle)
    if not _fg_event_hook:
        logging.warning("SetWinEventHook(EVENT_SYSTEM_FOREGROUND) failed")
        _fg_event_proc_ref = None


def _uninstall_foreground_event_hook() -> None:
    global _fg_event_hook, _fg_event_proc_ref
    if _fg_event_hook:
        try:
            user32.UnhookWinEvent(_fg_event_hook)
        except Exception:
            logging.debug("UnhookWinEvent failed", exc_info=True)
    _fg_event_hook = 0
    _fg_event_proc_ref = None


def _resolve_real_foreground_hwnd() -> int:
    """Текущее foreground-окно, а если это шелл (таскбар/пуск) — последнее реальное."""
    fg = _hwnd_value(user32.GetForegroundWindow())
    if fg and not _is_shell_window(fg):
        return fg
    return _last_real_fg_hwnd

# ═══════════════════════════════════════════════════════════════════════════════
# SendMessage к чужим окнам (только из worker'а)
# ═══════════════════════════════════════════════════════════════════════════════

_WORKER_SEND_TIMEOUT_MS: Final[int] = 200

def _sendmsg(hwnd: object, msg: int, wparam: int = 0, lparam: int = 0) -> int:
    """SendMessageTimeoutW с защитой от зависшего окна; 0 при таймауте/ошибке."""
    res = ctypes.c_ulonglong(0)
    ok = user32.SendMessageTimeoutW(
        hwnd, msg, wparam, lparam,
        SMTO_ABORTIFHUNG | SMTO_BLOCK, _WORKER_SEND_TIMEOUT_MS, ctypes.byref(res),
    )
    return int(res.value) if ok else 0

def _sendmsg_ok(hwnd: object, msg: int, wparam: int, lparam: int,
                timeout_ms: int = _WORKER_SEND_TIMEOUT_MS) -> bool:
    """SendMessageTimeoutW, где важен только факт обработки (EM_SETSEL и т.п.)."""
    res = ctypes.c_ulonglong(0)
    return bool(user32.SendMessageTimeoutW(
        hwnd, msg, wparam, lparam,
        SMTO_ABORTIFHUNG | SMTO_BLOCK, timeout_ms, ctypes.byref(res),
    ))

# ═══════════════════════════════════════════════════════════════════════════════
# Keyboard input
# ═══════════════════════════════════════════════════════════════════════════════

_scan_codes: dict[int, int] = {}

def _scan_code_for_vk(vk: int) -> int:
    """Скан-код для VK (кэш). Часть приложений и RDP без него капризничают."""
    code = _scan_codes.get(vk)
    if code is None:
        try:
            code = int(user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)) & 0xFF if user32 is not None else 0
        except Exception:
            code = 0
        _scan_codes[vk] = code
    return code

def _key_input(vk: int, is_up: bool) -> INPUT:
    flags = KEYEVENTF_KEYUP if is_up else 0
    if vk in _EXTENDED_VKS:
        flags |= KEYEVENTF_EXTENDEDKEY
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki = KEYBDINPUT(wVk=vk, wScan=_scan_code_for_vk(vk), dwFlags=flags, time=0, dwExtraInfo=_INJECT_TAG)
    return inp

def _build_unicode_inputs(text: str) -> list[INPUT]:
    """События KEYEVENTF_UNICODE (down+up) на каждую UTF-16 единицу текста."""
    inputs: list[INPUT] = []
    data = text.encode("utf-16-le")
    for (unit,) in struct.iter_unpack("<H", data):
        for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
            inp = INPUT()
            inp.type = INPUT_KEYBOARD
            inp.ki = KEYBDINPUT(wVk=0, wScan=unit, dwFlags=flags, time=0, dwExtraInfo=_INJECT_TAG)
            inputs.append(inp)
    return inputs

def _send_input(inputs: list[INPUT]) -> None:
    if not inputs:
        return
    arr = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        _raise_last_error("SendInput failed")

def _send_input_chunked(inputs: list[INPUT], chunk: int = 1000) -> None:
    for i in range(0, len(inputs), chunk):
        _send_input(inputs[i:i + chunk])

def _is_any_vk_pressed(vks: frozenset[int]) -> bool:
    for vk in vks:
        if user32.GetAsyncKeyState(vk) & 0x8000:
            return True
    return False

def _physical_modifier_release_events() -> list[INPUT]:
    """keyup для модификаторов, физически зажатых пользователем.

    Ставится в начало синтетического батча: иначе наш Ctrl+C превратится,
    например, в Ctrl+Shift+C (Inspector в Firefox), а Shift+Home при всё ещё
    зажатом Ctrl от хоткея Ctrl+Ins — в Ctrl+Shift+Home (выделение до начала
    документа). Сбрасываем по конкретным L/R VK: одиночный VK_SHIFT keyup не
    всегда снимает физически зажатый правый Shift.
    """
    return [_key_input(vk, True) for vk in _RELEASE_MODIFIER_VKS if user32.GetAsyncKeyState(vk) & 0x8000]

def _press_combo(modifier_vk: int, vk_tap: int, timings: Timings) -> None:
    """Модификатор+клавиша с паузами между событиями (надёжнее для RDP/VM).

    Модификатор отпускается в finally — даже при ошибке SendInput он не залипнет.
    """
    _send_input(_physical_modifier_release_events() + [_key_input(modifier_vk, False)])
    try:
        time.sleep(timings.between_key_events_seconds)
        _send_input([_key_input(vk_tap, False), _key_input(vk_tap, True)])
        time.sleep(timings.between_key_events_seconds)
    finally:
        _send_input([_key_input(modifier_vk, True)])
        time.sleep(timings.between_key_events_seconds)

def _press_combo_ctrl(vk_tap: int, timings: Timings) -> None:
    _press_combo(VK_CONTROL, vk_tap, timings)

def _press_combo_shift(vk_tap: int, timings: Timings) -> None:
    _press_combo(VK_SHIFT, vk_tap, timings)

def _select_last_chars(count: int, timings: Timings) -> None:
    """Shift+Left × count — выделить только что вставленный текст."""
    if count <= 0:
        return
    taps: list[INPUT] = []
    for _ in range(int(count)):
        taps.append(_key_input(VK_LEFT, False))
        taps.append(_key_input(VK_LEFT, True))
    _send_input(_physical_modifier_release_events() + [_key_input(VK_SHIFT, False)])
    try:
        _send_input_chunked(taps)
    finally:
        _send_input([_key_input(VK_SHIFT, True)])
    time.sleep(timings.between_key_events_seconds)

def _collapse_selection_to_right() -> None:
    _send_input([_key_input(VK_RIGHT, False), _key_input(VK_RIGHT, True)])

def _caret_units(text: str) -> int:
    """Сколько нажатий стрелки занимает текст: \\r\\n — одна позиция каретки."""
    return len(text.replace("\r\n", "\n"))

def _text_safe_for_typing(text: str, max_len: int) -> bool:
    """Можно ли набрать текст через KEYEVENTF_UNICODE.

    Перевод строки набором в чатах означает «отправить», Tab уводит фокус —
    такой текст и слишком длинный вставляем через буфер.
    """
    return bool(text) and len(text) <= max_len and not any(ch in text for ch in "\r\n\t")

def _type_text(text: str) -> None:
    _send_input_chunked(_build_unicode_inputs(text))

def _force_foreground_window(hwnd: object) -> None:
    """Надёжно делает окно foreground (для трей-меню и возврата фокуса).

    Голый SetForegroundWindow часто молча проваливается из-за foreground-lock'а.
    1) AttachThreadInput к потоку текущего foreground-окна + SetForegroundWindow.
    2) Если не помогло — «Alt-трюк»: короткое синтетическое нажатие Alt снимает
       lock, после чего SetForegroundWindow проходит. Наши события помечены
       _INJECT_TAG и хуком игнорируются.
    """
    target = _hwnd_value(hwnd)
    if not target:
        return

    def is_foreground() -> bool:
        return _hwnd_value(user32.GetForegroundWindow()) == target

    try:
        fg = _hwnd_value(user32.GetForegroundWindow())
        our_tid = int(kernel32.GetCurrentThreadId())
        fg_tid = int(user32.GetWindowThreadProcessId(fg, None)) if fg else 0
        attached = False
        if fg_tid and fg_tid != our_tid:
            attached = bool(user32.AttachThreadInput(our_tid, fg_tid, True))
        try:
            user32.BringWindowToTop(target)
            user32.SetForegroundWindow(target)
        finally:
            if attached:
                user32.AttachThreadInput(our_tid, fg_tid, False)

        if not is_foreground():
            try:
                _send_input([_key_input(VK_MENU, False), _key_input(VK_MENU, True)])
            except Exception:
                logging.debug("Alt-trick send failed", exc_info=True)
            time.sleep(0.03)  # SendInput асинхронен — даём ОС обработать Alt
            for _ in range(3):
                user32.BringWindowToTop(target)
                user32.SetForegroundWindow(target)
                if is_foreground():
                    break
                time.sleep(0.02)
    except Exception:
        logging.debug("_force_foreground_window failed", exc_info=True)

# ═══════════════════════════════════════════════════════════════════════════════
# Layout switching
# ═══════════════════════════════════════════════════════════════════════════════

_hkl_cache: dict[str, int] = {}

def _count_mappable_chars(text: str) -> tuple[int, int]:
    en_like = 0
    ru_like = 0
    for ch in text:
        lower = ch.lower()
        if lower in _EN_TO_RU:
            en_like += 1
        elif lower in _RU_TO_EN:
            ru_like += 1
    return en_like, ru_like

def _dominant_layout(text: str) -> Optional[str]:
    en_like, ru_like = _count_mappable_chars(text)
    if ru_like > en_like:
        return LAYOUT_RU
    if en_like > ru_like:
        return LAYOUT_EN
    return None

def _switch_input_language_for_foreground(layout_id: str) -> None:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return
    hkl = _hkl_cache.get(layout_id)
    if hkl is None:
        hkl = _hwnd_value(user32.LoadKeyboardLayoutW(layout_id, 0))
        if not hkl:
            _raise_last_error(f"LoadKeyboardLayoutW failed for {layout_id}")
        _hkl_cache[layout_id] = hkl
    user32.PostMessageW(hwnd, WM_INPUTLANGCHANGEREQUEST, 0, hkl)

def _switch_layout_toward_text(text: str) -> None:
    """Переключает раскладку активного окна на язык, преобладающий в тексте."""
    layout = _dominant_layout(text)
    if layout is not None:
        _switch_input_language_for_foreground(layout)

# ═══════════════════════════════════════════════════════════════════════════════
# Text conversion (layout & case) — чистые функции
# ═══════════════════════════════════════════════════════════════════════════════

def convert_keyboard_layout(text: str) -> str:
    if not text:
        return text

    # Направление определяем по составу текста, чтобы корректно обработать
    # символы из обеих таблиц (напр. «.»: EN-клавиша «.» → «ю», но RU «.» — это
    # клавиша «/»).
    en_like, ru_like = _count_mappable_chars(text)
    ru_to_en_first = ru_like >= en_like
    primary, secondary = (_RU_TO_EN, _EN_TO_RU) if ru_to_en_first else (_EN_TO_RU, _RU_TO_EN)

    def convert_char(ch: str) -> str:
        lower = ch.lower()
        mapped = primary.get(lower)
        if mapped is None:
            mapped = secondary.get(lower)
            if mapped is None:
                return ch
        return mapped.upper() if ch.isupper() else mapped

    return "".join(convert_char(c) for c in text)

def _is_all_upper_alpha(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    return bool(letters) and all(ch.isupper() for ch in letters)

def _is_all_lower_alpha(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    return bool(letters) and all(ch.islower() for ch in letters)

def _is_title_first_upper_rest_lower(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    return bool(letters) and letters[0].isupper() and all(ch.islower() for ch in letters[1:])

def _to_title_first_upper_rest_lower(text: str) -> str:
    chars = list(text)
    first_alpha_done = False
    for i, ch in enumerate(chars):
        if not ch.isalpha():
            continue
        chars[i] = ch.lower() if first_alpha_done else ch.upper()
        first_alpha_done = True
    return "".join(chars)

def toggle_case_selected_fragment(text: str) -> str:
    """Цикл регистра: «abc» → «Abc» → «ABC» → «abc»; смешанный → нижний."""
    if not text:
        return text
    if _is_all_lower_alpha(text):
        return _to_title_first_upper_rest_lower(text)
    if _is_title_first_upper_rest_lower(text):
        upper = text.upper()
        # Одна заглавная буква («A») уже и Title, и UPPER — сразу в нижний,
        # иначе хоткей на ней ничего не меняет.
        return upper if upper != text else text.lower()
    return text.lower()

def _layout_kind_for_char(ch: str) -> str:
    if not ch or not ch.isalpha():
        return "other"
    lower = ch.lower()
    if lower in _EN_TO_RU:
        return "en"
    if lower in _RU_TO_EN:
        return "ru"
    return "other"

def _find_run_before_caret(text: str, caret_pos: int) -> Optional[tuple[int, int, str]]:
    """(start, end, kind) — фрагмент одной раскладки до каретки.

    Run прерывается только на границе строки (\\r, \\n) либо на букве другой
    раскладки. Знаки препинания и пробелы проходятся насквозь, чтобы
    Ctrl+Insert чинил всю строку, а не последнее слово после точки.
    Языковая граница сохранена: на «привет vbh|» отдаём только «vbh».
    """
    if caret_pos <= 0:
        return None
    end = caret_pos
    i = caret_pos - 1

    while i >= 0 and _layout_kind_for_char(text[i]) == "other":
        if text[i] in "\r\n":
            return None
        i -= 1
    if i < 0:
        return None
    kind = _layout_kind_for_char(text[i])
    i -= 1
    while i >= 0:
        ch = text[i]
        k = _layout_kind_for_char(ch)
        if k == "other":
            if ch in "\r\n":
                break
            i -= 1
            continue
        if k != kind:
            break
        i -= 1
    return i + 1, end, kind

def _transform_run_before_caret_text(
    text: str,
    caret_pos: int,
    transform: Callable[[str], str],
) -> Optional[tuple[int, int, str]]:
    """Фрагмент перед кареткой (по правилу Ctrl+Ins) и его новое значение.

    (start, end, new_fragment) или None — фрагмента нет или transform его не
    меняет. Общая основа для Ctrl+Ins (раскладка) и Ctrl+F9 (регистр).
    """
    run = _find_run_before_caret(text, caret_pos)
    if run is None:
        return None
    start, end, _kind = run
    fragment = text[start:end]
    new_fragment = transform(fragment)
    if new_fragment == fragment:
        return None
    return start, end, new_fragment

def _is_word_char(ch: str) -> bool:
    """Буква любой раскладки или цифра («file2», «привет123»)."""
    return ch.isalnum()

def _find_word_bounds_at_caret(text: str, caret_pos: int) -> Optional[tuple[int, int]]:
    """Границы слова, которого касается каретка.

    Справа от каретки буква/цифра — берём слово справа, иначе слово слева.
    None — каретка в пробелах/пунктуации.
    """
    n = len(text)
    if n == 0:
        return None
    caret = max(0, min(caret_pos, n))

    if caret < n and _is_word_char(text[caret]):
        anchor = caret
    elif caret > 0 and _is_word_char(text[caret - 1]):
        anchor = caret - 1
    else:
        return None

    start = anchor
    while start > 0 and _is_word_char(text[start - 1]):
        start -= 1
    end = anchor + 1
    while end < n and _is_word_char(text[end]):
        end += 1
    return start, end

# ═══════════════════════════════════════════════════════════════════════════════
# Rule matching — чистые функции
# ═══════════════════════════════════════════════════════════════════════════════

_BLOCK_SENTINEL: Final[TextRule] = TextRule(trigger="__BLOCK__", replacement="")

def _compute_max_trigger_len(cfg: RulesConfig) -> int:
    lengths = [len(r.trigger) for r in cfg.replace_rules if r.is_enabled]
    lengths += [len(t) for t in cfg.block_triggers]
    return max(lengths, default=0)

def _match_or_block(
    cfg: RulesConfig,
    window: str,
    full_text: str,
    window_abs_start: int,
) -> TextRule | None:
    """Самое длинное правило, чей триггер заканчивает window и стоит на границе слова.

    _BLOCK_SENTINEL — если окно заканчивается словом из словаря «не заменять».
    """
    for bt in cfg.block_triggers:
        if bt and window.endswith(bt):
            return _BLOCK_SENTINEL

    matched_rule: TextRule | None = None
    for r in cfg.replace_rules:
        if not r.is_enabled or not r.trigger or not window.endswith(r.trigger):
            continue
        abs_trigger_start = window_abs_start + len(window) - len(r.trigger)
        if abs_trigger_start > 0 and full_text[abs_trigger_start - 1] not in WORD_SEPARATORS:
            continue
        if matched_rule is None or len(r.trigger) > len(matched_rule.trigger):
            matched_rule = r
    return matched_rule

# ═══════════════════════════════════════════════════════════════════════════════
# Edit control helpers (EM_GETSEL, EM_REPLACESEL) — только из worker'а
# ═══════════════════════════════════════════════════════════════════════════════

def _edit_get_sel(hwnd: object) -> Optional[tuple[int, int]]:
    """(start, end) выделения в Edit/RichEdit; None — не Edit или окно не ответило."""
    if not hwnd or not _is_edit_like_class(_get_class_name(hwnd)):
        return None
    start = wintypes.DWORD(0)
    end = wintypes.DWORD(0)
    if not _sendmsg_ok(hwnd, EM_GETSEL, ctypes.addressof(start), ctypes.addressof(end)):
        return None
    return int(start.value), int(end.value)

def _get_collapsed_caret_from_edit(hwnd: object) -> Optional[int]:
    sel = _edit_get_sel(hwnd)
    if sel is None or sel[0] != sel[1]:
        return None
    return sel[1]

def _read_edit_full_text(hwnd: object) -> str:
    total_len = _sendmsg(hwnd, WM_GETTEXTLENGTH)
    if total_len <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(total_len + 1)
    _sendmsg(hwnd, WM_GETTEXT, total_len + 1, ctypes.addressof(buf))
    return buf.value

def _try_get_selected_text_from_edit(hwnd: object, max_len: int) -> Optional[str]:
    sel = _edit_get_sel(hwnd)
    if sel is None:
        return None
    sel_start, sel_end = sel
    if sel_end <= sel_start or (sel_end - sel_start) > max_len:
        return None
    text = _read_edit_full_text(hwnd)
    if not text:
        return None
    return text[sel_start:sel_end]

def _try_replace_selection_in_edit(hwnd: object, text: str, restore_selection: bool = True) -> bool:
    if not hwnd or not _is_edit_like_class(_get_class_name(hwnd)):
        return False
    sel = _edit_get_sel(hwnd) if restore_selection else None
    buf = ctypes.create_unicode_buffer(text)
    if not _sendmsg_ok(hwnd, EM_REPLACESEL, 1, ctypes.addressof(buf)):
        return False
    if restore_selection and sel is not None:
        s = sel[0]
        _sendmsg_ok(hwnd, EM_SETSEL, s, s + len(text))
    return True

def _replace_range_in_edit_safely(
    hwnd: object,
    start: int,
    end: int,
    expected_text: str,
    replacement: str,
    caret_after: int,
) -> bool:
    """Заменяет [start, end) на replacement, только если там всё ещё expected_text."""
    if not hwnd or start < 0 or end < start:
        return False

    current_text = _read_edit_full_text(hwnd)
    if not current_text or end > len(current_text) or current_text[start:end] != expected_text:
        return False

    if not _sendmsg_ok(hwnd, EM_SETSEL, start, end):
        return False
    selected_now = _try_get_selected_text_from_edit(hwnd, max(len(expected_text), 1))
    if selected_now != expected_text:
        _sendmsg_ok(hwnd, EM_SETSEL, end, end)
        return False

    buf = ctypes.create_unicode_buffer(replacement)
    _sendmsg_ok(hwnd, EM_REPLACESEL, 1, ctypes.addressof(buf))
    _sendmsg_ok(hwnd, EM_SETSEL, caret_after, caret_after)
    return True

# ═══════════════════════════════════════════════════════════════════════════════
# Runtime state
# ═══════════════════════════════════════════════════════════════════════════════

_timings: Timings = Timings()
_is_paused: bool = False
_active_window_only: bool = False
_allowed_hwnd: int = 0

# ═══════════════════════════════════════════════════════════════════════════════
# Clipboard: low-level
# ═══════════════════════════════════════════════════════════════════════════════

_registered_formats: dict[str, int] = {}

def _registered_format(name: str) -> int:
    fmt = _registered_formats.get(name)
    if fmt is None:
        fmt = int(user32.RegisterClipboardFormatW(name))
        _registered_formats[name] = fmt
    return fmt

def _cf_png() -> int:
    return _registered_format(PNG_CLIPBOARD_FORMAT_NAME)

def _open_clipboard_with_retry(timings: Timings) -> None:
    for _ in range(timings.open_clipboard_retries):
        if user32.OpenClipboard(None):
            return
        time.sleep(timings.open_clipboard_retry_delay_seconds)
    _raise_last_error("OpenClipboard failed (clipboard busy)")

def _clipboard_read_bytes_from_open(fmt: int) -> bytes:
    h_data = user32.GetClipboardData(fmt)
    if not h_data:
        return b""
    ptr = kernel32.GlobalLock(h_data)
    if not ptr:
        _raise_last_error("GlobalLock failed")
    try:
        size = int(kernel32.GlobalSize(h_data))
        if size <= 0:
            return b""
        return ctypes.string_at(ptr, size)
    finally:
        kernel32.GlobalUnlock(h_data)

def _clipboard_read_text_from_open() -> str:
    raw = _clipboard_read_bytes_from_open(CF_UNICODETEXT)
    if not raw:
        return ""
    return raw.decode("utf-16le", errors="ignore").split("\x00", 1)[0]

def _clipboard_get_text(timings: Timings) -> str:
    _open_clipboard_with_retry(timings)
    try:
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return ""
        return _clipboard_read_text_from_open()
    finally:
        user32.CloseClipboard()

def _clipboard_set_format_bytes_from_open(fmt: int, data: bytes) -> None:
    h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not h_mem:
        _raise_last_error("GlobalAlloc failed")
    ptr = kernel32.GlobalLock(h_mem)
    if not ptr:
        kernel32.GlobalFree(h_mem)
        _raise_last_error("GlobalLock failed")
    try:
        ctypes.memmove(ptr, data, len(data))
    finally:
        kernel32.GlobalUnlock(h_mem)
    if not user32.SetClipboardData(fmt, h_mem):
        kernel32.GlobalFree(h_mem)
        _raise_last_error("SetClipboardData failed")

def _clipboard_set_text(text: str, timings: Timings) -> None:
    _open_clipboard_with_retry(timings)
    try:
        if not user32.EmptyClipboard():
            _raise_last_error("EmptyClipboard failed")
        _clipboard_set_format_bytes_from_open(CF_UNICODETEXT, (text + "\0").encode("utf-16le"))
    finally:
        user32.CloseClipboard()

def _wait_for_new_clipboard_text(old_seq: int, timings: Timings) -> Optional[str]:
    deadline = time.monotonic() + timings.copy_poll_timeout_seconds
    while time.monotonic() < deadline:
        if int(user32.GetClipboardSequenceNumber()) != old_seq:
            return _clipboard_get_text(timings)
        time.sleep(timings.copy_poll_interval_seconds)
    return None

# ═══════════════════════════════════════════════════════════════════════════════
# Clipboard snapshot: все форматы, а не только текст/картинка
# ═══════════════════════════════════════════════════════════════════════════════
#
# Раньше снапшот сохранял только текст или картинку. Если в буфере лежал файл
# из Проводника (CF_HDROP), HTML или RTF, снапшот был «пустым» и после
# конвертации через буфер скопированный файл пропадал. Теперь сохраняются все
# форматы, которые хранятся как HGLOBAL-байты.

# Форматы с GDI-хэндлами вместо HGLOBAL — их нельзя скопировать байтами.
# CF_BITMAP система сама синтезирует из CF_DIB при восстановлении.
_SNAPSHOT_SKIP_FORMATS: Final[frozenset[int]] = frozenset({
    CF_BITMAP, CF_METAFILEPICT, CF_PALETTE, CF_ENHMETAFILE,
    CF_OWNERDISPLAY, CF_DSPBITMAP, CF_DSPMETAFILEPICT, CF_DSPENHMETAFILE,
})

# Служебные форматы OLE: в них ссылки на объект владельца, а не данные.
# Восстановленные «как есть», они указывали бы на чужой, уже недоступный объект.
_SNAPSHOT_SKIP_FORMAT_NAMES: Final[frozenset[str]] = frozenset({
    "DataObject", "Ole Private Data", "OleClipboardPersistOnFlush",
    "Embed Source", "Embedded Object", "Link Source", "Link Source Descriptor",
    "Object Descriptor", "Native", "OwnerLink", "ObjectLink",
})


@dataclass(frozen=True)
class ClipboardSnapshot:
    formats: tuple[tuple[int, bytes], ...] = ()

    @property
    def total_bytes(self) -> int:
        return sum(len(data) for _fmt, data in self.formats)


def _snapshot_format_is_skipped(fmt: int, name: str, present: frozenset[int]) -> bool:
    if fmt in _SNAPSHOT_SKIP_FORMATS:
        return True
    if CF_PRIVATEFIRST <= fmt <= CF_GDIOBJLAST:  # private- и GDI-object-диапазоны
        return True
    if fmt in (CF_TEXT, CF_OEMTEXT) and CF_UNICODETEXT in present:
        return True  # система синтезирует из CF_UNICODETEXT
    return name in _SNAPSHOT_SKIP_FORMAT_NAMES

def _clipboard_format_name(fmt: int) -> str:
    if fmt < 0xC000:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    n = user32.GetClipboardFormatNameW(fmt, buf, len(buf))
    return buf.value if n > 0 else ""

def _clipboard_take_snapshot(timings: Timings) -> ClipboardSnapshot:
    _open_clipboard_with_retry(timings)
    try:
        formats: list[int] = []
        fmt = 0
        while True:
            fmt = int(user32.EnumClipboardFormats(fmt))
            if fmt == 0:
                break
            formats.append(fmt)
        present = frozenset(formats)

        deadline = time.monotonic() + timings.clipboard_snapshot_deadline_seconds
        saved: list[tuple[int, bytes]] = []
        total = 0
        for index, fmt in enumerate(formats):
            if _snapshot_format_is_skipped(fmt, _clipboard_format_name(fmt), present):
                continue
            if time.monotonic() > deadline:
                logging.info("clipboard snapshot: дедлайн, не сохранено форматов: %d", len(formats) - index)
                break
            try:
                data = _clipboard_read_bytes_from_open(fmt)
            except OSError:
                logging.debug("clipboard snapshot: format %d unreadable", fmt, exc_info=True)
                continue
            if not data:
                continue
            if total + len(data) > timings.clipboard_snapshot_max_bytes:
                logging.info("clipboard snapshot: формат %d (%d байт) не влез в бюджет", fmt, len(data))
                continue
            saved.append((fmt, data))
            total += len(data)
        return ClipboardSnapshot(tuple(saved))
    finally:
        user32.CloseClipboard()

def _clipboard_restore_snapshot(snapshot: ClipboardSnapshot, timings: Timings) -> None:
    """Возвращает буфер в состояние снапшота (пустой снапшот — пустой буфер)."""
    _open_clipboard_with_retry(timings)
    try:
        if not user32.EmptyClipboard():
            _raise_last_error("EmptyClipboard failed")
        for fmt, data in snapshot.formats:
            try:
                _clipboard_set_format_bytes_from_open(fmt, data)
            except OSError:
                logging.debug("clipboard restore: format %d failed", fmt, exc_info=True)
    finally:
        user32.CloseClipboard()

@contextmanager
def _clipboard_guard(timings: Timings) -> Generator[Optional[ClipboardSnapshot], None, None]:
    snapshot: Optional[ClipboardSnapshot] = None
    try:
        snapshot = _clipboard_take_snapshot(timings)
    except OSError:
        logging.debug("clipboard_guard: failed to take snapshot", exc_info=True)
    try:
        yield snapshot
    finally:
        if snapshot is not None:
            try:
                _clipboard_restore_snapshot(snapshot, timings)
            except OSError:
                logging.debug("clipboard_guard: failed to restore snapshot", exc_info=True)

# ═══════════════════════════════════════════════════════════════════════════════
# Image / DIB helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_dib_meta(dib: bytes) -> Optional[tuple[int, int, int, bool, int, int]]:
    """(width, height, bpp, top_down, pixel_offset, row_stride) для 24/32 bpp DIB."""
    if len(dib) < 40:
        return None
    bi_size = int.from_bytes(dib[0:4], "little", signed=False)
    if bi_size < 40 or len(dib) < bi_size:
        return None
    width = struct.unpack_from("<i", dib, 4)[0]
    height_signed = struct.unpack_from("<i", dib, 8)[0]
    planes = struct.unpack_from("<H", dib, 12)[0]
    bpp = struct.unpack_from("<H", dib, 14)[0]
    compression = struct.unpack_from("<I", dib, 16)[0]
    if planes != 1 or width <= 0 or height_signed == 0:
        return None
    top_down = height_signed < 0
    height = abs(int(height_signed))
    pixel_offset = int(bi_size)
    if compression == BI_BITFIELDS and bi_size == 40:
        pixel_offset += 12
    if bpp == 24:
        row_stride = ((width * 3 + 3) // 4) * 4
    elif bpp == 32:
        row_stride = width * 4
    else:
        return None
    if pixel_offset + row_stride * height > len(dib):
        return None
    return width, height, bpp, top_down, pixel_offset, row_stride

def _parse_png_meta(png: bytes) -> Optional[tuple[int, int]]:
    if len(png) < 33 or png[0:8] != b"\x89PNG\r\n\x1a\n":
        return None
    length = int.from_bytes(png[8:12], "big", signed=False)
    if png[12:16] != b"IHDR" or length < 13:
        return None
    w = int.from_bytes(png[16:20], "big", signed=False)
    h = int.from_bytes(png[20:24], "big", signed=False)
    if w <= 0 or h <= 0:
        return None
    return w, h

def _crc32(data: bytes) -> int:
    return int(zlib.crc32(data) & 0xFFFFFFFF)

def _fit_size(w: int, h: int, max_px: int) -> tuple[int, int]:
    if max_px > 0 and (w > max_px or h > max_px):
        scale = min(max_px / w, max_px / h)
        return max(1, int(w * scale)), max(1, int(h * scale))
    return w, h

def _gather(indices: list[int]) -> Callable[[bytes], tuple[int, ...]]:
    if len(indices) == 1:
        only = indices[0]
        return lambda seq: (seq[only],)
    return operator.itemgetter(*indices)

def _dib_to_ppm(dib: bytes, max_px: int) -> Optional[bytes]:
    """24/32-bpp DIB → бинарный PPM (P6) с уменьшением до max_px.

    Tk читает PPM сам, на C. Выборка пикселей тоже идёт C-кодом (itemgetter
    по строке + срезы bytearray), поэтому 4K-скриншот превращается в превью за
    миллисекунды, а не секунды, как при построчной сборке строк «#rrggbb».
    Масштаб — ближайший сосед.
    """
    meta = _parse_dib_meta(dib)
    if meta is None:
        return None
    w, h, bpp, top_down, pixel_offset, row_stride = meta
    out_w, out_h = _fit_size(w, h, max_px)
    step = 3 if bpp == 24 else 4
    xs = [((x * w) // out_w) * step for x in range(out_w)]
    get_b, get_g, get_r = _gather(xs), _gather([i + 1 for i in xs]), _gather([i + 2 for i in xs])

    out = bytearray(out_w * out_h * 3)
    row_out = bytearray(out_w * 3)
    row_len = out_w * 3
    for y in range(out_h):
        sy = (y * h) // out_h
        src_y = sy if top_down else (h - 1 - sy)
        base = pixel_offset + src_y * row_stride
        row = dib[base:base + w * step]
        row_out[0::3] = bytes(get_r(row))
        row_out[1::3] = bytes(get_g(row))
        row_out[2::3] = bytes(get_b(row))
        out[y * row_len:(y + 1) * row_len] = row_out
    return f"P6\n{out_w} {out_h}\n255\n".encode("ascii") + bytes(out)

def _clipboard_read_cf_bitmap_as_dib_from_open(timings: Timings) -> bytes:
    hbmp = user32.GetClipboardData(CF_BITMAP)
    if not hbmp:
        return b""
    bmp = BITMAP()
    if int(gdi32.GetObjectW(hbmp, ctypes.sizeof(BITMAP), ctypes.byref(bmp))) <= 0:
        _raise_last_error("GetObjectW failed")
    width = int(bmp.bmWidth)
    height = int(bmp.bmHeight)
    if width <= 0 or height <= 0:
        return b""
    row_stride = width * 4
    size_image = row_stride * height
    if size_image <= 0 or size_image > timings.clipboard_history_max_image_bytes:
        return b""
    bih = BITMAPINFOHEADER()
    bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bih.biWidth = width
    bih.biHeight = height
    bih.biPlanes = 1
    bih.biBitCount = 32
    bih.biCompression = BI_RGB
    bih.biSizeImage = size_image
    bmi = BITMAPINFO()
    bmi.bmiHeader = bih
    buf = (ctypes.c_ubyte * size_image)()
    hdc = user32.GetDC(None)
    if not hdc:
        _raise_last_error("GetDC failed")
    try:
        lines = int(gdi32.GetDIBits(hdc, hbmp, 0, height, ctypes.byref(buf), ctypes.byref(bmi), DIB_RGB_COLORS))
        if lines != height:
            return b""
    finally:
        user32.ReleaseDC(None, hdc)
    hdr = ctypes.string_at(ctypes.byref(bmi.bmiHeader), ctypes.sizeof(BITMAPINFOHEADER))
    return hdr + bytes(buf)

def _create_hbitmap_from_dib(dib: bytes) -> int:
    meta = _parse_dib_meta(dib)
    if meta is None:
        return 0
    w, h, bpp, top_down, pixel_offset, row_stride = meta
    size_bits = row_stride * h
    if size_bits <= 0 or pixel_offset + size_bits > len(dib):
        return 0
    bih = BITMAPINFOHEADER()
    bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bih.biWidth = w
    bih.biHeight = -h if top_down else h
    bih.biPlanes = 1
    bih.biBitCount = bpp
    bih.biCompression = BI_RGB
    bih.biSizeImage = size_bits
    bmi = BITMAPINFO()
    bmi.bmiHeader = bih
    bits_ptr = ctypes.c_void_p()
    hdc = user32.GetDC(None)
    if not hdc:
        return 0
    try:
        hbmp = gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits_ptr), None, 0)
        if not hbmp or not bits_ptr:
            return 0
        ctypes.memmove(bits_ptr, dib[pixel_offset:pixel_offset + size_bits], size_bits)
        return _hwnd_value(hbmp)
    finally:
        user32.ReleaseDC(None, hdc)

def _clipboard_set_image(dib_fmt: int, dib: bytes, png_fmt: int, png: bytes, timings: Timings) -> None:
    if not dib and not png:
        return
    _open_clipboard_with_retry(timings)
    try:
        if not user32.EmptyClipboard():
            _raise_last_error("EmptyClipboard failed")
        if png and png_fmt:
            _clipboard_set_format_bytes_from_open(png_fmt, png)
        if dib and dib_fmt:
            _clipboard_set_format_bytes_from_open(dib_fmt, dib)
            hbmp = _create_hbitmap_from_dib(dib)
            if hbmp and not user32.SetClipboardData(CF_BITMAP, hbmp):
                gdi32.DeleteObject(hbmp)
    finally:
        user32.CloseClipboard()

# ═══════════════════════════════════════════════════════════════════════════════
# Clipboard history
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ClipboardItem:
    kind: Literal["text", "image"]
    text: str = ""
    dib_fmt: int = 0
    dib: bytes = b""
    png_fmt: int = 0
    png: bytes = b""
    width: int = 0
    height: int = 0
    bpp: int = 0
    crc32: int = 0

    def signature(self) -> tuple[object, ...]:
        if self.kind == "text":
            return ("text", self.text)
        return ("image", self.width, self.height, self.bpp, self.crc32)

    def size_bytes(self) -> int:
        return len(self.text) * 2 + len(self.dib) + len(self.png)

    def list_label(self) -> str:
        if self.kind == "text":
            s = self.text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
            return s[:120] + "…" if len(s) > 120 else s
        if self.bpp:
            return f"[IMG {self.width}×{self.height}, {self.bpp} bpp]"
        return f"[IMG {self.width}×{self.height}, PNG]"


def _should_paste_png_only(it: ClipboardItem) -> bool:
    if it.kind != "image" or not it.png or not it.png_fmt:
        return False
    if not it.dib or not it.dib_fmt:
        return True
    meta = _parse_png_meta(it.png)
    if meta is None:
        return False
    pw, ph = meta
    return pw > it.width or ph > it.height


def _history_with_item(
    history: list[ClipboardItem],
    item: ClipboardItem,
    max_items: int,
    max_total_bytes: int,
) -> list[ClipboardItem]:
    """Новая история: item наверху, без дублей, в пределах числа и объёма.

    Самый свежий элемент остаётся всегда; более старые, не влезающие в бюджет
    байт, выпадают (крупная старая картинка вытесняется, мелкий текст — нет).
    """
    sig = item.signature()
    if history and history[0].signature() == sig:
        return history
    candidates = [item] + [it for it in history if it.signature() != sig]
    result: list[ClipboardItem] = []
    total = 0
    for it in candidates:
        if len(result) >= max_items:
            break
        size = it.size_bytes()
        if result and total + size > max_total_bytes:
            continue
        result.append(it)
        total += size
    return result


# Пометки «не сохранять в историю», которые ставят менеджеры паролей
# (KeePass, Bitwarden, 1Password...) и сама Windows для своей истории Win+V.
_PRIVATE_CLIPBOARD_MARKERS: Final[tuple[str, ...]] = (
    "ExcludeClipboardContentFromMonitorProcessing",
    "Clipboard Viewer Ignore",
)

def _is_deny_flag(raw: bytes) -> bool:
    """DWORD 0 в формате CanIncludeInClipboardHistory — «не включать в историю»."""
    return len(raw) >= 4 and int.from_bytes(raw[:4], "little") == 0

def _clipboard_is_private_from_open() -> bool:
    for name in _PRIVATE_CLIPBOARD_MARKERS:
        fmt = _registered_format(name)
        if fmt and user32.IsClipboardFormatAvailable(fmt):
            return True
    fmt = _registered_format("CanIncludeInClipboardHistory")
    if fmt and user32.IsClipboardFormatAvailable(fmt):
        try:
            if _is_deny_flag(_clipboard_read_bytes_from_open(fmt)):
                return True
        except OSError:
            return True  # не смогли прочитать флаг — перестраховываемся
    return False

def _normalize_clip_text(text: str, timings: Timings) -> str:
    s = (text or "").strip()
    if len(s) > timings.clipboard_history_max_chars_per_item:
        s = s[:timings.clipboard_history_max_chars_per_item]
    return s

def _clipboard_try_get_item(timings: Timings) -> Optional[ClipboardItem]:
    _open_clipboard_with_retry(timings)
    try:
        if _clipboard_is_private_from_open():
            return None

        cf_png = _cf_png()
        png = b""
        if cf_png and user32.IsClipboardFormatAvailable(cf_png):
            png = _clipboard_read_bytes_from_open(cf_png)
            if len(png) > timings.clipboard_history_max_image_bytes:
                png = b""

        dib_fmt = 0
        dib = b""
        if user32.IsClipboardFormatAvailable(CF_DIBV5):
            dib_fmt = CF_DIBV5
        elif user32.IsClipboardFormatAvailable(CF_DIB):
            dib_fmt = CF_DIB
        if dib_fmt:
            dib = _clipboard_read_bytes_from_open(dib_fmt)
            if len(dib) > timings.clipboard_history_max_image_bytes:
                dib = b""

        if dib:
            meta = _parse_dib_meta(dib)
            if meta is not None:
                w, h, bpp = meta[0], meta[1], meta[2]
                return ClipboardItem(
                    kind="image", dib_fmt=dib_fmt, dib=dib,
                    png_fmt=cf_png if png else 0, png=png,
                    width=w, height=h, bpp=bpp, crc32=_crc32(dib),
                )

        if png:
            meta_png = _parse_png_meta(png)
            if meta_png is not None:
                w, h = meta_png
                return ClipboardItem(
                    kind="image", png_fmt=cf_png, png=png,
                    width=w, height=h, bpp=0, crc32=_crc32(png),
                )

        if user32.IsClipboardFormatAvailable(CF_BITMAP):
            dib2 = _clipboard_read_cf_bitmap_as_dib_from_open(timings)
            if dib2 and len(dib2) <= timings.clipboard_history_max_image_bytes:
                meta2 = _parse_dib_meta(dib2)
                if meta2 is not None:
                    w, h, bpp = meta2[0], meta2[1], meta2[2]
                    return ClipboardItem(
                        kind="image", dib_fmt=CF_DIB, dib=dib2,
                        width=w, height=h, bpp=bpp, crc32=_crc32(dib2),
                    )

        if user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            s = _normalize_clip_text(_clipboard_read_text_from_open(), timings)
            if s:
                return ClipboardItem(kind="text", text=s)
        return None
    finally:
        user32.CloseClipboard()


_clipboard_history: list[ClipboardItem] = []
_clipboard_history_lock = threading.Lock()
_last_clipboard_seq: int = 0
_capture_pending = threading.Event()


def _capture_clipboard_to_history(timings: Timings, force: bool = False) -> None:
    """Добавляет текущее содержимое буфера в историю (выполняется в worker'е)."""
    global _last_clipboard_seq, _clipboard_history
    seq = int(user32.GetClipboardSequenceNumber())
    if not force and seq == _last_clipboard_seq:
        return
    try:
        item = _clipboard_try_get_item(timings)
    except OSError:
        return
    _last_clipboard_seq = seq
    if item is None:
        return
    settings = _settings
    with _clipboard_history_lock:
        _clipboard_history = _history_with_item(
            _clipboard_history, item,
            settings.clipboard_history_max_items,
            settings.clipboard_history_max_total_bytes,
        )

def _clipboard_history_snapshot() -> list[ClipboardItem]:
    with _clipboard_history_lock:
        return list(_clipboard_history)

def _clipboard_capture_job() -> None:
    _capture_pending.clear()
    if not _is_paused:
        _capture_clipboard_to_history(_timings)

def _request_clipboard_capture() -> None:
    """Вызывается из потока трея на WM_CLIPBOARDUPDATE. Схлопывает всплески.

    Захват идёт в worker'е — значит, строго после текущей операции. Наш
    временный Ctrl+C внутри конвертации в историю не попадёт: к моменту
    захвата буфер уже восстановлен.
    """
    if _is_paused or _capture_pending.is_set():
        return
    _capture_pending.set()
    if not _worker.submit("clipboard-capture", _clipboard_capture_job):
        _capture_pending.clear()

# ═══════════════════════════════════════════════════════════════════════════════
# Actions (выполняются в worker'е)
# ═══════════════════════════════════════════════════════════════════════════════

def _replace_selection_with_text(text: str, timings: Timings) -> bool:
    """Заменяет выделение в не-Edit поле. True — вставляли через буфер.

    По умолчанию — Ctrl+V. Режим «type» (настройка replace_method) набирает
    текст через KEYEVENTF_UNICODE и буфер при замене не трогает, но при наборе
    срабатывают автозамена Word/Outlook и автозакрытие скобок в IDE — а
    раскладочная конвертация как раз даёт [ ] ; ' из х ъ ж э.
    """
    if _settings.replace_method == "type" and _text_safe_for_typing(text, timings.max_typed_chars):
        _type_text(text)
        time.sleep(timings.between_key_events_seconds)
        return False
    _clipboard_set_text(text, timings)
    _press_combo_ctrl(VK_V, timings)
    return True


def _transform_selection_via_clipboard(
    timings: Timings,
    transform: Callable[[str], str],
    after: Optional[Callable[[str], None]] = None,
) -> None:
    """Ctrl+C → transform → замена выделения → повторное выделение результата.

    Весь путь — внутри снапшота буфера: прежнее содержимое (включая файлы,
    HTML, RTF) возвращается на место. Перед восстановлением ждём
    paste_settle_seconds, чтобы приложение успело прочитать наш Ctrl+V.
    """
    with _clipboard_guard(timings):
        old_seq = int(user32.GetClipboardSequenceNumber())
        _press_combo_ctrl(VK_C, timings)

        selected = _wait_for_new_clipboard_text(old_seq, timings)
        if not selected or not selected.strip() or len(selected) > timings.max_selected_length:
            return

        converted = transform(selected)
        if converted == selected:
            return

        pasted = _replace_selection_with_text(converted, timings)
        _select_last_chars(_caret_units(converted), timings)
        if after is not None:
            after(converted)
        if pasted:
            time.sleep(timings.paste_settle_seconds)


def convert_selected_text(timings: Timings) -> None:
    hwnd_focus = _get_focused_control_hwnd()

    sel = _edit_get_sel(hwnd_focus)
    if sel is not None:
        s, e = sel
        if e <= s:
            return  # в Edit ничего не выделено
        selected = _try_get_selected_text_from_edit(hwnd_focus, timings.max_selected_length)
        if selected is not None and selected.strip():
            converted = convert_keyboard_layout(selected)
            if converted != selected and _try_replace_selection_in_edit(hwnd_focus, converted):
                _switch_layout_toward_text(converted)
            return

    _transform_selection_via_clipboard(timings, convert_keyboard_layout, _switch_layout_toward_text)


def toggle_case_selected_text(timings: Timings) -> None:
    hwnd_focus = _get_focused_control_hwnd()

    sel = _edit_get_sel(hwnd_focus)
    if sel is not None:
        s, e = sel
        if e <= s:
            return  # в Edit ничего не выделено
        selected = _try_get_selected_text_from_edit(hwnd_focus, timings.max_selected_length)
        if selected is not None and selected.strip():
            converted = toggle_case_selected_fragment(selected)
            if converted != selected:
                _try_replace_selection_in_edit(hwnd_focus, converted)
            return

    _transform_selection_via_clipboard(timings, toggle_case_selected_fragment)


def _transform_run_before_caret_in_edit(
    hwnd: object,
    caret_pos: int,
    transform: Callable[[str], str],
) -> Optional[tuple[str, int]]:
    """Edit/RichEdit: заменяет фрагмент перед кареткой. (новый фрагмент, Δдлины) или None."""
    if caret_pos <= 0:
        return None
    full_text = _read_edit_full_text(hwnd)
    if not full_text:
        return None
    found = _transform_run_before_caret_text(full_text, caret_pos, transform)
    if found is None:
        return None
    start, end, new_fragment = found
    if not _sendmsg_ok(hwnd, EM_SETSEL, start, end):
        return None
    if not _try_replace_selection_in_edit(hwnd, new_fragment, restore_selection=False):
        return None
    new_caret = start + len(new_fragment)
    _sendmsg_ok(hwnd, EM_SETSEL, new_caret, new_caret)
    return new_fragment, len(new_fragment) - (end - start)


def _transform_run_before_caret_via_clipboard(
    timings: Timings,
    transform: Callable[[str], str],
) -> Optional[str]:
    """Не-Edit поля: Shift+Home → Ctrl+C → замена строки до каретки. Новый фрагмент или None."""
    with _clipboard_guard(timings):
        old_seq = int(user32.GetClipboardSequenceNumber())

        # Физически зажатый Ctrl от хоткея (Ctrl+Ins, Ctrl+F9) _press_combo_*
        # отпускает сам — иначе вышло бы Ctrl+Shift+Home.
        _press_combo_shift(VK_HOME, timings)
        time.sleep(max(0.03, timings.between_key_events_seconds * 2))
        _press_combo_ctrl(VK_C, timings)

        selected = _wait_for_new_clipboard_text(old_seq, timings)
        if selected is None:
            time.sleep(0.05)
            old_seq = int(user32.GetClipboardSequenceNumber())
            _press_combo_ctrl(VK_C, timings)
            selected = _wait_for_new_clipboard_text(old_seq, timings)

        found = _transform_run_before_caret_text(selected, len(selected), transform) if selected else None
        if found is None:
            _collapse_selection_to_right()
            return None

        start, end, new_fragment = found
        pasted = _replace_selection_with_text(selected[:start] + new_fragment + selected[end:], timings)
        if pasted:
            time.sleep(timings.paste_settle_seconds)
        return new_fragment


def _transform_run_before_caret(timings: Timings, transform: Callable[[str], str]) -> Optional[str]:
    """Применяет transform к фрагменту перед кареткой — как Ctrl+Ins, выделять не нужно.

    Возвращает новый фрагмент или None, если менять было нечего.
    """
    hwnd_focus = _get_focused_control_hwnd()
    sel = _edit_get_sel(hwnd_focus)
    if sel is None:
        return _transform_run_before_caret_via_clipboard(timings, transform)

    s, e = sel
    # Каретка — в конце выделения (EM_GETSEL гарантирует s ≤ e).
    _sendmsg_ok(hwnd_focus, EM_SETSEL, e, e)
    result = _transform_run_before_caret_in_edit(hwnd_focus, e, transform)
    if result is None or result[1] == 0:
        # Длина не изменилась (раскладка и регистр меняют текст символ в символ) —
        # возвращаем прежнее выделение/позицию каретки как было.
        _sendmsg_ok(hwnd_focus, EM_SETSEL, s, e)
    return None if result is None else result[0]


def convert_before_caret_text(timings: Timings) -> None:
    """Ctrl+Ins: сменить раскладку фрагмента перед кареткой."""
    converted = _transform_run_before_caret(timings, convert_keyboard_layout)
    if converted is not None:
        _switch_layout_toward_text(converted)


def toggle_case_before_caret_text(timings: Timings) -> None:
    """Ctrl+F9: сменить регистр фрагмента перед кареткой (выбор — как у Ctrl+Ins).

    Повторные нажатия идут по циклу F9: «abc» → «Abc» → «ABC» → «abc».
    """
    _transform_run_before_caret(timings, toggle_case_selected_fragment)


def undo_last_change(timings: Timings) -> None:
    _press_combo_ctrl(VK_Z, timings)


def _select_word_under_caret_in_edit(hwnd: object) -> bool:
    """EM_SETSEL на слово под кареткой. True — выделено или уже было выделение."""
    sel = _edit_get_sel(hwnd)
    if sel is None:
        return False
    s, e = sel
    if s != e:
        return True  # пользователь уже что-то выделил — не перетираем
    full_text = _read_edit_full_text(hwnd)
    if not full_text:
        return False
    bounds = _find_word_bounds_at_caret(full_text, e)
    if bounds is None:
        return False
    return _sendmsg_ok(hwnd, EM_SETSEL, bounds[0], bounds[1])


def _select_word_under_caret_via_keys(timings: Timings) -> None:
    """Fallback для не-Edit контролов: Ctrl+Left → Ctrl+Shift+Right.

    Текст не читается, поэтому на краях неточен: каретка ровно в начале слова
    уедет к предыдущему; Word может прихватить хвостовой пробел.
    """
    _send_input(_physical_modifier_release_events() + [
        _key_input(VK_CONTROL, False),
        _key_input(VK_LEFT, False),
        _key_input(VK_LEFT, True),
        _key_input(VK_CONTROL, True),
    ])
    time.sleep(max(0.02, timings.between_key_events_seconds))
    _send_input([
        _key_input(VK_CONTROL, False),
        _key_input(VK_SHIFT, False),
        _key_input(VK_RIGHT, False),
        _key_input(VK_RIGHT, True),
        _key_input(VK_SHIFT, True),
        _key_input(VK_CONTROL, True),
    ])
    time.sleep(timings.between_key_events_seconds)


def select_word_under_caret(timings: Timings) -> None:
    # Короткий сигнал — подтверждение, что аккорд Ctrl+Alt+Shift пойман.
    user32.MessageBeep(0xFFFFFFFF)
    if _select_word_under_caret_in_edit(_get_focused_control_hwnd()):
        return
    _select_word_under_caret_via_keys(timings)


def _paste_history_item(item: ClipboardItem, target_hwnd: int) -> None:
    """Кладёт элемент истории в буфер и вставляет его в окно, бывшее активным."""
    timings = _timings
    # После закрытия окна истории Windows не всегда сразу возвращает фокус —
    # если Ctrl+V уйдёт в этот промежуток, вставка пропадёт или уйдёт не туда.
    if target_hwnd:
        _force_foreground_window(target_hwnd)
        time.sleep(0.05)

    if item.kind == "text":
        _clipboard_set_text(item.text, timings)
    elif _should_paste_png_only(item):
        _clipboard_set_image(0, b"", item.png_fmt, item.png, timings)
    else:
        _clipboard_set_image(item.dib_fmt, item.dib, item.png_fmt, item.png, timings)
    # Выбранный элемент остаётся в буфере (как Win+V): Telegram и другие
    # Qt-приложения дочитывают HBITMAP/DIB заметно позже нажатия Ctrl+V.
    time.sleep(0.05)
    _press_combo_ctrl(VK_V, timings)
    time.sleep(0.2)


def _prepare_clipboard_picker(target_hwnd: int) -> None:
    """Worker: дочитываем текущий буфер в историю и открываем окно выбора."""
    _capture_clipboard_to_history(_timings, force=True)
    history = _clipboard_history_snapshot()
    _ui.call(lambda root: _open_clipboard_picker_window(root, history, target_hwnd))

# ── Автозамена в Edit/RichEdit ────────────────────────────────────────────────

def _apply_rules_in_edit(hwnd: object, after_space: bool) -> None:
    """Применяет правила к тексту перед кареткой в стандартном Edit/RichEdit.

    after_space=True — сразу после пробела (триггер стоит перед ним),
    False — после паузы во вводе (триггер стоит прямо перед кареткой).
    """
    caret = _get_collapsed_caret_from_edit(hwnd)
    if caret is None or caret <= 0:
        return
    full_text = _read_edit_full_text(hwnd)
    if not full_text or caret > len(full_text):
        return

    if after_space:
        if full_text[caret - 1] != " ":
            return
        look_end = caret - 1
    else:
        look_end = caret
    if look_end <= 0:
        return

    cfg = _get_rules_snapshot()
    max_trigger_len = _compute_max_trigger_len(cfg)
    if max_trigger_len <= 0:
        return

    window_start = max(0, look_end - max_trigger_len)
    match = _match_or_block(cfg, full_text[window_start:look_end], full_text, window_start)
    if match is None or match is _BLOCK_SENTINEL:
        return

    replace_start = look_end - len(match.trigger)
    new_caret = replace_start + len(match.replacement) + (1 if after_space else 0)
    # _replace_range_in_edit_safely перечитывает текст и проверяет, что на месте
    # всё ещё стоит триггер, — поэтому лишних повторных чтений здесь не нужно.
    if _replace_range_in_edit_safely(
        hwnd=hwnd,
        start=replace_start,
        end=look_end,
        expected_text=match.trigger,
        replacement=match.replacement,
        caret_after=new_caret,
    ):
        _switch_layout_toward_text(match.replacement)
    else:
        logging.debug("%s: safe replace aborted", "SPACE" if after_space else "IDLE")


def _idle_rules_job(fg_hwnd: int, focus_hwnd: int) -> None:
    """Worker: автозамена после паузы во вводе — если окно и фокус те же."""
    if _is_paused:
        return
    if _hwnd_value(user32.GetForegroundWindow()) != fg_hwnd:
        return
    focus = _get_focused_control_hwnd()
    if focus != focus_hwnd or not _is_text_input_focus(focus):
        return
    _apply_rules_in_edit(focus, after_space=False)

# ═══════════════════════════════════════════════════════════════════════════════
# Tk windows (поток tk-ui)
# ═══════════════════════════════════════════════════════════════════════════════

def _tk_window_alive(win: object | None) -> bool:
    try:
        return win is not None and bool(win.winfo_exists())
    except Exception:
        return False


def _present_tk_window(win: object) -> None:
    """Показывает окно поверх остальных и отдаёт ему фокус."""
    try:
        win.attributes("-topmost", True)
        win.deiconify()
        win.lift()
        win.update_idletasks()
        _force_foreground_window(int(win.wm_frame(), 16))
        win.focus_force()
    except Exception:
        logging.debug("present tk window failed", exc_info=True)


def _open_rules_editor_window(root: object) -> None:
    global _rules_editor_window
    import tkinter as tk
    from tkinter import ttk, messagebox

    if _tk_window_alive(_rules_editor_window):
        _present_tk_window(_rules_editor_window)
        return

    cfg = _get_rules_snapshot()

    win = tk.Toplevel(root)
    _rules_editor_window = win
    win.title("Правила автозамены (по пробелу)")
    win.geometry("980x620")
    win.minsize(820, 520)

    def close() -> None:
        global _rules_editor_window
        _rules_editor_window = None
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", close)

    frm = ttk.Frame(win, padding=10)
    frm.pack(fill="both", expand=True)

    nb = ttk.Notebook(frm)
    nb.pack(fill="both", expand=True)

    replace_tab = ttk.Frame(nb, padding=10)
    block_tab = ttk.Frame(nb, padding=10)
    nb.add(replace_tab, text="Заменять")
    nb.add(block_tab, text="Не заменять")

    # ─── Replace rules tab ────────────────────────────────────────────────────

    tree = ttk.Treeview(replace_tab, columns=("trigger", "replacement", "enabled"),
                        show="headings", selectmode="browse")
    tree.heading("trigger", text="Триггер (что набираем)")
    tree.heading("replacement", text="Замена (на что заменить)")
    tree.heading("enabled", text="Вкл")
    tree.column("trigger", width=220, anchor="w")
    tree.column("replacement", width=560, anchor="w")
    tree.column("enabled", width=60, anchor="center")
    tree.pack(fill="both", expand=True)

    def refresh_replace() -> None:
        tree.delete(*tree.get_children())
        for i, r in enumerate(cfg.replace_rules):
            tree.insert("", "end", iid=str(i), values=(r.trigger, r.replacement, "✓" if r.is_enabled else ""))

    refresh_replace()

    form = ttk.Frame(replace_tab)
    form.pack(fill="x", pady=(10, 0))

    ttk.Label(form, text="Триггер").grid(row=0, column=0, sticky="w")
    ent_trigger = ttk.Entry(form)
    ent_trigger.grid(row=0, column=1, sticky="we", padx=(8, 0))

    ttk.Label(form, text="Замена").grid(row=1, column=0, sticky="w", pady=(8, 0))
    ent_repl = ttk.Entry(form)
    ent_repl.grid(row=1, column=1, sticky="we", padx=(8, 0), pady=(8, 0))

    var_enabled = tk.BooleanVar(master=win, value=True)
    ttk.Checkbutton(form, text="Включено", variable=var_enabled).grid(
        row=2, column=1, sticky="w", pady=(8, 0), padx=(8, 0))
    form.columnconfigure(1, weight=1)

    btns = ttk.Frame(replace_tab)
    btns.pack(fill="x", pady=(10, 0))

    def add_rule() -> None:
        nonlocal cfg
        tr = ent_trigger.get().strip()
        if not tr:
            messagebox.showerror("Ошибка", "Триггер не может быть пустым.", parent=win)
            return
        rules = [r for r in cfg.replace_rules if r.trigger != tr]
        rules.append(TextRule(trigger=tr, replacement=ent_repl.get(), is_enabled=bool(var_enabled.get())))
        rules.sort(key=lambda r: (r.trigger.lower(), r.trigger))
        cfg = RulesConfig(replace_rules=tuple(rules), block_triggers=cfg.block_triggers)
        refresh_replace()
        ent_trigger.delete(0, tk.END)
        ent_repl.delete(0, tk.END)
        var_enabled.set(True)

    def selected_index(tv: object, size: int) -> Optional[int]:
        sel = tv.selection()
        if not sel:
            return None
        idx = int(sel[0])
        return idx if 0 <= idx < size else None

    def delete_rule() -> None:
        nonlocal cfg
        idx = selected_index(tree, len(cfg.replace_rules))
        if idx is None:
            return
        rules = list(cfg.replace_rules)
        rules.pop(idx)
        cfg = RulesConfig(replace_rules=tuple(rules), block_triggers=cfg.block_triggers)
        refresh_replace()

    def toggle_enabled() -> None:
        nonlocal cfg
        idx = selected_index(tree, len(cfg.replace_rules))
        if idx is None:
            return
        rules = list(cfg.replace_rules)
        r = rules[idx]
        rules[idx] = TextRule(trigger=r.trigger, replacement=r.replacement, is_enabled=not r.is_enabled)
        cfg = RulesConfig(replace_rules=tuple(rules), block_triggers=cfg.block_triggers)
        refresh_replace()
        tree.selection_set(str(idx))

    ttk.Button(btns, text="Добавить/обновить", command=add_rule).pack(side="left")
    ttk.Button(btns, text="Удалить", command=delete_rule).pack(side="left", padx=(8, 0))
    ttk.Button(btns, text="Вкл/выкл", command=toggle_enabled).pack(side="left", padx=(8, 0))

    # ─── Block triggers tab ───────────────────────────────────────────────────

    block_tree = ttk.Treeview(block_tab, columns=("trigger",), show="headings", selectmode="browse")
    block_tree.heading("trigger", text="Триггер, при котором НИЧЕГО не заменяем")
    block_tree.column("trigger", width=840, anchor="w")
    block_tree.pack(fill="both", expand=True)

    block_form = ttk.Frame(block_tab)
    block_form.pack(fill="x", pady=(10, 0))
    ttk.Label(block_form, text="Триггер").grid(row=0, column=0, sticky="w")
    ent_block = ttk.Entry(block_form)
    ent_block.grid(row=0, column=1, sticky="we", padx=(8, 0))
    block_form.columnconfigure(1, weight=1)

    block_btns = ttk.Frame(block_tab)
    block_btns.pack(fill="x", pady=(10, 0))

    def refresh_block() -> None:
        block_tree.delete(*block_tree.get_children())
        for i, t in enumerate(cfg.block_triggers):
            block_tree.insert("", "end", iid=str(i), values=(t,))

    refresh_block()

    def add_block() -> None:
        nonlocal cfg
        t = ent_block.get().strip()
        if not t:
            messagebox.showerror("Ошибка", "Триггер не может быть пустым.", parent=win)
            return
        items = list(cfg.block_triggers)
        if t not in items:
            items.append(t)
            items.sort(key=lambda x: (x.lower(), x))
        cfg = RulesConfig(replace_rules=cfg.replace_rules, block_triggers=tuple(items))
        refresh_block()
        ent_block.delete(0, tk.END)

    def del_block() -> None:
        nonlocal cfg
        idx = selected_index(block_tree, len(cfg.block_triggers))
        if idx is None:
            return
        items = list(cfg.block_triggers)
        items.pop(idx)
        cfg = RulesConfig(replace_rules=cfg.replace_rules, block_triggers=tuple(items))
        refresh_block()

    ttk.Button(block_btns, text="Добавить", command=add_block).pack(side="left")
    ttk.Button(block_btns, text="Удалить", command=del_block).pack(side="left", padx=(8, 0))

    # ─── Footer ───────────────────────────────────────────────────────────────

    footer = ttk.Frame(frm)
    footer.pack(fill="x", pady=(10, 0))

    def save_and_close() -> None:
        global _rules_config
        try:
            with _rules_lock:
                _save_rules(cfg)
                _save_dictionary(list(cfg.block_triggers))
                _rules_config = cfg
        except Exception as exc:
            logging.exception("rules editor: save failed")
            messagebox.showerror("Ошибка", f"Не удалось сохранить: {exc}", parent=win)
            return
        close()

    ttk.Button(footer, text="Сохранить", command=save_and_close).pack(side="right")
    ttk.Button(footer, text="Отмена", command=close).pack(side="right", padx=(0, 8))

    _present_tk_window(win)


def _make_photo_from_dib(master: object, dib: bytes, max_px: int) -> object | None:
    import tkinter as tk
    ppm = _dib_to_ppm(dib, max_px)
    if ppm is None:
        return None
    try:
        return tk.PhotoImage(master=master, data=ppm, format="ppm")
    except tk.TclError:
        # Старые сборки Tk принимают -data только в base64
        try:
            return tk.PhotoImage(master=master, data=base64.b64encode(ppm).decode("ascii"), format="ppm")
        except tk.TclError:
            logging.debug("PPM preview failed", exc_info=True)
            return None


def _make_photo_from_png(master: object, png: bytes, w: int, h: int, max_px: int) -> object | None:
    import tkinter as tk
    if not png:
        return None
    try:
        img = tk.PhotoImage(master=master, data=base64.b64encode(png).decode("ascii"), format="png")
    except tk.TclError:
        return None
    if max_px > 0 and w > 0 and h > 0 and (w > max_px or h > max_px):
        factor = -(-max(w, h) // max_px)  # ceil
        if factor > 1:
            try:
                img = img.subsample(factor, factor)
            except tk.TclError:
                pass
    return img


def _open_clipboard_picker_window(root: object, history: list[ClipboardItem], target_hwnd: int) -> None:
    global _picker_window
    import tkinter as tk
    from tkinter import ttk

    if _tk_window_alive(_picker_window):
        _present_tk_window(_picker_window)
        return

    timings = _timings
    BG = "#867E7E"
    LIST_BG = "#B5B5B5"
    SELECT_BG = "#302F2F"
    SELECT_FG = "#FFFFFF"

    win = tk.Toplevel(root)
    _picker_window = win
    win.title("Буфер обмена")
    win.geometry("1200x720")
    win.minsize(900, 520)
    win.configure(bg=BG)

    # Собственные имена стилей: тема общая на весь интерпретатор, и окно
    # истории не должно перекрашивать редактор правил.
    style = ttk.Style(win)
    style.configure("Picker.TFrame", background=BG)
    style.configure("Picker.TLabel", background=BG)
    style.configure("Picker.TButton", padding=(10, 6))

    def close() -> None:
        global _picker_window
        _picker_window = None
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", close)
    win.bind("<Escape>", lambda _e: close())

    frame = ttk.Frame(win, padding=10, style="Picker.TFrame")
    frame.pack(fill="both", expand=True)

    if not history:
        ttk.Label(
            frame, style="Picker.TLabel",
            text="История пуста. Скопируйте текст или изображение (Ctrl+C), затем откройте снова.",
        ).pack(anchor="w")
        ttk.Button(frame, text="Закрыть", style="Picker.TButton", command=close).pack(anchor="e", pady=(12, 0))
        _present_tk_window(win)
        return

    body = ttk.Frame(frame, style="Picker.TFrame")
    body.pack(fill="both", expand=True)
    left = ttk.Frame(body, style="Picker.TFrame")
    left.pack(side="left", fill="both", expand=True)
    right = ttk.Frame(body, style="Picker.TFrame", width=520)
    right.pack(side="right", fill="y", padx=(10, 0))
    right.pack_propagate(False)

    scrollbar = ttk.Scrollbar(left, orient="vertical")
    listbox = tk.Listbox(
        left,
        activestyle="dotbox",
        bg=LIST_BG, fg="#111111",
        selectbackground=SELECT_BG, selectforeground=SELECT_FG,
        highlightthickness=0, relief="flat",
        yscrollcommand=scrollbar.set,
    )
    scrollbar.config(command=listbox.yview)
    scrollbar.pack(side="right", fill="y")
    listbox.pack(side="left", fill="both", expand=True)

    img_no = 0
    for it in history:
        if it.kind == "image":
            img_no += 1
            listbox.insert(tk.END, f"Изображение {img_no}")
        else:
            listbox.insert(tk.END, it.list_label())
    listbox.selection_set(0)
    listbox.activate(0)

    ttk.Label(right, text="Предпросмотр", style="Picker.TLabel").pack(anchor="w")
    preview_image = tk.Label(right, bg=BG)
    preview_text = tk.Text(right, height=10, wrap="word", bg=LIST_BG, relief="flat", highlightthickness=0)
    preview_text.configure(state="disabled")
    thumb_cache: dict[tuple, object | None] = {}

    def set_text_preview(s: str) -> None:
        preview_image.pack_forget()
        preview_text.configure(state="normal")
        preview_text.delete("1.0", tk.END)
        preview_text.insert("1.0", s)
        preview_text.configure(state="disabled")
        preview_text.pack(fill="both", expand=True, pady=(6, 0))

    def set_image_preview(it: ClipboardItem) -> None:
        preview_text.pack_forget()
        max_px = timings.clipboard_preview_max_px
        key = (it.crc32, it.width, it.height, it.bpp, bool(it.dib))
        if key not in thumb_cache:
            if it.dib:
                thumb_cache[key] = _make_photo_from_dib(win, it.dib, max_px)
            else:
                thumb_cache[key] = _make_photo_from_png(win, it.png, it.width, it.height, max_px)
        photo = thumb_cache[key]
        preview_image.configure(image=photo if photo is not None else "")
        preview_image.image = photo
        preview_image.pack(fill="both", expand=True, pady=(6, 0))

    def refresh_preview() -> None:
        sel = listbox.curselection()
        if not sel:
            return
        it = history[int(sel[0])]
        if it.kind == "text":
            set_text_preview(it.text)
        else:
            set_image_preview(it)

    listbox.bind("<<ListboxSelect>>", lambda _e: refresh_preview())
    refresh_preview()

    def on_ok() -> None:
        sel = listbox.curselection()
        close()
        if not sel:
            return
        chosen = history[int(sel[0])]
        _worker.submit("paste-history-item", lambda: _paste_history_item(chosen, target_hwnd))

    btns = ttk.Frame(frame, style="Picker.TFrame")
    btns.pack(fill="x", pady=(8, 0))
    ttk.Button(btns, text="Вставить", style="Picker.TButton", command=on_ok).pack(side="right")
    ttk.Button(btns, text="Отмена", style="Picker.TButton", command=close).pack(side="right", padx=(0, 8))

    win.bind("<Return>", lambda _e: on_ok())
    listbox.bind("<Double-Button-1>", lambda _e: on_ok())

    _present_tk_window(win)
    listbox.focus_set()

# ═══════════════════════════════════════════════════════════════════════════════
# Tray (собственный поток со своим циклом сообщений)
# ═══════════════════════════════════════════════════════════════════════════════

_tray_window_handle: int = 0
_tray_window_class_name: str = ""
_tray_window_proc_ref: object | None = None
_tray_icon_handle: int = 0
_tray_icon_owned: bool = False
_tray_taskbar_created_message: int = 0
_tray_thread: Optional[threading.Thread] = None
_clipboard_listener_active: bool = False
_clipboard_poll_last_seq: int = 0
_main_thread_id: int = 0


def _tray_tooltip_text() -> str:
    return f"punto_like: {'на паузе' if _is_paused else 'работает'}"


def _make_notify_icon_data(hwnd: int, h_icon: int) -> NOTIFYICONDATAW:
    data = NOTIFYICONDATAW()
    data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
    data.hWnd = hwnd
    data.uID = _TRAY_ICON_UID
    data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
    data.uCallbackMessage = _WM_TRAY_CALLBACK
    data.hIcon = h_icon
    data.szTip = _tray_tooltip_text()[:127]
    return data


def _shell_notify_icon(message: int, data: NOTIFYICONDATAW) -> bool:
    ok = bool(shell32.Shell_NotifyIconW(message, ctypes.byref(data)))
    if not ok:
        logging.warning("Shell_NotifyIconW failed (message=%s)", message)
    return ok


def _load_tray_icon() -> tuple[int, bool]:
    icon_path = DATA_DIR / "punto_like.ico"
    if icon_path.exists():
        h_icon = _hwnd_value(user32.LoadImageW(None, str(icon_path), IMAGE_ICON, 0, 0,
                                               LR_LOADFROMFILE | LR_DEFAULTSIZE))
        if h_icon:
            return h_icon, True
        logging.warning("Failed to load tray icon from %s", icon_path)
    return _hwnd_value(user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))), False


def _post_tray_refresh() -> None:
    if _tray_window_handle:
        user32.PostMessageW(_tray_window_handle, _WM_TRAY_REFRESH, 0, 0)


def _request_app_exit() -> None:
    """Просит главный поток завершиться (из любого потока)."""
    if _main_thread_id:
        user32.PostThreadMessageW(_main_thread_id, _WM_APP_EXIT, 0, 0)


def _open_file_async(path: Path, ensure: Callable[[], None]) -> None:
    def run() -> None:
        try:
            if not path.exists():
                ensure()
            os.startfile(str(path))
        except Exception as exc:
            logging.warning("Failed to open %s: %s", path, exc)
    threading.Thread(target=run, name="open-file", daemon=True).start()


def _show_tray_menu(hwnd: int) -> None:
    global _active_window_only, _allowed_hwnd
    pt = POINT(0, 0)
    user32.GetCursorPos(ctypes.byref(pt))

    # Пользователь мог отредактировать файлы руками — перечитываем (дёшево).
    _run_guarded("reload disabled apps", _reload_disabled_apps)
    _run_guarded("reload dictionary", _reload_dictionary)

    # Foreground сейчас уже Shell_TrayWnd — берём последнее реальное окно.
    origin_hwnd = _resolve_real_foreground_hwnd()
    origin_exe = _get_exe_name_for_hwnd(origin_hwnd)
    origin_disabled = _is_exe_disabled(origin_exe)

    hmenu = user32.CreatePopupMenu()
    if not hmenu:
        return
    try:
        def add(item_id: int, text: Optional[str], flags: int = MF_STRING) -> None:
            user32.AppendMenuW(hmenu, flags, item_id, text)

        add(_TRAY_MENU_OPEN_RULES, "Открыть файл правил")
        add(_TRAY_MENU_OPEN_DICT, "Открыть словарь")
        add(_TRAY_MENU_OPEN_SETTINGS, "Настройки правил/словарь…")
        add(_TRAY_MENU_OPEN_APP_SETTINGS, "Открыть файл настроек (хоткеи, лимиты)")
        add(0, None, MF_SEPARATOR)
        add(_TRAY_MENU_TOGGLE_ACTIVE_WINDOW, "Работать только в текущем окне",
            MF_STRING | (MF_CHECKED if _active_window_only else 0))
        add(0, None, MF_SEPARATOR)
        if origin_exe:
            label = (f"Включить в этом приложении ({origin_exe})" if origin_disabled
                     else f"Отключить в этом приложении ({origin_exe})")
        else:
            label = "Отключить в этом приложении (exe не определён)"
        add(_TRAY_MENU_TOGGLE_DISABLED_HERE, label)
        add(_TRAY_MENU_OPEN_DISABLED_LIST, "Открыть список отключённых приложений")
        add(0, None, MF_SEPARATOR)
        add(_TRAY_MENU_EXIT, "Закрыть")

        # Без этого первый клик по меню лишь отдаёт фокус и закрывает его.
        _force_foreground_window(hwnd)
        cmd = int(user32.TrackPopupMenu(
            hmenu, TPM_RIGHTALIGN | TPM_BOTTOMALIGN | TPM_RETURNCMD | TPM_NONOTIFY,
            pt.x, pt.y, 0, hwnd, None,
        ))
        user32.PostMessageW(hwnd, 0, 0, 0)  # WM_NULL — рекомендованный трюк после TrackPopupMenu
    finally:
        user32.DestroyMenu(hmenu)

    if cmd == _TRAY_MENU_OPEN_RULES:
        _open_file_async(_rules_path(), lambda: _atomic_write_text(_rules_path(), "{}"))
    elif cmd == _TRAY_MENU_OPEN_DICT:
        _open_file_async(_dictionary_path(), lambda: _save_dictionary([]))
    elif cmd == _TRAY_MENU_OPEN_SETTINGS:
        _ui.call(_open_rules_editor_window)
    elif cmd == _TRAY_MENU_OPEN_APP_SETTINGS:
        _open_file_async(_settings_path(), _load_settings)
    elif cmd == _TRAY_MENU_TOGGLE_ACTIVE_WINDOW:
        if not _active_window_only:
            _allowed_hwnd = origin_hwnd
            _active_window_only = True
            logging.info("active_window_only=True, allowed_hwnd=0x%X", _allowed_hwnd)
        else:
            _active_window_only = False
            _allowed_hwnd = 0
            logging.info("active_window_only=False")
    elif cmd == _TRAY_MENU_TOGGLE_DISABLED_HERE:
        if origin_exe:
            now_disabled = _toggle_disabled_for_exe(origin_exe)
            logging.info("disabled_apps: %s %s", origin_exe,
                         "added (disabled)" if now_disabled else "removed (enabled)")
        else:
            logging.info("disabled_apps: skip toggle, origin exe unknown (hwnd=0x%X)", origin_hwnd)
    elif cmd == _TRAY_MENU_OPEN_DISABLED_LIST:
        _open_file_async(_disabled_apps_path(), lambda: _save_disabled_apps(frozenset()))
    elif cmd == _TRAY_MENU_EXIT:
        _request_app_exit()


def _tray_window_proc(hwnd: int, msg: int, w_param: int, l_param: int) -> int:
    global _clipboard_poll_last_seq
    try:
        if _tray_taskbar_created_message and msg == _tray_taskbar_created_message:
            # Explorer перезапустился — иконку нужно добавить заново.
            if _tray_icon_handle:
                _shell_notify_icon(NIM_ADD, _make_notify_icon_data(hwnd, _tray_icon_handle))
            return 0
        if msg == _WM_TRAY_CALLBACK:
            if (l_param & 0xFFFF) == WM_RBUTTONUP:
                _show_tray_menu(hwnd)
            return 0
        if msg == _WM_TRAY_REFRESH:
            if _tray_icon_handle:
                _shell_notify_icon(NIM_MODIFY, _make_notify_icon_data(hwnd, _tray_icon_handle))
            return 0
        if msg == WM_CLIPBOARDUPDATE:
            _request_clipboard_capture()
            return 0
        if msg == WM_TIMER and w_param == _CLIPBOARD_POLL_TIMER_ID:
            seq = int(user32.GetClipboardSequenceNumber())
            if seq != _clipboard_poll_last_seq:
                _clipboard_poll_last_seq = seq
                _request_clipboard_capture()
            return 0
        if msg == WM_CLOSE:
            _dispose_tray_window()
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
    except Exception:
        logging.exception("tray window proc error (msg=0x%X)", msg)
        return 0
    return int(user32.DefWindowProcW(hwnd, msg, w_param, l_param))


def _init_tray_window() -> None:
    global _tray_window_handle, _tray_window_class_name, _tray_window_proc_ref
    global _tray_icon_handle, _tray_icon_owned, _tray_taskbar_created_message

    h_instance = kernel32.GetModuleHandleW(None)
    if not h_instance:
        _raise_last_error("GetModuleHandleW failed for tray icon")

    _tray_taskbar_created_message = int(user32.RegisterWindowMessageW("TaskbarCreated"))
    _tray_window_class_name = f"punto_like_tray_window_{kernel32.GetCurrentProcessId()}_{_get_session_id()}"
    _tray_window_proc_ref = _WNDPROC(_tray_window_proc)

    wnd_class = WNDCLASSW()
    wnd_class.lpfnWndProc = ctypes.cast(_tray_window_proc_ref, ctypes.c_void_p).value
    wnd_class.hInstance = h_instance
    wnd_class.lpszClassName = _tray_window_class_name
    if not user32.RegisterClassW(ctypes.byref(wnd_class)):
        _raise_last_error("RegisterClassW failed for tray icon")

    hwnd = _hwnd_value(user32.CreateWindowExW(
        0, _tray_window_class_name, _tray_window_class_name, 0,
        0, 0, 0, 0, None, None, h_instance, None,
    ))
    if not hwnd:
        user32.UnregisterClassW(_tray_window_class_name, h_instance)
        _raise_last_error("CreateWindowExW failed for tray icon")

    h_icon, owned = _load_tray_icon()
    if not h_icon or not _shell_notify_icon(NIM_ADD, _make_notify_icon_data(hwnd, h_icon)):
        if h_icon and owned:
            user32.DestroyIcon(h_icon)
        user32.DestroyWindow(hwnd)
        user32.UnregisterClassW(_tray_window_class_name, h_instance)
        raise RuntimeError("Failed to add tray icon")

    _tray_window_handle = hwnd
    _tray_icon_handle = h_icon
    _tray_icon_owned = owned


def _start_clipboard_monitoring() -> None:
    """WM_CLIPBOARDUPDATE вместо опроса каждые 300 мс; опрос — только запасной путь."""
    global _clipboard_listener_active, _clipboard_poll_last_seq
    if user32.AddClipboardFormatListener(_tray_window_handle):
        _clipboard_listener_active = True
        logging.info("Clipboard listener installed")
        return
    logging.warning("AddClipboardFormatListener failed — fallback to polling")
    _clipboard_poll_last_seq = int(user32.GetClipboardSequenceNumber())
    if not user32.SetTimer(_tray_window_handle, _CLIPBOARD_POLL_TIMER_ID, 300, None):
        logging.warning("SetTimer for clipboard polling failed — history will not update")


def _stop_clipboard_monitoring() -> None:
    global _clipboard_listener_active
    if not _tray_window_handle:
        return
    if _clipboard_listener_active:
        user32.RemoveClipboardFormatListener(_tray_window_handle)
        _clipboard_listener_active = False
    else:
        user32.KillTimer(_tray_window_handle, _CLIPBOARD_POLL_TIMER_ID)


def _dispose_tray_window() -> None:
    """Убирает иконку и окно. Идемпотентно — безопасно звать повторно."""
    global _tray_window_handle, _tray_icon_handle, _tray_icon_owned
    hwnd = _tray_window_handle
    if hwnd:
        _stop_clipboard_monitoring()
        _shell_notify_icon(NIM_DELETE, _make_notify_icon_data(hwnd, _tray_icon_handle))
        _tray_window_handle = 0
        user32.DestroyWindow(hwnd)  # → WM_DESTROY → PostQuitMessage
    if _tray_icon_owned and _tray_icon_handle:
        user32.DestroyIcon(_tray_icon_handle)
    _tray_icon_handle = 0
    _tray_icon_owned = False


def _tray_thread_main(ready: threading.Event, startup_error: list[BaseException]) -> None:
    _setup_winapi_prototypes()
    try:
        _init_tray_window()
        _install_foreground_event_hook()
        _start_clipboard_monitoring()
    except BaseException as exc:
        startup_error.append(exc)
        _uninstall_foreground_event_hook()
        _dispose_tray_window()
        _unregister_tray_class()
        ready.set()
        return
    ready.set()

    msg = MSG()
    try:
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0 or ret == -1:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    finally:
        _uninstall_foreground_event_hook()
        _dispose_tray_window()
        _unregister_tray_class()


def _unregister_tray_class() -> None:
    global _tray_window_class_name, _tray_window_proc_ref
    h_instance = kernel32.GetModuleHandleW(None)
    if _tray_window_class_name and h_instance:
        user32.UnregisterClassW(_tray_window_class_name, h_instance)
    _tray_window_class_name = ""
    _tray_window_proc_ref = None


def _start_tray_thread() -> None:
    global _tray_thread
    ready = threading.Event()
    startup_error: list[BaseException] = []
    _tray_thread = threading.Thread(target=_tray_thread_main, args=(ready, startup_error),
                                    name="tray", daemon=True)
    _tray_thread.start()
    if not ready.wait(10.0):
        raise RuntimeError("Tray thread did not start in time")
    if startup_error:
        raise startup_error[0]


def _stop_tray_thread(timeout: float = 2.0) -> None:
    global _tray_thread
    if _tray_window_handle:
        user32.PostMessageW(_tray_window_handle, WM_CLOSE, 0, 0)
    if _tray_thread is not None:
        _tray_thread.join(timeout)
        _tray_thread = None

# ═══════════════════════════════════════════════════════════════════════════════
# Low-level hooks (главный поток). Колбэки — только дешёвая работа.
# ═══════════════════════════════════════════════════════════════════════════════

_hook_handle: int = 0
_hook_callback_ref: object | None = None
_mouse_hook_handle: int = 0
_mouse_hook_callback_ref: object | None = None

# Watchdog: время последнего срабатывания любого нашего LL-хука.
_last_hook_event_time: float = 0.0
_HOOK_WATCHDOG_INTERVAL: Final[float] = 5.0
_last_hook_watchdog_check: float = 0.0
_WORKER_STUCK_WARN_SECONDS: Final[float] = 30.0
_worker_stuck_warned: bool = False

_space_keydown_blocked: bool = False
_space_keydown_fg_hwnd: int = 0

# ── Аккорд Ctrl+Alt+Shift → выделить слово под кареткой ──────────────────────
# Срабатывает на ОТПУСКАНИИ, если все три модификатора (любые — левые/правые)
# удерживались одновременно и в это время не нажималась ни одна другая клавиша.
# Состояние модификаторов читаем «вживую» через GetAsyncKeyState, чтобы пропуск
# событий хуком не рассинхронизировал учёт.
_swc_armed: bool = False       # все три были зажаты одновременно
_swc_disarmed: bool = False    # в цикле нажималась посторонняя клавиша → отмена

_SWC_GROUP_BY_VK: Final[dict[int, str]] = {
    VK_LCONTROL: "ctrl", VK_RCONTROL: "ctrl", VK_CONTROL: "ctrl",
    VK_LMENU: "alt", VK_RMENU: "alt", VK_MENU: "alt",
    VK_LSHIFT: "shift", VK_RSHIFT: "shift", VK_SHIFT: "shift",
}
_SWC_GROUP_VKS: Final[dict[str, tuple[int, int]]] = {
    "ctrl": (VK_LCONTROL, VK_RCONTROL),
    "alt": (VK_LMENU, VK_RMENU),
    "shift": (VK_LSHIFT, VK_RSHIFT),
}


def _swc_group_held(group: str) -> bool:
    l_vk, r_vk = _SWC_GROUP_VKS[group]
    return bool((user32.GetAsyncKeyState(l_vk) & 0x8000) or (user32.GetAsyncKeyState(r_vk) & 0x8000))


def _swc_other_two_held(group: Optional[str]) -> bool:
    """group=None → «зажат хоть один модификатор»; иначе «две другие группы зажаты».

    Группу текущего события не проверяем: в LL-хуке её физическое состояние
    может ещё не отразиться в GetAsyncKeyState.
    """
    if group is None:
        return any(_swc_group_held(g) for g in _SWC_GROUP_VKS)
    return all(_swc_group_held(g) for g in _SWC_GROUP_VKS if g != group)


def _swc_on_key_event(vk: int, is_keydown: bool, is_keyup: bool) -> bool:
    """Машина состояний аккорда. True → пора выделить слово.

    • keydown модификатора при двух других зажатых → аккорд собран.
    • keydown любой другой клавиши при зажатых модификаторах → это шорткат
      (Ctrl+Alt+Shift+X), срываем аккорд до конца цикла.
    • keyup любого модификатора при собранном аккорде → выстрел (один раз).
      Здесь не проверяем, держатся ли остальные: при отпускании «пачкой» к
      первому keyup физически может не быть уже ни одного.
    • когда модификаторов не осталось → сброс для нового цикла.
    """
    global _swc_armed, _swc_disarmed
    group = _SWC_GROUP_BY_VK.get(vk)

    if is_keydown:
        if group is None:
            if _swc_other_two_held(None):
                _swc_disarmed = True
            _swc_armed = False
            return False
        if not _swc_other_two_held(group):
            _swc_disarmed = False  # первый модификатор нового цикла
        if not _swc_disarmed and _swc_other_two_held(group):
            _swc_armed = True
        return False

    if is_keyup and group is not None:
        fire = _swc_armed and not _swc_disarmed
        if fire:
            _swc_armed = False
        if not _swc_other_two_held(group):
            _swc_armed = False
            _swc_disarmed = False
        return fire
    return False


def _is_char_vk(vk: int) -> bool:
    """Клавиша, которая (обычно) вставляет символ."""
    return (
        0x30 <= vk <= 0x39      # 0-9
        or 0x41 <= vk <= 0x5A   # A-Z
        or 0x60 <= vk <= 0x6F   # numpad цифры и знаки
        or 0xBA <= vk <= 0xC0   # OEM_1..OEM_3
        or 0xDB <= vk <= 0xDF   # OEM_4..OEM_8
        or vk == 0xE2           # OEM_102
        or vk in (VK_PACKET, VK_PROCESSKEY)  # Unicode-ввод чужих программ, IME
    )


def _on_key_down(vk: int, fg_hwnd: int) -> None:
    global _space_keydown_blocked, _space_keydown_fg_hwnd
    if vk == VK_SPACE:
        _space_keydown_fg_hwnd = fg_hwnd
        _space_keydown_blocked = _is_any_vk_pressed(_SPACE_BLOCKING_MODIFIER_VKS)
        return
    if vk in _IDLE_NEUTRAL_VKS:
        return
    if not _is_char_vk(vk):
        # Стрелки, Home/End, Backspace, Delete, Enter, Tab, Esc... — пользователь
        # ушёл с места набора или правит текст: отложенную замену отменяем.
        _idle.cancel()
        return
    if _is_any_vk_pressed(_TEXT_SHORTCUT_MODIFIER_VKS):
        _idle.cancel()  # Ctrl+A, Ctrl+C... — команда, а не набор
        return
    focus = _get_focused_control_hwnd()
    if not _is_text_input_focus(focus):  # не Edit или поле пароля
        _idle.cancel()
        return
    _idle.schedule(
        _settings.idle_replace_delay_seconds,
        lambda fg=fg_hwnd, f=focus: _idle_rules_job(fg, f),
    )


def _on_space_up(fg_hwnd: int, fg_exe: str) -> None:
    global _space_keydown_blocked, _space_keydown_fg_hwnd
    _idle.cancel()
    blocked, down_fg = _space_keydown_blocked, _space_keydown_fg_hwnd
    _space_keydown_blocked = False
    _space_keydown_fg_hwnd = 0
    if blocked:
        return  # Shift+Space и т.п.
    if down_fg and fg_hwnd and down_fg != fg_hwnd:
        return  # между нажатием и отпусканием сменилось окно
    if fg_exe in _MEDIA_PLAYER_EXES or fg_exe in _CONSOLE_EXES:
        return
    focus = _get_focused_control_hwnd()
    if not _is_text_input_focus(focus):
        return
    # Замену делает worker, а хук ждёт её с жёстким дедлайном: следующие нажатия
    # пользователя придут уже после замены (как было при работе прямо в хуке),
    # но сам хук никогда не висит дольше space_job_deadline_seconds.
    _worker.run_sync(
        "rules-after-space",
        lambda f=focus: _apply_rules_in_edit(f, after_space=True),
        _timings.space_job_deadline_seconds,
    )


def _handle_keyboard_event(msg: int, l_param: int) -> None:
    kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
    if kb.dwExtraInfo == _INJECT_TAG:
        return  # наши собственные синтетические нажатия
    if _is_paused:
        return

    fg_hwnd, fg_exe, disabled = _foreground_info()
    if disabled:
        return  # хоткеи (RegisterHotKey) идут мимо хука и продолжают работать
    if _active_window_only and _allowed_hwnd and fg_hwnd != _allowed_hwnd:
        return

    vk = int(kb.vkCode)
    is_keydown = msg in (WM_KEYDOWN, WM_SYSKEYDOWN)
    is_keyup = msg in (WM_KEYUP, WM_SYSKEYUP)

    if _settings.select_word_chord and _swc_on_key_event(vk, is_keydown, is_keyup):
        logging.info("chord Ctrl+Alt+Shift -> select word under caret")
        _worker.submit("select-word-chord", lambda: select_word_under_caret(_timings))

    if is_keydown:
        _on_key_down(vk, fg_hwnd)
    elif is_keyup and vk == VK_SPACE:
        _on_space_up(fg_hwnd, fg_exe)


def _touch_hook_liveness() -> None:
    global _last_hook_event_time
    now = time.monotonic()
    if now - _last_hook_event_time > 0.2:  # дросселируем запись глобала
        _last_hook_event_time = now


def _keyboard_hook_proc(n_code: int, w_param: int, l_param: int) -> int:
    _touch_hook_liveness()
    if n_code == HC_ACTION:
        try:
            _handle_keyboard_event(int(w_param), l_param)
        except Exception:
            logging.debug("keyboard hook callback error", exc_info=True)
    return int(user32.CallNextHookEx(None, n_code, w_param, l_param))


def _mouse_hook_proc(n_code: int, w_param: int, l_param: int) -> int:
    """Клик/начало выделения мышью отменяет отложенную idle-замену.

    Клавиатурный хук не видит выделение мышью: без этого idle-таймер мог бы
    сработать поверх только что выделенного фрагмента.
    """
    _touch_hook_liveness()
    if n_code == HC_ACTION and int(w_param) in _MOUSE_BUTTON_DOWN_MESSAGES:
        try:
            _idle.cancel()
        except Exception:
            logging.debug("mouse hook callback error", exc_info=True)
    return int(user32.CallNextHookEx(None, n_code, w_param, l_param))


def _install_keyboard_hook() -> None:
    global _hook_handle, _hook_callback_ref
    if _hook_handle:
        return
    _hook_callback_ref = _HOOKPROC(_keyboard_hook_proc)
    h_mod = kernel32.GetModuleHandleW(None)
    if not h_mod:
        _raise_last_error("GetModuleHandleW failed")
    _hook_handle = _hwnd_value(user32.SetWindowsHookExW(
        WH_KEYBOARD_LL, ctypes.cast(_hook_callback_ref, ctypes.c_void_p), h_mod, 0))
    if not _hook_handle:
        _hook_callback_ref = None
        _raise_last_error("SetWindowsHookExW(WH_KEYBOARD_LL) failed")


def _uninstall_keyboard_hook() -> None:
    global _hook_handle, _hook_callback_ref
    if _hook_handle:
        user32.UnhookWindowsHookEx(_hook_handle)
    _hook_handle = 0
    _hook_callback_ref = None


def _install_mouse_hook() -> None:
    global _mouse_hook_handle, _mouse_hook_callback_ref
    if _mouse_hook_handle:
        return
    _mouse_hook_callback_ref = _HOOKPROC(_mouse_hook_proc)
    h_mod = kernel32.GetModuleHandleW(None)
    if not h_mod:
        _raise_last_error("GetModuleHandleW failed")
    _mouse_hook_handle = _hwnd_value(user32.SetWindowsHookExW(
        WH_MOUSE_LL, ctypes.cast(_mouse_hook_callback_ref, ctypes.c_void_p), h_mod, 0))
    if not _mouse_hook_handle:
        # Не критично: работаем и без него, просто без отмены по клику мышью.
        logging.warning("SetWindowsHookExW(WH_MOUSE_LL) failed; mouse-cancel disabled")
        _mouse_hook_callback_ref = None


def _uninstall_mouse_hook() -> None:
    global _mouse_hook_handle, _mouse_hook_callback_ref
    if _mouse_hook_handle:
        user32.UnhookWindowsHookEx(_mouse_hook_handle)
    _mouse_hook_handle = 0
    _mouse_hook_callback_ref = None


def _reinstall_hooks() -> None:
    """Переустанавливает оба LL-хука. Только на главном потоке (с очередью сообщений)."""
    global _last_hook_event_time
    _run_guarded("uninstall keyboard hook", _uninstall_keyboard_hook)
    _run_guarded("uninstall mouse hook", _uninstall_mouse_hook)
    _run_guarded("reinstall keyboard hook", _install_keyboard_hook)
    _run_guarded("reinstall mouse hook", _install_mouse_hook)
    _last_hook_event_time = time.monotonic()


def _watchdog_check_hooks() -> None:
    """Переустанавливает LL-хуки, если Windows их тихо снял.

    Признак: ввод в системе недавно был (GetLastInputInfo), а наши хуки за это
    время не срабатывали. Работа в колбэках теперь короткая, так что основной
    сценарий — смена сессии/блокировка, а не таймаут хука.
    """
    global _last_hook_watchdog_check
    now = time.monotonic()
    if now - _last_hook_watchdog_check < _HOOK_WATCHDOG_INTERVAL:
        return
    _last_hook_watchdog_check = now

    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        return
    # Беззнаковая разница: корректна и после переполнения GetTickCount (~49.7 дня).
    idle_ms = (int(kernel32.GetTickCount()) - int(lii.dwTime)) & 0xFFFFFFFF
    window_ms = _HOOK_WATCHDOG_INTERVAL * 1000.0
    if idle_ms > window_ms:
        return  # ввода не было — пропускать нечего

    since_hook_ms = (now - _last_hook_event_time) * 1000.0
    if since_hook_ms > window_ms:
        logging.warning(
            "Hooks appear dead (last input %dms ago, no hook events for %.0fms) — reinstalling",
            idle_ms, since_hook_ms,
        )
        _reinstall_hooks()


def _watchdog_check_worker() -> None:
    """Пишет в лог, если задача worker'а выполняется подозрительно долго."""
    global _worker_stuck_warned
    name, running_for = _worker.current_job()
    if running_for > _WORKER_STUCK_WARN_SECONDS:
        if not _worker_stuck_warned:
            logging.warning("worker: задача %s выполняется уже %.1f сек", name, running_for)
            _worker_stuck_warned = True
    else:
        _worker_stuck_warned = False

# ═══════════════════════════════════════════════════════════════════════════════
# Hotkeys
# ═══════════════════════════════════════════════════════════════════════════════

# Голые F7–F12 как запасные варианты не регистрируем: они нужны приложениям.
_BLOCKED_PLAIN_FALLBACK_VKS: Final[frozenset[int]] = frozenset({
    VK_F7, VK_F8, VK_F9, VK_F10, VK_F11, VK_F12,
})


def _prepare_hotkey_candidates(candidates: list[HotkeyCombo]) -> list[HotkeyCombo]:
    """Убирает дубликаты и опасные голые fallback-клавиши (основной вариант — любой)."""
    prepared: list[HotkeyCombo] = []
    seen: set[HotkeyCombo] = set()
    for index, (mod, vk) in enumerate(candidates):
        if index > 0 and mod == 0 and vk in _BLOCKED_PLAIN_FALLBACK_VKS:
            continue
        if (mod, vk) in seen:
            continue
        seen.add((mod, vk))
        prepared.append((mod, vk))
    return prepared


def _hotkey_definitions(hk: Hotkeys) -> list[tuple[int, list[HotkeyCombo], str]]:
    """(id, [основной, запасные...], назначение). Основной берётся из настроек."""
    CA = MOD_CONTROL | MOD_ALT
    return [
        (_HK_CONVERT_SELECTED, [hk.convert_selected, (0, VK_INSERT), (MOD_ALT, VK_F8)], "convert-selected"),
        (_HK_CONVERT_BEFORE_CARET, [hk.convert_before_caret, (MOD_CONTROL, VK_INSERT), (MOD_ALT, VK_INSERT),
                                    (CA, VK_INSERT), (MOD_CONTROL, VK_F8)], "convert-before-caret"),
        (_HK_EXIT, [hk.exit, (CA, VK_F12), (MOD_CONTROL, VK_F12), (MOD_ALT, VK_F12)], "exit"),
        (_HK_PAUSE, [hk.pause, (CA, VK_F11), (MOD_CONTROL, VK_F11), (MOD_ALT, VK_F11)], "pause"),
        (_HK_RULES_EDITOR, [hk.rules_editor, (CA, VK_F7), (MOD_CONTROL, VK_F7), (MOD_ALT, VK_F7)], "rules-editor"),
        (_HK_UNDO, [hk.undo, (CA, VK_Z), (CA, VK_F6), (MOD_CONTROL, VK_Z)], "undo-last-change"),
        (_HK_TOGGLE_CASE, [hk.toggle_case, (MOD_ALT, VK_F9), (CA, VK_F9),
                           (MOD_CONTROL, VK_F8), (MOD_CONTROL, VK_F10)], "toggle-case"),
        (_HK_TOGGLE_CASE_BEFORE_CARET, [hk.toggle_case_before_caret, (MOD_CONTROL | MOD_SHIFT, VK_F9),
                                        (MOD_SHIFT | MOD_ALT, VK_F9)], "toggle-case-before-caret"),
        (_HK_CLIPBOARD_PICKER, [hk.clipboard_picker, (MOD_CONTROL, VK_F10), (MOD_ALT, VK_F10), (CA, VK_F10),
                                (MOD_ALT, VK_F8), (MOD_ALT, VK_F9)], "clipboard-picker"),
    ]


def _register_hotkey_with_fallback(hotkey_id: int, candidates: list[HotkeyCombo], purpose: str) -> HotkeyCombo:
    prepared = _prepare_hotkey_candidates(candidates)
    for mod, vk in prepared:
        ctypes.set_last_error(0)
        # MOD_NOREPEAT: удержание клавиши не шлёт серию WM_HOTKEY (и не забивает
        # очередь worker'а повторами одного действия).
        if user32.RegisterHotKey(None, hotkey_id, mod | MOD_NOREPEAT, vk):
            logging.info("Hotkey OK: %s: %s", purpose, _format_hotkey(mod, vk))
            return mod, vk
        last_err = ctypes.get_last_error()
        if last_err != ERROR_HOTKEY_ALREADY_REGISTERED:
            raise OSError(last_err, f"RegisterHotKey failed for {purpose} (winerror={last_err})")
        logging.info("Hotkey busy: %s: %s", purpose, _format_hotkey(mod, vk))
    raise OSError(
        ERROR_HOTKEY_ALREADY_REGISTERED,
        f"RegisterHotKey {purpose} failed (all safe candidates used/blocked)",
    )


def _toggle_pause() -> None:
    global _is_paused
    _is_paused = not _is_paused
    _idle.cancel()
    _post_tray_refresh()
    logging.info("PAUSED" if _is_paused else "RESUMED")


def _on_hotkey(hotkey_id: int) -> bool:
    """Обрабатывает WM_HOTKEY на главном потоке. False — пора выходить."""
    if hotkey_id == _HK_EXIT:
        return False
    if hotkey_id == _HK_PAUSE:
        _toggle_pause()
        return True
    if _is_paused:
        return True

    timings = _timings
    if hotkey_id == _HK_CLIPBOARD_PICKER:
        # Окно, в которое потом вставлять, запоминаем сейчас — до открытия Tk.
        target = _hwnd_value(user32.GetForegroundWindow())
        _worker.submit("clipboard-picker", lambda: _prepare_clipboard_picker(target))
    elif hotkey_id == _HK_RULES_EDITOR:
        _ui.call(_open_rules_editor_window)
    elif hotkey_id == _HK_CONVERT_SELECTED:
        _idle.cancel()
        _worker.submit("convert-selected", lambda: convert_selected_text(timings))
    elif hotkey_id == _HK_CONVERT_BEFORE_CARET:
        _idle.cancel()
        _worker.submit("convert-before-caret", lambda: convert_before_caret_text(timings))
    elif hotkey_id == _HK_TOGGLE_CASE:
        _idle.cancel()
        _worker.submit("toggle-case", lambda: toggle_case_selected_text(timings))
    elif hotkey_id == _HK_TOGGLE_CASE_BEFORE_CARET:
        _idle.cancel()
        _worker.submit("toggle-case-before-caret", lambda: toggle_case_before_caret_text(timings))
    elif hotkey_id == _HK_UNDO:
        _idle.cancel()
        _worker.submit("undo-last-change", lambda: undo_last_change(timings))
    return True

# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def run_app() -> None:
    global _timings, _settings, _main_thread_id, _last_hook_event_time
    _configure_stdio_utf8()
    _setup_winapi_prototypes()
    _setup_logging()
    _settings = _load_settings()
    _timings = Timings()
    _reload_rules()
    _reload_disabled_apps()
    _main_thread_id = int(kernel32.GetCurrentThreadId())
    _ensure_thread_message_queue()  # чтобы PostThreadMessageW из трея не потерялся

    mutex_handle = _ensure_single_instance("punto_like_single_instance_v1")
    hotkey_defs = _hotkey_definitions(_settings.hotkeys)
    registered_ids: list[int] = []
    timer_id = 0
    try:
        for hk_id, candidates, purpose in hotkey_defs:
            _register_hotkey_with_fallback(hk_id, candidates, purpose)
            registered_ids.append(hk_id)

        logging.info("punto_like started (session=%d, rdp=%s)", _get_session_id(), _is_rdp_session())
        logging.info(
            "settings: replace_method=%s, idle=%.1fs, history=%d items/%d MB, chord=%s",
            _settings.replace_method, _settings.idle_replace_delay_seconds,
            _settings.clipboard_history_max_items, _settings.clipboard_history_max_total_bytes // 1_000_000,
            _settings.select_word_chord,
        )

        _worker.start()
        _idle.start()
        _start_tray_thread()
        _worker.submit("clipboard-capture-initial", lambda: _capture_clipboard_to_history(_timings, force=True))
        _install_keyboard_hook()
        _install_mouse_hook()
        _last_hook_event_time = time.monotonic()

        # Двойной бип — слышимое подтверждение, что запущена именно эта версия.
        # Один бип = срабатывание аккорда Ctrl+Alt+Shift.
        user32.MessageBeep(0x00000040)
        time.sleep(0.18)
        user32.MessageBeep(0x00000040)

        # Для hwnd=NULL система сама генерирует ID таймера (переданный
        # игнорируется), поэтому сравниваем wParam с возвращённым значением.
        timer_id = int(user32.SetTimer(None, 0, 1000, None))
        if not timer_id:
            _raise_last_error("SetTimer failed")

        msg = MSG()
        while True:
            try:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret == 0:
                    break
                if ret == -1:
                    _raise_last_error("GetMessageW failed")

                if msg.message == _WM_APP_EXIT and not msg.hwnd:
                    break
                if msg.message == WM_TIMER and not msg.hwnd and int(msg.wParam) == timer_id:
                    # Watchdog хуков — даже на паузе: хук должен оставаться живым.
                    _run_guarded("hook-watchdog", _watchdog_check_hooks)
                    _run_guarded("worker-watchdog", _watchdog_check_worker)
                    continue
                if msg.message == WM_HOTKEY:
                    if not _on_hotkey(int(msg.wParam)):
                        break
                    continue

                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            except KeyboardInterrupt:
                break
            except Exception:
                logging.exception("Main loop error")
    finally:
        if timer_id:
            _run_guarded("KillTimer", lambda: user32.KillTimer(None, timer_id))
        _run_guarded("uninstall keyboard hook", _uninstall_keyboard_hook)
        _run_guarded("uninstall mouse hook", _uninstall_mouse_hook)
        _run_guarded("stop idle scheduler", _idle.stop)
        _run_guarded("stop worker", _worker.stop)
        _run_guarded("stop ui", _ui.stop)
        _run_guarded("stop tray", _stop_tray_thread)
        for hk_id in registered_ids:
            _run_guarded("UnregisterHotKey", lambda hk_id=hk_id: user32.UnregisterHotKey(None, hk_id))
        _run_guarded("CloseHandle(mutex)", lambda: kernel32.CloseHandle(mutex_handle))


def _worker_entrypoint() -> int:
    _configure_stdio_utf8()
    _setup_winapi_prototypes()
    _setup_logging()
    _setup_threading_excepthook()
    _setup_fault_handler()
    try:
        run_app()
        logging.info("Worker stopped normally")
        return _WORKER_EXIT_OK
    except KeyboardInterrupt:
        logging.info("Worker interrupted by user")
        return _WORKER_EXIT_OK
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else _WORKER_EXIT_OK
        logging.info("Worker stopped via SystemExit(code=%s)", code)
        return _WORKER_EXIT_OK if code == 0 else _WORKER_EXIT_CRASH
    except RuntimeError as exc:
        if str(exc) == "Another instance is already running":
            msg = (
                f"Скрипт уже запущен в этой сессии (session={_get_session_id()}, rdp={_is_rdp_session()}).\n\n"
                "Закройте предыдущий экземпляр (Ctrl+Alt+F12) или завершите процесс python.exe."
            )
            print(msg)
            _show_message_box("punto_like", msg)
            logging.info("Worker stopped because another instance is already running")
            return _WORKER_EXIT_ALREADY_RUNNING
        logging.exception("Unhandled RuntimeError in worker")
        return _WORKER_EXIT_CRASH
    except BaseException:
        logging.exception("Fatal worker crash")
        return _WORKER_EXIT_CRASH

# ═══════════════════════════════════════════════════════════════════════════════
# Supervisor
# ═══════════════════════════════════════════════════════════════════════════════

def _create_kill_on_close_job() -> int:
    """Job Object, который убивает worker вместе с супервизором.

    Раньше структура лимитов передавалась нулями (флаг KILL_ON_JOB_CLOSE не
    выставлялся) и неверного размера — Job ничего не делал, и после убийства
    супервизора worker оставался висеть.
    """
    job = _hwnd_value(kernel32.CreateJobObjectW(None, None))
    if not job:
        logging.warning("CreateJobObjectW failed (winerror=%d)", ctypes.get_last_error())
        return 0
    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = (
        _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | _JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK
    )
    if not kernel32.SetInformationJobObject(
        job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS, ctypes.byref(info), ctypes.sizeof(info),
    ):
        logging.warning("SetInformationJobObject failed (winerror=%d)", ctypes.get_last_error())
        kernel32.CloseHandle(job)
        return 0
    return job


def _supervisor_entrypoint() -> int:
    _configure_stdio_utf8()
    _setup_winapi_prototypes()
    _setup_logging()
    job = _create_kill_on_close_job()

    script_path = Path(__file__).resolve()
    restart_count = 0

    while True:
        started_at = time.monotonic()
        logging.info("Supervisor: starting worker")

        try:
            proc = subprocess.Popen([sys.executable, str(script_path), "--worker"])
        except Exception:
            restart_count += 1
            delay = min(_SUPERVISOR_RESTART_MAX_DELAY_SECONDS, _SUPERVISOR_RESTART_BASE_DELAY_SECONDS * restart_count)
            logging.exception("Supervisor: failed to start worker, retry in %.1f s", delay)
            time.sleep(delay)
            continue

        if job and not kernel32.AssignProcessToJobObject(job, int(proc._handle)):
            logging.warning("AssignProcessToJobObject failed (winerror=%d)", ctypes.get_last_error())

        exit_code = proc.wait()
        uptime = time.monotonic() - started_at

        if exit_code in (_WORKER_EXIT_OK, _WORKER_EXIT_ALREADY_RUNNING):
            logging.info("Supervisor: worker exited normally (code=%s, uptime=%.1fs)", exit_code, uptime)
            return 0

        if uptime >= _SUPERVISOR_STABLE_UPTIME_SECONDS:
            restart_count = 0
        restart_count += 1
        delay = min(_SUPERVISOR_RESTART_MAX_DELAY_SECONDS, _SUPERVISOR_RESTART_BASE_DELAY_SECONDS * restart_count)
        logging.error(
            "Supervisor: worker crashed (code=%s, uptime=%.1fs), restart in %.1f s",
            exit_code, uptime, delay,
        )
        time.sleep(delay)



# ============================================================
# ОТДЕЛЬНЫЙ ЗНАЧОК В ТРЕЕ
# ============================================================
# Windows различает значки трея по exe. Если скрипт запущен общим
# python.exe/pythonw.exe (например, из Choice), перезапускаем его под своей
# копией NP_Punto.exe (их делает make_portable.py в папке Runtime). Нет копии — работаем как есть.

def _relaunch_under_own_exe(exe_name: str = "NP_Punto") -> None:
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


def _main_entrypoint() -> int:
    if not _IS_WINDOWS:
        print("punto_like работает только в Windows.", file=sys.stderr)
        return 1
    if "--worker" in sys.argv[1:]:
        return _worker_entrypoint()
    _relaunch_under_own_exe()
    return _supervisor_entrypoint()


if __name__ == "__main__":
    raise SystemExit(_main_entrypoint())
