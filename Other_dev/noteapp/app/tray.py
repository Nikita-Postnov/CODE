"""TrayMixin: системный трей, глобальные хоткеи и всплывающие тосты.

Вырезано из NotesApp (step 4.5). Апстрим-методы (_invoke_in_main_thread,
bring_widget_to_front, exit_app, translate_case_only, translate_layout_only)
остаются в NotesApp и доступны через self.
"""

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor, QPen, QImage
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QStyle, QSystemTrayIcon, QWidget

from ..config import ICON_PATH, TRAY_ICON_PATH, qt_path
from ..utils import get_keyboard_module


class TrayMixin:
    def _init_tray_icon(self) -> None:
        if getattr(self, "_tray_inited", False):
            return
        try:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                self._tray_inited = True
                return
        except Exception:
            self._tray_inited = True
            return
        try:
            icon = QIcon()
            for source in (TRAY_ICON_PATH, ICON_PATH):
                if not source.is_file():
                    continue
                candidate = QIcon(qt_path(source))
                if not candidate.isNull() and not candidate.pixmap(32, 32).isNull():
                    icon = candidate
                    break
                try:
                    from PIL import Image
                    from io import BytesIO
                    with Image.open(source) as image:
                        image.seek(0)
                        image = image.convert("RGBA")
                        image.thumbnail((64, 64))
                        raw = image.tobytes("raw", "RGBA")
                        qt_image = QImage(raw, image.width, image.height,
                                          image.width * 4, QImage.Format_RGBA8888).copy()
                        icon = QIcon(QPixmap.fromImage(qt_image))
                    if not icon.isNull():
                        break
                except (ImportError, OSError, ValueError):
                    pass
            if icon.isNull():
                pixmap = QPixmap(32, 32)
                pixmap.fill(Qt.transparent)
                painter = QPainter(pixmap)
                painter.setRenderHint(QPainter.Antialiasing)
                painter.setPen(QPen(QColor("#2C67C7"), 2))
                painter.setBrush(QColor("#FFFFFF"))
                painter.drawRoundedRect(4, 2, 24, 28, 3, 3)
                painter.drawLine(9, 12, 23, 12)
                painter.drawLine(9, 17, 23, 17)
                painter.drawLine(9, 22, 19, 22)
                painter.end()
                icon = QIcon(pixmap)
            self.tray_icon = QSystemTrayIcon(self)
            if not icon.isNull():
                self.tray_icon.setIcon(icon)
            self.tray_icon.activated.connect(self.on_tray_icon_activated)
            self.tray_icon.setToolTip("Мои Заметки")
            menu = QMenu()
            restore_action = QAction("Открыть", self)
            restore_action.triggered.connect(self.show)
            exit_action = QAction("Выход", self)
            exit_action.triggered.connect(self.exit_app)
            menu.addAction(restore_action)
            menu.addAction(exit_action)
            self.tray_icon.setContextMenu(menu)
            # setContextMenu не забирает меню во владение: без ссылки его может
            # удалить сборщик мусора, и правый клик по значку перестанет работать.
            self._tray_menu = menu
            if not self.tray_icon.icon().isNull():
                self.tray_icon.setVisible(True)
        finally:
            self._tray_inited = True

    def _register_global_hotkeys(self) -> None:
        kb = get_keyboard_module()
        if kb is None:
            return
        self._unregister_global_hotkeys()
        try:
            hk_layout = kb.add_hotkey(
                "ctrl+shift+f12",
                lambda: self._invoke_in_main_thread(self.translate_layout_only),
                suppress=False,
            )
            # Глобальная смена регистра (Ctrl+Alt+F12) убрана: эта комбинация
            # закрывает punto_like, а регистр меняет он сам (F9 / Ctrl+F9).
            self._global_hotkeys = [hk_layout]
        except Exception:
            self._global_hotkeys = []

    def _unregister_global_hotkeys(self) -> None:
        kb = get_keyboard_module()
        if kb is None:
            return
        for hk in getattr(self, "_global_hotkeys", []):
            try:
                kb.remove_hotkey(hk)
            except Exception:
                pass
        self._global_hotkeys = []

    def show_toast(
        self,
        text: str,
        ms: int = 3000,
        *,
        timeout_ms: int | None = None,
        boundary_widget: QWidget | None = None,
        anchor_widget: QWidget | None = None,
    ) -> None:
        duration = timeout_ms if timeout_ms is not None else ms
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
            if lbl not in self._live_toasts:
                return
            try:
                lbl.close()
            except RuntimeError:
                pass
            finally:
                if lbl in self._live_toasts:
                    self._live_toasts.remove(lbl)
                lbl.deleteLater()
        QTimer.singleShot(duration, _close)

    def show_from_tray(self):
        self.bring_widget_to_front(self)

    def on_tray_icon_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.show_from_tray()
