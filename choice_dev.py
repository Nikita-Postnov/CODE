from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import ast
import json
import os
import shutil
import sys
import shlex
import subprocess
import time
from PySide6.QtCore import Qt, QProcess, QProcessEnvironment, QSize, QTimer
from PySide6.QtGui import QIcon, QFont, QKeySequence, QAction
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
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
    QMenu,
)

APP_TITLE = "Launcher — дружелюбный лаунчер скриптов"
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
    if not getattr(sys, "frozen", False) and sys.executable:
        return sys.executable
    return "python.exe" if running_on_windows() else "python"

def find_python_icon() -> QIcon:
    try:
        candidates = [
            app_folder() / "files" / "Data" / "icon.ico",
            app_folder() / "Data" / "icon.ico",
        ]
        for p in candidates:
            if p.exists():
                return QIcon(str(p))
    except Exception:
        pass
    return QIcon()

def list_python_files(root: Path, recursive: bool) -> list[Path]:
    if not root.exists() or not root.is_dir():
        return []
    def excluded(p: Path) -> bool:
        return any(part.lower() == "plugins" for part in p.parts)
    if recursive:
        found = root.rglob("*.py")
    else:
        found = root.glob("*.py")
    files = [p for p in found if p.is_file() and not excluded(p)]
    files.sort(key=lambda p: (p.name.lower(), str(p).lower()))
    return files

def safe_open(p: Path) -> None:
    try:
        if running_on_windows():
            os.startfile(str(p))
        else:
            subprocess.Popen(["xdg-open", str(p)])
    except Exception:
        pass

def time_stamp() -> str:
    return time.strftime("%Y-%m-%d_%H-%M-%S")

@dataclass
class Settings:
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
    recent_runs: list[dict] | None = None

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
            "recent_runs": self.recent_runs or [],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

class FriendlyLauncher(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings.load(config_file())
        self.process: Optional[QProcess] = None
        self.start_time: Optional[float] = None
        self.all_scripts: list[Path] = []
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(QSize(1100, 700))
        self._create_actions()
        self._create_toolbar()
        self._create_main_ui()
        self.setStatusBar(QStatusBar(self))
        QTimer.singleShot(0, self._startup_deferred)

    def _startup_deferred(self) -> None:
        self._refresh_script_list(save=False)
        self._restore_previous()
        self._update_script_preview()

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
        self.action_check_env = QAction("Проверить окружение", self)
        self.action_check_env.setShortcut(QKeySequence("Ctrl+D"))
        self.action_check_env.triggered.connect(self._run_system_checks)

        # Доп. действия для удобства работы со скриптами (не влияют на запуск)

        self.action_open_in_editor = QAction("Открыть в редакторе", self)
        self.action_open_in_editor.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self.action_open_in_editor.triggered.connect(self._open_current_script_in_editor)

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
        tb.addAction(self.action_save_log)

    def _create_main_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        splitter = QSplitter(Qt.Horizontal, self)
        main_layout.addWidget(splitter, 1)
        left_panel = QWidget(self)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        folder_box = QGroupBox("Папка со скриптами")
        folder_layout = QFormLayout(folder_box)
        self.python_field = QLineEdit(self.settings.python_executable or detect_system_python())
        btn_python = QPushButton("Выбрать интерпретатор")
        btn_python.clicked.connect(self._choose_python)
        python_row = QWidget()
        py_row_layout = QHBoxLayout(python_row)
        py_row_layout.setContentsMargins(0, 0, 0, 0)
        py_row_layout.addWidget(self.python_field, 1)
        py_row_layout.addWidget(btn_python)
        folder_layout.addRow("Python:", python_row)
        self.folder_field = QLineEdit(self.settings.scripts_folder or str(app_folder()))
        btn_folder = QPushButton("Папка")
        btn_folder.clicked.connect(self._choose_scripts_folder)
        folder_row = QWidget()
        folder_row_layout = QHBoxLayout(folder_row)
        folder_row_layout.setContentsMargins(0, 0, 0, 0)
        folder_row_layout.addWidget(self.folder_field, 1)
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
        search_row = QWidget()
        search_layout = QHBoxLayout(search_row)
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Поиск по имени или пути")
        self.search_field.textChanged.connect(self._apply_filters)
        self.fav_only_checkbox = QCheckBox("Только избранные")
        self.fav_only_checkbox.stateChanged.connect(self._apply_filters)
        search_layout.addWidget(self.search_field, 1)
        search_layout.addWidget(self.fav_only_checkbox)
        selection_layout.addWidget(search_row)
        self.scripts_list = QListWidget()
        self.scripts_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.scripts_list.customContextMenuRequested.connect(self._scripts_context_menu)
        self.scripts_list.currentItemChanged.connect(self._on_script_selected)
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
        env_group = QGroupBox("Переменные окружения (каждая строка KEY=VALUE)")
        env_layout = QVBoxLayout(env_group)
        self.env_editor = QPlainTextEdit()
        env_layout.addWidget(self.env_editor)
        run_layout.addRow(env_group)
        middle_layout.addWidget(run_box)
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
        self.output_text.setPlaceholderText("Стандартный вывод (stdout)")
        self.error_text = QPlainTextEdit()
        self.error_text.setReadOnly(True)
        self.error_text.setPlaceholderText("Ошибки и диагностика (stderr)")
        self.output_tabs.addTab(self.output_text, "Вывод")
        if bool(self.settings.show_errors_tab):
            self.output_tabs.addTab(self.error_text, "Ошибки")
        bottom_row = QWidget()
        bottom_layout = QHBoxLayout(bottom_row)
        save_log_btn = QPushButton("Сохранить лог")
        save_log_btn.clicked.connect(self._save_log)
        open_cfg_btn = QPushButton("Открыть настройки")
        open_cfg_btn.clicked.connect(self._open_config_file)
        bottom_layout.addWidget(save_log_btn)
        bottom_layout.addWidget(open_cfg_btn)
        bottom_layout.addStretch(1)
        right_layout.addWidget(self.output_tabs, 1)
        right_layout.addWidget(bottom_row)
        splitter.addWidget(left_panel)
        splitter.addWidget(middle_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([350, 350, 550])

    def _choose_python(self) -> None:
        start = self.python_field.text().strip()
        start_dir = str(Path(start).parent) if start and Path(start).exists() else str(app_folder())
        path, _ = QFileDialog.getOpenFileName(self, "Выберите интерпретатор Python", start_dir, "Python (python.exe);;Все файлы (*)" if running_on_windows() else "Все файлы (*)")
        if path:
            self.python_field.setText(path)
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
        self._apply_filters()
        if save:
            self._save_settings()

    def _apply_filters(self) -> None:
        q = (self.search_field.text() or "").strip().lower()
        fav_only = self.fav_only_checkbox.isChecked()
        favorites = set(self.settings.favorites or [])
        current = (self._current_script_path() or "").strip()
        self.scripts_list.blockSignals(True)
        self.scripts_list.clear()
        for p in self.all_scripts:
            sp = str(p)
            if fav_only and sp not in favorites:
                continue
            hay = (p.name + " " + sp).lower()
            if q and q not in hay:
                continue
            title = p.name
            if sp in favorites:
                title = "⭐ " + title
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, sp)
            item.setToolTip(sp)
            self.scripts_list.addItem(item)
        self.scripts_list.blockSignals(False)
        if current:
            self._highlight_script_in_list(current)

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
        fav = self.settings.favorites or []
        if s in fav:
            fav = [x for x in fav if x != s]
        else:
            fav.append(s)
        self.settings.favorites = fav
        self._apply_filters()
        self._update_star_button()
        self._save_settings()

    def _update_star_button(self) -> None:
        s = (self._current_script_path() or "").strip()
        fav = set(self.settings.favorites or [])
        self.star_button.setText("★" if s and s in fav else "☆")

    def _scripts_context_menu(self, pos) -> None:
        it = self.scripts_list.itemAt(pos)
        if not it:
            return
        path = (it.data(Qt.UserRole) or "").strip()
        menu = QMenu(self)
        a_run = menu.addAction("Запустить")
        a_fav = menu.addAction("Добавить/убрать избранное")
        menu.addSeparator()
        a_open_file = menu.addAction("Открыть файл")
        a_open_editor = menu.addAction("Открыть в редакторе")
        a_open_dir = menu.addAction("Открыть папку")
        menu.addSeparator()
        a_req = menu.addAction("Проверить требования (импорты)")
        menu.addSeparator()
        a_copy = menu.addAction("Копировать путь")
        act = menu.exec(self.scripts_list.mapToGlobal(pos))
        if act == a_run:
            self._set_current_script(path)
            self.run_script()
        elif act == a_fav:
            self._set_current_script(path)
            self._toggle_favorite()
        elif act == a_open_file:
            self._set_current_script(path)
            self._open_current_script()
        elif act == a_open_editor:
            self._set_current_script(path)
            self._open_current_script_in_editor()
        elif act == a_open_dir:
            p = Path(path)
            if p.exists():
                safe_open(p.parent)
        elif act == a_req:
            self._set_current_script(path)
            self._check_requirements_for_current_script()
        elif act == a_copy:
            QApplication.clipboard().setText(path)

    def _current_script_path(self) -> str:
        return (self.settings.last_script_path or "").strip()

    def _update_script_preview(self) -> None:
        script = self._current_script_path()
        if not script:
            self._set_status_no_script()
            return
        p = Path(script)
        exists = p.exists()
        size = f"{p.stat().st_size} байт" if exists else "—"
        info = f"Файл: {p.name}\nПуть: {p}\nСтатус: {'найден' if exists else 'НЕ НАЙДЕН'}\nРазмер: {size}"
        self.statusBar().showMessage("", 1)
        self._update_star_button()
        self.preview_button.setEnabled(True)
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def _set_status_no_script(self) -> None:
        self.preview_button.setEnabled(False)
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def _copy_preview(self) -> None:
        cmd = self._build_command_string()
        QApplication.clipboard().setText(cmd)
        self.statusBar().showMessage("Команда скопирована в буфер обмена", 3000)

    def _build_command_string(self) -> str:
        py = (self.python_field.text() or "").strip()
        script = (self._current_script_path() or "").strip()
        args = split_command_line(self.args_field.text())
        parts = [py, script] + args
        if running_on_windows():
            def q(s: str) -> str:
                if not s:
                    return s
                return f'"{s}"' if (" " in s or "\t" in s) else s
            return " ".join(q(p) for p in parts if p)
        return " ".join(shlex.quote(p) for p in parts if p)

    def _validate_before_run(self) -> tuple[bool, str]:
        py = (self.python_field.text() or "").strip()
        script = (self._current_script_path() or "").strip()
        if not script:
            return False, "Не выбран скрипт для запуска."
        if not Path(script).exists():
            return False, f"Скрипт не найден: {script}"
        if py.lower() not in ("python", "python.exe"):
            if not py:
                return False, "Не указан путь к интерпретатору Python."
            if not Path(py).exists():
                return False, f"Интерпретатор Python не найден: {py}"
        return True, ""

    def _parse_env_editor(self) -> dict[str, str]:
        text = self.env_editor.toPlainText().strip()
        env: dict[str, str] = {}
        if not text:
            return env
        for line in text.splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
        return env

    def run_script(self) -> None:
        ok, msg = self._validate_before_run()
        if not ok:
            QMessageBox.warning(self, "Ошибка", msg)
            return
        if self.process and self.process.state() != QProcess.NotRunning:
            QMessageBox.information(self, "Выполнение", "Процесс уже запущен.")
            return
        py = (self.python_field.text() or "").strip()
        script = (self._current_script_path() or "").strip()
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
        self.start_time = time.time()
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.SeparateChannels)
        if workdir:
            self.process.setWorkingDirectory(workdir)
        self.process.readyReadStandardOutput.connect(self._on_stdout)
        self.process.readyReadStandardError.connect(self._on_stderr)
        self.process.finished.connect(self._on_finished)
        self.process.errorOccurred.connect(self._on_error)
        self._set_running_ui(True)
        root = str(app_folder())
        env = QProcessEnvironment.systemEnvironment()
        env.insert("LAUNCHER_ROOT", root)
        extra_env = self._parse_env_editor()
        for k, v in extra_env.items():
            env.insert(k, v)
        self.process.setProcessEnvironment(env)
        self.process.start(py, [script] + args)
        self.settings.per_script_workdir = self.settings.per_script_workdir or {}
        self.settings.per_script_workdir[script] = workdir
        self.settings.recent_runs = self.settings.recent_runs or []
        self.settings.recent_runs.insert(0, {"script": script, "args": self.args_field.text(), "time": time.strftime("%Y-%m-%d %H:%M:%S")})
        self.settings.recent_runs = self.settings.recent_runs[:30]
        if not self.process.waitForStarted(3000):
            self._set_running_ui(False)
            self._append_error("! Не удалось запустить процесс (таймаут ожидания).")
            QMessageBox.critical(self, "Ошибка", "Не удалось запустить процесс.")
            self.process = None
            return
        self.statusBar().showMessage("Процесс запущен", 3000)
        self._save_settings()
        self._refresh_recent_list()

    def _set_running_ui(self, running: bool) -> None:
        self.run_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.action_run.setEnabled(not running)
        self.action_stop.setEnabled(running)

    def stop_script(self) -> None:
        if not self.process or self.process.state() == QProcess.NotRunning:
            return
        self._append_output("\n> Stop requested...")
        self.process.terminate()
        if not self.process.waitForFinished(2500):
            self.process.kill()

    def _on_stdout(self) -> None:
        if not self.process:
            return
        data = bytes(self.process.readAllStandardOutput()).decode(errors="replace")
        if data:
            self._append_output(data)

    def _on_stderr(self) -> None:
        if not self.process:
            return
        data = bytes(self.process.readAllStandardError()).decode(errors="replace")
        if data:
            self._append_error(data)

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        status = "NormalExit" if exit_status == QProcess.NormalExit else "CrashExit"
        dur = ""
        if self.start_time is not None:
            try:
                dur = f", duration={time.time() - self.start_time:.2f}s"
            except Exception:
                dur = ""
        self._append_output(f"\n> Finished: exit_code={exit_code}, status={status}{dur}")
        self.start_time = None
        self._set_running_ui(False)
        self.statusBar().showMessage(f"Завершено: {status}, code={exit_code}", 5000)

    def _on_error(self, err: QProcess.ProcessError) -> None:
        self._append_error(f"\n! ProcessError: {err}")
        self._set_running_ui(False)
        self.statusBar().showMessage(f"Ошибка процесса: {err}", 5000)

    def _append_output(self, text: str) -> None:
        if not text:
            return
        self.output_text.appendPlainText(text.rstrip("\n"))
        if self.autoscroll_checkbox.isChecked():
            QTimer.singleShot(0, lambda: self.output_text.verticalScrollBar().setValue(self.output_text.verticalScrollBar().maximum()))

    def _append_error(self, text: str) -> None:
        if not text:
            return
        self.error_text.appendPlainText(text.rstrip("\n"))
        if self.autoscroll_checkbox.isChecked():
            QTimer.singleShot(0, lambda: self.error_text.verticalScrollBar().setValue(self.error_text.verticalScrollBar().maximum()))

    def _clear_output_texts(self) -> None:
        self.output_text.clear()
        self.error_text.clear()

    def _save_settings(self) -> None:
        self.settings.python_executable = (self.python_field.text() or "").strip()
        self.settings.scripts_folder = (self.folder_field.text() or "").strip()
        self.settings.last_script_path = (self.settings.last_script_path or "").strip()
        self.settings.last_arguments = self.args_field.text()
        self.settings.last_workdir = (self.workdir_field.text() or "").strip()
        self.settings.scan_subfolders = self.scan_checkbox.isChecked()
        self.settings.clear_output_on_start = self.clear_checkbox.isChecked()
        self.settings.autoscroll_output = self.autoscroll_checkbox.isChecked()
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

    # --- Открытие скрипта / редактор ---
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
        """Пытается открыть файл в редакторе. Не влияет на запуск скриптов."""
        cmd = self._detect_editor_command()
        try:
            if cmd:
                # cmd может быть строкой или списком (на случай сложных команд)
                if isinstance(cmd, str):
                    argv = split_command_line(cmd)
                else:
                    argv = list(cmd)
                argv.append(str(path))
                subprocess.Popen(argv)
                return True, ""
        except Exception as e:
            return False, f"Не удалось открыть в редакторе: {e}"

        # Фолбэк — открыть системным способом (ассоциации ОС)
        try:
            safe_open(path)
            return True, "Редактор не найден; файл открыт системным приложением по умолчанию."
        except Exception as e:
            return False, f"Редактор не найден и системное открытие не сработало: {e}"

    def _detect_editor_command(self) -> Optional[object]:
        """Возвращает команду редактора.

        Приоритет:
          1) LAUNCHER_EDITOR
          2) EDITOR
          3) VS Code (code)
          4) Windows: notepad
          5) Linux/macOS: None (будет safe_open)
        """
        env_editor = (os.environ.get("LAUNCHER_EDITOR") or os.environ.get("EDITOR") or "").strip()
        if env_editor:
            return env_editor
        if shutil.which("code"):
            return ["code", "-g"]
        if running_on_windows():
            return ["notepad"]
        return None

    # --- Проверка требований (импорты) ---
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

        # Проверяем только "верхнеуровневые" модули (requests, numpy, PySide6 и т.д.)
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
            self._append_output("\nПохоже, отсутствуют:")
            for m in missing:
                self._append_output(f"  - {m}")
        self._append_output("=== конец проверки требований ===\n")

        if missing:
            QMessageBox.warning(
                self,
                "Требования",
                "Обнаружены отсутствующие импорты. Смотри вкладку 'Вывод' для деталей."
            )
        else:
            QMessageBox.information(
                self,
                "Требования",
                "Все найденные импорты успешно импортируются выбранным Python."
            )

    def _extract_imports(self, script_path: Path) -> tuple[set[str], set[str]]:
        """Возвращает (imports, relative_imports).

        imports: множество верхнеуровневых модулей ("requests", "PySide6", ...)
        relative_imports: относительные импорты ("from .x import y"), их не проверяем автоматически.
        """
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
                # node.module может быть None (например: from . import x)
                if getattr(node, "level", 0) and node.level > 0:
                    mod = node.module or ""
                    rel.add("." * node.level + mod)
                    continue
                mod = (node.module or "").strip()
                if mod:
                    imports.add(mod.split(".")[0])
        # Явно игнорируем импорт самого файла, если имя совпадает (редкий случай)
        try:
            imports.discard(script_path.stem)
        except Exception:
            pass
        return imports, rel

    def _run_python_import_check(self, python_exe: str, module: str) -> tuple[int, str]:
        """Проверяет `import <module>` выбранным интерпретатором."""
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
            title = f"{r.get('time','?')} — {Path(r.get('script','')).name} {r.get('args','')}"
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
        icon = find_python_icon()
        if not icon.isNull():
            app.setWindowIcon(icon)
            window.setWindowIcon(icon)
    except Exception:
        pass
    window.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())