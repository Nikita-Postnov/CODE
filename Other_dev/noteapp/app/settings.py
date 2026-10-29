"""SettingsMixin: настройки, тема оформления, приоритет процесса,
видимость полей и пропорции доков.

Вырезано из NotesApp (step 4.8). Апстрим-методы (rebuild_toolbar,
_current_dock_widths, _restore_view_visibility, _apply_vertical_defaults,
_coerce_to_bool) остаются в NotesApp и доступны через self.
"""

import ctypes
import logging
import platform

from PySide6.QtCore import (
    QTimer,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPalette,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QSpinBox,
    QStyleFactory,
)

from ..config import PROCESS_PRIORITY_LEVELS, _WIN_PRIORITY_CLASS


class SettingsMixin:
    def _load_dock_ratios_from_settings(self) -> list[float]:
        ratios = self.settings.value("ui/dock_ratios") or [0.22, 0.56, 0.22]
        try:
            ratios = [float(r) for r in ratios]
        except Exception:
            ratios = [0.22, 0.56, 0.22]

        ratios = (ratios + [0.22, 0.56, 0.22])[:3]
        total = float(sum(ratios))
        if total <= 0:
            return [0.22, 0.56, 0.22]
        return [r / total for r in ratios]

    def _capture_dock_ratios(self):
        l, c, r = self._current_dock_widths()
        total = max(1, l + c + r)
        self._dock_ratios = [l / total, c / total, r / total]
        try:
            self.settings.setValue("ui/dock_ratios", self._dock_ratios)
        except Exception:
            pass

    def _apply_dock_ratios(self) -> None:
        if self._ignore_dock_resize:
            return
        if not getattr(self, "dock_notes_list", None) or not getattr(
            self, "dock_editor", None
        ):
            return
        self._ignore_dock_resize = True
        try:
            notes_dock = self.dock_notes_list
            editor_dock = self.dock_editor
            lst = self.notes_list
            total_width = notes_dock.width() + editor_dock.width()
            if total_width <= 0:
                total_width = max(self.width(), 800)
            fm = QFontMetrics(lst.font())
            icon_extra = lst.iconSize().width() + 8
            vbar = lst.verticalScrollBar()
            scroll_w = vbar.sizeHint().width() if vbar is not None else 0
            base_padding = scroll_w + 24
            max_text_width = 0
            count = lst.count()
            for i in range(count):
                item = lst.item(i)
                if not item:
                    continue
                text = item.text() or ""
                w = fm.horizontalAdvance(text)
                if not item.icon().isNull():
                    w += icon_extra
                w += base_padding
                if w > max_text_width:
                    max_text_width = w
            if max_text_width <= 0:
                max_text_width = 220
            left_min = max(notes_dock.minimumWidth(), max_text_width)
            editor_min = max(editor_dock.minimumWidth(), 500)
            max_left_allowed = max(notes_dock.minimumWidth(), total_width - editor_min)
            left_width = min(left_min, max_left_allowed)
            editor_width = total_width - left_width
            if editor_width < editor_min:
                editor_width = editor_min
                left_width = max(
                    total_width - editor_width,
                    notes_dock.minimumWidth(),
                )
            if left_width < notes_dock.minimumWidth():
                left_width = notes_dock.minimumWidth()
                editor_width = max(total_width - left_width, editor_min)
            self.resizeDocks(
                [notes_dock],
                [left_width],
                Qt.Horizontal,
            )
            left, center, right = self._current_dock_widths()
            total = float(left + center + right)
            if total > 0:
                self._dock_ratios = (left / total, center / total, right / total)
        finally:
            self._ignore_dock_resize = False

    def load_settings(self) -> None:
        h = self.settings.value("ui/dock_toolbar_height", type=int)
        if not h:
            h = 36
        else:
            h = max(36, min(h, 300))
        self.resizeDocks(
            [self.dock_toolbar],
            [h],
            Qt.Vertical,
        )
        self.dock_toolbar.setMinimumHeight(36)
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        state = self.settings.value("windowState")
        if state:
            self.restoreState(state)
        QTimer.singleShot(0, self._restore_view_visibility)
        try:
            self._apply_dock_ratios()
        except Exception:
            pass
        last_text = self.settings.value("lastNoteText")
        if last_text and not getattr(self, "current_note", None):
            self.text_edit.blockSignals(True)
            self.text_edit.setHtml(last_text)
            self.text_edit.blockSignals(False)
        else:
            self.settings.setValue("lastNoteText", "")
        self._apply_vertical_defaults()

    def save_settings(self) -> None:
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("ui/dock_toolbar_height", self.dock_toolbar.height())
        self.settings.setValue("windowState", self.saveState())
        self.settings.setValue("ui/dock_notes_list_visible",
            self.dock_notes_list.isVisible() if getattr(self, "dock_notes_list", None) else True)
        self.settings.setValue("ui/dock_toolbar_visible",
            self.dock_toolbar.isVisible() if getattr(self, "dock_toolbar", None) else True)
        self.settings.setValue("ui/visibility_toolbar_visible",
            self.visibility_toolbar.isVisible() if getattr(self, "visibility_toolbar", None) else True)
        self.settings.setValue("ui/dock_ratios", self._dock_ratios)
        self.settings.setValue(
            "lastNoteText",
            "" if getattr(self, "current_note", None) else self.text_edit.toHtml(),
        )
        self.settings.sync()

    def show_settings_window(self):
        dialog = QDialog(self)
        dialog.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        dialog.setWindowTitle("Настройки")
        layout = QFormLayout(dialog)
        theme_combo = QComboBox(dialog)
        theme_combo.addItems(["Светлая", "Тёмная"])
        theme_combo.setCurrentIndex(
            0 if self.settings.value("theme", "dark") == "light" else 1
        )
        layout.addRow("Тема:", theme_combo)
        online_spell_cb = QCheckBox(dialog)
        curr_online = self.settings.value("spellcheck/online_enabled", True, type=bool)
        online_spell_cb.setChecked(curr_online)
        online_spell_cb.setToolTip(
            "Если выключено — подчёркивание строится только по локальному словарю."
        )
        layout.addRow("Онлайн-проверка грамматики:", online_spell_cb)
        autosave_debounce = QSpinBox(dialog)
        autosave_debounce.setRange(150, 5000)
        autosave_debounce.setSingleStep(50)
        try:
            autosave_debounce.setValue(
                int(self.settings.value("autosave/debounce_ms", 350))
            )
        except Exception:
            autosave_debounce.setValue(350)
        autosave_debounce.setToolTip(
            "Задержка автосохранения после последнего ввода.\n"
            "Меньше — чаще запись на диск; больше — меньше нагрузки."
        )
        layout.addRow("Автосохранение (мс):", autosave_debounce)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        dialog.setLayout(layout)
        if dialog.exec() == QDialog.Accepted:
            new_theme = "light" if theme_combo.currentIndex() == 0 else "dark"
            self.settings.setValue("theme", new_theme)
            self.spell_online_enabled = online_spell_cb.isChecked()
            self.settings.setValue(
                "spellcheck/online_enabled", self.spell_online_enabled
            )
            if hasattr(self, "spell_highlighter"):
                try:
                    self.spell_highlighter.set_online_enabled(self.spell_online_enabled)
                except Exception:
                    pass
            try:
                self.settings.setValue(
                    "autosave/debounce_ms", int(autosave_debounce.value())
                )
            except Exception:
                pass
            self.init_theme()

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
        "color: white; background-color: #2b2b2b;"
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

    def apply_light_theme(self):
        self.setStyle(QStyleFactory.create("Fusion"))
        default_palette = QApplication.style().standardPalette()
        default_palette.setColor(QPalette.ColorRole.Link, Qt.GlobalColor.black)
        default_palette.setColor(QPalette.ColorRole.LinkVisited, Qt.GlobalColor.black)
        QApplication.instance().setPalette(default_palette)
        self.notes_list.setStyleSheet("color: black; background-color: white;")
        self.text_edit.setFont(QFont("Times New Roman", 14))
        self.text_edit.setStyleSheet(
            "color: black; background-color: white;"
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

    def _set_process_priority(self, level: str) -> bool:
        level = (level or "").strip().lower()
        if level not in _WIN_PRIORITY_CLASS:
            level = "normal"
        if platform.system().lower() != "windows":
            return False
        try:
            kernel32 = ctypes.windll.kernel32
            GetCurrentProcess = kernel32.GetCurrentProcess
            SetPriorityClass = kernel32.SetPriorityClass
            GetCurrentProcess.restype = ctypes.c_void_p
            SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            SetPriorityClass.restype = ctypes.c_int
            hproc = GetCurrentProcess()
            ok = SetPriorityClass(hproc, _WIN_PRIORITY_CLASS[level])
            return bool(ok)
        except Exception:
            return False

    def _get_process_priority(self) -> str:
        if platform.system().lower() != "windows":
            return "normal"
        try:
            kernel32 = ctypes.windll.kernel32
            GetCurrentProcess = kernel32.GetCurrentProcess
            GetPriorityClass = kernel32.GetPriorityClass
            GetCurrentProcess.restype = ctypes.c_void_p
            GetPriorityClass.argtypes = [ctypes.c_void_p]
            GetPriorityClass.restype = ctypes.c_uint32
            hproc = GetCurrentProcess()
            cls = int(GetPriorityClass(hproc))

            for k, v in _WIN_PRIORITY_CLASS.items():
                if int(v) == cls:
                    return k
        except Exception:
            pass

        return "normal"

    def show_process_priority(self) -> None:
        try:
            level = self._get_process_priority()
            self.show_toast(f"Текущий приоритет процесса: {level}")
        except Exception:
            pass

    def _apply_process_priority_from_settings(self) -> None:
        level = "normal"
        try:
            if hasattr(self, "settings") and self.settings is not None:
                level = self.settings.value("system/process_priority", "normal")
        except Exception:
            level = "normal"
        self._set_process_priority(level)

    def set_process_priority_ui(self, level: str) -> None:
        level = (level or "").strip().lower()
        if level not in PROCESS_PRIORITY_LEVELS:
            level = "normal"

        logging.info(f"set_process_priority_ui: requested={level}")

        ok = self._set_process_priority(level)

        logging.info(f"set_process_priority_ui: applied={ok}, level={level}")

        try:
            if hasattr(self, "settings") and self.settings is not None:
                self.settings.setValue("system/process_priority", level)
        except Exception:
            logging.exception("Failed to save process priority to settings")

        try:
            if ok:
                self.show_toast(f"Приоритет процесса: {level}")
            else:
                self.show_toast("Не удалось применить приоритет процесса (или ОС не Windows).")
        except Exception:
            logging.exception("Failed to show toast after priority change")
