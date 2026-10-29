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
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextListFormat,
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
        self.text_edit.setCurrentFont(font)

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
            f = QFont(font_family)
            fmt.setFont(f)
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

    def insert_horizontal_line(self) -> None:
        cursor = self.text_edit.textCursor()
        cursor.beginEditBlock()
        cursor.insertHtml("<hr style='border:1px solid #888; margin:0;'>")
        cursor.endEditBlock()
        self.text_edit.setTextCursor(cursor)

    def insert_audio_link(self, filepath: str) -> None:
        filename = os.path.basename(filepath)
        file_url = QUrl.fromLocalFile(os.path.abspath(filepath)).toString()
        self.text_edit.insertHtml(f'📄 <a href="{file_url}">{filename}</a>')
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
            fmt = cursor.charFormat()
            if not fmt.isAnchor():
                return None
            href = fmt.anchorHref()
            c = QTextCursor(cursor)
            max_steps = cursor.document().characterCount() + 5
            steps = 0
            while steps < max_steps:
                steps += 1
                left = QTextCursor(c)
                moved = left.movePosition(QTextCursor.Left, QTextCursor.KeepAnchor, 1)
                if (not moved) or left.atStart():
                    break
                f = left.charFormat()
                if not (f.isAnchor() and f.anchorHref() == href):
                    break
                if left.position() == c.position() and left.anchor() == c.anchor():
                    break
                c = left
            while steps < max_steps:
                steps += 1
                right = QTextCursor(c)
                moved = right.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, 1)
                if (not moved) or right.atEnd():
                    break
                f = right.charFormat()
                if not (f.isAnchor() and f.anchorHref() == href):
                    break
                if right.position() == c.position() and right.anchor() == c.anchor():
                    break
                c = right
            return c

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
        if c.hasSelection():
            c.mergeBlockFormat(bf)
            c.mergeCharFormat(ch)
        else:
            te.setCurrentCharFormat(ch)
            c.mergeBlockFormat(bf)
        te.setTextCursor(c)
