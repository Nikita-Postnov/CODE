import numpy as np
import json
import time
import math
import tempfile
import os
import sys
import re
import uuid
import shutil
import base64
import sounddevice as sd
import importlib.util
from urllib.parse import quote
from PySide6.QtCore import (
    Qt,
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
)
from PySide6.QtGui import (
    QIcon,
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
    QPainter,
    QPalette,
    QTextDocument,
)
from scipy.io.wavfile import write
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QMainWindow,
    QTextEdit,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QDialog,
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
)

APPDIR = getattr(sys, "_MEIPASS", os.path.abspath(os.path.dirname(__file__)))
DATA_DIR = os.path.join(APPDIR, "Data")
ICON_PATH = os.path.join(DATA_DIR, "icon.ico")
TRAY_ICON_PATH = os.path.join(DATA_DIR, "tray_icon.ico")
os.makedirs(DATA_DIR, exist_ok=True)
MAX_HISTORY = 20
sys.excepthook = lambda t, v, tb: print("Uncaught exception:", t, v)

def copy_default_icons():
    src_icon = os.path.join(os.path.abspath(os.path.dirname(__file__)), "icon.ico")
    src_tray_icon = os.path.join(os.path.abspath(os.path.dirname(__file__)), "tray_icon.ico")
    if not os.path.exists(ICON_PATH) and os.path.exists(src_icon):
        shutil.copy(src_icon, ICON_PATH)
    if not os.path.exists(TRAY_ICON_PATH) and os.path.exists(src_tray_icon):
        shutil.copy(src_tray_icon, TRAY_ICON_PATH)
copy_default_icons()




def heading_to_path(head):
    return head.replace(" ", "_").lower()


class AudioRecorderThread(QThread):
    recording_finished = Signal(str)

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
        self._running = True
        self.audio_data = []

    def callback(self, indata, frames, time, status):
        if self._running:
            self.audio_data.append(indata.copy())

    def run(self):
        self.audio_data = []
        try:
            with sd.InputStream(
                samplerate=44100,
                channels=1,
                dtype="int16",
                callback=self.callback,
            ):
                while self._running:
                    sd.sleep(100)
            if self.audio_data:
                audio_array = np.concatenate(self.audio_data, axis=0)
                write(self.file_path, 44100, audio_array)
                self.recording_finished.emit(self.file_path)
        except Exception as e:
            print("Ошибка записи:", e)

    def stop(self):
        self._running = False


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, spacing=6):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self.itemList = []

    def addItem(self, item):
        self.itemList.append(item)

    def count(self):
        return len(self.itemList)

    def itemAt(self, index):
        return self.itemList[index] if index < len(self.itemList) else None

    def takeAt(self, index):
        if 0 <= index < len(self.itemList):
            return self.itemList.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        height = self.doLayout(QRect(0, 0, width, 0), True)
        return height

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.doLayout(rect, False)

    def doLayout(self, rect, testOnly):
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
    def __init__(self, parent=None, paste_image_callback=None):
        super().__init__(parent)
        self.paste_image_callback = paste_image_callback
        self.setFont(QFont("Times New Roman", 14))
        self.setCurrentFont(QFont("Times New Roman"))
        self.setFontPointSize(14)

    def insertFromMimeData(self, source):
        if source.hasImage() and self.paste_image_callback:
            image = source.imageData()
            self.paste_image_callback(image)
        else:
            super().insertFromMimeData(source)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and (event.modifiers() & Qt.ControlModifier):
            cursor = self.cursorForPosition(event.position().toPoint())
            char_format = cursor.charFormat()
            if char_format.isImageFormat():
                image_format = char_format.toImageFormat()
                image_path = image_format.name()
                if image_path.startswith("Data:image"):
                    import tempfile, base64

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
                        QDesktopServices.openUrl(QUrl.fromLocalFile(file_path))
                return
            elif char_format.isAnchor():
                link = char_format.anchorHref()
                if link.startswith("file://"):
                    local_path = QUrl(link).toLocalFile()
                    if os.path.exists(local_path):
                        QDesktopServices.openUrl(QUrl.fromLocalFile(local_path))
                        return
                else:
                    QDesktopServices.openUrl(QUrl(link))
                    return
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            block_html = cursor.selection().toHtml()
            import re

            match = re.search(r'href="(file://[^"]+)"', block_html)
            if match:
                link = match.group(1)
                local_path = QUrl(link).toLocalFile()
                if os.path.exists(local_path):
                    QDesktopServices.openUrl(QUrl.fromLocalFile(local_path))
                    return
        cursor = self.cursorForPosition(event.position().toPoint())
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        word = cursor.selectedText()
        if word == "☐":
            cursor.insertText("☑")
            return
        elif word == "☑":
            cursor.insertText("☐")
            return
        super().mousePressEvent(event)

    def create_drag_image(self, widget):
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

    def startDrag(self, supportedActions):
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
        title,
        content,
        tags,
        favorite=False,
        history=None,
        timestamp=None,
        reminder=None,
        uuid=None,
        reminder_repeat=None,
        pinned=False,
    ):
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

    def to_dict(self):
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
        }

    @staticmethod
    def from_dict(data):
        note = Note(
            title=data.get("title", ""),
            content=data.get("content", ""),
            tags=data.get("tags", []),
            favorite=data.get("favorite", False),
            history=data.get("history", []),
            timestamp=data.get("timestamp"),
            reminder=data.get("reminder"),
            uuid=data.get("uuid"),
            reminder_repeat=data.get("reminder_repeat", None),
        )
        note.pinned = data.get("pinned", False)
        note.history_index = data.get("history_index", len(note.history) - 1)
        return note


class NotesApp(QMainWindow):
    TRASH_DIR = "Trash"

    def __init__(self):
        super().__init__()
        self.exiting = False
        self.notes = []
        self.audio_thread = None
        self.init_ui()
        self.autosave_enabled = True
        self.autosave_interval = 60000
        self.autosave_timer = QTimer(self)
        self.current_note = None
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

    def exit_app(self):
        self.exiting = True
        self.tray_icon.hide()
        self.close()
        QApplication.instance().quit()

    def init_ui(self):
        self.setWindowTitle("Мои Заметки")
        self.setMinimumSize(1250, 800)
        self.setWindowIcon(QIcon(ICON_PATH))
        self.new_note_button = QPushButton("Новая")
        self.save_note_button = QPushButton("Сохранить")
        self.delete_note_button = QPushButton("Удалить")
        button_layout = QVBoxLayout()
        button_layout.addWidget(self.new_note_button)
        button_layout.addWidget(self.save_note_button)
        button_layout.addWidget(self.delete_note_button)
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
        self.history_list.itemClicked.connect(self.restore_version_from_history)
        history_layout = QVBoxLayout()
        history_layout.addWidget(self.history_label)
        history_layout.addWidget(self.history_list)
        self.history_widget = QWidget()
        self.history_widget.setLayout(history_layout)
        self.history_widget.setFixedWidth(200)
        self.text_edit = CustomTextEdit(self, self.insert_image_from_clipboard)
        self.text_edit.cursorPositionChanged.connect(self.update_font_controls)
        self.text_edit.setReadOnly(True)
        self.text_edit.hide()
        self.text_edit.setFocusPolicy(Qt.StrongFocus)
        self.text_edit.setAlignment(Qt.AlignLeft)
        self.text_edit.setMinimumWidth(400)
        self.text_edit.setStyleSheet("font-size: 14px; font-family: 'Segoe UI Emoji';")
        self.text_edit.installEventFilter(self)
        # self.text_edit.textChanged.connect(self.record_state_for_undo)
        self.tags_label = QLabel("Теги: нет")
        self.tags_label.setAlignment(Qt.AlignLeft)
        editor_combined = QWidget()
        editor_layout_combined = QVBoxLayout(editor_combined)
        editor_layout_combined.addWidget(self.tags_label)
        editor_layout_combined.addWidget(self.text_edit)
        self.undo_button = QPushButton("↩️")
        self.redo_button = QPushButton("↪️")
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        right_layout = QVBoxLayout()
        right_layout.addWidget(self.undo_button)
        right_layout.addWidget(self.redo_button)
        right_layout.addStretch()
        right_widget = QWidget()
        right_widget.setLayout(right_layout)
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
        self.settings = QSettings("settings.ini", QSettings.IniFormat)
        self.all_tags = set()
        self.new_note_button.clicked.connect(self.new_note)
        self.save_note_button.clicked.connect(self.save_note)
        self.delete_note_button.clicked.connect(self.delete_note)
        self.notes_list.itemClicked.connect(self.load_note)
        self.text_edit.setReadOnly(True)
        self.add_menu_bar()

    def add_toolbar(self):
        self.init_toolbar()
        layout_splitter = QSplitter(Qt.Vertical)
        layout_splitter.addWidget(self.toolbar_scroll)
        layout_splitter.addWidget(self.main_splitter)
        layout_splitter.setSizes([140, 1000])
        self.layout_splitter = layout_splitter
        self.main_layout = QHBoxLayout()
        self.main_layout.addWidget(self.layout_splitter)
        self.central_widget.setLayout(self.main_layout)

    def insert_update_block(self):
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

    def restore_version_from_history(self, item):
        if not self.current_note:
            return
        content = item.data(Qt.UserRole)
        if content:
            self.text_edit.blockSignals(True)
            self.text_edit.setHtml(content)
            self.text_edit.blockSignals(False)
            self.current_note.history_index = self.history_list.row(item)
            self.update_history_list_selection()

    def record_state_for_undo(self):
        note = self.current_note
        if not note:
            return
        if not hasattr(note, "history") or note.history is None:
            note.history = []
        if len(note.history) >= MAX_HISTORY:
            note.history.pop(0)
        note.history.append(self.text_edit.toHtml())
        note.history_index = len(note.history) - 1
        self.update_history_list()
        self.update_history_list_selection()

    def on_tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.show()
            self.raise_()
            self.activateWindow()

    def update_history_list(self):
        if not self.current_note:
            self.history_list.clear()
            return
        self.history_list.clear()
        for i, content in enumerate(self.current_note.history):
            item = QListWidgetItem(f"Версия {i+1}")
            item.setData(Qt.UserRole, content)
            self.history_list.addItem(item)
        self.history_list.scrollToBottom()

    def undo(self):
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

    def redo(self):
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

    def update_history_list_selection(self):
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

    def load_notes_from_disk(self):
        self.ensure_notes_directory()
        self.notes = []
        for folder in os.listdir("Notes"):
            folder_path = os.path.join("Notes", folder)
            if os.path.isdir(folder_path):
                file_path = os.path.join(folder_path, "note.json")
                if os.path.exists(file_path):
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        note = Note.from_dict(data)
                        self.notes.append(note)

    def save_note_to_file(self, note):
        note_dir = os.path.join(
            "Notes", NotesApp.safe_folder_name(note.title, note.uuid)
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

    def save_all_notes_to_disk(self):
        self.ensure_notes_directory()
        unique_notes = {}
        for note in self.notes:
            unique_notes[note.uuid] = note
        self.notes = list(unique_notes.values())
        for note in self.notes:
            self.save_note_to_file(note)

    def load_settings(self):
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        state = self.settings.value("windowState")
        if state:
            self.restoreState(state)
        last_text = self.settings.value("lastNoteText")
        if last_text:
            self.text_edit.setHtml(last_text)

    def save_settings(self):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
        self.settings.setValue("lastNoteText", self.text_edit.toHtml())

    def confirm_delete_note(self, note):
        reply = QMessageBox.question(
            self,
            "Удалить заметку",
            f"Вы уверены, что хотите удалить заметку '{note.title}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.notes = [n for n in self.notes if n.uuid != note.uuid]
            note_dir = os.path.join(
                "Notes", NotesApp.safe_folder_name(note.title, note.uuid)
            )
            if os.path.exists(note_dir):
                shutil.rmtree(note_dir)
            if self.current_note and self.current_note.uuid == note.uuid:
                self.current_note = None
                self.text_edit.clear()
            self.refresh_notes_list()
            self.save_all_notes_to_disk()

    def rename_note(self, note):
        new_title, ok = QInputDialog.getText(
            self, "Переименовать", "Новое имя заметки:", text=note.title
        )
        if ok and new_title and new_title != note.title:
            old_dir = os.path.join(
                "Notes", NotesApp.safe_folder_name(note.title, note.uuid)
            )
            note.title = new_title
            new_dir = os.path.join(
                "Notes", NotesApp.safe_folder_name(note.title, note.uuid)
            )
            if os.path.exists(old_dir):
                os.rename(old_dir, new_dir)
            self.save_note_to_file(note)
            self.refresh_notes_list()

    def copy_note(self, note):
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
        )
        note_dir = os.path.join(
            "Notes", NotesApp.safe_folder_name(note.title, note.uuid)
        )
        new_note_dir = os.path.join(
            "Notes", NotesApp.safe_folder_name(new_title, new_uuid)
        )
        if os.path.exists(note_dir):
            shutil.copytree(note_dir, new_note_dir)
            self.save_note_to_file(new_note)
        self.load_notes_from_disk()
        self.refresh_notes_list()


    def ensure_notes_directory(self):
        if not os.path.exists("Notes"):
            os.makedirs("Notes")

    def create_new_note(self):
        self.new_note()

    def save_current_note(self):
        self.save_note()

    def delete_current_note(self):
        self.delete_note()

    def new_note(self):
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
            note_dir = os.path.join(
                "Notes", NotesApp.safe_folder_name(title, note_uuid)
            )
            os.makedirs(note_dir, exist_ok=True)

            self.current_note = note
            self.text_edit.setFont(QFont("Times New Roman", 14))
            self.text_edit.setCurrentFont(QFont("Times New Roman"))
            self.text_edit.setFontPointSize(14)
            self.font_combo.setCurrentFont(QFont("Times New Roman"))
            self.font_size_spin.setValue(14)

            self.refresh_notes_list()
            self.show_note_with_attachments(note)
            self.text_edit.setFocus()
        self.text_edit.setReadOnly(False)

    def save_note(self):
        if self.current_note:
            self.current_note.content = self.text_edit.toHtml()
            self.save_note_to_file(self.current_note)
            self.refresh_notes_list()
            self.record_state_for_undo()
            QMessageBox.information(self, "Сохранено", "Заметка успешно сохранена.")

    def delete_note(self):
        selected_items = self.notes_list.selectedItems()
        if not selected_items:
            QMessageBox.information(
                self, "Удаление", "Выберите одну или несколько заметок для удаления."
            )
            return

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
            note_folder_name = NotesApp.safe_folder_name(
                note.title, note.uuid, note.timestamp
            )
            note_dir = os.path.join("Notes", note_folder_name)
            trash_dir = os.path.join(self.TRASH_DIR, note_folder_name)
            try:
                if not os.path.exists(self.TRASH_DIR):
                    os.makedirs(self.TRASH_DIR)
                if os.path.exists(trash_dir):
                    shutil.rmtree(trash_dir)
                if os.path.exists(note_dir):
                    shutil.move(note_dir, trash_dir)
                    self.notes = [n for n in self.notes if n.uuid != note.uuid]
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Ошибка",
                    f"Не удалось переместить заметку '{note.title}' в корзину:\n{str(e)}",
                )
                continue

        self.refresh_notes_list()
        self.load_note(None)
        self.current_note = None
        QMessageBox.information(
            self, "Готово", "Выбранные заметки перемещены в корзину."
        )

    def show_trash(self):
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
                        title = note.title
                        timestamp = QDateTime.fromString(note.timestamp, Qt.ISODate)
                        date_str = timestamp.toString("dd.MM.yyyy")
                        item_text = f"{title} — {date_str} 🗑"
                        item = QListWidgetItem(item_text)
                        item.setData(Qt.UserRole, note)
                        item.setForeground(QColor("gray"))
                        self.notes_list.addItem(item)

    def restore_note_from_trash(self):
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
            "Notes", NotesApp.safe_folder_name(note.title, note.uuid, note.timestamp)
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

    def delete_note_permanently(self):
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

    def empty_trash(self):
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

    def load_note(self, item):
        if item is None:
            self.text_edit.clear()
            self.text_edit.setReadOnly(True)
            self.text_edit.hide()
            self.tags_label.setText("Теги: нет")
            self.current_note = None
            return
        note = item.data(Qt.ItemDataRole.UserRole)
        self.select_note(note)

    def select_note(self, note):
        self.text_edit.show()
        if hasattr(self, "current_note") and self.current_note:
            self.current_note.content = self.text_edit.toHtml()
            self.save_note_to_file(self.current_note)
        self.current_note = note

        if (
            not hasattr(note, "history")
            or note.history is None
            or len(note.history) == 0
        ):
            note.history = [note.content]
            note.history_index = 0
        self.update_history_list()
        self.update_history_list_selection()

        self.show_note_with_attachments(note)
        self.text_edit.setReadOnly(False)
        self.tags_label.setText(f"Теги: {', '.join(note.tags) if note.tags else 'нет'}")

    def show_note_with_attachments(self, note):
        if self.current_note:
            note = self.current_note
            self.text_edit.setHtml(note.content)
            note_dir = os.path.join("Notes", note.uuid)
            if not os.path.isdir(note_dir):
                return
            attachments = ""
            ignored_files = {"note.json", ".DS_Store", "Thumbs.db"}
            for file in os.listdir(note_dir):
                if file in ignored_files:
                    continue
                file_path = os.path.join(note_dir, file)
                if file.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif")):
                    continue
                else:
                    link = f'<a href="file://{file_path}">{file}</a>'
                    attachments += link + "<br>"
            if attachments and "--- Attachments ---" not in note.content:
                note.content += "<br>--- Attachments ---<br>" + attachments
                self.text_edit.setHtml(note.content)

    def attach_file_to_note(self):
        if not self.current_note:
            return
        file_path, _ = QFileDialog.getOpenFileName(self, "Прикрепить файл")
        if not file_path:
            return
        note_dir = os.path.join("Notes", self.current_note.uuid)
        os.makedirs(note_dir, exist_ok=True)
        filename = os.path.basename(file_path)
        dest = os.path.join(note_dir, filename)
        try:
            shutil.copy(file_path, dest)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось скопировать файл: {e}")
            return
        is_image = filename.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif"))
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
            from urllib.parse import quote

            url = "file:///" + quote(os.path.abspath(dest).replace(os.sep, "/"))
            self.text_edit.insertHtml(f'📄 <a href="{url}">{filename}</a><br>')

        self.save_note()
        QMessageBox.information(
            self, "Файл прикреплён", f"Файл '{filename}' прикреплён к заметке."
        )

    def align_left(self):
        self.text_edit.setAlignment(Qt.AlignLeft)

    def align_center(self):
        self.text_edit.setAlignment(Qt.AlignCenter)

    def align_right(self):
        self.text_edit.setAlignment(Qt.AlignRight)

    def change_font(self, font):
        self.text_edit.setCurrentFont(font)

    def change_font_size(self, size):
        cursor = self.text_edit.textCursor()
        fmt = QTextCharFormat()
        fmt.setFontPointSize(size)
        if cursor.hasSelection():
            cursor.mergeCharFormat(fmt)
        else:
            self.text_edit.setCurrentCharFormat(fmt)

    def _current_font_size(self, cursor):
        size = cursor.charFormat().fontPointSize()
        if not size:
            size = self.text_edit.fontPointSize() or 14
        return size

    def toggle_bold(self):
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

    def toggle_italic(self):
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

    def toggle_underline(self):
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

    def change_text_color(self):
        color = QColorDialog.getColor(Qt.black, self.text_edit, "Выберите цвет текста")
        if color.isValid():
            cursor = self.text_edit.textCursor()
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            if cursor.hasSelection():
                cursor.mergeCharFormat(fmt)
            else:
                self.text_edit.setCurrentCharFormat(fmt)

    def change_background_color(self):
        color = QColorDialog.getColor(Qt.white, self.text_edit, "Выберите цвет фона")
        if color.isValid():
            cursor = self.text_edit.textCursor()
            fmt = QTextCharFormat()
            fmt.setBackground(color)
            if cursor.hasSelection():
                cursor.mergeCharFormat(fmt)
            else:
                self.text_edit.setCurrentCharFormat(fmt)

    def clear_formatting_complete(self):
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

    def apply_formatting(self, **kwargs):
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

    def update_font_controls(self):
        cursor = self.text_edit.textCursor()
        fmt = cursor.charFormat()
        font = fmt.font()
        family = font.family() if font.family() else "Times New Roman"
        size = int(font.pointSize() if font.pointSize() > 0 else 14)
        self.font_combo.setCurrentFont(QFont(family))
        self.font_size_spin.setValue(size)

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

    def set_font_family(self, font_family):
        cursor = self.text_edit.textCursor()
        fmt = QTextCharFormat()
        fmt.setFontFamily(font_family)
        if cursor.hasSelection():
            cursor.mergeCharFormat(fmt)
        else:
            self.text_edit.setCurrentCharFormat(fmt)

    def toggle_strikethrough(self):
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

    def toggle_case(self):
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            text = cursor.selectedText()
            text = text.swapcase()
            cursor.insertText(text)

    def insert_bullet_list(self):
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            selection_start = cursor.selectionStart()
            selection_end = cursor.selectionEnd()
            cursor.setPosition(selection_start)
            cursor.setPosition(selection_end, QTextCursor.KeepAnchor)
            block_format = QTextListFormat()
            block_format.setStyle(QTextListFormat.ListDisc)
            cursor.createList(block_format)
        else:
            cursor.insertText("• ")

    def insert_numbered_list(self):
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            selection_start = cursor.selectionStart()
            selection_end = cursor.selectionEnd()
            cursor.setPosition(selection_start)
            cursor.setPosition(selection_end, QTextCursor.KeepAnchor)
            block_format = QTextListFormat()
            block_format.setStyle(QTextListFormat.ListDecimal)
            cursor.createList(block_format)
        else:
            cursor.insertText("1. ")

    def insert_checkbox(self):
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

    def insert_horizontal_line(self):
        cursor = self.text_edit.textCursor()
        cursor.insertHtml("<hr style='border:1px solid #888;'><br>")
        cursor.movePosition(QTextCursor.EndOfBlock)
        self.text_edit.setTextCursor(cursor)

    def insert_image_html(self, html_img, replace_current=False, orig_path=None):
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
            self.text_edit.insertHtml(html_img)
            self.record_state_for_undo()

    def insert_image_into_note(self, image_path):
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            pixmap.save(buffer, "PNG")
            base64_data = base64.b64encode(buffer.data()).decode("utf-8")
            html_img = (
                f'<img src="Data:image/png;base64,{base64_data}" width="300"><br>'
            )
            self.text_edit.insertHtml(html_img)
            self.record_state_for_undo()

    def insert_image_from_clipboard(self, image: QImage):
        if not self.current_note:
            QMessageBox.warning(
                self, "Нет заметки", "Пожалуйста, выберите или создайте заметку."
            )
            return
        note_dir = os.path.join("Notes", self.current_note.uuid)
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
            self.text_edit.insertHtml(html_img)
            self.record_state_for_undo()

        self.save_note()

    def insert_audio_link(self, filepath):
        filename = os.path.basename(filepath)
        url = "file:///" + quote(os.path.abspath(filepath).replace(os.sep, "/"))
        self.text_edit.insertHtml(f'📄 <a href="{url}">{filename}</a>')
        self.save_note()

    def toggle_audio_recording(self):
        if self.audio_thread and self.audio_thread.isRunning():
            self.audio_thread.stop()
            self.audio_thread.wait()
            self.audio_thread = None
            self.audio_button.setText("🎤")
        else:
            filename = str(uuid.uuid4()) + ".wav"
            folder_path = os.path.join("Notes", "Audio")
            os.makedirs(folder_path, exist_ok=True)
            full_path = os.path.join(folder_path, filename)

            self.audio_thread = AudioRecorderThread(full_path)
            self.audio_thread.recording_finished.connect(self.insert_audio_link)
            self.audio_thread.start()
            self.audio_button.setText("⏹")

    def apply_sorting(self):
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

    def refresh_notes_list(self):
        self.notes_list.clear()
        pinned_notes = [note for note in self.notes if note.pinned]
        unpinned_notes = [note for note in self.notes if not note.pinned]
        for note in pinned_notes + unpinned_notes:
            title = note.title
            timestamp = QDateTime.fromString(note.timestamp, Qt.ISODate)
            date_str = timestamp.toString("dd.MM.yyyy")
            reminder_symbol = " 🔔" if note.reminder else ""
            item_text = f"{title} — {date_str}{reminder_symbol}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, note)
            item.setFont(QFont("Segoe UI Emoji", 10))
            if note.favorite:
                item.setForeground(QColor("gold"))
            self.notes_list.addItem(item)

    def sort_notes_by_title(self):
        self.notes.sort(key=lambda note: note.title.lower())
        self.refresh_notes_list()

    def sort_notes_by_date(self):
        self.notes.sort(key=lambda note: note.timestamp, reverse=True)
        self.refresh_notes_list()

    def toggle_favorite(self):
        if self.current_note:
            self.current_note.favorite = not self.current_note.favorite
            self.refresh_notes_list()

    def show_favorites_only(self):
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

    def add_tag_to_note(self):
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

    def manage_tags_dialog(self):
        dialog = QDialog(self)
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

    def get_all_tags(self):
        tags = set()
        for note in self.notes:
            tags.update(note.tags)
        return sorted(tags)

    def show_all_notes(self):
        self.refresh_notes_list()

    def show_notes_by_tag(self, tag):
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

    def apply_tag_filter(self):
        selected_tag = self.tag_filter.currentText()
        if selected_tag == "Все теги" or not selected_tag:
            self.show_all_notes()
        else:
            self.show_notes_by_tag(selected_tag)

    def insert_link(self):
        cursor = self.text_edit.textCursor()
        url, ok = QInputDialog.getText(self, "Вставить ссылку", "URL:")
        if ok and url:
            fmt = QTextCharFormat()
            fmt.setAnchor(True)
            fmt.setAnchorHref(url)
            fmt.setForeground(Qt.blue)
            fmt.setFontUnderline(True)
            if cursor.hasSelection():
                cursor.mergeCharFormat(fmt)
            else:
                cursor.select(QTextCursor.WordUnderCursor)
                if cursor.selectedText().strip():
                    cursor.mergeCharFormat(fmt)
                    self.text_edit.setTextCursor(cursor)
                else:
                    cursor.insertHtml(f'<a href="{url}">{url}</a>')

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

        toggle_fav_button = QPushButton("⭐")
        toggle_fav_button.setToolTip("⭐ - Добавить/удалить из избранного")
        toggle_fav_button.clicked.connect(self.toggle_favorite)
        flow_layout.addWidget(toggle_fav_button)
        add_tool_button("", "🗑 - Корзина", self.show_trash)
        add_tool_button("", "➕ - Новая", self.create_new_note)
        add_tool_button("", "💾 - Сохранить", self.save_note)
        add_tool_button("", "❌ - Удалить", self.delete_note)
        add_tool_button("📎", "📎 - Приерепть файл", self.attach_file_to_note)
        add_tool_button("", "🖼 - Картинка", self.attach_file_to_note)
        add_tool_button(
            "", "🔧 - Вставить UPD/BASE/USER/RESULT/DETAILS", self.insert_update_block
        )
        self.audio_button = QPushButton("🎤")
        self.audio_button.setToolTip("🎤 - Записать аудио")
        self.audio_button.setFixedSize(32, 32)
        self.audio_button.clicked.connect(self.toggle_audio_recording)
        flow_layout.addWidget(self.audio_button)
        add_tool_button("", "𝐁 - Жирный", self.toggle_bold)
        add_tool_button("", "𝐼 - Курсив", self.toggle_italic)
        add_tool_button("", "U̲ - Подчёркнутый", self.toggle_underline)
        add_tool_button("", "🧹 - Сбросить формат", self.clear_formatting)
        add_tool_button("", "🌈 - Цвет текста", self.change_text_color)
        add_tool_button("", "🅰️ - Фон текста", self.change_background_color)
        add_tool_button("", "← - Расположить слева", self.align_left)
        add_tool_button("", "→← - Центрировать", self.align_center)
        add_tool_button("", "→ - Расположить справа", self.align_right)
        add_tool_button("", "Aa - Изменить регистр", self.toggle_case)
        add_tool_button("", "• - маркированный  список", self.insert_bullet_list)
        add_tool_button("", "1. - нумерованный список", self.insert_numbered_list)
        add_tool_button("", "☑ - чекбокс", self.insert_checkbox)
        add_tool_button("", "📅 - Таблица", self.insert_table)
        add_tool_button("", "🔗 - Ссылка", self.insert_link)
        add_tool_button("", "▁ - Горизонтальная линия", self.insert_horizontal_line)
        add_tool_button("", "+🏷 - Добавить тег", self.add_tag_to_note)
        mass_reminders_btn = QPushButton("🗓️ Массовые напоминания")
        mass_reminders_btn.clicked.connect(self.open_mass_reminders_dialog)
        flow_layout.addWidget(mass_reminders_btn)
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
        add_tool_button("", "⚙ - Настройки", self.show_settings_window)
        add_tool_button("", "❓ - Справка", self.show_help_window)
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
        remove_reminder_button = QPushButton("Удалить напоминание")
        remove_reminder_button.clicked.connect(self.remove_reminder_from_note)
        reminder_layout.addWidget(reminder_button)
        reminder_layout.addWidget(remove_reminder_button)
        bottom_toolbar_widget = QWidget()
        bottom_toolbar_widget.setLayout(reminder_layout)
        full_layout.addWidget(top_toolbar_widget)
        full_layout.addWidget(bottom_toolbar_widget)
        self.toolbar_scroll = QScrollArea()
        self.toolbar_scroll.setWidget(full_toolbar_widget)
        self.toolbar_scroll.setWidgetResizable(True)
        self.toolbar_scroll.setMaximumHeight(140)
        self.toolbar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.toolbar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.search_bar.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    def open_mass_reminders_dialog(self):
        dialog = QDialog(self)
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
            lambda: self.mass_remove_reminders(list_widget, dialog)
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
            QMessageBox.information(self, "Готово", "Выбранные напоминания удалены.")
            dialog.accept()

    def rebuild_toolbar(self):
        if hasattr(self, "dock_toolbar") and self.dock_toolbar:
            self.removeDockWidget(self.dock_toolbar)
            self.dock_toolbar.deleteLater()
        self.init_toolbar()
        self.dock_toolbar = QDockWidget("Панель инструментов", self)
        self.dock_toolbar.setObjectName("dock_toolbar")
        self.dock_toolbar.setWidget(self.toolbar_scroll)
        self.dock_toolbar.setAllowedAreas(
            Qt.TopDockWidgetArea | Qt.BottomDockWidgetArea
        )
        self.addDockWidget(Qt.TopDockWidgetArea, self.dock_toolbar)

    def show_note_context_menu(self, position):
        item = self.notes_list.itemAt(position)
        if not item:
            return
        note = item.data(Qt.UserRole)
        menu = QMenu()
        toggle_pin_action = QAction(
            "Закрепить" if not note.pinned else "Открепить", self
        )
        toggle_pin_action.triggered.connect(lambda: self.toggle_pin(note))
        menu.addAction(toggle_pin_action)
        open_action = QAction("Открыть", self)
        delete_action = QAction("Удалить", self)
        rename_action = QAction("Переименовать", self)
        copy_action = QAction("Копировать", self)
        open_action.triggered.connect(lambda: self.select_note(note))
        delete_action.triggered.connect(lambda: self.confirm_delete_note(note))
        rename_action.triggered.connect(lambda: self.rename_note(note))
        copy_action.triggered.connect(lambda: self.copy_note(note))
        menu.addAction(open_action)
        menu.addAction(rename_action)
        menu.addAction(copy_action)
        menu.addSeparator()
        menu.addAction(delete_action)
        menu.exec(self.notes_list.viewport().mapToGlobal(position))

    def attach_docks(self, dock1, dock2):
        self.tabifyDockWidget(dock1, dock2)
        dock2.show()
        dock1.raise_()

    def detach_dock(self, dock):
        dock.setFloating(True)
        dock.show()

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

        detach_action = menu.addAction("Открепить")
        detach_action.triggered.connect(lambda: self.detach_dock(dock))

        menu.exec(dock.mapToGlobal(position))

    def clear_formatting(self):
        cursor = self.text_edit.textCursor()
        palette = self.text_edit.palette()
        default_bg_color = palette.color(QPalette.Base)
        default_text_color = palette.color(QPalette.Text)
        if cursor.hasSelection():
            selected_text = cursor.selectedText()
            fmt = QTextCharFormat()
            fmt.setFontWeight(QFont.Normal)
            fmt.setFontItalic(False)
            fmt.setFontUnderline(False)
            fmt.setFontStrikeOut(False)
            fmt.setForeground(default_text_color)
            fmt.setBackground(default_bg_color)
            fmt.setFontPointSize(14)
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
            fmt.setBackground(default_bg_color)
            fmt.setFontPointSize(14)
            cursor.insertText(selected_text, fmt)

    def toggle_pin(self, note):
        note.pinned = not note.pinned
        self.save_note_to_file(note)
        self.refresh_notes_list()

    def add_menu_bar(self):
        menu_bar = self.menuBar()
        plugins_menu = menu_bar.addMenu("Плагины")
        manage_plugins_action = QAction("Управление плагинами", self)
        manage_plugins_action.triggered.connect(self.manage_plugins_dialog)
        plugins_menu.addAction(manage_plugins_action)
        reload_plugins_action = QAction("Перезагрузить плагины", self)
        reload_plugins_action.triggered.connect(self.load_plugins)
        plugins_menu.addAction(reload_plugins_action)
        notes_menu = self.menuBar().addMenu("Заметки")
        show_all_notes_action = QAction("Показать все заметки", self)
        show_all_notes_action.triggered.connect(self.show_all_notes)
        notes_menu.addAction(show_all_notes_action)
        file_menu = menu_bar.addMenu("Файл")
        help_menu = menu_bar.addMenu("Справка")
        settings_menu = menu_bar.addMenu("Настройки")
        view_menu = menu_bar.addMenu("Вид")
        for dock, name in [
            (self.dock_notes_list, "Заметки"),
            (self.dock_history, "История"),
            (self.dock_buttons, "Кнопки"),
            (self.dock_editor, "Редактор"),
            (self.dock_toolbar, "Панель инструментов"),
        ]:
            action = dock.toggleViewAction()
            action.setText(name)
            view_menu.addAction(action)
        export_action = QAction("Экспорт...", self)
        export_action.triggered.connect(self.export_note)
        file_menu.addAction(export_action)
        import_action = QAction("Импорт...", self)
        import_action.triggered.connect(self.import_note)
        file_menu.addAction(import_action)
        help_action = QAction("Справка", self)
        help_action.setShortcut("F1")
        help_action.triggered.connect(self.show_help_window)
        help_menu.addAction(help_action)
        settings_action = QAction("Настройки:", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self.show_settings_window)
        settings_menu.addAction(settings_action)
        trash_menu = self.menuBar().addMenu("Корзина")
        show_trash_action = QAction("Показать корзину", self)
        show_trash_action.triggered.connect(self.show_trash)
        trash_menu.addAction(show_trash_action)
        restore_action = QAction("Восстановить заметку", self)
        restore_action.triggered.connect(self.restore_note_from_trash)
        trash_menu.addAction(restore_action)
        delete_forever_action = QAction("Удалить безвозвратно", self)
        delete_forever_action.triggered.connect(self.delete_note_permanently)
        trash_menu.addAction(delete_forever_action)
        empty_trash_action = QAction("Очистить корзину", self)
        empty_trash_action.triggered.connect(self.empty_trash)
        trash_menu.addAction(empty_trash_action)

    def show_settings_window(self):
        dialog = QDialog(self)
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
            self.init_theme()

    def show_help_window(self):

        dialog = QDialog(self)
        dialog.setWindowTitle("Справка — Мои Заметки")
        dialog.setMinimumSize(600, 620)

        layout = QVBoxLayout(dialog)
        browser = QTextBrowser(dialog)
        browser.setOpenExternalLinks(True)

        browser.setHtml(
            f"""
            <h2 style="text-align:center;">🗒️ Справка</h2>
            <h3>Горячие клавиши</h3>
            <ul>
            <li><b>Ctrl+N</b> — новая заметка</li>
            <li><b>Ctrl+S</b> — сохранить заметку</li>
            <li><b>Ctrl+B</b> — жирный текст</li>
            <li><b>Ctrl+I</b> — курсив</li>
            <li><b>Ctrl+U</b> — подчёркнутый текст</li>
            <li><b>Ctrl+Z</b> — отмена действия (Undo)</li>
            <li><b>Ctrl+Y</b> — повтор действия (Redo)</li>
            <li><b>Ctrl+Space</b> — сбросить форматирование выделенного текста</li>
            <li><b>Ctrl+V</b> — вставить (текст, изображения из буфера обмена)</li>
            <li><b>Delete</b> — удалить выделенную заметку (в корзину)</li>
            <li><b>Escape</b> — выйти из текущей заметки</li>
            <li><b>Ctrl + Клик по картинке</b> — открыть редактор изображения</li>
            <li><b>ПКМ по заметке</b> — контекстное меню: открыть, удалить, переименовать, копировать, закрепить</li>
            </ul>
            <h3>Форматирование текста</h3>
            <ul>
            <li><b>𝐁</b> — сделать текст жирным</li>
            <li><b>𝐼</b> — сделать текст курсивом</li>
            <li><b>U̲</b> — подчеркнуть текст</li>
            <li><b>🌈</b> — изменить цвет текста</li>
            <li><b>🅰️</b> — изменить цвет фона текста</li>
            <li><b>🧹</b> — сбросить всё форматирование (очистить все стили)</li>
            <li><b>🔗</b> — вставить гиперссылку</li>
            <li><b>•</b> — вставить маркированный список</li>
            <li><b>1.</b> — вставить нумерованный список</li>
            <li><b>☑</b> — вставить чекбокс (можно отмечать кликом)</li>
            <li><b>▁</b> — вставить горизонтальную линию</li>
            <li><b>📅</b> — вставить таблицу (с настройкой количества строк и столбцов)</li>
            <li><b>🔧</b> — вставить блок "UPD" с датой и полями Base/User/Result/Details</li>
            </ul>
            <h3>Работа с изображениями и файлами</h3>
            <ul>
            <li><b>📎</b> — прикрепить файл (любой формат)</li>
            <li><b>🖼️</b> — вставить изображение из файла</li>
            <li><b>🖊️</b> — открыть редактор изображений:
            <ul>
            <li>рисование, выбор цвета и толщины линии, отмена и повтор действий (Undo/Redo)</li>
            <li>очистка холста, вставка изображения в заметку</li>
            </ul>
            </li>
            <li>Изображения можно вставлять drag&drop и из буфера обмена</li>
            </ul>
            <h3>Аудиозаметки</h3>
            <ul>
            <li><b>🎤</b> — запись аудио с микрофона (вставляется как ссылка)</li>
            </ul>
            <h3>Теги, фильтрация и сортировка</h3>
            <ul>
            <li><b>+🏷</b> — добавить теги к текущей заметке</li>
            <li><b>🏷</b> — управление тегами (переименовать, удалить)</li>
            <li>Фильтрация заметок по тегам и поиск по заголовку или содержимому</li>
            <li>Сортировка заметок по названию, дате создания, избранным</li>
            <li><b>⭐</b> — добавить/убрать заметку из избранного</li>
            <li>Закрепление заметок вверху списка</li>
            </ul>
            <h3>Напоминания</h3>
            <ul>
            <li>Установка напоминаний с вариантами повторения: однократно, по будням, ежедневно, еженедельно, ежемесячно</li>
            <li>Удаление напоминаний из заметок</li>
            </ul>
            <h3>Корзина</h3>
            <ul>
            <li>Удалённые заметки помещаются в корзину</li>
            <li>Возможность восстановления заметок из корзины</li>
            <li>Удаление заметок из корзины навсегда (по одной или сразу всех)</li>
            </ul>
            <h3>Экспорт и импорт</h3>
            <ul>
            <li>Экспорт заметок в архив (ZIP-файл с содержимым)</li>
            <li>Импорт заметок из архивов ZIP</li>
            </ul>
            <h3>Настройки и интерфейс</h3>
            <ul>
            <li>Настройка темы интерфейса (светлая/тёмная)</li>
            <li>Настройка автосохранения (интервал в секундах)</li>
            <li>Сохранение и восстановление положения и размера панелей и окон</li>
            <li>Панели можно закрывать и открывать через меню "Вид"</li>
            </ul>
            <hr>
            <div style="text-align:center; color:#888;">
            Автор: Никита Постнов | Версия приложения: <b>1.8</b>
            </div>
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
                # НЕ append, а перезагрузка из файлов:
                self.load_notes_from_disk()
                self.refresh_notes_list()
                QMessageBox.information(
                    self, "Импорт", "Заметка успешно импортирована."
                )
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Ошибка импорта: {e}")

    def trigger_search(self):
        self.handle_combined_search()

    def check_reminders(self):
        now = QDateTime.currentDateTime()
        updated = False
        for note in self.notes:
            if not note.reminder or getattr(note, 'reminder_shown', False):
                continue

            reminder_time = QDateTime.fromString(note.reminder, Qt.ISODate)
            if reminder_time <= now:
                if self.tray_icon:
                    self.tray_icon.showMessage(
                        f"Напоминание: {note.title}",
                        f"Напоминание по заметке: {note.title}\nВремя: {note.reminder}",
                        QSystemTrayIcon.Information,
                        5000
                    )
                note.reminder_shown = True
                if not note.reminder_repeat:
                    note.reminder = None
                    note.reminder_shown = False
                    self.save_note_to_file(note)
                    self.load_notes_from_disk()
                    updated = True
                else:
                    reminder_time = QDateTime.fromString(note.reminder, Qt.ISODate)
                    if note.reminder_repeat == "day":
                        next_reminder = reminder_time.addDays(1)
                    elif note.reminder_repeat == "week":
                        next_reminder = reminder_time.addDays(7)
                    elif note.reminder_repeat == "month":
                        next_reminder = reminder_time.addMonths(1)
                    elif note.reminder_repeat == "year":
                        next_reminder = reminder_time.addYears(1)
                    else:
                        next_reminder = None
                    if next_reminder:
                        note.reminder = next_reminder.toString(Qt.ISODate)
                        note.reminder_shown = False
                        self.save_note_to_file(note)
                        self.load_notes_from_disk()
                        updated = True
        if updated:
            self.refresh_notes_list()

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
        note_dir = os.path.join("Notes", self.current_note.uuid)
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
            self.text_edit.append("\n--- Attachments ---\n" + attachment_links)

    def update_tag_filter_items(self):
        all_tags = sorted(self.get_all_tags())
        self.tag_filter.clear()
        self.tag_filter.addItem("Все теги")
        self.tag_filter.addItems(all_tags)

    def set_reminder_for_note(self):
        if not self.current_note:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Установить напоминание")
        layout = QFormLayout(dialog)
        datetime_edit = QDateTimeEdit(QDateTime.currentDateTime())
        datetime_edit.setCalendarPopup(True)
        layout.addRow("Напоминание Date & Time:", datetime_edit)
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
                    QMessageBox.information(
                        self, "Напоминание", f"Напоминание для заметки: {note.title}"
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
        QShortcut(QKeySequence("Delete"), self, self.delete_note)
        QShortcut(QKeySequence("Delete"), self.notes_list, self.delete_note)
        self.load_notes_from_disk()
        self.refresh_notes_list()
        self.update_tag_filter_items()
        self.setup_reminder_timer()
        self.setAcceptDrops(True)
        self.autosave_enabled = self.settings.value("autosave_enabled", True, type=bool)
        self.autosave_interval = self.settings.value(
            "autosave_interval", 300000, type=int
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
        self.notes_list.setStyleSheet("color: white; background-color: #2b2b2b;")
        self.text_edit.setStyleSheet(
            "font-size: 14px; color: white; background-color: #2b2b2b;"
        )
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
                            """
        )
        self.rebuild_toolbar()

    def exit_note(self):
        self.text_edit.clear()
        self.text_edit.setReadOnly(True)
        self.text_edit.hide()
        self.tags_label.setText("Теги: нет")
        self.current_note = None
        self.notes_list.clearSelection()

    def apply_light_theme(self):
        self.setStyle(QStyleFactory.create("Fusion"))
        default_palette = QApplication.style().standardPalette()
        QApplication.instance().setPalette(default_palette)
        self.notes_list.setStyleSheet("color: black; background-color: white;")
        self.text_edit.setStyleSheet(
            "font-size: 14px; color: black; background-color: white;"
        )
        self.new_note_button.setStyleSheet("")
        self.save_note_button.setStyleSheet("")
        self.delete_note_button.setStyleSheet("")
        self.audio_button.setStyleSheet("")
        self.menuBar().setStyleSheet("")
        self.setStyleSheet(
            """
                                QToolTip {
                                    background-color: #ffffff;
                                    color: #000000;
                                    border: 1px solid #999;
                                    padding: 5px;
                                    font-size: 12px;
                                }"""
        )
        self.rebuild_toolbar()

    def autosave_current_note(self):
        for note in self.notes:
            if note == self.current_note:
                note.content = self.text_edit.toHtml()
            self.save_note_to_file(note)

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
                note_dir = os.path.join("Notes", self.current_note.uuid)
                if not os.path.exists(note_dir):
                    os.makedirs(note_dir)
                filename = os.path.basename(file_path)
                dest = os.path.join(note_dir, filename)
                shutil.copy(file_path, dest)
                if filename.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif")):
                    pixmap = QPixmap(dest)
                    if not pixmap.isNull():
                        buffer = QBuffer()
                        buffer.open(QIODevice.WriteOnly)
                        pixmap.save(buffer, "PNG")
                        base64_data = base64.b64encode(buffer.data()).decode("utf-8")
                        html_img = f'<img src="Data:image/png;base64,{base64_data}" width="200"><br>'
                        self.text_edit.insertHtml(html_img)
                        self.record_state_for_undo()
                else:
                    url = "file:///" + quote(os.path.abspath(dest).replace(os.sep, "/"))
                    self.text_edit.insertHtml(f'📄 <a href="{url}">{filename}</a><br>')
        self.save_note()
        QMessageBox.information(
            self, "Перетаскивание файлов", "Файлы прикреплены к заметке."
        )

    def closeEvent(self, event: QCloseEvent):
        self.save_settings()
        if hasattr(self, "autosave_timer") and self.autosave_timer.isActive():
            self.autosave_timer.stop()
        if hasattr(self, "reminder_timer") and self.reminder_timer.isActive():
            self.reminder_timer.stop()
        if self.audio_thread and self.audio_thread.isRunning():
            self.audio_thread.stop()
            self.audio_thread.wait()
            self.audio_thread = None
        super().closeEvent(event)

    def load_plugins(self):
        load_plugins(self)

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
        dialog = QDialog(self)
        dialog.setWindowTitle("Управление плагинами")
        dialog.setMinimumSize(500, 300)
        layout = QVBoxLayout(dialog)
        plugins_folder = "Plugins"
        os.makedirs(plugins_folder, exist_ok=True)
        list_widget = QListWidget(dialog)
        plugins = [f for f in os.listdir(plugins_folder) if f.endswith(".py")]
        list_widget.addItems(plugins)
        layout.addWidget(list_widget)
        btn_add = QPushButton("Добавить плагин")

        def add_plugin():
            file_path, _ = QFileDialog.getOpenFileName(
                self, "Выберите .py файл плагина", "", "Python Files (*.py)"
            )
            if file_path:
                dest_path = os.path.join(plugins_folder, os.path.basename(file_path))
                if os.path.exists(dest_path):
                    QMessageBox.warning(
                        self, "Ошибка", "Плагин с таким именем уже существует."
                    )
                    return
                shutil.copy(file_path, dest_path)
                list_widget.addItem(os.path.basename(file_path))
                QMessageBox.information(self, "Готово", "Плагин добавлен.")
                self.load_plugins()

        btn_add.clicked.connect(add_plugin)
        btn_del = QPushButton("Удалить плагин")

        def del_plugin():
            item = list_widget.currentItem()
            if not item:
                QMessageBox.warning(self, "Нет выбора", "Выберите плагин для удаления.")
                return
            fname = item.text()
            path = os.path.join(plugins_folder, fname)
            if os.path.exists(path):
                reply = QMessageBox.question(
                    self,
                    "Удалить плагин",
                    f"Удалить плагин {fname}?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if reply == QMessageBox.Yes:
                    os.remove(path)
                    list_widget.takeItem(list_widget.row(item))
                    QMessageBox.information(self, "Готово", "Плагин удалён.")
                    self.load_plugins()

        btn_del.clicked.connect(del_plugin)
        btn_rename = QPushButton("Переименовать плагин")

        def rename_plugin():
            item = list_widget.currentItem()
            if not item:
                QMessageBox.warning(
                    self, "Нет выбора", "Выберите плагин для переименования."
                )
                return
            old_name = item.text()
            new_name, ok = QInputDialog.getText(
                self, "Переименовать плагин", "Новое имя файла (с .py):", text=old_name
            )
            if ok and new_name and new_name.endswith(".py") and new_name != old_name:
                old_path = os.path.join(plugins_folder, old_name)
                new_path = os.path.join(plugins_folder, new_name)
                if os.path.exists(new_path):
                    QMessageBox.warning(
                        self, "Ошибка", "Файл с таким именем уже существует."
                    )
                    return
                os.rename(old_path, new_path)
                item.setText(new_name)
                QMessageBox.information(self, "Готово", "Плагин переименован.")
                self.load_plugins()

        btn_rename.clicked.connect(rename_plugin)
        btns = QHBoxLayout()
        btns.addWidget(btn_add)
        btns.addWidget(btn_del)
        btns.addWidget(btn_rename)
        layout.addLayout(btns)
        btn_close = QPushButton("Закрыть")
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close)
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
        self.clear_plugin_menu_actions()
        load_plugins(self)

    def closeEvent(self, event):
        self.save_settings()
        if not getattr(self, "exiting", False) and self.tray_icon and self.tray_icon.isVisible():
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                "Мои Заметки",
                "Приложение свернуто в трей и продолжает работать.",
                QSystemTrayIcon.Information,
                2000
            )
        else:
            if hasattr(self, "autosave_timer") and self.autosave_timer.isActive():
                self.autosave_timer.stop()
            if hasattr(self, "reminder_timer") and self.reminder_timer.isActive():
                self.reminder_timer.stop()
            if self.audio_thread and self.audio_thread.isRunning():
                self.audio_thread.stop()
                self.audio_thread.wait()
                self.audio_thread = None
            super().closeEvent(event)

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


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    window = NotesApp()
    window.show()
    sys.exit(app.exec())
