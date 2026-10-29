"""SearchMixin: поиск, фильтрация по тегам и сортировка списка заметок.

Вырезано из NotesApp (step 4.9). eventFilter НЕ входит сюда (он про undo/redo
и переименование заголовка — остаётся в ядре). Апстрим-методы (refresh_notes_list,
show_all_notes, show_notes_by_tag, get_all_tags, get_contrast_favorite_color)
остаются в NotesApp и доступны через self.
"""

import time

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtGui import QFont, QTextDocument
from PySide6.QtWidgets import QFrame, QListWidgetItem

from ..models import Note


class SearchMixin:
    def apply_sorting(self) -> None:
        index = self.sort_combo.currentIndex()
        reverse = self.sort_order_combo.currentIndex() == 1

        if index == 0:
            self.notes.sort(key=lambda note: (note.title or "").lower(), reverse=reverse)
            self.refresh_notes_list()
        elif index == 1:
            self.notes.sort(key=lambda note: (note.timestamp or ""), reverse=reverse)
            self.refresh_notes_list()
        elif index == 2:
            self.notes.sort(
                key=lambda note: (not bool(note.favorite), (note.title or "").lower()),
                reverse=reverse,
            )
            self.refresh_notes_list()

    def filter_notes(self):
        if self.current_note:
            self.current_note.content = self.text_edit.toHtml()
        query = self.search_field.text().strip().lower()
        if not query:
            return self.notes
        filtered: list[Note] = []
        for note in self.notes:
            content_plain = getattr(note, "content_txt", "") or ""
            if self.current_note and note.uuid == self.current_note.uuid:
                content_plain = self.text_edit.toPlainText()
                note.content_txt = content_plain
            elif not content_plain:
                doc = QTextDocument()
                doc.setHtml(note.content)
                content_plain = doc.toPlainText()
                note.content_txt = content_plain
            reminder_raw = str(note.reminder or "").lower()
            reminder_human = ""
            if note.reminder:
                try:
                    dt = QDateTime.fromString(note.reminder, Qt.ISODate)
                    if dt.isValid():
                        reminder_human = dt.toString("dd.MM.yyyy HH:mm")
                except Exception:
                    reminder_human = ""
            if (
                query in note.title.lower()
                or query in content_plain.lower()
                or query in reminder_raw
                or (reminder_human and query in reminder_human.lower())
            ):
                filtered.append(note)
        return filtered

    def sort_notes_by_title(self) -> None:
        self.notes.sort(key=lambda note: note.title.lower())
        self.refresh_notes_list()

    def sort_notes_by_date(self) -> None:
        self.notes.sort(key=lambda note: note.timestamp, reverse=True)
        self.refresh_notes_list()

    def apply_tag_filter(self) -> None:
        selected_tag = self.tag_filter.currentText()
        if selected_tag == "Все теги" or not selected_tag:
            self.show_all_notes()
        else:
            self.show_notes_by_tag(selected_tag)

    def trigger_search(self):
        self.handle_combined_search()

    def handle_combined_search(self):
        tag = self.tag_filter.currentText().strip().lower()
        if tag == "все теги":
            tag = ""

        text = self.search_bar.text().strip().lower()
        mode = self.search_mode_combo.currentText()

        if not text and not tag:
            self.refresh_notes_list()
            return

        def _matches(note):
            matches_tag_filter = tag in [t.lower() for t in note.tags] if tag else True
            if not text:
                return matches_tag_filter
            note_tags_joined = " ".join([t for t in (note.tags or [])]).lower()
            matches_search_by_tags = text in note_tags_joined if note_tags_joined else False
            if mode == "Заголовок":
                matches_search_main = text in (note.title or "").lower()
            elif mode == "Напоминание":
                matches_search_main = bool(note.reminder) and text in str(note.reminder).lower()
            else:
                content_plain = getattr(note, "content_txt", "") or ""
                if not content_plain:
                    doc = QTextDocument()
                    doc.setHtml(note.content)
                    content_plain = doc.toPlainText()
                    note.content_txt = content_plain
                matches_search_main = text in content_plain.lower()
            return matches_tag_filter and (matches_search_main or matches_search_by_tags)
        filtered = [n for n in self.notes if _matches(n)]
        fav_color = self.get_contrast_favorite_color()
        current_uuid = self.current_note.uuid if self.current_note else None
        self.notes_list.clear()

        def _add_note(note):
            timestamp = QDateTime.fromString(note.timestamp, Qt.ISODate)
            date_str = timestamp.toString("dd.MM.yyyy")
            reminder_symbol = " 🔔" if note.reminder else ""
            item_text = f"{note.title} — {date_str}{reminder_symbol}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, note)
            item.setFont(QFont("Segoe UI Emoji", 10))
            if note.favorite:
                item.setForeground(fav_color)
            self.notes_list.addItem(item)
        pinned = [n for n in filtered if n.pinned]
        unpinned = [n for n in filtered if not n.pinned]
        for n in pinned:
            _add_note(n)
        if pinned and unpinned:
            sep_item = QListWidgetItem()
            sep_item.setFlags(Qt.NoItemFlags)
            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            line.setFrameShadow(QFrame.Sunken)
            sep_item.setSizeHint(line.sizeHint())
            self.notes_list.addItem(sep_item)
            self.notes_list.setItemWidget(sep_item, line)
        for n in unpinned:
            _add_note(n)
        if current_uuid:
            for i in range(self.notes_list.count()):
                it = self.notes_list.item(i)
                n = it.data(Qt.UserRole)
                if n and n.uuid == current_uuid:
                    self.notes_list.setCurrentItem(it)
                    break

    def update_tag_filter_items(self):
        all_tags = sorted(self.get_all_tags())
        self.tag_filter.clear()
        self.tag_filter.addItem("Все теги")
        self.tag_filter.addItems(all_tags)

    def update_search_filter_items(self) -> None:
        if not hasattr(self, "search_mode_combo") or self.search_mode_combo is None:
            return
        modes = ["Заголовок", "Содержимое", "Напоминание"]
        self.search_mode_combo.blockSignals(True)
        self.search_mode_combo.clear()
        self.search_mode_combo.addItems(modes)
        self.search_mode_combo.blockSignals(False)

    def _timestamp_sort_key(self, note: "Note") -> int:
        try:
            dt = QDateTime.fromString(getattr(note, "timestamp", "") or "", Qt.ISODate)
            if dt.isValid():
                return int(dt.toSecsSinceEpoch())
        except Exception:
            pass
        try:
            return int(time.time())
        except Exception:
            return 0
