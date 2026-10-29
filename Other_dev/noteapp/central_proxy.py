"""Прокси центрального виджета для NotesApp."""

from PySide6.QtWidgets import (
    QWidget,
)


class _CentralWidgetProxy:
    def __init__(self, widget: QWidget):
        self._w = widget
        self._title = ""

    def widget(self):
        return self._w

    def setVisible(self, v: bool):
        self._w.setVisible(v)

    def isVisible(self) -> bool:
        return self._w.isVisible()

    def width(self) -> int:
        return self._w.width()

    def height(self) -> int:
        return self._w.height()

    def minimumWidth(self) -> int:
        return self._w.minimumWidth()

    def setMinimumWidth(self, w: int):
        self._w.setMinimumWidth(int(w))

    def resize(self, w: int, h: int):
        try:
            self._w.resize(int(w), int(h))
        except Exception:
            pass

    def setWindowTitle(self, title: str):
        self._title = str(title)

    def windowTitle(self) -> str:
        return self._title
