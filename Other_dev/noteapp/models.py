"""Модель данных заметки. Чистая сериализация, без UI."""

from uuid import uuid4

from PySide6.QtCore import QDateTime, Qt


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
        # БЫЛО: uuid or str(uuid.uuid4()) — параметр uuid затенял модуль uuid,
        # поэтому при uuid=None вычислялось None.uuid4() -> AttributeError.
        # uuid4 импортирован напрямую, модуль не нужен.
        self.uuid = uuid or str(uuid4())
        self.history = history if history is not None else []
        self.history_index = len(self.history) - 1 if self.history else -1
        self.reminder_repeat = reminder_repeat
        self.pinned = pinned
        self.password_manager = password_manager
        self.custom_fields = custom_fields if custom_fields is not None else []
        self.password_manager_visible = False
        self.ignored_words = ignored_words or []
        self.content_txt: str = ""

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
            "password_manager_visible": bool(self.password_manager_visible),
            "custom_fields": self.custom_fields,
            "ignored_words": self.ignored_words,
        }

    @staticmethod
    def from_dict(data: dict) -> "Note":
        # «or» вместо значения по умолчанию: поле может быть в файле, но null —
        # тогда list(None) ронял загрузку всей заметки.
        note = Note(
            title=data.get("title") or "",
            content=data.get("content") or "",
            tags=list(data.get("tags") or []),
            favorite=data.get("favorite", False),
            history=list(data.get("history") or []),
            timestamp=data.get("timestamp"),
            reminder=data.get("reminder"),
            uuid=data.get("uuid"),
            reminder_repeat=data.get("reminder_repeat", None),
            ignored_words=list(data.get("ignored_words") or []),
        )
        note.pinned = data.get("pinned", False)
        # Индекс истории держим в границах: битый или устаревший индекс
        # давал IndexError при отмене/повторе.
        last = len(note.history) - 1
        index = data.get("history_index", last)
        note.history_index = max(-1, min(index, last)) if isinstance(index, int) else last
        note.password_manager = data.get("password_manager") or ""
        note.password_manager_visible = bool(data.get("password_manager_visible", False))
        note.custom_fields = list(data.get("custom_fields") or [])
        note.content_txt = data.get("content_txt") or ""
        return note
