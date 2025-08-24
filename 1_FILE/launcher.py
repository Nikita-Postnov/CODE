import os
import sys
import json
import re
import string
import random
import difflib
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import wave
import traceback
import base64
import html as html_lib

try:
    import pyperclip
except ImportError:
    pyperclip = None
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
from PySide6.QtPrintSupport import QPrinter
from docx import Document

try:
    from spellchecker import SpellChecker
except ImportError:
    SpellChecker = None
import numpy as np
import time
import math
import tempfile
import uuid
import shutil
import datetime
import sounddevice as sd
import importlib.util
from urllib.parse import quote, unquote
from typing import Callable
from PySide6.QtCore import (
    Qt,
    QMimeData,
    QTimer,
    QUrl,
    QSettings,
    QSize,
    QEvent,
    QDateTime,
    QPoint,
    QRect,
    QThread,
    Signal,
    QBuffer,
    QPointF,
    QIODevice,
    QFileSystemWatcher,
)
from PySide6.QtGui import (
    QIcon,
    QDragEnterEvent,
    QDropEvent,
    QMouseEvent,
    QContextMenuEvent,
    QCursor,
    QShortcut,
    QPainterPath,
    QImageReader,
    QFont,
    QImage,
    QPixmap,
    QKeySequence,
    QCloseEvent,
    QDrag,
    QAction,
    QPen,
    QColor,
    QTextCharFormat,
    QDesktopServices,
    QTextCursor,
    QPolygonF,
    QTransform,
    QTextListFormat,
    QTextBlockFormat,
    QPainter,
    QPalette,
    QTextDocument,
    QSyntaxHighlighter,
)
from scipy.io.wavfile import write
from PySide6.QtWidgets import (
    QApplication,
    QLayoutItem,
    QStyle,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QMainWindow,
    QTextEdit,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QTextBrowser,
    QFileDialog,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QWidget,
    QLabel,
    QSizePolicy,
    QLineEdit,
    QMessageBox,
    QInputDialog,
    QColorDialog,
    QSpinBox,
    QScrollArea,
    QLayout,
    QStyleFactory,
    QToolTip,
    QFontComboBox,
    QDialog,
    QDialogButtonBox,
    QComboBox,
    QCheckBox,
    QSystemTrayIcon,
    QAbstractItemView,
    QMenu,
    QDateTimeEdit,
    QSplitter,
    QToolBar,
    QDockWidget,
    QToolButton,
    QFrame,
)

if getattr(sys, "frozen", False):
    APPDIR = os.path.dirname(sys.executable)
else:
    APPDIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(APPDIR, "Data")
NOTES_DIR = os.path.join(APPDIR, "Notes")
PASSWORDS_DIR = os.path.join(APPDIR, "Passwords")
SALT_PATH = os.path.join(DATA_DIR, "salt.bin")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.ini")
ICON_PATH = os.path.join(DATA_DIR, "icon.ico")
TRAY_ICON_PATH = os.path.join(DATA_DIR, "tray_icon.ico")
FILE_ICON_PATH = os.path.join(DATA_DIR, "file.ico")
USER_DICT_PATH = os.path.join(DATA_DIR, "user_dictionary.txt")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(NOTES_DIR, exist_ok=True)
os.makedirs(PASSWORDS_DIR, exist_ok=True)
if not os.path.exists(USER_DICT_PATH):
    with open(USER_DICT_PATH, "a", encoding="utf-8"):
        pass
MAX_HISTORY = 250
IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".bmp", ".gif"]
AUDIO_EXTENSIONS = [".wav", ".mp3", ".ogg"]
ATTACH_FILE_FILTER = (
    f"Изображения ({' '.join('*' + ext for ext in IMAGE_EXTENSIONS)})"
    f";;Аудио ({' '.join('*' + ext for ext in AUDIO_EXTENSIONS)})"
    f";;Все файлы (*.*)"
)


def create_list(*items):
    return list(items)


EXAMPLE_NUMBERS = create_list(1, 2, 3, 4)
EXAMPLE_WORDS = create_list("alpha", "beta", "gamma")
EXAMPLE_MIXED = create_list("hello", 42, 3.14)


class SpellCheckHighlighter(QSyntaxHighlighter):

    def __init__(self, parent):
        super().__init__(parent)
        self.err_fmt = QTextCharFormat()
        self.err_fmt.setUnderlineColor(Qt.red)
        self.err_fmt.setUnderlineStyle(QTextCharFormat.SpellCheckUnderline)
        if SpellChecker is not None:
            try:
                self.spell_checker = SpellChecker(language="ru")
            except Exception:
                self.spell_checker = SpellChecker()
        else:
            self.spell_checker = None
        self._load_user_dictionary()
        try:
            self._dict_watcher = QFileSystemWatcher([USER_DICT_PATH])
            self._dict_watcher.fileChanged.connect(self._reload_user_dictionary)
        except Exception:
            self._dict_watcher = None

    def _load_user_dictionary(self) -> None:
        prev_local = getattr(self, "local_ignored", set())
        self.user_words = set()
        self.local_ignored = set()
        try:
            with open(USER_DICT_PATH, "r", encoding="utf-8") as f:
                words = [line.strip().lower() for line in f if line.strip()]
            self.user_words.update(words)
            if self.spell_checker and words:
                self.spell_checker.word_frequency.load_words(words)
        except Exception:
            pass
        self.local_ignored = prev_local

    def add_to_dictionary(self, word: str) -> None:
        w = (word or "").strip().lower()
        if not w or w in getattr(self, "user_words", set()):
            return
        try:
            with open(USER_DICT_PATH, "a", encoding="utf-8") as f:
                f.write(w + "\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            return
        self._load_user_dictionary()
        self.rehighlight()
        w = word.strip().lower()
        if not w or w in getattr(self, "user_words", set()):
            return
        try:
            with open(USER_DICT_PATH, "a", encoding="utf-8") as f:
                f.write(w + "\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            return
        self._load_user_dictionary()
        self.rehighlight()

    def set_local_ignored(self, words: list[str] | set[str]) -> None:
        self.local_ignored = {w.strip().lower() for w in words if w.strip()}
        self.rehighlight()

    def _reload_user_dictionary(self, path: str) -> None:
        if self._dict_watcher and path not in self._dict_watcher.files():
            try:
                self._dict_watcher.addPath(path)
            except Exception:
                pass
        self._load_user_dictionary()
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        if not self.spell_checker:
            return
        matches = list(re.finditer(r"[A-Za-zА-Яа-яЁё']+", text))
        if not matches:
            return
        words = [m.group().lower() for m in matches]
        misspelled = self.spell_checker.unknown(words)
        misspelled -= getattr(self, "user_words", set())
        misspelled -= getattr(self, "local_ignored", set())
        for match in matches:
            word = match.group().lower()
            if word in misspelled:
                self.setFormat(match.start(), match.end() - match.start(), self.err_fmt)


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


def handle_exception(exc_type, exc_value, exc_traceback):
    traceback.print_exception(exc_type, exc_value, exc_traceback)


sys.excepthook = lambda t, v, tb: print("Uncaught exception:", t, v)


def copy_default_icons():
    app_root = (
        os.path.dirname(sys.executable)
        if getattr(sys, "frozen", False)
        else os.path.abspath(os.path.dirname(__file__))
    )
    src_root = os.path.join(app_root, "Data")
    icon_names = ["icon.ico", "tray_icon.ico", "file.ico"]
    destination_paths = [ICON_PATH, TRAY_ICON_PATH, FILE_ICON_PATH]
    for name, dst in zip(icon_names, destination_paths):
        src = os.path.join(src_root, name)
        if os.path.isfile(src) and not os.path.isfile(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy(src, dst)


copy_default_icons()


def paste_from_clipboard(widget):
    if pyperclip is None:
        messagebox.showerror("Ошибка", "pyperclip не установлен.")
        return
    if not widget or not hasattr(widget, "delete") or not hasattr(widget, "insert"):
        return
    try:
        text = pyperclip.paste()
        if isinstance(widget, (tk.Entry, ttk.Entry)):
            widget.delete(0, tk.END)
            widget.insert(0, text)
        else:
            if hasattr(widget, "selection_present") and widget.selection_present():
                widget.delete("sel.first", "sel.last")
            widget.insert(tk.INSERT, text)
    except (tk.TclError, pyperclip.PyperclipException) as exc:
        messagebox.showerror("Ошибка", f"Не удалось вставить из буфера: {exc}")


CUSTOM_MENU_STYLE = """
QMenu {
    background-color: #282828;
    color: #fff;
    border-radius: 10px;
    font-size: 15px;
    padding: 6px;
}
QMenu::item {
    background-color: transparent;
    color: #fff;
    padding: 8px 32px 8px 24px;
    border-radius: 6px;
}
QMenu::item:selected {
    background-color: #fff;
    color: #111;
    border-radius: 6px;
    border: 2px solid #7a7a7a;
}
QMenu::separator {
    height: 1px;
    background: #444;
    margin: 8px 0;
}
"""


class AudioRecorderThread(QThread):
    recording_finished = Signal(str)

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
        self._running = True
        self._wavefile = None

    def callback(self, indata, frames, time, status):
        if self._running and self._wavefile:
            self._wavefile.writeframes(indata.tobytes())

    def run(self):
        try:
            with wave.open(self.file_path, "wb") as wf:
                self._wavefile = wf
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(44100)
                with sd.InputStream(
                    samplerate=44100,
                    channels=1,
                    dtype="int16",
                    callback=self.callback,
                ):
                    while self._running:
                        sd.sleep(100)
            self.recording_finished.emit(self.file_path)
        except Exception as e:
            print("Ошибка записи:", e)
        finally:
            self._wavefile = None

    def stop(self):
        self._running = False


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, spacing=6):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self.itemList = []

    def addItem(self, item: QLayoutItem) -> None:
        self.itemList.append(item)

    def count(self) -> int:
        return len(self.itemList)

    def itemAt(self, index: int) -> QLayoutItem | None:
        return self.itemList[index] if index < len(self.itemList) else None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self.itemList):
            return self.itemList.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width: int) -> int:
        height = self.doLayout(QRect(0, 0, width, 0), True)
        return height

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self.doLayout(rect, False)

    def doLayout(self, rect: QRect, testOnly: bool) -> int:
        x = rect.x()
        y = rect.y()
        lineHeight = 0

        for item in self.itemList:
            wid = item.widget()
            spaceX = self.spacing() + wid.style().layoutSpacing(
                QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Horizontal
            )
            spaceY = self.spacing() + wid.style().layoutSpacing(
                QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Vertical
            )
            if wid is not None and wid.property("flow_break") is True:
                x = rect.x()
                y = y + lineHeight + spaceY
                lineHeight = 0
                continue
            nextX = x + item.sizeHint().width() + spaceX
            if nextX - spaceX > rect.right() and lineHeight > 0:
                x = rect.x()
                y = y + lineHeight + spaceY
                nextX = x + item.sizeHint().width() + spaceX
                lineHeight = 0
            if not testOnly:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x = nextX
            lineHeight = max(lineHeight, item.sizeHint().height())
        return y + lineHeight - rect.y()


class CustomTextEdit(QTextEdit):
    def __init__(
        self,
        parent: QWidget | None = None,
        paste_image_callback: Callable | None = None,
    ):
        super().__init__(parent)
        self.paste_image_callback = paste_image_callback
        self.setFont(QFont("Times New Roman", 14))
        self.setCurrentFont(QFont("Times New Roman"))
        self.setFontPointSize(14)
        self.setAcceptDrops(True)

    def insertFromMimeData(self, source: QMimeData) -> None:
        if source.hasImage() and self.paste_image_callback:
            image = source.imageData()
            self.paste_image_callback(image)
        elif source.hasHtml():
            html = source.html()
            html = re.sub(r"font-family:[^;\"]*;?", "", html, flags=re.IGNORECASE)
            html = re.sub(r"font-size:[^;\"]*;?", "", html, flags=re.IGNORECASE)
            self.textCursor().insertHtml(html)
        elif source.hasText():
            fmt = QTextCharFormat()
            fmt.setFont(QFont("Times New Roman", 14))
            self.textCursor().insertText(source.text(), fmt)
        else:
            super().insertFromMimeData(source)

    def ignore_in_this_note(self, word: str) -> None:  # NEW
        mw = self.window()
        if hasattr(mw, "add_word_to_note_ignore"):
            mw.add_word_to_note_ignore(word)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            cursor = self.textCursor()
            block_text = cursor.block().text()
            normalized = block_text.lstrip("\u202a\u202c\ufeff\u200b\xa0 ").replace(
                "\xa0", " "
            )
            m = re.match(r"^[☐☑][ \u00A0]", normalized)
            if m:
                after_marker = normalized[m.end() :]
                if after_marker.strip() == "":
                    super().keyPressEvent(event)
                    return
                else:
                    super().keyPressEvent(event)
                    cursor = self.textCursor()
                    cursor.insertText("☐ ")
                    self.setTextCursor(cursor)
                    return
            if block_text.strip().startswith("• "):
                if block_text.strip() == "•":
                    cursor.movePosition(QTextCursor.StartOfBlock)
                    cursor.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, 2)
                    cursor.removeSelectedText()
                    super().keyPressEvent(event)
                    return
                else:
                    super().keyPressEvent(event)
                    cursor = self.textCursor()
                    cursor.insertText("• ")
                    self.setTextCursor(cursor)
                    return
            num_match = re.match(r"^(\d+)\. ", block_text.strip())
            if num_match:
                number = int(num_match.group(1))
                if block_text.strip() == f"{number}.":
                    cursor.movePosition(QTextCursor.StartOfBlock)
                    cursor.movePosition(
                        QTextCursor.Right,
                        QTextCursor.KeepAnchor,
                        len(num_match.group(0)),
                    )
                    cursor.removeSelectedText()
                    super().keyPressEvent(event)
                    return
                else:
                    super().keyPressEvent(event)
                    cursor = self.textCursor()
                    cursor.insertText(f"{number + 1}. ")
                    self.setTextCursor(cursor)
                    return
        super().keyPressEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                if os.path.isfile(file_path):
                    main_window = self.window()
                    if hasattr(main_window, "attach_file_to_note_external"):
                        main_window.attach_file_to_note_external(file_path)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def _sanitize_windows_path(self, p: str) -> str:
        if not p:
            return p
        p = p.strip().strip('"')
        bad = "\ufeff\u200b\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
        p = p.translate({ord(ch): None for ch in bad})
        p = p.replace("/", os.sep)
        parts = [re.sub(r"[ \.]+$", "", part) for part in p.split(os.sep)]
        p = os.sep.join(parts)
        return os.path.normpath(p)

    def _open_any_link(self, link: str) -> bool:
        try:
            s = html_lib.unescape((link or "").strip())
            url = QUrl.fromUserInput(s)
            is_file_like = (url.scheme().lower() == "file") or re.match(
                r"^[a-zA-Z]:[\\/]", s
            )
            if is_file_like:
                if url.scheme().lower() == "file":
                    local_path = url.toLocalFile()
                    if not local_path:
                        raw_path = (
                            QUrl(s).path() if s.lower().startswith("file://") else s
                        )
                        raw_path = raw_path or ""
                        raw_path = unquote(raw_path).lstrip("/").replace("/", os.sep)
                        local_path = raw_path
                else:
                    local_path = s
                local_path = self._sanitize_windows_path(local_path)

                def try_open(p: str) -> bool:
                    if sys.platform.startswith("win"):
                        try:
                            os.startfile(p)
                            return True
                        except Exception:
                            pass
                        try:
                            from PySide6.QtCore import QProcess

                            return QProcess.startDetached(
                                "cmd", ["/c", "start", "", f'"{p}"']
                            )
                        except Exception:
                            pass
                    return QDesktopServices.openUrl(QUrl.fromLocalFile(p))

                if os.path.exists(local_path):
                    return try_open(local_path)
                lower = local_path.replace("/", os.sep).replace("\\", os.sep).lower()
                sep_notes = f"{os.sep}notes{os.sep}"
                if sep_notes in lower:
                    suffix = local_path[
                        len(lower) - len(lower.split(sep_notes, 1)[1]) :
                    ]
                    candidate = os.path.join(NOTES_DIR, suffix)
                    if os.path.exists(candidate):
                        return try_open(candidate)
                mw = self.window()
                if hasattr(mw, "current_note") and mw.current_note:
                    folder = NotesApp.safe_folder_name(
                        mw.current_note.title,
                        mw.current_note.uuid,
                        mw.current_note.timestamp,
                    )
                    candidate = os.path.join(
                        NOTES_DIR, folder, os.path.basename(local_path)
                    )
                    if os.path.exists(candidate):
                        return try_open(candidate)
                return try_open(local_path)
            if not url.scheme():
                url = QUrl.fromUserInput("https://" + s)
            return QDesktopServices.openUrl(url)
        except Exception:
            return False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        cursor = self.cursorForPosition(pos)
        char_format = cursor.charFormat()
        if event.button() == Qt.LeftButton:
            if char_format.isAnchor():
                link = char_format.anchorHref()
                if link.startswith("dropdown://"):
                    dd_id = link.split("://", 1)[1]
                    main_window = self.window()
                    if hasattr(main_window, "show_dropdown_menu_for_token"):
                        rect = self.cursorRect(cursor)
                        global_pos = self.viewport().mapToGlobal(rect.bottomLeft())
                        main_window.show_dropdown_menu_for_token(dd_id, global_pos)
                    return
                if event.modifiers() & Qt.ControlModifier:
                    self._open_any_link(link)
                    return
                super().mousePressEvent(event)
                return
            if char_format.isImageFormat():
                if event.modifiers() & Qt.ControlModifier:
                    image_format = char_format.toImageFormat()
                    image_path = image_format.name()
                    if image_path.startswith("Data:image"):
                        header, b64data = image_path.split(",", 1)
                        suffix = ".png" if "png" in header else ".jpg"
                        with tempfile.NamedTemporaryFile(
                            delete=False, suffix=suffix
                        ) as tmpfile:
                            tmpfile.write(base64.b64decode(b64data))
                            tmpfile_path = tmpfile.name
                        QDesktopServices.openUrl(QUrl.fromLocalFile(tmpfile_path))
                    elif image_path.startswith("file://"):
                        file_path = QUrl(image_path).toLocalFile()
                        if os.path.exists(file_path):
                            self._open_any_link(image_path)
                else:
                    super().mousePressEvent(event)
                return
            if event.modifiers() & Qt.ControlModifier:
                block_cursor = self.cursorForPosition(pos)
                block_cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                block_html = block_cursor.selection().toHtml()
                m = re.search(r'href="((?:file|https?)://[^"]+)"', block_html)
                if m:
                    self._open_any_link(html_lib.unescape(m.group(1)))
                    return
            word_cursor = self.cursorForPosition(pos)
            word_cursor.select(QTextCursor.SelectionType.WordUnderCursor)
            word = word_cursor.selectedText()
            if word == "☐":
                word_cursor.insertText("☑")
                return
            elif word == "☑":
                word_cursor.insertText("☐")
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        cursor = self.cursorForPosition(pos)
        cf = cursor.charFormat()
        if cf.isAnchor():
            if event.modifiers() & Qt.ControlModifier:
                self._open_any_link(cf.anchorHref())
                return
            super().mouseDoubleClickEvent(event)
            return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        cf = self.cursorForPosition(pos).charFormat()
        if cf.isAnchor() and (event.modifiers() & Qt.ControlModifier):
            self.viewport().setCursor(Qt.PointingHandCursor)
        else:
            self.viewport().setCursor(Qt.IBeamCursor)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self.viewport().unsetCursor()
        super().leaveEvent(event)

    def create_drag_image(self, widget: QWidget) -> QPixmap:
        pixmap = widget.grab()
        scale_factor = 0.4
        scaled_pixmap = pixmap.scaled(
            pixmap.size() * scale_factor, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        painter = QPainter(scaled_pixmap)
        path = QPainterPath()
        path.addRect(0, 0, scaled_pixmap.width() - 1, scaled_pixmap.height() - 1)
        pen = QPen(QColor(0, 0, 0), 1)
        painter.setPen(pen)
        painter.drawPath(path)
        return scaled_pixmap

    def delete_selection(self) -> None:
        cursor = self.textCursor()
        if cursor.hasSelection():
            cursor.removeSelectedText()

    def replace_word(self, cursor: QTextCursor, new_word: str) -> None:
        cursor.beginEditBlock()
        cursor.removeSelectedText()
        cursor.insertText(new_word)
        cursor.endEditBlock()

    def add_to_dictionary(self, word: str) -> None:
        main_window = self.window()
        highlighter = getattr(main_window, "spell_highlighter", None)
        if highlighter:
            highlighter.add_to_dictionary(word)
            highlighter.rehighlight()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(CUSTOM_MENU_STYLE)
        undo_action = QAction("Undo", self)
        undo_action.setShortcut("Ctrl+Z")
        undo_action.triggered.connect(self.undo)
        menu.addAction(undo_action)
        redo_action = QAction("Redo", self)
        redo_action.setShortcut("Ctrl+Y")
        redo_action.triggered.connect(self.redo)
        menu.addAction(redo_action)
        menu.addSeparator()
        cut_action = QAction("Cut", self)
        cut_action.setShortcut("Ctrl+X")
        cut_action.triggered.connect(self.cut)
        menu.addAction(cut_action)
        copy_action = QAction("Copy", self)
        copy_action.setShortcut("Ctrl+C")
        copy_action.triggered.connect(self.copy)
        menu.addAction(copy_action)
        paste_action = QAction("Paste", self)
        paste_action.setShortcut("Ctrl+V")
        paste_action.triggered.connect(self.paste)
        menu.addAction(paste_action)
        delete_action = QAction("Delete", self)
        delete_action.triggered.connect(self.delete_selection)
        menu.addAction(delete_action)
        menu.addSeparator()
        select_all_action = QAction("Select All", self)
        select_all_action.setShortcut("Ctrl+A")
        select_all_action.triggered.connect(self.selectAll)
        menu.addAction(select_all_action)
        menu.addSeparator()
        view_dict_action = QAction("View Dictionary", self)
        view_dict_action.triggered.connect(
            lambda checked=False: QDesktopServices.openUrl(
                QUrl.fromLocalFile(USER_DICT_PATH)
            )
        )
        menu.addAction(view_dict_action)
        word_cursor = self.cursorForPosition(event.pos())
        word_cursor.select(QTextCursor.WordUnderCursor)
        raw_word = word_cursor.selectedText()
        m = re.search(r"[A-Za-zА-Яа-яЁё']+", raw_word or "")
        if not m:
            menu.exec(self.mapToGlobal(event.pos()))
            return
        lw = m.group(0).lower()
        highlighter = getattr(self.window(), "spell_highlighter", None)
        spell = getattr(highlighter, "spell_checker", None)
        user_candidates = []
        if highlighter and getattr(highlighter, "user_words", None):
            try:
                user_candidates = difflib.get_close_matches(
                    lw, list(highlighter.user_words), n=7, cutoff=0.6
                )
            except Exception:
                user_candidates = []
        spell_candidates = []
        if spell:
            try:
                corr = spell.correction(lw)
                cands = spell.candidates(lw) if hasattr(spell, "candidates") else set()
                spell_candidates = [corr] + sorted(cands)
            except Exception:
                spell_candidates = []
        doc_candidates = []
        try:
            plain = self.window().text_edit.toPlainText()
            tokens = set(w.lower() for w in re.findall(r"[A-Za-zА-Яа-яЁё']+", plain))
            if lw in tokens:
                tokens.discard(lw)
            sample = list(tokens)[:5000]
            doc_candidates = difflib.get_close_matches(lw, sample, n=7, cutoff=0.65)
        except Exception:
            doc_candidates = []

        def _clean(seq):
            seen = set()
            out = []
            for s in seq:
                if not s:
                    continue
                sl = s.lower()
                if sl == lw or sl in seen:
                    continue
                out.append(s)
                seen.add(sl)
                if len(out) >= 7:
                    break
            return out

        user_candidates = _clean(user_candidates)
        spell_candidates = _clean(spell_candidates)
        doc_candidates = _clean(doc_candidates)
        menu.addSeparator()
        ignore_action = QAction("Ignore the word in the current note", self)
        ignore_action.triggered.connect(
            lambda checked=False, w=raw_word: self.ignore_in_this_note(w)
        )
        menu.addAction(ignore_action)
        add_dict_action = QAction("Add to Dictionary", self)
        add_dict_action.triggered.connect(
            lambda checked=False, w=raw_word: self.add_to_dictionary(w)
        )
        menu.addAction(add_dict_action)
        replace_menu = menu.addMenu("Replace")
        user_menu = replace_menu.addMenu("From your personal dictionary")
        if user_candidates:
            for s in user_candidates:
                act = user_menu.addAction(s)
                act.triggered.connect(
                    lambda _, s=s, c=QTextCursor(word_cursor): self.replace_word(c, s)
                )
        else:
            a = user_menu.addAction("— There are no options —")
            a.setEnabled(False)

        spell_menu = replace_menu.addMenu("Spelling options")
        if spell_candidates:
            for s in spell_candidates:
                act = spell_menu.addAction(s)
                act.triggered.connect(
                    lambda _, s=s, c=QTextCursor(word_cursor): self.replace_word(c, s)
                )
        else:
            a = spell_menu.addAction("— There are no options —")
            a.setEnabled(False)
        doc_menu = replace_menu.addMenu("From the current note")
        if doc_candidates:
            for s in doc_candidates:
                act = doc_menu.addAction(s)
                act.triggered.connect(
                    lambda _, s=s, c=QTextCursor(word_cursor): self.replace_word(c, s)
                )
        else:
            a = doc_menu.addAction("— There are no options —")
            a.setEnabled(False)
        menu.exec(self.mapToGlobal(event.pos()))

    def createMimeDataFromSelection(self):
        md = super().createMimeDataFromSelection()
        try:
            txt = md.text()
            if txt:
                md.setText(txt.replace("▾", ""))
        except Exception:
            pass
        try:
            html = md.html()
            if html:
                html = html.replace("▾", "").replace("&#9662;", "")
                md.setHtml(html)
        except Exception:
            pass
        return md

    def startDrag(self, supportedActions: Qt.DropActions) -> None:
        cursor = self.textCursor()
        if cursor.charFormat().isImageFormat():
            image_format = cursor.charFormat().toImageFormat()
            image_path = image_format.name()
            if os.path.exists(image_path):
                drag = QDrag(self)
                mimeData = self.createMimeDataFromSelection()
                drag.setMimeData(mimeData)
                drag.setPixmap(self.create_drag_image(self))
                drag.exec(supportedActions, Qt.CopyAction)
                return
        super().startDrag(supportedActions)


class Note:
    def __init__(
        self,
        title: str,
        content: str,
        tags: list[str],
        favorite: bool = False,
        history: list[str] | None = None,
        timestamp: str | None = None,
        reminder: str | None = None,
        uuid: str | None = None,
        reminder_repeat: str | None = None,
        pinned: bool = False,
        password_manager: str = "",
        rdp_1c8: str = "",
        custom_fields: list[dict] | None = None,
        ignored_words: list[str] | None = None,
    ) -> None:
        self.reminder_shown = False
        self.title = title
        self.content = content
        self.tags = tags
        self.favorite = favorite
        self.timestamp = timestamp or QDateTime.currentDateTime().toString(Qt.ISODate)
        self.reminder = reminder
        self.uuid = uuid or str(uuid.uuid4())
        self.history = history if history is not None else []
        self.history_index = len(self.history) - 1 if self.history else -1
        self.reminder_repeat = reminder_repeat
        self.pinned = pinned
        self.password_manager = password_manager
        self.rdp_1c8 = rdp_1c8
        self.custom_fields = custom_fields if custom_fields is not None else []
        self.password_manager_visible = False
        self.rdp_1c8_visible = False
        self.rdp_1c8_removed = False
        self.ignored_words = ignored_words or []

    def to_dict(self) -> dict:
        return {
            "pinned": self.pinned,
            "history": self.history,
            "history_index": self.history_index,
            "title": self.title,
            "content": self.content,
            "tags": self.tags,
            "favorite": self.favorite,
            "timestamp": self.timestamp,
            "reminder": self.reminder,
            "reminder_repeat": self.reminder_repeat,
            "uuid": self.uuid,
            "password_manager": self.password_manager,
            "rdp_1c8": self.rdp_1c8,
            "password_manager_visible": bool(self.password_manager_visible),
            "rdp_1c8_visible": bool(self.rdp_1c8_visible),
            "rdp_1c8_removed": bool(self.rdp_1c8_removed),
            "custom_fields": self.custom_fields,
            "ignored_words": self.ignored_words,
        }

    @staticmethod
    def from_dict(data: dict) -> "Note":
        note = Note(
            title=data.get("title", ""),
            content=data.get("content", ""),
            tags=list(data.get("tags", [])),
            favorite=data.get("favorite", False),
            history=list(data.get("history", [])),
            timestamp=data.get("timestamp"),
            reminder=data.get("reminder"),
            uuid=data.get("uuid"),
            reminder_repeat=data.get("reminder_repeat", None),
            ignored_words=data.get("ignored_words", []),
        )
        note.pinned = data.get("pinned", False)
        note.history_index = data.get("history_index", len(note.history) - 1)
        note.password_manager = data.get("password_manager", "")
        note.rdp_1c8 = data.get("rdp_1c8", "")
        note.password_manager_visible = bool(
            data.get("password_manager_visible", False)
        )
        note.rdp_1c8_visible = bool(data.get("rdp_1c8_visible", False))
        note.rdp_1c8_removed = bool(data.get("rdp_1c8_removed", False))
        note.custom_fields = list(data.get("custom_fields", []))
        return note


class NotesApp(QMainWindow):
    TRASH_DIR = os.path.join(NOTES_DIR, "Trash")
    window_hidden = Signal()

    def __init__(self):
        super().__init__()
        self._live_toasts: list[QLabel] = []
        self.exiting = False
        self.notes = []
        self.audio_thread = None
        self.load_plugins_state()
        self.init_ui()
        self.debounce_ms = self.settings.value("autosave_debounce_ms", 1500, type=int)
        self.debounce_timer = QTimer(self)
        self.debounce_timer.setSingleShot(True)
        self.debounce_timer.timeout.connect(self.autosave_current_note)
        self.text_edit.textChanged.connect(self._on_text_changed)
        self.current_note = None
        self.attachments_watcher = QFileSystemWatcher(self)
        self.attachments_watcher.directoryChanged.connect(self._refresh_attachments)
        self.attachments_watcher.fileChanged.connect(self._refresh_attachments)
        self.init_all_components()
        self.load_plugins()
        self.init_theme()
        self.load_settings()
        self.tray_icon = QSystemTrayIcon(QIcon(TRAY_ICON_PATH), self)
        self.tray_icon.activated.connect(self.on_tray_icon_activated)
        self.tray_icon.setToolTip("Мои Заметки")
        self.tray_icon.setVisible(True)
        menu = QMenu()
        restore_action = QAction("Открыть", self)
        restore_action.triggered.connect(self.show)
        exit_action = QAction("Выход", self)
        exit_action.triggered.connect(self.exit_app)
        menu.addAction(restore_action)
        menu.addAction(exit_action)
        self.tray_icon.setContextMenu(menu)
        self.reminder_timer = QTimer(self)
        self.reminder_timer.timeout.connect(self.check_reminders)
        self.reminder_timer.start(60000)

    def _on_text_changed(self) -> None:
        self.pending_save = True
        self._set_unsaved(True)
        if getattr(self, "autosave_enabled", True):
            self.debounce_timer.start(self.debounce_ms)

    def exit_app(self) -> None:
        self.tray_icon.hide()
        self.close()
        QApplication.instance().quit()

    def _set_unsaved(self, flag: bool) -> None:
        self.setWindowModified(bool(flag))
        if hasattr(self, "dock_editor"):
            self.dock_editor.setWindowTitle("Редактор *" if flag else "Редактор")

    def init_ui(self) -> None:
        self.setWindowTitle("Мои Заметки — [*]")
        self.setMinimumSize(1250, 800)
        self.setWindowIcon(QIcon(ICON_PATH))
        self.settings = QSettings(SETTINGS_PATH, QSettings.IniFormat)
        pm_label = self.settings.value("password_manager_label", "PasswordManager")
        rdp_label = self.settings.value("rdp_1c8_label", "1C8 RDP")
        self.new_note_button = QPushButton("Новая")
        self.save_note_button = QPushButton("Сохранить")
        self.delete_note_button = QPushButton("Удалить")
        self.undo_button = QPushButton("↩️")
        self.redo_button = QPushButton("↪️")
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Поиск по заметкам...")
        self.search_field.textChanged.connect(self.refresh_notes_list)
        button_layout = QVBoxLayout()
        button_layout.addWidget(self.new_note_button)
        button_layout.addWidget(self.save_note_button)
        button_layout.addWidget(self.delete_note_button)
        button_layout.addWidget(self.undo_button)
        button_layout.addWidget(self.redo_button)
        button_layout.addStretch()
        button_widget = QWidget()
        button_widget.setLayout(button_layout)
        self.notes_list = QListWidget()
        self.notes_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.notes_list.setDragEnabled(True)
        self.notes_list.setAcceptDrops(True)
        self.notes_list.setDropIndicatorShown(True)
        self.notes_list.setDefaultDropAction(Qt.MoveAction)
        self.notes_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.notes_list.model().rowsMoved.connect(self.handle_note_reorder)
        self.notes_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.notes_list.customContextMenuRequested.connect(self.show_note_context_menu)
        self.history_label = QLabel("Версии:")
        self.history_list = QListWidget()
        self.history_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.history_list.itemClicked.connect(self.restore_version_from_history)
        self.delete_history_button = QPushButton("Удалить выбранные версии")
        self.delete_history_button.clicked.connect(self.delete_selected_history_entries)
        self.history_list.setFocusPolicy(Qt.StrongFocus)
        self._hist_delete_sc = QShortcut(QKeySequence.Delete, self.history_list)
        self._hist_delete_sc.setContext(Qt.WidgetWithChildrenShortcut)
        self._hist_delete_sc.activated.connect(self.delete_selected_history_entries)
        history_layout = QVBoxLayout()
        history_layout.addWidget(self.history_label)
        history_layout.addWidget(self.history_list)
        history_layout.addWidget(self.delete_history_button)
        self.history_widget = QWidget()
        self.history_widget.setLayout(history_layout)
        self.history_widget.setFixedWidth(200)
        self.text_edit = CustomTextEdit(
            parent=self, paste_image_callback=self.insert_image_from_clipboard
        )
        self.spell_highlighter = SpellCheckHighlighter(self.text_edit.document())
        self._save_debouncer = QTimer(self)
        self._save_debouncer.setSingleShot(True)
        self._save_debouncer.setInterval(400)
        self._save_debouncer.timeout.connect(self.update_current_note_content)
        self.text_edit.textChanged.connect(self._save_debouncer.start)
        self.text_edit.cursorPositionChanged.connect(self.update_font_controls)
        self.text_edit.setReadOnly(True)
        self.text_edit.hide()
        self.text_edit.setFocusPolicy(Qt.StrongFocus)
        self.text_edit.setAlignment(Qt.AlignLeft)
        self.text_edit.setMinimumWidth(400)
        self.text_edit.setStyleSheet("font-size: 14px; font-family: 'Segoe UI Emoji';")
        self.text_edit.installEventFilter(self)
        self.text_edit.textChanged.connect(lambda: self._set_unsaved(True))
        self.tags_label = QLabel("Теги: нет")
        self.tags_label.setAlignment(Qt.AlignLeft)
        self.attachments_panel = QWidget()
        self.attachments_layout = QHBoxLayout(self.attachments_panel)
        self.attachments_layout.setAlignment(Qt.AlignLeft)
        self.attachments_scroll = QScrollArea()
        self.attachments_scroll.setWidgetResizable(True)
        self.attachments_scroll.setWidget(self.attachments_panel)
        self.attachments_scroll.setVisible(False)
        self.attachments_layout.setContentsMargins(0, 0, 0, 0)
        self.attachments_scroll.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Minimum
        )
        editor_combined = QWidget()
        editor_layout_combined = QVBoxLayout(editor_combined)
        editor_layout_combined.addWidget(self.tags_label)
        editor_layout_combined.addWidget(self.text_edit)
        editor_layout_combined.addWidget(self.attachments_scroll)
        editor_layout_combined.setStretch(1, 1)
        editor_layout_combined.setStretch(2, 0)
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.init_toolbar()
        self.dock_notes_list = QDockWidget("Заметки", self)
        self.dock_notes_list.setObjectName("dock_notes_list")
        self.dock_notes_list.setWidget(self.notes_list)
        self.dock_notes_list.setAllowedAreas(
            Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea
        )
        self.addDockWidget(Qt.LeftDockWidgetArea, self.dock_notes_list)
        self.dock_history = QDockWidget("История", self)
        self.dock_history.setObjectName("dock_history")
        self.dock_history.setWidget(self.history_widget)
        self.dock_history.setAllowedAreas(
            Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea
        )
        self.addDockWidget(Qt.LeftDockWidgetArea, self.dock_history)
        self.dock_buttons = QDockWidget("Управление", self)
        self.dock_buttons.setObjectName("dock_buttons")
        self.dock_buttons.setWidget(button_widget)
        self.dock_buttons.setAllowedAreas(
            Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea
        )
        self.addDockWidget(Qt.LeftDockWidgetArea, self.dock_buttons)
        self.dock_editor = QDockWidget("Редактор", self)
        self.dock_editor.setObjectName("dock_editor")
        self.dock_editor.setWidget(editor_combined)
        self.dock_editor.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock_editor)
        self.password_manager_field = QLineEdit()
        self.password_manager_field.setPlaceholderText(pm_label)
        self.rdp_1c8_field = QLineEdit()
        self.rdp_1c8_field.setPlaceholderText(rdp_label)
        self.password_manager_row = QWidget()
        _pm_row_layout = QHBoxLayout(self.password_manager_row)
        _pm_row_layout.setContentsMargins(0, 0, 0, 0)
        self.password_manager_label = QLineEdit()
        self.password_manager_label.setText(pm_label)
        self.password_manager_label.setMinimumWidth(140)
        self.password_manager_label.setFrame(False)
        self.password_manager_label.setStyleSheet("background: transparent;")
        self.password_manager_label.textChanged.connect(self.on_pm_label_changed)
        self.password_manager_label.editingFinished.connect(
            lambda: self.settings.setValue(
                "password_manager_label", self.password_manager_label.text()
            )
        )
        _pm_row_layout.addWidget(self.password_manager_label)
        _pm_row_layout.addWidget(self.password_manager_field, 1)
        self.password_manager_copy_btn = QPushButton("Копировать")
        self.password_manager_copy_btn.setFixedHeight(24)
        self.password_manager_copy_btn.clicked.connect(
            self.copy_password_manager_to_clipboard
        )
        self.password_manager_copy_btn.setEnabled(False)
        self.password_manager_field.textChanged.connect(
            lambda t: self.password_manager_copy_btn.setEnabled(bool(t))
        )
        _pm_row_layout.addWidget(self.password_manager_copy_btn)
        self.rdp_1c8_row = QWidget()
        _rdp_row_layout = QHBoxLayout(self.rdp_1c8_row)
        _rdp_row_layout.setContentsMargins(0, 0, 0, 0)
        self.rdp_1c8_label = QLineEdit()
        self.rdp_1c8_label.setText(rdp_label)
        self.rdp_1c8_label.setMinimumWidth(140)
        self.rdp_1c8_label.setFrame(False)
        self.rdp_1c8_label.setStyleSheet("background: transparent;")
        self.rdp_1c8_label.textChanged.connect(self.on_rdp_label_changed)
        self.rdp_1c8_label.editingFinished.connect(
            lambda: self.settings.setValue("rdp_1c8_label", self.rdp_1c8_label.text())
        )
        _rdp_row_layout.addWidget(self.rdp_1c8_label)
        _rdp_row_layout.addWidget(self.rdp_1c8_field, 1)
        self.rdp_1c8_copy_btn = QPushButton("Копировать")
        self.rdp_1c8_copy_btn.setFixedHeight(24)
        self.rdp_1c8_copy_btn.clicked.connect(self.copy_rdp_1c8_to_clipboard)
        self.rdp_1c8_copy_btn.setEnabled(False)
        self.rdp_1c8_field.textChanged.connect(
            lambda t: self.rdp_1c8_copy_btn.setEnabled(bool(t))
        )
        self.rdp_1c8_delete_btn = QPushButton("✖")
        self.rdp_1c8_delete_btn.setFixedSize(24, 24)
        self.rdp_1c8_delete_btn.clicked.connect(self.delete_rdp_1c8_field)
        _rdp_row_layout.addWidget(self.rdp_1c8_copy_btn)
        _rdp_row_layout.addWidget(self.rdp_1c8_delete_btn)
        self.custom_fields_container = QWidget()
        self.custom_fields_layout = QVBoxLayout(self.custom_fields_container)
        self.custom_fields_layout.setContentsMargins(0, 0, 0, 0)
        self.custom_fields_widgets: list[dict] = []
        self.add_field_btn = QPushButton("Добавить поле")
        self.add_field_btn.setFixedHeight(24)
        self.add_field_btn.setEnabled(False)
        self.add_field_btn.clicked.connect(self.add_custom_field)
        self.custom_fields_layout.addWidget(self.add_field_btn)
        editor_layout_combined.insertWidget(0, self.password_manager_row)
        editor_layout_combined.insertWidget(1, self.rdp_1c8_row)
        editor_layout_combined.insertWidget(2, self.custom_fields_container)
        self.dock_toolbar = QDockWidget("Панель инструментов", self)
        self.dock_toolbar.setObjectName("dock_toolbar")
        self.dock_toolbar.setWidget(self.toolbar_scroll)
        self.dock_toolbar.setAllowedAreas(
            Qt.TopDockWidgetArea | Qt.BottomDockWidgetArea
        )
        self.addDockWidget(Qt.TopDockWidgetArea, self.dock_toolbar)
        docks = [
            self.dock_notes_list,
            self.dock_history,
            self.dock_buttons,
            self.dock_editor,
            self.dock_toolbar,
        ]
        for dock in docks:
            dock.setContextMenuPolicy(Qt.CustomContextMenu)
            dock.customContextMenuRequested.connect(
                lambda pos, d=dock: self.show_dock_context_menu(pos, d)
            )
        self.visibility_toolbar = QToolBar("Видимость полей", self)
        self.visibility_toolbar.setObjectName("visibility_toolbar")
        self.visibility_toolbar.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, self.visibility_toolbar)
        self.action_toggle_pm = QAction(
            f"🙈 {self.password_manager_label.text()}", self
        )
        self.action_toggle_pm.setCheckable(True)
        self.action_toggle_pm.toggled.connect(self.on_toggle_pm_visible)
        self.action_toggle_rdp = QAction(f"🙈 {self.rdp_1c8_label.text()}", self)
        self.action_toggle_rdp.setCheckable(True)
        self.action_toggle_rdp.toggled.connect(self.on_toggle_rdp_visible)
        self.visibility_toolbar.addAction(self.action_toggle_pm)
        self.visibility_toolbar.addAction(self.action_toggle_rdp)
        self.all_tags = set()
        self.new_note_button.clicked.connect(self.new_note)
        self.save_note_button.clicked.connect(self.save_note)
        self.delete_note_button.clicked.connect(self.delete_note)
        self.notes_list.itemClicked.connect(self.load_note)
        self.text_edit.setReadOnly(True)
        self.add_menu_bar()
        self.current_note = None
        self._update_editor_visibility()

    def copy_password_manager_to_clipboard(self) -> None:
        text = self.password_manager_field.text().strip()
        if not text:
            QToolTip.showText(QCursor.pos(), "Поле пустое")
            return
        QApplication.clipboard().setText(text)
        self.show_toast(
            "Скопировано",
            boundary_widget=self.dock_editor.widget(),
            anchor_widget=self.password_manager_copy_btn,
        )

    def copy_rdp_1c8_to_clipboard(self) -> None:
        text = self.rdp_1c8_field.text().strip()
        if not text:
            QToolTip.showText(QCursor.pos(), "Поле пустое")
            return
        QApplication.clipboard().setText(text)
        self.show_toast(
            "Скопировано",
            boundary_widget=self.dock_editor.widget(),
            anchor_widget=self.rdp_1c8_copy_btn,
        )

    def add_word_to_note_ignore(self, word: str) -> None:  # NEW
        if not getattr(self, "current_note", None):
            return
        w = (word or "").strip().lower()
        if not w:
            return
        if w not in self.current_note.ignored_words:
            self.current_note.ignored_words.append(w)
            if hasattr(self, "spell_highlighter"):
                self.spell_highlighter.set_local_ignored(
                    self.current_note.ignored_words
                )
            self.save_note_quiet(force=True)

    def delete_rdp_1c8_field(self) -> None:
        self.rdp_1c8_field.clear()
        if getattr(self, "current_note", None):
            self.current_note.rdp_1c8 = ""
            self.current_note.rdp_1c8_visible = False
            self.current_note.rdp_1c8_removed = True
            self.save_note_to_file(self.current_note)
        self.rdp_1c8_row.setVisible(False)
        if hasattr(self, "action_toggle_rdp"):
            self.action_toggle_rdp.blockSignals(True)
            self.action_toggle_rdp.setChecked(False)
            self._update_eye_action(
                self.action_toggle_rdp, False, self.rdp_1c8_label.text()
            )
            self.action_toggle_rdp.setEnabled(False)
            self.action_toggle_rdp.setVisible(False)
            self.action_toggle_rdp.blockSignals(False)

    def add_custom_field(self, data: dict | None = None) -> None:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        label_edit = QLineEdit()
        label = data.get("label", "Новое поле") if data else "Новое поле"
        label_edit.setText(label)
        label_edit.setMinimumWidth(140)
        label_edit.setFrame(False)
        label_edit.setStyleSheet("background: transparent;")
        value_edit = QLineEdit()
        value = data.get("value", "") if data else ""
        value_edit.setText(value)
        value_edit.setPlaceholderText(label)
        copy_btn = QPushButton("Копировать")
        copy_btn.setFixedHeight(24)
        copy_btn.setEnabled(bool(value))
        copy_btn.clicked.connect(
            lambda _, e=value_edit, b=copy_btn: self.copy_custom_field_to_clipboard(
                e, b
            )
        )
        value_edit.textChanged.connect(lambda t, b=copy_btn: b.setEnabled(bool(t)))
        value_edit.textChanged.connect(
            lambda _: self.update_current_note_custom_fields()
        )
        value_edit.textChanged.connect(
            lambda _: self.debounce_timer.start(self.debounce_ms)
        )
        remove_btn = QPushButton("✖")
        remove_btn.setFixedSize(24, 24)
        layout.addWidget(label_edit)
        layout.addWidget(value_edit, 1)
        layout.addWidget(copy_btn)
        layout.addWidget(remove_btn)
        self.custom_fields_layout.insertWidget(
            self.custom_fields_layout.count() - 1, row
        )
        action = QAction(f"🙈 {label}", self)
        action.setCheckable(True)
        widget = {
            "row": row,
            "label_edit": label_edit,
            "value_edit": value_edit,
            "copy_btn": copy_btn,
            "remove_btn": remove_btn,
            "action": action,
        }
        action.toggled.connect(
            lambda checked, w=widget: self.on_toggle_custom_field(w, checked)
        )
        label_edit.textChanged.connect(
            lambda text, w=widget: self.on_custom_field_label_changed(w, text)
        )
        remove_btn.clicked.connect(lambda _, w=widget: self.remove_custom_field(w))
        self.visibility_toolbar.addAction(action)
        self.custom_fields_widgets.append(widget)
        action.blockSignals(True)
        visible = bool(data.get("visible")) if data else False
        action.setChecked(visible)
        action.blockSignals(False)
        raw = data.get("visible", False) if data else False
        visible = (raw is True) or (str(raw).lower() in {"1", "true", "yes"})
        action.setChecked(visible)
        row.setVisible(visible)
        self._update_eye_action(action, visible, label)
        self._update_eye_action(action, visible, label)
        self.update_current_note_custom_fields()

    def remove_custom_field(self, widget: dict) -> None:
        self.visibility_toolbar.removeAction(widget["action"])
        widget["row"].setParent(None)
        widget["action"].deleteLater()
        widget["row"].deleteLater()
        self.custom_fields_widgets.remove(widget)
        self.update_current_note_custom_fields()
        if self.current_note:
            self.save_note_to_file(self.current_note)

    def clear_custom_fields(self) -> None:
        for w in list(self.custom_fields_widgets):
            self.visibility_toolbar.removeAction(w["action"])
            w["action"].deleteLater()
            w["row"].deleteLater()
        self.custom_fields_widgets.clear()
        self.update_current_note_custom_fields()

    def on_custom_field_label_changed(self, widget: dict, text: str) -> None:
        widget["value_edit"].setPlaceholderText(text)
        self._update_eye_action(widget["action"], widget["row"].isVisible(), text)
        self.update_current_note_custom_fields()
        if hasattr(self, "debounce_timer"):
            self.debounce_timer.start(self.debounce_ms)

    def on_toggle_custom_field(self, widget: dict, checked: bool) -> None:
        if not self.current_note:
            widget["action"].blockSignals(True)
            widget["action"].setChecked(False)
            widget["action"].blockSignals(False)
            return
        widget["row"].setVisible(checked)
        self._update_eye_action(widget["action"], checked, widget["label_edit"].text())
        self.update_current_note_custom_fields()
        self.save_note_to_file(self.current_note)

    def copy_custom_field_to_clipboard(self, edit: QLineEdit, btn: QPushButton) -> None:
        text = edit.text().strip()
        if not text:
            QToolTip.showText(QCursor.pos(), "Поле пустое")
            return
        QApplication.clipboard().setText(text)
        self.show_toast(
            "Скопировано",
            boundary_widget=self.dock_editor.widget(),
            anchor_widget=btn,
        )

    def update_current_note_custom_fields(self) -> None:
        if not getattr(self, "current_note", None):
            return
        fields = []
        for w in self.custom_fields_widgets:
            fields.append(
                {
                    "label": w["label_edit"].text(),
                    "value": w["value_edit"].text(),
                    "visible": w["row"].isVisible(),
                }
            )
        self.current_note.custom_fields = fields

    def on_pm_label_changed(self, text: str) -> None:
        self.password_manager_field.setPlaceholderText(text)
        if hasattr(self, "action_toggle_pm"):
            self._update_eye_action(
                self.action_toggle_pm,
                self.password_manager_row.isVisible(),
                text,
            )

    def on_rdp_label_changed(self, text: str) -> None:
        self.rdp_1c8_field.setPlaceholderText(text)
        if hasattr(self, "action_toggle_rdp"):
            self._update_eye_action(
                self.action_toggle_rdp,
                self.rdp_1c8_row.isVisible(),
                text,
            )

    def add_toolbar(self) -> None:
        self.init_toolbar()
        layout_splitter = QSplitter(Qt.Vertical)
        layout_splitter.addWidget(self.toolbar_scroll)
        layout_splitter.addWidget(self.main_splitter)
        layout_splitter.setSizes([140, 1000])
        self.layout_splitter = layout_splitter
        self.main_layout = QHBoxLayout()
        self.main_layout.addWidget(self.layout_splitter)
        self.central_widget.setLayout(self.main_layout)

    def _update_eye_action(self, action: QAction, visible: bool, label: str) -> None:
        action.setText(("👁 " if visible else "🙈 ") + label)
        action.setToolTip(("Скрыть " if visible else "Показать ") + label)

    def on_toggle_pm_visible(self, checked: bool) -> None:
        if not self.current_note:
            return
        self.current_note.password_manager_visible = bool(checked)
        self.password_manager_row.setVisible(checked)
        self._update_eye_action(
            self.action_toggle_pm, checked, self.password_manager_label.text()
        )
        self.save_note_to_file(self.current_note)

    def on_toggle_rdp_visible(self, checked: bool) -> None:
        if not self.current_note:
            return
        if getattr(self.current_note, "rdp_1c8_removed", False):
            if hasattr(self, "action_toggle_rdp"):
                self.action_toggle_rdp.blockSignals(True)
                self.action_toggle_rdp.setChecked(False)
                self.action_toggle_rdp.blockSignals(False)
            return
        self.current_note.rdp_1c8_visible = bool(checked)
        self.rdp_1c8_row.setVisible(checked)
        self._update_eye_action(
            self.action_toggle_rdp, checked, self.rdp_1c8_label.text()
        )
        self.save_note_to_file(self.current_note)

    def delete_selected_history_entries(self) -> None:
        if not self.current_note:
            return
        selected_indexes = [item.row() for item in self.history_list.selectedIndexes()]
        if not selected_indexes:
            QMessageBox.information(
                self, "Удаление", "Нет выбранных версий для удаления."
            )
            return
        selected_indexes.sort(reverse=True)
        for index in selected_indexes:
            if 0 <= index < len(self.current_note.history):
                self.current_note.history.pop(index)
        if self.current_note.history_index >= len(self.current_note.history):
            self.current_note.history_index = len(self.current_note.history) - 1
        elif self.current_note.history_index in selected_indexes:
            self.current_note.history_index = max(
                0, self.current_note.history_index - 1
            )
        if not self.current_note.history:
            self.text_edit.blockSignals(True)
            self.text_edit.clear()
            self.text_edit.blockSignals(False)
            self.current_note.history_index = -1
        else:
            self.text_edit.blockSignals(True)
            self.text_edit.setHtml(
                self.current_note.history[self.current_note.history_index]
            )
            self.text_edit.blockSignals(False)
        self.update_history_list()
        self.update_history_list_selection()
        self.save_note_to_file(self.current_note)
        QMessageBox.information(self, "Удалено", "Выбранные версии удалены из истории.")

    def insert_update_block(self) -> None:
        if not self.current_note:
            return

        now = QDateTime.currentDateTime()
        date_str = now.toString("dd.MM.yyyy")
        cursor = self.text_edit.textCursor()

        html = (
            f"<b>UPD [{date_str}]</b><br>"
            f"<b>Base:</b> <br>"
            f"<b>User:</b> <br>"
            f"<b>Result:</b> <br>"
            f"<b>Details:</b> <br><br>"
        )
        cursor.insertHtml(html)
        self.text_edit.setTextCursor(cursor)
        self.text_edit.setFocus()

    def restore_version_from_history(self, item: QListWidgetItem) -> None:
        if not self.current_note:
            return
        content = item.data(Qt.UserRole)
        if content:
            self.text_edit.blockSignals(True)
            self.text_edit.setHtml(content)
            self.text_edit.blockSignals(False)
            self.current_note.history_index = self.history_list.row(item)
            self.update_history_list_selection()

    def move_note_to_trash(self, note: Note) -> None:
        self.save_note_to_specific_folder(note, self.TRASH_DIR)
        note_folder_name = NotesApp.safe_folder_name(
            note.title, note.uuid, note.timestamp
        )
        note_dir = os.path.join(NOTES_DIR, note_folder_name)
        trash_dir = os.path.join(self.TRASH_DIR, note_folder_name)
        if not os.path.exists(self.TRASH_DIR):
            os.makedirs(self.TRASH_DIR)
        if os.path.exists(trash_dir):
            shutil.rmtree(trash_dir)
        if os.path.exists(note_dir):
            shutil.move(note_dir, trash_dir)
        self.notes = [n for n in self.notes if n.uuid != note.uuid]

    def save_note_to_specific_folder(self, note: Note, folder: str) -> None:
        note_dir = os.path.join(
            folder, NotesApp.safe_folder_name(note.title, note.uuid, note.timestamp)
        )
        os.makedirs(note_dir, exist_ok=True)
        file_path = os.path.join(note_dir, "note.json")
        if self.current_note and note.uuid == self.current_note.uuid:
            note.content = self.text_edit.toHtml()
        note_dict = note.to_dict()
        if not note.reminder:
            note_dict.pop("reminder", None)
        with open(file_path, "w", encoding="utf-8") as f:
            doc = QTextDocument()
            doc.setHtml(note.content)
            plain_text = doc.toPlainText()
            note_dict["content_txt"] = plain_text
            json.dump(note_dict, f, ensure_ascii=False, indent=4)

    def bring_widget_to_front(self, w: QWidget) -> None:
        old = w.windowFlags()
        w.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        w.show()
        w.raise_()
        w.activateWindow()

        def _restore():
            w.setWindowFlags(old)
            w.show()

        QTimer.singleShot(800, _restore)

    def record_state_for_undo(self) -> None:
        note = self.current_note
        if not note:
            self.attachments_scroll.setVisible(False)
            return
        if not hasattr(note, "history") or note.history is None:
            note.history = []
        if note.history_index < len(note.history) - 1:
            note.history = note.history[: note.history_index + 1]
        current_html = self.text_edit.toHtml()
        current_plain = self.text_edit.toPlainText()
        if note.history:
            doc = QTextDocument()
            doc.setHtml(note.history[-1])
            if doc.toPlainText() == current_plain:
                return
        if len(note.history) >= MAX_HISTORY:
            note.history = [current_html]
            note.history_index = 0
        else:
            note.history.append(current_html)
            note.history_index = len(note.history) - 1
        self.update_history_list()
        self.update_history_list_selection()

    def on_tray_icon_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.show()
            self.raise_()
            self.activateWindow()

    def update_history_list(self) -> None:
        if not self.current_note:
            self.history_list.clear()
            return
        self.history_list.clear()
        for i, content in enumerate(self.current_note.history):
            item = QListWidgetItem(f"Версия {i+1}")
            item.setData(Qt.UserRole, content)
            self.history_list.addItem(item)
        self.history_list.scrollToBottom()

    def undo(self) -> None:
        if not self.current_note:
            return
        if self.current_note.history_index > 0:
            self.current_note.history_index -= 1
            self.text_edit.blockSignals(True)
            self.text_edit.setHtml(
                self.current_note.history[self.current_note.history_index]
            )
            self.text_edit.blockSignals(False)
            self.update_history_list_selection()

    def redo(self) -> None:
        if not self.current_note:
            return
        if self.current_note.history_index < len(self.current_note.history) - 1:
            self.current_note.history_index += 1
            self.text_edit.blockSignals(True)
            self.text_edit.setHtml(
                self.current_note.history[self.current_note.history_index]
            )
            self.text_edit.blockSignals(False)
            self.update_history_list_selection()

    def update_history_list_selection(self) -> None:
        if not self.current_note:
            return
        self.history_list.blockSignals(True)
        for i in range(self.history_list.count()):
            item = self.history_list.item(i)
            if i == self.current_note.history_index:
                item.setSelected(True)
            else:
                item.setSelected(False)
        self.history_list.blockSignals(False)

    def load_notes_from_disk(self) -> None:
        self.ensure_notes_directory()
        loaded_notes = []
        for folder in os.listdir(NOTES_DIR):
            folder_path = os.path.join(NOTES_DIR, folder)
            if os.path.isdir(folder_path):
                file_path = os.path.join(folder_path, "note.json")
                if os.path.exists(file_path):
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    note = Note.from_dict(data)
                    if "content_txt" in data:
                        note.content_txt = data["content_txt"]
                    else:
                        doc = QTextDocument()
                        doc.setHtml(note.content)
                        note.content_txt = doc.toPlainText()
                    loaded_notes.append(note)
        unique = {}
        for note in loaded_notes:
            unique[note.uuid] = note
        self.notes = list(unique.values())
        self.deduplicate_notes()

    def save_note_to_file(self, note: Note) -> None:
        note_dir = os.path.join(
            NOTES_DIR, NotesApp.safe_folder_name(note.title, note.uuid, note.timestamp)
        )
        os.makedirs(note_dir, exist_ok=True)
        file_path = os.path.join(note_dir, "note.json")
        if self.current_note and note.uuid == self.current_note.uuid:
            note.content = self.text_edit.toHtml()
        note_dict = note.to_dict()
        if not note.reminder:
            note_dict.pop("reminder", None)
        with open(file_path, "w", encoding="utf-8") as f:
            if self.current_note and note.uuid == self.current_note.uuid:
                doc = QTextDocument()
                doc.setHtml(self.text_edit.toHtml())
                plain_text = doc.toPlainText()
                note_dict["content_txt"] = plain_text
            else:
                doc = QTextDocument()
                doc.setHtml(note.content)
                plain_text = doc.toPlainText()
                note_dict["content_txt"] = plain_text
            json.dump(note_dict, f, ensure_ascii=False, indent=4)

    def save_all_notes_to_disk(self) -> None:
        self.ensure_notes_directory()
        unique_notes = {}
        for note in self.notes:
            unique_notes[note.uuid] = note
        self.notes = list(unique_notes.values())
        for note in self.notes:
            self.save_note_to_file(note)
        self.deduplicate_notes()

    def deduplicate_notes(self) -> None:
        unique = {}
        for note in self.notes:
            unique[note.uuid] = note
        self.notes = list(unique.values())

    def load_settings(self) -> None:
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        state = self.settings.value("windowState")
        if state:
            self.restoreState(state)
        last_text = self.settings.value("lastNoteText")
        if last_text:
            self.text_edit.blockSignals(True)
            self.text_edit.setHtml(last_text)
            self.text_edit.blockSignals(False)

    def save_settings(self) -> None:
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
        self.settings.setValue("lastNoteText", self.text_edit.toHtml())

    def confirm_delete_note(self, note: Note) -> None:
        reply = QMessageBox.question(
            self,
            "Удалить заметку",
            f"Вы уверены, что хотите удалить заметку '{note.title}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.move_note_to_trash(note)
            note_dir = os.path.join(
                NOTES_DIR, NotesApp.safe_folder_name(note.title, note.uuid)
            )
            if self.current_note and self.current_note.uuid == note.uuid:
                self.current_note = None
                self.text_edit.clear()
            self.refresh_notes_list()
            self.save_all_notes_to_disk()

    def rename_note(self, note: Note) -> None:
        new_title, ok = QInputDialog.getText(
            self, "Переименовать", "Новое имя заметки:", text=note.title
        )
        if ok and new_title and new_title != note.title:
            old_dir = os.path.join(
                NOTES_DIR,
                NotesApp.safe_folder_name(note.title, note.uuid, note.timestamp),
            )
            note.title = new_title
            new_dir = os.path.join(
                NOTES_DIR,
                NotesApp.safe_folder_name(note.title, note.uuid, note.timestamp),
            )
            if os.path.exists(old_dir):
                os.rename(old_dir, new_dir)
            self.save_note_to_file(note)
            self.refresh_notes_list()

    @staticmethod
    def safe_filename(title: str, ext: str) -> str:
        base = re.sub(r"[^a-zA-Zа-яА-Я0-9 _\-]", "", title)
        base = base.strip().replace(" ", "_")
        if len(base) > 100:
            base = base[:100]
        return f"{base or 'note'}.{ext}"

    def export_current_note_pdf(self) -> None:
        if not self.current_note:
            QMessageBox.warning(self, "Ошибка", "Нет выбранной заметки для экспорта.")
            return
        default_name = self.safe_filename(self.current_note.title, "pdf")
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить как PDF", default_name, filter="PDF Files (*.pdf)"
        )
        if file_path:
            doc = QTextDocument()
            html = self.text_edit.toHtml()
            html = re.sub(r'font-size\s*:[^;"]*;?', "", html)
            doc.setHtml(html)
            font = QFont("Times New Roman", 14)
            doc.setDefaultFont(font)
            printer = QPrinter(QPrinter.HighResolution)
            printer.setOutputFormat(QPrinter.PdfFormat)
            printer.setOutputFileName(file_path)
            doc.print_(printer)
            QMessageBox.information(
                self,
                "Экспорт завершён",
                f"Заметка успешно сохранена как PDF:\n{file_path}",
            )

    def export_current_note_txt(self) -> None:
        if not self.current_note:
            QMessageBox.warning(self, "Ошибка", "Нет выбранной заметки для экспорта.")
            return
        default_name = self.safe_filename(self.current_note.title, "txt")
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить как TXT", default_name, filter="Text Files (*.txt)"
        )
        if file_path:
            text = self.text_edit.toPlainText()
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(text)
            QMessageBox.information(
                self,
                "Экспорт завершён",
                f"Заметка успешно сохранена как TXT:\n{file_path}",
            )

    def export_current_note_docx(self) -> None:
        if not self.current_note:
            QMessageBox.warning(self, "Ошибка", "Нет выбранной заметки для экспорта.")
            return
        default_name = self.safe_filename(self.current_note.title, "docx")
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить как DOCX", default_name, filter="Word Documents (*.docx)"
        )
        if file_path:
            text = self.text_edit.toPlainText()
            doc = Document()
            for line in text.splitlines():
                doc.add_paragraph(line)
            doc.save(file_path)
            QMessageBox.information(
                self,
                "Экспорт завершён",
                f"Заметка успешно сохранена как DOCX:\n{file_path}",
            )

    def copy_note(self, note: Note) -> None:
        new_title = note.title + "(копия)"
        new_uuid = str(uuid.uuid4())
        new_note = Note(
            title=new_title,
            content=note.content,
            tags=note.tags.copy(),
            favorite=False,
            history=note.history.copy(),
            reminder=None,
            uuid=new_uuid,
            password_manager=note.password_manager,
            rdp_1c8=note.rdp_1c8,
            custom_fields=[dict(f) for f in getattr(note, "custom_fields", [])],
        )
        new_note.password_manager_visible = note.password_manager_visible
        new_note.rdp_1c8_visible = note.rdp_1c8_visible
        note_dir = os.path.join(
            NOTES_DIR, NotesApp.safe_folder_name(note.title, note.uuid, note.timestamp)
        )
        new_note_dir = os.path.join(
            NOTES_DIR,
            NotesApp.safe_folder_name(new_title, new_uuid, new_note.timestamp),
        )
        if os.path.exists(note_dir):
            shutil.copytree(note_dir, new_note_dir)
            self.save_note_to_file(new_note)
        self.load_notes_from_disk()
        self.refresh_notes_list()
        self.deduplicate_notes()

    def ensure_notes_directory(self) -> None:
        if not os.path.exists(NOTES_DIR):
            os.makedirs(NOTES_DIR)

    def create_new_note(self) -> None:
        self.new_note()

    def save_current_note(self) -> None:
        self.save_note()

    def delete_current_note(self) -> None:
        self.delete_note()

    def new_note(self) -> None:
        title, ok = QInputDialog.getText(self, "Новая заметка", "Введите название:")
        if ok and title:
            for note in self.notes:
                if note.title == title:
                    QMessageBox.warning(
                        self,
                        "Дубликат",
                        f"Заметка с названием '{title}' уже существует.",
                    )
                    return
            note_uuid = str(uuid.uuid4())
            note = Note(
                title=title,
                content="",
                tags=[],
                favorite=False,
                timestamp=QDateTime.currentDateTime().toString(Qt.ISODate),
                reminder=None,
                uuid=note_uuid,
            )
            note.history = [""]
            note.history_index = 0
            note_dir = os.path.join(
                NOTES_DIR, NotesApp.safe_folder_name(title, note_uuid)
            )
            os.makedirs(note_dir, exist_ok=True)
            self.notes.append(note)
            self.current_note = note
            if hasattr(self, "spell_highlighter"):
                self.spell_highlighter.set_local_ignored(
                    self.current_note.ignored_words
                )
            self.text_edit.blockSignals(True)
            self.text_edit.clear()
            self.text_edit.setFont(QFont("Times New Roman", 14))
            self.text_edit.setCurrentFont(QFont("Times New Roman"))
            self.text_edit.setFontPointSize(14)
            self.font_combo.setCurrentFont(QFont("Times New Roman"))
            self.font_size_spin.setValue(14)
            self.text_edit.blockSignals(False)
            self.tags_label.setText("Теги: нет")
            self.password_manager_field.clear()
            self.rdp_1c8_field.clear()
            self.refresh_notes_list()
            self.show_note_with_attachments(note)
            self.text_edit.setFocus()
            self.text_edit.setReadOnly(False)
            note.password_manager_visible = False
            note.rdp_1c8_visible = False
            note.rdp_1c8_removed = False
            self.password_manager_field.clear()
            self.rdp_1c8_field.clear()
            self.password_manager_row.setVisible(False)
            self.rdp_1c8_row.setVisible(False)
            self.clear_custom_fields()
            self.add_field_btn.setEnabled(True)
            if hasattr(self, "action_toggle_pm"):
                self.action_toggle_pm.blockSignals(True)
                self.action_toggle_pm.setChecked(False)
                self._update_eye_action(
                    self.action_toggle_pm, False, self.password_manager_label.text()
                )
                self.action_toggle_pm.blockSignals(False)
            if hasattr(self, "action_toggle_rdp"):
                self.action_toggle_rdp.blockSignals(True)
                self.action_toggle_rdp.setChecked(False)
                self._update_eye_action(
                    self.action_toggle_rdp, False, self.rdp_1c8_label.text()
                )
                self.action_toggle_rdp.blockSignals(False)

    def save_note(self) -> None:
        if self.current_note:
            self.current_note.content = self.text_edit.toHtml()
            self.current_note.password_manager = self.password_manager_field.text()
            self.current_note.rdp_1c8 = self.rdp_1c8_field.text()
            self.update_current_note_custom_fields()
            self.save_note_to_file(self.current_note)
            self.refresh_notes_list()
            self.record_state_for_undo()
            QMessageBox.information(self, "Сохранено", "Заметка успешно сохранена.")
            self._set_unsaved(False)

    def save_note_quiet(self, *, force: bool = False) -> None:
        if not force and not getattr(self, "autosave_enabled", True):
            return
        if self.current_note:
            self.current_note.content = self.text_edit.toHtml()
            self.current_note.password_manager = self.password_manager_field.text()
            self.current_note.rdp_1c8 = self.rdp_1c8_field.text()
            self.update_current_note_custom_fields()
            self.save_note_to_file(self.current_note)
            self.record_state_for_undo()
            self._set_unsaved(False)

    def open_note_folder(self, note: Note) -> None:
        if not note:
            self.attachments_scroll.setVisible(False)
            return
        folder_name = NotesApp.safe_folder_name(note.title, note.uuid, note.timestamp)
        candidates = [
            os.path.join(NOTES_DIR, folder_name),
            os.path.join(self.TRASH_DIR, folder_name),
        ]
        for path in candidates:
            if os.path.isdir(path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(path)))
                return
        self.save_note_to_file(note)
        path = os.path.join(NOTES_DIR, folder_name)
        os.makedirs(path, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(path)))

    def delete_note(self) -> None:
        selected_items = self.notes_list.selectedItems()
        if selected_items:
            reply = QMessageBox.question(
                self,
                "Удаление",
                f"Переместить выбранные заметки в корзину? ({len(selected_items)} шт.)",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            for item in selected_items:
                note = item.data(Qt.UserRole)
                if note:
                    self.move_note_to_trash(note)
            self.refresh_notes_list()
            self.load_note(None)
            self.current_note = None
            QMessageBox.information(
                self, "Готово", "Выбранные заметки перемещены в корзину."
            )
            return
        if self.current_note:
            title = self.current_note.title
            reply = QMessageBox.question(
                self,
                "Удаление",
                f"Переместить заметку '{title}' в корзину?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self.move_note_to_trash(self.current_note)
                self.refresh_notes_list()
                self.load_note(None)
                self.current_note = None
                QMessageBox.information(
                    self, "Готово", f"Заметка '{title}' перемещена в корзину."
                )
            return
        QMessageBox.information(
            self, "Удаление", "Нет открытой или выделенной заметки для удаления."
        )

    def load_templates(self) -> list[dict]:
        templates_path = os.path.join(DATA_DIR, "templates.json")
        base_templates = [
            {
                "name": "Список дел",
                "category": "Работа",
                "description": "Чекбокс-лист для задач",
                "content_html": "<b>Список дел:</b><br>☐ Первая задача<br>☐ Вторая задача<br>☐ Третья задача<br>",
            },
            {
                "name": "Встреча",
                "category": "Встречи",
                "description": "Заготовка для заметки о встрече",
                "content_html": "<b>Встреча</b><br>Дата: <br>Участники: <br>Цели: <br>Результаты: <br>",
            },
            {
                "name": "Дневник",
                "category": "Личное",
                "description": "Дневниковая запись",
                "content_html": "<b>Дневник</b><br>Дата: <br>Сегодня:<br><br>Настроение:<br>События:<br>",
            },
        ]

        if not os.path.exists(templates_path):
            with open(templates_path, "w", encoding="utf-8") as f:
                json.dump(base_templates, f, ensure_ascii=False, indent=4)
        try:
            with open(templates_path, "r", encoding="utf-8") as f:
                templates = json.load(f)
        except Exception:
            templates = base_templates
        upd_tpl = {
            "name": "UPD блок",
            "category": "Работа",
            "description": "Блок обновления с датой, базой, пользователем, результатом и деталями",
            "content_html": "<b>UPD [{date}]</b><br><b>Base:</b> <br><b>User:</b> <br><b>Result:</b> <br><b>Details:</b> <br><br>",
        }
        if not any(t.get("name") == "UPD блок" for t in templates):
            templates.append(upd_tpl)
            with open(templates_path, "w", encoding="utf-8") as f:
                json.dump(templates, f, ensure_ascii=False, indent=4)
        return templates

    def save_templates(self, templates: list[dict]) -> None:
        templates_path = os.path.join(DATA_DIR, "templates.json")
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(templates_path, "w", encoding="utf-8") as f:
            json.dump(templates, f, ensure_ascii=False, indent=4)

    def save_current_as_template(self) -> None:
        if not self.current_note:
            QMessageBox.warning(self, "Нет заметки", "Сначала выбери заметку.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Сохранить как шаблон")
        layout = QFormLayout(dialog)
        name_edit = QLineEdit()
        category_edit = QLineEdit()
        description_edit = QLineEdit()
        only_selection = QCheckBox("Только выделенный фрагмент")
        layout.addRow("Название:", name_edit)
        layout.addRow("Категория:", category_edit)
        layout.addRow("Описание:", description_edit)
        layout.addRow("", only_selection)
        preview = QTextEdit()
        preview.setMinimumHeight(180)
        layout.addRow("Содержимое:", preview)

        def fill_preview():
            cur = self.text_edit.textCursor()
            if only_selection.isChecked() and cur.hasSelection():
                frag = cur.selection()
                preview.setHtml(frag.toHtml())
            else:
                preview.setHtml(self.text_edit.toHtml())

        only_selection.toggled.connect(fill_preview)
        fill_preview()
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        layout.addRow(buttons)

        def on_accept():
            name = name_edit.text().strip()
            if not name:
                QMessageBox.warning(dialog, "Ошибка", "Укажи название шаблона.")
                return
            tpl = {
                "name": name,
                "category": (category_edit.text().strip() or "Без категории"),
                "description": description_edit.text().strip(),
                "content_html": preview.toHtml(),
            }
            templates = self.load_templates()
            exist_idx = next(
                (i for i, t in enumerate(templates) if t.get("name") == name), -1
            )
            if exist_idx >= 0:
                r = QMessageBox.question(
                    dialog,
                    "Перезаписать?",
                    f"Шаблон «{name}» уже существует. Перезаписать?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if r == QMessageBox.No:
                    return
                templates[exist_idx] = tpl
            else:
                templates.append(tpl)
            self.save_templates(templates)
            dialog.accept()
            QMessageBox.information(self, "Готово", f"Шаблон «{name}» сохранён.")

        buttons.accepted.connect(on_accept)
        buttons.rejected.connect(dialog.reject)
        fg = dialog.frameGeometry()
        fg.moveCenter(self.frameGeometry().center())
        dialog.move(fg.topLeft())
        dialog.exec()

    def insert_template(self) -> None:
        if not self.current_note:
            QMessageBox.warning(self, "Нет заметки", "Создайте или выберите заметку.")
            return
        templates = self.load_templates()
        dialog = QDialog(self)
        dialog.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        dialog.setWindowTitle("Вставить шаблон")
        layout = QVBoxLayout(dialog)
        combo = QComboBox(dialog)
        categories = sorted({tpl.get("category", "Без категории") for tpl in templates})
        category_combo = QComboBox(dialog)
        category_combo.addItem("Все категории")
        category_combo.addItems(categories)
        filtered_templates = templates.copy()

        def filter_templates():
            cat = category_combo.currentText()
            combo.clear()
            filtered = [
                tpl
                for tpl in templates
                if cat == "Все категории" or tpl.get("category", "Без категории") == cat
            ]
            filtered_templates.clear()
            filtered_templates.extend(filtered)
            combo.addItems(
                [f"{tpl['name']} ({tpl.get('description','')})" for tpl in filtered]
            )

        category_combo.currentIndexChanged.connect(filter_templates)
        layout.addWidget(category_combo)
        layout.addWidget(combo)
        preview = QTextEdit(dialog)
        preview.setReadOnly(True)
        preview.setMinimumHeight(100)
        layout.addWidget(preview)

        def update_preview(idx):
            if 0 <= idx < len(filtered_templates):
                content = filtered_templates[idx]["content_html"]
                if "{date}" in content:
                    now = QDateTime.currentDateTime()
                    date_str = now.toString("dd.MM.yyyy")
                    content = content.replace("{date}", date_str)
                preview.setHtml(content)
            else:
                preview.setHtml("")

        combo.currentIndexChanged.connect(update_preview)
        filter_templates()
        combo.setCurrentIndex(0)
        update_preview(0)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(buttons)
        dialog.setLayout(layout)

        def keyPressEvent(event):
            if event.key() == Qt.Key_Escape:
                dialog.reject()
            else:
                QDialog.keyPressEvent(dialog, event)

        dialog.keyPressEvent = keyPressEvent

        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec() == QDialog.Accepted:
            idx = combo.currentIndex()
            if 0 <= idx < len(filtered_templates):
                tpl = filtered_templates[idx]
                content_html = tpl["content_html"]
                if "{date}" in content_html:
                    now = QDateTime.currentDateTime()
                    date_str = now.toString("dd.MM.yyyy")
                    content_html = content_html.replace("{date}", date_str)

                cursor = self.text_edit.textCursor()
                start = cursor.position()
                self.text_edit.insertHtml(content_html)
                end = self.text_edit.textCursor().position()
                if end > start:
                    cursor.setPosition(start)
                    cursor.setPosition(end, QTextCursor.KeepAnchor)
                    fmt = QTextCharFormat()
                    font = QFont("Times New Roman", 14)
                    fmt.setFont(font)
                    cursor.mergeCharFormat(fmt)
                    cursor.clearSelection()
                    self.text_edit.setTextCursor(cursor)
                self.record_state_for_undo()

    def manage_templates_dialog(self) -> None:
        templates = self.load_templates()
        dlg = QDialog(self)
        dlg.setWindowTitle("Шаблоны")
        v = QVBoxLayout(dlg)
        lst = QListWidget()

        def refresh():
            lst.clear()
            for t in templates:
                lst.addItem(f"{t.get('name','')} — {t.get('category','Без категории')}")

        refresh()
        v.addWidget(lst)
        form = QFormLayout()
        name_edit = QLineEdit()
        category_edit = QLineEdit()
        desc_edit = QLineEdit()
        form.addRow("Название:", name_edit)
        form.addRow("Категория:", category_edit)
        form.addRow("Описание:", desc_edit)
        v.addLayout(form)
        content = QTextEdit()
        content.setMinimumHeight(180)
        v.addWidget(content)
        btns_line = QHBoxLayout()
        btn_new = QPushButton("Новый")
        btn_save = QPushButton("Сохранить")
        btn_del = QPushButton("Удалить")
        btn_close = QPushButton("Закрыть")
        for b in (btn_new, btn_save, btn_del, btn_close):
            btns_line.addWidget(b)
        v.addLayout(btns_line)

        def load_current(i):
            if i < 0 or i >= len(templates):
                name_edit.clear()
                category_edit.clear()
                desc_edit.clear()
                content.clear()
                return
            t = templates[i]
            name_edit.setText(t.get("name", ""))
            category_edit.setText(t.get("category", ""))
            desc_edit.setText(t.get("description", ""))
            content.setHtml(t.get("content_html", ""))

        lst.currentRowChanged.connect(load_current)
        if templates:
            lst.setCurrentRow(0)

        def on_new():
            templates.append(
                {
                    "name": "Новый шаблон",
                    "category": "Без категории",
                    "description": "",
                    "content_html": "",
                }
            )
            refresh()
            lst.setCurrentRow(len(templates) - 1)

        def on_save():
            i = lst.currentRow()
            if i < 0:
                return
            templates[i] = {
                "name": name_edit.text().strip() or "Без имени",
                "category": category_edit.text().strip() or "Без категории",
                "description": desc_edit.text().strip(),
                "content_html": content.toHtml(),
            }
            self.save_templates(templates)
            refresh()
            lst.setCurrentRow(i)
            QMessageBox.information(dlg, "Готово", "Сохранено.")

        def on_del():
            i = lst.currentRow()
            if i < 0:
                return
            r = QMessageBox.question(
                dlg,
                "Удалить",
                "Удалить выбранный шаблон?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if r == QMessageBox.Yes:
                templates.pop(i)
                self.save_templates(templates)
                refresh()
                lst.setCurrentRow(min(i, len(templates) - 1))

        btn_new.clicked.connect(on_new)
        btn_save.clicked.connect(on_save)
        btn_del.clicked.connect(on_del)
        btn_close.clicked.connect(dlg.accept)
        fg = dlg.frameGeometry()
        fg.moveCenter(self.frameGeometry().center())
        dlg.move(fg.topLeft())
        dlg.exec()

    def show_trash(self) -> None:
        self.notes_list.clear()
        if not os.path.exists(self.TRASH_DIR):
            return
        for folder in os.listdir(self.TRASH_DIR):
            folder_path = os.path.join(self.TRASH_DIR, folder)
            if os.path.isdir(folder_path):
                file_path = os.path.join(folder_path, "note.json")
                if os.path.exists(file_path):
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        note = Note.from_dict(data)
                        doc = QTextDocument()
                        doc.setHtml(note.content)
                        note.content_txt = doc.toPlainText()
                        title = note.title
                        timestamp = QDateTime.fromString(note.timestamp, Qt.ISODate)
                        date_str = timestamp.toString("dd.MM.yyyy")
                        item_text = f"{title} — {date_str} 🗑"
                        item = QListWidgetItem(item_text)
                        item.setFont(QFont("Segoe UI Emoji", 10))
                        item.setData(Qt.UserRole, note)
                        item.setForeground(QColor("gray"))
                        self.notes_list.addItem(item)

    def restore_note_from_trash(self) -> None:
        selected_items = self.notes_list.selectedItems()
        if not selected_items:
            return
        item = selected_items[0]
        note = item.data(Qt.UserRole)
        trash_note_dir = os.path.join(
            self.TRASH_DIR,
            NotesApp.safe_folder_name(note.title, note.uuid, note.timestamp),
        )
        note_dir = os.path.join(
            NOTES_DIR, NotesApp.safe_folder_name(note.title, note.uuid, note.timestamp)
        )
        if os.path.exists(trash_note_dir):
            shutil.move(trash_note_dir, note_dir)
        self.load_notes_from_disk()
        self.refresh_notes_list()
        for i in range(self.notes_list.count()):
            item = self.notes_list.item(i)
            note_obj = item.data(Qt.UserRole)
            if note_obj.uuid == note.uuid:
                self.notes_list.setCurrentRow(i)
                self.select_note(note_obj)
                break
        QMessageBox.information(
            self, "Восстановлено", "Заметка восстановлена из корзины."
        )

    def delete_note_permanently(self) -> None:
        selected_items = self.notes_list.selectedItems()
        if not selected_items:
            return
        reply = QMessageBox.question(
            self,
            "Удалить навсегда",
            "Удалить выбранную заметку безвозвратно?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            item = selected_items[0]
            note = item.data(Qt.UserRole)
            trash_note_dir = os.path.join(
                self.TRASH_DIR,
                NotesApp.safe_folder_name(note.title, note.uuid, note.timestamp),
            )
            if os.path.exists(trash_note_dir):
                shutil.rmtree(trash_note_dir)
            self.refresh_notes_list()
            QMessageBox.information(self, "Удалено", "Заметка удалена навсегда.")

    def empty_trash(self) -> None:
        if os.path.exists(self.TRASH_DIR):
            reply = QMessageBox.question(
                self,
                "Очистить корзину",
                "Удалить все заметки из корзины безвозвратно?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                for folder in os.listdir(self.TRASH_DIR):
                    folder_path = os.path.join(self.TRASH_DIR, folder)
                    shutil.rmtree(folder_path)
                self.refresh_notes_list()
                QMessageBox.information(
                    self, "Корзина очищена", "Все заметки удалены навсегда."
                )

    def load_note(self, item: QListWidgetItem | None) -> None:
        if item is None:
            self.setWindowTitle("Мои Заметки — [*]")
            self.setWindowModified(False)
            self.text_edit.blockSignals(True)
            self.text_edit.clear()
            self.text_edit.blockSignals(False)
            self.text_edit.setReadOnly(True)
            self.text_edit.hide()
            self.tags_label.setText("Теги: нет")
            self.current_note = None
            if hasattr(self, "spell_highlighter"):
                self.spell_highlighter.set_local_ignored(note.ignored_words)
            self.clear_custom_fields()
            self.add_field_btn.setEnabled(False)
            if hasattr(self, "history_list"):
                self.history_list.clear()
            self.attachments_scroll.setVisible(False)
            self._update_editor_visibility()
            return
        note = item.data(Qt.ItemDataRole.UserRole)
        self.select_note(note)
        self._update_editor_visibility()

    def select_note(self, note: Note | None) -> None:
        if note is None:
            return
        if getattr(self, "current_note", None):
            self.current_note.content = self.text_edit.toHtml()
            self.save_note_to_file(self.current_note)
        self.current_note = note
        if hasattr(self, "spell_highlighter"):
            self.spell_highlighter.set_local_ignored(note.ignored_words)
        self.text_edit.show()
        self.text_edit.setReadOnly(False)
        self.setWindowTitle(f"Мои Заметки — {note.title} [*]")
        self.setWindowModified(False)
        if hasattr(self, "dock_editor"):
            self.dock_editor.setWindowTitle("Редактор")
        pm_vis = bool(getattr(note, "password_manager_visible", False))
        rdp_vis = bool(getattr(note, "rdp_1c8_visible", False))
        rdp_removed = bool(getattr(note, "rdp_1c8_removed", False))
        self.password_manager_row.setVisible(pm_vis)
        self.rdp_1c8_row.setVisible(False if rdp_removed else rdp_vis)
        if hasattr(self, "action_toggle_pm"):
            self.action_toggle_pm.blockSignals(True)
            self.action_toggle_pm.setChecked(pm_vis)
            self._update_eye_action(
                self.action_toggle_pm, pm_vis, self.password_manager_label.text()
            )
            self.action_toggle_pm.blockSignals(False)
        if hasattr(self, "action_toggle_rdp"):
            self.action_toggle_rdp.blockSignals(True)
            self.action_toggle_rdp.setVisible(not rdp_removed)
            self.action_toggle_rdp.setEnabled(not rdp_removed)
            self.action_toggle_rdp.setChecked(rdp_vis)
            self._update_eye_action(
                self.action_toggle_rdp, rdp_vis, self.rdp_1c8_label.text()
            )
            self.action_toggle_rdp.blockSignals(False)
        fields_data = list(getattr(note, "custom_fields", []))
        self.clear_custom_fields()
        for field in fields_data:
            self.add_custom_field(field)
        self.add_field_btn.setEnabled(True)

        if hasattr(self, "settings"):
            self.settings.setValue("lastNoteUUID", note.uuid)

        if not getattr(note, "history", None):
            note.history = [note.content]
            note.history_index = 0
        self.update_history_list()
        self.update_history_list_selection()
        self.show_note_with_attachments(note)

        self.tags_label.setText(f"Теги: {', '.join(note.tags) if note.tags else 'нет'}")
        self.password_manager_field.setText(note.password_manager)
        self.rdp_1c8_field.setText(note.rdp_1c8)

        # Выделяем элемент в списке заметок
        for i in range(self.notes_list.count()):
            item = self.notes_list.item(i)
            n = item.data(Qt.UserRole)
            if n and n.uuid == note.uuid:
                self.notes_list.setCurrentItem(item)
                break

    def _html_escape(self, s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _load_dropdown_values(self) -> list[str]:
        try:
            vals = json.loads(self.settings.value("dropdown_values", "[]"))
            if not isinstance(vals, list):
                vals = []
        except Exception:
            vals = []
        if not vals:
            vals = ["Вариант 1", "Вариант 2", "Вариант 3"]
        return [str(v) for v in vals]

    def _dropdown_palette(self) -> tuple[str, str, str]:
        is_dark = self.settings.value("theme", "dark") == "dark"
        if is_dark:
            return ("#303030", "#ffffff", "#7a7a7a")
        return ("#f0f0f0", "#111111", "#b0b0b0")

    def _ensure_dd_map(self) -> None:
        if not hasattr(self, "_dropdown_tokens"):
            # id -> {"value": str, "values": list[str]}
            self._dropdown_tokens = {}

    def _get_dropdown_token_info(self, dd_id: str) -> dict | None:
        """Retrieve dropdown token info, populating cache from the document if needed."""
        self._ensure_dd_map()
        if dd_id in self._dropdown_tokens:
            return self._dropdown_tokens[dd_id]
        href = f"dropdown://{re.escape(dd_id)}"
        html = self.text_edit.toHtml()
        match = re.search(rf'<a[^>]*href="{href}"[^>]*>(.*?)</a>', html, flags=re.S)
        if not match:
            return None
        full_tag = match.group(0)
        inner = match.group(1)
        title_match = re.search(r'title="([^"]*)"', full_tag)
        if title_match:
            try:
                vals = json.loads(unquote(title_match.group(1)))
            except Exception:
                vals = self._load_dropdown_values()
        else:
            vals = self._load_dropdown_values()
        text = re.sub(r"<[^>]+>", "", inner)
        text = text.replace("▼", "").replace("&#9662;", "").strip()
        info = {"value": text, "values": vals}
        self._dropdown_tokens[dd_id] = info
        return info

    def _insert_dropdown_token(
        self, value: str, dd_id: str | None = None, values: list[str] | None = None
    ) -> str:
        self._ensure_dd_map()
        if dd_id is None:
            dd_id = uuid.uuid4().hex[:8]
        if values is None:
            values = self._load_dropdown_values()
        self._dropdown_tokens[dd_id] = {"value": value, "values": list(values)}
        bg, fg, br = self._dropdown_palette()
        inner = (
            f'<span style="display:inline-block; padding:2px 8px; '
            f"border-radius:6px; border:1px solid {br}; "
            f'background:{bg}; color:{fg};">{self._html_escape(value)} &#9662;</span>'
        )
        encoded = quote(json.dumps(values, ensure_ascii=False))
        html = (
            f'<a href="dropdown://{dd_id}" title="{encoded}" '
            f'style="text-decoration:none;">{inner}</a>&nbsp;'
        )
        c = self.text_edit.textCursor()
        c.insertHtml(html)
        self.text_edit.setTextCursor(c)
        self.record_state_for_undo()
        if hasattr(self, "debounce_timer"):
            self.debounce_timer.start(self.debounce_ms)
        return dd_id

    def _update_dropdown_token(self, dd_id: str, new_value: str) -> None:
        info = self._get_dropdown_token_info(dd_id)
        if not info:
            return
        info["value"] = new_value
        values = info.get("values", [])
        bg, fg, br = self._dropdown_palette()
        inner = (
            f'<span style="display:inline-block; padding:2px 8px; '
            f"border-radius:6px; border:1px solid {br}; "
            f'background:{bg}; color:{fg};">{self._html_escape(new_value)} &#9662;</span>'
        )

        href = f"dropdown://{re.escape(dd_id)}"
        encoded = quote(json.dumps(values, ensure_ascii=False))
        new_anchor = (
            f'<a href="dropdown://{dd_id}" title="{encoded}" '
            f'style="text-decoration:none;">{inner}</a>'
        )
        html = self.text_edit.toHtml()
        new_html = re.sub(
            rf'<a[^>]*href="{href}"[^>]*>.*?</a>', new_anchor, html, flags=re.S
        )
        self.text_edit.blockSignals(True)
        self.text_edit.setHtml(new_html)
        self.text_edit.blockSignals(False)
        self.record_state_for_undo()
        if hasattr(self, "debounce_timer"):
            self.debounce_timer.start(self.debounce_ms)

    def _edit_values_and_reopen(self, dd_id: str) -> None:
        info = self._get_dropdown_token_info(dd_id)
        if not info:
            return
        vals = self._open_dropdown_values_editor(info.get("values"))
        if vals is not None:
            info["values"] = vals
            self._update_dropdown_token(dd_id, info.get("value", ""))
            self.show_dropdown_menu_for_token(dd_id)

    def show_dropdown_menu_for_token(self, dd_id: str, global_pos=None) -> None:
        info = self._get_dropdown_token_info(dd_id)
        values = (
            info.get("values", self._load_dropdown_values())
            if info
            else self._load_dropdown_values()
        )
        menu = QMenu(self)
        menu.setStyleSheet(CUSTOM_MENU_STYLE)
        for v in values:
            act = menu.addAction(v)
            act.triggered.connect(
                lambda _, val=v: self._update_dropdown_token(dd_id, val)
            )
        menu.addSeparator()
        add_act = menu.addAction("➕ Добавить значение…")
        add_act.triggered.connect(lambda: self._add_value_to_dropdown(dd_id))
        curr = (info or {}).get("value", "")
        del_act = menu.addAction(f"➖ Удалить «{curr}» из списка")
        del_act.setEnabled(bool(curr and curr in values))
        del_act.triggered.connect(lambda: self._remove_value_from_dropdown(dd_id, curr))
        menu.addSeparator()
        edit_act = menu.addAction("✏️ Редактировать список…")
        edit_act.triggered.connect(lambda: self._edit_values_and_reopen(dd_id))
        if global_pos is None:
            cr = self.text_edit.cursorRect(self.text_edit.textCursor())
            global_pos = self.text_edit.viewport().mapToGlobal(cr.bottomLeft())
        menu.exec(global_pos)

    def show_note_with_attachments(self, note: Note | None) -> None:
        files = self.attachments_watcher.files()
        if files:
            self.attachments_watcher.removePaths(files)
        dirs = self.attachments_watcher.directories()
        if dirs:
            self.attachments_watcher.removePaths(dirs)
        if not note:
            self.attachments_scroll.setVisible(False)
            self.text_edit.blockSignals(True)
            self.text_edit.clear()
            self.text_edit.blockSignals(False)
            if hasattr(self, "attachments_layout"):
                for i in reversed(range(self.attachments_layout.count())):
                    widget = self.attachments_layout.itemAt(i).widget()
                    if widget:
                        widget.setParent(None)
                        widget.deleteLater()
            self.attachments_scroll.setVisible(False)
            return
        cursor_pos = None
        anchor_pos = None
        if note == self.current_note:
            cursor = self.text_edit.textCursor()
            cursor_pos = cursor.position()
            anchor_pos = cursor.anchor()
        self.text_edit.blockSignals(True)
        self.text_edit.setHtml(
            note.content_html
            if hasattr(note, "content_html") and note.content_html
            else note.content
        )
        self.text_edit.blockSignals(False)
        if cursor_pos is not None and anchor_pos is not None:
            self._safe_restore_cursor(anchor_pos, cursor_pos)
        if hasattr(self, "attachments_layout"):
            for i in reversed(range(self.attachments_layout.count())):
                widget = self.attachments_layout.itemAt(i).widget()
                if widget:
                    widget.setParent(None)
                    widget.deleteLater()
            note_dir = os.path.join(
                NOTES_DIR,
                NotesApp.safe_folder_name(note.title, note.uuid, note.timestamp),
            )
            attachments_found = False
            if os.path.isdir(note_dir):
                ignored_files = {"note.json", ".DS_Store", "Thumbs.db"}
                ignored_prefixes = ("~$", ".~")
                ignored_suffixes = ("~", ".tmp", ".temp")
                for filename in os.listdir(note_dir):
                    if (
                        filename in ignored_files
                        or filename.startswith(ignored_prefixes)
                        or filename.endswith(ignored_suffixes)
                    ):
                        continue
                    attachments_found = True
                    file_path = os.path.join(note_dir, filename)
                    item_widget = QWidget()
                    layout = QHBoxLayout(item_widget)
                    if filename.lower().endswith(tuple(IMAGE_EXTENSIONS)):
                        pixmap = QPixmap(file_path)
                        icon_label = QLabel()
                        icon_label.setPixmap(
                            pixmap.scaled(
                                48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation
                            )
                        )
                        layout.addWidget(icon_label)
                    else:
                        icon_label = QLabel()
                        if os.path.exists(FILE_ICON_PATH):
                            icon_label.setPixmap(
                                QPixmap(FILE_ICON_PATH).scaled(
                                    48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation
                                )
                            )
                        else:
                            icon_label.setPixmap(
                                self.style()
                                .standardIcon(QStyle.SP_FileIcon)
                                .pixmap(32, 32)
                            )
                        layout.addWidget(icon_label)
                    label = QLabel(filename)
                    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                    layout.addWidget(label)
                    open_btn = QPushButton("Открыть")
                    open_btn.setToolTip("Открыть вложение")
                    open_btn.setFixedSize(60, 24)
                    open_btn.clicked.connect(
                        lambda _, path=file_path: self.text_edit._open_any_link(path)
                    )
                    layout.addWidget(open_btn)
                    del_btn = QPushButton("❌")
                    del_btn.setToolTip("Удалить вложение")
                    del_btn.setFixedSize(28, 24)
                    del_btn.clicked.connect(
                        lambda _, path=file_path: self.delete_attachment_from_panel(
                            path
                        )
                    )
                    layout.addWidget(del_btn)
                    item_widget.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
                    if self.attachments_layout.count() > 0:
                        self.attachments_layout.addWidget(QLabel(" - "))
                    self.attachments_layout.addWidget(item_widget)
                if note_dir not in self.attachments_watcher.directories():
                    self.attachments_watcher.addPath(note_dir)
            self.attachments_scroll.setVisible(attachments_found)

    def _refresh_attachments(self, *_) -> None:
        if not self.current_note:
            return
        self._rebuild_attachments_panel(self.current_note)

    def delete_attachment_from_panel(self, file_path: str) -> None:
        reply = QMessageBox.question(
            self,
            "Удалить вложение",
            f"Удалить вложение '{os.path.basename(file_path)}'?\nФайл будет удалён безвозвратно.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            b64_data = None
            if file_path.lower().endswith(tuple(IMAGE_EXTENSIONS)):
                try:
                    pixmap = QPixmap(file_path)
                    if not pixmap.isNull():
                        buffer = QBuffer()
                        buffer.open(QIODevice.WriteOnly)
                        pixmap.save(buffer, "PNG")
                        b64_data = base64.b64encode(buffer.data()).decode("utf-8")
                except Exception:
                    b64_data = None
            try:
                os.remove(file_path)
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", f"Не удалось удалить файл:\n{e}")
            if self.current_note:
                file_path_abs = os.path.abspath(file_path)
                urls = {
                    QUrl.fromLocalFile(file_path_abs).toString(),
                    "file:///" + quote(file_path_abs.replace(os.sep, "/")),
                }
                html = self.text_edit.toHtml()
                for url in urls:
                    esc = re.escape(url)
                    html = re.sub(
                        rf"(<br>\s*)*(?:📄\s*)?<a[^>]+href=\"{esc}\"[^>]*>.*?</a>(<br>\s*)*",
                        "",
                        html,
                        flags=re.IGNORECASE,
                    )
                    html = re.sub(
                        rf"(<br>\s*)*<img[^>]+src=\"{esc}\"[^>]*>(<br>\s*)*",
                        "",
                        html,
                        flags=re.IGNORECASE,
                    )
                if b64_data:
                    esc_b64 = re.escape(b64_data)
                    html = re.sub(
                        rf"(<br>\s*)*<img[^>]+src=\"data:image/[^;]+;base64,{esc_b64}\"[^>]*>(<br>\s*)*",
                        "",
                        html,
                        flags=re.IGNORECASE,
                    )
                self.text_edit.blockSignals(True)
                self.text_edit.setHtml(html)
                self.text_edit.blockSignals(False)
                self.save_note_quiet(force=True)
                self._rebuild_attachments_panel(self.current_note)

    def _safe_restore_cursor(self, anchor_pos: int, cursor_pos: int) -> None:
        doc = self.text_edit.document()
        max_pos = max(0, doc.characterCount() - 1)
        a = max(0, min(anchor_pos, max_pos))
        p = max(0, min(cursor_pos, max_pos))
        cur = self.text_edit.textCursor()
        if a == p:
            cur.setPosition(p)
        else:
            cur.setPosition(a)
            cur.setPosition(p, QTextCursor.KeepAnchor)
        self.text_edit.setTextCursor(cur)

    def _atomic_json_dump(path: str, data: dict) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def _update_editor_visibility(self):
        has = self.current_note is not None
        self.dock_editor.setVisible(has)
        self.dock_toolbar.setVisible(has)
        self.visibility_toolbar.setVisible(has)
        self.text_edit.setVisible(has)
        self.text_edit.setReadOnly(not has)
        self.tags_label.setVisible(has)
        if not has:
            self.tags_label.setText("Теги: нет")
        self.add_field_btn.setEnabled(has)
        self.attachments_scroll.setVisible(
            False if not has else self.attachments_scroll.isVisible()
        )
        if not has:
            self.password_manager_row.setVisible(False)
            self.rdp_1c8_row.setVisible(False)
            if hasattr(self, "action_toggle_pm"):
                self.action_toggle_pm.setEnabled(False)
            if hasattr(self, "action_toggle_rdp"):
                self.action_toggle_rdp.setEnabled(False)
            for w in self.custom_fields_widgets:
                w["row"].setVisible(False)
                w["action"].setEnabled(False)
            return
        if hasattr(self, "action_toggle_pm"):
            self.action_toggle_pm.setEnabled(True)
            self.action_toggle_pm.blockSignals(True)
            self.action_toggle_pm.setChecked(
                bool(self.current_note.password_manager_visible)
            )
            self.action_toggle_pm.blockSignals(False)
        if hasattr(self, "action_toggle_rdp"):
            self.action_toggle_rdp.setEnabled(True)
            self.action_toggle_rdp.blockSignals(True)
            self.action_toggle_rdp.setChecked(bool(self.current_note.rdp_1c8_visible))
            self.action_toggle_rdp.blockSignals(False)
        if hasattr(self, "action_toggle_rdp"):
            rdp_removed = bool(getattr(self.current_note, "rdp_1c8_removed", False))
            self.action_toggle_rdp.setVisible(not rdp_removed)  # <— НОВОЕ
            self.action_toggle_rdp.setEnabled(not rdp_removed)  # <— НОВОЕ
            self.action_toggle_rdp.blockSignals(True)
            self.action_toggle_rdp.setChecked(
                False if rdp_removed else bool(self.current_note.rdp_1c8_visible)
            )
            self.action_toggle_rdp.blockSignals(False)

        self.rdp_1c8_row.setVisible(
            False if rdp_removed else bool(self.current_note.rdp_1c8_visible)
        )
        self.password_manager_row.setVisible(
            bool(self.current_note.password_manager_visible)
        )
        self.rdp_1c8_row.setVisible(bool(self.current_note.rdp_1c8_visible))
        for w in self.custom_fields_widgets:
            w["action"].setEnabled(True)
            vis = bool(w["action"].isChecked())
            w["row"].setVisible(vis)
            self._update_eye_action(w["action"], vis, w["label_edit"].text())

    def attach_file_to_note(self) -> None:
        if not self.current_note:
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Прикрепить файл",
            "",
            ATTACH_FILE_FILTER,
        )
        if not file_path:
            return
        note_dir = os.path.join(
            NOTES_DIR,
            NotesApp.safe_folder_name(
                self.current_note.title,
                self.current_note.uuid,
                self.current_note.timestamp,
            ),
        )
        os.makedirs(note_dir, exist_ok=True)
        filename = os.path.basename(file_path)
        dest = os.path.join(note_dir, filename)
        try:
            shutil.copy(file_path, dest)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось скопировать файл: {e}")
            return
        is_image = filename.lower().endswith(tuple(IMAGE_EXTENSIONS))
        cursor = self.text_edit.textCursor()
        self.text_edit.setTextCursor(cursor)
        if is_image:
            pixmap = QPixmap(dest)
            if not pixmap.isNull():
                buffer = QBuffer()
                buffer.open(QIODevice.WriteOnly)
                pixmap.save(buffer, "PNG")
                base64_data = base64.b64encode(buffer.data()).decode("utf-8")
                html_img = (
                    f'<img src="Data:image/png;base64,{base64_data}" width="200"><br>'
                )
                self.text_edit.insertHtml(html_img)
                self.record_state_for_undo()
            else:
                QMessageBox.warning(
                    self, "Ошибка", f"Не удалось открыть изображение: {filename}"
                )
        else:
            file_url = QUrl.fromLocalFile(os.path.abspath(dest)).toString()
            self.text_edit.insertHtml(f'📄 <a href="{file_url}">{filename}</a>')
        QMessageBox.information(
            self, "Файл прикреплён", f"Файл '{filename}' прикреплён к заметке."
        )
        self.save_note_quiet(force=True)
        self._rebuild_attachments_panel(self.current_note)

    def attach_file_to_note_external(self, file_path: str) -> None:
        if not self.current_note:
            return
        note_dir = os.path.join(
            NOTES_DIR,
            NotesApp.safe_folder_name(
                self.current_note.title,
                self.current_note.uuid,
                self.current_note.timestamp,
            ),
        )
        os.makedirs(note_dir, exist_ok=True)
        filename = os.path.basename(file_path)
        dest = os.path.join(note_dir, filename)
        try:
            shutil.copy(file_path, dest)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось скопировать файл: {e}")
            return
        is_image = filename.lower().endswith(tuple(IMAGE_EXTENSIONS))
        cursor = self.text_edit.textCursor()
        self.text_edit.setTextCursor(cursor)
        if is_image:
            pixmap = QPixmap(dest)
            if not pixmap.isNull():
                buffer = QBuffer()
                buffer.open(QIODevice.WriteOnly)
                pixmap.save(buffer, "PNG")
                base64_data = base64.b64encode(buffer.data()).decode("utf-8")
                html_img = (
                    f'<img src="Data:image/png;base64,{base64_data}" width="200"><br>'
                )
                self.text_edit.insertHtml(html_img)
                self.record_state_for_undo()
            else:
                QMessageBox.warning(
                    self, "Ошибка", f"Не удалось открыть изображение: {filename}"
                )
        else:
            file_url = QUrl.fromLocalFile(os.path.abspath(dest)).toString()
            self.text_edit.insertHtml(f'📄 <a href="{file_url}">{filename}</a>')
        QMessageBox.information(
            self, "Файл прикреплён", f"Файл '{filename}' прикреплён к заметке."
        )
        self.save_note_quiet(force=True)
        self._rebuild_attachments_panel(self.current_note)

    def align_left(self) -> None:
        self.text_edit.setAlignment(Qt.AlignLeft)

    def align_center(self) -> None:
        self.text_edit.setAlignment(Qt.AlignCenter)

    def align_right(self) -> None:
        self.text_edit.setAlignment(Qt.AlignRight)

    def align_justify(self) -> None:
        self.text_edit.setAlignment(Qt.AlignJustify)

    def change_font(self, font: QFont) -> None:
        self.text_edit.setCurrentFont(font)

    def change_font_size(self, size: int) -> None:
        cursor = self.text_edit.textCursor()
        fmt = QTextCharFormat()
        fmt.setFontPointSize(size)
        if cursor.hasSelection():
            cursor.mergeCharFormat(fmt)
        else:
            self.text_edit.setCurrentCharFormat(fmt)

    def _current_font_size(self, cursor: QTextCursor) -> float:
        size = cursor.charFormat().fontPointSize()
        if not size:
            size = self.text_edit.fontPointSize() or 14
        return size

    def toggle_bold(self) -> None:
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            current_format = cursor.charFormat()
            fmt = QTextCharFormat()
            new_weight = (
                QFont.Normal
                if current_format.fontWeight() == QFont.Bold
                else QFont.Bold
            )
            fmt.setFontWeight(new_weight)
            cursor.mergeCharFormat(fmt)
        else:
            fmt = self.text_edit.currentCharFormat()
            new_weight = QFont.Normal if fmt.fontWeight() == QFont.Bold else QFont.Bold
            fmt.setFontWeight(new_weight)
            self.text_edit.setCurrentCharFormat(fmt)

    def toggle_italic(self) -> None:
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            current_format = cursor.charFormat()
            fmt = QTextCharFormat()
            fmt.setFontItalic(not current_format.fontItalic())
            cursor.mergeCharFormat(fmt)
        else:
            fmt = self.text_edit.currentCharFormat()
            fmt.setFontItalic(not fmt.fontItalic())
            self.text_edit.setCurrentCharFormat(fmt)

    def toggle_underline(self) -> None:
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            current_format = cursor.charFormat()
            fmt = QTextCharFormat()
            fmt.setFontUnderline(not current_format.fontUnderline())
            cursor.mergeCharFormat(fmt)
        else:
            fmt = self.text_edit.currentCharFormat()
            fmt.setFontUnderline(not fmt.fontUnderline())
            self.text_edit.setCurrentCharFormat(fmt)

    def _set_dropdown_values(self, dd_id: str, values: list[str]) -> None:
        info = self._get_dropdown_token_info(dd_id)
        if not info:
            return
        cleaned = []
        for v in values:
            v = (v or "").strip()
            if v and v not in cleaned:
                cleaned.append(v)
        info["values"] = cleaned
        self._update_dropdown_token(dd_id, info.get("value", ""))

    def _add_value_to_dropdown(self, dd_id: str) -> None:
        text, ok = QInputDialog.getText(self, "Добавить значение", "Текст:")
        if not ok:
            return
        val = (text or "").strip()
        if not val:
            return
        info = self._get_dropdown_token_info(dd_id)
        if not info:
            return
        values = list(info.get("values", []))
        if val not in values:
            values.append(val)
            self._set_dropdown_values(dd_id, values)
        self.show_dropdown_menu_for_token(dd_id)

    def _remove_value_from_dropdown(self, dd_id: str, value: str) -> None:
        info = self._get_dropdown_token_info(dd_id)
        if not info:
            return
        values = [v for v in info.get("values", []) if v != value]
        self._set_dropdown_values(dd_id, values)
        self.show_dropdown_menu_for_token(dd_id)

    def change_text_color(self) -> None:
        color = QColorDialog.getColor(Qt.black, self.text_edit, "Выберите цвет текста")
        if color.isValid():
            cursor = self.text_edit.textCursor()
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            if cursor.hasSelection():
                cursor.mergeCharFormat(fmt)
            else:
                self.text_edit.setCurrentCharFormat(fmt)

    def change_background_color(self) -> None:
        color = QColorDialog.getColor(Qt.white, self.text_edit, "Выберите цвет фона")
        if color.isValid():
            cursor = self.text_edit.textCursor()
            fmt = QTextCharFormat()
            fmt.setBackground(color)
            if cursor.hasSelection():
                cursor.mergeCharFormat(fmt)
            else:
                self.text_edit.setCurrentCharFormat(fmt)

    def clear_formatting_complete(self) -> None:
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            selected_text = cursor.selectedText()
            fmt = QTextCharFormat()
            fmt.setFontFamily("Times New Roman")
            fmt.setFontPointSize(14)
            cursor.insertText(selected_text, fmt)
        else:
            fmt = QTextCharFormat()
            fmt.setFontFamily("Times New Roman")
            fmt.setFontPointSize(14)
            self.text_edit.setCurrentCharFormat(fmt)

    def apply_formatting(self, **kwargs) -> None:
        cursor = self.text_edit.textCursor()
        fmt = QTextCharFormat()
        for key, value in kwargs.items():
            if key == "bold":
                fmt.setFontWeight(QFont.Bold if value else QFont.Normal)
            elif key == "italic":
                fmt.setFontItalic(value)
            elif key == "underline":
                fmt.setFontUnderline(value)
            elif key == "color":
                fmt.setForeground(QColor(value))
            elif key == "background":
                fmt.setBackground(QColor(value))
            elif key == "font_size":
                fmt.setFontPointSize(value)
        if cursor.hasSelection():
            cursor.mergeCharFormat(fmt)
        else:
            self.text_edit.setCurrentCharFormat(fmt)

    def update_font_controls(self) -> None:
        cursor = self.text_edit.textCursor()
        fmt = cursor.charFormat()
        font = fmt.font()
        family = font.family() if font.family() else "Times New Roman"
        size = int(font.pointSize() if font.pointSize() > 0 else 14)
        self.font_combo.blockSignals(True)
        self.font_combo.setCurrentFont(QFont(family))
        self.font_combo.blockSignals(False)
        self.font_size_spin.blockSignals(True)
        self.font_size_spin.setValue(size)
        self.font_size_spin.blockSignals(False)

    def get_current_formatting(self):
        cursor = self.text_edit.textCursor()
        fmt = (
            cursor.charFormat()
            if cursor.hasSelection()
            else self.text_edit.currentCharFormat()
        )
        return {
            "bold": fmt.fontWeight() == QFont.Bold,
            "italic": fmt.fontItalic(),
            "underline": fmt.fontUnderline(),
            "color": fmt.foreground().color(),
            "background": fmt.background().color(),
            "font_size": fmt.fontPointSize(),
        }

    def set_font_family(self, font_family: str) -> None:
        cursor = self.text_edit.textCursor()
        fmt = QTextCharFormat()
        fmt.setFontFamily(font_family)
        if cursor.hasSelection():
            cursor.mergeCharFormat(fmt)
        else:
            self.text_edit.setCurrentCharFormat(fmt)

    def toggle_strikethrough(self) -> None:
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            current_format = cursor.charFormat()
            fmt = QTextCharFormat()
            fmt.setFontStrikeOut(not current_format.fontStrikeOut())
            cursor.mergeCharFormat(fmt)
        else:
            fmt = self.text_edit.currentCharFormat()
            fmt.setFontStrikeOut(not fmt.fontStrikeOut())
            self.text_edit.setCurrentCharFormat(fmt)

    @staticmethod
    def _app_dir():
        return (
            os.path.dirname(sys.executable)
            if getattr(sys, "frozen", False)
            else os.path.abspath(os.path.dirname(__file__))
        )

    def open_readme(self):
        path = os.path.join(APPDIR, "README.md")
        if not os.path.exists(path):
            up = os.path.abspath(os.path.join(APPDIR, "..", "README.md"))
            if os.path.exists(up):
                path = up
        if not os.path.exists(path):
            QMessageBox.warning(self, "README", f"Файл не найден:\n{path}")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("README.md")
        dlg.resize(900, 700)
        from PySide6.QtWidgets import QVBoxLayout, QTextBrowser, QDialogButtonBox

        v = QVBoxLayout(dlg)
        view = QTextBrowser(dlg)
        view.setOpenLinks(False)
        view.setOpenExternalLinks(False)
        view.setTextInteractionFlags(Qt.TextBrowserInteraction)
        v.addWidget(view)
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.addButton("Открыть в редакторе", QDialogButtonBox.ActionRole)
        v.addWidget(btns)
        with open(path, "r", encoding="utf-8") as f:
            md = f.read()
        try:
            view.setMarkdown(md)
        except AttributeError:
            view.setPlainText(md)
        base = QUrl.fromLocalFile(os.path.abspath(os.path.dirname(path)) + os.sep)
        view.document().setBaseUrl(base)
        self._ensure_heading_ids(view)
        if hasattr(self, "_linkify_urls_in_browser"):
            self._linkify_urls_in_browser(view)
            view.document().setBaseUrl(base)
            view.setOpenLinks(False)
            view.setOpenExternalLinks(False)

        def _on_anchor_clicked(url: QUrl):
            if (not url.scheme()) and url.fragment():
                frag = url.fragment()
                if not view.scrollToAnchor(frag):
                    view.scrollToAnchor(frag.lower())
                return
            if url.isRelative():
                QDesktopServices.openUrl(view.document().baseUrl().resolved(url))
                return
            QDesktopServices.openUrl(url)

        view.anchorClicked.connect(_on_anchor_clicked)

        def _open_external():
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(path)))

        btns.rejected.connect(dlg.reject)
        for b in btns.buttons():
            if btns.buttonRole(b) == QDialogButtonBox.ActionRole:
                b.clicked.connect(_open_external)
                break
        fg = dlg.frameGeometry()
        fg.moveCenter(self.frameGeometry().center())
        dlg.move(fg.topLeft())
        dlg.exec()

    def _ensure_heading_ids(self, view: QTextBrowser):
        html = view.toHtml()

        def slugify(text: str) -> str:
            s = text.strip().lower()
            s = re.sub(r"[^0-9a-zа-яё \-]+", "", s, flags=re.IGNORECASE)
            s = re.sub(r"\s+", "-", s)
            s = re.sub(r"-{2,}", "-", s)
            return s.strip("-")

        def repl(m):
            tag, attrs, inner = m.group(1), m.group(2), m.group(3)
            if re.search(r"\b(id|name)\s*=", attrs, flags=re.I):
                return m.group(0)
            text_only = re.sub(r"<[^>]*>", "", inner)
            anchor = slugify(text_only)
            if not anchor:
                return m.group(0)
            return f'<{tag}{attrs} id="{anchor}" name="{anchor}">{inner}</{tag}>'

        html = re.sub(r"<(h[1-6])([^>]*)>(.*?)</\1>", repl, html, flags=re.I | re.S)
        view.setHtml(html)
        base = view.document().baseUrl()
        view.document().setBaseUrl(base)
        view.setOpenLinks(False)
        view.setOpenExternalLinks(False)

    def _linkify_urls_in_browser(self, view: QTextBrowser):
        html = view.toHtml()
        pattern = re.compile(r'(?<!href=")(?<!src=")((?:https?://|www\.)[^\s"<>]+)')

        def repl(m):
            url = m.group(1)
            href = url if url.startswith(("http://", "https://")) else f"http://{url}"
            return f'<a href="{href}">{url}</a>'

        html = pattern.sub(repl, html)
        view.setHtml(html)
        view.setOpenExternalLinks(True)
        view.setOpenLinks(False)

    def toggle_case(self) -> None:
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            text = cursor.selectedText()
            text = text.swapcase()
            cursor.insertText(text)

    def apply_heading(self, level: int) -> None:
        cursor = self.text_edit.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.WordUnderCursor)
        fmt = QTextCharFormat()
        size_map = {1: 24, 2: 18, 3: 14}
        fmt.setFontPointSize(size_map.get(level, 12))
        fmt.setFontWeight(QFont.Bold)
        cursor.mergeCharFormat(fmt)

    def insert_list(self, style: QTextListFormat.Style) -> None:
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            selection_start = cursor.selectionStart()
            selection_end = cursor.selectionEnd()
            cursor.setPosition(selection_start)
            cursor.setPosition(selection_end, QTextCursor.KeepAnchor)
            block_format = QTextListFormat()
            block_format.setStyle(style)
            cursor.createList(block_format)
        else:
            if style == QTextListFormat.ListDisc:
                cursor.insertText("• ")
            elif style == QTextListFormat.ListDecimal:
                cursor.insertText("1. ")

    def insert_bullet_list(self) -> None:
        self.insert_list(QTextListFormat.ListDisc)

    def insert_numbered_list(self) -> None:
        self.insert_list(QTextListFormat.ListDecimal)

    def insert_checkbox(self) -> None:
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            selection_start = cursor.selectionStart()
            selection_end = cursor.selectionEnd()

            doc = self.text_edit.document()
            start_block = doc.findBlock(selection_start)
            end_block = doc.findBlock(selection_end)

            block = start_block
            while True:
                block_cursor = QTextCursor(block)
                block_cursor.movePosition(QTextCursor.StartOfBlock)
                block_cursor.movePosition(QTextCursor.Right, QTextCursor.MoveAnchor, 0)
                text = block.text()
                if text.strip() and not (
                    text.startswith("☐ ") or text.startswith("☑ ")
                ):
                    block_cursor.insertText("☐ ")
                if block == end_block:
                    break
                block = block.next()
        else:
            cursor.movePosition(QTextCursor.StartOfLine)
            text = cursor.block().text()
            if not (text.startswith("☐ ") or text.startswith("☑ ")):
                cursor.insertText("☐ ")
                cursor.movePosition(QTextCursor.Right, QTextCursor.MoveAnchor, 2)
                self.text_edit.setTextCursor(cursor)
                self.text_edit.setFocus()

    def insert_horizontal_line(self) -> None:
        cursor = self.text_edit.textCursor()
        cursor.insertHtml("<hr style='border:1px solid #888;'><br>")
        cursor.movePosition(QTextCursor.EndOfBlock)
        self.text_edit.setTextCursor(cursor)

    def insert_image_html(
        self, html_img: str, replace_current: bool = False, orig_path: str | None = None
    ) -> None:
        doc = self.text_edit.document()
        cursor = QTextCursor(doc)
        replaced = False
        while not cursor.isNull() and not cursor.atEnd():
            if cursor.charFormat().isImageFormat():
                img_format = cursor.charFormat().toImageFormat()
                if orig_path and (
                    img_format.name() == orig_path
                    or (
                        img_format.name().startswith("Data:image")
                        and orig_path.startswith("Data:image")
                    )
                ):
                    cursor.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, 1)
                    cursor.insertHtml(html_img)
                    replaced = True
                    break
            cursor.movePosition(QTextCursor.NextCharacter)
        if not replaced:
            insert_cursor = self.text_edit.textCursor()
            insert_cursor.movePosition(QTextCursor.End)
            self.text_edit.setTextCursor(insert_cursor)
            self.text_edit.insertHtml(html_img)
            self.record_state_for_undo()

    def insert_image_into_note(self, image_path: str) -> None:
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            pixmap.save(buffer, "PNG")
            base64_data = base64.b64encode(buffer.data()).decode("utf-8")
            html_img = (
                f'<img src="Data:image/png;base64,{base64_data}" width="300"><br>'
            )
            cursor = self.text_edit.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.text_edit.setTextCursor(cursor)
            self.text_edit.insertHtml(html_img)
            self.record_state_for_undo()

    def insert_image_from_clipboard(self, image: QImage) -> None:
        if not self.current_note:
            QMessageBox.warning(
                self, "Нет заметки", "Пожалуйста, выберите или создайте заметку."
            )
            return
        note_dir = os.path.join(
            NOTES_DIR,
            NotesApp.safe_folder_name(self.current_note.title, self.current_note.uuid),
        )
        os.makedirs(note_dir, exist_ok=True)
        filename = f"clipboard_{uuid.uuid4().hex}.png"
        filepath = os.path.join(note_dir, filename)
        try:
            image.save(filepath)
        except Exception as e:
            QMessageBox.critical(
                self, "Ошибка", f"Не удалось сохранить изображение: {e}"
            )
            return
        pixmap = QPixmap(filepath)
        if not pixmap.isNull():
            buffer = QBuffer()
            buffer.open(QIODevice.WriteOnly)
            pixmap.save(buffer, "PNG")
            base64_data = base64.b64encode(buffer.data()).decode("utf-8")
            html_img = (
                f'<img src="Data:image/png;base64,{base64_data}" width="200"><br>'
            )
            cursor = self.text_edit.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.text_edit.setTextCursor(cursor)
            self.text_edit.insertHtml(html_img)
            self.record_state_for_undo()

        self.save_note()

    def insert_audio_link(self, filepath: str) -> None:
        filename = os.path.basename(filepath)
        file_url = QUrl.fromLocalFile(os.path.abspath(filepath)).toString()
        self.text_edit.insertHtml(f'📄 <a href="{file_url}">{filename}</a>')
        self.save_note()

    def toggle_audio_recording(self) -> None:
        if self.audio_thread and self.audio_thread.isRunning():
            self.audio_thread.stop()
            self.audio_thread.wait()
            self.audio_thread = None
            self.audio_button.setText("🎤")
        else:
            filename = str(uuid.uuid4()) + ".wav"
            folder_path = os.path.join(NOTES_DIR, "Audio")
            os.makedirs(folder_path, exist_ok=True)
            full_path = os.path.join(folder_path, filename)

            self.audio_thread = AudioRecorderThread(full_path)
            self.audio_thread.recording_finished.connect(self.insert_audio_link)
            self.audio_thread.start()
            self.audio_button.setText("⏹")

    def apply_sorting(self) -> None:
        index = self.sort_combo.currentIndex()
        reverse = self.sort_order_combo.currentIndex() == 1

        if index == 0:
            self.notes.sort(key=lambda note: note.title.lower(), reverse=reverse)
            self.refresh_notes_list()
        elif index == 1:
            self.notes.sort(key=lambda note: note.timestamp, reverse=reverse)
            self.refresh_notes_list()
        elif index == 2:
            self.show_favorites_only()

    def filter_notes(self):
        if self.current_note:
            self.current_note.content = self.text_edit.toHtml()
        query = self.search_field.text().strip().lower()
        if not query:
            return self.notes
        filtered = []
        for note in self.notes:
            if self.current_note and note.uuid == self.current_note.uuid:
                content_plain = self.text_edit.toPlainText()
            else:
                doc = QTextDocument()
                doc.setHtml(note.content)
                content_plain = doc.toPlainText()
            reminder_raw = str(note.reminder or "").lower()
            reminder_human = ""
            if note.reminder:
                try:
                    dt = QDateTime.fromString(note.reminder, Qt.ISODate)
                    if dt.isValid():
                        reminder_human = dt.toString("dd.MM.yyyy HH:mm")
                except Exception:
                    reminder_human = ""
            if (
                query in note.title.lower()
                or query in content_plain.lower()
                or query in reminder_raw
                or (reminder_human and query in reminder_human.lower())
            ):
                filtered.append(note)
        return filtered

    def refresh_notes_list(self) -> None:
        self.notes_list.clear()
        filtered_notes = self.filter_notes()
        pinned_notes = [note for note in filtered_notes if note.pinned]
        unpinned_notes = [note for note in filtered_notes if not note.pinned]
        fav_color = self.get_contrast_favorite_color()
        current_uuid = self.current_note.uuid if self.current_note else None

        def _add_note(note):
            title = note.title
            timestamp = QDateTime.fromString(note.timestamp, Qt.ISODate)
            date_str = timestamp.toString("dd.MM.yyyy")
            reminder_symbol = " 🔔" if note.reminder else ""
            item_text = f"{title} — {date_str}{reminder_symbol}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, note)
            item.setFont(QFont("Segoe UI Emoji", 10))
            if note.favorite:
                item.setForeground(fav_color)
            self.notes_list.addItem(item)
            return item

        for note in pinned_notes:
            _add_note(note)

        if pinned_notes and unpinned_notes:
            sep_item = QListWidgetItem()
            sep_item.setFlags(Qt.NoItemFlags)
            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            line.setFrameShadow(QFrame.Sunken)
            sep_item.setSizeHint(line.sizeHint())
            self.notes_list.addItem(sep_item)
            self.notes_list.setItemWidget(sep_item, line)

        for note in unpinned_notes:
            _add_note(note)

        if current_uuid:
            for i in range(self.notes_list.count()):
                it = self.notes_list.item(i)
                n = it.data(Qt.UserRole)
                if n and n.uuid == current_uuid:
                    self.notes_list.setCurrentItem(it)
                    break

    def get_contrast_favorite_color(self) -> QColor:
        bg = self.notes_list.palette().color(self.notes_list.backgroundRole())
        avg = (bg.red() + bg.green() + bg.blue()) / 3
        if avg > 200:
            return QColor(180, 0, 0)
        elif avg > 127:
            return QColor(220, 25, 25)
        else:
            return QColor(255, 60, 60)

    def sort_notes_by_title(self) -> None:
        self.notes.sort(key=lambda note: note.title.lower())
        self.refresh_notes_list()

    def sort_notes_by_date(self) -> None:
        self.notes.sort(key=lambda note: note.timestamp, reverse=True)
        self.refresh_notes_list()

    def toggle_favorite(self):
        if self.current_note:
            self.current_note.favorite = not self.current_note.favorite
            self.refresh_notes_list()

    def show_favorites_only(self) -> None:
        self.notes_list.clear()
        for note in self.notes:
            if note.favorite:
                timestamp = QDateTime.fromString(note.timestamp, Qt.ISODate)
                date_str = timestamp.toString("dd.MM.yyyy")
                reminder_symbol = " 🔔" if note.reminder else ""
                item_text = f"{note.title} — {date_str}{reminder_symbol}"
                item = QListWidgetItem(item_text)
                item.setData(Qt.UserRole, note)
                item.setFont(QFont("Segoe UI Emoji", 10))
                item.setForeground(QColor("gold"))
                self.notes_list.addItem(item)

    def add_tag_to_note(self) -> None:
        if not self.current_note:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Добавить тег")
        layout = QVBoxLayout(dialog)
        combo = QComboBox(dialog)
        combo.setEditable(True)
        all_tags = self.get_all_tags()
        combo.addItems(all_tags)
        layout.addWidget(combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(buttons)
        dialog.setLayout(layout)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec() == QDialog.Accepted:
            tag_line = combo.currentText()
            tags = [t.strip() for t in tag_line.split(",") if t.strip()]
            added = []
            for tag in tags:
                if tag and tag not in self.current_note.tags:
                    self.current_note.tags.append(tag)
                    added.append(tag)
            if added:
                self.update_tag_filter_items()
                QMessageBox.information(
                    self, "Теги добавлены", "Добавлены теги: " + ", ".join(added)
                )
                self.tags_label.setText(f"Теги: {', '.join(self.current_note.tags)}")
            else:
                QMessageBox.information(
                    self, "Нет новых тегов", "Все введённые теги уже есть у заметки."
                )

    def manage_tags_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        dialog.setWindowTitle("Управление тегами")
        layout = QVBoxLayout(dialog)
        all_tags = sorted(self.get_all_tags())
        combo = QComboBox(dialog)
        combo.addItems(all_tags)
        layout.addWidget(combo)
        rename_btn = QPushButton("Переименовать тег")
        delete_btn = QPushButton("Удалить тег")
        layout.addWidget(rename_btn)
        layout.addWidget(delete_btn)

        def rename_tag():
            old_tag = combo.currentText()
            new_tag, ok = QInputDialog.getText(
                dialog, "Переименовать тег", f"Новый тег для '{old_tag}':"
            )
            if ok and new_tag and new_tag != old_tag:
                for note in self.notes:
                    note.tags = [new_tag if t == old_tag else t for t in note.tags]
                self.save_all_notes_to_disk()
                self.update_tag_filter_items()
                self.refresh_notes_list()
                combo.clear()
                combo.addItems(sorted(self.get_all_tags()))
                if self.current_note:
                    self.tags_label.setText(
                        f"Теги: {', '.join(self.current_note.tags) if self.current_note.tags else 'нет'}"
                    )

        def delete_tag():
            tag_to_delete = combo.currentText()
            if not tag_to_delete:
                return
            reply = QMessageBox.question(
                dialog,
                "Удалить тег?",
                f"Удалить тег '{tag_to_delete}' из всех заметок?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                for note in self.notes:
                    if tag_to_delete in note.tags:
                        note.tags.remove(tag_to_delete)
                self.save_all_notes_to_disk()
                self.update_tag_filter_items()
                self.refresh_notes_list()
                combo.clear()
                combo.addItems(sorted(self.get_all_tags()))
                if self.current_note:
                    self.tags_label.setText(
                        f"Теги: {', '.join(self.current_note.tags) if self.current_note.tags else 'нет'}"
                    )

        rename_btn.clicked.connect(rename_tag)
        delete_btn.clicked.connect(delete_tag)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        layout.addWidget(buttons)
        buttons.rejected.connect(dialog.reject)
        dialog.setLayout(layout)
        dialog.exec()

    def get_all_tags(self) -> list[str]:
        tags: set[str] = set()
        for note in self.notes:
            tags.update(note.tags)
        return sorted(tags)

    def show_all_notes(self) -> None:
        self.refresh_notes_list()

    def show_notes_by_tag(self, tag: str) -> None:
        self.notes_list.clear()
        for note in self.notes:
            if tag in note.tags:
                timestamp = QDateTime.fromString(note.timestamp, Qt.ISODate)
                date_str = timestamp.toString("dd.MM.yyyy")
                reminder_symbol = " 🔔" if note.reminder else ""
                item_text = f"{note.title} — {date_str}{reminder_symbol}"
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, note)
                item.setFont(QFont("Segoe UI Emoji", 10))
                if note.favorite:
                    item.setForeground(QColor("gold"))
                self.notes_list.addItem(item)

    def apply_tag_filter(self) -> None:
        selected_tag = self.tag_filter.currentText()
        if selected_tag == "Все теги" or not selected_tag:
            self.show_all_notes()
        else:
            self.show_notes_by_tag(selected_tag)

    def _rebuild_attachments_panel(self, note: Note | None) -> None:
        if hasattr(self, "attachments_layout"):
            for i in reversed(range(self.attachments_layout.count())):
                w = self.attachments_layout.itemAt(i).widget()
                if w:
                    w.setParent(None)
                    w.deleteLater()
        if not note:
            self.attachments_scroll.setVisible(False)
            return
        note_dir = os.path.join(
            NOTES_DIR, NotesApp.safe_folder_name(note.title, note.uuid, note.timestamp)
        )
        attachments_found = False
        if os.path.isdir(note_dir):
            ignored_files = {"note.json", ".DS_Store", "Thumbs.db"}
            ignored_prefixes = ("~$", ".~")
            ignored_suffixes = ("~", ".tmp", ".temp")
            for filename in os.listdir(note_dir):
                if (
                    filename in ignored_files
                    or filename.startswith(ignored_prefixes)
                    or filename.endswith(ignored_suffixes)
                ):
                    continue
                attachments_found = True
                file_path = os.path.join(note_dir, filename)
                item_widget = QWidget()
                layout = QHBoxLayout(item_widget)
                icon_label = QLabel()
                if filename.lower().endswith(tuple(IMAGE_EXTENSIONS)):
                    pixmap = QPixmap(file_path)
                    icon_label.setPixmap(
                        pixmap.scaled(
                            48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation
                        )
                    )
                else:
                    if os.path.exists(FILE_ICON_PATH):
                        icon_label.setPixmap(
                            QPixmap(FILE_ICON_PATH).scaled(
                                48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation
                            )
                        )
                    else:
                        icon_label.setPixmap(
                            self.style().standardIcon(QStyle.SP_FileIcon).pixmap(32, 32)
                        )
                layout.addWidget(icon_label)
                label = QLabel(filename)
                label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                layout.addWidget(label)
                open_btn = QPushButton("Открыть")
                open_btn.setToolTip("Открыть вложение")
                open_btn.setFixedSize(60, 24)
                open_btn.clicked.connect(
                    lambda _, path=file_path: self.text_edit._open_any_link(path)
                )
                layout.addWidget(open_btn)
                del_btn = QPushButton("❌")
                del_btn.setToolTip("Удалить вложение")
                del_btn.setFixedSize(28, 24)
                del_btn.clicked.connect(
                    lambda _, path=file_path: self.delete_attachment_from_panel(path)
                )
                layout.addWidget(del_btn)
                self.attachments_layout.addWidget(item_widget)
        self.attachments_scroll.setVisible(attachments_found)

    def insert_link(self) -> None:
        cursor = self.text_edit.textCursor()
        url, ok = QInputDialog.getText(self, "Вставить ссылку", "URL:")
        if not (ok and url):
            return
        url = url.strip()
        href = url
        if os.path.isabs(url) or os.path.exists(url):
            href = QUrl.fromLocalFile(os.path.abspath(url)).toString()
        else:
            if not re.match(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://", url):
                href = "https://" + url
        fmt = QTextCharFormat()
        fmt.setAnchor(True)
        fmt.setAnchorHref(href)
        fmt.setForeground(Qt.blue)
        fmt.setFontUnderline(True)
        if cursor.hasSelection() and cursor.selectedText().strip():
            cursor.mergeCharFormat(fmt)
        else:
            cursor.insertHtml(f'<a href="{href}">{url}</a>')

        def _select_entire_anchor(self, cursor: QTextCursor) -> QTextCursor | None:
            fmt = cursor.charFormat()
            if not fmt.isAnchor():
                return None
            href = fmt.anchorHref()
            c = QTextCursor(cursor)
            max_steps = cursor.document().characterCount() + 5
            steps = 0
            while steps < max_steps:
                steps += 1
                left = QTextCursor(c)
                moved = left.movePosition(QTextCursor.Left, QTextCursor.KeepAnchor, 1)
                if (not moved) or left.atStart():
                    break
                f = left.charFormat()
                if not (f.isAnchor() and f.anchorHref() == href):
                    break
                if left.position() == c.position() and left.anchor() == c.anchor():
                    break
                c = left
            while steps < max_steps:
                steps += 1
                right = QTextCursor(c)
                moved = right.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, 1)
                if (not moved) or right.atEnd():
                    break
                f = right.charFormat()
                if not (f.isAnchor() and f.anchorHref() == href):
                    break
                if right.position() == c.position() and right.anchor() == c.anchor():
                    break
                c = right
            return c

    def edit_link(self) -> None:
        cursor = self.text_edit.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.WordUnderCursor)
        if not cursor.charFormat().isAnchor():
            QMessageBox.information(self, "Ссылка", "Курсор не находится на ссылке.")
            return
        full = self._select_entire_anchor(cursor)
        if not full:
            return
        fmt = full.charFormat()
        old_url = fmt.anchorHref()
        new_url, ok = QInputDialog.getText(
            self, "Изменить ссылку", "URL:", text=old_url
        )
        if not (ok and new_url):
            return
        visible = full.selectedText()
        if visible.strip() == old_url.strip() or re.match(
            r"^\s*(https?://|www\.)", visible, flags=re.I
        ):
            new_visible = new_url
        else:
            new_visible = visible
        fmt.setAnchor(True)
        fmt.setAnchorHref(new_url)
        full.insertText(new_visible, fmt)

    def remove_link(self) -> None:
        cursor = self.text_edit.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.WordUnderCursor)
        fmt = QTextCharFormat(cursor.charFormat())
        fmt.setAnchor(False)
        fmt.setAnchorHref("")
        fmt.setForeground(self.text_edit.palette().text())
        fmt.setFontUnderline(False)
        cursor.mergeCharFormat(fmt)

    def insert_table(self):
        rows, ok1 = QInputDialog.getInt(
            self, "Вставить таблицу", "Количество строк:", 2, 1, 100
        )
        cols, ok2 = QInputDialog.getInt(
            self, "Вставить таблицу", "Количество столбцов:", 2, 1, 100
        )
        if ok1 and ok2:
            is_dark = self.settings.value("theme", "dark") == "dark"
            border_color = "white" if is_dark else "black"

            html = f"<table border='1' cellspacing='0' cellpadding='3' style='border-collapse:collapse; border: 1px solid {border_color};'>"
            for _ in range(rows):
                html += "<tr>"
                for _ in range(cols):
                    html += f"<td style='min-width:1em; padding:3px; border: 1px solid {border_color};'>&nbsp;</td>"
                html += "</tr>"
            html += "</table>"
            self.text_edit.insertHtml(html)

    def insert_dropdown(self) -> None:
        if not self.current_note:
            QMessageBox.warning(
                self, "Нет заметки", "Сначала выбери или создай заметку."
            )
            return
        values = self._load_dropdown_values()
        initial = values[0] if values else "Выбрать…"
        dd_id = self._insert_dropdown_token(initial, values=values)
        cr = self.text_edit.cursorRect(self.text_edit.textCursor())
        pos = self.text_edit.viewport().mapToGlobal(cr.bottomLeft())
        self.show_dropdown_menu_for_token(dd_id, pos)

    def _open_dropdown_values_editor(
        self, initial_values: list[str] | None = None
    ) -> list[str] | None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Значения выпадающего списка")
        v = QVBoxLayout(dlg)
        lst = QListWidget(dlg)
        v.addWidget(lst)
        if initial_values is None:
            try:
                last = json.loads(self.settings.value("dropdown_values", "[]"))
                if not isinstance(last, list):
                    last = []
            except Exception:
                last = []
            if not last:
                last = ["Вариант 1", "Вариант 2", "Вариант 3"]
        else:
            last = (
                list(initial_values)
                if initial_values
                else ["Вариант 1", "Вариант 2", "Вариант 3"]
            )
        for s in last:
            lst.addItem(str(s))
        btns_line = QHBoxLayout()
        btn_add = QPushButton("Добавить")
        btn_ren = QPushButton("Переименовать")
        btn_del = QPushButton("Удалить")
        btn_up = QPushButton("↑")
        btn_dn = QPushButton("↓")
        btns_line.addWidget(btn_add)
        btns_line.addWidget(btn_ren)
        btns_line.addWidget(btn_del)
        btns_line.addStretch(1)
        btns_line.addWidget(btn_up)
        btns_line.addWidget(btn_dn)
        v.addLayout(btns_line)

        def add_item():
            text, ok = QInputDialog.getText(dlg, "Добавить значение", "Текст:")
            if ok and text.strip():
                lst.addItem(text.strip())

        def rename_item():
            it = lst.currentItem()
            if not it:
                return
            text, ok = QInputDialog.getText(
                dlg, "Переименовать", "Текст:", text=it.text()
            )
            if ok and text.strip():
                it.setText(text.strip())

        def delete_item():
            row = lst.currentRow()
            if row >= 0:
                lst.takeItem(row)

        def move_up():
            row = lst.currentRow()
            if row > 0:
                it = lst.takeItem(row)
                lst.insertItem(row - 1, it)
                lst.setCurrentRow(row - 1)

        def move_dn():
            row = lst.currentRow()
            if 0 <= row < lst.count() - 1:
                it = lst.takeItem(row)
                lst.insertItem(row + 1, it)
                lst.setCurrentRow(row + 1)

        btn_add.clicked.connect(add_item)
        btn_ren.clicked.connect(rename_item)
        btn_del.clicked.connect(delete_item)
        btn_up.clicked.connect(move_up)
        btn_dn.clicked.connect(move_dn)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dlg)
        v.addWidget(buttons)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        fg = dlg.frameGeometry()
        fg.moveCenter(self.frameGeometry().center())
        dlg.move(fg.topLeft())
        if dlg.exec() == QDialog.Accepted:
            values = [
                lst.item(i).text().strip()
                for i in range(lst.count())
                if lst.item(i).text().strip()
            ]
            if initial_values is None:
                self.settings.setValue(
                    "dropdown_values", json.dumps(values, ensure_ascii=False)
                )
            return values
        return None

    def _show_combo_popup(self, values: list[str]) -> None:
        menu = QMenu(self)
        fm = self.text_edit.fontMetrics()
        w = (
            max([180] + [fm.horizontalAdvance(v) for v in values])
            + fm.averageCharWidth() * 3
        )
        menu.setFixedWidth(int(w))
        for val in values:
            act = menu.addAction(val)
            act.triggered.connect(lambda _, v=val: self._insert_dropdown_plain(v))
        cr = self.text_edit.cursorRect(self.text_edit.textCursor())
        pos = self.text_edit.viewport().mapToGlobal(cr.bottomLeft())
        menu.exec(pos)

    def _insert_dropdown_plain(self, value: str) -> None:
        fmt = self.text_edit.currentCharFormat()
        c = self.text_edit.textCursor()
        c.insertText(value, fmt)
        self.text_edit.setTextCursor(c)
        self.record_state_for_undo()
        if hasattr(self, "debounce_timer"):
            self.debounce_timer.start(self.debounce_ms)

    def _commit_dropdown_value(self, combo: QComboBox, value: str) -> None:
        fmt = self.text_edit.currentCharFormat()
        cursor = self.text_edit.textCursor()
        cursor.insertText(value, fmt)
        self.text_edit.setTextCursor(cursor)
        combo.hide()
        self.record_state_for_undo()
        if hasattr(self, "debounce_timer"):
            self.debounce_timer.start(self.debounce_ms)

    def _insert_dropdown_plain(self, value: str) -> None:
        fmt = self.text_edit.currentCharFormat()
        c = self.text_edit.textCursor()
        c.insertText(value, fmt)
        self.text_edit.setTextCursor(c)
        self.record_state_for_undo()
        if hasattr(self, "debounce_timer"):
            self.debounce_timer.start(self.debounce_ms)

    def init_toolbar(self):
        full_toolbar_widget = QWidget()
        full_layout = QVBoxLayout(full_toolbar_widget)
        full_layout.setContentsMargins(0, 0, 0, 0)
        full_layout.setSpacing(0)
        top_toolbar_widget = QWidget()
        flow_layout = FlowLayout(top_toolbar_widget)

        def add_tool_button(icon_path, tooltip, callback):
            button = QPushButton()
            button.setText(tooltip.split()[0])
            button.setToolTip(tooltip)
            button.clicked.connect(callback)
            button.setFixedSize(32, 32)
            flow_layout.addWidget(button)

        def flow_break():
            br = QWidget()
            br.setProperty("flow_break", True)
            br.setFixedSize(0, 0)
            flow_layout.addWidget(br)

        toggle_fav_button = QPushButton("⭐")
        toggle_fav_button.setToolTip("⭐ - Добавить/удалить из избранного")
        toggle_fav_button.setFixedSize(32, 32)
        toggle_fav_button.clicked.connect(self.toggle_favorite)
        flow_layout.addWidget(toggle_fav_button)
        add_tool_button("", "🗑 - Корзина", self.show_trash)
        add_tool_button("", "📒 - Заметки", self.show_all_notes)
        add_tool_button("", "🔄 - Обновить", self.refresh_notes_list)
        add_tool_button("", "➕ - Новая", self.create_new_note)
        add_tool_button("", "💾 - Сохранить", self.save_note)
        add_tool_button("📎", "📎 - Приерепить файл", self.attach_file_to_note)
        self.audio_button = QPushButton("🎤")
        self.audio_button.setToolTip("🎤 - Записать аудио")
        self.audio_button.setFixedSize(32, 32)
        self.audio_button.clicked.connect(self.toggle_audio_recording)
        flow_layout.addWidget(self.audio_button)
        add_tool_button("", "𝐁 - Жирный", self.toggle_bold)
        add_tool_button("", "𝐼 - Курсив", self.toggle_italic)
        add_tool_button("", "U̲ - Подчёркнутый", self.toggle_underline)
        add_tool_button("", "̶̶̶Z - Зачеркнуть", self.toggle_strikethrough)
        add_tool_button("", "🔽 - Выпадающий список", self.insert_dropdown)
        add_tool_button("", "🧹 - Сбросить формат", self.clear_formatting)
        add_tool_button("", "🌈 - Цвет текста", self.change_text_color)
        add_tool_button("", "🅰️ - Фон текста", self.change_background_color)
        add_tool_button("", "← - Расположить слева", self.align_left)
        add_tool_button("", "→← - Расположить по центру", self.align_center)
        add_tool_button("", "→ - Расположить справа", self.align_right)
        add_tool_button("", "≡ - По ширине", self.align_justify)
        add_tool_button("", "H1 - Заголовок 1", lambda: self.apply_heading(1))
        add_tool_button("", "H2 - Заголовок 2", lambda: self.apply_heading(2))
        add_tool_button("", "H3 - Заголовок 3", lambda: self.apply_heading(3))
        add_tool_button("", "Aa - Изменить регистр", self.toggle_case)
        add_tool_button("", "• - Маркированный  список", self.insert_bullet_list)
        add_tool_button("", "1. - Нумерованный список", self.insert_numbered_list)
        add_tool_button("", "☑ - Чекбокс", self.insert_checkbox)
        add_tool_button("", "📅 - Таблица", self.insert_table)
        add_tool_button("", "🔗 - Ссылка", self.insert_link)
        add_tool_button("", "❌ - Удалить ссылку", self.remove_link)
        add_tool_button("", "▁ - Горизонтальная линия", self.insert_horizontal_line)
        add_tool_button("", "+🏷 - Добавить тег", self.add_tag_to_note)
        self.tag_filter = QComboBox()
        self.tag_filter.setEditable(False)
        self.tag_filter.setFixedWidth(180)
        self.update_tag_filter_items()
        flow_layout.addWidget(self.tag_filter)
        manage_tags_button = QPushButton("🏷")
        manage_tags_button.setToolTip("Управление тегами")
        manage_tags_button.clicked.connect(self.manage_tags_dialog)
        flow_layout.addWidget(manage_tags_button)
        favorites_button = QPushButton("★Избранные")
        favorites_button.clicked.connect(self.show_favorites_only)
        flow_layout.addWidget(favorites_button)
        reset_button = QPushButton("Сбросить фильтр")
        reset_button.clicked.connect(self.refresh_notes_list)
        flow_layout.addWidget(reset_button)
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["По заголовку", "По дате", "Избранные"])
        self.sort_combo.setToolTip("Сортировка")
        self.sort_combo.currentIndexChanged.connect(self.apply_sorting)
        flow_layout.addWidget(self.sort_combo)
        self.sort_order_combo = QComboBox()
        self.sort_order_combo.addItems(["↑", "↓"])
        self.sort_order_combo.setToolTip("Порядок сортировки")
        self.sort_order_combo.currentIndexChanged.connect(self.apply_sorting)
        flow_layout.addWidget(self.sort_order_combo)
        self.search_mode_combo = QComboBox()
        self.search_mode_combo.addItems(["Заголовок", "Содержимое", "Напоминание"])
        flow_layout.addWidget(self.search_mode_combo)
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Поиск...")
        flow_layout.addWidget(self.search_bar)
        search_button = QPushButton("🔍 - Поиск")
        search_button.clicked.connect(self.trigger_search)
        flow_layout.addWidget(search_button)
        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentFont(QFont("Times New Roman"))
        self.font_combo.currentFontChanged.connect(self.change_font)
        flow_layout.addWidget(self.font_combo)
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 48)
        self.font_size_spin.setValue(14)
        self.font_size_spin.valueChanged.connect(self.change_font_size)
        flow_layout.addWidget(self.font_size_spin)
        reminder_layout = QHBoxLayout()
        reminder_layout.setContentsMargins(0, 0, 0, 0)
        reminder_layout.setSpacing(10)
        reminder_button = QPushButton("Установить напоминание")
        reminder_button.clicked.connect(self.set_reminder_for_note)
        edit_reminder_button = QPushButton("Изменить напоминание")
        edit_reminder_button.clicked.connect(self.edit_reminder_for_note)
        remove_reminder_button = QPushButton("Удалить напоминание")
        remove_reminder_button.clicked.connect(self.remove_reminder_from_note)
        reminder_layout.addWidget(reminder_button)
        reminder_layout.addWidget(edit_reminder_button)
        reminder_layout.addWidget(remove_reminder_button)
        bottom_toolbar_widget = QWidget()
        bottom_toolbar_widget.setLayout(reminder_layout)
        full_layout.addWidget(top_toolbar_widget)
        self.toolbar_scroll = QScrollArea()
        self.toolbar_scroll.setWidget(full_toolbar_widget)
        self.toolbar_scroll.setWidgetResizable(True)
        self.toolbar_scroll.setMaximumHeight(140)
        self.toolbar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.toolbar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.search_bar.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    def open_mass_reminders_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        dialog.setWindowTitle("Массовое управление напоминаниями")
        layout = QVBoxLayout(dialog)
        list_widget = QListWidget()
        notes_with_reminder = [n for n in self.notes if n.reminder]
        for note in notes_with_reminder:
            item = QListWidgetItem(f"{note.title} [{note.reminder}]")
            item.setData(Qt.UserRole, note)
            item.setCheckState(Qt.Unchecked)
            list_widget.addItem(item)
        layout.addWidget(list_widget)
        btn_remove = QPushButton("Удалить напоминание у выбранных")
        btn_remove.clicked.connect(
            lambda _=False, lw=list_widget, dlg=dialog: self.mass_remove_reminders(lw, dlg)
        )
        layout.addWidget(btn_remove)
        dialog.setLayout(layout)
        dialog.exec()

    def mass_remove_reminders(self, list_widget, dialog):
        changed = False
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            note = item.data(Qt.UserRole)
            if item.checkState() == Qt.Checked:
                note.reminder = None
                note.reminder_repeat = None
                self.save_note_to_file(note)
                changed = True
        if changed:
            self.refresh_notes_list()
            dialog.accept()

    def rebuild_toolbar(self):
        dock = getattr(self, "dock_toolbar", None)
        was_visible = bool(dock and dock.isVisible())
        area = self.dockWidgetArea(dock) if dock else Qt.TopDockWidgetArea
        old_scroll = getattr(self, "toolbar_scroll", None)
        if old_scroll is not None:
            try:
                old_scroll.setParent(None)
                old_scroll.deleteLater()
            except Exception:
                pass
        self.init_toolbar()
        if dock is None:
            self.dock_toolbar = QDockWidget("Панель инструментов", self)
            self.dock_toolbar.setObjectName("dock_toolbar")
            self.dock_toolbar.setAllowedAreas(
                Qt.TopDockWidgetArea | Qt.BottomDockWidgetArea
            )
            self.addDockWidget(area, self.dock_toolbar)
            dock = self.dock_toolbar
        dock.setWidget(self.toolbar_scroll)
        dock.setVisible(was_visible)

    def show_reminder_dialog(self, note):
        time_str = ""
        if note.reminder:
            dt = QDateTime.fromString(note.reminder, Qt.ISODate)
            if dt.isValid():
                time_str = dt.toString("dd.MM.yyyy HH:mm")
        text = f"<b>Напоминание по заметке:</b><br><b>{note.title}</b>"
        if time_str:
            text += f"<br><b>Время:</b> {time_str}"
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("Напоминание")
        msg.setTextFormat(Qt.RichText)
        msg.setText(text)
        msg.setStandardButtons(QMessageBox.Ok)
        msg.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        msg.exec()
        note.reminder_shown = True

    def show_note_context_menu(self, position):
        item = self.notes_list.itemAt(position)
        if not item:
            menu = QMenu(self)
            create_action = QAction("Создать", self)
            create_action.triggered.connect(self.create_new_note)
            menu.addAction(create_action)
            menu.exec(self.notes_list.viewport().mapToGlobal(position))
            return
        note = item.data(Qt.UserRole)
        menu = QMenu()
        menu.setStyleSheet(
            """
            QMenu {
                background-color: #282828;
                color: #fff;
                border-radius: 10px;
                font-size: 16px;
                padding: 6px;
            }
            QMenu::item {
                background-color: transparent;
                color: #fff;
                padding: 8px 32px 8px 24px;
                border-radius: 6px;
            }
            QMenu::item:selected {
                background-color: #fff;
                color: #111;
                border-radius: 6px;
                border: 2px solid #7a7a7a;
            }
            QMenu::separator {
                height: 1px;
                background: #444;
                margin: 8px 0;
            }
            """
        )
        toggle_pin_action = QAction(
            "Закрепить" if not note.pinned else "Открепить", self
        )
        toggle_pin_action.triggered.connect(lambda: self.toggle_pin(note))
        menu.addAction(toggle_pin_action)
        open_action = QAction("Открыть", self)
        open_action.triggered.connect(lambda: self.select_note(note))
        menu.addAction(open_action)
        open_in_fs_action = QAction("Открыть в проводнике", self)
        open_in_fs_action.triggered.connect(lambda: self.open_note_folder(note))
        menu.addAction(open_in_fs_action)
        rename_action = QAction("Переименовать", self)
        rename_action.triggered.connect(lambda: self.rename_note(note))
        menu.addAction(rename_action)
        copy_action = QAction("Копировать", self)
        copy_action.triggered.connect(lambda: self.copy_note(note))
        menu.addAction(copy_action)
        menu.addSeparator()
        delete_perm_action = QAction("Удалить безвозвратно", self)
        delete_perm_action.triggered.connect(lambda: self.delete_note_completely(note))
        menu.addAction(delete_perm_action)
        note_folder_name = NotesApp.safe_folder_name(
            note.title, note.uuid, note.timestamp
        )
        note_in_trash = os.path.exists(os.path.join(self.TRASH_DIR, note_folder_name))
        if note_in_trash:
            delete_action = QAction("Удалить навсегда", self)

            def delete_permanently():
                reply = QMessageBox.question(
                    self,
                    "Удалить навсегда",
                    f"Удалить заметку '{note.title}' безвозвратно?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if reply == QMessageBox.Yes:
                    trash_note_dir = os.path.join(self.TRASH_DIR, note_folder_name)
                    if os.path.exists(trash_note_dir):
                        shutil.rmtree(trash_note_dir)
                    self.refresh_notes_list()

            delete_action.triggered.connect(delete_permanently)
            menu.addAction(delete_action)
        else:
            delete_action = QAction("Удалить", self)

            def move_to_trash():
                reply = QMessageBox.question(
                    self,
                    "Удаление",
                    f"Переместить заметку '{note.title}' в корзину?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if reply == QMessageBox.Yes:
                    self.move_note_to_trash(note)
                    self.refresh_notes_list()
                    self.load_note(None)
                    self.current_note = None

            delete_action.triggered.connect(move_to_trash)
            menu.addAction(delete_action)
        menu.exec(self.notes_list.viewport().mapToGlobal(position))

    def autosave(self) -> None:
        if self.current_note and not self.text_edit.isReadOnly():
            current_html = self.text_edit.toHtml()
            last_html = (
                self.current_note.history[-1] if self.current_note.history else ""
            )
            if current_html != last_html:
                if len(self.current_note.history) >= MAX_HISTORY:
                    self.current_note.history.pop(0)
                self.current_note.history.append(current_html)
                self.current_note.history_index = len(self.current_note.history) - 1
                self.update_history_list()
                self.update_history_list_selection()
            self.current_note.content = current_html
            self.current_note.password_manager = self.password_manager_field.text()
            self.current_note.rdp_1c8 = self.rdp_1c8_field.text()
            self.save_note_to_file(self.current_note)

    def attach_docks(self, dock1, dock2):
        area = self.dockWidgetArea(dock1)
        self.addDockWidget(area, dock2)
        self.tabifyDockWidget(dock1, dock2)
        dock2.show()
        dock1.raise_()

    def detach_dock(self, dock):
        dock.setFloating(True)
        dock.show()

    def move_dock(self, dock, area):
        self.addDockWidget(area, dock)
        dock.show()
        dock.raise_()

    def show_dock_context_menu(self, position, dock):
        menu = QMenu()
        attach_menu = menu.addMenu("Приклеить к...")
        docks = [
            (self.dock_notes_list, "Заметки"),
            (self.dock_history, "История"),
            (self.dock_buttons, "Кнопки"),
            (self.dock_editor, "Редактор"),
            (self.dock_toolbar, "Панель инструментов"),
        ]
        for target_dock, name in docks:
            if target_dock != dock:
                action = attach_menu.addAction(name)
                action.triggered.connect(
                    lambda checked, d1=target_dock, d2=dock: self.attach_docks(d1, d2)
                )

        move_menu = menu.addMenu("Переместить к краю")
        areas = [
            (Qt.LeftDockWidgetArea, "Слева"),
            (Qt.RightDockWidgetArea, "Справа"),
            (Qt.TopDockWidgetArea, "Сверху"),
            (Qt.BottomDockWidgetArea, "Снизу"),
        ]
        for area, name in areas:
            move_action = move_menu.addAction(name)
            move_action.triggered.connect(
                lambda checked, a=area, d=dock: self.move_dock(d, a)
            )
        detach_action = menu.addAction("Открепить")
        detach_action.triggered.connect(lambda: self.detach_dock(dock))
        menu.exec(dock.mapToGlobal(position))

    def clear_formatting(self):
        cursor = self.text_edit.textCursor()
        palette = self.text_edit.palette()
        default_text_color = palette.color(QPalette.Text)
        if cursor.hasSelection():
            selected_text = cursor.selectedText()
            fmt = QTextCharFormat()
            fmt.setFontWeight(QFont.Normal)
            fmt.setFontItalic(False)
            fmt.setFontUnderline(False)
            fmt.setFontStrikeOut(False)
            fmt.setForeground(default_text_color)
            fmt.clearBackground()
            fmt.setFontPointSize(14)
            block_fmt = QTextBlockFormat()
            block_fmt.setHeadingLevel(0)
            cursor.mergeBlockFormat(block_fmt)
            cursor.insertText(selected_text, fmt)
        else:
            cursor.select(QTextCursor.WordUnderCursor)
            selected_text = cursor.selectedText()
            fmt = QTextCharFormat()
            fmt.setFontWeight(QFont.Normal)
            fmt.setFontItalic(False)
            fmt.setFontUnderline(False)
            fmt.setFontStrikeOut(False)
            fmt.setForeground(default_text_color)
            fmt.clearBackground()
            fmt.setFontPointSize(14)
            block_fmt = QTextBlockFormat()
            block_fmt.setHeadingLevel(0)
            cursor.mergeBlockFormat(block_fmt)
            cursor.insertText(selected_text, fmt)

    def toggle_pin(self, note):
        note.pinned = not note.pinned
        self.save_note_to_file(note)
        self.refresh_notes_list()

    def add_menu_bar(self):
        menu_bar = self.menuBar()
        plugins_menu = menu_bar.addMenu("Плагины")
        act = QAction("Управление плагинами", self)
        act.triggered.connect(self.manage_plugins_dialog)
        plugins_menu.addAction(act)
        act = QAction("Перезагрузить плагины", self)
        act.triggered.connect(self.load_plugins)
        plugins_menu.addAction(act)
        template_menu = self.menuBar().addMenu("Шаблоны")
        act = QAction("Вставить шаблон", self)
        act.triggered.connect(self.insert_template)
        template_menu.addAction(act)
        act = QAction("Сохранить как шаблон", self)
        act.setShortcut("Ctrl+Shift+S")
        act.triggered.connect(self.save_current_as_template)
        template_menu.addAction(act)
        act = QAction("Управление шаблонами", self)
        act.triggered.connect(self.manage_templates_dialog)
        template_menu.addAction(act)
        file_menu = menu_bar.addMenu("Файл")
        act = QAction("Импорт", self)
        act.triggered.connect(self.import_note)
        file_menu.addAction(act)
        act = QAction("Экспорт в PDF", self)
        act.triggered.connect(self.export_current_note_pdf)
        file_menu.addAction(act)
        act = QAction("Экспорт в TXT", self)
        act.triggered.connect(self.export_current_note_txt)
        file_menu.addAction(act)
        act = QAction("Экспорт в DOCX", self)
        act.triggered.connect(self.export_current_note_docx)
        file_menu.addAction(act)
        act = QAction("Экспорт в JSON", self)
        act.triggered.connect(self.export_note)
        file_menu.addAction(act)
        help_menu = menu_bar.addMenu("Справка")
        act = QAction("Открыть README.md", self)
        act.triggered.connect(self.open_readme)
        help_menu.addAction(act)
        settings_menu = menu_bar.addMenu("Настройки")
        settings_action = QAction("Настройки:", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self.show_settings_window)
        settings_menu.addAction(settings_action)
        self.view_menu = menu_bar.addMenu("Вид")
        for dock in [
            self.dock_notes_list,
            self.dock_history,
            self.dock_buttons,
            self.dock_editor,
        ]:
            action = dock.toggleViewAction()
            action.setText(dock.windowTitle())
            self.view_menu.addAction(action)
        self.toolbars_menu = self.view_menu.addMenu("Панели инструментов")
        dock_action = self.dock_toolbar.toggleViewAction()
        dock_action.setText(self.dock_toolbar.windowTitle() or "Панель инструментов")
        self.toolbars_menu.addAction(dock_action)
        if hasattr(self, "visibility_toolbar") and isinstance(
            self.visibility_toolbar, QToolBar
        ):
            tb_action = self.visibility_toolbar.toggleViewAction()
            tb_action.setText(
                self.visibility_toolbar.windowTitle() or "Видимость полей"
            )
            self.toolbars_menu.addAction(tb_action)
        trash_menu = self.menuBar().addMenu("Корзина")
        act = QAction("Показать корзину", self)
        act.triggered.connect(self.show_trash)
        trash_menu.addAction(act)
        act = QAction("Восстановить заметку", self)
        act.triggered.connect(self.restore_note_from_trash)
        trash_menu.addAction(act)
        act = QAction("Удалить безвозвратно", self)
        act.triggered.connect(self.delete_note_permanently)
        trash_menu.addAction(act)
        act = QAction("Очистить корзину", self)
        act.triggered.connect(self.empty_trash)
        trash_menu.addAction(act)
        reminders_menu = menu_bar.addMenu("Управление напоминаниями")
        act = QAction("Добавить напоминание к текущей заметки", self)
        act.triggered.connect(self.set_reminder_for_note)
        reminders_menu.addAction(act)
        act = QAction("Изменить напоминание у текущей заметки", self)
        act.triggered.connect(self.edit_reminder_for_note)
        reminders_menu.addAction(act)
        act = QAction("Удалить напоминание у текущей заметки", self)
        act.triggered.connect(self.remove_reminder_from_note)
        reminders_menu.addAction(act)
        reminders_menu.addSeparator()
        act = QAction("Массовое удаление", self)
        act.triggered.connect(self.open_mass_reminders_dialog)
        reminders_menu.addAction(act)

    def show_settings_window(self):
        dialog = QDialog(self)
        dialog.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        dialog.setWindowTitle("Настройки")
        layout = QFormLayout(dialog)
        theme_combo = QComboBox()
        theme_combo.addItems(["Светлая", "Тёмная"])
        theme_combo.setCurrentIndex(
            0 if self.settings.value("theme", "dark") == "light" else 1
        )
        layout.addRow("Тема:", theme_combo)
        autosave_checkbox = QCheckBox()
        autosave_checkbox.setChecked(self.autosave_enabled)
        layout.addRow("Автосохранение:", autosave_checkbox)
        interval_spinbox = QSpinBox()
        interval_spinbox.setRange(1, 120)
        interval_spinbox.setSuffix(" сек")
        interval_spinbox.setValue(self.autosave_interval // 1000)
        layout.addRow("Интервал автосохранения:", interval_spinbox)
        interval_spinbox.setEnabled(autosave_checkbox.isChecked())
        autosave_checkbox.toggled.connect(interval_spinbox.setEnabled)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.setLayout(layout)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_theme = "light" if theme_combo.currentIndex() == 0 else "dark"
            self.settings.setValue("theme", new_theme)
            self.autosave_enabled = autosave_checkbox.isChecked()
            self.autosave_interval = interval_spinbox.value() * 1000
            self.settings.setValue("autosave_enabled", self.autosave_enabled)
            self.settings.setValue("autosave_interval", self.autosave_interval)
            if self.autosave_enabled:
                self.autosave_timer.start(self.autosave_interval)
            else:
                self.autosave_timer.stop()
                if hasattr(self, "debounce_timer"):
                    self.debounce_timer.stop()
            self.init_theme()

    def show_help_window(self):

        dialog = QDialog(self)
        dialog.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        dialog.setWindowTitle("Справка — Мои Заметки")
        dialog.setMinimumSize(600, 620)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser(dialog)
        browser.setOpenExternalLinks(True)
        browser.setHtml(
            """
                        <h2 style="text-align:center;">🗒️ Справка по приложению "Мои Заметки"</h2>

                        <h3>Основные возможности</h3>
                        <ul>
                        <li>Создание, редактирование, удаление и восстановление заметок</li>
                        <li>Форматирование текста (жирный, курсив, подчёркнутый, зачёркнутый, цвет, списки, чекбоксы, линии)</li>
                        <li>Прикрепление файлов и изображений, просмотр и удаление вложений</li>
                        <li>Вставка ссылок, аудиозаписей</li>
                        <li>Работа с тегами (создание, добавление, фильтрация, переименование, удаление)</li>
                        <li>История изменений и версий заметки</li>
                        <li>Корзина: перемещение, восстановление, удаление навсегда, очистка</li>
                        <li>Избранные и закреплённые заметки</li>
                        <li>Поиск, сортировка и фильтрация заметок</li>
                        <li>Напоминания с возможностью повторения</li>
                        <li>Экспорт заметок в PDF, TXT, DOCX</li>
                        </ul>

                        <h3>Горячие клавиши</h3>
                        <ul>
                        <li><b>Ctrl+N</b> — новая заметка</li>
                        <li><b>Ctrl+S</b> — сохранить заметку</li>
                        <li><b>Ctrl+B</b> — сделать текст жирным</li>
                        <li><b>Ctrl+I</b> — сделать текст курсивом</li>
                        <li><b>Ctrl+U</b> — подчеркнуть текст</li>
                        <li><b>Ctrl+Z</b> — отменить действие (Undo)</li>
                        <li><b>Ctrl+Y</b> — повторить действие (Redo)</li>
                        <li><b>Ctrl+Space</b> — сбросить форматирование выделенного текста</li>
                        <li><b>Ctrl+V</b> — вставить (текст, изображение из буфера обмена)</li>
                        <li><b>Delete</b> — удалить выделенную заметку (в корзину)</li>
                        <li><b>Esc</b> — выйти из режима редактирования заметки</li>
                        <li><b>Ctrl + Клик по картинке</b> — открыть изображение во внешней программе</li>
                        <li><b>ПКМ по заметке</b> — контекстное меню (открыть, удалить, переименовать, копировать, закрепить)</li>
                        </ul>

                        <h3>Форматирование и работа с текстом</h3>
                        <ul>
                        <li><b>𝐁</b> — жирный текст</li>
                        <li><b>𝐼</b> — курсив</li>
                        <li><b>U̲</b> — подчёркнутый</li>
                        <li><b>S̶</b> — зачёркнутый</li>
                        <li><b>🌈</b> — изменить цвет текста</li>
                        <li><b>🅰️</b> — изменить цвет фона текста</li>
                        <li><b>🧹</b> — сбросить всё форматирование</li>
                        <li><b>🔗</b> — вставить гиперссылку</li>
                        <li><b>•</b> — маркированный список</li>
                        <li><b>1.</b> — нумерованный список</li>
                        <li><b>☑</b> — чекбокс (флажок)</li>
                        <li><b>▁</b> — горизонтальная линия</li>
                        <li>Изменение размера и семейства шрифта — через панель инструментов сверху</li>
                        </ul>

                        <h3>Вложения, изображения и аудио</h3>
                        <ul>
                        <li><b>📎</b> — прикрепить файл к заметке</li>
                        <li><b>🖼</b> — вставить изображение (через меню или Ctrl+V)</li>
                        <li>Вложенные изображения и файлы отображаются под текстом заметки с кнопками "Открыть" и "Удалить"</li>
                        <li><b>🎤</b> — записать аудиофрагмент (отдельный файл, появится как вложение)</li>
                        </ul>

                        <h3>Работа с заметками</h3>
                        <ul>
                        <li>Новая, сохранить, удалить — через кнопки и горячие клавиши</li>
                        <li>Переименовать, копировать, закрепить — через контекстное меню</li>
                        <li>Закреплённые заметки отображаются выше</li>
                        <li>Избранное (⭐) — отметка заметки, быстрая фильтрация</li>
                        <li>Восстановление из корзины — через меню корзины</li>
                        </ul>

                        <h3>Корзина</h3>
                        <ul>
                        <li>Удалённые заметки перемещаются в корзину</li>
                        <li>В корзине можно восстановить заметку или удалить навсегда</li>
                        <li>Кнопка "Очистить корзину" — удаляет все заметки безвозвратно</li>
                        </ul>

                        <h3>Теги, фильтрация и сортировка</h3>
                        <ul>
                        <li>Теги отображаются под заголовком заметки</li>
                        <li>Добавление, удаление, переименование, фильтрация заметок по тегам</li>
                        <li>Строка поиска — фильтрация по заголовку, содержимому, тегам</li>
                        <li>Сортировка — по имени, дате, избранному (меню сортировки)</li>
                        <li>Быстрая фильтрация по тегам</li>
                        </ul>

                        <h3>История изменений</h3>
                        <ul>
                        <li>Для каждой заметки ведётся история версий (до 20 последних)</li>
                        <li>Можно откатываться к любой версии, удалять отдельные версии</li>
                        <li>История отображается в отдельной панели "История"</li>
                        </ul>

                        <h3>Напоминания</h3>
                        <ul>
                        <li>Можно задать напоминание для заметки (одноразовое или повторяющееся)</li>
                        <li>Время и периодичность задаются через форму напоминания</li>
                        <li>Сработавшее напоминание покажет уведомление, если приложение запущено</li>
                        </ul>

                        <h3>Экспорт</h3>
                        <ul>
                        <li>Заметку можно экспортировать в PDF, TXT или DOCX</li>
                        <li>Экспорт доступен через меню или кнопку экспорта</li>
                        </ul>

                        <h3>Прочее</h3>
                        <ul>
                        <li>Автосохранение изменений заметки каждые 60 секунд</li>
                        <li>Поддержка drag&amp;drop для вложений и заметок</li>
                        <li>Все данные хранятся локально в папке "Notes" рядом с программой</li>
                        <li>Удаление заметок и вложений из корзины — без возможности восстановления</li>
                        </ul>

                        <p style="font-size:11px; color:#888;">Обновлено: Август 2025</p>
                        """
        )
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(browser)
        layout.addWidget(close_btn)
        dialog.exec()

    def export_note(self):
        if not self.current_note:
            QMessageBox.warning(
                self, "Экспорт", "Сначала выберите заметку для экспорта."
            )
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Экспорт заметки",
            f"{self.current_note.title}.json",
            "JSON Files (*.json)",
        )
        if file_path:
            note_dict = self.current_note.to_dict()
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(note_dict, f, ensure_ascii=False, indent=4)
                QMessageBox.information(
                    self, "Экспорт", "Заметка успешно экспортирована."
                )
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Ошибка экспорта: {e}")

    def import_note(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Импорт заметки", "", "JSON Files (*.json)"
        )
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    note_data = json.load(f)
                note_data["uuid"] = str(uuid.uuid4())
                note_data["title"] += " (импорт)"
                imported_note = Note.from_dict(note_data)
                self.save_note_to_file(imported_note)
                self.load_notes_from_disk()
                self.refresh_notes_list()
                QMessageBox.information(
                    self, "Импорт", "Заметка успешно импортирована."
                )
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Ошибка импорта: {e}")
                self.deduplicate_notes()

    def delete_note_completely(self, note: Note) -> None:
        reply = QMessageBox.question(
            self,
            "Удалить навсегда",
            f"Безвозвратно удалить заметку '{note.title}'? Данные будут удалены полностью.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            note_dir = os.path.join(
                NOTES_DIR, NotesApp.safe_folder_name(note.title, note.uuid)
            )
            if os.path.exists(note_dir):
                shutil.rmtree(note_dir)
            self.notes = [n for n in self.notes if n.uuid != note.uuid]
            if self.current_note and self.current_note.uuid == note.uuid:
                self.current_note = None
                self.text_edit.clear()
                if hasattr(self, "history_list"):
                    self.history_list.clear()
                self.attachments_scroll.setVisible(False)
            self.refresh_notes_list()
            self.save_all_notes_to_disk()
            QMessageBox.information(
                self, "Удалено", f"Заметка '{note.title}' удалена безвозвратно."
            )

    def trigger_search(self):
        self.handle_combined_search()

    def check_reminders(self):
        now = QDateTime.currentDateTime()
        changed = False
        for note in self.notes:
            if note.reminder and not getattr(note, "reminder_shown", False):
                reminder_time = QDateTime.fromString(note.reminder, Qt.ISODate)
                if not reminder_time.isValid():
                    continue
                if reminder_time <= now:
                    self.show_reminder_dialog(note)
                    changed = True
                    repeat = (note.reminder_repeat or "").lower()
                    if repeat in ("once", "", None):
                        note.reminder = None
                        note.reminder_repeat = None
                    elif repeat == "workdays":
                        next_dt = reminder_time.addDays(1)
                        while next_dt.date().dayOfWeek() > 5:
                            next_dt = next_dt.addDays(1)
                        note.reminder = next_dt.toString(Qt.ISODate)
                        note.reminder_shown = False
                    elif repeat == "weekends":
                        next_dt = reminder_time.addDays(1)
                        while next_dt.date().dayOfWeek() < 6:
                            next_dt = next_dt.addDays(1)
                        note.reminder = next_dt.toString(Qt.ISODate)
                        note.reminder_shown = False
                    elif repeat == "daily":
                        next_dt = reminder_time.addDays(1)
                        note.reminder = next_dt.toString(Qt.ISODate)
                        note.reminder_shown = False
                    elif repeat == "weekly":
                        next_dt = reminder_time.addDays(7)
                        note.reminder = next_dt.toString(Qt.ISODate)
                        note.reminder_shown = False
                    elif repeat == "minutely":
                        next_dt = reminder_time.addSecs(60)
                        note.reminder = next_dt.toString(Qt.ISODate)
                        note.reminder_shown = False
                    elif repeat == "hourly":
                        next_dt = reminder_time.addSecs(3600)
                        note.reminder = next_dt.toString(Qt.ISODate)
                        note.reminder_shown = False
                    else:
                        note.reminder = None
                        note.reminder_repeat = None

        if changed:
            self.save_all_notes_to_disk()
            self.refresh_notes_list()

    def show_reminder_dialog(self, note):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("Напоминание")
        note_time = note.reminder or ""
        msg.setText(
            f"Напоминание по заметке:\n\n{note.title}\n\n"
            f"{QDateTime.fromString(note_time, Qt.ISODate).toString('dd.MM.yyyy HH:mm')}"
        )
        msg.setStandardButtons(QMessageBox.Ok)
        msg.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        msg.exec()
        note.reminder_shown = True

    def handle_combined_search(self):
        tag = self.tag_filter.currentText().strip().lower()
        if tag == "все теги":
            tag = ""
        text = self.search_bar.text().strip().lower()
        mode = self.search_mode_combo.currentText()
        self.notes_list.clear()
        for note in self.notes:
            matches_tag = tag in [t.lower() for t in note.tags] if tag else True
            matches_search = False
            if mode == "Заголовок":
                matches_search = text in note.title.lower()
            elif mode == "Напоминание":
                matches_search = note.reminder and text in note.reminder.lower()
            elif mode == "Содержимое":
                doc = QTextDocument()
                doc.setHtml(note.content)
                plain_text = doc.toPlainText().lower()
                matches_search = text in plain_text
            elif not text:
                matches_search = True
            if matches_tag and matches_search:
                item = QListWidgetItem(note.title)
                item.setData(Qt.UserRole, note)
                if note.favorite:
                    item.setForeground(QColor("gold"))
                self.notes_list.addItem(item)

    def create_history_toolbar(self):
        toolbar = QToolBar("История версий", self)
        toolbar.setObjectName("history_toolbar")
        toolbar.addWidget(self.history_label)
        toolbar.addWidget(self.history_list)
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, toolbar)

    def list_attachments_for_current_note(self):
        if not self.current_note:
            return
        note_dir = os.path.join(NOTES_DIR, self.current_note.uuid)
        if not os.path.exists(note_dir):
            return
        attachments = []
        for file_name in os.listdir(note_dir):
            if file_name != "note.json":
                attachments.append(file_name)
        attachment_links = "\n".join(
            f'<a href="file://{os.path.abspath(os.path.join(note_dir, f))}">{f}</a>'
            for f in attachments
        )
        if attachment_links:
            cursor = self.text_edit.textCursor()
            html = "<br>--- Attachments ---<br>" + attachment_links.replace(
                "\n", "<br>"
            )
            cursor.insertHtml(html)
            self.text_edit.setTextCursor(cursor)

    def update_tag_filter_items(self):
        all_tags = sorted(self.get_all_tags())
        self.tag_filter.clear()
        self.tag_filter.addItem("Все теги")
        self.tag_filter.addItems(all_tags)

    def update_search_filter_items(self) -> None:
        if not hasattr(self, "search_mode_combo") or self.search_mode_combo is None:
            return

        modes = ["Заголовок", "Содержимое", "Напоминание"]
        self.search_mode_combo.blockSignals(True)
        self.search_mode_combo.clear()
        self.search_mode_combo.addItems(modes)
        self.search_mode_combo.blockSignals(False)

    def set_reminder_for_note(self):
        if not self.current_note:
            return
        dialog = QDialog(self)
        dialog.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        dialog.setWindowTitle("Установить напоминание")
        layout = QFormLayout(dialog)
        datetime_edit = QDateTimeEdit(QDateTime.currentDateTime())
        datetime_edit.setCalendarPopup(True)
        layout.addRow("Напоминание:", datetime_edit)
        repeat_combo = QComboBox()
        repeat_combo.addItems(
            ["Однократно", "По будням", "Каждый день", "Каждую неделю", "Каждый месяц"]
        )
        layout.addRow("Повторять:", repeat_combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            dt = datetime_edit.dateTime()
            self.current_note.reminder = dt.toString("yyyy-MM-dd HH:mm")
            self.save_note_to_file(self.current_note)
            self.refresh_notes_list()
            QMessageBox.information(
                self,
                "Напоминание установлено",
                f"Напоминание установлено на {self.current_note.reminder}",
            )
            repeat_option = repeat_combo.currentText()
            if repeat_option == "Однократно":
                self.current_note.reminder_repeat = None
            else:
                self.current_note.reminder_repeat = repeat_option

    def edit_reminder_for_note(self):
        if not self.current_note:
            QMessageBox.warning(self, "Нет заметки", "Сначала выберите заметку.")
            return
        dialog = QDialog(self)
        dialog.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        dialog.setWindowTitle("Изменить напоминание")
        layout = QFormLayout(dialog)
        if self.current_note.reminder:
            dt = QDateTime.fromString(self.current_note.reminder, "yyyy-MM-dd HH:mm")
            if not dt.isValid():
                dt = QDateTime.fromString(self.current_note.reminder, Qt.ISODate)
            if not dt.isValid():
                dt = QDateTime.currentDateTime()
        else:
            dt = QDateTime.currentDateTime()
        datetime_edit = QDateTimeEdit(dt)
        datetime_edit.setCalendarPopup(True)
        layout.addRow("Напоминание:", datetime_edit)
        repeat_combo = QComboBox()
        options = [
            "Однократно",
            "По будням",
            "Каждый день",
            "Каждую неделю",
            "Каждый месяц",
        ]
        repeat_combo.addItems(options)
        if getattr(self.current_note, "reminder_repeat", None) in options:
            repeat_combo.setCurrentText(
                self.current_note.reminder_repeat or "Однократно"
            )
        else:
            repeat_combo.setCurrentIndex(0)
        layout.addRow("Повторять:", repeat_combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.Accepted:
            dt = datetime_edit.dateTime()
            self.current_note.reminder = dt.toString("yyyy-MM-dd HH:mm")
            selected = repeat_combo.currentText()
            self.current_note.reminder_repeat = (
                None if selected == "Однократно" else selected
            )
            self.save_note_to_file(self.current_note)
            self.refresh_notes_list()
            QMessageBox.information(
                self, "Готово", f"Напоминание обновлено: {self.current_note.reminder}"
            )

    def remove_reminder_from_note(self):
        if self.current_note:
            self.current_note.reminder = None
            self.save_note_to_file(self.current_note)
            self.refresh_notes_list()
            QMessageBox.information(
                self, "Напоминание удалено", "Напоминание было удалено."
            )

    def check_upcoming_reminders(self):
        now = QDateTime.currentDateTime()
        for note in self.notes:
            if note.reminder:
                reminder_dt = QDateTime.fromString(note.reminder, "yyyy-MM-dd HH:mm")
                if -60 <= now.secsTo(reminder_dt) <= 60:
                    self.tray_icon.showMessage(
                        "Напоминание",
                        f"Заметка: {note.title}",
                        QSystemTrayIcon.Information,
                        10000,
                    )
                    self.show_reminder_popup(note)
                    if note.reminder_repeat == "Каждый день":
                        note.reminder = reminder_dt.addDays(1).toString(
                            "yyyy-MM-dd HH:mm"
                        )
                        self.save_note_to_file(note)
                    elif note.reminder_repeat == "По будням":
                        if reminder_dt.date().dayOfWeek() < 6:
                            note.reminder = reminder_dt.addDays(1).toString(
                                "yyyy-MM-dd HH:mm"
                            )
                        else:
                            days_to_monday = 8 - reminder_dt.date().dayOfWeek()
                            note.reminder = reminder_dt.addDays(
                                days_to_monday
                            ).toString("yyyy-MM-dd HH:mm")
                        self.save_note_to_file(note)
                    elif note.reminder_repeat == "Каждую неделю":
                        note.reminder = reminder_dt.addDays(7).toString(
                            "yyyy-MM-dd HH:mm"
                        )
                        self.save_note_to_file(note)
                    elif note.reminder_repeat == "Каждый месяц":
                        note.reminder = reminder_dt.addMonths(1).toString(
                            "yyyy-MM-dd HH:mm"
                        )
                        self.save_note_to_file(note)
                    else:
                        note.reminder = None
                        self.save_note_to_file(note)
                elif now > reminder_dt.addSecs(60):
                    note.reminder = None
                    self.save_note_to_file(note)
                    self.refresh_notes_list()

    def show_reminder_popup(self, note):
        dlg = QDialog(self, Qt.WindowStaysOnTopHint)
        dlg.setWindowTitle("Напоминание")
        dlg.setWindowModality(Qt.NonModal)
        dlg.setMinimumWidth(300)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(f"Напоминание по заметке: <b>{note.title}</b>"))
        layout.addWidget(QLabel(f"Время: {note.reminder}"))
        btn = QPushButton("ОК")
        btn.clicked.connect(dlg.accept)
        layout.addWidget(btn)
        dlg.show()

    def setup_reminder_timer(self):
        self.reminder_timer = QTimer(self)
        self.reminder_timer.timeout.connect(self.check_upcoming_reminders)
        self.reminder_timer.start(60000)

    def handle_note_reorder(self):
        new_order = []
        for i in range(self.notes_list.count()):
            item = self.notes_list.item(i)
            note = item.data(Qt.UserRole)
            new_order.append(note)
        self.notes = new_order
        self.save_all_notes_to_disk()

    def init_all_components(self):
        QShortcut(QKeySequence("Escape"), self.text_edit, self.exit_note)
        QShortcut(QKeySequence("Ctrl+B"), self.text_edit, self.toggle_bold)
        QShortcut(QKeySequence("Ctrl+I"), self.text_edit, self.toggle_italic)
        QShortcut(QKeySequence("Ctrl+U"), self.text_edit, self.toggle_underline)
        QShortcut(QKeySequence("Ctrl+N"), self, self.create_new_note)
        QShortcut(QKeySequence("Ctrl+S"), self, self.save_note)
        QShortcut(QKeySequence("Ctrl+Space"), self.text_edit, self.clear_formatting)
        self._notes_delete_sc = QShortcut(QKeySequence.Delete, self.notes_list)
        self._notes_delete_sc.setContext(Qt.WidgetWithChildrenShortcut)
        self._notes_delete_sc.activated.connect(self.delete_note)
        self.load_notes_from_disk()
        self.refresh_notes_list()
        last_uuid = self.settings.value("lastNoteUUID", "")
        if last_uuid:
            for i in range(self.notes_list.count()):
                it = self.notes_list.item(i)
                n = it.data(Qt.UserRole)
                if n and getattr(n, "uuid", None) == last_uuid:
                    self.notes_list.setCurrentRow(i)
                    self.select_note(n)
                    break
        self.update_tag_filter_items()
        self.update_search_filter_items()
        self.setup_reminder_timer()
        self.setAcceptDrops(True)
        self.autosave_enabled = self.settings.value("autosave_enabled", True, type=bool)
        self.autosave_interval = self.settings.value(
            "autosave_interval", 60000, type=int
        )
        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.autosave_current_note)
        if self.autosave_enabled:
            self.autosave_timer.start(self.autosave_interval)

    def init_theme(self):
        theme = self.settings.value("theme", "dark")
        if theme == "dark":
            self.apply_dark_theme()
        else:
            self.apply_light_theme()

    def apply_dark_theme(self):
        self.setStyle(QStyleFactory.create("Fusion"))
        dark_palette = QPalette()
        dark_palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.Base, QColor(42, 42, 42))
        dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(66, 66, 66))
        dark_palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
        dark_palette.setColor(
            QPalette.ColorRole.Highlight, QColor(142, 45, 197).lighter()
        )
        dark_palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
        dark_palette.setColor(QPalette.ColorRole.Link, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.LinkVisited, Qt.GlobalColor.white)
        self.notes_list.setStyleSheet("color: white; background-color: #2b2b2b;")
        self.text_edit.setFont(QFont("Times New Roman", 14))
        self.text_edit.setStyleSheet(
            "font-size: 14px; font-family: 'Times New Roman'; color: white; background-color: #2b2b2b;"
        )
        self.text_edit.document().setDefaultStyleSheet("a { color: white; }")
        QApplication.instance().setPalette(dark_palette)
        self.setStyleSheet(
            """
            QToolTip {
                background-color: #2a2a2a;
                color: white;
                border: 1px solid white;
                padding: 5px;
                font-size: 12px;
            }
            QCheckBox { color: white; }
        """
        )
        self.rebuild_toolbar()

    def show_toast(
        self,
        text: str,
        ms: int = 1200,
        *,
        boundary_widget: QWidget | None = None,
        anchor_widget: QWidget | None = None,
    ) -> None:
        overlay_parent = boundary_widget or self
        lbl = QLabel(text, overlay_parent)
        lbl.setObjectName("toast")
        lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        lbl.setStyleSheet(
            """
            QLabel {
                background: #ffffff;
                color: #000000;
                border: 1px solid #9a9a9a;
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 12px;
            }
        """
        )
        lbl.setWordWrap(False)
        lbl.adjustSize()
        if anchor_widget is not None:
            anchor_center = anchor_widget.mapTo(
                overlay_parent, anchor_widget.rect().center()
            )
            x = anchor_center.x() - lbl.width() - 8
            y = anchor_center.y() - lbl.height() // 2
        else:
            x = overlay_parent.width() - lbl.width() - 8
            y = overlay_parent.height() - lbl.height() - 8
        stack_idx = sum(1 for t in self._live_toasts if t.parent() is overlay_parent)
        y -= stack_idx * (lbl.height() + 6)
        x = max(6, min(x, overlay_parent.width() - lbl.width() - 6))
        y = max(6, min(y, overlay_parent.height() - lbl.height() - 6))
        lbl.move(x, y)
        lbl.raise_()
        lbl.show()
        self._live_toasts.append(lbl)

        def _close():
            try:
                lbl.close()
            finally:
                if lbl in self._live_toasts:
                    self._live_toasts.remove(lbl)
                lbl.deleteLater()

        QTimer.singleShot(ms, _close)

    def exit_note(self):
        self.load_note(None)
        self.current_note = None
        self.notes_list.clearSelection()
        self._update_editor_visibility()

    def apply_light_theme(self):
        self.setStyle(QStyleFactory.create("Fusion"))
        default_palette = QApplication.style().standardPalette()
        default_palette.setColor(QPalette.ColorRole.Link, Qt.GlobalColor.black)
        default_palette.setColor(QPalette.ColorRole.LinkVisited, Qt.GlobalColor.black)
        QApplication.instance().setPalette(default_palette)
        self.notes_list.setStyleSheet("color: black; background-color: white;")
        self.text_edit.setFont(QFont("Times New Roman", 14))
        self.text_edit.setStyleSheet(
            "font-size: 14px; font-family: 'Times New Roman'; color: black; background-color: white;"
        )
        self.text_edit.document().setDefaultStyleSheet("a { color: black; }")
        self.new_note_button.setStyleSheet("")
        self.save_note_button.setStyleSheet("")
        self.setStyleSheet(
            """
            QToolTip {
                background-color: #ffffff;
                color: black;
                border: 1px solid black;
                padding: 5px;
                font-size: 12px;
            }
            QCheckBox { color: black; }
        """
        )
        self.delete_note_button.setStyleSheet("")
        self.audio_button.setStyleSheet("")
        self.menuBar().setStyleSheet("")
        self.rebuild_toolbar()

    def autosave_current_note(self):
        if not getattr(self, "autosave_enabled", True):
            return
        for note in self.notes:
            if note == self.current_note:
                note.content = self.text_edit.toHtml()
                note.password_manager = self.password_manager_field.text()
                note.rdp_1c8 = self.rdp_1c8_field.text()
                self.update_current_note_custom_fields()
            self.save_note_to_file(note)
        self._set_unsaved(False)

    def eventFilter(self, source, event):
        if source is self.text_edit and event.type() == QEvent.KeyPress:
            if event.matches(QKeySequence.Undo):
                self.undo()
                return True
            elif event.matches(QKeySequence.Redo):
                self.redo()
                return True
        return super().eventFilter(source, event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if not self.current_note:
            return
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if os.path.isfile(file_path):
                note_dir = os.path.join(
                    NOTES_DIR,
                    NotesApp.safe_folder_name(
                        self.current_note.title,
                        self.current_note.uuid,
                        self.current_note.timestamp,
                    ),
                )
                if not os.path.exists(note_dir):
                    os.makedirs(note_dir)
                filename = os.path.basename(file_path)
                dest = os.path.join(note_dir, filename)
                shutil.copy(file_path, dest)
                if filename.lower().endswith(tuple(IMAGE_EXTENSIONS)):
                    pixmap = QPixmap(dest)
                    if not pixmap.isNull():
                        buffer = QBuffer()
                        buffer.open(QIODevice.WriteOnly)
                        pixmap.save(buffer, "PNG")
                        base64_data = base64.b64encode(buffer.data()).decode("utf-8")
                        html_img = f'<img src="Data:image/png;base64,{base64_data}" width="200"><br>'
                        cursor = self.text_edit.textCursor()
                        cursor.movePosition(QTextCursor.End)
                        self.text_edit.setTextCursor(cursor)
                        self.text_edit.insertHtml(html_img)
                        self.record_state_for_undo()
                else:
                    file_url = QUrl.fromLocalFile(os.path.abspath(dest)).toString()
                    cursor = self.text_edit.textCursor()
                    cursor.movePosition(QTextCursor.End)
                    self.text_edit.setTextCursor(cursor)
                    self.text_edit.insertHtml(f'📄 <a href="{file_url}">{filename}</a>')
        QMessageBox.information(
            self, "Перетаскивание файлов", "Файлы прикреплены к заметке."
        )
        self.save_note()

    def closeEvent(self, event: QCloseEvent):
        self.save_settings()
        try:
            if getattr(self, "current_note", None):
                self.save_note_quiet(force=True)
            self.save_all_notes_to_disk()
        except Exception as e:
            print("Save on close failed:", e)
        event.ignore()
        self.hide()
        self.tray_icon.show()
        self.window_hidden.emit()

    @staticmethod
    def safe_folder_name(title, note_uuid, timestamp=None):
        safe_title = re.sub(r"[^\w\-_ ]", "_", title)[:40].strip()
        if timestamp is None:
            date_str = QDateTime.currentDateTime().toString("dd.MM.yyyy")
        else:
            if isinstance(timestamp, str):
                dt = QDateTime.fromString(timestamp, Qt.ISODate)
            else:
                dt = timestamp
            date_str = dt.toString("dd.MM.yyyy")
        uuid_short = (
            note_uuid if note_uuid.startswith("UUID_") else f"UUID({note_uuid[:8]})"
        )
        return f"{safe_title} от {date_str}, {uuid_short}"

    def manage_plugins_dialog(self):
        plugins_folder = os.path.join(APPDIR, "Plugins")
        os.makedirs(plugins_folder, exist_ok=True)
        plugins_state_path = os.path.join(DATA_DIR, "plugins_state.json")
        plugins = []
        if os.path.exists(plugins_folder):
            for fname in os.listdir(plugins_folder):
                if fname.endswith(".py"):
                    plugins.append(fname[:-3])
        if os.path.exists(plugins_state_path):
            with open(plugins_state_path, "r", encoding="utf-8") as f:
                plugins_state = json.load(f)
        else:
            plugins_state = {}

        dialog = QDialog(self)
        dialog.setWindowTitle("Управление плагинами")
        layout = QVBoxLayout(dialog)
        checkboxes = {}
        for plugin in sorted(plugins):
            cb = QCheckBox(plugin)
            cb.setChecked(plugins_state.get(plugin, False))
            layout.addWidget(cb)
            checkboxes[plugin] = cb

        btn_add = QPushButton("Добавить плагин")
        btn_del = QPushButton("Удалить плагин")
        btn_rename = QPushButton("Переименовать плагин")
        btns_h = QHBoxLayout()
        btns_h.addWidget(btn_add)
        btns_h.addWidget(btn_del)
        btns_h.addWidget(btn_rename)
        layout.addLayout(btns_h)

        def add_plugin():
            file_path, _ = QFileDialog.getOpenFileName(
                dialog, "Выберите .py файл плагина", "", "Python Files (*.py)"
            )
            if file_path:
                dest_path = os.path.join(plugins_folder, os.path.basename(file_path))
                if os.path.exists(dest_path):
                    QMessageBox.warning(
                        dialog, "Ошибка", "Плагин с таким именем уже существует."
                    )
                    return
                shutil.copy(file_path, dest_path)
                dialog.close()
                self.manage_plugins_dialog()

        def del_plugin():
            names = [name for name, cb in checkboxes.items() if cb.isChecked()]
            if not names:
                QMessageBox.warning(
                    dialog,
                    "Нет выбора",
                    "Отметьте чекбокс напротив плагина для удаления.",
                )
                return
            for fname in names:
                path = os.path.join(plugins_folder, fname + ".py")
                if os.path.exists(path):
                    reply = QMessageBox.question(
                        dialog,
                        "Удалить плагин",
                        f"Удалить плагин {fname}?",
                        QMessageBox.Yes | QMessageBox.No,
                    )
                    if reply == QMessageBox.Yes:
                        os.remove(path)
                        plugins_state.pop(fname, None)
            dialog.close()
            self.manage_plugins_dialog()

        def rename_plugin():
            names = [name for name, cb in checkboxes.items() if cb.isChecked()]
            if not names:
                QMessageBox.warning(
                    dialog,
                    "Нет выбора",
                    "Отметьте чекбокс напротив плагина для переименования.",
                )
                return
            old_name = names[0]
            new_name, ok = QInputDialog.getText(
                dialog,
                "Переименовать плагин",
                "Новое имя файла (без .py):",
                text=old_name,
            )
            if ok and new_name and new_name != old_name:
                old_path = os.path.join(plugins_folder, old_name + ".py")
                new_path = os.path.join(plugins_folder, new_name + ".py")
                if os.path.exists(new_path):
                    QMessageBox.warning(
                        dialog, "Ошибка", "Файл с таким именем уже существует."
                    )
                    return
                os.rename(old_path, new_path)
                plugins_state[new_name] = plugins_state.pop(old_name)
                dialog.close()
                self.manage_plugins_dialog()

        btn_add.clicked.connect(add_plugin)
        btn_del.clicked.connect(del_plugin)
        btn_rename.clicked.connect(rename_plugin)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(buttons)

        def on_accept():
            for plugin, cb in checkboxes.items():
                plugins_state[plugin] = cb.isChecked()
            with open(plugins_state_path, "w", encoding="utf-8") as f:
                json.dump(plugins_state, f, ensure_ascii=False, indent=2)
            dialog.accept()
            self.load_plugins()

        buttons.accepted.connect(on_accept)
        buttons.rejected.connect(dialog.reject)
        dialog.setLayout(layout)
        dialog.exec()

    def clear_plugin_menu_actions(self):
        menu_bar = self.menuBar()
        plugins_menu = None
        for menu in menu_bar.children():
            try:
                if menu.title() == "Плагины":
                    plugins_menu = menu
                    break
            except Exception:
                continue
        if plugins_menu:
            static_actions = {"Управление плагинами", "Перезагрузить плагины"}
            actions_to_remove = []
            for action in plugins_menu.actions():
                if action.text() not in static_actions:
                    actions_to_remove.append(action)
            for action in actions_to_remove:
                plugins_menu.removeAction(action)

    def load_plugins(self):
        import importlib

        importlib.invalidate_caches()
        self.clear_plugin_menu_actions()
        for module in getattr(self, "active_plugins", {}).values():
            try:
                if hasattr(module, "on_disable"):
                    module.on_disable(parent=self)
            except Exception as e:
                print(
                    f"Ошибка при деинициализации плагина {getattr(module, '__name__', '')}: {e}"
                )
        plugins_folder = os.path.join(APPDIR, "Plugins")
        plugins_state_path = os.path.join(DATA_DIR, "plugins_state.json")
        if os.path.exists(plugins_state_path):
            with open(plugins_state_path, "r", encoding="utf-8") as f:
                plugins_state = json.load(f)
        else:
            plugins_state = {}
        self.active_plugins = {}
        if not os.path.exists(plugins_folder):
            return
        for fname in os.listdir(plugins_folder):
            if fname.endswith(".py"):
                plugin_name = fname[:-3]
                plugin_path = os.path.join(plugins_folder, fname)
                try:
                    spec = importlib.util.spec_from_file_location(
                        plugin_name, plugin_path
                    )
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    self.active_plugins[plugin_name] = module
                    if plugins_state.get(plugin_name, False):
                        if hasattr(module, "on_enable"):
                            module.on_enable(parent=self)
                    else:
                        if hasattr(module, "on_disable"):
                            module.on_disable(parent=self)
                except Exception as e:
                    print(f"Ошибка при загрузке плагина {fname}:", e)

    def detect_plugins(self):
        plugins = []
        plugins_folder = os.path.join(APPDIR, "Plugins")
        if os.path.exists(plugins_folder):
            for file in os.listdir(plugins_folder):
                if file.endswith(".py"):
                    plugins.append(file[:-3])
        return plugins

    def load_plugins_state(self):
        plugins_path = os.path.join(DATA_DIR, "plugins_state.json")
        if os.path.exists(plugins_path):
            with open(plugins_path, "r", encoding="utf-8") as f:
                self.plugins_state = json.load(f)
        else:
            self.plugins_state = {}

    def save_plugins_state(self):
        plugins_path = os.path.join(DATA_DIR, "plugins_state.json")
        with open(plugins_path, "w", encoding="utf-8") as f:
            json.dump(self.plugins_state, f, ensure_ascii=False, indent=2)

    def update_current_note_content(self):
        if not hasattr(self, "current_note") or self.current_note is None:
            return
        self.current_note.content = self.text_edit.toHtml()
        self.record_state_for_undo()

    def hideEvent(self, event):
        self.save_settings()
        super().hideEvent(event)

    def show_from_tray(self):
        self.bring_widget_to_front(self)

    def on_tray_icon_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.show_from_tray()

    def resizeEvent(self, event):
        self.save_settings()
        super().resizeEvent(event)

    def moveEvent(self, event):
        self.save_settings()
        super().moveEvent(event)


def load_plugins(app, plugins_folder="Plugins"):
    if not os.path.exists(plugins_folder):
        os.makedirs(plugins_folder)
        return
    for filename in os.listdir(plugins_folder):
        if filename.endswith(".py"):
            plugin_path = os.path.join(plugins_folder, filename)
            spec = importlib.util.spec_from_file_location(filename[:-3], plugin_path)
            if spec is None:
                continue
            plugin = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(plugin)
                if hasattr(plugin, "register_plugin"):
                    plugin.register_plugin(app)
            except Exception as e:
                print(f"Ошибка при загрузке плагина {filename}: {e}")


def get_app_dir():
    return APPDIR


def create_default_config():
    config_path = os.path.join(PASSWORDS_DIR, "config.json")
    if not os.path.exists(config_path):
        default_config = {
            "salt_file": "salt.bin",
            "max_password_length": 32,
            "default_length": 18,
            "use_uppercase": True,
            "use_lowercase": True,
            "use_digits": True,
            "use_symbols": True,
            "excluded_chars": "O0DQl1I|i!S5Z2B8G6CGceaouvwxX",
            "passwords_file": "passwords.json",
        }
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=4)
        except Exception as e:
            print(f"Ошибка создания конфигурации: {str(e)}")


class PasswordGenerator:
    def __init__(self):
        self.password_length = 15
        self.use_uppercase = True
        self.use_lowercase = True
        self.use_digits = True
        self.use_symbols = True
        self.excluded_chars = ""
        self.load_config()

    def load_config(self):
        config_path = os.path.join(PASSWORDS_DIR, "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    if "max_password_length" in config:
                        self.max_password_length = config["max_password_length"]
                    if "default_length" in config:
                        self.password_length = config["default_length"]
                    if "use_uppercase" in config:
                        self.use_uppercase = config["use_uppercase"]
                    if "use_lowercase" in config:
                        self.use_lowercase = config["use_lowercase"]
                    if "use_digits" in config:
                        self.use_digits = config["use_digits"]
                    if "use_symbols" in config:
                        self.use_symbols = config["use_symbols"]
                    if "excluded_chars" in config:
                        self.excluded_chars = config["excluded_chars"]
            except Exception as e:
                print(f"Ошибка загрузки конфигурации: {str(e)}")
        else:
            self.max_password_length = 32
            create_default_config()
            self.load_config()

    def generate_password(self):
        char_sets: list[list[str]] = []
        if self.use_uppercase:
            char_sets.append(list(string.ascii_uppercase))
        if self.use_lowercase:
            char_sets.append(list(string.ascii_lowercase))
        if self.use_digits:
            char_sets.append(list(string.digits))
        if self.use_symbols:
            char_sets.append(list(string.punctuation))
        if not char_sets:
            return ""
        charset = [c for subset in char_sets for c in subset]
        charset = [c for c in charset if c not in self.excluded_chars]
        if not charset:
            return ""
        password_chars: list[str] = []
        for char_set in char_sets:
            valid_chars = [c for c in char_set if c not in self.excluded_chars]
            if valid_chars:
                password_chars.append(random.choice(valid_chars))
        remaining_length = max(0, self.password_length - len(password_chars))
        if remaining_length > 0:
            password_chars += random.choices(charset, k=remaining_length)
        random.shuffle(password_chars)
        return "".join(password_chars)

    def evaluate_password_strength(self, password):
        score = 0
        if len(password) >= 8:
            score += 10
        if len(password) >= 12:
            score += 10
        if len(password) >= 16:
            score += 10
        if re.search(r"[A-Z]", password):
            score += 10
        if re.search(r"[a-z]", password):
            score += 10
        if re.search(r"[0-9]", password):
            score += 10
        if re.search(r"[^A-Za-z0-9]", password):
            score += 10
        if not re.search(r"(.)\1\1", password):
            score += 10
        unique_chars = len(set(password))
        score += min(20, unique_chars * 2)
        if re.search(r"[A-Z].*[0-9]|[0-9].*[A-Z]", password) and re.search(
            r"[a-z].*[0-9]|[0-9].*[a-z]", password
        ):
            score += 10
        return min(100, score)


class PasswordManager:
    def __init__(self, master_password=None):
        self.master_password = master_password
        self.passwords = []
        self.key = None
        self.salt = None
        self._create_default_config()
        self.load_config()
        if self.master_password:
            self._initialize_encryption()
        self.load_passwords()

    def backup_passwords(self):
        backup_dir = os.path.join(PASSWORDS_DIR, "backups")
        backup_filename = os.path.join(backup_dir, "backup_passwords.bin")
        os.makedirs(backup_dir, exist_ok=True)
        try:
            data = json.dumps(self.passwords, indent=4, ensure_ascii=False)
            with open(backup_filename, "w", encoding="utf-8") as backup_file:
                backup_file.write(data)
            return True, f"Резервная копия создана: {backup_filename}"
        except Exception as e:
            return False, f"Ошибка резервного копирования: {str(e)}"

    def regenerate_salt(self, master_password):
        new_salt = os.urandom(16)
        backup_passwords = self.get_all_passwords()
        try:
            with open(SALT_PATH, "wb") as salt_file:
                salt_file.write(new_salt)
            self.salt = new_salt
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=self.salt,
                iterations=100000,
                backend=default_backend(),
            )
            key = kdf.derive(master_password.encode())
            self.key = base64.urlsafe_b64encode(key)
            self.passwords = []
            for item in backup_passwords:
                self.add_password(
                    item["password"],
                    item["description"],
                    item.get("tags", []),
                    item.get("url", ""),
                )
            return True, "Соль успешно обновлена. Все пароли перешифрованы."
        except Exception as e:
            self.passwords = backup_passwords
            return False, f"Ошибка обновления соли: {str(e)}"

    def _initialize_encryption(self):
        if not os.path.exists(SALT_PATH):
            self.salt = os.urandom(16)
            with open(SALT_PATH, "wb") as salt_file:
                salt_file.write(self.salt)
        else:
            with open(SALT_PATH, "rb") as salt_file:
                self.salt = salt_file.read()
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self.salt,
            iterations=100000,
            backend=default_backend(),
        )
        key = kdf.derive(self.master_password.encode())
        self.key = base64.urlsafe_b64encode(key)

    def encrypt(self, data):
        fernet = Fernet(self.key)
        return fernet.encrypt(data.encode()).decode()

    def decrypt(self, encrypted_data):
        fernet = Fernet(self.key)
        return fernet.decrypt(encrypted_data.encode()).decode()

    def load_config(self):
        config_path = os.path.join(PASSWORDS_DIR, "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    filename = config.get("passwords_file", "passwords.json")
                    if not os.path.isabs(filename):
                        filename = os.path.join(PASSWORDS_DIR, filename)
                    self.filename = filename
            except Exception as e:
                self.filename = os.path.join(PASSWORDS_DIR, "passwords.json")
        else:
            self.filename = os.path.join(PASSWORDS_DIR, "passwords.json")

    def add_password(self, password, description, tags=None, url=None, login=""):
        encrypted_password = self.encrypt(password)
        self.passwords.append(
            {
                "password": encrypted_password,
                "description": description.strip(),
                "tags": tags or [],
                "url": url.strip() if url else "",
                "login": login.strip(),
                "encrypted": True,
                "updated_at": datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
            }
        )
        self._save_passwords()
        return True

    def _create_default_config(self):
        config_path = os.path.join(PASSWORDS_DIR, "config.json")
        if not os.path.exists(config_path):
            default_config = {
                "max_password_length": 32,
                "default_length": 15,
                "use_uppercase": True,
                "use_lowercase": True,
                "use_digits": True,
                "use_symbols": True,
                "excluded_chars": "O0oQl1I|i!S5Z2B8G6CQDceaouvwxX",
                "passwords_file": "passwords.json",
            }
            try:
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(default_config, f, indent=4)
            except Exception as e:
                print(f"Ошибка создания конфигурации: {str(e)}")

    def update_password(
        self, index, password, description, tags=None, url=None, login=""
    ):
        if 0 <= index < len(self.passwords):
            encrypted_password = self.encrypt(password)
            self.passwords[index] = {
                "password": encrypted_password,
                "description": description,
                "tags": tags or [],
                "url": url.strip() if url else "",
                "login": login.strip(),
                "encrypted": True,
                "updated_at": datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
            }
            self._save_passwords()
            return True
        return False

    def export_to_txt(self, filename):
        try:
            decrypted_passwords = self.get_all_passwords()
            with open(filename, "w", encoding="utf-8") as f:
                for pwd in decrypted_passwords:
                    f.write(f"Описание: {pwd['description']}\n")
                    f.write(f"Пароль: {pwd['password']}\n")
                    f.write(f"Теги: {', '.join(pwd['tags'])}\n")
                    f.write(f"URL: {pwd.get('url', '')}\n")
                    f.write("-" * 40 + "\n")
            return True, "Пароли успешно экспортированы"
        except Exception as e:
            return False, f"Ошибка экспорта: {str(e)}"

    def import_from_txt(self, filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                content = f.read().strip()
            password_blocks = []
            current_block = []
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("-----") or line == "":
                    if current_block:
                        password_blocks.append("\n".join(current_block))
                        current_block = []
                else:
                    current_block.append(line)
            if current_block:
                password_blocks.append("\n".join(current_block))
            imported_data = []
            for block in password_blocks:
                password_info = {"description": "", "password": "", "tags": []}
                lines = block.strip().split("\n")
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    if ":" in line:
                        key_part, value_part = line.split(":", 1)
                        key = key_part.strip().lower()
                        value = value_part.strip()
                        if key.startswith("опис"):
                            password_info["description"] = value
                        elif key.startswith("парол"):
                            password_info["password"] = value
                        elif key.startswith("url"):
                            password_info["url"] = value
                        elif key.startswith("тег"):
                            tags = [
                                t.strip() for t in re.split(r"[,;]", value) if t.strip()
                            ]
                            password_info["tags"] = tags
                if password_info["description"] and password_info["password"]:
                    imported_data.append(password_info)
                else:
                    print(f"Пропущен неполный блок: {block[:50]}...")
            if not imported_data:
                return False, "Не удалось найти валидные пароли в файле"
            imported_count = 0
            existing_descriptions = {p["description"] for p in self.passwords}
            for item in imported_data:
                if item["description"] in existing_descriptions:
                    print(f"Пропущен дубликат: {item['description']}")
                    continue
                encrypted_password = self.encrypt(item["password"])
                self.passwords.append(
                    {
                        "password": encrypted_password,
                        "description": item["description"],
                        "tags": item.get("tags", []),
                        "url": item.get("url", ""),
                        "encrypted": True,
                    }
                )
                imported_count += 1
            self._save_passwords()
            return True, f"Успешно импортировано {imported_count} паролей"
        except Exception as e:
            return False, f"Ошибка импорта: {str(e)}"

    def delete_password(self, index):
        if 0 <= index < len(self.passwords):
            del self.passwords[index]
            self._save_passwords()
            return True
        return False

    def get_password(self, index):
        if 0 <= index < len(self.passwords):
            item = self.passwords[index]
            try:
                return {
                    "password": self.decrypt(item["password"]),
                    "description": item["description"],
                    "tags": item.get("tags", []),
                    "url": item.get("url", ""),
                    "login": item.get("login", ""),
                }
            except:
                return {"error": "Неверный мастер-пароль для расшифровки"}
        return None

    def get_all_passwords(self):
        for p in self.passwords:
            if not p.get("updated_at"):
                p["updated_at"] = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
        return [
            {
                "password": self.decrypt(p["password"]),
                "description": p["description"],
                "tags": p.get("tags", []),
                "url": p.get("url", ""),
                "login": p.get("login", ""),
                "updated_at": p.get("updated_at", ""),
            }
            for p in self.passwords
        ]

    def load_passwords(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r", encoding="utf-8") as f:
                    self.passwords = json.load(f)
                if self.passwords:
                    test_item = self.passwords[0]
                    self.decrypt(test_item["password"])
                if self.key and any(
                    not p.get("encrypted", False) for p in self.passwords
                ):
                    self._migrate_old_passwords()
            except (InvalidToken, json.JSONDecodeError):
                self.passwords = []
            except Exception:
                self.passwords = []

    def _save_passwords(self):
        data = [
            {
                "login": p.get("login", ""),
                "password": p["password"],
                "description": p["description"],
                "tags": p.get("tags", []),
                "url": p.get("url", ""),
                "encrypted": True,
                "updated_at": p.get("updated_at", ""),
            }
            for p in self.passwords
        ]
        try:
            with open(self.filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                self.backup_passwords()
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка сохранения: {str(e)}")

    def _migrate_old_passwords(self):
        migrated = False
        for item in self.passwords:
            if not item.get("encrypted", False):
                try:
                    item["password"] = self.encrypt(item["password"])
                    item["encrypted"] = True
                    migrated = True
                except Exception as e:
                    messagebox.showerror(
                        "Ошибка шифрования",
                        f"Не удалось зашифровать пароль для '{item['description']}': {str(e)}",
                    )
        if migrated:
            self._save_passwords()
            messagebox.showinfo(
                "Миграция", "Существующие пароли были успешно зашифрованы"
            )

    def change_master_password(self, old_password, new_password):
        if old_password != self.master_password:
            return False, "Неверный текущий мастер-пароль"
        decrypted_passwords = []
        try:
            for item in self.passwords:
                decrypted_password = (
                    self.decrypt(item["password"])
                    if item.get("encrypted", False)
                    else item["password"]
                )
                decrypted_passwords.append(
                    {
                        "password": decrypted_password,
                        "description": item["description"],
                        "tags": item.get("tags", []),
                        "url": item.get("url", ""),
                    }
                )
        except Exception as e:
            return False, f"Ошибка расшифровки паролей: {str(e)}"
        self.master_password = new_password
        self._initialize_encryption()
        self.passwords = []
        for item in decrypted_passwords:
            self.add_password(
                item["password"], item["description"], item["tags"], item.get("url", "")
            )
        return True, "Мастер-пароль успешно изменен"


class AuthenticationDialog(tk.Toplevel):
    def __init__(self, parent, title="Аутентификация"):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.grab_set()
        self.attributes("-topmost", True)
        self.parent = parent
        self.result = None
        self.master_password = None
        self.max_attempts = 3
        self.attempts = 0
        self._setup_ui()
        self._center_window()
        self.protocol("WM_DELETE_WINDOW", self._safe_destroy)
        self.after(100, lambda: self.parent.focus_force())

    def _center_window(self):
        self.update_idletasks()
        parent_x = self.parent.winfo_x()
        parent_y = self.parent.winfo_y()
        parent_width = self.parent.winfo_width()
        parent_height = self.parent.winfo_height()
        width = self.winfo_width()
        height = self.winfo_height()
        x = parent_x + (parent_width - width) // 2
        y = parent_y + (parent_height - height) // 2
        if parent_width == 1 or parent_height == 1:
            screen_width = self.winfo_screenwidth()
            screen_height = self.winfo_screenheight()
            x = (screen_width - width) // 2
            y = (screen_height - height) // 2
        self.geometry(f"+{x}+{y}")

    def _setup_ui(self):
        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            main_frame, text="Введите мастер-пароль для шифрования/расшифрования:"
        ).pack(pady=(0, 10))
        self.password_var = tk.StringVar()
        self.password_entry = ttk.Entry(
            main_frame, textvariable=self.password_var, show="*", width=30
        )
        self.password_entry.pack(pady=(0, 10), fill=tk.X)
        self.password_entry.focus_force()
        self.attempts_label = ttk.Label(main_frame, text="", foreground="red")
        self.attempts_label.pack(pady=(0, 10), fill=tk.X)
        buttons_frame = ttk.Frame(main_frame)
        buttons_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(buttons_frame, text="ОК", command=self._on_ok).pack(
            side=tk.RIGHT, padx=5
        )
        ttk.Button(buttons_frame, text="Отмена", command=self._on_cancel).pack(
            side=tk.RIGHT, padx=5
        )
        self.bind("<Return>", lambda event: self._on_ok())
        self.minsize(300, 150)
        self.show_password_var = tk.BooleanVar(value=False)
        checkbox_frame = ttk.Frame(main_frame)
        checkbox_frame.pack(fill=tk.X, pady=(0, 10))
        self.show_password_var = tk.BooleanVar(value=False)
        self.show_checkbutton = ttk.Checkbutton(
            checkbox_frame,
            text="Показать пароль",
            variable=self.show_password_var,
            command=self._toggle_password_visibility,
        )
        self.show_checkbutton.pack(side=tk.LEFT, anchor=tk.W)
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(
            label="Вставить",
            command=lambda: paste_from_clipboard(self.password_entry),
        )
        self.password_entry.bind("<Button-3>", self._show_context_menu)

    def _toggle_password_visibility(self):
        show = self.show_password_var.get()
        self.password_entry.config(show="" if show else "*")

    def _show_context_menu(self, event):
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def _validate_master_password(self, password):
        try:
            passwords_file = os.path.join(PASSWORDS_DIR, "passwords.json")
            if os.path.exists(passwords_file):
                with open(passwords_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data:
                        test_item = data[0]
                        fernet = Fernet(self._generate_key(password))
                        fernet.decrypt(test_item["password"].encode())
            return True
        except Exception:
            return False

    def _generate_key(self, password):
        with open(SALT_PATH, "rb") as salt_file:
            salt = salt_file.read()
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend(),
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return key

    def _on_ok(self):
        password = self.password_var.get()
        if not password:
            messagebox.showerror("Ошибка", "Пароль не может быть пустым")
            return
        self.attempts += 1
        try:
            if self._validate_master_password(password):
                self.master_password = password
                self.result = True
                if self.winfo_exists():
                    self.destroy()
            else:
                remaining = self.max_attempts - self.attempts
                if remaining > 0:
                    self.attempts_label.config(
                        text=f"Неверный пароль. Осталось попыток: {remaining}"
                    )
                    self.password_var.set("")
                    self.password_entry.focus_set()
                else:
                    if self.parent.winfo_exists():
                        self.parent.destroy()
                    self.destroy()
        except Exception as e:
            if self.parent.winfo_exists():
                self.parent.destroy()
            self.destroy()

    def _on_cancel(self):
        self.result = False
        self.destroy()
        self.parent.grab_release()

    def _safe_destroy(self):
        self.result = False
        self.destroy()
        self.parent.focus_set()


class BasePasswordDialog(tk.Toplevel):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.grab_set()
        self.parent = parent
        self.result = None
        self._setup_ui()
        self._center_window()

    def _center_window(self):
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"+{x}+{y}")

    def _setup_ui(self):
        raise NotImplementedError("Subclasses must implement _setup_ui")


class PasswordDialog(BasePasswordDialog):
    def __init__(self, parent, title, password_data=None):
        self.password_data = password_data or {
            "description": "",
            "password": "",
            "tags": [],
            "url": "",
            "login": "",
        }
        super().__init__(parent, title)
        self._setup_ui()
        self.attributes("-topmost", True)
        self._load_data()

    def _setup_ui(self):
        ttk.Label(self, text="Описание:").grid(
            row=0, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.description_entry = ttk.Entry(self, width=30)
        self.description_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        ttk.Label(self, text="Логин:").grid(
            row=1, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.login_entry = ttk.Entry(self, width=30)
        self.login_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.EW)
        ttk.Label(self, text="Пароль:").grid(
            row=2, column=0, padx=5, pady=5, sticky=tk.W
        )
        password_frame = ttk.Frame(self)
        password_frame.grid(row=2, column=1, padx=5, pady=5, sticky=tk.EW)
        self.password_entry = ttk.Entry(password_frame, width=25, show="*")
        self.password_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=2)
        self.paste_button = ttk.Button(
            password_frame,
            text="PASTE",
            command=lambda: paste_from_clipboard(self.password_entry),
            style="Small.TButton",
        )
        self.paste_button.pack(side=tk.RIGHT, padx=2, ipady=0)
        style = ttk.Style()
        style.configure("Small.TButton", width=6, font=("Arial", 8), padding=(1, 1))
        ttk.Label(self, text="Теги:").grid(row=3, column=0, padx=5, pady=5, sticky=tk.W)
        self.tags_entry = ttk.Entry(self, width=30)
        self.tags_entry.grid(row=3, column=1, padx=5, pady=5, sticky=tk.EW)
        ttk.Label(self, text="URL:").grid(row=4, column=0, padx=5, pady=5, sticky=tk.W)
        self.url_entry = ttk.Entry(self, width=30)
        self.url_entry.grid(row=4, column=1, padx=5, pady=5, sticky=tk.EW)
        self.show_password_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self,
            text="Показать пароль",
            variable=self.show_password_var,
            command=self._toggle_password_visibility,
        ).grid(row=5, column=1, padx=5, pady=5, sticky=tk.E)
        button_frame = ttk.Frame(self)
        button_frame.grid(row=6, column=0, columnspan=2, pady=10)
        ttk.Button(button_frame, text="Сохранить", command=self._save).pack(
            side=tk.RIGHT, padx=5
        )
        ttk.Button(button_frame, text="Отмена", command=self.destroy).pack(
            side=tk.RIGHT
        )

    def _load_data(self):
        self.description_entry.insert(0, self.password_data.get("description", ""))
        self.password_entry.insert(0, self.password_data.get("password", ""))
        self.tags_entry.insert(0, ", ".join(self.password_data.get("tags", [])))
        self.url_entry.insert(0, self.password_data.get("url", ""))
        self.login_entry.insert(0, self.password_data.get("login", ""))

    def _toggle_password_visibility(self):
        show = self.show_password_var.get()
        self.password_entry.config(show="" if show else "*")

    def _save(self):
        description = self.description_entry.get()
        password = self.password_entry.get()
        url = self.url_entry.get().strip()
        tags = [tag.strip() for tag in self.tags_entry.get().split(",") if tag.strip()]
        if not description or not password:
            tk.messagebox.showerror("Ошибка", "Заполните описание и пароль!")
            return
        if len(password) < 4:
            messagebox.showerror("Ошибка", "Пароль должен быть не короче 4 символов!")
            return
        url = self.url_entry.get()
        login = self.login_entry.get()
        self.result = {
            "description": description,
            "login": login,
            "password": password,
            "tags": tags,
            "url": url.strip(),
        }
        self.destroy()


class ChangeMasterPasswordDialog(tk.Toplevel):
    def __init__(self, parent, password_manager):
        super().__init__(parent)
        self.attributes("-topmost", True)
        self.title("Смена мастер-пароля")
        self.transient(parent)
        self.grab_set()
        self.parent = parent
        self.password_manager = password_manager
        self.result = None
        self._setup_ui()
        self._center_window()
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(
            label="Вставить",
            command=lambda: paste_from_clipboard(self.focus_get()),
        )
        self.old_password_entry.bind("<Button-3>", self._show_context_menu)
        self.new_password_entry.bind("<Button-3>", self._show_context_menu)
        self.confirm_password_entry.bind("<Button-3>", self._show_context_menu)

    def _center_window(self):
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"+{x}+{y}")

    def _setup_ui(self):
        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(main_frame, text="Текущий мастер-пароль:").pack(
            anchor=tk.W, pady=(0, 5)
        )
        self.old_password_var = tk.StringVar()
        self.old_password_entry = ttk.Entry(
            main_frame, textvariable=self.old_password_var, show="*", width=30
        )
        self.old_password_entry.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(main_frame, text="Новый мастер-пароль:").pack(
            anchor=tk.W, pady=(0, 5)
        )
        self.new_password_var = tk.StringVar()
        self.new_password_entry = ttk.Entry(
            main_frame, textvariable=self.new_password_var, show="*", width=30
        )
        self.new_password_entry.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(main_frame, text="Подтвердите новый пароль:").pack(
            anchor=tk.W, pady=(0, 5)
        )
        self.confirm_password_var = tk.StringVar()
        self.confirm_password_entry = ttk.Entry(
            main_frame, textvariable=self.confirm_password_var, show="*", width=30
        )
        self.confirm_password_entry.pack(fill=tk.X, pady=(0, 10))
        buttons_frame = ttk.Frame(main_frame)
        buttons_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(buttons_frame, text="Сменить пароль", command=self._on_change).pack(
            side=tk.RIGHT, padx=5
        )
        ttk.Button(buttons_frame, text="Отмена", command=self._on_cancel).pack(
            side=tk.RIGHT, padx=5
        )

    def _on_change(self):
        old_password = self.old_password_var.get()
        new_password = self.new_password_var.get()
        confirm_password = self.confirm_password_var.get()
        if not old_password or not new_password:
            messagebox.showerror("Ошибка", "Все поля должны быть заполнены")
            return
        if new_password != confirm_password:
            messagebox.showerror("Ошибка", "Новые пароли не совпадают")
            return
        success, message = self.password_manager.change_master_password(
            old_password, new_password
        )
        if success:
            messagebox.showinfo("Успех", message)
            self.result = True
            self.destroy()
        else:
            messagebox.showerror("Ошибка", message)

    def _on_cancel(self):
        self.result = False
        self.destroy()

    def _show_context_menu(self, event):
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()


class ConfigEditorDialog(BasePasswordDialog):
    def __init__(self, parent, config_data):
        self.config_data = config_data
        super().__init__(parent, "Редактирование конфигурации")
        self.attributes("-topmost", True)

    def _setup_ui(self):
        ttk.Label(self, text="Макс. длина пароля:").grid(
            row=0, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.max_length_entry = ttk.Spinbox(self, from_=8, to=128, width=10)
        self.max_length_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
        self.max_length_entry.set(self.config_data.get("max_password_length", 32))
        ttk.Label(self, text="Длина по умолчанию:").grid(
            row=1, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.default_length_entry = ttk.Spinbox(
            self, from_=4, to=self.config_data.get("max_password_length", 32), width=10
        )
        self.default_length_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)
        self.default_length_entry.set(self.config_data.get("default_length", 18))
        self.use_upper_var = tk.BooleanVar(
            value=self.config_data.get("use_uppercase", True)
        )
        ttk.Checkbutton(
            self, text="Исп. заглавные буквы", variable=self.use_upper_var
        ).grid(row=2, column=0, columnspan=2, padx=5, pady=2, sticky=tk.W)
        self.use_lower_var = tk.BooleanVar(
            value=self.config_data.get("use_lowercase", True)
        )
        ttk.Checkbutton(
            self, text="Исп. строчные буквы", variable=self.use_lower_var
        ).grid(row=3, column=0, columnspan=2, padx=5, pady=2, sticky=tk.W)
        self.use_digits_var = tk.BooleanVar(
            value=self.config_data.get("use_digits", True)
        )
        ttk.Checkbutton(self, text="Исп. цифры", variable=self.use_digits_var).grid(
            row=4, column=0, columnspan=2, padx=5, pady=2, sticky=tk.W
        )
        self.use_symbols_var = tk.BooleanVar(
            value=self.config_data.get("use_symbols", True)
        )
        ttk.Checkbutton(self, text="Исп. символы", variable=self.use_symbols_var).grid(
            row=5, column=0, columnspan=2, padx=5, pady=2, sticky=tk.W
        )
        ttk.Label(self, text="Исключенные символы:").grid(
            row=6, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.excluded_chars_entry = ttk.Entry(self, width=30)
        self.excluded_chars_entry.grid(row=6, column=1, padx=5, pady=5)
        self.excluded_chars_entry.insert(0, self.config_data.get("excluded_chars", ""))
        ttk.Label(self, text="Файл для паролей:").grid(
            row=7, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.pass_file_entry = ttk.Entry(self, width=30)
        self.pass_file_entry.grid(row=7, column=1, padx=5, pady=5)
        self.pass_file_entry.insert(
            0, self.config_data.get("passwords_file", "passwords.json")
        )
        button_frame = ttk.Frame(self)
        button_frame.grid(row=8, column=0, columnspan=2, pady=10)
        ttk.Button(button_frame, text="Сохранить", command=self._save).pack(
            side=tk.RIGHT, padx=5
        )
        ttk.Button(button_frame, text="Отмена", command=self.destroy).pack(
            side=tk.RIGHT
        )

    def _save(self):
        new_config = {
            "max_password_length": int(self.max_length_entry.get()),
            "default_length": int(self.default_length_entry.get()),
            "use_uppercase": self.use_upper_var.get(),
            "use_lowercase": self.use_lower_var.get(),
            "use_digits": self.use_digits_var.get(),
            "use_symbols": self.use_symbols_var.get(),
            "excluded_chars": self.excluded_chars_entry.get(),
            "passwords_file": self.pass_file_entry.get(),
        }
        if new_config["default_length"] > new_config["max_password_length"]:
            messagebox.showerror(
                "Ошибка", "Длина по умолчанию не может превышать максимальную"
            )
            return
        self.config_data.update(new_config)
        self.result = True
        self.destroy()


class RegenerateSaltDialog(tk.Toplevel):
    def __init__(self, parent, password_manager):
        super().__init__(parent)
        self.title("Обновление криптографической соли")
        self.password_manager = password_manager
        self._setup_ui()
        self.attributes("-topmost", True)
        self._center_window()
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(
            label="Вставить",
            command=lambda: paste_from_clipboard(self.password_entry),
        )
        self.password_entry.bind("<Button-3>", self._show_context_menu)

    def _center_window(self):
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"+{x}+{y}")

    def _show_context_menu(self, event):
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def _setup_ui(self):
        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(main_frame, text="Введите текущий мастер-пароль:").pack(pady=(0, 10))
        self.password_var = tk.StringVar()
        self.password_entry = ttk.Entry(
            main_frame, textvariable=self.password_var, show="*", width=30
        )
        self.password_entry.pack(pady=(0, 10))
        buttons_frame = ttk.Frame(main_frame)
        buttons_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(buttons_frame, text="Обновить", command=self._regenerate).pack(
            side=tk.RIGHT, padx=5
        )
        ttk.Button(buttons_frame, text="Отмена", command=self.destroy).pack(
            side=tk.RIGHT, padx=5
        )

    def _regenerate(self):
        password = self.password_var.get()
        if not password:
            messagebox.showerror("Ошибка", "Введите мастер-пароль")
            return
        success, message = self.password_manager.regenerate_salt(password)
        if success:
            messagebox.showinfo("Успех", message)
            self.destroy()
        else:
            messagebox.showerror("Ошибка", message)


class PasswordGeneratorApp:
    def __init__(self, master):
        self.master = master
        master.title("Генератор паролей")
        master.geometry("800x600")
        master.minsize(800, 600)
        self.idle_timer = None
        self.idle_timeout = 120000
        self.setup_activity_tracking()
        if not self._initialize_password_manager():
            return
        self._full_ui_initialization()

    def _full_ui_initialization(self):
        self.password_generator = PasswordGenerator()
        self._setup_styles()
        self._create_tabs()
        self._setup_context_menu()
        self._create_menu()
        self.length_slider.config(to=self.password_generator.max_password_length)
        self.schedule_backup()
        self._refresh_password_list()
        self.master.deiconify()

    def _edit_configuration(self):
        config_path = os.path.join(PASSWORDS_DIR, "config.json")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
        except Exception as e:
            messagebox.showerror(
                "Ошибка", f"Не удалось загрузить конфигурацию: {str(e)}"
            )
            return
        dialog = ConfigEditorDialog(self.master, config_data)
        dialog.wait_window()
        if getattr(dialog, "result", False):
            try:
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, indent=4, ensure_ascii=False)
                self.password_generator.load_config()
                self.length_slider.config(
                    to=self.password_generator.max_password_length
                )
                messagebox.showinfo("Успех", "Конфигурация успешно обновлена!")
            except Exception as e:
                messagebox.showerror(
                    "Ошибка", f"Ошибка сохранения конфигурации: {str(e)}"
                )

    def _export_passwords_txt(self):
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")],
            title="Сохранить пароли в TXT",
        )
        if not file_path:
            return
        success, message = self.password_manager.export_to_txt(file_path)
        if success:
            messagebox.showinfo("Успех", message)
        else:
            messagebox.showerror("Ошибка", message)

    def schedule_backup(self):
        self.password_manager.backup_passwords()
        self.master.after(3600000, self.schedule_backup)

    def _initialize_password_manager(self):
        attempts = 3
        while attempts > 0:
            auth_dialog = AuthenticationDialog(self.master)
            auth_dialog.wait_window()
            if not auth_dialog.result:
                if self.master.winfo_exists():
                    self.master.destroy()
                return False
            try:
                self.password_manager = PasswordManager(auth_dialog.master_password)
                self.password_manager.load_passwords()
                self.master.withdraw()
                return True
            except Exception:
                attempts -= 1
                if attempts > 0:
                    messagebox.showwarning(
                        "Ошибка", f"Неверный пароль. Осталось попыток: {attempts}"
                    )
                else:
                    if self.master.winfo_exists():
                        self.master.destroy()
                    return

    def _show_change_master_password(self):
        dialog = ChangeMasterPasswordDialog(self.master, self.password_manager)
        dialog.wait_window()
        if dialog.result:
            self._refresh_password_list()

    def _create_default_config(self):
        config_path = os.path.join(PASSWORDS_DIR, "config.json")
        if not os.path.exists(config_path):
            default_config = {
                "max_password_length": 32,
                "default_length": 15,
                "use_uppercase": True,
                "use_lowercase": True,
                "use_digits": True,
                "use_symbols": True,
                "excluded_chars": "O0oQl1I|i!S5Z2B8G6CQDceaouvwxX",
                "passwords_file": "passwords.json",
            }
            try:
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(default_config, f, indent=4)
            except Exception as e:
                print(f"Ошибка создания конфигурации: {str(e)}")

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TButton", font=("Arial", 10))
        style.configure("TLabel", font=("Arial", 10))
        style.configure("TEntry", font=("Arial", 10))
        style.configure("TCheckbutton", font=("Arial", 10))
        style.configure("red.Horizontal.TProgressbar", background="red")
        style.configure("yellow.Horizontal.TProgressbar", background="yellow")
        style.configure("green.Horizontal.TProgressbar", background="green")
        style.configure("Treeview.Cell", borderwidth=1, relief="solid", padding=(5, 2))
        style.layout(
            "Treeview.Item",
            [
                (
                    "Treeitem.padding",
                    {
                        "sticky": "nswe",
                        "children": [
                            ("Treeitem.indicator", {"side": "left", "sticky": ""}),
                            ("Treeitem.image", {"side": "left", "sticky": ""}),
                            ("Treeitem.text", {"side": "left", "sticky": ""}),
                            ("Treeitem.Cell", {"sticky": "nswe"}),
                        ],
                    },
                )
            ],
        )

    def _create_tabs(self):
        if not hasattr(self, "password_manager"):
            return
        self.tab_control = ttk.Notebook(self.master)
        self.generator_tab = ttk.Frame(self.tab_control)
        self.tab_control.add(self.generator_tab, text="Генератор")
        self._setup_generator_tab()
        self.manager_tab = ttk.Frame(self.tab_control)
        self.tab_control.add(self.manager_tab, text="Менеджер паролей")
        self._setup_manager_tab()
        self.tab_control.pack(expand=1, fill="both")

    def _setup_generator_tab(self):
        settings_frame = ttk.LabelFrame(
            self.generator_tab, text="Настройки генератора", padding=10
        )
        settings_frame.pack(padx=10, pady=10, fill=tk.BOTH)
        ttk.Label(settings_frame, text="Длина пароля:").grid(
            row=0, column=0, sticky=tk.W, pady=5
        )
        self.length_var = tk.IntVar(value=self.password_generator.password_length)
        length_entry = ttk.Entry(settings_frame, textvariable=self.length_var, width=5)
        length_entry.grid(row=0, column=1, sticky=tk.W, pady=5)
        self.length_slider = ttk.Scale(
            settings_frame,
            from_=4,
            to=32,
            orient=tk.HORIZONTAL,
            variable=self.length_var,
            length=200,
            command=lambda _: self.length_var.set(int(self.length_slider.get())),
        )
        self.length_slider.grid(row=0, column=2, sticky=tk.W, pady=5, padx=10)
        self.use_uppercase = tk.BooleanVar(value=self.password_generator.use_uppercase)
        ttk.Checkbutton(
            settings_frame, text="Заглавные буквы (A-Z)", variable=self.use_uppercase
        ).grid(row=1, column=0, columnspan=3, sticky=tk.W)
        self.use_lowercase = tk.BooleanVar(value=self.password_generator.use_lowercase)
        ttk.Checkbutton(
            settings_frame, text="Строчные буквы (a-z)", variable=self.use_lowercase
        ).grid(row=2, column=0, columnspan=3, sticky=tk.W)
        self.use_digits = tk.BooleanVar(value=self.password_generator.use_digits)
        ttk.Checkbutton(
            settings_frame, text="Цифры (0-9)", variable=self.use_digits
        ).grid(row=3, column=0, columnspan=3, sticky=tk.W)
        self.use_symbols = tk.BooleanVar(value=self.password_generator.use_symbols)
        ttk.Checkbutton(
            settings_frame,
            text="Специальные символы (!@#$%)",
            variable=self.use_symbols,
        ).grid(row=4, column=0, columnspan=3, sticky=tk.W)
        ttk.Label(settings_frame, text="Исключить:").grid(
            row=5, column=0, sticky=tk.W, pady=5
        )
        self.excluded_chars_var = tk.StringVar(
            value=self.password_generator.excluded_chars
        )
        ttk.Entry(settings_frame, textvariable=self.excluded_chars_var, width=30).grid(
            row=5, column=1, columnspan=2, sticky=tk.W, pady=5
        )
        ttk.Button(
            settings_frame, text="Сгенерировать пароль", command=self._generate_password
        ).grid(row=6, column=0, columnspan=3, pady=10)
        output_frame = ttk.LabelFrame(
            self.generator_tab, text="Сгенерированный пароль", padding=10
        )
        output_frame.pack(padx=10, pady=10, fill=tk.BOTH)
        self.password_var = tk.StringVar()
        password_entry_frame = ttk.Frame(output_frame)
        password_entry_frame.pack(fill=tk.X)
        self.password_entry = ttk.Entry(
            password_entry_frame, textvariable=self.password_var, width=30
        )
        self.password_entry.pack(side=tk.LEFT, expand=True, fill=tk.X)
        self.password_entry.config(show="*")
        self.show_password_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            password_entry_frame,
            text="Показать",
            variable=self.show_password_var,
            command=lambda: self.password_entry.config(
                show="" if self.show_password_var.get() else "*"
            ),
        ).pack(side=tk.RIGHT)
        ttk.Label(output_frame, text="Сложность пароля:").pack(anchor=tk.W)
        self.strength_var = tk.IntVar()
        self.strength_bar = ttk.Progressbar(
            output_frame,
            orient=tk.HORIZONTAL,
            length=200,
            mode="determinate",
            variable=self.strength_var,
        )
        self.strength_bar.pack(fill=tk.X, pady=5)
        button_frame = ttk.Frame(output_frame)
        button_frame.pack(fill=tk.X, pady=5)
        ttk.Button(button_frame, text="Копировать", command=self._copy_password).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(
            button_frame, text="Очистить", command=lambda: self.password_var.set("")
        ).pack(side=tk.LEFT, padx=5)
        ttk.Button(
            button_frame, text="Сохранить", command=self._save_password_dialog
        ).pack(side=tk.LEFT, padx=5)

    def _setup_manager_tab(self):
        control_frame = ttk.Frame(self.manager_tab, padding=10)
        control_frame.pack(fill=tk.X)
        self.hide_passwords_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            control_frame,
            text="Скрыть пароли",
            variable=self.hide_passwords_var,
            command=self._refresh_password_list,
        ).pack(side=tk.LEFT, padx=5)
        ttk.Button(
            control_frame, text="Обновить список", command=self._refresh_password_list
        ).pack(side=tk.LEFT, padx=5)
        ttk.Button(
            control_frame, text="Добавить новый пароль", command=self._add_new_password
        ).pack(side=tk.LEFT, padx=5)
        ttk.Label(control_frame, text="Поиск:").pack(side=tk.LEFT, padx=(10, 0))
        self.search_var = tk.StringVar()
        self.search_var.trace("w", lambda *args: self._filter_passwords())
        ttk.Entry(control_frame, textvariable=self.search_var, width=20).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Label(control_frame, text="Теги:").pack(side=tk.LEFT, padx=(10, 0))
        self.tag_filter_var = tk.StringVar(value="Все")
        self.tag_filter = ttk.Combobox(
            control_frame,
            textvariable=self.tag_filter_var,
            values=["Все"],
            state="readonly",
        )
        self.tag_filter.pack(side=tk.LEFT, padx=5)
        self.tag_filter.bind("<<ComboboxSelected>>", lambda e: self._filter_passwords())
        list_frame = ttk.Frame(self.manager_tab, padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True)
        columns = ("description", "password", "tags", "updated_at")
        self.password_tree = ttk.Treeview(
            list_frame, columns=columns, show="headings", selectmode="browse"
        )
        headings = {
            "description": "Описание",
            "password": "Пароль",
            "tags": "Теги",
            "updated_at": "Обновлено",
        }
        for col in columns:
            self.password_tree.heading(col, text=headings[col], anchor="center")
            if col == "description":
                self.password_tree.column(col, anchor="e", stretch=True, width=150)
            elif col == "password":
                self.password_tree.column(col, anchor="center", stretch=True, width=200)
            elif col == "tags":
                self.password_tree.column(col, anchor="center", stretch=True, width=100)
            elif col == "updated_at":
                self.password_tree.column(col, anchor="center", stretch=True, width=120)
        vscroll = ttk.Scrollbar(
            list_frame, orient="vertical", command=self.password_tree.yview
        )
        hscroll = ttk.Scrollbar(
            list_frame, orient="horizontal", command=self.password_tree.xview
        )
        self.password_tree.configure(
            yscrollcommand=vscroll.set, xscrollcommand=hscroll.set
        )
        vscroll.pack(side=tk.RIGHT, fill=tk.Y)
        hscroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.password_tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        action_frame = ttk.Frame(self.manager_tab, padding=10)
        action_frame.pack(fill=tk.X)
        ttk.Button(
            action_frame, text="Копировать", command=self._copy_selected_password
        ).pack(side=tk.LEFT, padx=5)
        ttk.Button(
            action_frame, text="Просмотреть", command=self._view_selected_password
        ).pack(side=tk.LEFT, padx=5)
        ttk.Button(
            action_frame, text="Редактировать", command=self._edit_selected_password
        ).pack(side=tk.LEFT, padx=5)
        ttk.Button(
            action_frame, text="Удалить", command=self._delete_selected_password
        ).pack(side=tk.LEFT, padx=5)
        self._refresh_password_list()
        self.password_tree.bind("<Double-1>", lambda e: self._edit_selected_password())

    def _setup_context_menu(self):
        self.entry_context_menu = tk.Menu(self.master, tearoff=0)
        self.entry_context_menu.add_command(
            label="Копировать",
            command=lambda: self._copy_to_clipboard(self.master.focus_get()),
        )
        self.entry_context_menu.add_command(
            label="Вырезать",
            command=lambda: self._cut_to_clipboard(self.master.focus_get()),
        )
        self.entry_context_menu.add_command(
            label="Вставить",
            command=lambda: paste_from_clipboard(self.master.focus_get()),
        )
        self.entry_context_menu.add_command(
            label="Выбрать всё",
            command=lambda: self._select_all(self.master.focus_get()),
        )
        self.tree_context_menu = tk.Menu(self.master, tearoff=0)
        self.tree_context_menu.add_command(
            label="Копировать", command=self._copy_selected_password
        )
        self.tree_context_menu.add_command(
            label="Просмотреть", command=self._view_selected_password
        )
        self.tree_context_menu.add_command(
            label="Редактировать", command=self._edit_selected_password
        )
        self.tree_context_menu.add_command(
            label="Удалить", command=self._delete_selected_password
        )
        self.master.bind("<Button-3>", self._on_right_click)
        self.password_tree.bind("<Button-3>", self._on_tree_right_click)

    def setup_activity_tracking(self):
        def track_activity(event):
            self.reset_inactivity_timer()

        def bind_recursive(widget):
            widget.bind("<Motion>", track_activity)
            widget.bind("<KeyPress>", track_activity)
            for child in widget.winfo_children():
                bind_recursive(child)

        bind_recursive(self.master)
        self.reset_inactivity_timer()

    def reset_inactivity_timer(self, event=None):
        if self.idle_timer is not None:
            self.master.after_cancel(self.idle_timer)
        self.idle_timer = self.master.after(self.idle_timeout, self.lock_application)

    def lock_application(self):
        self.master.withdraw()
        if not hasattr(self, "password_manager") or not self.password_manager:
            return
        auth_window = tk.Toplevel(self.master)
        auth_window.title("Блокировка")
        auth_window.protocol("WM_DELETE_WINDOW", lambda: None)
        auth_window.grab_set()
        auth_window.update_idletasks()
        parent_width = self.master.winfo_width()
        parent_height = self.master.winfo_height()
        parent_x = self.master.winfo_x()
        parent_y = self.master.winfo_y()
        width = auth_window.winfo_width()
        height = auth_window.winfo_height()
        x = parent_x + (parent_width - width) // 2
        y = parent_y + (parent_height - height) // 2
        auth_window.geometry(f"+{x}+{y}")
        auth_dialog = AuthenticationDialog(auth_window)
        auth_dialog.wait_window()
        if auth_dialog.result:
            try:
                self.password_manager = PasswordManager(auth_dialog.master_password)
                self.password_manager.load_passwords()
                self._refresh_password_list()
                auth_window.destroy()
                self.master.deiconify()
            except Exception as e:
                messagebox.showerror("Ошибка", f"Ошибка разблокировки: {str(e)}")
                self.master.destroy()
        else:
            self.master.destroy()
        self.reset_inactivity_timer()

    def _create_menu(self):
        self.menu_bar = tk.Menu(self.master)
        self.master.config(menu=self.menu_bar)
        security_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Безопасность", menu=security_menu)
        security_menu.add_command(
            label="Обновить криптографическую соль", command=self._regenerate_salt
        )
        security_menu.add_command(
            label="Сменить мастер-пароль", command=self._show_change_master_password
        )
        security_menu.add_command(
            label="Заблокировать", command=lambda: self.lock_application()
        )
        file_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Файл", menu=file_menu)
        file_menu.add_command(
            label="Изменить конфигурацию", command=self._edit_configuration
        )
        file_menu.add_command(label="Экспорт в TXT", command=self._export_passwords_txt)
        file_menu.add_command(label="Импорт из TXT", command=self._import_passwords_txt)
        file_menu.add_command(
            label="Редактировать выбранный пароль", command=self._edit_selected_password
        )
        file_menu.add_command(
            label="Создать резервную копию", command=self._create_backup
        )
        file_menu.add_command(
            label="Открыть резервную копию", command=self._open_backup
        )
        file_menu.add_separator()
        file_menu.add_command(label="Выход", command=self.master.destroy)
        help_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Справка", menu=help_menu)
        help_menu.add_command(label="О программе", command=self._show_about)

    def _show_text_context_menu(self, event, menu):
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _regenerate_salt(self):
        dialog = RegenerateSaltDialog(self.master, self.password_manager)
        dialog.wait_window()
        self._refresh_password_list()

    def _open_backup(self):
        backup_dir = os.path.join(PASSWORDS_DIR, "backups")
        backup_file = os.path.join(backup_dir, "backup_passwords.bin")
        if not os.path.exists(backup_file):
            messagebox.showerror("Ошибка", f"Файл не найден:\n{backup_file}")
            return
        try:
            with open(backup_file, "r", encoding="utf-8") as f:
                encrypted_data = f.read()
            backup_passwords = json.loads(encrypted_data)
            decrypted_passwords = []
            for item in backup_passwords:
                try:
                    decrypted_pwd = self.password_manager.decrypt(item["password"])
                    decrypted_item = {
                        "description": item["description"],
                        "password": decrypted_pwd,
                        "tags": item.get("tags", []),
                    }
                    decrypted_passwords.append(decrypted_item)
                except Exception as e:
                    messagebox.showerror(
                        "Ошибка расшифровки",
                        f"Не удалось расшифровать пароль для '{item['description']}': {str(e)}",
                    )
                    return
            text_window = tk.Toplevel(self.master)
            text_window.title("Резервная копия (расшифровано)")
            text = tk.Text(text_window, wrap=tk.WORD)
            text.pack(fill=tk.BOTH, expand=True)
            formatted_data = json.dumps(
                decrypted_passwords, indent=4, ensure_ascii=False
            )
            text.insert(tk.END, formatted_data)

            context_menu = tk.Menu(text_window, tearoff=0)
            context_menu.add_command(
                label="Копировать", command=lambda: self._copy_from_text_widget(text)
            )

            text.bind(
                "<Button-3>", lambda e: self._show_text_context_menu(e, context_menu)
            )
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось обработать файл: {str(e)}")

    def _copy_from_text_widget(self, text_widget):
        try:
            selected = text_widget.get("sel.first", "sel.last")
            self.master.clipboard_clear()
            self.master.clipboard_append(selected)
        except tk.TclError:
            pass

    def _create_backup(self):
        success, message = self.password_manager.backup_passwords()
        if success:
            messagebox.showinfo("Успех", message)
        else:
            messagebox.showerror("Ошибка", message)

    def _show_about(self):
        messagebox.showinfo("О программе", "Менеджер паролей с шифрованием\n\n")

    def _import_passwords_txt(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Выберите файл для импорта",
        )
        if not file_path:
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                preview = f.read(1000)
            if not messagebox.askyesno(
                "Подтверждение",
                f"Импортировать пароли из файла?\n\nПревью:\n{preview[:200]}...",
            ):
                return
            success, message = self.password_manager.import_from_txt(file_path)
            if success:
                messagebox.showinfo("Успех", message)
                self._refresh_password_list()
            else:
                messagebox.showerror("Ошибка", message)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось прочитать файл: {str(e)}")

    def _generate_password(self):
        self.password_generator.password_length = int(self.length_var.get())
        self.password_generator.use_uppercase = self.use_uppercase.get()
        self.password_generator.use_lowercase = self.use_lowercase.get()
        self.password_generator.use_digits = self.use_digits.get()
        self.password_generator.use_symbols = self.use_symbols.get()
        self.password_generator.excluded_chars = self.excluded_chars_var.get().replace(
            " ", ""
        )
        new_password = self.password_generator.generate_password()
        self.password_var.set(new_password)
        self._update_strength_bar(new_password)

    def _update_strength_bar(self, password):
        score = self.password_generator.evaluate_password_strength(password)
        self.strength_var.set(score)
        if score < 40:
            self.strength_bar.config(style="red.Horizontal.TProgressbar")
        elif score < 70:
            self.strength_bar.config(style="yellow.Horizontal.TProgressbar")
        else:
            self.strength_bar.config(style="green.Horizontal.TProgressbar")

    def _copy_password(self):
        password = self.password_var.get()
        if password:
            pyperclip.copy(password)
            messagebox.showinfo("Успешно", "Пароль скопирован в буфер обмена!")
        else:
            messagebox.showerror("Ошибка", "Нет пароля для копирования.")

    def _save_password_dialog(self):
        password = self.password_var.get()
        if not password:
            messagebox.showerror("Ошибка", "Сначала сгенерируйте пароль!")
            return
        initial_data = {"password": password, "description": "", "tags": [], "url": ""}
        dialog = PasswordDialog(self.master, "Сохранение пароля", initial_data)
        dialog.wait_window()
        if hasattr(dialog, "result") and dialog.result:
            data = dialog.result
            if not data["description"]:
                messagebox.showerror("Ошибка", "Заполните описание!")
                return
            self.password_manager.add_password(
                data["password"],
                data["description"],
                data.get("tags", []),
                data.get("url", ""),
            )
            messagebox.showinfo("Успешно", "Пароль сохранен!")
            self._refresh_password_list()

    def _add_new_password(self):
        dialog = PasswordDialog(self.master, "Добавить новый пароль")
        dialog.wait_window()
        if hasattr(dialog, "result") and dialog.result:
            data = dialog.result
            self.password_manager.add_password(
                data["password"],
                data["description"],
                data.get("tags", []),
                data.get("url", ""),
            )
            self._refresh_password_list()

    def _refresh_password_list(self):
        self.password_tree.delete(*self.password_tree.get_children())
        passwords = self.password_manager.get_all_passwords()
        for idx, pwd in enumerate(passwords):
            pwd_copy = pwd.copy()
            if self.hide_passwords_var.get():
                pwd_copy["password"] = "••••••••"
            self.password_tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    pwd_copy["description"],
                    pwd_copy["password"],
                    ", ".join(pwd.get("tags", [])),
                    pwd.get("updated_at", "—"),
                ),
            )

        self._update_tag_filter_options()
        self._filter_passwords()

    def _update_tag_filter_options(self):
        tags = set()
        for pwd in self.password_manager.get_all_passwords():
            tags.update(pwd.get("tags", []))
        all_tags = ["Все"] + sorted(tags)
        self.tag_filter["values"] = all_tags
        self.tag_filter.config(
            width=max(
                10, max(len(str(tag)) for tag in all_tags) + 2 if all_tags else 10
            )
        )

    def _filter_passwords(self):
        search_term = self.search_var.get().lower()
        selected_tag = self.tag_filter_var.get()
        self.password_tree.delete(*self.password_tree.get_children())
        passwords = self.password_manager.get_all_passwords()
        for idx, pwd in enumerate(passwords):
            tags = [t.lower() for t in pwd.get("tags", [])]
            match_search = (
                not search_term
                or search_term in pwd["description"].lower()
                or search_term in pwd["password"].lower()
                or any(search_term in tag for tag in tags)
            )
            match_tag = selected_tag == "Все" or selected_tag.lower() in tags
            if match_search and match_tag:
                display_password = (
                    "••••••••••••••••••••••••••••••••••••••••••••••••••••••••"
                    if self.hide_passwords_var.get()
                    else pwd["password"]
                )
                self.password_tree.insert(
                    "",
                    tk.END,
                    iid=str(idx),
                    values=(
                        pwd["description"],
                        display_password,
                        ", ".join(pwd.get("tags", [])),
                        pwd.get("updated_at", "—"),
                    ),
                )

    def _get_selected_password_index(self):
        selection = self.password_tree.selection()
        return int(selection[0]) if selection else None

    def _copy_selected_password(self):
        index = self._get_selected_password_index()
        if index is None:
            messagebox.showerror("Ошибка", "Выберите пароль для копирования.")
            return
        pwd = self.password_manager.get_password(index)
        if pwd:
            pyperclip.copy(pwd["password"])
            messagebox.showinfo("Успешно", "Пароль скопирован в буфер обмена!")

    def _view_selected_password(self):
        index = self._get_selected_password_index()
        if index is None:
            messagebox.showerror("Ошибка", "Выберите пароль для просмотра.")
            return
        pwd = self.password_manager.get_password(index)
        if pwd:
            dialog = PasswordDialog(self.master, "Просмотр пароля", pwd)
            dialog.paste_button.pack_forget()
            dialog.paste_button.destroy()
            dialog.password_entry.config(state="readonly")
            dialog.description_entry.config(state="readonly")
            dialog.tags_entry.config(state="readonly")
            dialog.url_entry.config(state="readonly")
            for child in dialog.winfo_children():
                if isinstance(child, ttk.Button):
                    child.destroy()
            url = pwd.get("url", "")
            if url.startswith(("http://", "https://")):
                link_frame = ttk.Frame(dialog)
                link_frame.grid(row=5, column=0, columnspan=2, pady=10, sticky="ew")
                ttk.Button(
                    link_frame,
                    text="Открыть ссылку",
                    command=lambda: QDesktopServices.openUrl(QUrl(url)),
                    cursor="hand2",
                ).pack(side=tk.TOP, fill=tk.X)
            ttk.Button(dialog, text="Закрыть", command=dialog.destroy).grid(
                row=6, column=0, columnspan=2, pady=10, sticky="ew"
            )

    def _edit_selected_password(self):
        index = self._get_selected_password_index()
        if index is None:
            messagebox.showerror("Ошибка", "Выберите пароль для редактирования.")
            return
        pwd = self.password_manager.get_password(index)
        if pwd:
            dialog = PasswordDialog(self.master, "Редактировать пароль", pwd)
            dialog.wait_window()
            if hasattr(dialog, "result") and dialog.result:
                data = dialog.result
                self.password_manager.update_password(
                    index,
                    data["password"],
                    data["description"],
                    data.get("tags", []),
                    data.get("url", ""),
                    data.get("login", ""),
                )
                self._refresh_password_list()

    def _delete_selected_password(self):
        index = self._get_selected_password_index()
        if index is None:
            messagebox.showerror("Ошибка", "Выберите пароль для удаления.")
            return
        if messagebox.askyesno(
            "Подтверждение", "Вы уверены, что хотите удалить этот пароль?"
        ):
            if self.password_manager.delete_password(index):
                messagebox.showinfo("Успех", "Пароль удален.")
                self._refresh_password_list()
            else:
                messagebox.showerror("Ошибка", "Не удалось удалить пароль.")

    def _copy_to_clipboard(self, widget):
        if widget.selection_present():
            self.master.clipboard_clear()
            self.master.clipboard_append(widget.selection_get())

    def _cut_to_clipboard(self, widget):
        if widget.selection_present():
            self._copy_to_clipboard(widget)
            widget.delete("sel.first", "sel.last")

    def _select_all(self, widget):
        if isinstance(widget, (tk.Entry, ttk.Entry)):
            widget.select_range(0, tk.END)
            widget.icursor(tk.END)
        elif isinstance(widget, tk.Text):
            widget.tag_add("sel", "1.0", tk.END)
            widget.mark_set("insert", tk.END)

    def _on_right_click(self, event):
        widget = event.widget
        if isinstance(widget, (tk.Entry, ttk.Entry)):
            widget.focus_set()
            try:
                widget.icursor(widget.index(f"@{event.x}"))
            except tk.TclError:
                pass
            self.entry_context_menu.tk_popup(event.x_root, event.y_root)

    def _on_tree_right_click(self, event):
        item = self.password_tree.identify_row(event.y)
        if item:
            self.password_tree.selection_set(item)
            self.tree_context_menu.tk_popup(event.x_root, event.y_root)


def heading_to_path(head):
    return head.replace(" ", "_").lower()


def run_password_manager():
    root = tk.Tk()
    app = PasswordGeneratorApp(root)
    root.mainloop()


def run_notes_app():
    app = QApplication(sys.argv)
    window = NotesApp()
    window.show()
    app.exec()


class LauncherWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.notes_window = None
        self.setWindowIcon(QIcon(ICON_PATH))
        central_widget = QWidget(self)
        layout = QVBoxLayout(central_widget)
        layout.setSpacing(20)
        layout.setContentsMargins(40, 40, 40, 40)
        btn_notes = QPushButton("Заметки")
        btn_notes.setMinimumHeight(40)
        btn_notes.clicked.connect(self.launch_notes)
        btn_notes.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(btn_notes)
        btn_manager = QPushButton("Менеджер паролей")
        btn_manager.setMinimumHeight(40)
        btn_manager.clicked.connect(self.launch_password_manager)
        btn_manager.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(btn_manager)
        btn_exit = QPushButton("Выход")
        btn_exit.setMinimumHeight(40)
        btn_exit.clicked.connect(sys.exit)
        btn_exit.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(btn_exit)
        self.setCentralWidget(central_widget)
        self.setWindowTitle("Выберите приложение")
        self.setMinimumSize(400, 250)
        self.setStyleSheet(
            """
            QPushButton {
                font-size: 20px;
                border-radius: 10px;
                padding: 8px 0;
                outline: none;
                border: none;
                background-color: #f6f6f6;
                color: #222;
            }
            QPushButton:focus {
                outline: none;
                border: none;
                background-color: #e0e0e0;
                color: #222;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
                color: #222;
            }
            """
        )

    def launch_notes(self):
        self.hide()
        if self.notes_window is None:
            self.notes_window = NotesApp()
            self.notes_window.window_hidden.connect(self.on_notes_hidden)
        self.notes_window.show()
        self.notes_window.raise_()
        self.notes_window.activateWindow()

    def on_notes_hidden(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def launch_password_manager(self):
        self.hide()
        run_password_manager()
        self.show()
        self.raise_()
        self.activateWindow()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(ICON_PATH))
    app.setQuitOnLastWindowClosed(False)
    window = LauncherWindow()
    window.show()
    sys.exit(app.exec())
    # UPD 24.08.2025|18:23
