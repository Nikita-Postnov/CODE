"""LayoutMixin: переключение раскладки клавиатуры и регистра текста.

Punto-подобные операции: транслитерация раскладки и смена регистра — для всего
документа и для выделения. Вырезано из NotesApp (step 4.13). Апстрим-метод
record_state_for_undo остаётся в NotesApp и доступен через self.
"""

from typing import Callable

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from ..constants import EN_LAYOUT, EN_TO_RU, RU_LAYOUT, RU_TO_EN


class LayoutMixin:
    def _replace_selection_with_text(self, cursor: QTextCursor, new_text: str) -> None:
        selection_start = cursor.selectionStart()
        cursor.insertText(new_text, self.text_edit._default_char_format())
        cursor.setPosition(selection_start)
        cursor.setPosition(selection_start + len(new_text), QTextCursor.KeepAnchor)
        self.text_edit.setTextCursor(cursor)

    def toggle_case(self) -> None:
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            text = cursor.selectedText()
            text = text.swapcase()
            self._replace_selection_with_text(cursor, text)
            self.record_state_for_undo()

    def _convert_layout_text(self, text: str) -> str:
        ru_count = sum(1 for ch in text if ch.lower() in RU_LAYOUT)
        en_count = sum(1 for ch in text if ch.lower() in EN_LAYOUT)
        if ru_count == 0 and en_count == 0:
            return text
        table = EN_TO_RU if en_count >= ru_count else RU_TO_EN
        return text.translate(table)

    def _swap_case_text(self, text: str) -> str:
        return text.swapcase()

    def _apply_text_transform(
        self, transform: Callable[[str], str], message: str
    ) -> None:
        cursor = self.text_edit.textCursor()
        used_selection = False
        if cursor.hasSelection():
            text = cursor.selectedText()
            used_selection = True
        else:
            clipboard = QApplication.clipboard()
            text = clipboard.text()
        if not text:
            return
        converted = transform(text)
        if used_selection:
            self._replace_selection_with_text(cursor, converted)
            self.record_state_for_undo()
        else:
            clipboard.setText(converted)
            if self.isVisible():
                self.show_toast(message)
            else:
                try:
                    self.tray_icon.showMessage(
                        "Мои Заметки",
                        message,
                        QSystemTrayIcon.Information,
                        3000,
                    )
                except Exception:
                    pass

    def translate_layout_only(self) -> None:
        self._apply_text_transform(
            self._convert_layout_text, "Текст в буфере переведен (раскладка)"
        )

    def translate_case_only(self) -> None:
        self._apply_text_transform(
            self._swap_case_text, "Регистр текста в буфере изменен"
        )

    def switch_keyboard_layout(self) -> None:
        cursor = self.text_edit.textCursor()
        if not cursor.hasSelection():
            return

        text = cursor.selectedText()
        if not text:
            return

        converted = self._convert_layout_text(text)
        if not converted or converted == text:
            return

        self._replace_selection_with_text(cursor, converted)
        self.record_state_for_undo()

        try:
            self.show_toast("Раскладка выделения изменена")
        except Exception:
            pass

    def _apply_selection_transform(
        self, transform: Callable[[str], str], message: str
    ) -> None:
        cursor = self.text_edit.textCursor()
        if not cursor.hasSelection():
            return
        text = cursor.selectedText()
        converted = transform(text)
        self._replace_selection_with_text(cursor, converted)
        self.record_state_for_undo()
        if self.isVisible():
            self.show_toast(message)

    def translate_layout_selection(self) -> None:
        self._apply_selection_transform(
            self._convert_layout_text, "Раскладка выделения изменена"
        )

    def translate_case_selection(self) -> None:
        self._apply_selection_transform(
            self._swap_case_text, "Регистр выделения изменен"
        )
