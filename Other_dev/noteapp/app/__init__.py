"""Ядро приложения «Мои Заметки»: класс NotesApp, точка входа main() и bootstrap.

Перенесено из монолита notes_app.py (step 4.1). notes_app.py теперь тонкий лаунчер.
"""

import os
import json
import re
import sys
import base64
from uuid import uuid4
import tempfile
import uuid
import shutil
import datetime
from typing import Callable
import ctypes
from pathlib import Path
import logging
logging.getLogger("telethon.crypto.libssl").setLevel(logging.WARNING)
logging.getLogger("telethon.crypto.aes").setLevel(logging.WARNING)
import threading

from PySide6.QtCore import (
    Qt,
    QTimer,
    QUrl,
    QDate,
    QSettings,
    QSize,
    QEvent,
    QDateTime,
    QPoint,
    QThread,
    Signal,
    QBuffer,
    QIODevice,
)
from PySide6.QtGui import (
    QTextOption,
    QIcon,
    QCursor,
    QShortcut,
    QFont,
    QPixmap,
    QKeySequence,
    QCloseEvent,
    QAction,
    QColor,
    QTextCharFormat,
    QDesktopServices,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QMainWindow,
    QTextEdit,
    QProgressBar,
    QVBoxLayout,
    QHBoxLayout,
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
    QSpinBox,
    QScrollArea,
    QFontComboBox,
    QDialog,
    QDialogButtonBox,
    QComboBox,
    QCheckBox,
    QAbstractItemView,
    QMenu,
    QSplitter,
    QToolBar,
    QDockWidget,
    QToolButton,
    QFrame,
)

# --- вынесено в пакет noteapp (миграция монолита) ---
from noteapp.config import (
    APPDIR, DATA_DIR, NOTES_DIR, PASSWORDS_DIR, SETTINGS_PATH,
    ICON_PATH, USER_DICT_PATH, LOG_PATH, qt_path,
    resolve_rammap_exe,
)
from noteapp.constants import (
    MAX_HISTORY, IMAGE_EXTENSIONS,
)
from noteapp.logging_setup import (
    _setup_crash_logging, install_exception_hooks,
    install_qt_message_handler,
)
from noteapp.utils import (
    strip_html, copy_default_icons, safe_folder_name,
)
from noteapp.models import Note
from noteapp.generators import NumberGenerator
from noteapp.widgets.flow_layout import FlowLayout
from noteapp.widgets.spellcheck import SpellCheckHighlighter
from noteapp.widgets.text_edit import CustomTextEdit
from noteapp.widgets.dialogs import NumberGeneratorDialog
from noteapp.central_proxy import _CentralWidgetProxy
from noteapp.threads import AudioRecorderThread, NotesLoaderThread
# --- конец блока миграции ---
from .persistence import NotePersistenceMixin
from .plugins import PluginsMixin
from .reminders import RemindersMixin
from .tray import TrayMixin
from .autosave import AutosaveMixin
from .templates import TemplatesMixin
from .settings import SettingsMixin
from .search import SearchMixin
from .dropdowns import DropdownsMixin
from .images import ImagesMixin
from .editor import EditorMixin
from .layout import LayoutMixin

try:
    from PySide6.QtCore import qInstallMessageHandler, QtMsgType
except Exception:
    qInstallMessageHandler = None
    QtMsgType = None


def init_app_environment() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    PASSWORDS_DIR.mkdir(parents=True, exist_ok=True)

    if not USER_DICT_PATH.exists():
        USER_DICT_PATH.touch()

    _setup_crash_logging(LOG_PATH)
    install_exception_hooks()
    install_qt_message_handler()

    copy_default_icons()

    logging.info("=== APP START ===")


class NotesApp(NotePersistenceMixin, PluginsMixin, RemindersMixin, TrayMixin, AutosaveMixin, TemplatesMixin, SettingsMixin, SearchMixin, DropdownsMixin, ImagesMixin, EditorMixin, LayoutMixin, QMainWindow):
    TRASH_DIR: Path = NOTES_DIR / "Trash"
    window_hidden = Signal()

    def __init__(self):
        super().__init__()
        self.notes_folder = NOTES_DIR
        self.text_edit: CustomTextEdit | None = None
        self.tags_label: QLabel | None = None
        self.attachments_panel: QWidget | None = None
        self.attachments_layout: QHBoxLayout | None = None
        self.attachments_scroll: QScrollArea | None = None
        self.current_note_path = None
        self.timer_btn = None
        self._live_toasts: list[QLabel] = []
        self.exiting = False
        self.notes = []
        self.audio_thread = None
        self.settings = QSettings(qt_path(SETTINGS_PATH), QSettings.IniFormat)
        self._apply_process_priority_from_settings()
        self._timer_mode = self.settings.value("timer/mode", "countdown")
        self._timer_total = int(self.settings.value("timer/total", 25 * 60, type=int))
        self._timer_left = int(self._timer_total) if self._timer_mode == "countdown" else 0
        self._timer_running = False
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick_timer)
        self.autosave_enabled = True
        self.current_note = None
        self._ignore_dock_resize = False
        self._dock_ratios = [0.22, 0.56, 0.22]
        self._last_selection: tuple[int, int] | None = None
        self.init_ui()
        self.init_all_components()
        self.attachments_watcher = None
        self._attachments_snapshot: dict[str, set[str]] = {}
        QTimer.singleShot(200, self.load_plugins)
        self.init_theme()
        self.load_settings()
        self._clipboard_watch_enabled = self.settings.value(
            "layout/clipboard_auto_convert", True, type=bool
        )
        self._clipboard_ignore = False
        self._last_clipboard_text = ""
        self._clipboard_connected = False
        QTimer.singleShot(450, self._init_clipboard_watch)
        self._background_loader = None
        QTimer.singleShot(800, self._start_background_preload)
        self.tray_icon = None
        self._tray_inited = False
        QTimer.singleShot(350, self._init_tray_icon)
        self.reminder_timer = QTimer(self)
        self.reminder_timer.timeout.connect(self.check_reminders)
        self.reminder_timer.start(60000)

    @staticmethod
    def _html_to_plain_text(content: str) -> str:
        doc = QTextDocument()
        doc.setHtml(content or "")
        return doc.toPlainText()


    def _start_background_preload(self) -> None:
        if getattr(self, "_background_loader", None) is not None:
            try:
                self._background_loader.finished.disconnect()
            except Exception:
                pass
        self._background_loader = NotesLoaderThread(self)
        self._background_loader.finished.connect(self._apply_preloaded_notes)
        self._background_loader.finished.connect(
            lambda *_: getattr(self._background_loader, "deleteLater", lambda: None)()
        )
        self._background_loader.start()

    def clear_standby_list(self) -> None:
        rammap = resolve_rammap_exe()
        if rammap is None:
            QMessageBox.critical(
                self,
                "Очистка Standby List",
                "rammap.exe не найден.\n\n"
                f"Папка Data, которую использует приложение:\n{qt_path(DATA_DIR)}\n\n"
                "Положи rammap.exe в эту папку и попробуй снова.",
            )
            return

        try:
            params = "-Et"
            rc = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", str(rammap), params, None, 1
            )
            if rc <= 32:
                QMessageBox.warning(
                    self,
                    "Очистка Standby List",
                    f"Не удалось выполнить RamMap.exe (код {rc}).",
                )
                return
            QMessageBox.information(
                self,
                "Очистка Standby List",
                "Standby List успешно очищен.",
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Не удалось очистить Standby List:\n{e}",
            )


    def _apply_preloaded_notes(self, notes: list[Note]) -> None:
        self.notes = notes or []
        if not self.notes:
            self.notes_list.clear()
            return
        self.deduplicate_notes()
        self._apply_saved_notes_order()
        self.refresh_notes_list()
        last_uuid = (
            self.settings.value("lastNoteUUID", "")
            or self.settings.value("lastNoteUuid", "")
            or self.settings.value("ui/lastOpenedNoteUuid", "")
        )
        opened = False
        if last_uuid:
            for i in range(self.notes_list.count()):
                it = self.notes_list.item(i)
                n = it.data(Qt.UserRole)
                if n and getattr(n, "uuid", None) == last_uuid:
                    self.notes_list.setCurrentRow(i)
                    self.load_note(self.notes_list.currentItem())
                    opened = True
                    break
        if not opened:
            for i in range(self.notes_list.count()):
                it = self.notes_list.item(i)
                n = it.data(Qt.UserRole)
                if n and getattr(n, "uuid", None):
                    self.notes_list.setCurrentRow(i)
                    self.load_note(self.notes_list.currentItem())
                    opened = True
                    break
        self.update_tag_filter_items()
        self.update_search_filter_items()
        if not hasattr(self, "reminder_timer") or self.reminder_timer is None:
            self.setup_reminder_timer()


    def _install_dialog_probe(self) -> None:
        if not getattr(self, "debug_dialog_probe", False):
            return

        old_show_event = QDialog.showEvent

        def patched(dlg, e):
            try:
                logging.debug("[Dialog] %s shown", type(dlg).__name__)
            except Exception:
                pass
            return old_show_event(dlg, e)

        QDialog.showEvent = patched

    def _on_text_changed(self) -> None:
        if not getattr(self, "current_note", None):
            return
        if getattr(self, "_is_switching_note", False):
            return
        if (
            getattr(self, "_edit_session_note_uuid", None)
            and self._edit_session_note_uuid != self.current_note.uuid
        ):
            return

        self._edit_session_note_uuid = self.current_note.uuid
        self.update_current_note_content()

        if getattr(self, "autosave_enabled", False):
            try:
                if hasattr(self, "debounce_timer"):
                    self.debounce_timer.stop()
            except Exception:
                pass
            self._perform_autosave()
            self.pending_save = False
            return

        self.pending_save = True
        self._set_unsaved(True)
        if hasattr(self, "debounce_timer"):
            self.debounce_timer.start()

    def exit_app(self) -> None:
        try:
            if getattr(self, "tray_icon", None):
                self.tray_icon.hide()
        except Exception:
            pass

        try:
            self._unregister_global_hotkeys()
        except Exception:
            pass

        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _set_unsaved(self, flag: bool) -> None:
        self.setWindowModified(bool(flag))
        if hasattr(self, "dock_editor"):
            self.dock_editor.setWindowTitle("Редактор *" if flag else "Редактор")

    @staticmethod
    def _log_startup():
        try:
            log_path = os.path.join(DATA_DIR, "last_run.log")
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                print("=" * 60, file=f)
                print("START", datetime.datetime.now().isoformat(), file=f)
                print("APPDIR:", APPDIR, file=f)
                print("CWD   :", os.getcwd(), file=f)
                print("Notes exists:", os.path.isdir(NOTES_DIR), file=f)
                print("Data  exists:", os.path.isdir(DATA_DIR), file=f)
        except Exception:
            pass

    def _init_editor_defaults(self) -> None:
        qf = QFont("Times New Roman", 14)
        self.text_edit.document().setDefaultFont(qf)
        self.text_edit.setFont(qf)
        fmt = QTextCharFormat()
        fmt.setFont(QFont("Times New Roman", 14))
        self.text_edit.setCurrentCharFormat(fmt)
        if hasattr(self, "font_combo"):
            self.font_combo.setCurrentFont(QFont("Times New Roman"))
        if hasattr(self, "font_size_spin"):
            self.font_size_spin.setValue(14)

    @staticmethod
    def _count_layout_characters(text: str) -> dict[str, int]:
        latin = 0
        cyrillic = 0

        for ch in text or "":
            code = ord(ch)

            # Латиница: A-Z, a-z
            if 65 <= code <= 90 or 97 <= code <= 122:
                latin += 1

            # Кириллица: А-Я, а-я, Ё, ё
            elif 1040 <= code <= 1103 or code == 1025 or code == 1105:
                cyrillic += 1

        total_text = len(text or "")

        return {
            "latin": latin,
            "cyrillic": cyrillic,
            "total_text": total_text,
            "total_letters": latin + cyrillic,
        }

    def _schedule_layout_counter_update(self) -> None:
        timer = getattr(self, "_layout_counter_timer", None)
        if timer is None:
            self.update_note_layout_counter()
            return

        try:
            timer.start()
        except Exception:
            self.update_note_layout_counter()

    def update_note_layout_counter(self) -> None:
        label = getattr(self, "layout_counter_label", None)
        if label is None:
            return

        try:
            text = self.text_edit.toPlainText() if getattr(self, "text_edit", None) else ""
        except Exception:
            text = ""

        counts = self._count_layout_characters(text)

        label.setText(
            f"Кириллица: {counts['cyrillic']} | "
            f"Латиница: {counts['latin']} | "
            f"Всего символов: {counts['total_text']}"
        )

        label.setToolTip(
            "Показывает количество букв кириллицы и латиницы в текущей заметке. "
            "Пробелы, цифры и знаки считаются только в общем количестве символов."
        )

    def init_ui(self) -> None:
        self.setWindowTitle("Мои Заметки — [*]")
        self.setMinimumSize(600, 270)
        self.setWindowIcon(QIcon(qt_path(ICON_PATH)))
        always_on_top = self.settings.value("ui/always_on_top", True, type=bool)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, always_on_top)
        pm_label = self.settings.value("password_manager_label", "PasswordManager")
        self.new_note_button = QPushButton("Новая")
        self.save_note_button = QPushButton("Сохранить")
        self.delete_note_button = QPushButton("Удалить")
        self.export_note_button = QPushButton("Экспорт")
        self.undo_button = QPushButton("↩️")
        self.redo_button = QPushButton("↪️")
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Поиск по заметкам...")
        self.clear_search_button = QPushButton("Очистить")
        self.clear_search_button.setFixedWidth(90)
        self.clear_search_button.clicked.connect(lambda: self.search_field.setText(""))
        self.search_field.textChanged.connect(self.refresh_notes_list)
        self.topmost_checkbox = QCheckBox("Поверх всех окон")
        self.topmost_checkbox.setChecked(always_on_top)
        self.topmost_checkbox.toggled.connect(self._toggle_always_on_top)
        btns = QVBoxLayout()
        btns.addWidget(self.new_note_button)
        btns.addWidget(self.save_note_button)
        btns.addWidget(self.export_note_button)
        btns.addWidget(self.delete_note_button)
        btns.addWidget(self.undo_button)
        btns.addWidget(self.redo_button)
        btns.addWidget(self.topmost_checkbox)
        btns.addStretch()
        buttons_widget = QWidget()
        buttons_widget.setLayout(btns)
        self.notes_list = QListWidget()
        self.notes_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.notes_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
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
        self._hist_delete_sc = QShortcut(QKeySequence.Delete, self.history_list)
        self._hist_delete_sc.setContext(Qt.WidgetWithChildrenShortcut)
        self._hist_delete_sc.activated.connect(self.delete_selected_history_entries)
        hist_layout = QVBoxLayout()
        hist_layout.addWidget(self.history_label)
        hist_layout.addWidget(self.history_list)
        hist_layout.addWidget(self.delete_history_button)
        self.history_widget = QWidget()
        self.history_widget.setLayout(hist_layout)
        self.history_widget.setMinimumWidth(200)
        self.history_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.text_edit = CustomTextEdit(
            parent=self, paste_image_callback=self.insert_image_from_clipboard
        )
        self.text_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.text_edit.setWordWrapMode(QTextOption.WrapMode.NoWrap)
        self._init_editor_defaults()
        self.autosave_delay_ms = 1000
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.timeout.connect(lambda: self.save_note_quiet(force=True))
        self._sc_new = QShortcut(QKeySequence("Ctrl+N"), self)
        self._sc_new.activated.connect(self.create_new_note)
        self._sc_save = QShortcut(QKeySequence("Ctrl+S"), self)
        self._sc_save.activated.connect(lambda: self.save_note_quiet(force=True))
        self._sc_focus_search = QShortcut(QKeySequence("Ctrl+F"), self)
        self._sc_focus_search.activated.connect(lambda: self.search_field.setFocus())
        self._sc_export = QShortcut(QKeySequence("Ctrl+Shift+E"), self)
        self._sc_export.activated.connect(self.export_note)
        self._sc_import = QShortcut(QKeySequence("Ctrl+Shift+I"), self)
        self._sc_import.activated.connect(self.import_note)
        self.text_edit.textChanged.connect(self._schedule_autosave)
        self.text_edit.textChanged.connect(self.on_text_changed_autosave)

        self._layout_counter_timer = QTimer(self)
        self._layout_counter_timer.setSingleShot(True)
        self._layout_counter_timer.setInterval(120)
        self._layout_counter_timer.timeout.connect(self.update_note_layout_counter)

        self.text_edit.textChanged.connect(self._schedule_layout_counter_update)

        self.text_edit.setUndoRedoEnabled(False)
        self.spell_highlighter = SpellCheckHighlighter(self.text_edit.document())
        if not self.settings.contains("spellcheck/online_enabled"):
            self.settings.setValue("spellcheck/online_enabled", True)
        self.spell_online_enabled = self.settings.value(
            "spellcheck/online_enabled", True, type=bool
        )
        self.spell_highlighter.set_online_enabled(self.spell_online_enabled)
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
        self.text_edit.setMinimumWidth(250)
        self.text_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.text_edit.installEventFilter(self)
        try:
            self.text_edit.selectionChanged.connect(self._on_text_selection_changed)
        except Exception:
            pass
        self.text_edit.textChanged.connect(lambda: self._set_unsaved(True))
        self.tags_label = QLabel("Теги: нет")
        self.tags_label.setAlignment(Qt.AlignLeft)
        self.attachments_panel = QWidget()
        self.attachments_layout = QHBoxLayout(self.attachments_panel)
        self.attachments_layout.setAlignment(Qt.AlignLeft)
        self.attachments_layout.setContentsMargins(0, 0, 0, 0)
        self.attachments_scroll = QScrollArea()
        self.attachments_scroll.setWidgetResizable(True)
        self.attachments_scroll.setWidget(self.attachments_panel)
        self.attachments_scroll.setVisible(False)
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
        _cw_lay = QVBoxLayout(self.central_widget)
        _cw_lay.setContentsMargins(0, 0, 0, 0)
        _cw_lay.setSpacing(0)
        _cw_lay.addWidget(editor_combined, 1)
        self.setCentralWidget(self.central_widget)
        self.dock_editor = _CentralWidgetProxy(editor_combined)
        self.init_toolbar()
        self.left_panel_splitter = QSplitter(Qt.Vertical)

        def _mk_section(title: str, widget: QWidget) -> QWidget:
            wrap = QWidget()
            lay = QVBoxLayout(wrap)
            lay.setContentsMargins(6, 6, 6, 6)
            lay.setSpacing(6)
            lbl = QLabel(title)
            lbl.setObjectName("left_section_title")
            lay.addWidget(lbl, 0)
            lay.addWidget(widget, 1)
            return wrap

        self._left_section_notes = _mk_section("Заметки", self.notes_list)
        self._left_section_history = _mk_section("История", self.history_widget)
        self._left_section_buttons = _mk_section("Управление", buttons_widget)
        self.left_panel_splitter.addWidget(self._left_section_notes)
        self.left_panel_splitter.addWidget(self._left_section_history)
        self.left_panel_splitter.addWidget(self._left_section_buttons)
        self.left_panel_splitter.setChildrenCollapsible(False)
        self.dock_notes_list = QDockWidget("Панель", self)
        self.dock_notes_list.setObjectName("dock_notes_list")
        self.dock_notes_list.setWidget(self.left_panel_splitter)
        self.dock_notes_list.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.dock_notes_list)
        self.dock_history = None
        self.dock_buttons = None
        self.password_manager_field = QLineEdit()
        self.password_manager_field.setPlaceholderText(pm_label)
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
        self.password_manager_copy_btn.setEnabled(False)
        self.password_manager_copy_btn.clicked.connect(
            self.copy_password_manager_to_clipboard
        )
        self.password_manager_field.textChanged.connect(
            lambda t: self.password_manager_copy_btn.setEnabled(bool(t))
        )
        _pm_row_layout.addWidget(self.password_manager_copy_btn)
        pm_up = QToolButton()
        pm_up.setText("▲")
        pm_up.setFixedSize(24, 24)
        pm_dn = QToolButton()
        pm_dn.setText("▼")
        pm_dn.setFixedSize(24, 24)
        pm_up.clicked.connect(
            lambda _, w=self.password_manager_row: self._move_pinned(w, -1)
        )
        pm_dn.clicked.connect(
            lambda _, w=self.password_manager_row: self._move_pinned(w, +1)
        )
        _pm_row_layout.addWidget(pm_up)
        _pm_row_layout.addWidget(pm_dn)
        self.pinned_container = QWidget()
        self.pinned_layout = QVBoxLayout(self.pinned_container)
        self.pinned_layout.setContentsMargins(0, 0, 0, 0)
        self.pinned_layout.setSpacing(6)
        self.pinned_layout.addWidget(self.password_manager_row)
        self._add_field_panel = QWidget()
        _add_l = QHBoxLayout(self._add_field_panel)
        _add_l.setContentsMargins(0, 0, 0, 0)
        self.add_field_btn = QPushButton("Добавить поле")
        self.add_field_btn.setFixedHeight(24)
        self.add_field_btn.setEnabled(False)
        self.add_field_btn.clicked.connect(self.add_custom_field)
        _add_l.addStretch(1)
        _add_l.addWidget(self.add_field_btn)
        self._add_field_panel.setVisible(False) 
        self.pinned_layout.addWidget(self._add_field_panel)
        self.custom_fields_container = self.pinned_container
        self.custom_fields_layout = self.pinned_layout
        self.custom_fields_widgets: list[dict] = []
        editor_layout_combined.insertWidget(0, self.pinned_container)
        self.dock_toolbar = QDockWidget("Панель инструментов", self)
        self.dock_toolbar.setObjectName("dock_toolbar")
        self.dock_toolbar.setWidget(self.toolbar_scroll)
        self.dock_toolbar.setAllowedAreas(
            Qt.TopDockWidgetArea | Qt.BottomDockWidgetArea
        )
        self.addDockWidget(Qt.TopDockWidgetArea, self.dock_toolbar)
        self.resizeDocks(
            [self.dock_toolbar], [120], Qt.Vertical
        )
        for dock in (
            self.dock_notes_list,
            self.dock_toolbar,
        ):
            if dock is None:
                continue

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
        # Поле PM убрано из интерфейса: «глаз» на панель видимости не добавляем,
        # а строку password_manager_row держим всегда скрытой (см. select_note /
        # _update_editor_visibility). Данные заметок (password_manager) сохранены.
        self.add_menu_bar()
        self._restore_view_visibility()
        self.layout_counter_label = QLabel(self)
        self.layout_counter_label.setObjectName("layout_counter_label")
        self.statusBar().addPermanentWidget(self.layout_counter_label)
        self.update_note_layout_counter()
        self.new_note_button.clicked.connect(self.new_note)
        self.save_note_button.clicked.connect(self.save_note)
        self.export_note_button.clicked.connect(self.show_export_menu)
        self.delete_note_button.clicked.connect(self.delete_note)
        self.notes_list.itemClicked.connect(self.load_note)
        self.current_note = None
        self._update_editor_visibility()
        sc_undo_notes = QShortcut(QKeySequence.Undo, self)
        sc_undo_notes.setContext(Qt.ApplicationShortcut)
        sc_undo_notes.activated.connect(self.undo)
        sc_redo_notes = QShortcut(QKeySequence.Redo, self)
        sc_redo_notes.setContext(Qt.ApplicationShortcut)
        sc_redo_notes.activated.connect(self.redo)
        sc_translate_layout = QShortcut(QKeySequence("Ctrl+Shift+F12"), self)
        sc_translate_layout.setContext(Qt.ApplicationShortcut)
        sc_translate_layout.activated.connect(self.translate_layout_only)
        sc_translate_layout_selection = QShortcut(QKeySequence("Ctrl+Shift+L"), self)
        sc_translate_layout_selection.setContext(Qt.ApplicationShortcut)
        sc_translate_layout_selection.activated.connect(self.translate_layout_selection)
        # Ctrl+Alt+F12 (смена регистра) убран: эта комбинация закрывает punto_like.
        sc_toggle_case_selection = QShortcut(QKeySequence("Ctrl+Alt+L"), self)
        sc_toggle_case_selection.setContext(Qt.ApplicationShortcut)
        sc_toggle_case_selection.activated.connect(self.translate_case_selection)
        self._register_global_hotkeys()
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._unregister_global_hotkeys)

        self._dock_ratios = self._load_dock_ratios_from_settings()
        self._resizing_apply = False
        QTimer.singleShot(0, self._apply_dock_proportions)


    def _apply_dock_proportions(self):
        if not getattr(self, "dock_notes_list", None) or not getattr(self, "dock_editor", None):
            return
        if not getattr(self, "left_panel_splitter", None):
            return
        try:
            total_h = max(1, self.dock_notes_list.height())
            lst = self.notes_list
            count = lst.count()
            if count > 0:
                row_h = lst.sizeHintForRow(0)
                if row_h <= 0:
                    row_h = lst.fontMetrics().height() + 6
            else:
                row_h = lst.fontMetrics().height() + 6
            frame = lst.frameWidth() * 2
            extra = 0
            list_h_needed = row_h * max(1, count) + frame + extra
            btn_h_min = 60
            btn_widget = getattr(self, "_left_section_buttons", None)
            btn_h_hint = btn_widget.sizeHint().height() if btn_widget else 120
            btn_h = max(btn_h_min, min(btn_h_hint, int(total_h * 0.25)))
            hist_h_min = 120
            hist_h = total_h - list_h_needed - btn_h
            if hist_h < hist_h_min:
                deficit = hist_h_min - hist_h
                min_visible_rows = max(1, min(max(3, count), count))
                list_h_min = row_h * min_visible_rows + frame + extra
                shrink_from_list = min(deficit, max(0, list_h_needed - list_h_min))
                list_h_needed -= shrink_from_list
                deficit -= shrink_from_list

                if deficit > 0:
                    btn_h = max(btn_h_min, btn_h - deficit)
                hist_h = hist_h_min
            try:
                self.left_panel_splitter.setSizes([int(list_h_needed), int(hist_h), int(btn_h)])
            except Exception:
                pass
            total_w = max(1, self.width())
            min_left = 260
            pref_left = 360
            min_editor = 500
            if total_w <= min_left + min_editor:
                left_width = max(min_left, int(total_w * 0.3))
            else:
                left_width = min(pref_left, total_w - min_editor)
            self.resizeDocks(
                [self.dock_notes_list],
                [left_width],
                Qt.Horizontal,
            )
        except Exception:
            pass

    def show_number_generator(self):
        try:
            dlg = NumberGeneratorDialog(self)
            if dlg.exec() == QDialog.Accepted:
                text = dlg.result_text()
                if text and hasattr(self, "text_edit"):
                    cur = self.text_edit.textCursor()
                    cur.insertText(text, self.text_edit._default_char_format())
                    self.text_edit.setTextCursor(cur)
                    self._set_unsaved(True)
                    if getattr(self, "autosave_enabled", True):
                        if self.autosave_enabled:
                            self.save_note_quiet(force=True)
        except Exception as e:
            QMessageBox.warning(self, "Генератор чисел", f"Ошибка: {e}")

    def _apply_vertical_defaults(self):
        min_h = 36
        h = self.settings.value("ui/dock_toolbar_height", min_h, type=int)
        try:
            h = int(h)
        except Exception:
            h = min_h
        h = max(min_h, min(h, 300))
        self.dock_toolbar.setMinimumHeight(min_h)
        self.resizeDocks(
            [self.dock_toolbar],
            [h],
            Qt.Vertical,
        )

    
    def _current_dock_widths(self):
        l = max(1, self.dock_notes_list.width()) if getattr(self, "dock_notes_list", None) else 1
        c = max(1, self.dock_editor.width()) if getattr(self, "dock_editor", None) else 1
        r = max(1, self.dock_history.width()) if getattr(self, "dock_history", None) else 1
        return [l, c, r]


    def start_stopwatch(self):
        if not getattr(self, "stopwatch_running", False):
            self.stopwatch_running = True
            try:
                self.stopwatch_timer.start()
            except Exception:
                pass

    def resizeEvent(self, event):
        super().resizeEvent(event)

        try:
            self._apply_dock_proportions()
        except Exception:
            pass

        if not hasattr(self, "_resize_deb"):
            self._resize_deb = QTimer(self)
            self._resize_deb.setSingleShot(True)
            self._resize_deb.setInterval(0)
            self._resize_deb.timeout.connect(self._apply_dock_ratios)
        self._resize_deb.start()

        if not hasattr(self, "_save_settings_deb"):
            self._save_settings_deb = QTimer(self)
            self._save_settings_deb.setSingleShot(True)
            self._save_settings_deb.setInterval(250)
            self._save_settings_deb.timeout.connect(self.save_settings)
        self._save_settings_deb.start()


    def stop_stopwatch(self):
        self.stopwatch_running = False
        self.stopwatch_timer.stop()

    def _set_html_preserve_view(
        self, html: str, preferred_pos: int | None = None
    ) -> None:
        cur_before = self.text_edit.textCursor()
        block_num = cur_before.blockNumber()
        col_in_block = cur_before.positionInBlock()
        if preferred_pos is not None:
            tmp = QTextCursor(self.text_edit.document())
            tmp.setPosition(max(0, int(preferred_pos)))
            block_num = tmp.blockNumber()
            col_in_block = tmp.positionInBlock()
        vbar = self.text_edit.verticalScrollBar()
        old_scroll = vbar.value()
        self.text_edit.blockSignals(True)
        self.text_edit.setUpdatesEnabled(False)
        self.text_edit.setHtml(html)
        doc = self.text_edit.document()
        max_block = max(0, doc.blockCount() - 1)
        block_num = max(0, min(block_num, max_block))
        block = doc.findBlockByNumber(block_num)
        max_col = max(0, block.length() - 1)
        col_in_block = max(0, min(col_in_block, max_col))
        target_pos = block.position() + col_in_block
        cur_after = self.text_edit.textCursor()
        cur_after.setPosition(target_pos)
        self.text_edit.setTextCursor(cur_after)
        vbar.setValue(old_scroll)
        self.text_edit.setUpdatesEnabled(True)
        self.text_edit.blockSignals(False)

    def reset_stopwatch(self):
        self.stopwatch_running = False
        self.stopwatch_timer.stop()
        self.stopwatch_time = 0
        self.lbl_stopwatch.setText("00:00:00")

    def _update_stopwatch(self):
        if self.stopwatch_running:
            self.stopwatch_time += 1
            h = self.stopwatch_time // 3600
            m = (self.stopwatch_time % 3600) // 60
            s = self.stopwatch_time % 60
            self.lbl_stopwatch.setText(f"{h:02d}:{m:02d}:{s:02d}")

    def add_word_to_note_ignore(self, word: str) -> None:
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
        remove_btn = QPushButton("✖")
        remove_btn.setFixedSize(24, 24)
        up_btn = QToolButton()
        up_btn.setText("▲")
        up_btn.setFixedSize(24, 24)
        down_btn = QToolButton()
        down_btn.setText("▼")
        down_btn.setFixedSize(24, 24)
        up_btn.clicked.connect(lambda _, w=row: self._move_pinned(w, -1))
        down_btn.clicked.connect(lambda _, w=row: self._move_pinned(w, +1))
        copy_btn = QPushButton("Копировать")
        copy_btn.setFixedHeight(24)
        copy_btn.setEnabled(bool(value))
        copy_btn.clicked.connect(
            lambda _, e=value_edit, b=copy_btn: self.copy_custom_field_to_clipboard(
                e, b
            )
        )
        value_edit.textChanged.connect(lambda _: self._schedule_autosave())
        value_edit.textChanged.connect(lambda t, b=copy_btn: b.setEnabled(bool(t)))
        value_edit.textChanged.connect(
            lambda _: self.update_current_note_custom_fields()
        )
        value_edit.textChanged.connect(
            lambda _: (
                self.save_note_quiet(force=True) if self.autosave_enabled else None
            )
        )
        layout.addWidget(up_btn)
        layout.addWidget(down_btn)
        layout.addWidget(label_edit)
        layout.addWidget(value_edit, 1)
        layout.addWidget(copy_btn)
        layout.addWidget(remove_btn)
        insert_at = self.pinned_layout.indexOf(self._add_field_panel)
        self.pinned_layout.insertWidget(insert_at, row)
        fid = (data.get("id") if data else None) or f"cf::{uuid4().hex}"
        action = QAction(f"🙈 {label}", self)
        action.setCheckable(True)
        fid = label_edit.text().strip() or "field"
        visible = bool(int(self.settings.value(f"ui/customFieldVisible/{fid}", 1)))
        if data and "visible" in data:
            raw = data.get("visible", False)
            visible = (raw is True) or (str(raw).lower() in {"1", "true", "yes"})
        action.setChecked(visible)
        row.setVisible(visible)
        self._update_eye_action(action, visible, label)
        widget = {
            "row": row,
            "label_edit": label_edit,
            "value_edit": value_edit,
            "copy_btn": copy_btn,
            "remove_btn": remove_btn,
            "action": action,
            "id": fid,
        }
        if data and "visible" in data:
            raw = data["visible"]
            visible = (raw is True) or (str(raw).lower() in {"1", "true", "yes"})
        else:
            visible = bool(int(self.settings.value(f"ui/customFieldVisible/{fid}", 1)))
            action.blockSignals(True)
        action.setChecked(visible)
        action.blockSignals(False)
        row.setVisible(visible)
        self._update_eye_action(action, visible, label)
        action.toggled.connect(
            lambda checked, w=widget: self.on_toggle_custom_field(w, checked)
        )
        label_edit.textChanged.connect(
            lambda text, w=widget: self.on_custom_field_label_changed(w, text)
        )
        remove_btn.clicked.connect(lambda _, w=widget: self.remove_custom_field(w))
        self.visibility_toolbar.addAction(action)
        self.custom_fields_widgets.append(widget)
        self.update_current_note_custom_fields()

    def _pinned_widgets(self) -> list[QWidget]:
        out = []
        if not hasattr(self, "pinned_layout"):
            return out
        for i in range(self.pinned_layout.count()):
            w = self.pinned_layout.itemAt(i).widget()
            if not w or w is self._add_field_panel:
                continue
            out.append(w)
        return out

    def _sync_custom_widgets_order_from_layout(self) -> None:
        if not hasattr(self, "custom_fields_widgets"):
            return
        by_row = {w["row"]: w for w in self.custom_fields_widgets}
        new_list = []
        for w in self._pinned_widgets():
            if w in by_row:
                new_list.append(by_row[w])
        self.custom_fields_widgets = new_list

    def remove_custom_field(self, widget: dict) -> None:
        self.visibility_toolbar.removeAction(widget["action"])
        widget["row"].setParent(None)
        widget["action"].deleteLater()
        widget["row"].deleteLater()
        self.custom_fields_widgets.remove(widget)
        self.update_current_note_custom_fields()
        if self.current_note:
            self.save_note_to_file(self.current_note)

    def _move_pinned(self, widget: QWidget, delta: int) -> None:
        if not hasattr(self, "pinned_layout"):
            return
        cur = self.pinned_layout.indexOf(widget)
        if cur < 0:
            return
        last_index = self.pinned_layout.indexOf(self._add_field_panel) - 1
        if last_index < 0:
            last_index = self.pinned_layout.count() - 1
        target = max(0, min(cur + int(delta), last_index))
        if target == cur:
            return
        self.pinned_layout.removeWidget(widget)
        self.pinned_layout.insertWidget(target, widget)
        self._sync_custom_widgets_order_from_layout()
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
            if self.autosave_enabled:
                self.save_note_quiet(force=True)

    def on_toggle_custom_field(self, widget: dict, checked: bool) -> None:
        if not self.current_note:
            widget["action"].blockSignals(True)
            widget["action"].setChecked(False)
            widget["action"].blockSignals(False)
            return
        widget["row"].setVisible(checked)
        self._update_eye_action(widget["action"], checked, widget["label_edit"].text())
        fid = widget.get("id")
        if fid:
            self.settings.setValue(f"ui/customFieldVisible/{fid}", int(checked))
            self.settings.sync()
        self.update_current_note_custom_fields()
        self.save_note_to_file(self.current_note)
        self.save_note_quiet(force=True)


    def update_current_note_custom_fields(self) -> None:
        if not getattr(self, "current_note", None):
            return
        fields = []
        for w in self.custom_fields_widgets:
            fields.append(
                {
                    "id": w.get("id"),
                    "label": w["label_edit"].text(),
                    "value": w["value_edit"].text(),
                    "visible": bool(w["action"].isChecked()),
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

    def delete_selected_history_entries(self) -> None:
        if not self.current_note:
            return
        selected_indexes = [item.row() for item in self.history_list.selectedIndexes()]
        if not selected_indexes:
            self.show_toast("Нет выбранных версий для удаления")
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
            self._force_default_note_font()
            self.text_edit.blockSignals(False)
            self.current_note.history_index = -1
        else:
            self.text_edit.blockSignals(True)
            self._set_html_preserve_view(
                self.current_note.history[self.current_note.history_index]
            )
            self.text_edit.blockSignals(False)
        self.update_history_list()
        self.update_history_list_selection()
        self.save_note_to_file(self.current_note)
        self.show_toast("Выбранные версии удалены из истории")


    def restore_version_from_history(self, item: QListWidgetItem) -> None:
        if not self.current_note:
            return
        content = item.data(Qt.UserRole)
        if content:
            self._set_html_preserve_view(content)
            self.current_note.history_index = self.history_list.row(item)
            self.update_history_list_selection()


    def move_note_to_trash(self, note: "Note") -> None:
        self.save_note_to_file(note)

        note_dir = self._note_folder_path(note, NOTES_DIR)
        trash_dir = self._note_folder_path(note, self.TRASH_DIR)

        self._detach_attachments_watcher([qt_path(note_dir)])

        self.TRASH_DIR.mkdir(parents=True, exist_ok=True)

        if trash_dir.exists():
            shutil.rmtree(trash_dir)
        if note_dir.exists():
            shutil.move(note_dir, trash_dir)

        try:
            self._remove_uuid_from_notes_order(getattr(note, "uuid", "") or "")
        except Exception:
            pass
        self.notes = [n for n in self.notes if n.uuid != note.uuid]


    def _as_path(self, p: Path | str) -> Path:
        return p if isinstance(p, Path) else Path(p)


    def bring_widget_to_front(self, w: QWidget) -> None:
        old_stays_on_top = bool(w.windowFlags() & Qt.WindowStaysOnTopHint)
        w.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        w.show()
        w.raise_()
        w.activateWindow()

        def _restore() -> None:
            w.setWindowFlag(Qt.WindowStaysOnTopHint, old_stays_on_top)
            w.show()

        QTimer.singleShot(800, _restore)

    def _center_on_parent(self, dlg: QDialog) -> None:
        try:
            parent = dlg.parent() if isinstance(dlg.parent(), QWidget) else self
            if not isinstance(parent, QWidget):
                return
            dlg.adjustSize()
            rect = QStyle.alignedRect(
                Qt.LeftToRight, Qt.AlignCenter, dlg.sizeHint(), parent.frameGeometry()
            )
            dlg.setGeometry(rect)
        except Exception:
            pass

    def record_state_for_undo(self) -> None:
        note = self.current_note
        if not note:
            if hasattr(self, "attachments_scroll") and self.attachments_scroll:
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
            self._set_html_preserve_view(
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
            self._set_html_preserve_view(
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


    @staticmethod
    def _coerce_to_bool(value, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return value != 0
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return default


    def _note_folder_path(self, note: "Note", root: Path) -> Path:
        return root / safe_folder_name(note.title, note.uuid, note.timestamp)


    def deduplicate_notes(self) -> None:
        unique = {}
        for note in self.notes:
            unique[note.uuid] = note
        self.notes = list(unique.values())


    def _save_view_visibility(self, key: str, visible: bool) -> None:
        # Сохраняем только реальный выбор пользователя. Когда окно свёрнуто или
        # спрятано в трей, дочерние доки временно невидимы — такое состояние
        # писать нельзя, иначе панели «пропадут» при следующем запуске.
        if not self.isVisible() or self.isMinimized():
            return
        self.settings.setValue(key, bool(visible))

    def _restore_view_visibility(self) -> None:
        try:
            if getattr(self, "dock_notes_list", None):
                v = self.settings.value("ui/dock_notes_list_visible", True, type=bool)
                self.dock_notes_list.setVisible(v)
            if getattr(self, "dock_toolbar", None):
                v = self.settings.value("ui/dock_toolbar_visible", True, type=bool)
                self.dock_toolbar.setVisible(v)
            if getattr(self, "visibility_toolbar", None):
                v = self.settings.value("ui/visibility_toolbar_visible", True, type=bool)
                self.visibility_toolbar.setVisible(v)
        except Exception:
            logging.exception("Failed to restore view visibility")

    def _note_dir(self, note=None) -> str | None:
        n = note or getattr(self, "current_note", None)
        if not n:
            return None
        return os.path.join(
            NOTES_DIR, safe_folder_name(n.title, n.uuid, n.timestamp)
        )


    def confirm_delete_note(self, note: Note) -> None:
        reply = QMessageBox.question(
            self,
            "Удалить заметку",
            f"Вы уверены, что хотите удалить заметку '{note.title}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.move_note_to_trash(note)
            if self.current_note and self.current_note.uuid == note.uuid:
                self.current_note = None
                self.text_edit.clear()
            self.refresh_notes_list()
            self.save_all_notes_to_disk()

    def rename_note(self, note: Note) -> None:
        dlg = QInputDialog(self)
        dlg.setWindowTitle("Переименовать")
        dlg.setLabelText("Новое имя заметки:")
        dlg.setTextValue(note.title)
        edit = dlg.findChild(QLineEdit)
        if edit is not None:
            edit.selectAll()
            edit.setProperty("renameTitleEditor", True)
            edit.installEventFilter(self)
        if dlg.exec():
            new_title = dlg.textValue().strip()
            if new_title and new_title != note.title:
                old_dir = os.path.join(
                    NOTES_DIR,
                    safe_folder_name(note.title, note.uuid, note.timestamp),
                )
                note.title = new_title
                new_dir = os.path.join(
                    NOTES_DIR,
                    safe_folder_name(note.title, note.uuid, note.timestamp),
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
            from PySide6.QtPrintSupport import QPrinter

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
            self.show_toast("PDF сохранён")

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
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(text)
            except OSError as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить TXT: {e}")
                return
            self.show_toast("TXT сохранён")

    def export_current_note_docx(self) -> None:
        if not self.current_note:
            QMessageBox.warning(self, "Ошибка", "Нет выбранной заметки для экспорта.")
            return
        default_name = self.safe_filename(self.current_note.title, "docx")
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить как DOCX", default_name, filter="Word Documents (*.docx)"
        )
        if file_path:
            from docx import Document

            doc = Document()
            qt_doc = self.text_edit.document()
            block = qt_doc.firstBlock()
            while block.isValid():
                paragraph = doc.add_paragraph()
                it = block.begin()
                while not it.atEnd():
                    fragment = it.fragment()
                    if fragment.isValid():
                        char_format = fragment.charFormat()
                        if char_format.isImageFormat():
                            image_format = char_format.toImageFormat()
                            image_path = image_format.name()
                            run = paragraph.add_run()
                            if image_path.startswith("data:image"):
                                header, b64data = image_path.split(",", 1)
                                suffix = ".png" if "png" in header else ".jpg"
                                with tempfile.NamedTemporaryFile(
                                    delete=False, suffix=suffix
                                ) as tmp:
                                    tmp.write(base64.b64decode(b64data))
                                    tmp_path = tmp.name
                                run.add_picture(tmp_path)
                                os.unlink(tmp_path)
                            else:
                                if image_path.startswith("file://"):
                                    image_path = QUrl(image_path).toLocalFile()
                                if os.path.exists(image_path):
                                    run.add_picture(image_path)
                        else:
                            paragraph.add_run(fragment.text())
                    it += 1
                block = block.next()
            doc.save(file_path)
            self.show_toast("DOCX сохранён")

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
            custom_fields=[dict(f) for f in getattr(note, "custom_fields", [])],
        )
        new_note.password_manager_visible = note.password_manager_visible
        note_dir = os.path.join(
            NOTES_DIR, safe_folder_name(note.title, note.uuid, note.timestamp)
        )
        new_note_dir = os.path.join(
            NOTES_DIR,
            safe_folder_name(new_title, new_uuid, new_note.timestamp),
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
            ts_iso = QDateTime.currentDateTime().toString(Qt.ISODate)
            note = Note(
                title=title,
                content="",
                tags=[],
                favorite=False,
                timestamp=ts_iso,
                reminder=None,
                uuid=note_uuid,
            )
            note.history = [""]
            note.history_index = 0
            note_dir = os.path.join(
                NOTES_DIR, safe_folder_name(title, note_uuid, ts_iso)
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

            self.update_note_layout_counter()
            self.tags_label.setText("Теги: нет")
            self.password_manager_field.clear()
            self.refresh_notes_list()
            self.show_note_with_attachments(note)
            self.text_edit.setFocus()
            self.text_edit.setReadOnly(False)
            note.password_manager_visible = False
            self.password_manager_field.clear()
            self.password_manager_row.setVisible(False)
            self.clear_custom_fields()
            self.add_field_btn.setEnabled(True)
            if hasattr(self, "action_toggle_pm"):
                self.action_toggle_pm.blockSignals(True)
                self.action_toggle_pm.setChecked(False)
                self._update_eye_action(
                    self.action_toggle_pm, False, self.password_manager_label.text()
                )
                self.action_toggle_pm.blockSignals(False)

    def save_note(self) -> None:
        if self.current_note:
            html = self.text_edit.toHtml()
            html = self._persist_dropdown_values_in_html(html)
            self.current_note.content = html
            self.current_note.password_manager = self.password_manager_field.text()
            self.update_current_note_custom_fields()
            self.save_note_to_file(self.current_note)
            self.refresh_notes_list()
            self.record_state_for_undo()
            self.show_toast("Заметка сохранена")
            self._set_unsaved(False)


    def show_export_menu(self):
        if not getattr(self, "current_note", None):
            QMessageBox.information(self, "Экспорт", "Сначала выберите заметку для экспорта.")
            return

        menu = QMenu(self)
        act_pdf = menu.addAction("Экспорт в PDF")
        act_txt = menu.addAction("Экспорт в TXT")
        act_docx = menu.addAction("Экспорт в DOCX")
        act_json = menu.addAction("Экспорт заметки (JSON)")

        def _safe_call(fn_name: str):
            fn = getattr(self, fn_name, None)
            if callable(fn):
                fn()
            else:
                QMessageBox.warning(self, "Экспорт", f"Функция {fn_name} не найдена в этой версии.")

        act_pdf.triggered.connect(lambda: _safe_call("export_current_note_pdf"))
        act_txt.triggered.connect(lambda: _safe_call("export_current_note_txt"))
        act_docx.triggered.connect(lambda: _safe_call("export_current_note_docx"))
        act_json.triggered.connect(lambda: _safe_call("export_note"))
        pos = self.export_note_button.mapToGlobal(QPoint(0, self.export_note_button.height()))
        menu.exec(pos)

    def save_note_quiet(self, *, force: bool = False) -> None:
        if not force and not getattr(self, "autosave_enabled", True):
            return
        if self.current_note:
            html = self.text_edit.toHtml()
            html = self._persist_dropdown_values_in_html(html)
            self.current_note.content = html
            self.current_note.password_manager = self.password_manager_field.text()
            self.update_current_note_custom_fields()
            self.save_note_to_file(self.current_note)
            self.record_state_for_undo()
            self._set_unsaved(False)

    def open_note_folder(self, note: Note) -> None:
        if not note:
            if hasattr(self, "attachments_scroll") and self.attachments_scroll:
                self.attachments_scroll.setVisible(False)
            return
        folder_name = safe_folder_name(note.title, note.uuid, note.timestamp)
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
            self.show_toast("Перемещены в корзину")
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
                self.show_toast(f"«{title}» перемещена в корзину")
            return
        self.show_toast("Нет заметки для удаления")


    def _render_date_placeholders(self, html: str, base_date: QDate) -> str:
        pattern = re.compile(r"\{date(?:\s*(?P<sign>[+-])\s*(?P<days>\d+))?\}", re.I)

        def repl(m: re.Match) -> str:
            days = int(m.group("days") or 0)
            if m.group("sign") == "-":
                days = -days
            d = base_date.addDays(days)
            return d.toString("dd.MM.yyyy")

        return pattern.sub(repl, html)

    def _apply_dynamic_tokens(self, html: str) -> str:
        today = QDate.currentDate().toString("dd.MM.yyyy")
        html = re.sub(
            r'(<span\b[^>]*\bdata-dyn="today"[^>]*>)(.*?)(</span>)',
            lambda m: m.group(1) + today + m.group(3),
            html,
            flags=re.I | re.S,
        )
        html = re.sub(r"\{today\}", today, html, flags=re.I)
        return html


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
            safe_folder_name(note.title, note.uuid, note.timestamp),
        )
        note_dir = os.path.join(
            NOTES_DIR, safe_folder_name(note.title, note.uuid, note.timestamp)
        )
        if os.path.exists(trash_note_dir):
            shutil.move(trash_note_dir, note_dir)
        self.load_notes_from_disk()
        try:
            restored_uuid = getattr(note, "uuid", "") or ""
            if restored_uuid:
                order = self._load_notes_order()
                pinned = list(order.get("pinned") or [])
                unpinned = list(order.get("unpinned") or [])
                if restored_uuid not in pinned and restored_uuid not in unpinned:
                    (pinned if getattr(note, "pinned", False) else unpinned).append(restored_uuid)
                    self._save_notes_order(pinned, unpinned)
        except Exception:
            pass
        self.refresh_notes_list()
        for i in range(self.notes_list.count()):
            item = self.notes_list.item(i)
            note_obj = item.data(Qt.UserRole)
            if note_obj.uuid == note.uuid:
                self.notes_list.setCurrentRow(i)
                self.select_note(note_obj)
                break
        self.show_toast("Заметка восстановлена")

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
                safe_folder_name(note.title, note.uuid, note.timestamp),
            )
            if os.path.exists(trash_note_dir):
                self._detach_attachments_watcher([trash_note_dir])
                shutil.rmtree(trash_note_dir)
            self.refresh_notes_list()
            self.show_toast("Заметка удалена навсегда")

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
                self.show_toast("Корзина очищена")

    def load_note(self, item: QListWidgetItem | None) -> None:
        if item is None:
            self.setWindowTitle("Мои Заметки — [*]")
            self.setWindowModified(False)
            self.text_edit.blockSignals(True)
            self.text_edit.clear()
            self.text_edit.blockSignals(False)
            self.update_note_layout_counter()
            self.text_edit.setReadOnly(True)
            self.text_edit.hide()
            self._detach_attachments_watcher()
            self.tags_label.setText(
                f"Теги: {', '.join(self.current_note.tags) if (self.current_note and self.current_note.tags) else 'нет'}"
            )
            self.current_note = None
            if hasattr(self, "spell_highlighter"):
                self.spell_highlighter.set_local_ignored([])
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

        previous_note = getattr(self, "current_note", None)
        if previous_note and previous_note.uuid == note.uuid:
            return

        self._suspend_edit_signals()
        try:
            if previous_note:
                try:
                    html_content = self.text_edit.toHtml()
                    html_content = self._persist_dropdown_values_in_html(html_content)
                except Exception:
                    html_content = previous_note.content
                previous_note.content = html_content
                try:
                    plain_text = self._html_to_plain_text(html_content)
                except Exception:
                    plain_text = ""
                if not hasattr(self, "_note_save_locks"):
                    self._note_save_locks = {}
                lock = self._note_save_locks.get(previous_note.uuid)
                if lock is None:
                    lock = threading.Lock()
                    self._note_save_locks[previous_note.uuid] = lock
                note_snapshot = previous_note.to_dict()
                if not previous_note.reminder:
                    note_snapshot.pop("reminder", None)
                note_snapshot["content"] = html_content
                note_snapshot["content_txt"] = plain_text

                def _bg_save(snapshot: dict, title: str, uuid_: str, ts: str | QDateTime | None) -> None:
                    with lock:
                        try:
                            note_folder = NOTES_DIR / safe_folder_name(title, uuid_, ts)
                            self._save_payload_to_folder(note_folder, snapshot, keep_backups=10)
                        except Exception:
                            logging.exception("Background save failed (uuid=%s)", uuid_)

                threading.Thread(
                    target=_bg_save,
                    args=(note_snapshot, previous_note.title, previous_note.uuid, previous_note.timestamp),
                    daemon=True,
                ).start()
            self.current_note = note
            self.tags_label.setText(f"Теги: {', '.join(note.tags) if note and note.tags else 'нет'}")
            if hasattr(self, "settings"):
                self.settings.setValue("lastNoteText", "")
            if hasattr(self, "spell_highlighter"):
                self.spell_highlighter.set_local_ignored(note.ignored_words)
            self.text_edit.show()
            self.text_edit.setReadOnly(False)
            self.setWindowTitle(f"Мои Заметки — {note.title} [*]")
            self.setWindowModified(False)
            if hasattr(self, "dock_editor"):
                self.dock_editor.setWindowTitle("Редактор")
            pm_vis = bool(getattr(note, "password_manager_visible", False))
            self.password_manager_row.setVisible(False)  # поле PM убрано из UI
            if hasattr(self, "action_toggle_pm"):
                self.action_toggle_pm.blockSignals(True)
                self.action_toggle_pm.setChecked(pm_vis)
                self._update_eye_action(self.action_toggle_pm, pm_vis, self.password_manager_label.text())
                self.action_toggle_pm.blockSignals(False)
            fields_data = list(getattr(note, "custom_fields", []))
            self.clear_custom_fields()
            for field in fields_data:
                self.add_custom_field(field)
            self.add_field_btn.setEnabled(True)
            if hasattr(self, "settings"):
                self.settings.setValue("lastNoteUUID", note.uuid)
            if not getattr(self.current_note, "history", None):
                self.current_note.history = [self.current_note.content]
                self.current_note.history_index = 0
            self.update_history_list()
            self.update_history_list_selection()
            self.show_note_with_attachments(note)
            cursor = self.text_edit.textCursor()
            cursor.clearSelection()
            self.text_edit.setTextCursor(cursor)
            self.tags_label.setText(f"Теги: {', '.join(note.tags) if note.tags else 'нет'}")
            self.password_manager_field.setText(note.password_manager)
            for i in range(self.notes_list.count()):
                item = self.notes_list.item(i)
                n = item.data(Qt.UserRole)
                if n and n.uuid == note.uuid:
                    self.notes_list.setCurrentItem(item)
                    break
        finally:
            self._resume_edit_signals()

    def _html_escape(self, s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


    def _ensure_dd_map(self) -> None:
        if not hasattr(self, "_dropdown_tokens"):
            self._dropdown_tokens = {}


    def _edit_values_and_reopen(self, dd_id: str) -> None:
        info = self._get_dropdown_token_info(dd_id)
        if not info:
            return
        vals = self._open_dropdown_values_editor(info.get("values"))
        if vals is not None:
            info["values"] = vals
            self._update_dropdown_token(dd_id, info.get("value", ""))
            self.show_dropdown_menu_for_token(dd_id)

    def _ensure_typing_defaults(self) -> None:
        fmt = self.text_edit.currentCharFormat()
        f = fmt.font()
        family = (f.family() or "").strip()
        if not family:
            f.setFamily("Times New Roman")
        size = fmt.fontPointSize()
        if not size or size <= 0:
            f.setPointSize(14)
        fmt.setFont(f)
        self.text_edit.setCurrentCharFormat(fmt)
        self.text_edit.document().setDefaultFont(QFont("Times New Roman", 14))
        if hasattr(self, "font_combo"):
            self.font_combo.setCurrentFont(QFont(fmt.font().family() or "Times New Roman"))
        if hasattr(self, "font_size_spin"):
            self.font_size_spin.setValue(int(fmt.fontPointSize() or 14))


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


    def _update_editor_visibility(self):
        has = self.current_note is not None
        self.dock_editor.setVisible(has)
        self.dock_toolbar.setVisible(has)
        self.visibility_toolbar.setVisible(has)
        self.text_edit.setVisible(has)
        self.text_edit.setReadOnly(not has)
        self.tags_label.setVisible(has)
        self._add_field_panel.setVisible(has)
        if not has:
            self.tags_label.clear()
            self.add_field_btn.setEnabled(False)
            self.attachments_scroll.setVisible(False)
            self.password_manager_row.setVisible(False)
            if hasattr(self, "action_toggle_pm"):
                self.action_toggle_pm.setEnabled(False)
            for w in self.custom_fields_widgets:
                w["row"].setVisible(False)
                w["action"].setEnabled(False)
            return
        self.add_field_btn.setEnabled(True)
        note = self.current_note
        pm_vis = bool(getattr(note, "password_manager_visible", False))
        self.password_manager_row.setVisible(False)  # поле PM убрано из UI
        if hasattr(self, "action_toggle_pm"):
            self.action_toggle_pm.setEnabled(True)
            self.action_toggle_pm.blockSignals(True)
            self.action_toggle_pm.setChecked(pm_vis)
            self._update_eye_action(
                self.action_toggle_pm, pm_vis, self.password_manager_label.text()
            )
            self.action_toggle_pm.blockSignals(False)
        for w in self.custom_fields_widgets:
            w["action"].setEnabled(True)
            vis = bool(w["action"].isChecked())
            w["row"].setVisible(vis)
            self._update_eye_action(w["action"], vis, w["label_edit"].text())


    def select_last_or_first_note(self) -> None:
        if not self.notes:
            return
        last_uuid = self.settings.value("lastNoteUuid", "")
        picked = (
            next((n for n in self.notes if n.uuid == last_uuid), None) or self.notes[0]
        )
        self.show_note_with_attachments(picked)
        items = self.notes_list.findItems(picked.title, Qt.MatchExactly)
        if items:
            self.notes_list.setCurrentItem(items[0])


    @staticmethod
    def _app_dir():
        return (
            os.path.dirname(sys.executable)
            if getattr(sys, "frozen", False)
            else os.path.abspath(os.path.dirname(__file__))
        )

    def open_readme(self):
        path = os.path.join(DATA_DIR, "README.md")

        if not os.path.exists(path):
            QMessageBox.warning(self, "README", f"Файл не найден:\n{path}")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("README.md")
        dlg.resize(900, 700)
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


    def _invoke_in_main_thread(self, func: Callable[[], None]) -> None:
        QTimer.singleShot(0, func)


    def toggle_audio_recording(self) -> None:
        if self.audio_thread and self.audio_thread.isRunning():
            self.audio_thread.stop()
            self.audio_thread.wait()
            self.audio_thread = None
            self.audio_button.setText("🎤")
        else:
            if not self.current_note:
                QMessageBox.warning(
                    self, "Нет заметки", "Пожалуйста, выбери или создай заметку."
                )
                return
            note_dir = os.path.join(
                NOTES_DIR,
                safe_folder_name(
                    self.current_note.title,
                    self.current_note.uuid,
                    self.current_note.timestamp,
                ),
            )
            os.makedirs(note_dir, exist_ok=True)
            filename = (
                f"audio_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}.wav"
            )
            full_path = os.path.join(note_dir, filename)

            self.audio_thread = AudioRecorderThread(full_path)
            self.audio_thread.recording_finished.connect(self.insert_audio_link)
            self.audio_thread.start()
            self.audio_button.setText("⏹")


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
            date_str = timestamp.toString("dd.MM.yyyy HH:mm")
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
            line.setFrameShadow(QFrame.Plain)
            line.setFixedHeight(4)
            line.setStyleSheet("""
            QFrame {
                background-color: #000000;      /* тело линии */
                border-top: 1px solid #ffffff;  /* обводка сверху */
                border-bottom: 1px solid #ffffff;/* обводка снизу */
                border-left: none;
                border-right: none;
            }
            """)
            sep_item.setSizeHint(QSize(0, line.height()))
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
                    n = it.data(Qt.UserRole)
                    if n:
                        self.select_note(n)
                    break
        QTimer.singleShot(0, self._apply_dock_proportions)
        self._adjust_notes_list_height()

    def _adjust_notes_list_height(self) -> None:
        def _set_left_section_h(list_h: int) -> None:
            try:
                wrap = getattr(self, "_left_section_notes", None)
                if wrap is None:
                    return
                lay = wrap.layout()
                if lay is None:
                    return
                m = lay.contentsMargins()
                spacing = int(lay.spacing() if lay.spacing() is not None else 0)
                title_h = 0
                try:
                    it0 = lay.itemAt(0)
                    w0 = it0.widget() if it0 is not None else None
                    if w0 is not None:
                        title_h = int(w0.sizeHint().height())
                except Exception:
                    title_h = 0
                total = int(m.top() + m.bottom() + title_h + spacing + int(list_h))
                wrap.setMinimumHeight(total)
                wrap.setMaximumHeight(total)
            except Exception:
                pass

        if self.notes_list.count() == 0:
            self.notes_list.setMinimumHeight(60)
            self.notes_list.setMaximumHeight(60)
            _set_left_section_h(60)
            return
        rows = self.notes_list.count()
        spacing = 0
        try:
            spacing = int(getattr(self.notes_list, "spacing", lambda: 0)())
        except Exception:
            spacing = 0
        total_rows_h = 0
        fm_h = self.notes_list.fontMetrics().height() + 6
        for i in range(rows):
            h = 0
            try:
                h = int(self.notes_list.sizeHintForRow(i))
            except Exception:
                h = 0
            if h <= 0:
                h = fm_h
            total_rows_h += max(1, h)
        frame = self.notes_list.frameWidth() * 2
        margins = self.notes_list.contentsMargins()
        extra = frame + margins.top() + margins.bottom()
        total_h = total_rows_h + max(0, rows - 1) * max(0, spacing) + extra
        total_h += 4
        self.notes_list.setMinimumHeight(total_h)
        self.notes_list.setMaximumHeight(total_h)
        _set_left_section_h(total_h)

    def get_contrast_favorite_color(self) -> QColor:
        bg = self.notes_list.palette().color(self.notes_list.backgroundRole())
        avg = (bg.red() + bg.green() + bg.blue()) / 3
        if avg > 200:
            return QColor(180, 0, 0)
        elif avg > 127:
            return QColor(220, 25, 25)
        else:
            return QColor(255, 60, 60)

    def _show_refresh_busy(self, busy: bool) -> None:
        if busy:
            if not hasattr(self, "_busy_box") or self._busy_box is None:
                self._busy_box = QWidget(self)
                self._busy_box.setObjectName("BusyBox")
                lay = QVBoxLayout(self._busy_box)
                lay.setContentsMargins(0, 0, 0, 0)
                lay.setSpacing(0)
                self._busy_label = QLabel("0%", self._busy_box)
                self._busy_label.setAlignment(Qt.AlignHCenter | Qt.AlignBottom)
                self._busy_label.setStyleSheet(
                    "font-size:10px; font-weight:600; margin-bottom:1px;"
                )
                self._busy_progress = QProgressBar(self._busy_box)
                self._busy_progress.setRange(0, 100)
                self._busy_progress.setValue(0)
                self._busy_progress.setFixedHeight(8)
                self._busy_progress.setTextVisible(False)
                lay.addWidget(self._busy_label)
                lay.addWidget(self._busy_progress)
                self.statusBar().addPermanentWidget(self._busy_box, 1)
            if not hasattr(self, "_busy_timer") or self._busy_timer is None:
                self._busy_timer = QTimer(self)
                self._busy_timer.setInterval(60)
                self._busy_timer.timeout.connect(self._tick_busy_progress)
            self._busy_target = 95
            self._busy_step = 2
            self._busy_timer.start()
            self.statusBar().showMessage("Обновляю…")
            QApplication.setOverrideCursor(Qt.BusyCursor)
            if getattr(self, "refresh_button", None):
                self.refresh_button.setEnabled(False)

        else:
            try:
                if getattr(self, "_busy_timer", None):
                    self._busy_timer.stop()
            except Exception:
                pass
            if getattr(self, "_busy_progress", None):

                def _finish():
                    if not getattr(self, "_busy_progress", None):
                        return
                    cur = self._busy_progress.value()
                    if cur < 100:
                        new_v = min(100, cur + 4)
                        self._busy_progress.setValue(new_v)
                        if getattr(self, "_busy_label", None):
                            self._busy_label.setText(f"{new_v}%")
                        QTimer.singleShot(30, _finish)
                    else:
                        if getattr(self, "_busy_label", None):
                            self._busy_label.setText("100%")
                        QTimer.singleShot(300, self._remove_busy_progress)

                _finish()
            else:
                self._remove_busy_progress()

    def _tick_busy_progress(self):
        if not getattr(self, "_busy_progress", None):
            return
        v = self._busy_progress.value()
        if v < getattr(self, "_busy_target", 95):
            new_v = min(self._busy_target, v + self._busy_step)
            self._busy_progress.setValue(new_v)
            if getattr(self, "_busy_label", None):
                self._busy_label.setText(f"{new_v}%")

    def _remove_busy_progress(self):
        self.statusBar().clearMessage()
        QApplication.restoreOverrideCursor()
        if getattr(self, "refresh_button", None):
            self.refresh_button.setEnabled(True)
        if getattr(self, "_busy_box", None):
            try:
                self.statusBar().removeWidget(self._busy_box)
                self._busy_box.deleteLater()
            except Exception:
                pass
            self._busy_box = None
        if getattr(self, "_busy_progress", None):
            try:
                self._busy_progress.deleteLater()
            except Exception:
                pass
            self._busy_progress = None
        if getattr(self, "_busy_label", None):
            try:
                self._busy_label.deleteLater()
            except Exception:
                pass
            self._busy_label = None
        if getattr(self, "_busy_timer", None):
            try:
                self._busy_timer.stop()
            except Exception:
                pass
            self._busy_timer = None

    def on_refresh_clicked(self) -> None:
        self._show_refresh_busy(True)
        try:
            self.show_toast(
                "Обновляю…",
                timeout_ms=1600,
                anchor_widget=getattr(self, "refresh_button", None),
            )
        except Exception:
            pass
        QApplication.processEvents()

        try:
            if hasattr(self, "refresh_all"):
                self.refresh_all()
            else:
                self.refresh_notes_list()
                if getattr(self, "current_note", None):
                    self.show_note_with_attachments(self.current_note)
        except Exception as e:
            QMessageBox.warning(self, "Обновление", f"Не удалось обновить: {e}")
        finally:
            self._show_refresh_busy(False)


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
                self.show_toast("Теги добавлены", "Добавлены теги: " + ", ".join(added))
                self.tags_label.setText(f"Теги: {', '.join(self.current_note.tags)}")
            else:
                self.show_toast("Нет новых тегов", "Все введённые теги уже есть у заметки.")

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
                date_str = timestamp.toString("dd.MM.yyyy HH:mm")
                reminder_symbol = " 🔔" if note.reminder else ""
                item_text = f"{note.title} — {date_str}{reminder_symbol}"
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, note)
                item.setFont(QFont("Segoe UI Emoji", 10))
                if note.favorite:
                    item.setForeground(QColor("gold"))
                self.notes_list.addItem(item)


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
            return button

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
        add_tool_button("", "🎲 - Генератор чисел", self.open_number_generator)
        add_tool_button("", "🗑 - Корзина", self.show_trash)
        add_tool_button("", "📒 - Заметки", self.show_all_notes)
        self.refresh_button = add_tool_button(
            "", "🔄 - Обновить", self.on_refresh_clicked
        )
        add_tool_button("", "➕ - Новая", self.create_new_note)
        add_tool_button("", "💾 - Сохранить", self.save_note)
        add_tool_button("📎", "📎 - Приерепить файл", self.attach_file_to_note)
        add_tool_button("", "🖌 - Рисовать", self.open_drawing_dialog)
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
        add_tool_button("", "Aa - Регистр (выделение)", self.translate_case_only)
        add_tool_button("", "⌨ - Раскладка (выделение)", self.translate_layout_only)
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
        self.timer_btn = QPushButton()
        self.timer_btn.setFixedHeight(32)
        self.timer_btn.setContextMenuPolicy(Qt.CustomContextMenu)
        self.timer_btn.clicked.connect(self._on_timer_clicked)
        self.timer_btn.customContextMenuRequested.connect(self._timer_context_menu)
        flow_layout.addWidget(self.timer_btn)
        self._update_timer_ui()
        
    def _timer_context_menu(self, pos):
        menu = QMenu(self)
        act_reset = menu.addAction("Сброс")
        act_mode = menu.addAction(
            "Режим: " + ("Обратный отсчёт" if self._timer_mode == "countdown" else "Секундомер")
        )
        sender = self.sender()
        try:
            global_pos = (
                sender.mapToGlobal(pos) if sender is not None else QCursor.pos()
            )
        except Exception:
            global_pos = QCursor.pos()
        act = menu.exec(global_pos)
        if act == act_reset:
            self._reset_timer()
        elif act == act_mode:
            self.toggle_timer_mode()


    def open_number_generator(self):
        dlg = NumberGeneratorDialog(self)
        dlg.exec()

    def refresh_all(self) -> None:
        try:
            current_uuid = (
                self.current_note.uuid if getattr(self, "current_note", None) else None
            )

            self.load_notes_from_disk()
            self.refresh_notes_list()

            if current_uuid:
                note = next((n for n in self.notes if n.uuid == current_uuid), None)
                if not note:
                    self.show_note_with_attachments(None)
                    return

                note_dir = os.path.join(
                    NOTES_DIR,
                    safe_folder_name(note.title, note.uuid, note.timestamp),
                )
                json_path = os.path.join(note_dir, "note.json")
                if os.path.exists(json_path):
                    with open(json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    fresh = Note.from_dict(data)

                    note.title = fresh.title
                    note.content = fresh.content
                    note.tags = list(getattr(fresh, "tags", []))
                    note.password_manager = getattr(fresh, "password_manager", "")
                    note.custom_fields = list(getattr(fresh, "custom_fields", []))
                    note.favorite = getattr(
                        fresh, "favorite", getattr(note, "favorite", False)
                    )

                self.current_note = note
                self.text_edit.blockSignals(True)
                self.text_edit.setHtml(
                    getattr(note, "content_html", "") or note.content
                )
                self.text_edit.blockSignals(False)

                self.tags_label.setText(
                    f"Теги: {', '.join(note.tags) if note.tags else 'нет'}"
                )
                self.password_manager_field.setText(
                    getattr(note, "password_manager", "")
                )
                self._rebuild_attachments_panel(note)

        except Exception as e:
            QMessageBox.warning(self, "Обновление", f"Не удалось обновить: {e}")

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

    def show_random_number(self):
        gen = NumberGenerator(1, 1000)
        num = gen.generate()
        QMessageBox.information(self, "Случайное число", f"Результат: {num}")


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
        note_folder_name = safe_folder_name(
            note.title, note.uuid, note.timestamp
        )
        note_in_trash = os.path.exists(os.path.join(self.TRASH_DIR, note_folder_name))
        if note_in_trash:
            delete_action = QAction("Удалить навсегда", self)
            delete_action.triggered.connect(lambda: self.delete_note_completely(note))
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
            (self.dock_notes_list, "Панель"),
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
        tools_menu = menu_bar.addMenu("Инструменты")
        act_clear_standby = QAction("Очистить Standby List (RAM)", self)
        fn = getattr(self, "clear_standby_list", None)
        if callable(fn):
            act_clear_standby.triggered.connect(fn)
        else:
            act_clear_standby.triggered.connect(
                lambda: QMessageBox.warning(
                    self,
                    "Очистка Standby List",
                    "Функция clear_standby_list отсутствует в этой сборке.",
                )
            )
        tools_menu.addAction(act_clear_standby)
        act_rng = QAction("🎲 Генератор чисел", self)
        act_rng.triggered.connect(self.open_number_generator)
        tools_menu.addAction(act_rng)
        perf_menu = tools_menu.addMenu("Приоритет приложения")
        act_pr_low = QAction("Низкий", self)
        act_pr_low.triggered.connect(lambda: self.set_process_priority_ui("low"))
        perf_menu.addAction(act_pr_low)
        act_pr_bn = QAction("Ниже среднего", self)
        act_pr_bn.triggered.connect(lambda: self.set_process_priority_ui("below_normal"))
        perf_menu.addAction(act_pr_bn)
        act_pr_norm = QAction("Обычный", self)
        act_pr_norm.triggered.connect(lambda: self.set_process_priority_ui("normal"))
        perf_menu.addAction(act_pr_norm)
        act_pr_an = QAction("Выше среднего", self)
        act_pr_an.triggered.connect(lambda: self.set_process_priority_ui("above_normal"))
        perf_menu.addAction(act_pr_an)
        act_pr_high = QAction("Высокий", self)
        act_pr_high.triggered.connect(lambda: self.set_process_priority_ui("high"))
        perf_menu.addAction(act_pr_high)
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
        system_menu = self.menuBar().addMenu("Система")
        act = QAction("Показать текущий приоритет", self)
        act.triggered.connect(self.show_process_priority)
        system_menu.addAction(act)
        prio_sub = system_menu.addMenu("Установить приоритет")
        for lvl, title in [
            ("low", "Низкий"),
            ("below_normal", "Ниже обычного"),
            ("normal", "Обычный"),
            ("above_normal", "Выше обычного"),
            ("high", "Высокий"),
        ]:
            a = prio_sub.addAction(title)
            a.triggered.connect(lambda checked=False, lvl=lvl: self.set_process_priority_ui(lvl))
        self.view_menu = menu_bar.addMenu("Вид")
        for dock, vkey in [
            (self.dock_notes_list, "ui/dock_notes_list_visible"),
            (self.dock_toolbar, "ui/dock_toolbar_visible"),
        ]:
            if dock is None:
                continue
            action = dock.toggleViewAction()
            action.setText(dock.windowTitle())
            dock.visibilityChanged.connect(
                lambda vis, k=vkey: self._save_view_visibility(k, vis)
            )
            self.view_menu.addAction(action)
        self.view_menu.addSeparator()
        self.action_always_on_top = QAction("Поверх всех окон", self)
        self.action_always_on_top.setCheckable(True)
        self.action_always_on_top.setChecked(
            self.settings.value("ui/always_on_top", True, type=bool)
        )
        self.action_always_on_top.toggled.connect(self._toggle_always_on_top)
        self.view_menu.addAction(self.action_always_on_top)
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
            self.visibility_toolbar.visibilityChanged.connect(
                lambda vis: self._save_view_visibility(
                    "ui/visibility_toolbar_visible", vis
                )
            )
            self.toolbars_menu.addAction(tb_action)
        trash_menu = self.menuBar().addMenu("Корзина")
        act = QAction("Показать корзину", self)
        act.triggered.connect(self.show_trash)
        trash_menu.addAction(act)
        act = QAction("Восстановить заметку", self)
        act.triggered.connect(self.restore_note_from_trash)
        trash_menu.addAction(act)
        act = QAction("Удалить навсегда", self)
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

    def _toggle_always_on_top(self, checked: bool) -> None:
        self.setWindowFlag(Qt.WindowStaysOnTopHint, checked)
        self.settings.setValue("ui/always_on_top", checked)
        if (
            hasattr(self, "topmost_checkbox")
            and self.topmost_checkbox.isChecked() != checked
        ):
            self.topmost_checkbox.blockSignals(True)
            self.topmost_checkbox.setChecked(checked)
            self.topmost_checkbox.blockSignals(False)
        if (
            hasattr(self, "action_always_on_top")
            and self.action_always_on_top.isChecked() != checked
        ):
            self.action_always_on_top.blockSignals(True)
            self.action_always_on_top.setChecked(checked)
            self.action_always_on_top.blockSignals(False)
        self.show()


    def _fmt_mmss(self, secs: int) -> str:
        secs = max(0, int(secs))
        return f"{secs // 60:02d}:{secs % 60:02d}"

    def _update_timer_ui(self) -> None:
        if not hasattr(self, "timer_btn") or self.timer_btn is None:
            return

        txt = f"⏱ {self._fmt_mmss(self._timer_left)}"
        self.timer_btn.setText(txt)
        self.timer_btn.setToolTip(
            f"⏱ {txt[2:].strip()} — {('идёт' if self._timer_running else 'пауза')}; "
            "ЛКМ — старт/пауза, ПКМ — сброс, Shift+ЛКМ — задать длительность"
        )

    def _on_timer_clicked(self) -> None:
        if QApplication.keyboardModifiers() & Qt.ShiftModifier:
            self._set_timer_duration_dialog()
            return
        if not self._timer_running:
            self._timer_running = True
            self._timer.start()
        else:
            self._timer_running = False
            self._timer.stop()
        self._update_timer_ui()

    def _reset_timer(self) -> None:
        if self._timer_mode == "countdown":
            self._timer_left = int(self._timer_total)
        else:
            self._timer_left = 0
        self._timer_running = False
        self._timer.stop()
        self._update_timer_ui()

    def _tick_timer(self) -> None:
        if self._timer_mode == "countdown":
            self._timer_left -= 1
            if self._timer_left <= 0:
                self._timer_left = 0
                self._timer_running = False
                try:
                    self._timer.stop()
                except Exception:
                    pass
                try:
                    QApplication.beep()
                    self.show_toast(
                        "⏱ Таймер: Время вышло!",
                        timeout_ms=3000,
                        anchor_widget=getattr(self, "timer_btn", None),
                    )
                    dlg = QMessageBox(self)
                    dlg.setWindowTitle("Таймер")
                    dlg.setText("⏱ Время вышло!")
                    dlg.setIcon(QMessageBox.Icon.Information)
                    dlg.setStandardButtons(QMessageBox.StandardButton.Ok)
                    dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
                    dlg.setModal(True)
                    dlg.adjustSize()
                    win_handle = self.windowHandle()
                    screen = (
                        win_handle.screen()
                        if win_handle is not None
                        else QApplication.primaryScreen()
                    )
                    if screen is not None:
                        geo = screen.availableGeometry()
                        frame_geo = dlg.frameGeometry()
                        frame_geo.moveCenter(geo.center())
                        dlg.move(frame_geo.topLeft())
                    dlg.exec()
                except Exception:
                    pass
            self._update_timer_ui()
            return
        self._timer_left += 1
        self._update_timer_ui()

    def _set_timer_duration_dialog(self) -> None:
        minutes, ok = QInputDialog.getInt(
            self, "⏱ Длительность", "Минут:", max(1, self._timer_total // 60), 1, 240, 1
        )
        if not ok:
            return
        self._timer_total = minutes * 60
        self.settings.setValue("timer/total", int(self._timer_total))
        if self._timer_mode == "countdown":
            self._timer_left = int(self._timer_total)
        self._update_timer_ui()

    def toggle_timer_mode(self) -> None:
        self._timer_mode = (
            "stopwatch" if self._timer_mode == "countdown" else "countdown"
        )
        self.settings.setValue("timer/mode", self._timer_mode)
        self._reset_timer()

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
            QMessageBox.warning(self, "Экспорт", "Сначала выберите заметку для экспорта.")
            return

        items = ["JSON (полный)", "TXT", "PDF", "DOCX", "Markdown (TXT)", "ZIP (папка заметки)"]
        choice, ok = QInputDialog.getItem(self, "Экспорт", "Формат:", items, 0, False)
        if not ok:
            return

        note = self.current_note
        if choice.startswith("JSON"):
            file_path, _ = QFileDialog.getSaveFileName(self, "Экспорт заметки", self.safe_filename(note.title, "json"), "JSON Files (*.json)")
            if not file_path:
                return
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(note.to_dict(), f, ensure_ascii=False, indent=4)
                self.show_toast("Экспорт завершён")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Ошибка экспорта: {e}")
            return

        if choice == "TXT":
            self.export_current_note_txt()
            return
        if choice == "PDF":
            self.export_current_note_pdf()
            return
        if choice == "DOCX":
            self.export_current_note_docx()
            return

        if choice.startswith("Markdown"):
            file_path, _ = QFileDialog.getSaveFileName(self, "Экспорт заметки", self.safe_filename(note.title, "md"), "Markdown (*.md)")
            if not file_path:
                return
            try:
                text = note.content_txt or strip_html(note.content)
                header = f"# {note.title}\n\n"
                tags = ""
                try:
                    _tags = getattr(note, 'tags', None) or []
                    if _tags:
                        tags = "\n\n---\nТеги: " + ", ".join(_tags) + "\n"
                except Exception:
                    tags = ""
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(header + text + tags)
                self.show_toast("Экспорт завершён")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Ошибка экспорта: {e}")
            return

        if choice.startswith("ZIP"):
            note_folder = os.path.join(
                self.notes_folder,
                safe_folder_name(note.title, note.uuid, note.timestamp)
            )
            if not os.path.isdir(note_folder):
                QMessageBox.critical(self, "Ошибка", "Папка заметки не найдена.")
                return
            file_path, _ = QFileDialog.getSaveFileName(self, "Экспорт заметки", f"{note.title}.zip", "ZIP (*.zip)")
            if not file_path:
                return
            try:
                import zipfile
                with zipfile.ZipFile(file_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
                    for root, _, files in os.walk(note_folder):
                        for fn in files:
                            fp = os.path.join(root, fn)
                            rel = os.path.relpath(fp, os.path.dirname(note_folder))
                            z.write(fp, rel)
                self.show_toast("Экспорт завершён")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Ошибка экспорта: {e}")
            return
    def import_note(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Импорт заметки", "", "Заметки (*.json *.txt *.md)")
        if not file_path:
            return
        try:
            ext = os.path.splitext(file_path)[1].lower()
            if ext == '.json':
                with open(file_path, "r", encoding="utf-8") as f:
                    note_data = json.load(f)
                note_data["uuid"] = str(uuid.uuid4())
                note_data["title"] = (note_data.get("title", "") + " (импорт)").strip()
                imported_note = Note.from_dict(note_data)
                imported_note.content_txt = note_data.get('content_txt', '')
            else:
                with open(file_path, "r", encoding="utf-8") as f:
                    text = f.read()
                base = os.path.basename(file_path)
                title = os.path.splitext(base)[0]
                imported_note = Note(title=title + " (импорт)", content=text)
                imported_note.content_txt = text
            self.save_note_to_file(imported_note)
            self.deduplicate_notes()
            self.load_notes_from_disk()
            self.refresh_notes_list()
            self.show_toast("Заметка импортирована")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка импорта: {e}")
    def delete_note_completely(self, note: Note) -> None:
        reply = QMessageBox.question(
            self,
            "Удалить навсегда",
            f"Безвозвратно удалить заметку '{note.title}'? Данные будут удалены полностью.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        candidates = []
        try:
            name_with_ts = safe_folder_name(
                note.title, note.uuid, note.timestamp
            )
        except Exception:
            name_with_ts = safe_folder_name(note.title, note.uuid)
        name_no_ts = safe_folder_name(note.title, note.uuid)
        for base in (NOTES_DIR, self.TRASH_DIR):
            for fname in (name_with_ts, name_no_ts):
                p = os.path.join(base, fname)
                if os.path.exists(p):
                    candidates.append(p)
        try:
            if hasattr(self, "attachments_watcher") and self.attachments_watcher:
                watched = set(self.attachments_watcher.directories() or [])
                to_remove = [p for p in candidates if p in watched]
                if to_remove:
                    self.attachments_watcher.removePaths(list(set(to_remove)))
        except Exception:
            pass
        QApplication.processEvents()
        QThread.msleep(50)
        for p in candidates:
            if os.path.exists(p):
                shutil.rmtree(p)
        self.notes = [n for n in self.notes if n.uuid != note.uuid]
        if self.current_note and self.current_note.uuid == note.uuid:
            self.current_note = None
            self.text_edit.clear()
            if hasattr(self, "history_list"):
                self.history_list.clear()
            self.attachments_scroll.setVisible(False)

        self.refresh_notes_list()
        self.save_all_notes_to_disk()
        self.show_toast(f"«{note.title}» удалена безвозвратно")


    def create_history_toolbar(self):
        toolbar = QToolBar("История версий", self)
        toolbar.setObjectName("history_toolbar")
        toolbar.addWidget(self.history_label)
        toolbar.addWidget(self.history_list)
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, toolbar)


    def _resize_editor_dock(self, delta_px: int) -> None:
        left_dock = getattr(self, "dock_notes_list", None)
        if left_dock is None:
            return
        left_w = max(0, left_dock.width())
        total_w = max(1, self.width())
        min_editor = 300
        max_left = max(80, total_w - min_editor)
        new_left = max(80, min(max_left, left_w - int(delta_px)))
        try:
            self.resizeDocks([left_dock], [new_left], Qt.Horizontal)
        except Exception:
            try:
                left_dock.setMinimumWidth(80)
                left_dock.resize(new_left, left_dock.height())
            except Exception:
                pass


    def _apply_saved_notes_order(self) -> None:
        if not isinstance(getattr(self, "notes", None), list) or not self.notes:
            return
        order = self._load_notes_order()
        pinned_order = order.get("pinned") or []
        unpinned_order = order.get("unpinned") or []
        by_uuid: dict[str, Note] = {}
        for n in self.notes:
            if getattr(n, "uuid", None):
                by_uuid[str(n.uuid)] = n
        pinned_notes = [n for n in by_uuid.values() if getattr(n, "pinned", False)]
        unpinned_notes = [n for n in by_uuid.values() if not getattr(n, "pinned", False)]
        pinned_sorted_rest = sorted(
            [n for n in pinned_notes if str(n.uuid) not in pinned_order],
            key=self._timestamp_sort_key,
            reverse=True,
        )
        unpinned_sorted_rest = sorted(
            [n for n in unpinned_notes if str(n.uuid) not in unpinned_order],
            key=self._timestamp_sort_key,
            reverse=True,
        )
        pinned_final: list[Note] = [
            by_uuid[u]
            for u in pinned_order
            if u in by_uuid and getattr(by_uuid[u], "pinned", False)
        ]
        unpinned_final: list[Note] = [
            by_uuid[u]
            for u in unpinned_order
            if u in by_uuid and (not getattr(by_uuid[u], "pinned", False))
        ]
        pinned_final.extend(pinned_sorted_rest)
        unpinned_final.extend(unpinned_sorted_rest)
        self.notes = pinned_final + unpinned_final

    def handle_note_reorder(self) -> None:
        try:
            pinned: list[str] = []
            unpinned: list[str] = []
            seen: set[str] = set()
            for i in range(self.notes_list.count()):
                item = self.notes_list.item(i)
                if item is None:
                    continue
                note = item.data(Qt.UserRole)
                if not note or not getattr(note, "uuid", None):
                    continue
                uid = str(note.uuid)
                if uid in seen:
                    continue
                seen.add(uid)
                if getattr(note, "pinned", False):
                    pinned.append(uid)
                else:
                    unpinned.append(uid)
            self._save_notes_order(pinned, unpinned)
            current_uuid = getattr(getattr(self, "current_note", None), "uuid", None)
            self._apply_saved_notes_order()
            self.refresh_notes_list()
            if current_uuid:
                for i in range(self.notes_list.count()):
                    it = self.notes_list.item(i)
                    n = it.data(Qt.UserRole)
                    if n and getattr(n, "uuid", None) == current_uuid:
                        self.notes_list.setCurrentRow(i)
                        break
        except Exception:
            try:
                self.refresh_notes_list()
            except Exception:
                pass

    def init_all_components(self):
        QShortcut(QKeySequence("Escape"), self.text_edit, self.exit_note)
        QShortcut(QKeySequence("Ctrl+B"), self.text_edit, self.toggle_bold)
        QShortcut(QKeySequence("Ctrl+I"), self.text_edit, self.toggle_italic)
        QShortcut(QKeySequence("Ctrl+U"), self.text_edit, self.toggle_underline)
        QShortcut(QKeySequence("Ctrl+N"), self, self.create_new_note)
        QShortcut(QKeySequence("Ctrl+S"), self, self.save_note)
        QShortcut(QKeySequence("Ctrl+Space"), self.text_edit, self.clear_formatting)
        QShortcut(
            QKeySequence("Ctrl+Shift+D"), self, activated=self.open_drawing_dialog
        )

        self._notes_delete_sc = QShortcut(QKeySequence.Delete, self.notes_list)
        self._notes_delete_sc.setContext(Qt.WidgetWithChildrenShortcut)
        self._notes_delete_sc.activated.connect(self.delete_note)
        self.notes = []
        self.refresh_notes_list()
        self.setAcceptDrops(True)
        self.autosave_enabled = self.settings.value("autosave_enabled", True, type=bool)
        self._edit_session_note_uuid = None

    def _suspend_edit_signals(self):
        try:
            self._is_switching_note = True
            if hasattr(self, "debounce_timer"):
                self.debounce_timer.stop()
            self.text_edit.blockSignals(True)
        except Exception:
            pass
    def _on_text_selection_changed(self) -> None:
        try:
            cur = self.text_edit.textCursor()
            if cur.hasSelection():
                self._last_selection = (int(cur.selectionStart()), int(cur.selectionEnd()))
        except Exception:
            pass

    def _resume_edit_signals(self):
        try:
            self.text_edit.blockSignals(False)
        finally:
            self._is_switching_note = False


    def exit_note(self):
        self.load_note(None)
        self.current_note = None
        self.notes_list.clearSelection()
        self._update_editor_visibility()


    def eventFilter(self, source, event):
        if (
            isinstance(source, QLineEdit)
            and source.property("renameTitleEditor")
            and event.type() == QEvent.KeyPress
        ):
            if source.hasSelectedText() and len(source.selectedText()) == len(
                source.text()
            ):
                if event.key() == Qt.Key_Left:
                    source.setCursorPosition(0)
                    source.setSelection(0, 0)
                    return True
                if event.key() == Qt.Key_Right:
                    source.setCursorPosition(len(source.text()))
                    source.setSelection(0, 0)
                    return True
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
                    safe_folder_name(
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
        try:
            self.show_toast(
                "Файлы прикреплены",
                timeout_ms=1400,
                anchor_widget=getattr(self, "attachments_scroll", None),
            )
        except Exception:
            pass
        self.save_note()

    def closeEvent(self, event: QCloseEvent):
        self.save_settings()
        try:
            self.save_note_quiet(force=True)
            if getattr(self, "current_note", None):
                self.save_note_quiet(force=True)
            self.save_all_notes_to_disk()
        except Exception:
            logging.exception("Save on close failed")
        event.ignore()
        self.hide()
        try:
            if self.tray_icon is not None:
                self.tray_icon.show()
        except Exception:
            pass
        self.window_hidden.emit()


    def update_current_note_content(self):
        if not hasattr(self, "current_note") or self.current_note is None:
            return
        html = self.text_edit.toHtml()
        html = self._persist_dropdown_values_in_html(html)
        self.current_note.content = html
        self.record_state_for_undo()

    def hideEvent(self, event):
        self.save_settings()
        super().hideEvent(event)


    def moveEvent(self, event):
        self.save_settings()
        super().moveEvent(event)


def get_app_dir():
    return APPDIR


def main(argv=None):
    argv = sys.argv if argv is None else argv
    try:
        init_app_environment()
        app = QApplication(argv)

        autostart = os.environ.get("CHOICE_AUTOSTART", "").strip() == "1"
        if autostart:
            app.setQuitOnLastWindowClosed(False)

        win = NotesApp()

        if autostart:
            win._init_tray_icon()
            win.hide()
        else:
            win.show()

        rc = app.exec()
        logging.info(f"=== APP EXIT rc={rc} ===")
        return rc
    except Exception:
        logging.exception("Fatal exception in main()")
        raise
