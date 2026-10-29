"""Мелкие вспомогательные функции без собственного состояния.

Ленивый импорт ``keyboard`` (модуль опциональный), очистка HTML,
фабрика редактируемого QComboBox, вставка из буфера и копирование
дефолтных иконок при первом запуске.
"""

import html as html_lib
import importlib.util
import re
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtWidgets import QApplication, QComboBox

from .config import APPDIR, FILE_ICON_PATH, ICON_PATH, TRAY_ICON_PATH
from .widgets.message_box import messagebox


def strip_html(text: str) -> str:
    if not text:
        return ""
    try:
        s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", text)
        s = re.sub(r"(?i)<br\s*/?>", "\n", s)
        s = re.sub(r"(?i)</p\s*>", "\n", s)
        s = re.sub(r"<[^>]+>", "", s)
        s = html_lib.unescape(s)
        return s
    except Exception:
        return re.sub(r"<[^>]+>", "", text)


_keyboard_module = None


def get_keyboard_module():
    global _keyboard_module
    if _keyboard_module is not None:
        return _keyboard_module
    spec = importlib.util.find_spec("keyboard")
    if spec is None or getattr(spec, "loader", None) is None:
        _keyboard_module = None
        return None
    try:
        # Обычный импорт: модуль попадает в sys.modules. Раньше exec_module
        # без регистрации давал вторую копию keyboard при любом «import keyboard»
        # в другом месте — с отдельным хуком и отдельным списком горячих клавиш.
        module = importlib.import_module("keyboard")
        _keyboard_module = module
        return module
    except Exception:
        _keyboard_module = None
        return None


def create_dropdown_combo(*items, parent=None):
    combo = QComboBox(parent)
    combo.setEditable(True)
    flat_items = []
    for item in items:
        if isinstance(item, (list, tuple, set)):
            flat_items.extend(item)
        else:
            flat_items.append(item)
    combo.addItems([str(i) for i in flat_items])

    def _commit_new_item() -> None:
        text = combo.currentText().strip()
        if text and combo.findText(text) == -1:
            combo.addItem(text)
            combo.setCurrentText(text)

    combo.lineEdit().editingFinished.connect(_commit_new_item)
    return combo


def copy_default_icons() -> None:
    # ВНИМАНИЕ: в монолите здесь стоял Path(__file__).parent, потому что файл
    # лежал в корне приложения. После переноса в noteapp/ это уехало бы в
    # noteapp/Data, поэтому берём APPDIR (корень лаунчера) — прежнее поведение.
    app_root = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else APPDIR
    )
    src_root = app_root / "Data"
    icon_names = ["icon.ico", "tray_icon.ico", "file.ico"]
    destination_paths = [ICON_PATH, TRAY_ICON_PATH, FILE_ICON_PATH]

    for name, dst in zip(icon_names, destination_paths):
        src = src_root / name
        if src.is_file() and not dst.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(str(src), str(dst))


def paste_from_clipboard(widget) -> None:
    if widget is None:
        return
    try:
        text = QApplication.clipboard().text() or ""
    except Exception as exc:
        messagebox.showerror("Ошибка", f"Не удалось прочитать буфер обмена: {exc}")
        return
    if not text:
        return
    try:
        if hasattr(widget, "setText"):
            widget.setText(text)
            return
        if hasattr(widget, "insertPlainText"):
            widget.insertPlainText(text)
            return
        if hasattr(widget, "insertHtml"):
            widget.insertHtml(text)
            return
        if hasattr(widget, "insert"):
            widget.insert(text)
            return
    except Exception as exc:
        messagebox.showerror("Ошибка", f"Не удалось вставить из буфера: {exc}")


def safe_folder_name(title, note_uuid, timestamp=None):
    safe_title = re.sub(r"[^\w\-_ ]", "_", title)[:40].strip()
    if isinstance(timestamp, str):
        dt = QDateTime.fromString(timestamp, Qt.ISODate)
    elif isinstance(timestamp, QDateTime):
        dt = timestamp
    else:
        dt = QDateTime.currentDateTime()
    dt_str = dt.toString("dd.MM.yyyy HH-mm")
    uuid_short = (
        note_uuid if note_uuid.startswith("UUID_") else f"UUID({note_uuid[:8]})"
    )
    return f"{safe_title} от {dt_str}, {uuid_short}"
