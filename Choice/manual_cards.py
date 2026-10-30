from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)


def normalize_home_cards(raw: object) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if not isinstance(path, str) or not path.strip():
            continue
        path = path.strip()
        if Path(path).suffix.casefold() not in (".py", ".pyw"):
            continue
        key = path.casefold()
        if key in seen:
            continue
        seen.add(key)
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            name = Path(path).stem
        result.append({"path": path, "name": " ".join(name.split())[:90]})
    return result


class ManualCardsHome(QWidget):
    addRequested = Signal()
    launchRequested = Signal(str)
    removeRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._cards: list[dict[str, str]] = []
        self._running: set[str] = set()
        self._icons: dict[str, str] = {}
        self._columns = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        heading = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("Мои приложения", self)
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        note = QLabel("На главной только те программы, которые ты добавил сам.", self)
        note.setWordWrap(True)
        note.setStyleSheet("color: #576477;")
        titles.addWidget(title)
        titles.addWidget(note)
        heading.addLayout(titles, 1)

        self.add_button = QPushButton("+ Добавить карточку", self)
        self.add_button.clicked.connect(self.addRequested.emit)
        heading.addWidget(self.add_button)
        layout.addLayout(heading)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content = QWidget(self.scroll)
        self.grid = QGridLayout(self.content)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(12)
        self.grid.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.content)
        layout.addWidget(self.scroll, 1)
        self._rebuild()

    def set_cards(
        self,
        cards: object,
        *,
        running: set[str] | None = None,
        icons: dict[str, str] | None = None,
    ) -> None:
        new_cards = normalize_home_cards(cards)
        new_running = set(running or ())
        new_icons = dict(icons or {})
        if (new_cards == self._cards and new_running == self._running
                and new_icons == self._icons):
            return
        self._cards = new_cards
        self._running = new_running
        self._icons = new_icons
        self._rebuild()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        columns = self._column_count()
        if columns != self._columns:
            self._rebuild()

    def _column_count(self) -> int:
        return max(1, min(4, max(0, self.width() - 35) // 255))

    def _rebuild(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()

        self._columns = self._column_count()
        if not self._cards:
            empty = QLabel(
                "Здесь пока нет карточек.\nНажми «+ Добавить карточку», чтобы выбрать приложение.",
                self.content,
            )
            empty.setWordWrap(True)
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet("color: #58687E; padding: 40px 12px;")
            self.grid.addWidget(empty, 0, 0)
            return

        for index, card in enumerate(self._cards):
            self.grid.addWidget(
                self._make_card(card),
                index // self._columns,
                index % self._columns,
            )
        for column in range(self._columns):
            self.grid.setColumnStretch(column, 1)

    def _make_card(self, entry: dict[str, str]) -> QWidget:
        path = entry["path"]
        exists = Path(path).is_file()
        running = path in self._running

        tile = QFrame(self.content)
        tile.setObjectName("ChoiceApplicationCard")
        tile.setStyleSheet(
            "QFrame#ChoiceApplicationCard {"
            " background-color: #FFFFFF; border: 1px solid #BAC6D8;"
            " border-radius: 9px; }"
        )
        tile.setMinimumWidth(190)
        tile.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        body = QVBoxLayout(tile)
        body.setContentsMargins(12, 12, 12, 12)
        body.setSpacing(8)

        top = QHBoxLayout()
        icon_label = QLabel(tile)
        icon_path = self._icons.get(path, "")
        icon = QIcon(icon_path) if icon_path and Path(icon_path).is_file() else QIcon()
        if icon.isNull():
            icon = tile.style().standardIcon(QStyle.SP_FileIcon)
        icon_label.setPixmap(icon.pixmap(36, 36))
        icon_label.setFixedSize(40, 40)
        top.addWidget(icon_label)

        name_label = QLabel(entry["name"], tile)
        name_label.setWordWrap(True)
        name_label.setToolTip(path)
        name_label.setStyleSheet("font-size: 13px; font-weight: 650; color: #1B293C;")
        top.addWidget(name_label, 1)
        body.addLayout(top)

        file_label = QLabel(Path(path).name, tile)
        file_label.setToolTip(path)
        file_label.setStyleSheet("font-size: 11px; color: #607086;")
        body.addWidget(file_label)

        status = QLabel(
            "● Работает" if running else ("● Доступно" if exists else "● Файл не найден"),
            tile,
        )
        status.setStyleSheet(
            "font-size: 11px; font-weight: 600; color: "
            + ("#177249;" if running else ("#566479;" if exists else "#B42318;"))
        )
        body.addWidget(status)

        actions = QHBoxLayout()
        launch = QPushButton("▶ Запустить", tile)
        launch.setEnabled(exists and not running)
        launch.clicked.connect(lambda checked=False, p=path: self.launchRequested.emit(p))
        actions.addWidget(launch, 1)

        remove = QPushButton("Убрать", tile)
        remove.clicked.connect(lambda checked=False, p=path: self.removeRequested.emit(p))
        actions.addWidget(remove)
        body.addLayout(actions)

        return tile
