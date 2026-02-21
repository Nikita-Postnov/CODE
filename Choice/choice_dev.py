from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem
from typing import Optional
import ast
import json
import os
import shutil
import sys
from functools import partial
import shlex
import subprocess
import time
from PySide6.QtCore import QProcess, QProcessEnvironment, QSize, QTimer, QByteArray
from PySide6.QtGui import QIcon, QFont, QKeySequence, QAction, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QApplication,
    QInputDialog,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QGroupBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QListWidget,
    QListWidgetItem,
    QCheckBox,
    QPlainTextEdit,
    QSplitter,
    QTabWidget,
    QToolBar,
    QStatusBar,
    QMessageBox,
    QSizePolicy,
    QMenu,
    QSystemTrayIcon,
)

MAX_LOG_LINES = 5000
APP_TITLE = "Choice"
CONFIG_FILENAME = "launcher_config.json"

def app_folder() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

def config_file() -> Path:
    return app_folder() / CONFIG_FILENAME

def running_on_windows() -> bool:
    return sys.platform.startswith("win")

def split_command_line(s: str) -> list[str]:
    s = (s or "").strip()
    if not s:
        return []
    return shlex.split(s, posix=not running_on_windows())

def detect_system_python() -> str:
    if sys.executable:
        return sys.executable
    return "python.exe" if running_on_windows() else "python"

def find_python_icon() -> Optional[str]:
    candidates = []
    try:
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    except Exception:
        base = Path(__file__).resolve().parent
    candidates.append(base / "choice.ico")
    candidates.append(Path(__file__).resolve().parent / "choice.ico")
    try:
        candidates.append(Path(sys.executable).resolve().parent / "choice.ico")
    except Exception:
        pass
    for p in candidates:
        try:
            if p.exists():
                return str(p)
        except Exception:
            continue
    return None

def list_python_files(root: Path, recursive: bool) -> list[Path]:
    if not root.exists() or not root.is_dir():
        return []

    launcher_path = Path(__file__).resolve()

    def excluded(p: Path) -> bool:
        if any(part.lower() == "plugins" for part in p.parts):
            return True
        try:
            return p.resolve() == launcher_path
        except Exception:
            return False

    found = root.rglob("*.py") if recursive else root.glob("*.py")
    files = [p for p in found if p.is_file() and not excluded(p)]
    files.sort(key=lambda p: (p.name.lower(), str(p).lower()))
    return files

def safe_open(p: Path) -> bool:
    p = Path(p)
    if not p.exists():
        return False

    try:
        if running_on_windows():
            os.startfile(str(p))
            return True

        rc = subprocess.call(["xdg-open", str(p)])
        return rc == 0
    except Exception:
        return False


def time_stamp() -> str:
    return time.strftime("%Y-%m-%d_%H-%M-%S")


@dataclass
class Settings:
    autostart_scripts: list[str] | None = None
    python_executable: str = ""
    scripts_folder: str = ""
    last_script_path: str = ""
    last_arguments: str = ""
    last_workdir: str = ""
    scan_subfolders: bool = False
    clear_output_on_start: bool = True
    favorites: list[str] | None = None
    autoscroll_output: bool = True
    show_errors_tab: bool = True
    per_script_workdir: dict[str, str] | None = None
    per_script_args: dict[str, str] | None = None
    per_script_shortcut: dict[str, str] | None = None
    per_script_icon: dict[str, str] | None = None
    recent_runs: list[dict] | None = None
    editor_command: str = ""
    env_text: str = ""
    window_geometry_b64: str = ""
    splitter_state_b64: str = ""

    @staticmethod
    def load(path: Path) -> "Settings":
        if not path.exists():
            return Settings()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            s = Settings()
            for k, v in data.items():
                if hasattr(s, k):
                    setattr(s, k, v)
            return s
        except Exception:
            return Settings()

    def save(self, path: Path) -> None:
        data = {
            "autostart_scripts": self.autostart_scripts or [],
            "python_executable": self.python_executable,
            "scripts_folder": self.scripts_folder,
            "last_script_path": self.last_script_path,
            "last_arguments": self.last_arguments,
            "last_workdir": self.last_workdir,
            "scan_subfolders": self.scan_subfolders,
            "clear_output_on_start": self.clear_output_on_start,
            "favorites": self.favorites or [],
            "autoscroll_output": self.autoscroll_output,
            "show_errors_tab": self.show_errors_tab,
            "per_script_workdir": self.per_script_workdir or {},
            "per_script_args": self.per_script_args or {},
            "per_script_shortcut": self.per_script_shortcut or {},
            "per_script_icon": self.per_script_icon or {},
            "recent_runs": self.recent_runs or [],
            "editor_command": self.editor_command,
            "env_text": self.env_text,
            "window_geometry_b64": self.window_geometry_b64,
            "splitter_state_b64": self.splitter_state_b64,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

class FriendlyLauncher(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings.load(config_file())
        self.processes: dict[int, QProcess] = {}
        self.proc_start_time: dict[int, float] = {}
        self.proc_info: dict[int, dict] = {}
        self.proc_counter: int = 0
        self.all_scripts: list[Path] = []
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(QSize(1100, 700))
        self._create_actions()
        self._create_toolbar()
        self._create_main_ui()
        self.setStatusBar(QStatusBar(self))
        self._allow_quit: bool = False
        self._init_tray()
        QTimer.singleShot(0, self._startup_deferred)

    def _startup_deferred(self) -> None:
        self._refresh_script_list(save=False)
        self._restore_previous()
        self._update_script_preview()
        self._restore_window_state()
        self._run_autostart_scripts()

    def _is_window_effectively_visible(self) -> bool:
        if not self.isVisible():
            return False
        if self.isMinimized():
            return False
        return True

    def _sync_tray_menu(self) -> None:
        visible = self._is_window_effectively_visible()
        self.a_tray_show.setVisible(not visible)
        self.a_tray_hide.setVisible(visible)

    def _init_tray(self) -> None:
        icon_path = find_python_icon()
        ico = QIcon(icon_path) if icon_path else self.windowIcon()

        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(ico)
        self.tray.setToolTip(APP_TITLE)

        self.tray_menu = QMenu()

        self.a_tray_show = self.tray_menu.addAction("Открыть Choice")
        self.a_tray_hide = self.tray_menu.addAction("Свернуть в трей")
        self.tray_menu.addSeparator()
        self.a_tray_quit = self.tray_menu.addAction("Полностью закрыть")

        self.a_tray_show.triggered.connect(self._tray_show_window)
        self.a_tray_hide.triggered.connect(self._tray_hide_window)
        self.a_tray_quit.triggered.connect(self._tray_quit)

        self.tray_menu.aboutToShow.connect(self._sync_tray_menu)

        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._tray_toggle_window()

    def _tray_toggle_window(self) -> None:
        if self.isVisible() and not self.isMinimized():
            self._tray_hide_window()
        else:
            self._tray_show_window()

    def _tray_show_window(self) -> None:
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def _tray_hide_window(self) -> None:
        self.hide()

    def _tray_quit(self) -> None:
        self._allow_quit = True
        try:
            if hasattr(self, "tray") and self.tray:
                self.tray.hide()
        except Exception:
            pass
        try:
            self.close()
        finally:
            app = QApplication.instance()
            if app is not None:
                app.quit()

    def _is_window_effectively_visible(self) -> bool:
        return self.isVisible() and not self.isMinimized()

    def _show_tray_menu(self, pos) -> None:
        menu = QMenu()

        if not self._is_window_effectively_visible():
            a_show = menu.addAction("Открыть Choice")
            a_show.triggered.connect(self._tray_show_window)
        else:
            a_hide = menu.addAction("Свернуть в трей")
            a_hide.triggered.connect(self._tray_hide_window)

        menu.addSeparator()
        a_quit = menu.addAction("Полностью закрыть")
        a_quit.triggered.connect(self._tray_quit)

        menu.exec(pos)

    def closeEvent(self, event) -> None:
        if not getattr(self, "_allow_quit", False):
            try:
                self._save_settings()
            except Exception:
                pass
            try:
                self.hide()
            except Exception:
                pass
            try:
                event.ignore()
            except Exception:
                pass
            return

        try:
            self.settings.window_geometry_b64 = bytes(self.saveGeometry().toBase64()).decode("ascii", errors="ignore")
        except Exception:
            pass
        try:
            if hasattr(self, "splitter"):
                self.settings.splitter_state_b64 = bytes(self.splitter.saveState().toBase64()).decode("ascii", errors="ignore")
        except Exception:
            pass
        try:
            self._shutdown_processes()
        except Exception:
            pass
        try:
            self._save_settings()
        except Exception:
            pass
        try:
            if hasattr(self, "tray") and self.tray:
                self.tray.hide()
        except Exception:
            pass
        try:
            event.accept()
        except Exception:
            pass
        app = QApplication.instance()
        if app is not None:
            app.quit()
        return



    def _restore_window_state(self) -> None:
        try:
            g = (self.settings.window_geometry_b64 or "").strip()
            if g:
                ba = QByteArray.fromBase64(g.encode("ascii", errors="ignore"))
                if not ba.isEmpty():
                    self.restoreGeometry(ba)
        except Exception:
            pass
        try:
            s = (self.settings.splitter_state_b64 or "").strip()
            if s and hasattr(self, "splitter"):
                ba = QByteArray.fromBase64(s.encode("ascii", errors="ignore"))
                if not ba.isEmpty():
                    self.splitter.restoreState(ba)
        except Exception:
            pass

    def _has_running(self) -> bool:
        return any(p.state() != QProcess.NotRunning for p in self.processes.values())
    
    def _is_same_script_running(self, script: str) -> bool:
        for rid, info in self.proc_info.items():
            if (info.get("script") or "") == script:
                p = self.processes.get(rid)
                if p and p.state() != QProcess.NotRunning:
                    return True
        return False
    
    def _update_run_item_title(self, rid: int, pid: int) -> None:
        for i in range(self.running_list.count()):
            it = self.running_list.item(i)
            if it and it.data(Qt.UserRole) == rid:
                name = Path(self.proc_info.get(rid, {}).get("script", "")).name
                it.setText(f"#{i + 1} {name}")
                return

    def _remove_run_item(self, rid: int) -> None:
        self.processes.pop(rid, None)
        self.proc_start_time.pop(rid, None)
        self.proc_info.pop(rid, None)
        removed = False
        for i in range(self.running_list.count()):
            it = self.running_list.item(i)
            if it and it.data(Qt.UserRole) == rid:
                self.running_list.takeItem(i)
                removed = True
                break
        if removed:
            self._renumber_running_items()

    def _renumber_running_items(self) -> None:
        for i in range(self.running_list.count()):
            it = self.running_list.item(i)
            if not it:
                continue
            rid = it.data(Qt.UserRole)
            if not isinstance(rid, int):
                continue
            name = Path(self.proc_info.get(rid, {}).get("script", "")).name
            it.setText(f"#{i + 1} {name}")

    def _display_no_for_rid(self, rid: int) -> int:
        for i in range(self.running_list.count()):
            it = self.running_list.item(i)
            if it and it.data(Qt.UserRole) == rid:
                return i + 1
        return rid
    
    def _proc_prefix(self, rid: int) -> str:
        dn = self._display_no_for_rid(rid)
        script = (self.proc_info.get(rid, {}).get("script") or "").strip()
        name = Path(script).name if script else "process"
        return f"[#{dn} {name}]"

    def _selected_run_ids(self) -> list[int]:
        ids: list[int] = []
        for it in self.running_list.selectedItems():
            rid = it.data(Qt.UserRole)
            if isinstance(rid, int):
                ids.append(rid)
        return ids

    def _update_stop_enabled(self) -> None:
        self.stop_button.setEnabled(bool(self._selected_run_ids()))
        self.action_stop.setEnabled(bool(self._selected_run_ids()))

    def _send_stdin_to_selected(self) -> None:
        text = (self.stdin_field.text() or "").strip()
        if not text:
            return
        ids = self._selected_run_ids()
        if not ids:
            QMessageBox.information(self, "Ввод", "Выберите запущенный процесс в списке 'Запущенные процессы'.")
            return

        if len(ids) > 1:
            QMessageBox.information(self, "Ввод", "Выберите один процесс (сейчас выбрано несколько).")
            return

        rid = ids[0]
        p = self.processes.get(rid)
        if not p or p.state() == QProcess.NotRunning:
            QMessageBox.information(self, "Ввод", "Процесс не запущен.")
            return

        try:
            payload = (text + "\n").encode("utf-8", errors="replace")
            p.write(payload)
            p.waitForBytesWritten(500)
        except Exception as e:
            QMessageBox.warning(self, "Ввод", f"Не удалось отправить ввод в процесс: {e}")
            return

        self._append_output(f"[#{self._display_no_for_rid(rid)}] > {text}")
        self.stdin_field.clear()
        self.stdin_field.setFocus()

    def _run_item_activated(self, item: QListWidgetItem) -> None:
        if not item:
            return
        path = (item.data(Qt.UserRole) or "").strip()
        if path:
            self._set_current_script(path)
            self.run_script()

    def _stdlib_names(self) -> set[str]:
        try:
            names = set(getattr(sys, "stdlib_module_names", set()) or set())
            if names:
                return set(names)
        except Exception:
            pass
        base = {
            "os","sys","time","json","re","math","pathlib","typing","dataclasses","subprocess","shlex","shutil",
            "threading","asyncio","logging","unittest","sqlite3","csv","datetime","collections","itertools",
            "functools","statistics","http","urllib","socket","email","tkinter","xml","html","traceback"
        }
        return base

    def _create_actions(self) -> None:
        self.action_run = QAction("Запустить", self)
        self.action_run.setShortcut(QKeySequence("Ctrl+R"))
        self.action_run.triggered.connect(self.run_script)
        self.action_stop = QAction("Остановить", self)
        self.action_stop.setShortcut(QKeySequence("Ctrl+E"))
        self.action_stop.triggered.connect(self.stop_script)
        self.action_stop.setEnabled(False)
        self.action_rescan = QAction("Пересканировать", self)
        self.action_rescan.setShortcut(QKeySequence.Refresh)
        self.action_rescan.triggered.connect(self._refresh_script_list)
        self.action_open_folder = QAction("Открыть папку скриптов", self)
        self.action_open_folder.triggered.connect(self._open_scripts_folder)
        self.action_open_config = QAction("Открыть файл настроек", self)
        self.action_open_config.triggered.connect(self._open_config_file)
        self.action_save_log = QAction("Сохранить лог", self)
        self.action_save_log.triggered.connect(self._save_log)
        self.action_clear_output = QAction("Очистить вывод", self)
        self.action_clear_output.setShortcut(QKeySequence("Ctrl+L"))
        self.action_clear_output.triggered.connect(self._clear_output_clicked)
        self.action_check_env = QAction("Проверить окружение", self)
        self.action_check_env.setShortcut(QKeySequence("Ctrl+D"))
        self.action_check_env.triggered.connect(self._run_system_checks)
        self.action_open_in_editor = QAction("Открыть в редакторе", self)
        self.action_open_in_editor.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self.action_open_in_editor.triggered.connect(self._open_current_script_in_editor)
        self.action_configure_editor = QAction("Настроить редактор", self)
        self.action_configure_editor.triggered.connect(self._configure_editor)
        self.action_check_requirements = QAction("Проверить требования (импорты)", self)
        self.action_check_requirements.setShortcut(QKeySequence("Ctrl+T"))
        self.action_check_requirements.triggered.connect(self._check_requirements_for_current_script)

    def _create_toolbar(self) -> None:
        tb = QToolBar("Главное", self)
        tb.setMovable(False)
        self.addToolBar(tb)
        tb.addAction(self.action_run)
        tb.addAction(self.action_stop)
        tb.addSeparator()
        tb.addAction(self.action_rescan)
        tb.addSeparator()
        tb.addAction(self.action_check_env)
        tb.addSeparator()
        tb.addAction(self.action_open_in_editor)
        tb.addAction(self.action_check_requirements)
        tb.addSeparator()
        tb.addAction(self.action_open_folder)
        tb.addAction(self.action_open_config)
        tb.addAction(self.action_configure_editor)
        tb.addAction(self.action_clear_output)
        tb.addAction(self.action_save_log)

    def _create_main_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        splitter = QSplitter(Qt.Horizontal, self)
        self.splitter = splitter
        main_layout.addWidget(splitter, 1)
        left_panel = QWidget(self)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        folder_box = QGroupBox("Папка со скриптами")
        folder_layout = QFormLayout(folder_box)
        self.python_field = QLineEdit(self.settings.python_executable or detect_system_python())
        self.python_field.textChanged.connect(lambda: self._save_debounce.start(400))
        btn_python = QPushButton("Выбрать интерпретатор")
        btn_python.clicked.connect(self._choose_python)
        python_row = QWidget()
        py_row_layout = QHBoxLayout(python_row)
        py_row_layout.setContentsMargins(0, 0, 0, 0)
        py_row_layout.addWidget(self.python_field, 1)
        py_row_layout.addWidget(btn_python)
        folder_layout.addRow("Python:", python_row)
        self.folder_field = QLineEdit(self.settings.scripts_folder or str(app_folder()))
        self.folder_field.textChanged.connect(lambda: self._save_debounce.start(400))
        btn_folder = QPushButton("Папка")
        btn_folder.clicked.connect(self._choose_scripts_folder)
        folder_row = QWidget()
        folder_row_layout = QHBoxLayout(folder_row)
        folder_row_layout.setContentsMargins(0, 0, 0, 0)
        folder_row_layout.addWidget(self.folder_field, 1)
        self._save_debounce = QTimer(self)
        self._save_debounce.setSingleShot(True)
        self._save_debounce.timeout.connect(self._save_settings)
        folder_row_layout.addWidget(btn_folder)
        folder_layout.addRow("Каталог:", folder_row)
        self.scan_checkbox = QCheckBox("Искать в подпапках")
        self.scan_checkbox.setChecked(bool(self.settings.scan_subfolders))
        self._scan_debounce = QTimer(self)
        self._scan_debounce.setSingleShot(True)
        self._scan_debounce.timeout.connect(self._refresh_script_list)
        self.scan_checkbox.stateChanged.connect(lambda: self._scan_debounce.start(300))
        folder_layout.addRow("", self.scan_checkbox)
        left_layout.addWidget(folder_box)
        selection_box = QGroupBox("Скрипты")
        selection_layout = QVBoxLayout(selection_box)

        search_block = QVBoxLayout()
        search_block.setContentsMargins(0, 0, 0, 0)
        search_block.setSpacing(6)

        fav_row = QHBoxLayout()
        fav_row.setContentsMargins(0, 0, 0, 0)
        fav_row.setSpacing(8)

        self.fav_only_checkbox = QCheckBox("Только избранные")
        self.fav_only_checkbox.stateChanged.connect(self._apply_filters)
        self.fav_only_checkbox.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        fav_row.addStretch(1)
        fav_row.addWidget(self.fav_only_checkbox, 0)

        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Поиск по имени")
        self.search_field.setClearButtonEnabled(True)
        self.search_field.textChanged.connect(self._apply_filters)
        self.search_field.returnPressed.connect(self._run_first_visible_script)
        self.search_field.setMinimumWidth(220)
        self.search_field.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        search_block.addLayout(fav_row)
        search_block.addWidget(self.search_field)
        selection_layout.addLayout(search_block)
        self.scripts_list = QListWidget()
        self.scripts_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.scripts_list.customContextMenuRequested.connect(self._scripts_context_menu)
        self.scripts_list.currentItemChanged.connect(self._on_script_selected)
        self.scripts_list.itemActivated.connect(self._run_item_activated)
        selection_layout.addWidget(self.scripts_list, 1)
        list_buttons = QWidget()
        list_buttons_layout = QHBoxLayout(list_buttons)
        pick_btn = QPushButton("Выбрать файл")
        pick_btn.clicked.connect(self._pick_script_file)
        refresh_btn = QPushButton("Обновить")
        refresh_btn.clicked.connect(self._refresh_script_list)
        self.star_button = QPushButton("☆")
        self.star_button.setToolTip("Отметить/снять избранное")
        self.star_button.clicked.connect(self._toggle_favorite)
        list_buttons_layout.addWidget(pick_btn)
        list_buttons_layout.addWidget(refresh_btn)
        list_buttons_layout.addStretch(1)
        list_buttons_layout.addWidget(self.star_button)
        selection_layout.addWidget(list_buttons)
        left_layout.addWidget(selection_box, 1)
        middle_panel = QWidget(self)
        middle_layout = QVBoxLayout(middle_panel)
        middle_layout.setContentsMargins(8, 8, 8, 8)
        run_box = QGroupBox("Параметры запуска")
        run_layout = QFormLayout(run_box)
        self.args_field = QLineEdit(self.settings.last_arguments or "")
        self.args_field.setPlaceholderText('--name "test"')
        self.args_field.textChanged.connect(self._remember_args)
        run_layout.addRow("Аргументы:", self.args_field)
        self.workdir_field = QLineEdit(self.settings.last_workdir or "")
        self.workdir_field.textChanged.connect(lambda: self._save_debounce.start(400))
        self.workdir_field.setPlaceholderText("Если пусто — используется папка со скриптом")
        self.workdir_field.textChanged.connect(self._update_script_preview)
        btn_wd = QPushButton("Папка")
        btn_wd.clicked.connect(self._pick_workdir)
        wd_row = QWidget()
        wd_row_layout = QHBoxLayout(wd_row)
        wd_row_layout.setContentsMargins(0, 0, 0, 0)
        wd_row_layout.addWidget(self.workdir_field, 1)
        wd_row_layout.addWidget(btn_wd)
        run_layout.addRow("Рабочая папка:", wd_row)
        self.clear_checkbox = QCheckBox("Очищать вывод при запуске")
        self.clear_checkbox.setChecked(bool(self.settings.clear_output_on_start))
        run_layout.addRow("", self.clear_checkbox)
        self.autoscroll_checkbox = QCheckBox("Автопрокрутка")
        self.autoscroll_checkbox.setChecked(bool(self.settings.autoscroll_output))
        self.autoscroll_checkbox.stateChanged.connect(self._save_autoscroll)
        run_layout.addRow("", self.autoscroll_checkbox)
        env_group = QGroupBox("Переменные окружения (каждая строка ключ=значение)")
        env_layout = QVBoxLayout(env_group)
        self._env_save_debounce = QTimer(self)
        self._env_save_debounce.setSingleShot(True)
        self._env_save_debounce.timeout.connect(self._save_settings)
        self.env_editor = QPlainTextEdit()
        self.env_editor.setPlainText(self.settings.env_text or "")
        self.env_editor.textChanged.connect(lambda: self._env_save_debounce.start(500))
        env_layout.addWidget(self.env_editor)
        run_layout.addRow(env_group)
        middle_layout.addWidget(run_box)
        self.script_info_label = QLabel()
        self.script_info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.script_info_label.setWordWrap(True)
        middle_layout.addWidget(self.script_info_label)
        controls_row = QWidget()
        controls_layout = QHBoxLayout(controls_row)
        self.run_button = QPushButton("▶ Запустить")
        self.run_button.clicked.connect(self.run_script)
        self.run_button.setDefault(True)
        self.stop_button = QPushButton("■ Остановить")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_script)
        self.preview_button = QPushButton("Копировать путь")
        self.preview_button.clicked.connect(self._copy_preview)
        controls_layout.addWidget(self.run_button)
        controls_layout.addWidget(self.stop_button)
        controls_layout.addWidget(self.preview_button)
        controls_layout.addStretch(1)
        middle_layout.addWidget(controls_row)
        running_box = QGroupBox("Запущенные процессы")
        running_layout = QVBoxLayout(running_box)
        self.running_list = QListWidget()
        self.running_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.running_list.currentItemChanged.connect(lambda *_: self._update_stop_enabled())
        self.running_list.itemSelectionChanged.connect(self._update_stop_enabled)
        self.running_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.running_list.customContextMenuRequested.connect(self._running_context_menu)
        running_layout.addWidget(self.running_list)

        self._ensure_list_min_rows(self.running_list, 4)

        middle_layout.addWidget(running_box)
        recent_box = QGroupBox("История запусков")
        recent_layout = QVBoxLayout(recent_box)
        self.recent_list = QListWidget()
        self.recent_list.itemActivated.connect(self._apply_recent)
        recent_layout.addWidget(self.recent_list)
        recent_buttons = QWidget()
        recent_buttons_layout = QHBoxLayout(recent_buttons)
        clear_history = QPushButton("Очистить историю")
        clear_history.clicked.connect(self._clear_history)
        recent_buttons_layout.addStretch(1)
        recent_buttons_layout.addWidget(clear_history)
        recent_layout.addWidget(recent_buttons)
        middle_layout.addWidget(recent_box, 1)
        right_panel = QWidget(self)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)
        self.output_tabs = QTabWidget()
        self.output_text = QPlainTextEdit()
        self.output_text.setReadOnly(True)
        try:
            self.output_text.setFont(QFont("Consolas", 10))
        except Exception:
            pass
        self.output_text.setPlaceholderText("Стандартный вывод (stdout)")
        self.error_text = QPlainTextEdit()
        self.error_text.setReadOnly(True)
        try:
            self.error_text.setFont(QFont("Consolas", 10))
        except Exception:
            pass
        self.error_text.setPlaceholderText("Ошибки и диагностика (stderr)")
        self.output_tabs.addTab(self.output_text, "Вывод")
        if bool(self.settings.show_errors_tab):
            self.output_tabs.addTab(self.error_text, "Ошибки")
        bottom_row = QWidget()
        bottom_layout = QGridLayout(bottom_row)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setHorizontalSpacing(8)
        bottom_layout.setVerticalSpacing(6)

        clear_out_btn = QPushButton("Очистить")
        clear_out_btn.clicked.connect(self._clear_output_clicked)

        save_log_btn = QPushButton("Сохранить лог")
        save_log_btn.clicked.connect(self._save_log)

        open_cfg_btn = QPushButton("Настройки")
        open_cfg_btn.clicked.connect(self._open_config_file)

        buttons_row = QWidget()
        buttons_layout = QHBoxLayout(buttons_row)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.addWidget(clear_out_btn)
        buttons_layout.addWidget(save_log_btn)
        buttons_layout.addWidget(open_cfg_btn)
        buttons_layout.addStretch(1)

        self.stdin_field = QLineEdit()
        self.stdin_field.setPlaceholderText("Ввод для запущенного процесса (Enter — отправить)")
        self.stdin_field.setMinimumWidth(520)
        self.stdin_field.returnPressed.connect(self._send_stdin_to_selected)

        bottom_layout.addWidget(buttons_row, 0, 0, 1, 1)
        bottom_layout.addWidget(self.stdin_field, 1, 0, 1, 1)

        bottom_layout.setRowStretch(0, 0)
        bottom_layout.setRowStretch(1, 0)
        right_layout.addWidget(self.output_tabs, 1)
        right_layout.addWidget(bottom_row)
        splitter.addWidget(left_panel)
        splitter.addWidget(middle_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 3)
        splitter.setSizes([320, 320, 760])

    def _run_first_visible_script(self) -> None:
        if self.scripts_list.count() <= 0:
            return
        it = self.scripts_list.item(0)
        if not it:
            return
        path = (it.data(Qt.UserRole) or "").strip()
        if not path:
            return
        self._set_current_script(path)
        self.run_script()


    def _choose_python(self) -> None:
        start = self.python_field.text().strip()
        start_dir = str(Path(start).parent) if start and Path(start).exists() else str(app_folder())
        path, _ = QFileDialog.getOpenFileName(self, "Выберите интерпретатор Python", start_dir, "Python (python.exe);;Все файлы (*)" if running_on_windows() else "Все файлы (*)")
        if path:
            self.python_field.setText(path)
            self._save_settings()

    def _configure_editor(self) -> None:
        current = (self.settings.editor_command or "").strip()
        text, ok = QInputDialog.getText(
            self,
            "Редактор",
            "Команда редактора (пример: code -g или путь до exe):",
            text=current
        )
        if ok:
            self.settings.editor_command = (text or "").strip()
            self._save_settings()

    def _choose_scripts_folder(self) -> None:
        start = self.folder_field.text().strip() or str(app_folder())
        path = QFileDialog.getExistingDirectory(self, "Выберите папку со скриптами", start)
        if path:
            self.folder_field.setText(path)
            self._refresh_script_list()

    def _pick_workdir(self) -> None:
        start = self.workdir_field.text().strip() or str(app_folder())
        path = QFileDialog.getExistingDirectory(self, "Выберите рабочую папку", start)
        if path:
            self.workdir_field.setText(path)
            self.settings.last_workdir = path
            script = self._current_script_path()
            if script:
                self.settings.per_script_workdir = self.settings.per_script_workdir or {}
                self.settings.per_script_workdir[script] = path
            self._save_settings()
            self._update_script_preview()

    def _pick_script_file(self) -> None:
        start = self.folder_field.text().strip() or str(app_folder())
        path, _ = QFileDialog.getOpenFileName(self, "Выберите .py", start, "Python (*.py);;Все файлы (*)")
        if path:
            self._set_current_script(path)
            self.statusBar().showMessage(f"Выбран: {os.path.basename(path)}", 2500)
            self._highlight_script_in_list(path)

    def _refresh_script_list(self, save: bool = True) -> None:
        root = Path(self.folder_field.text().strip() or app_folder())
        recursive = self.scan_checkbox.isChecked()
        self.all_scripts = list_python_files(root, recursive)

        self.all_scripts.sort(key=lambda p: (str(p.parent).lower(), p.name.lower(), str(p).lower()))

        self._apply_filters()
        if save:
            self._save_settings()

    def _apply_filters(self) -> None:
        q = (self.search_field.text() or "").strip().lower()
        fav_only = self.fav_only_checkbox.isChecked()

        favorites = set(self.settings.favorites or [])
        autostart = set(self.settings.autostart_scripts or [])
        current = (self._current_script_path() or "").strip()

        self.scripts_list.blockSignals(True)
        try:
            self.scripts_list.clear()
            root = Path(self.folder_field.text().strip() or app_folder()).resolve()

            for p in self.all_scripts:
                sp = str(p)

                if fav_only and sp not in favorites:
                    continue

                try:
                    rel_parent = p.resolve().parent.relative_to(root)
                    rel_parent_s = str(rel_parent).replace("\\", "/")
                    if rel_parent_s == ".":
                        rel_parent_s = ""
                except Exception:
                    rel_parent_s = ""

                hay = (p.name + " " + sp + " " + rel_parent_s).lower()
                if q and q not in hay:
                    continue

                has_custom_icon = bool((self.settings.per_script_icon or {}).get(sp, "").strip())

                icons: list[str] = []
                if sp in favorites:
                    icons.append("⭐")
                if sp in autostart:
                    icons.append("🚀")
                if not icons:
                    icons.append("🖼️" if has_custom_icon else "📄")

                icon = "".join(icons)
                second_line = rel_parent_s if rel_parent_s else "(корень)"
                title = f"{icon} {p.name}\n{second_line}"

                item = QListWidgetItem(title)
                item.setData(Qt.UserRole, sp)
                item.setToolTip(sp)
                self.scripts_list.addItem(item)

        except Exception as e:
            try:
                self._append_error(f"! Ошибка в _apply_filters: {type(e).__name__}: {e}")
            except Exception:
                pass
        finally:
            self.scripts_list.blockSignals(False)

        if current:
            self._highlight_script_in_list(current)

        QTimer.singleShot(300, self._save_settings)


    def _highlight_script_in_list(self, script_path: str) -> None:
        script_path = (script_path or "").strip()
        if not script_path:
            return
        for i in range(self.scripts_list.count()):
            it = self.scripts_list.item(i)
            if it and it.data(Qt.UserRole) == script_path:
                self.scripts_list.setCurrentItem(it)
                return

    def _on_script_selected(self, current: QListWidgetItem, _prev: QListWidgetItem) -> None:
        if not current:
            return
        path = (current.data(Qt.UserRole) or "").strip()
        if path:
            self._set_current_script(path)
            self.statusBar().showMessage(f"Выбран: {os.path.basename(path)}", 2500)

    def _set_current_script(self, path: str) -> None:
        self.settings.last_script_path = path
        self._apply_per_script_workdir(path)
        self._apply_per_script_args(path)
        self._update_star_button()
        self._update_script_preview()
        QTimer.singleShot(0, self._save_settings)

    def _apply_per_script_workdir(self, script_path: str) -> None:
        script_path = (script_path or "").strip()
        self.settings.per_script_workdir = self.settings.per_script_workdir or {}
        if not script_path:
            return
        wd = (self.settings.per_script_workdir.get(script_path, "") or "").strip()
        if wd:
            self.workdir_field.setText(wd)
        else:
            self.workdir_field.setText((self.settings.last_workdir or "").strip())

    def _apply_per_script_args(self, script_path: str) -> None:
        script_path = (script_path or "").strip()
        self.settings.per_script_args = self.settings.per_script_args or {}
        if not script_path:
            return
        a = (self.settings.per_script_args.get(script_path, "") or "").strip()
        if a:
            self.args_field.setText(a)
        else:
            self.args_field.setText((self.settings.last_arguments or "").strip())

    def _remember_args(self) -> None:
        s = (self._current_script_path() or "").strip()
        if not s:
            return
        self.settings.per_script_args = self.settings.per_script_args or {}
        self.settings.per_script_args[s] = self.args_field.text()
        QTimer.singleShot(400, self._save_settings)

    def _toggle_favorite(self) -> None:
        s = (self._current_script_path() or "").strip()
        if not s:
            return
        fav = list(self.settings.favorites or [])  # ✅ Явно копируем
        if s in fav:
            fav.remove(s)
        else:
            fav.append(s)
        self.settings.favorites = fav
        self._apply_filters()
        self._update_star_button()
        self._save_settings()

    def _toggle_autostart_for_script(self, script: str) -> None:
        script = (script or "").strip()
        if not script:
            return
        cur = list(self.settings.autostart_scripts or [])
        if script in cur:
            cur.remove(script)
            self.statusBar().showMessage("Убрано из автозапуска", 2500)
        else:
            cur.append(script)
            self.statusBar().showMessage("Добавлено в автозапуск", 2500)
        self.settings.autostart_scripts = cur

    def _args_for_script(self, script: str) -> list[str]:
        script = (script or "").strip()
        raw = ""
        if script:
            raw = (self.settings.per_script_args or {}).get(script, "") or ""
        if not raw:
            raw = self.settings.last_arguments or ""
        return split_command_line(raw)

    def _workdir_for_script(self, script: str) -> str:
        script = (script or "").strip()
        wd = ""
        if script:
            wd = (self.settings.per_script_workdir or {}).get(script, "") or ""
        if not wd:
            wd = (self.settings.last_workdir or "").strip()
        if not wd and script:
            wd = str(Path(script).resolve().parent)
        return wd

    def _start_script_direct(self, script: str, *, clear_output: bool) -> None:
        script = (script or "").strip()
        if not script:
            return
        if not Path(script).exists():
            self._append_error(f"! Autostart: файл не найден: {script}")
            return

        py = (self.python_field.text() or "").strip()
        if not py:
            self._append_error("! Autostart: не указан интерпретатор Python.")
            return

        if self._is_same_script_running(script):
            self._append_output(f"> Autostart: пропуск, уже запущен: {Path(script).name}")
            return

        args = self._args_for_script(script)
        workdir = self._workdir_for_script(script)

        if workdir and (not Path(workdir).exists() or not Path(workdir).is_dir()):
            self._append_error(f"! Autostart: некорректная рабочая папка: {workdir}")
            workdir = str(Path(script).resolve().parent)

        if clear_output:
            self._clear_output_texts()

        self._append_output(f"\n=== AUTOSTART: {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
        self._append_output(f"> Python: {py}")
        self._append_output(f"> Script: {script}")
        self._append_output(f"> Args: {args if args else '—'}")
        self._append_output(f"> Workdir: {workdir if workdir else '—'}")
        self._append_output("")

        self.proc_counter += 1
        rid = self.proc_counter

        p = QProcess(self)
        p.setProcessChannelMode(QProcess.SeparateChannels)
        p.setInputChannelMode(QProcess.ManagedInputChannel)
        if workdir:
            p.setWorkingDirectory(workdir)

        p.readyReadStandardOutput.connect(partial(self._on_stdout, rid))
        p.readyReadStandardError.connect(partial(self._on_stderr, rid))
        p.finished.connect(partial(self._on_finished, rid))
        p.errorOccurred.connect(partial(self._on_error, rid))

        env = QProcessEnvironment.systemEnvironment()
        env.insert("LAUNCHER_ROOT", str(app_folder()))
        extra_env = self._parse_env_editor()
        for k, v in extra_env.items():
            env.insert(k, v)
        p.setProcessEnvironment(env)

        self.processes[rid] = p
        self.proc_start_time[rid] = time.time()
        self.proc_info[rid] = {"script": script, "py": py, "args": args, "workdir": workdir}

        item = QListWidgetItem(Path(script).name)
        item.setData(Qt.UserRole, rid)
        item.setToolTip(script)
        self.running_list.insertItem(0, item)
        self.running_list.setCurrentItem(item)
        self._renumber_running_items()

        p.start(py, ["-u", script] + list(args))
        if not p.waitForStarted(3000):
            err = p.errorString()
            self._append_error(f"! Autostart: не удалось запустить {Path(script).name}. QProcess: {err}")
            self._remove_run_item(rid)
            return

        try:
            pid = int(p.processId())
        except Exception:
            pid = 0
        self._update_run_item_title(rid, pid)
        self._update_stop_enabled()

    def _run_autostart_scripts(self) -> None:
        scripts = [s for s in (self.settings.autostart_scripts or []) if (s or "").strip()]
        if not scripts:
            return

        uniq: list[str] = []
        seen: set[str] = set()
        for s in scripts:
            s2 = s.strip()
            if s2 not in seen:
                seen.add(s2)
                uniq.append(s2)

        self._append_output(f"\n>>> Autostart queue: {len(uniq)} script(s)")

        def step(i: int) -> None:
            if i >= len(uniq):
                self._append_output(">>> Autostart done\n")
                return
            self._start_script_direct(uniq[i], clear_output=False)
            QTimer.singleShot(350, lambda: step(i + 1))

        QTimer.singleShot(350, lambda: step(0))

    def _update_star_button(self) -> None:
        s = (self._current_script_path() or "").strip()
        fav = set(self.settings.favorites or [])
        self.star_button.setText("★" if s and s in fav else "☆")

    def _running_context_menu(self, pos) -> None:
        it = self.running_list.itemAt(pos)
        if not it:
            return
        rid = it.data(Qt.UserRole)
        if not isinstance(rid, int):
            return

        menu = QMenu(self)
        a_stop = menu.addAction("Остановить")
        a_copy_cmd = menu.addAction("Копировать команду")
        a_open_wd = menu.addAction("Открыть рабочую папку")

        act = menu.exec(self.running_list.mapToGlobal(pos))
        if act == a_stop:
            self.stop_script()
            return

        info = self.proc_info.get(rid, {}) if rid in self.proc_info else {}
        if act == a_copy_cmd:
            py = (info.get("py") or "").strip()
            script = (info.get("script") or "").strip()
            args = info.get("args") or []
            cmd = [py, "-u", script] + list(args)
            QApplication.clipboard().setText(
                subprocess.list2cmdline(cmd)
                if running_on_windows()
                else " ".join(shlex.quote(x) for x in cmd)
            )
            return

        if act == a_open_wd:
            wd = (info.get("workdir") or "").strip()
            if wd and Path(wd).exists():
                safe_open(Path(wd))
            return
        
    def _scripts_context_menu(self, pos) -> None:
        it = self.scripts_list.itemAt(pos)
        if not it:
            return
        script = (it.data(Qt.UserRole) or "").strip()
        if not script:
            return

        menu = QMenu(self)

        a_run = menu.addAction("Запустить")
        a_copy_path = menu.addAction("Копировать путь")
        a_open_folder = menu.addAction("Открыть папку")
        menu.addSeparator()

        a_open_in_editor = menu.addAction("Открыть в редакторе")
        menu.addSeparator()

        a_toggle_fav = menu.addAction("В избранное / убрать из избранного")
        a_toggle_autostart = menu.addAction("В автозапуск / убрать из автозапуска")
        menu.addSeparator()

        a_make_shortcut = menu.addAction("Создать/обновить ярлык")
        a_open_shortcut = menu.addAction("Открыть ярлык")
        menu.addSeparator()

        a_pick_icon = menu.addAction("Выбрать иконку...")
        a_clear_icon = menu.addAction("Сбросить иконку")

        act = menu.exec(self.scripts_list.mapToGlobal(pos))

        if act == a_run:
            self._set_current_script(script)
            self.run_script()
            return

        if act == a_toggle_autostart:
            self._toggle_autostart_for_script(script)
            self._apply_filters()
            self._save_settings()
            return

        if act == a_copy_path:
            QApplication.clipboard().setText(script)
            self.statusBar().showMessage("Путь скопирован", 2000)
            return

        if act == a_open_folder:
            p = Path(script)
            if p.exists():
                safe_open(p.parent)
            return

        if act == a_open_in_editor:
            p = Path(script)
            if p.exists():
                ok, msg = self._open_in_editor(p)
                if not ok:
                    QMessageBox.information(self, "Редактор", msg)
            return

        if act == a_toggle_fav:
            self._set_current_script(script)
            self._toggle_favorite()
            return

        if act == a_make_shortcut:
            self._set_current_script(script)
            self._create_or_update_shortcut_for_current()
            return

        if act == a_open_shortcut:
            self._set_current_script(script)
            self._open_shortcut_for_current()
            return

        if act == a_pick_icon:
            self._set_current_script(script)
            self._pick_icon_for_current_script()
            return

        if act == a_clear_icon:
            self._set_current_script(script)
            self._clear_icon_for_current_script()
            return
        
    def _pick_icon_for_current_script(self) -> None:
        script = (self._current_script_path() or "").strip()
        if not script:
            QMessageBox.information(self, "Иконка", "Скрипт не выбран.")
            return

        self.settings.per_script_icon = self.settings.per_script_icon or {}
        current = (self.settings.per_script_icon.get(script, "") or "").strip()

        start_dir = ""
        if current and Path(current).exists():
            start_dir = str(Path(current).parent)
        else:
            start_dir = str(Path(script).resolve().parent)

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите иконку для скрипта",
            start_dir,
            "Иконки (*.ico *.exe *.dll);;Все файлы (*)"
        )
        if not path:
            return

        p = Path(path)
        if not p.exists():
            QMessageBox.warning(self, "Иконка", f"Файл не найден: {path}")
            return

        self.settings.per_script_icon[script] = str(p)
        self._save_settings()
        self.statusBar().showMessage(f"Иконка сохранена: {p}", 4000)

    def _clear_icon_for_current_script(self) -> None:
        script = (self._current_script_path() or "").strip()
        if not script:
            QMessageBox.information(self, "Иконка", "Скрипт не выбран.")
            return
        m = self.settings.per_script_icon or {}
        if script in m:
            m.pop(script, None)
            self.settings.per_script_icon = m
            self._save_settings()
            self.statusBar().showMessage("Иконка для скрипта сброшена", 3000)
        else:
            self.statusBar().showMessage("Иконка для скрипта не задана", 2500)

    def _icon_for_script(self, script: str) -> Optional[str]:
        script = (script or "").strip()
        if not script:
            return None
        raw = ((self.settings.per_script_icon or {}).get(script, "") or "").strip()
        if raw:
            p = Path(raw)
            if p.exists():
                return str(p)
        return None


    def _current_script_path(self) -> str:
        return (self.settings.last_script_path or "").strip()

    def _update_script_preview(self) -> None:
        script = self._current_script_path()
        if not script:
            self._set_status_no_script()
            return
        p = Path(script)
        exists = p.exists()
        size = "—"
        if exists:
            try:
                size = f"{p.stat().st_size} байт"
            except Exception:
                size = "—"
        info = f"Файл: {p.name}\nПуть: {p}\nСтатус: {'найден' if exists else 'НЕ НАЙДЕН'}\nРазмер: {size}"
        self.script_info_label.setText(info)
        self.statusBar().showMessage("", 1)
        self._update_star_button()
        self.preview_button.setEnabled(True)
        self.run_button.setEnabled(True)
        self.action_run.setEnabled(True)
        self._update_stop_enabled()

    def _set_status_no_script(self) -> None:
        self.preview_button.setEnabled(False)
        self.run_button.setEnabled(True)
        self.action_run.setEnabled(True)
        self._update_stop_enabled()

    def _copy_preview(self) -> None:
        cmd = self._build_command_string()
        QApplication.clipboard().setText(cmd)
        self.statusBar().showMessage("Команда скопирована в буфер обмена", 3000)

    def _build_command_string(self) -> str:
        py = (self.python_field.text() or "").strip()
        script = (self._current_script_path() or "").strip()
        args = split_command_line(self.args_field.text())
        parts = [py, script] + args
        parts = [p for p in parts if p]

        if running_on_windows():
            return subprocess.list2cmdline(parts)

        return " ".join(shlex.quote(p) for p in parts)

    def _validate_before_run(self) -> tuple[bool, str]:
        py = (self.python_field.text() or "").strip()
        script = (self._current_script_path() or "").strip()
        if not script:
            return False, "Не выбран скрипт для запуска."
        if not Path(script).exists():
            return False, f"Скрипт не найден: {script}"
        if not py:
            return False, "Не указан интерпретатор Python."
        if py.lower() in ("python", "python.exe"):
            if not shutil.which(py):
                return False, f"Python не найден в PATH: {py}"
        else:
            if not Path(py).exists():
                return False, f"Интерпретатор Python не найден: {py}"

        workdir = (self.workdir_field.text() or "").strip()
        if workdir and not Path(workdir).exists():
            return False, f"Рабочая папка не найдена: {workdir}"
        if workdir and not Path(workdir).is_dir():
            return False, f"Рабочая папка не является директорией: {workdir}"

        return True, ""

    def _parse_env_editor(self) -> dict[str, str]:
        text = self.env_editor.toPlainText().strip()
        env: dict[str, str] = {}
        if not text:
            return env
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.lower().startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip()
            if not k:
                continue
            if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
                v = v[1:-1]
            env[k] = v
        return env


    def run_script(self) -> None:
        ok, msg = self._validate_before_run()
        if not ok:
            QMessageBox.warning(self, "Ошибка", msg)
            return
        py = (self.python_field.text() or "").strip()
        script = (self._current_script_path() or "").strip()
        if self._is_same_script_running(script):
            QMessageBox.information(self, "Запуск", "Этот скрипт уже запущен.")
            return
        args = split_command_line(self.args_field.text())
        workdir = (self.workdir_field.text() or "").strip()
        if not workdir:
            workdir = str(Path(script).resolve().parent)
        if self.clear_checkbox.isChecked():
            self._clear_output_texts()
        self._append_output(f"> {time.strftime('%Y-%m-%d %H:%M:%S')}")
        self._append_output(f"> Python: {py}")
        self._append_output(f"> Script: {script}")
        self._append_output(f"> Args: {args if args else '—'}")
        self._append_output(f"> Workdir: {workdir if workdir else '—'}")
        self._append_output("")
        self.proc_counter += 1
        rid = self.proc_counter

        p = QProcess(self)
        p.setProcessChannelMode(QProcess.SeparateChannels)
        p.setInputChannelMode(QProcess.ManagedInputChannel)
        if workdir:
            p.setWorkingDirectory(workdir)

        p.readyReadStandardOutput.connect(partial(self._on_stdout, rid))
        p.readyReadStandardError.connect(partial(self._on_stderr, rid))
        p.finished.connect(partial(self._on_finished, rid))
        p.errorOccurred.connect(partial(self._on_error, rid))

        env = QProcessEnvironment.systemEnvironment()
        env.insert("LAUNCHER_ROOT", str(app_folder()))
        extra_env = self._parse_env_editor()
        for k, v in extra_env.items():
            env.insert(k, v)
        p.setProcessEnvironment(env)

        self.processes[rid] = p
        self.proc_start_time[rid] = time.time()
        self.proc_info[rid] = {"script": script, "py": py, "args": args, "workdir": workdir}

        item = QListWidgetItem(Path(script).name)
        item.setData(Qt.UserRole, rid)
        item.setToolTip(script)

        self.running_list.insertItem(0, item)
        self.running_list.setCurrentItem(item)
        self._renumber_running_items()
        p.start(py, ["-u", script] + args)
        if not p.waitForStarted(3000):
            err = p.errorString()
            self._append_error(f"! Не удалось запустить процесс #{rid}. QProcess: {err}")
            self._remove_run_item(rid)
            QMessageBox.critical(self, "Ошибка", f"Не удалось запустить процесс #{rid}.\n\nПричина: {err}")
            return
        self.settings.per_script_workdir = self.settings.per_script_workdir or {}
        self.settings.per_script_workdir[script] = workdir
        self.settings.recent_runs = self.settings.recent_runs or []
        self.settings.recent_runs.insert(0, {
            "script": script,
            "args": self.args_field.text(),
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "workdir": workdir,
            "py": py,
        })
        self.settings.recent_runs = self.settings.recent_runs[:30]
        if not p.waitForStarted(3000):
            err = p.errorString()
            self._append_error(f"! Не удалось запустить процесс #{rid}. QProcess: {err}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось запустить процесс #{rid}.\n\nПричина: {err}")
            self._remove_run_item(rid)
            return
        try:
            pid = int(p.processId())
        except Exception:
            pid = 0
        self._update_run_item_title(rid, pid)
        self._update_stop_enabled()
        self.statusBar().showMessage("Процесс запущен", 3000)
        self._save_settings()
        self._refresh_recent_list()

    def _set_running_ui(self, running: bool) -> None:
        self.run_button.setEnabled(True)
        self.action_run.setEnabled(True)
        self._update_stop_enabled()

    def stop_script(self) -> None:
        ids = self._selected_run_ids()
        if not ids:
            QMessageBox.information(self, "Остановить", "Выбери один или несколько запущенных процессов в списке 'Запущенные процессы'.")
            return
        self._append_output("\n> Stop requested: " + ", ".join(f"#{i}" for i in ids))
        for rid in ids:
            p = self.processes.get(rid)
            if not p or p.state() == QProcess.NotRunning:
                continue
            try:
                p.write(b"\x03")
                p.waitForBytesWritten(200)
            except Exception:
                pass
            p.terminate()
        QTimer.singleShot(2600, lambda: self._kill_still_running(ids))
        self._update_stop_enabled()

    def _kill_still_running(self, ids: list[int]) -> None:
        for rid in ids:
            p = self.processes.get(rid)
            if not p or p.state() == QProcess.NotRunning:
                continue
            p.kill()

    def _shutdown_processes(self) -> None:
        for rid, p in list(self.processes.items()):
            if not p:
                continue
            try:
                p.readyReadStandardOutput.disconnect()
            except Exception:
                pass
            try:
                p.readyReadStandardError.disconnect()
            except Exception:
                pass
            try:
                p.finished.disconnect()
            except Exception:
                pass
            try:
                p.errorOccurred.disconnect()
            except Exception:
                pass
            try:
                if p.state() != QProcess.NotRunning:
                    p.terminate()
            except Exception:
                pass
            try:
                p.deleteLater()
            except Exception:
                pass

        self.processes.clear()
        self.proc_start_time.clear()
        self.proc_info.clear()


    def _on_stdout(self, rid: int) -> None:
        p = self.processes.get(rid)
        if not p:
            return
        data = bytes(p.readAllStandardOutput()).decode(errors="replace")
        if not data:
            return

        prefix = self._proc_prefix(rid)
        for line in data.splitlines():
            self._append_output(f"{prefix} {line}" if line else prefix)

    def _on_stderr(self, rid: int) -> None:
        p = self.processes.get(rid)
        if not p:
            return
        data = bytes(p.readAllStandardError()).decode(errors="replace")
        if not data:
            return

        prefix = self._proc_prefix(rid)
        for line in data.splitlines():
            self._append_error(f"{prefix} {line}" if line else prefix)

        try:
            if self.output_tabs.count() >= 2:
                self.output_tabs.setCurrentIndex(1)
        except Exception:
            pass

    def _on_finished(self, rid: int, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        status = "NormalExit" if exit_status == QProcess.NormalExit else "CrashExit"
        dur = ""
        t0 = self.proc_start_time.get(rid)
        if t0 is not None:
            try:
                dur = f", duration={time.time() - t0:.2f}s"
            except Exception:
                dur = ""
        dn = self._display_no_for_rid(rid)
        self._append_output(f"\n[#{dn}] Finished: exit_code={exit_code}, status={status}{dur}")
        self.statusBar().showMessage(f"Завершено #{dn}: {status}, code={exit_code}", 5000)
        self._remove_run_item(rid)

    def _on_error(self, rid: int, err: QProcess.ProcessError) -> None:
        dn = self._display_no_for_rid(rid)

        p = self.processes.get(rid)
        s = ""
        if p and p.state() != QProcess.NotRunning:
            try:
                s = p.errorString()
            except RuntimeError:
                s = ""

        self._append_error(f"\n[#{dn}] ProcessError: {err} {(':: ' + s) if s else ''}")

        try:
            self.statusBar().showMessage(f"Ошибка процесса #{dn}: {err}", 5000)
        except Exception:
            pass

        if err in (QProcess.FailedToStart, QProcess.Crashed):
            self._remove_run_item(rid)
            self._renumber_running_items()

    def _append_output(self, text: str) -> None:
        if not text:
            return
        try:
            self.output_text.appendPlainText(text.rstrip("\n"))
        except RuntimeError:
            return
        if self.output_text.blockCount() > MAX_LOG_LINES:
            c = self.output_text.textCursor()
            c.movePosition(c.Start)
            c.movePosition(c.Down, c.KeepAnchor, self.output_text.blockCount() - MAX_LOG_LINES)
            c.removeSelectedText()
            c.deleteChar()
        if self.autoscroll_checkbox.isChecked():
            self._scroll_to_bottom(self.output_text)

    def _scroll_to_bottom(self, text_edit: QPlainTextEdit) -> None:
        try:
            scrollbar = text_edit.verticalScrollBar()
            if scrollbar:
                scrollbar.setValue(scrollbar.maximum())
        except Exception:
            pass

    def _ensure_list_min_rows(self, lw: QListWidget, min_rows: int) -> None:
        if min_rows <= 0:
            return

        try:
            row_h = lw.sizeHintForRow(0)
        except Exception:
            row_h = -1

        if row_h is None or row_h <= 0:
            try:
                row_h = lw.fontMetrics().height() + 10
            except Exception:
                row_h = 24

        try:
            frame = lw.frameWidth() * 2
        except Exception:
            frame = 0

        try:
            margins = lw.contentsMargins()
            extra = margins.top() + margins.bottom()
        except Exception:
            extra = 0

        lw.setMinimumHeight(frame + extra + row_h * min_rows)

    def _append_error(self, text: str) -> None:
        if not text:
            return
        has_err_tab = False
        try:
            has_err_tab = self.output_tabs.count() >= 2
        except Exception:
            has_err_tab = False

        if has_err_tab and self.error_text:
            try:
                self.error_text.appendPlainText(text.rstrip("\n"))
            except RuntimeError:
                return
            if self.autoscroll_checkbox.isChecked():
                self._scroll_to_bottom(self.error_text)
        else:
            try:
                self.output_text.appendPlainText(("STDERR: " + text).rstrip("\n"))
            except RuntimeError:
                return
            if self.autoscroll_checkbox.isChecked():
                self._scroll_to_bottom(self.output_text)

    def _clear_output_texts(self) -> None:
        self.output_text.clear()
        self.error_text.clear()

    def _clear_output_clicked(self) -> None:
        self._clear_output_texts()
        self.statusBar().showMessage("Вывод очищен", 2000)

    def _save_settings(self) -> None:
        self.settings.python_executable = (self.python_field.text() or "").strip()
        self.settings.scripts_folder = (self.folder_field.text() or "").strip()
        self.settings.last_script_path = (self.settings.last_script_path or "").strip()
        self.settings.last_arguments = self.args_field.text()
        self.settings.last_workdir = (self.workdir_field.text() or "").strip()
        self.settings.scan_subfolders = self.scan_checkbox.isChecked()
        self.settings.clear_output_on_start = self.clear_checkbox.isChecked()
        self.settings.autoscroll_output = self.autoscroll_checkbox.isChecked()
        self.settings.env_text = self.env_editor.toPlainText()
        try:
            self.settings.save(config_file())
        except Exception:
            pass

    def _open_config_file(self) -> None:
        p = config_file()
        if not p.exists():
            try:
                self._save_settings()
            except Exception:
                pass
        safe_open(p)

    def _save_log(self) -> None:
        default_name = f"launcher_log_{time_stamp()}.txt"
        start_dir = str(app_folder())
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить лог", str(Path(start_dir) / default_name), "Text (*.txt)")
        if not path:
            return
        try:
            text = self.output_text.toPlainText()
            text += "\n\n----- STDERR -----\n" + self.error_text.toPlainText()
            Path(path).write_text(text, encoding="utf-8")
            self.statusBar().showMessage(f"Лог сохранён: {path}", 5000)
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить лог: {e}")

    def _open_scripts_folder(self) -> None:
        p = Path((self.settings.last_script_path or "").strip())
        if p.exists():
            safe_open(p.parent)

    def _open_current_script(self) -> None:
        script = (self._current_script_path() or "").strip()
        if not script:
            QMessageBox.information(self, "Открыть", "Скрипт не выбран.")
            return
        p = Path(script)
        if not p.exists():
            QMessageBox.warning(self, "Открыть", f"Файл не найден: {script}")
            return
        safe_open(p)

    def _open_current_script_in_editor(self) -> None:
        script = (self._current_script_path() or "").strip()
        if not script:
            QMessageBox.information(self, "Редактор", "Скрипт не выбран.")
            return
        p = Path(script)
        if not p.exists():
            QMessageBox.warning(self, "Редактор", f"Файл не найден: {script}")
            return
        ok, msg = self._open_in_editor(p)
        if not ok:
            QMessageBox.information(self, "Редактор", msg)

    def _open_in_editor(self, path: Path) -> tuple[bool, str]:
        cmd = self._detect_editor_command()

        if cmd:
            try:
                argv = self._editor_argv_for_command(cmd)
                argv.append(str(path))
                subprocess.Popen(argv)
                return True, ""
            except Exception as e:
                opened = safe_open(path)
                if opened:
                    return False, f"Не удалось открыть в редакторе: {e}\nФайл открыт приложением по умолчанию."
                return False, f"Не удалось открыть в редакторе: {e}\nИ системное открытие тоже не сработало."

        opened = safe_open(path)
        if opened:
            return True, "Редактор не найден; файл открыт системным приложением по умолчанию."
        return False, "Редактор не найден и системное открытие не сработало."

    def _editor_argv_for_command(self, cmd: object) -> list[str]:
        if isinstance(cmd, str):
            tokens = split_command_line(cmd)
        else:
            tokens = [str(x) for x in list(cmd)]

        tokens = [t for t in tokens if (t or "").strip()]
        if not tokens:
            raise FileNotFoundError("Пустая команда редактора")

        exe = self._resolve_editor_exe(tokens)
        if exe is None:
            raise FileNotFoundError(f"Редактор не найден: {tokens[0]!r}")

        return [str(exe)] + tokens[1:]


    def _resolve_editor_exe(self, tokens: list[str]) -> Optional[Path]:
        first = tokens[0].strip().strip('"')

        p = Path(first)

        if ("\\" in first) or ("/" in first) or (p.suffix.lower() == ".exe"):
            if p.is_file():
                return p.resolve()

            if running_on_windows():
                acc = first
                for i in range(1, len(tokens)):
                    acc = acc + " " + tokens[i]
                    candidate = Path(acc.strip().strip('"'))
                    if candidate.is_file():
                        tokens[:] = [str(candidate)] + tokens[i + 1 :]
                        return candidate.resolve()

            return None

        found = shutil.which(first)
        return Path(found).resolve() if found else None
        
    def _default_shortcut_dir(self) -> Path:
        home = Path.home()
        desktop = home / "Desktop"
        if desktop.exists() and desktop.is_dir():
            return desktop
        return app_folder()

    def _powershell_escape_single_quotes(self, s: str) -> str:
        return (s or "").replace("'", "''")

    def _resolved_python_for_shortcut(self) -> str:
        py = (self.python_field.text() or "").strip()
        if not py:
            return "python.exe" if running_on_windows() else "python"
        if py.lower() in ("python", "python.exe"):
            found = shutil.which(py)
            return found or py
        return py

    def _shortcut_target_and_args(self, script: str) -> tuple[str, str, str]:
        py = self._resolved_python_for_shortcut()
        args = split_command_line(self.args_field.text())
        script_path = str(Path(script).resolve())
        argv = ["-u", script_path] + args
        args_str = subprocess.list2cmdline(argv) if running_on_windows() else " ".join(shlex.quote(x) for x in argv)
        workdir = (self.workdir_field.text() or "").strip()
        if not workdir:
            workdir = str(Path(script_path).parent)
        return py, args_str, workdir

    def _pick_shortcut_path(self, script: str) -> Optional[Path]:
        script_p = Path(script)
        default_dir = self._default_shortcut_dir()
        default_name = f"{script_p.stem}.lnk"
        suggested = default_dir / default_name

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить ярлык",
            str(suggested),
            "Ярлык Windows (*.lnk)"
        )
        if not path:
            return None
        p = Path(path)
        if p.suffix.lower() != ".lnk":
            p = p.with_suffix(".lnk")
        return p

    def _create_windows_shortcut(self, shortcut_path: Path, target: str, arguments: str, workdir: str, icon_path: Optional[str]) -> tuple[bool, str]:
        if not running_on_windows():
            return False, "Ярлыки .lnk поддерживаются только на Windows."

        sp = self._powershell_escape_single_quotes(str(shortcut_path))
        tp = self._powershell_escape_single_quotes(target)
        ap = self._powershell_escape_single_quotes(arguments)
        wd = self._powershell_escape_single_quotes(workdir)
        ico = self._powershell_escape_single_quotes(icon_path or "")

        ps_lines = [
            "$WshShell = New-Object -ComObject WScript.Shell",
            f"$Shortcut = $WshShell.CreateShortcut('{sp}')",
            f"$Shortcut.TargetPath = '{tp}'",
            f"$Shortcut.Arguments = '{ap}'",
            f"$Shortcut.WorkingDirectory = '{wd}'",
        ]
        if ico:
            ps_lines.append(f"$Shortcut.IconLocation = '{ico}'")
        ps_lines.append("$Shortcut.Save()")
        ps = "; ".join(ps_lines)

        try:
            p = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                capture_output=True,
                text=True
            )
            out = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
            if p.returncode != 0:
                return False, out or f"powershell rc={p.returncode}"
            return True, ""
        except Exception as e:
            return False, str(e)

    def _create_or_update_shortcut_for_current(self) -> None:
        script = (self._current_script_path() or "").strip()
        if not script:
            QMessageBox.information(self, "Ярлык", "Скрипт не выбран.")
            return
        if not Path(script).exists():
            QMessageBox.warning(self, "Ярлык", f"Файл не найден: {script}")
            return
        if not running_on_windows():
            QMessageBox.information(self, "Ярлык", "Создание .lnk поддерживается только на Windows.")
            return

        self.settings.per_script_shortcut = self.settings.per_script_shortcut or {}
        saved = (self.settings.per_script_shortcut.get(script, "") or "").strip()

        shortcut_path: Optional[Path] = None
        if saved:
            sp = Path(saved)
            if sp.parent.exists():
                shortcut_path = sp

        if shortcut_path is None:
            shortcut_path = self._pick_shortcut_path(script)
            if shortcut_path is None:
                return

        target, arguments, workdir = self._shortcut_target_and_args(script)
        icon = self._icon_for_script(script) or find_python_icon()
        ok, err = self._create_windows_shortcut(shortcut_path, target, arguments, workdir, icon)

        if not ok:
            QMessageBox.warning(self, "Ярлык", f"Не удалось создать ярлык:\n\n{err}")
            return

        self.settings.per_script_shortcut[script] = str(shortcut_path)
        self._save_settings()
        self.statusBar().showMessage(f"Ярлык сохранён: {shortcut_path}", 5000)

    def _open_shortcut_for_current(self) -> None:
        script = (self._current_script_path() or "").strip()
        if not script:
            QMessageBox.information(self, "Ярлык", "Скрипт не выбран.")
            return
        p = Path((self.settings.per_script_shortcut or {}).get(script, "") or "")
        if not p.exists():
            QMessageBox.information(self, "Ярлык", "Для этого скрипта ярлык не задан или файл ярлыка не найден.")
            return
        safe_open(p)

    def _detect_editor_command(self) -> Optional[object]:
        cfg = (self.settings.editor_command or "").strip()
        if cfg:
            return cfg
        env_editor = (os.environ.get("LAUNCHER_EDITOR") or os.environ.get("EDITOR") or "").strip()
        if env_editor:
            return env_editor
        if shutil.which("code"):
            return ["code", "-g"]
        if running_on_windows():
            return ["notepad"]
        return None

    def _check_requirements_for_current_script(self) -> None:
        script = (self._current_script_path() or "").strip()
        if not script:
            QMessageBox.information(self, "Требования", "Скрипт не выбран.")
            return
        p = Path(script)
        if not p.exists():
            QMessageBox.warning(self, "Требования", f"Файл не найден: {script}")
            return
        py = (self.python_field.text() or "").strip()
        if py.lower() not in ("python", "python.exe") and py and not Path(py).exists():
            QMessageBox.warning(self, "Требования", "Интерпретатор Python не найден. Укажи корректный путь.")
            return

        try:
            imports, rel_imports = self._extract_imports(p)
        except Exception as e:
            QMessageBox.warning(self, "Требования", f"Не удалось проанализировать импорты: {e}")
            return

        if not imports and not rel_imports:
            QMessageBox.information(self, "Требования", "Импорты не найдены (или файл пустой).")
            return

        self._append_output("\n=== Проверка требований (импорты) ===")
        self._append_output(f"Script: {p}")
        self._append_output(f"Python: {py}")

        if rel_imports:
            self._append_output("\n[Относительные импорты] (проверка пропущена — зависит от пакета/working dir)")
            for x in sorted(rel_imports):
                self._append_output(f"  - {x}")
        missing: list[str] = []
        ok_list: list[str] = []
        self._append_output("\n[Проверка импортов через выбранный Python]")
        for mod in sorted(imports):
            rc, out = self._run_python_import_check(py, mod)
            if rc == 0:
                ok_list.append(mod)
                self._append_output(f"  OK  - {mod}")
            else:
                missing.append(mod)
                self._append_output(f"  FAIL- {mod} :: {out or 'ImportError'}")

        self._append_output("\nИтог:")
        self._append_output(f"  OK: {len(ok_list)}")
        self._append_output(f"  FAIL: {len(missing)}")
        if missing:
            self._append_output("\nПодсказка:")
            self._append_output(f"  {py} -m pip install " + " ".join(missing))
            self._append_output("\nПохоже, отсутствуют:")
            for m in missing:
                self._append_output(f"  - {m}")
        self._append_output("=== конец проверки требований ===\n")

        if missing:
            pip_packages = []
            for m in missing:
                pkg = self._module_to_pip_package(m)
                if pkg and pkg not in pip_packages:
                    pip_packages.append(pkg)

            self._append_output("\nПредложение установки:")
            self._append_output(f"  {py} -m pip install " + " ".join(pip_packages))

            msg = (
                "Обнаружены отсутствующие импорты.\n\n"
                "Установить зависимости через pip выбранным интерпретатором?\n\n"
                f"Python: {py}\n\n"
                "Будет выполнено:\n"
                f"{py} -m pip install " + " ".join(pip_packages)
            )
            ans = QMessageBox.question(self, "Требования", msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if ans != QMessageBox.Yes:
                QMessageBox.information(
                    self,
                    "Требования",
                    "Установка отменена. Детали см. во вкладке 'Вывод'."
                )
                return

            ok_pip, pip_info = self._pip_is_available(py)
            if not ok_pip:
                self._append_error("\nPIP недоступен для выбранного Python.")
                self._append_error(pip_info or "—")
                QMessageBox.warning(
                    self,
                    "Требования",
                    "Не удалось запустить pip для выбранного Python.\n\n"
                    "Проверьте, что pip установлен (python -m ensurepip), либо используйте другой интерпретатор.\n"
                    "Детали см. во вкладке 'Ошибки/Вывод'."
                )
                return

            self._append_output("\n=== Установка зависимостей (pip) ===")
            self._append_output(pip_info or "pip --version: —")
            rc, out = self._pip_install(py, pip_packages)
            self._append_output(f"\n[pip install] rc={rc}")
            self._append_output(out or "—")
            self._append_output("=== конец установки ===\n")

            still_missing: list[str] = []
            self._append_output("\n[Повторная проверка импортов]")
            for mod in sorted(imports):
                rc2, out2 = self._run_python_import_check(py, mod)
                if rc2 == 0:
                    self._append_output(f"  OK  - {mod}")
                else:
                    still_missing.append(mod)
                    self._append_output(f"  FAIL- {mod} :: {out2 or 'ImportError'}")

            if still_missing:
                QMessageBox.warning(
                    self,
                    "Требования",
                    "Часть импортов всё ещё не импортируется после установки.\n"
                    "См. вкладку 'Вывод' для деталей."
                )
            else:
                QMessageBox.information(
                    self,
                    "Требования",
                    "Зависимости установлены. Все найденные импорты успешно импортируются выбранным Python."
                )
        else:
            QMessageBox.information(
                self,
                "Требования",
                "Все найденные импорты успешно импортируются выбранным Python."
            )

    def _extract_imports(self, script_path: Path) -> tuple[set[str], set[str]]:
        src = script_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(script_path))
        imports: set[str] = set()
        rel: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    name = (a.name or "").strip()
                    if not name:
                        continue
                    imports.add(name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if getattr(node, "level", 0) and node.level > 0:
                    mod = node.module or ""
                    rel.add("." * node.level + mod)
                    continue
                mod = (node.module or "").strip()
                if mod:
                    imports.add(mod.split(".")[0])
        try:
            imports.discard(script_path.stem)
        except Exception:
            pass
        std = self._stdlib_names()
        imports = {m for m in imports if m and m not in std}
        return imports, rel

    def _run_python_import_check(self, python_exe: str, module: str) -> tuple[int, str]:
        code = (
            "import importlib,sys; "
            "m=sys.argv[1]; "
            "importlib.import_module(m); "
            "print('OK')"
        )
        try:
            p = subprocess.run([python_exe, "-c", code, module], capture_output=True, text=True)
            out = ((p.stdout or "") + (p.stderr or "")).strip()
            return p.returncode, out
        except Exception as e:
            return 999, str(e)
        
    def _module_to_pip_package(self, module: str) -> str:
        module = (module or "").strip()
        if not module:
            return module

        known = {
            "PIL": "Pillow",
            "cv2": "opencv-python",
            "sklearn": "scikit-learn",
            "bs4": "beautifulsoup4",
            "yaml": "PyYAML",
            "Crypto": "pycryptodome",
            "lxml": "lxml",
            "numpy": "numpy",
            "pandas": "pandas",
            "requests": "requests",
            "flask": "Flask",
            "django": "Django",
            "PySide6": "PySide6",
            "PyQt6": "PyQt6",
        }
        return known.get(module, module)

    def _pip_is_available(self, python_exe: str) -> tuple[bool, str]:
        try:
            p = subprocess.run([python_exe, "-m", "pip", "--version"], capture_output=True, text=True)
            out = ((p.stdout or "") + (p.stderr or "")).strip()
            return p.returncode == 0, out
        except Exception as e:
            return False, str(e)

    def _pip_install(self, python_exe: str, packages: list[str]) -> tuple[int, str]:
        pkgs = [p for p in (packages or []) if (p or "").strip()]
        if not pkgs:
            return 0, "Nothing to install"
        try:
            argv = [python_exe, "-m", "pip", "install"] + pkgs
            p = subprocess.run(argv, capture_output=True, text=True)
            out = ((p.stdout or "") + (p.stderr or "")).strip()
            return p.returncode, out
        except Exception as e:
            return 999, str(e)

    def _save_autoscroll(self) -> None:
        self.settings.autoscroll_output = self.autoscroll_checkbox.isChecked()
        self._save_settings()

    def _restore_previous(self) -> None:
        last = (self.settings.last_script_path or "").strip()
        if last:
            self._set_current_script(last)
            self._highlight_script_in_list(last)
        self._refresh_recent_list()

    def _run_system_checks(self) -> None:
        py = (self.python_field.text() or "").strip()
        script = (self._current_script_path() or "").strip()
        if py.lower() not in ("python", "python.exe") and not Path(py).exists():
            QMessageBox.warning(self, "Диагностика", "Интерпретатор Python не найден. Укажите корректный путь.")
            return
        self._append_output("\n=== Диагностика ===")
        self._append_output(f"Python: {py}")
        if script:
            self._append_output(f"Script: {script}")
        self._append_output("")
        def run_cmd(argv: list[str]) -> tuple[int, str]:
            try:
                p = subprocess.run(argv, capture_output=True, text=True)
                out = (p.stdout or "") + (p.stderr or "")
                return p.returncode, out.strip()
            except Exception as e:
                return 999, str(e)
        rc, out = run_cmd([py, "-V"])
        self._append_output(f"[python -V] rc={rc}")
        self._append_output(out or "—")
        checks = ["PySide6", "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets"]
        for m in checks:
            rc, out = run_cmd([py, "-c", f"import {m}; print('OK')"])
            self._append_output(f"[import {m}] rc={rc} -> {out or '—'}")
        if script:
            pth = Path(script)
            self._append_output(f"[script exists] {pth.exists()} :: {pth}")
            self._append_output(f"[script dir] {pth.parent}")
        self._append_output("=== конец диагностики ===\n")
        self.statusBar().showMessage("Диагностика выполнена", 4000)

    def _clear_history(self) -> None:
        self.settings.recent_runs = []
        self._refresh_recent_list()
        self._save_settings()

    def _refresh_recent_list(self) -> None:
        self.recent_list.clear()
        for r in (self.settings.recent_runs or []):
            title = f"{r.get('time','?')} — {Path(r.get('script','')).name} {r.get('args','')}".rstrip()
            it = QListWidgetItem(title)
            it.setData(Qt.UserRole, r)
            self.recent_list.addItem(it)

    def _apply_recent(self, item: QListWidgetItem) -> None:
        r = item.data(Qt.UserRole) or {}
        script = r.get("script", "")
        args = r.get("args", "")
        if script:
            self._set_current_script(script)
            self.args_field.setText(args)
            self._update_script_preview()

def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    try:
        app.setStyle("Fusion")
    except Exception:
        pass
    try:
        app.setFont(QFont("Segoe UI", 10))
    except Exception:
        pass
    window = FriendlyLauncher()
    try:
        icon_path = find_python_icon()
        if icon_path:
            ico = QIcon(icon_path)
            if not ico.isNull():
                app.setWindowIcon(ico)
                window.setWindowIcon(ico)
    except Exception:
        pass
    window.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())

# py -m PyInstaller --noconfirm --clean --onefile --windowed --name Choice --icon choice.ico --collect-all PySide6 --collect-submodules PySide6 --add-data "choice.ico;." choice_dev.py