"""EditorMixin: форматирование текста и вставка форматных конструкций.

Символьное (жирный/курсив/подчёркивание/зачёркивание, шрифт, размер, цвета),
абзацное (выравнивание, заголовки, списки) и вставка (checkbox, линия,
таблица, ссылка, audio-ссылка, update-блок) + работа со ссылками.

Вырезано из NotesApp (step 4.12). Апстрим (_set_unsaved, save_note,
save_note_quiet) остаётся в NotesApp и доступен через self. Раскладка/регистр,
undo/redo и eventFilter НЕ входят сюда — остаются в ядре.
"""

import html as html_lib
import os
import re

from PySide6.QtCore import (
    QDateTime,
    QUrl,
    Qt,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextListFormat,
    QTextLength,
    QTextTableFormat,
    QTextTableCellFormat,
)
from PySide6.QtWidgets import (
    QColorDialog,
    QInputDialog,
    QMessageBox,
    QTextBrowser,
)


class EditorMixin:
    def _strip_default_font_styles(self, html: str) -> str:
        if not html:
            return ""
        html = re.sub(
            r'font-family\s*:\s*(?:["\']?\s*Times New Roman\s*["\']?)\s*;?',
            "",
            html,
            flags=re.IGNORECASE,
        )
        html = re.sub(
            r'font-size\s*:\s*14(?:\.0+)?pt\s*;?',
            "",
            html,
            flags=re.IGNORECASE,
        )
        html = re.sub(
            r'font-size\s*:\s*14(?:\.0+)?px\s*;?',
            "",
            html,
            flags=re.IGNORECASE,
        )
        html = re.sub(r'\sstyle="\s*"', "", html, flags=re.IGNORECASE)
        html = re.sub(r"\sstyle='\s*'", "", html, flags=re.IGNORECASE)
        return html

    def insert_update_block(self) -> None:
        if not self.current_note:
            return

        now = QDateTime.currentDateTime()
        date_str = now.toString("dd.MM.yyyy")
        cursor = self.text_edit.textCursor()

        html = (
            f"<b>UPD [{date_str}]</b><br>"
            f"<b>Base:</b> <br>"
            f"<b>User:</b> <br>"
            f"<b>Result:</b> <br>"
            f"<b>Details:</b> <br><br>"
        )
        cursor.insertHtml(html)
        self.text_edit.setTextCursor(cursor)
        self.text_edit.setFocus()

    def _apply_default_doc_font_fallback(self) -> None:
        f = QFont("Times New Roman", 14)
        doc = self.text_edit.document()
        doc.setDefaultFont(f)
        self.text_edit.setFont(f)
        self.text_edit.setCurrentFont(f)
        self.text_edit.setFontPointSize(14)

    def align_left(self) -> None:
        self.text_edit.setAlignment(Qt.AlignLeft)

    def align_center(self) -> None:
        self.text_edit.setAlignment(Qt.AlignCenter)

    def align_right(self) -> None:
        self.text_edit.setAlignment(Qt.AlignRight)

    def align_justify(self) -> None:
        self.text_edit.setAlignment(Qt.AlignJustify)

    def _force_default_note_font(self) -> None:
        f = QFont("Times New Roman", 14)
        self.text_edit.setCurrentFont(f)
        self.text_edit.setFontPointSize(14)

    def change_font(self, font: QFont) -> None:
        # This is the connected QFontComboBox callback, not set_font_family.
        # Apply only the family to preserve font size and selected styles.
        self.set_font_family(font.family())

    def change_font_size(self, size: int) -> None:
        try:
            fmt = QTextCharFormat()
            fmt.setFontPointSize(float(size))
            cur = self.text_edit.textCursor()
            if cur.hasSelection():
                cur.mergeCharFormat(fmt)
            elif getattr(self, "_last_selection", None):
                max_pos = max(0, self.text_edit.document().characterCount() - 1)
                start, end = self._last_selection
                start = max(0, min(start, max_pos))
                end = max(0, min(end, max_pos))
                doc_cursor = QTextCursor(self.text_edit.document())
                doc_cursor.setPosition(start)
                doc_cursor.setPosition(end, QTextCursor.KeepAnchor)
                doc_cursor.mergeCharFormat(fmt)
            else:
                cur_fmt = self.text_edit.currentCharFormat()
                cur_fmt.merge(fmt)
                self.text_edit.setCurrentCharFormat(cur_fmt)
                try:
                    if hasattr(self, "text_edit") and getattr(self.text_edit, "set_default_font_size", None):
                        self.text_edit.set_default_font_size(int(size))
                except Exception:
                    pass
            self.update_font_controls()
            self._set_unsaved(True)
            if getattr(self, "autosave_enabled", False):
                if hasattr(self, "save_note_quiet"):
                    self.save_note_quiet(force=True)
        except Exception:
            pass

    def _current_font_size(self, cursor: QTextCursor) -> float:
        size = cursor.charFormat().fontPointSize()
        if not size:
            size = self.text_edit.fontPointSize() or 14
        return size

    def toggle_bold(self) -> None:
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            current_format = cursor.charFormat()
            fmt = QTextCharFormat()
            new_weight = (
                QFont.Normal
                if current_format.fontWeight() == QFont.Bold
                else QFont.Bold
            )
            fmt.setFontWeight(new_weight)
            cursor.mergeCharFormat(fmt)
        else:
            fmt = self.text_edit.currentCharFormat()
            new_weight = QFont.Normal if fmt.fontWeight() == QFont.Bold else QFont.Bold
            fmt.setFontWeight(new_weight)
            self.text_edit.setCurrentCharFormat(fmt)

    def toggle_italic(self) -> None:
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            current_format = cursor.charFormat()
            fmt = QTextCharFormat()
            fmt.setFontItalic(not current_format.fontItalic())
            cursor.mergeCharFormat(fmt)
        else:
            fmt = self.text_edit.currentCharFormat()
            fmt.setFontItalic(not fmt.fontItalic())
            self.text_edit.setCurrentCharFormat(fmt)

    def toggle_underline(self) -> None:
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            current_format = cursor.charFormat()
            fmt = QTextCharFormat()
            fmt.setFontUnderline(not current_format.fontUnderline())
            cursor.mergeCharFormat(fmt)
        else:
            fmt = self.text_edit.currentCharFormat()
            fmt.setFontUnderline(not fmt.fontUnderline())
            self.text_edit.setCurrentCharFormat(fmt)

    def change_text_color(self) -> None:
        color = QColorDialog.getColor(Qt.black, self.text_edit, "Выберите цвет текста")
        if color.isValid():
            cursor = self.text_edit.textCursor()
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            if cursor.hasSelection():
                cursor.mergeCharFormat(fmt)
            else:
                self.text_edit.setCurrentCharFormat(fmt)

    def change_background_color(self) -> None:
        color = QColorDialog.getColor(Qt.white, self.text_edit, "Выберите цвет фона")
        if color.isValid():
            cursor = self.text_edit.textCursor()
            fmt = QTextCharFormat()
            fmt.setBackground(color)
            if cursor.hasSelection():
                cursor.mergeCharFormat(fmt)
            else:
                self.text_edit.setCurrentCharFormat(fmt)

    def clear_formatting_complete(self) -> None:
        cursor = self.text_edit.textCursor()
        fmt = QTextCharFormat()
        f = QFont("Times New Roman", 14)
        fmt.setFont(f)
        fmt.setFontPointSize(14)
        fmt.setFontWeight(QFont.Normal)
        fmt.setFontItalic(False)
        fmt.setFontUnderline(False)
        fmt.setFontStrikeOut(False)
        fmt.clearForeground()
        fmt.clearBackground()
        if cursor.hasSelection():
            cursor.mergeCharFormat(fmt)
        else:
            self.text_edit.setCurrentCharFormat(fmt)

    def apply_formatting(self, **kwargs) -> None:
        cursor = self.text_edit.textCursor()
        fmt = QTextCharFormat()
        for key, value in kwargs.items():
            if key == "bold":
                fmt.setFontWeight(QFont.Bold if value else QFont.Normal)
            elif key == "italic":
                fmt.setFontItalic(value)
            elif key == "underline":
                fmt.setFontUnderline(value)
            elif key == "color":
                fmt.setForeground(QColor(value))
            elif key == "background":
                fmt.setBackground(QColor(value))
            elif key == "font_size":
                try:
                    fmt.setFontPointSize(float(value))
                except Exception:
                    pass
        if cursor.hasSelection():
            cursor.mergeCharFormat(fmt)
        else:
            self.text_edit.setCurrentCharFormat(fmt)

    def update_font_controls(self) -> None:
        cursor = self.text_edit.textCursor()
        fmt = cursor.charFormat()
        font = fmt.font()
        family = font.family() if font.family() else "Times New Roman"
        size = int(font.pointSize() if font.pointSize() > 0 else 14)
        self.font_combo.blockSignals(True)
        self.font_combo.setCurrentFont(QFont(family))
        self.font_combo.blockSignals(False)
        self.font_size_spin.blockSignals(True)
        self.font_size_spin.setValue(size)
        self.font_size_spin.blockSignals(False)
        self._update_paragraph_spacing_controls()

    # QTextBlockFormat supports paragraph-level spacing in native Qt HTML.
    # Keep these settings in each affected block instead of QSettings, so
    # they survive note save/reopen and encrypted cross-device sync.
    LINE_SPACING_CHOICES = (1.0, 1.15, 1.5, 2.0)
    PARAGRAPH_AFTER_CHOICES = (0, 4, 8, 12)

    def set_paragraph_line_spacing(self, multiplier: float) -> None:
        value = float(multiplier)
        if value not in self.LINE_SPACING_CHOICES:
            raise ValueError("Unsupported line spacing")
        cursor = self.text_edit.textCursor()
        delta = QTextBlockFormat()
        delta.setLineHeight(float(round(value * 100)), QTextBlockFormat.ProportionalHeight.value)
        cursor.beginEditBlock()
        try:
            cursor.mergeBlockFormat(delta)
        finally:
            cursor.endEditBlock()
        self.text_edit.setTextCursor(cursor)
        self._set_unsaved(True)
        self.update_font_controls()

    def set_paragraph_after_spacing(self, points: int) -> None:
        value = int(points)
        if value not in self.PARAGRAPH_AFTER_CHOICES:
            raise ValueError("Unsupported paragraph spacing")
        cursor = self.text_edit.textCursor()
        delta = QTextBlockFormat()
        # QTextDocument/Qt uses real-valued layout units; convert pt to px
        # at the document's current DPI for correct visual measurements.
        dpi = self.text_edit.logicalDpiY()
        delta.setBottomMargin(float(value) * dpi / 72.0)
        cursor.beginEditBlock()
        try:
            cursor.mergeBlockFormat(delta)
        finally:
            cursor.endEditBlock()
        self.text_edit.setTextCursor(cursor)
        self._set_unsaved(True)
        self.update_font_controls()

    def _update_paragraph_spacing_controls(self) -> None:
        cursor = self.text_edit.textCursor()
        # For a multi-paragraph selection, sample the first selected block;
        # the active cursor may be at the trailing unselected boundary.
        if cursor.hasSelection():
            cursor.setPosition(cursor.selectionStart())
        fmt = cursor.blockFormat()
        line_type = fmt.lineHeightType()
        if line_type == QTextBlockFormat.ProportionalHeight.value:
            line_ratio = fmt.lineHeight() / 100.0
        else:
            line_ratio = 1.0
        if hasattr(self, "line_spacing_combo"):
            combo = self.line_spacing_combo
            index = min(
                range(combo.count()),
                key=lambda i: abs(float(combo.itemData(i)) - line_ratio),
            )
            combo.blockSignals(True)
            combo.setCurrentIndex(index)
            combo.blockSignals(False)
        if hasattr(self, "paragraph_after_combo"):
            combo = self.paragraph_after_combo
            dpi = max(1, self.text_edit.logicalDpiY())
            margin_pt = fmt.bottomMargin() * 72.0 / dpi
            index = min(
                range(combo.count()),
                key=lambda i: abs(float(combo.itemData(i)) - margin_pt),
            )
            combo.blockSignals(True)
            combo.setCurrentIndex(index)
            combo.blockSignals(False)

    def get_current_formatting(self):
        cursor = self.text_edit.textCursor()
        fmt = (
            cursor.charFormat()
            if cursor.hasSelection()
            else self.text_edit.currentCharFormat()
        )
        return {
            "bold": fmt.fontWeight() == QFont.Bold,
            "italic": fmt.fontItalic(),
            "underline": fmt.fontUnderline(),
            "color": fmt.foreground().color(),
            "background": fmt.background().color(),
            "font_size": fmt.fontPointSize(),
        }

    def set_font_family(self, font_family: str) -> None:
        try:
            fmt = QTextCharFormat()
            # Change only the family. setFont(QFont(family)) also sets the
            # QFont default point size (12), unintentionally erasing 18 pt,
            # italic, weight and other formatting on the selected text.
            fmt.setFontFamilies([font_family])
            cur = self.text_edit.textCursor()
            if cur.hasSelection():
                cur.mergeCharFormat(fmt)
            elif getattr(self, "_last_selection", None):
                max_pos = max(0, self.text_edit.document().characterCount() - 1)
                start, end = self._last_selection
                start = max(0, min(start, max_pos))
                end = max(0, min(end, max_pos))
                doc_cursor = QTextCursor(self.text_edit.document())
                doc_cursor.setPosition(start)
                doc_cursor.setPosition(end, QTextCursor.KeepAnchor)
                doc_cursor.mergeCharFormat(fmt)
            else:
                cur_fmt = self.text_edit.currentCharFormat()
                cur_fmt.merge(fmt)
                self.text_edit.setCurrentCharFormat(cur_fmt)
            self.update_font_controls()
            self._set_unsaved(True)
            if getattr(self, "autosave_enabled", False):
                if hasattr(self, "save_note_quiet"):
                    self.save_note_quiet(force=True)
        except Exception:
            pass

    def toggle_strikethrough(self) -> None:
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            current_format = cursor.charFormat()
            fmt = QTextCharFormat()
            fmt.setFontStrikeOut(not current_format.fontStrikeOut())
            cursor.mergeCharFormat(fmt)
        else:
            fmt = self.text_edit.currentCharFormat()
            fmt.setFontStrikeOut(not fmt.fontStrikeOut())
            self.text_edit.setCurrentCharFormat(fmt)

    def _ensure_heading_ids(self, view: QTextBrowser):
        html = view.toHtml()

        def slugify(text: str) -> str:
            s = text.strip().lower()
            s = re.sub(r"[^0-9a-zа-яё \-]+", "", s, flags=re.IGNORECASE)
            s = re.sub(r"\s+", "-", s)
            s = re.sub(r"-{2,}", "-", s)
            return s.strip("-")

        def repl(m):
            tag, attrs, inner = m.group(1), m.group(2), m.group(3)
            if re.search(r"\b(id|name)\s*=", attrs, flags=re.I):
                return m.group(0)
            text_only = re.sub(r"<[^>]*>", "", inner)
            anchor = slugify(text_only)
            if not anchor:
                return m.group(0)
            return f'<{tag}{attrs} id="{anchor}" name="{anchor}">{inner}</{tag}>'

        html = re.sub(r"<(h[1-6])([^>]*)>(.*?)</\1>", repl, html, flags=re.I | re.S)
        view.setHtml(html)
        base = view.document().baseUrl()
        view.document().setBaseUrl(base)
        view.setOpenLinks(False)
        view.setOpenExternalLinks(False)

    def _linkify_urls_in_browser(self, view: QTextBrowser):
        html = view.toHtml()
        pattern = re.compile(r'(?<!href=")(?<!src=")((?:https?://|www\.)[^\s"<>]+)')

        def repl(m):
            url = m.group(1)
            href = url if url.startswith(("http://", "https://")) else f"http://{url}"
            return f'<a href="{href}">{url}</a>'

        html = pattern.sub(repl, html)
        view.setHtml(html)
        view.setOpenExternalLinks(True)
        view.setOpenLinks(False)

    def apply_heading(self, level: int) -> None:
        cursor = self.text_edit.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.WordUnderCursor)
        fmt = QTextCharFormat()
        size_map = {1: 24, 2: 18, 3: 14}
        fmt.setFontPointSize(size_map.get(level, 12))
        fmt.setFontWeight(QFont.Bold)
        cursor.mergeCharFormat(fmt)

    def insert_list(self, style: QTextListFormat.Style) -> None:
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            selection_start = cursor.selectionStart()
            selection_end = cursor.selectionEnd()
            cursor.setPosition(selection_start)
            cursor.setPosition(selection_end, QTextCursor.KeepAnchor)
            block_format = QTextListFormat()
            block_format.setStyle(style)
            cursor.createList(block_format)
        else:
            if style == QTextListFormat.ListDisc:
                cursor.insertText("• ", self.text_edit._default_char_format())
            elif style == QTextListFormat.ListDecimal:
                cursor.insertText("1. ", self.text_edit._default_char_format())

    def insert_bullet_list(self) -> None:
        self.insert_list(QTextListFormat.ListDisc)

    def insert_numbered_list(self) -> None:
        self.insert_list(QTextListFormat.ListDecimal)

    def insert_checkbox(self) -> None:
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            selection_start = cursor.selectionStart()
            selection_end = cursor.selectionEnd()

            doc = self.text_edit.document()
            start_block = doc.findBlock(selection_start)
            end_block = doc.findBlock(selection_end)

            block = start_block
            while True:
                block_cursor = QTextCursor(block)
                block_cursor.movePosition(QTextCursor.StartOfBlock)
                block_cursor.movePosition(QTextCursor.Right, QTextCursor.MoveAnchor, 0)
                text = block.text()
                if text.strip() and not (
                    text.startswith("☐ ") or text.startswith("☑ ")
                ):
                    block_cursor.insertText("☐ ", self.text_edit._default_char_format())
                if block == end_block:
                    break
                block = block.next()
        else:
            cursor.movePosition(QTextCursor.StartOfLine)
            text = cursor.block().text()
            if not (text.startswith("☐ ") or text.startswith("☑ ")):
                cursor.insertText("☐ ", self.text_edit._default_char_format())
                cursor.movePosition(QTextCursor.Right, QTextCursor.MoveAnchor, 2)
                self.text_edit.setTextCursor(cursor)
                self.text_edit.setFocus()

    def toggle_checkbox_at_cursor(self) -> None:
        """Переключает чекбокс с использованием истории NotesApp.

        В приложении Qt Undo отключён; поэтому фиксируем оба состояния
        в собственной истории заметки, а не полагаемся на QTextEdit.undo().
        """
        self.record_state_for_undo()
        cursor = self.text_edit.textCursor()
        block = cursor.block()
        text = block.text()
        if text.startswith("☐ ") or text.startswith("☑ "):
            replacement = "☑" if text.startswith("☐ ") else "☐"
            toggle = QTextCursor(block)
            toggle.beginEditBlock()
            toggle.setPosition(block.position())
            toggle.setPosition(block.position() + 1, QTextCursor.KeepAnchor)
            toggle.insertText(replacement)
            toggle.endEditBlock()
        else:
            self.insert_checkbox()
        self.record_state_for_undo()
        self.text_edit.setFocus()

    def _insert_visible_horizontal_rule(self, cursor: QTextCursor) -> None:
        """Draw a visible text-based rule without Qt HTML/table rendering.

        The application's editor uses NoWrap. Calculate the number of
        box-drawing characters from the actual viewport and fixed-width
        font, so the rule is unmistakable even in the dark theme. A stored
        rule is ordinary rich text and survives Qt HTML round trips.
        """
        if cursor.hasSelection():
            cursor.setPosition(cursor.selectionEnd())
        block = cursor.block()
        legacy_dot = (
            block.isValid()
            and block.text().strip() == "."
            and cursor.currentTable() is None
            and cursor.currentList() is None
        )
        if legacy_dot:
            cursor.setPosition(block.position())
            cursor.setPosition(
                block.position() + len(block.text()), QTextCursor.KeepAnchor
            )
            cursor.removeSelectedText()
        elif cursor.block().text():
            # Reserve a dedicated paragraph for the divider. Splitting in
            # the middle of a text block leaves a nonempty suffix; splitting
            # at the beginning produces an empty block BEFORE that suffix.
            if cursor.positionInBlock():
                cursor.insertBlock()
            if cursor.block().text():
                cursor.insertBlock()
                cursor.movePosition(QTextCursor.PreviousBlock)

        line_font = QFont("Consolas", 11)
        line_metrics = QFontMetrics(line_font)
        char_width = max(1, line_metrics.horizontalAdvance("─"))
        document_margin = self.text_edit.document().documentMargin()
        usable_width = max(
            120, self.text_edit.viewport().width() - 2 * document_margin - 16
        )
        characters = max(12, min(360, int(usable_width / char_width)))
        rule_format = QTextCharFormat()
        rule_format.setFont(line_font)
        rule_format.setForeground(QColor("#a9a9a9"))

        original_format = QTextCharFormat(cursor.charFormat())
        cursor.insertText("─" * characters, rule_format)
        # When replacing an old standalone dot (or inserting into an
        # existing blank paragraph), the next paragraph already exists.
        # insertBlock() in that case created an extra empty line between
        # the divider and the heading. Reuse the existing next paragraph.
        if cursor.block().next().isValid():
            cursor.movePosition(QTextCursor.NextBlock)
        else:
            cursor.insertBlock()
        cursor.setCharFormat(original_format)

    def insert_horizontal_line(self) -> None:
        """Insert a visible divider or replace the selected legacy dot."""
        cursor = self.text_edit.textCursor()
        cursor.beginEditBlock()
        try:
            self._insert_visible_horizontal_rule(cursor)
        finally:
            cursor.endEditBlock()
        self.text_edit.setTextCursor(cursor)
        self.text_edit.setFocus()
        if hasattr(self, "_set_unsaved"):
            self._set_unsaved(True)

    def restore_legacy_horizontal_lines(self) -> None:
        """Explicitly repair old divider dots and redundant post-rule gaps.

        Changing stored user notes automatically would be unsafe: a dot or
        intentional blank paragraph may be part of the user's text. This
        action requires confirmation and only edits the current document.
        """
        document = self.text_edit.document()
        operations = []
        dot_count = 0
        extra_gap_count = 0
        block = document.begin()
        while block.isValid():
            probe = QTextCursor(block)
            in_table_or_list = (
                probe.currentTable() is not None
                or probe.currentList() is not None
            )
            if not in_table_or_list and block.text().strip() == ".":
                operations.append((block.position(), "dot"))
                dot_count += 1
            elif not in_table_or_list:
                rule = block.text().strip()
                next_block = block.next()
                if (
                    len(rule) >= 12
                    and set(rule) == {"─"}
                    and next_block.isValid()
                    and not next_block.text()
                    and next_block.next().isValid()
                    and next_block.next().text().strip()
                ):
                    # Delete the separator between the rule and the empty
                    # block. This removes the redundant block without
                    # merging into or reformatting the next heading.
                    operations.append((block.position() + len(block.text()), "gap"))
                    extra_gap_count += 1
            block = block.next()
        if not operations:
            QMessageBox.information(
                self, "Горизонтальные линии",
                "В текущей заметке нет старых точек или лишних пустых строк "
                "сразу после горизонтальных линий.",
            )
            return
        reply = QMessageBox.question(
            self, "Восстановить горизонтальные линии",
            f"Старых точек: {dot_count}.\n"
            f"Пустых строк после линий: {extra_gap_count}.\n"
            "Восстановить разделители и убрать указанные пустые строки?\n"
            "Это изменит только текущую заметку. Остальной текст сохранится.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        cursor = self.text_edit.textCursor()
        cursor.beginEditBlock()
        try:
            # Edits from end to start preserve positions of earlier blocks.
            for position, action in sorted(operations, reverse=True):
                cursor.setPosition(position)
                if action == "gap":
                    cursor.deleteChar()
                else:
                    self._insert_visible_horizontal_rule(cursor)
        finally:
            cursor.endEditBlock()
        self.text_edit.setTextCursor(cursor)
        self.text_edit.setFocus()
        if hasattr(self, "_set_unsaved"):
            self._set_unsaved(True)

    def insert_audio_link(self, filepath: str) -> None:
        filename = os.path.basename(filepath)
        file_url = QUrl.fromLocalFile(os.path.abspath(filepath)).toString()
        self.text_edit.insertHtml(
            f'📄 <a href="{html_lib.escape(file_url, quote=True)}">'
            f'{html_lib.escape(filename)}</a>'
        )
        self.save_note()

    def insert_link(self) -> None:
        cursor = self.text_edit.textCursor()
        url, ok = QInputDialog.getText(self, "Вставить ссылку", "URL:")
        if not (ok and url):
            return
        url = url.strip()
        href = url
        if os.path.isabs(url) or os.path.exists(url):
            href = QUrl.fromLocalFile(os.path.abspath(url)).toString()
        else:
            if not re.match(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://", url):
                href = "https://" + url
        fmt = QTextCharFormat()
        fmt.setAnchor(True)
        fmt.setAnchorHref(href)
        fmt.setForeground(Qt.blue)
        fmt.setFontUnderline(True)
        fmt.setFont(QFont("Times New Roman", 14))

        if cursor.hasSelection() and cursor.selectedText().strip():
            cursor.mergeCharFormat(fmt)
        else:
            fmt.setFont(QFont("Times New Roman", 14))
            cursor.insertText(url, fmt)

    def _select_entire_anchor(self, cursor: QTextCursor) -> QTextCursor | None:
        """Select the complete link, including its first and last character.

        QTextCursor.charFormat() refers to the character before the cursor,
        so probing document positions precisely avoids truncating links at
        paragraph boundaries or accidentally selecting neighboring text.
        """
        doc = cursor.document()
        maximum = doc.characterCount() - 1

        def href_at(char_index: int) -> str | None:
            if char_index < 0 or char_index >= maximum:
                return None
            probe = QTextCursor(doc)
            probe.setPosition(char_index + 1)
            fmt = probe.charFormat()
            return fmt.anchorHref() if fmt.isAnchor() else None

        point = cursor.selectionStart() if cursor.hasSelection() else cursor.position()
        href = href_at(point) or href_at(point - 1)
        if not href:
            return None
        start = point
        while start > 0 and href_at(start - 1) == href:
            start -= 1
        end = point
        while end < maximum and href_at(end) == href:
            end += 1
        if start >= end:
            return None
        selected = QTextCursor(doc)
        selected.setPosition(start)
        selected.setPosition(end, QTextCursor.KeepAnchor)
        return selected

    def edit_link(self) -> None:
        cursor = self.text_edit.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.WordUnderCursor)
        if not cursor.charFormat().isAnchor():
            QMessageBox.information(self, "Ссылка", "Курсор не находится на ссылке.")
            return
        full = self._select_entire_anchor(cursor)
        if not full:
            return
        fmt = full.charFormat()
        old_url = fmt.anchorHref()
        new_url, ok = QInputDialog.getText(
            self, "Изменить ссылку", "URL:", text=old_url
        )
        if not (ok and new_url):
            return
        visible = full.selectedText()
        if visible.strip() == old_url.strip() or re.match(
            r"^\s*(https?://|www\.)", visible, flags=re.I
        ):
            new_visible = new_url
        else:
            new_visible = visible
        fmt.setAnchor(True)
        fmt.setAnchorHref(new_url)
        full.insertText(new_visible, fmt)

    def remove_link(self) -> None:
        cursor = self.text_edit.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.WordUnderCursor)
        fmt = QTextCharFormat(cursor.charFormat())
        fmt.setAnchor(False)
        fmt.setAnchorHref("")
        fmt.setForeground(self.text_edit.palette().text())
        fmt.setFontUnderline(False)
        cursor.mergeCharFormat(fmt)

    def insert_table(self) -> None:
        if not self.current_note:
            QMessageBox.warning(
                self, "Нет заметки", "Сначала выбери или создай заметку."
            )
            return
        cursor = self.text_edit.textCursor()
        has_sel = cursor.hasSelection()
        default_rows = 1 if has_sel else 2
        default_cols = 1 if has_sel else 2
        rows, ok1 = QInputDialog.getInt(
            self, "Вставить таблицу", "Количество строк:", default_rows, 1, 100
        )
        cols, ok2 = QInputDialog.getInt(
            self, "Вставить таблицу", "Количество столбцов:", default_cols, 1, 100
        )
        if not (ok1 and ok2):
            return
        is_dark = self.settings.value("theme", "dark") == "dark"
        border_color = "white" if is_dark else "black"
        selected_html = None
        if has_sel:
            sel_text = cursor.selectedText()
            selected_html = html_lib.escape(sel_text).replace("\u2029", "<br/>")
        rows_html = []
        for r in range(rows):
            cells_html = []
            for c in range(cols):
                if r == 0 and c == 0 and selected_html is not None:
                    cell_content = selected_html
                else:
                    cell_content = "&nbsp;"
                cells_html.append(
                    f"<td style=\'min-width:1em; padding:3px; border:1px solid {border_color}; font-family:Times New Roman; font-size:14pt;\'>{cell_content}</td>"
                )
            rows_html.append("<tr>" + "".join(cells_html) + "</tr>")
        table_html = (
            f"<table border='1' cellspacing='0' cellpadding='3' "
            f"style=\'border-collapse:collapse; border:1px solid {border_color}; font-family:Times New Roman; font-size:14pt;\'>"
            + "".join(rows_html)
            + "</table>"
        )
        cursor.beginEditBlock()
        if has_sel:
            cursor.removeSelectedText()
        cursor.insertHtml(table_html)
        cursor.endEditBlock()

    def clear_formatting(self):
        te = self.text_edit
        c = te.textCursor()
        ch = QTextCharFormat()
        f = QFont("Times New Roman", 14)
        ch.setFont(f)
        ch.setFontWeight(QFont.Normal)
        ch.setFontItalic(False)
        ch.setFontUnderline(False)
        ch.setFontStrikeOut(False)
        ch.setForeground(QBrush())
        ch.setBackground(QBrush())
        bf = QTextBlockFormat()
        bf.setHeadingLevel(0)
        # "Reset formatting" must also clear the new paragraph settings;
        # leaving custom line-height / bottom margin behind was surprising.
        bf.setLineHeight(0, QTextBlockFormat.SingleHeight.value)
        bf.setBottomMargin(0.0)
        if c.hasSelection():
            c.mergeBlockFormat(bf)
            c.mergeCharFormat(ch)
        else:
            te.setCurrentCharFormat(ch)
            c.mergeBlockFormat(bf)
        te.setTextCursor(c)
