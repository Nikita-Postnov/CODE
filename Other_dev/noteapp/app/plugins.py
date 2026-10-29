"""PluginsMixin: обнаружение, загрузка и состояние плагинов.

Вырезано из NotesApp (step 4.3). Группа полностью самодостаточна —
наружу вызывает только собственные методы и атрибуты self.
"""

import datetime
import importlib
import json
import logging
import os
import shutil
import sys
import traceback

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..config import DATA_DIR, PLUGINS_DIR, qt_path


class PluginsMixin:
    def manage_plugins_dialog(self):
        plugins_folder = str(PLUGINS_DIR)
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
        dialog.setWindowFlag(Qt.WindowStaysOnTopHint, True)
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
            self._atomic_write_json(plugins_state_path, plugins_state)
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

    def _append_plugin_error(self, message: str, exc: BaseException) -> None:
        try:
            log_path = DATA_DIR / "plugin_errors.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.datetime.now().isoformat(sep=' ', timespec='seconds')}] {message}\n")
                traceback.print_exception(type(exc), exc, exc.__traceback__, file=f)
        except Exception:
            pass

    def load_plugins(self) -> None:
        importlib.invalidate_caches()
        self.clear_plugin_menu_actions()

        for module in getattr(self, "active_plugins", {}).values():
            try:
                on_disable = getattr(module, "on_disable", None)
                if callable(on_disable):
                    on_disable(parent=self)
            except Exception as exc:
                logging.exception(
                    "Ошибка при деинициализации плагина %s",
                    getattr(module, "__name__", "<unknown>"),
                )
                self._append_plugin_error(
                    f"Ошибка при деинициализации плагина {getattr(module, '__name__', '<unknown>')}: {exc}",
                    exc,
                )

        plugins_folder = PLUGINS_DIR
        plugins_state_path = DATA_DIR / "plugins_state.json"

        try:
            if plugins_state_path.is_file():
                with open(plugins_state_path, "r", encoding="utf-8") as f:
                    plugins_state = json.load(f)
            else:
                plugins_state = {}
        except Exception:
            logging.exception("Не удалось прочитать %s", qt_path(plugins_state_path))
            plugins_state = {}

        self.active_plugins = {}

        if not plugins_folder.is_dir():
            return

        for plugin_file in sorted(plugins_folder.glob("*.py"), key=lambda p: p.name.lower()):
            plugin_name = plugin_file.stem
            try:
                spec = importlib.util.spec_from_file_location(plugin_name, str(plugin_file))
                if spec is None or spec.loader is None:
                    raise RuntimeError(f"spec/loader is None for plugin: {plugin_file.name}")
                module = importlib.util.module_from_spec(spec)
                sys.modules[plugin_name] = module
                try:
                    spec.loader.exec_module(module)
                except Exception:
                    sys.modules.pop(plugin_name, None)
                    raise
                self.active_plugins[plugin_name] = module

                if plugins_state.get(plugin_name, False):
                    on_enable = getattr(module, "on_enable", None)
                    if callable(on_enable):
                        on_enable(parent=self)
            except Exception as exc:
                logging.exception("Ошибка при загрузке плагина %s", plugin_name)
                self._append_plugin_error(
                    f"Ошибка при загрузке плагина {plugin_name} ({plugin_file.name}): {exc}",
                    exc,
                )
                continue

    def detect_plugins(self):
        plugins = []
        plugins_folder = str(PLUGINS_DIR)
        if os.path.exists(plugins_folder):
            for file in os.listdir(plugins_folder):
                if file.endswith(".py"):
                    plugins.append(file[:-3])
        return plugins

    def load_plugins_state(self):
        plugins_path = os.path.join(DATA_DIR, "plugins_state.json")
        self.plugins_state = {}
        if os.path.exists(plugins_path):
            # Битый plugins_state.json раньше ронял запуск приложения.
            try:
                with open(plugins_path, "r", encoding="utf-8") as f:
                    state = json.load(f)
                if isinstance(state, dict):
                    self.plugins_state = state
            except Exception:
                logging.exception("plugins_state.json не читается — плагины в состоянии по умолчанию")

    def save_plugins_state(self):
        plugins_path = os.path.join(DATA_DIR, "plugins_state.json")
        try:
            self._atomic_write_json(plugins_path, self.plugins_state)
        except Exception:
            try:
                with open(plugins_path, "w", encoding="utf-8") as f:
                    json.dump(self.plugins_state, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
