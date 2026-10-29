"""Основной редактор форматированного текста (QTextEdit)."""

from PySide6.QtCore import (
    Qt,
    QMimeData,
    QUrl,
    QEvent,
)

from PySide6.QtGui import (
    QBrush,
    QTextTableCellFormat,
    QTextFrameFormat,
    QDragEnterEvent,
    QDropEvent,
    QTextTableFormat,
    QMouseEvent,
    QContextMenuEvent,
    QPainterPath,
    QFont,
    QPixmap,
    QDrag,
    QAction,
    QPen,
    QColor,
    QTextCharFormat,
    QDesktopServices,
    QTextCursor,
    QPainter,
)

from PySide6.QtWidgets import (
    QApplication,
    QTextEdit,
    QWidget,
    QMessageBox,
    QMenu,
)

from typing import Callable
from urllib.parse import quote
from urllib.parse import unquote
import base64
import difflib
import html as html_lib
import os
import re
import sys
import tempfile

from ..config import NOTES_DIR, USER_DICT_PATH
from ..utils import safe_folder_name
from ..constants import CUSTOM_MENU_STYLE


class CustomTextEdit(QTextEdit):
    DEFAULT_FONT_FAMILY = "Times New Roman"
    DEFAULT_FONT_SIZE_PT = 14

    def __init__(
        self,
        parent: QWidget | None = None,
        paste_image_callback: Callable | None = None,
    ):
        super().__init__(parent)
        self.paste_image_callback = paste_image_callback

        self.setFont(QFont(self.DEFAULT_FONT_FAMILY, self.DEFAULT_FONT_SIZE_PT))
        self.setCurrentFont(QFont(self.DEFAULT_FONT_FAMILY))
        self.setFontPointSize(self.DEFAULT_FONT_SIZE_PT)
        self.document().setDefaultFont(
            QFont(self.DEFAULT_FONT_FAMILY, self.DEFAULT_FONT_SIZE_PT)
        )
        self.setAcceptDrops(True)
        self._ensure_default_typing_format()

    def _default_char_format(self) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setFont(QFont(self.DEFAULT_FONT_FAMILY, self.DEFAULT_FONT_SIZE_PT))
        fmt.setFontPointSize(self.DEFAULT_FONT_SIZE_PT)
        return fmt

    def _strip_font_styles(self, html: str) -> str:
        if not html:
            return ""
        html = re.sub(r"font-family:[^;\"']*;?", "", html, flags=re.IGNORECASE)
        html = re.sub(r"font-size:[^;\"']*;?", "", html, flags=re.IGNORECASE)
        return html

    def _wrap_html_default(self, html: str, *, strip_fonts: bool = False) -> str:
        if strip_fonts:
            html = self._strip_font_styles(html)
        try:
            cur_fmt = self.currentCharFormat()
            font = cur_fmt.font()
            family = font.family() if (font and font.family()) else self.DEFAULT_FONT_FAMILY
            size = int(font.pointSize()) if (font and font.pointSize() > 0) else self.DEFAULT_FONT_SIZE_PT
        except Exception:
            family = self.DEFAULT_FONT_FAMILY
            size = self.DEFAULT_FONT_SIZE_PT
        if re.search(
            r"<\s*(table|div|p|ul|ol|li|h[1-6]|pre|blockquote)\b",
            html,
            flags=re.IGNORECASE,
        ):
            return (
                f"<div style=\"font-family:'{family}'; "
                f"font-size:{size}pt;\">{html}</div>"
            )
        return (
            f"<span style=\"font-family:'{family}'; "
            f"font-size:{size}pt;\">{html}</span>"
        )

    def _ensure_default_typing_format(self) -> None:
        try:
            cursor = self.textCursor()
            if cursor.hasSelection():
                return

            cur = QTextCharFormat(self.currentCharFormat())

            font = cur.font()

            family = ""
            try:
                family = font.family()
            except Exception:
                family = ""
            need_family = not (family or "").strip()
            need_size = cur.fontPointSize() <= 0

            if not (need_family or need_size):
                return

            if need_family:
                font.setFamily(self.DEFAULT_FONT_FAMILY)
            if need_size:
                font.setPointSize(self.DEFAULT_FONT_SIZE_PT)

            cur.setFont(font)
            self.setCurrentCharFormat(cur)
        except Exception:
            pass

    def set_default_font_size(self, size_pt: int) -> None:
        try:
            sz = max(1, int(size_pt))
        except Exception:
            return
        try:
            cur_fmt = QTextCharFormat(self.currentCharFormat())
            f = cur_fmt.font()
            f.setPointSize(sz)
            cur_fmt.setFont(f)
            self.setCurrentCharFormat(cur_fmt)
        except Exception:
            pass
        try:
            doc_font = QFont(self.DEFAULT_FONT_FAMILY, sz)
            self.document().setDefaultFont(doc_font)

            try:
                self.DEFAULT_FONT_SIZE_PT = sz
            except Exception:
                pass
        except Exception:
            pass

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)


    def insertPlainText(self, text: str) -> None:
        super().insertPlainText(text)

    def insertHtml(self, html: str) -> None:
        wrapped = self._wrap_html_default(html, strip_fonts=True)
        super().insertHtml(wrapped)

    def insertFromMimeData(self, source: QMimeData) -> None:
        if source.hasImage() and self.paste_image_callback:
            image = source.imageData()
            self.paste_image_callback(image)
            return

        if source.hasHtml():
            self.insertHtml(source.html())
            return
        prev_fmt = QTextCharFormat(self.currentCharFormat())
        try:
            forced = QTextCharFormat(prev_fmt)
            font = forced.font()
            font.setFamily(self.DEFAULT_FONT_FAMILY)
            font.setPointSize(self.DEFAULT_FONT_SIZE_PT)
            forced.setFont(font)
            self.setCurrentCharFormat(forced)

            super().insertFromMimeData(source)
        finally:
            try:
                self.setCurrentCharFormat(prev_fmt)
            except Exception:
                pass

    def _linkify_plain_text(self, text: str) -> str | None:
        if not text:
            return None
        token_re = re.compile(
            r"(?:https?://|ftp://)[^\s<>\"']+"
            r"|www\.[^\s<>\"']+"
            r"|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
            r"|[A-Za-z]:[\\/][^\s<>\"']+"
            r"|/[^\s<>\"']+"
        )
        found_any = False
        out_parts: list[str] = []
        pos = 0
        for m in token_re.finditer(text):
            if m.start() > pos:
                out_parts.append(html_lib.escape(text[pos : m.start()]))
            raw = m.group(0)
            href = None
            label = html_lib.escape(raw)
            if re.match(r"^(?:https?://|ftp://)", raw, flags=re.I):
                href = raw
            elif raw.lower().startswith("www."):
                href = "https://" + raw
            elif re.match(r"^[A-Za-z0-9._%+-]+@", raw):
                href = f"mailto:{raw}"
            elif os.path.isabs(raw):
                try:
                    href = QUrl.fromLocalFile(os.path.abspath(raw)).toString()
                except Exception:
                    href = "file://" + quote(os.path.abspath(raw))
            if href:
                found_any = True
                out_parts.append(
                    f'<a href="{html_lib.escape(href)}" style="text-decoration: underline;">{label}</a>'
                )
            else:
                out_parts.append(label)
            pos = m.end()
        if pos < len(text):
            out_parts.append(html_lib.escape(text[pos:]))
        if not found_any:
            return None
        html = "".join(out_parts).replace("\r\n", "<br>").replace("\n", "<br>")
        html = f"<span style=\"font-family:'Times New Roman'; font-size:14pt;\">{html}</span>"
        return html

    def ignore_in_this_note(self, word: str) -> None:
        mw = self.window()
        if hasattr(mw, "add_word_to_note_ignore"):
            mw.add_word_to_note_ignore(word)

    def copy_without_formatting(self) -> None:
        cur = self.textCursor()
        plain = (
            cur.selection().toPlainText() if cur.hasSelection() else self.toPlainText()
        )
        md = QMimeData()
        md.setText(self._sanitize_plain_for_copy(plain))
        QApplication.clipboard().setMimeData(md)

    def copy_with_formatting(self) -> None:
        md = self._build_rich_mime_from_selection()
        QApplication.clipboard().setMimeData(md)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            cursor = self.textCursor()
            block_text = cursor.block().text()
            normalized = block_text.lstrip("\u202a\u202c\ufeff\u200b\xa0 ").replace("\xa0", " ")
            m = re.match(r"^[☐☑][ \u00A0]", normalized)
            if m:
                after_marker = normalized[m.end():]
                if after_marker.strip() == "":
                    super().keyPressEvent(event)
                    return
                else:
                    super().keyPressEvent(event)
                    cursor = self.textCursor()
                    cursor.insertText("☐ ", self._default_char_format())
                    self.setTextCursor(cursor)
                    return
            b = normalized
            is_bullet = b.startswith("•") and (len(b) == 1 or b[1] == " ")
            if is_bullet:
                if b.strip() == "•":
                    cursor.beginEditBlock()
                    cursor.movePosition(QTextCursor.StartOfBlock)
                    rm_len = 2 if (len(b) >= 2 and b[1] == " ") else 1
                    cursor.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, rm_len)
                    cursor.removeSelectedText()
                    cursor.endEditBlock()
                    super().keyPressEvent(event)
                    return
                super().keyPressEvent(event)
                cursor = self.textCursor()
                cursor.insertText("• ", self._default_char_format())
                self.setTextCursor(cursor)
                return
            num_match = re.match(r"^(\d+)\.\s*", block_text.strip())
            if num_match:
                number = int(num_match.group(1))
                if re.fullmatch(rf"{number}\.\s*", block_text.strip()):
                    cursor.beginEditBlock()
                    cursor.movePosition(QTextCursor.StartOfBlock)
                    cursor.movePosition(
                        QTextCursor.Right,
                        QTextCursor.KeepAnchor,
                        len(num_match.group(0)),
                    )
                    cursor.removeSelectedText()
                    cursor.endEditBlock()

                    super().keyPressEvent(event)
                    return
                else:
                    super().keyPressEvent(event)
                    cursor = self.textCursor()
                    cursor.insertText(f"{number + 1}. ", self._default_char_format())
                    self.setTextCursor(cursor)
                    return

        super().keyPressEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                if os.path.isfile(file_path):
                    main_window = self.window()
                    if hasattr(main_window, "attach_file_to_note_external"):
                        main_window.attach_file_to_note_external(file_path)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def _open_any_link(self, link: str) -> bool:
        try:
            s = html_lib.unescape((link or "").strip())
            url = QUrl.fromUserInput(s)
            is_file_like = (url.scheme().lower() == "file") or re.match(
                r"^[a-zA-Z]:[\\/]", s
            )
            if is_file_like:
                if url.scheme().lower() == "file":
                    local_path = url.toLocalFile()
                    if not local_path:
                        raw_path = (
                            QUrl(s).path() if s.lower().startswith("file://") else s
                        )
                        raw_path = raw_path or ""
                        raw_path = unquote(raw_path).lstrip("/").replace("/", os.sep)
                        local_path = raw_path
                else:
                    local_path = s
                local_path = self._sanitize_windows_path(local_path)

                def try_open(p: str) -> bool:
                    exe_path = os.path.abspath(sys.argv[0])
                    abs_p = os.path.abspath(p)
                    exe_dir = os.path.dirname(exe_path)
                    ext = os.path.splitext(abs_p)[1].lower()
                    try:
                        same = os.path.samefile(abs_p, exe_path)
                    except Exception:
                        same = (abs_p == exe_path)
                    executable_like_exts = (".exe", ".bat", ".cmd", ".lnk", ".py", ".pyw")
                    is_executable_like = ext in executable_like_exts
                    if same or (abs_p.startswith(exe_dir + os.sep) and is_executable_like):
                        QMessageBox.information(
                            self,
                            "Открытие вложения",
                            (
                                "Запуск исполняемых файлов из вложений заблокирован,\n"
                                "чтобы не открывать само приложение NotesPM или "
                                "связанные исполняемые файлы."
                            ),
                        )
                        return False
                    if sys.platform.startswith("win"):
                        try:
                            os.startfile(p)
                            return True
                        except Exception:
                            pass
                    return QDesktopServices.openUrl(QUrl.fromLocalFile(p))
                if os.path.exists(local_path):
                    return try_open(local_path)
                lower = local_path.replace("/", os.sep).replace("\\", os.sep).lower()
                sep_notes = f"{os.sep}notes{os.sep}"
                if sep_notes in lower:
                    suffix = lower.split(sep_notes, 1)[1]
                    candidate = os.path.join(NOTES_DIR, suffix)
                    if os.path.exists(candidate):
                        return try_open(candidate)
                mw = self.window()
                if hasattr(mw, "current_note") and mw.current_note:
                    folder = safe_folder_name(
                        mw.current_note.title,
                        mw.current_note.uuid,
                        mw.current_note.timestamp,
                    )
                    candidate = os.path.join(
                        NOTES_DIR, folder, os.path.basename(local_path)
                    )
                    if os.path.exists(candidate):
                        return try_open(candidate)
                return try_open(local_path)
            if not url.scheme():
                url = QUrl.fromUserInput("https://" + s)
            return QDesktopServices.openUrl(url)
        except Exception:
            return False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        cursor = self.cursorForPosition(pos)
        char_format = cursor.charFormat()
        if event.button() == Qt.LeftButton:
            if char_format.isAnchor():
                link = char_format.anchorHref()
                if link.startswith("dropdown://"):
                    tail = link.split("://", 1)[1]
                    dd_id = tail.split("?", 1)[0].split("#", 1)[0]
                    main_window = self.window()
                    if hasattr(main_window, "show_dropdown_menu_for_token"):
                        rect = self.cursorRect(cursor)
                        global_pos = self.viewport().mapToGlobal(rect.bottomLeft())
                        main_window.show_dropdown_menu_for_token(dd_id, global_pos)
                    return
                if event.modifiers() & Qt.ControlModifier:
                    self._open_any_link(link)
                    return
                super().mousePressEvent(event)
                return
            if char_format.isImageFormat():
                if event.modifiers() & Qt.ControlModifier:
                    image_format = char_format.toImageFormat()
                    image_path = image_format.name()
                    if image_path.startswith("Data:image"):
                        header, b64data = image_path.split(",", 1)
                        suffix = ".png" if "png" in header else ".jpg"
                        with tempfile.NamedTemporaryFile(
                            delete=False, suffix=suffix
                        ) as tmpfile:
                            tmpfile.write(base64.b64decode(b64data))
                            tmpfile_path = tmpfile.name
                        QDesktopServices.openUrl(QUrl.fromLocalFile(tmpfile_path))
                    elif image_path.startswith("file://"):
                        file_path = QUrl(image_path).toLocalFile()
                        if os.path.exists(file_path):
                            self._open_any_link(image_path)
                else:
                    super().mousePressEvent(event)
                return
            if event.modifiers() & Qt.ControlModifier:
                block_cursor = self.cursorForPosition(pos)
                block_cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                block_html = block_cursor.selection().toHtml()
                m = re.search(r'href="((?:file|https?)://[^"]+)"', block_html)
                if m:
                    self._open_any_link(html_lib.unescape(m.group(1)))
                    return
            word_cursor = self.cursorForPosition(pos)
            word_cursor.select(QTextCursor.SelectionType.WordUnderCursor)
            word = word_cursor.selectedText()
            if word == "☐":
                word_cursor.insertText("☑", self._default_char_format())
                return
            elif word == "☑":
                word_cursor.insertText("☐", self._default_char_format())
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        cursor = self.cursorForPosition(pos)
        cf = cursor.charFormat()
        if cf.isAnchor():
            if event.modifiers() & Qt.ControlModifier:
                self._open_any_link(cf.anchorHref())
                return
            super().mouseDoubleClickEvent(event)
            return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        cf = self.cursorForPosition(pos).charFormat()
        if cf.isAnchor() and (event.modifiers() & Qt.ControlModifier):
            self.viewport().setCursor(Qt.PointingHandCursor)
        else:
            self.viewport().setCursor(Qt.IBeamCursor)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self.viewport().unsetCursor()
        super().leaveEvent(event)

    def create_drag_image(self, widget: QWidget) -> QPixmap:
        pixmap = widget.grab()
        scale_factor = 0.4
        scaled_pixmap = pixmap.scaled(
            pixmap.size() * scale_factor, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        painter = QPainter(scaled_pixmap)
        path = QPainterPath()
        path.addRect(0, 0, scaled_pixmap.width() - 1, scaled_pixmap.height() - 1)
        pen = QPen(QColor(0, 0, 0), 1)
        painter.setPen(pen)
        painter.drawPath(path)
        return scaled_pixmap

    def delete_selection(self) -> None:
        cursor = self.textCursor()
        if cursor.hasSelection():
            cursor.removeSelectedText()

    def replace_word(self, cursor: QTextCursor, new_word: str) -> None:
        cursor.beginEditBlock()
        cursor.removeSelectedText()
        cursor.insertText(new_word, self._default_char_format())
        cursor.endEditBlock()

    def add_to_dictionary(self, word: str) -> None:
        highlighter = getattr(self.window(), "spell_highlighter", None)
        if highlighter:
            highlighter.add_to_dictionary(word)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(CUSTOM_MENU_STYLE)
        undo_action = QAction("Undo", self)
        undo_action.setShortcut("Ctrl+Z")
        menu.addAction(undo_action)
        redo_action = QAction("Redo", self)
        redo_action.setShortcut("Ctrl+Y")
        undo_action.triggered.connect(
            lambda: self.window().undo() if hasattr(self.window(), "undo") else None
        )
        redo_action.triggered.connect(
            lambda: self.window().redo() if hasattr(self.window(), "redo") else None
        )
        menu.addAction(redo_action)
        menu.addSeparator()
        cut_action = QAction("Cut", self)
        cut_action.setShortcut("Ctrl+X")
        cut_action.triggered.connect(self.cut)
        menu.addAction(cut_action)
        copy_action = QAction("Copy", self)
        copy_action.setShortcut("Ctrl+C")
        copy_action.triggered.connect(self.copy)
        menu.addAction(copy_action)
        paste_action = QAction("Paste", self)
        paste_action.setShortcut("Ctrl+V")
        paste_action.triggered.connect(self.paste)
        menu.addAction(paste_action)
        delete_action = QAction("Delete", self)
        delete_action.triggered.connect(self.delete_selection)
        menu.addAction(delete_action)
        menu.addSeparator()
        self._inject_table_context_menu(menu, event.pos())
        menu.addSeparator()
        select_all_action = QAction("Select All", self)
        select_all_action.setShortcut("Ctrl+A")
        select_all_action.triggered.connect(self.selectAll)
        menu.addAction(select_all_action)
        menu.addSeparator()
        view_dict_action = QAction("View Dictionary", self)
        view_dict_action.triggered.connect(
            lambda checked=False: QDesktopServices.openUrl(
                QUrl.fromLocalFile(USER_DICT_PATH)
            )
        )
        menu.addAction(view_dict_action)
        word_cursor = self.cursorForPosition(event.pos())
        word_cursor.select(QTextCursor.WordUnderCursor)
        raw_word = word_cursor.selectedText()
        m = re.search(r"[A-Za-zА-Яа-яЁё']+", raw_word or "")
        if not m:
            menu.exec(self.mapToGlobal(event.pos()))
            return
        lw = m.group(0).lower()
        highlighter = getattr(self.window(), "spell_highlighter", None)
        user_candidates = []
        if highlighter and getattr(highlighter, "user_words", None):
            try:
                user_candidates = difflib.get_close_matches(
                    lw, list(highlighter.user_words), n=7, cutoff=0.6
                )
            except Exception:
                user_candidates = []
        spell_candidates = []
        try:
            # Подсказки от Hunspell (spylls) через хайлайтер. Считаем их только
            # для слов, которые хайлайтер считает неверными, чтобы не засорять
            # меню вариантами для корректно написанных слов.
            if highlighter and hasattr(highlighter, "suggest"):
                known = False
                try:
                    known = highlighter._is_known_local(lw)
                except Exception:
                    known = False
                if not known:
                    spell_candidates = highlighter.suggest(lw, limit=7)
        except Exception:
            spell_candidates = []
        doc_candidates = []
        try:
            plain = self.window().text_edit.toPlainText()
            tokens = set(w.lower() for w in re.findall(r"[A-Za-zА-Яа-яЁё']+", plain))
            if lw in tokens:
                tokens.discard(lw)
            sample = list(tokens)[:5000]
            doc_candidates = difflib.get_close_matches(lw, sample, n=7, cutoff=0.65)
        except Exception:
            doc_candidates = []

        def _clean(seq):
            seen = set()
            out = []
            for s in seq:
                if not s:
                    continue
                sl = s.lower()
                if sl == lw or sl in seen:
                    continue
                out.append(s)
                seen.add(sl)
                if len(out) >= 7:
                    break
            return out

        user_candidates = _clean(user_candidates)
        spell_candidates = _clean(spell_candidates)
        doc_candidates = _clean(doc_candidates)
        menu.addSeparator()
        copy_plain_action = QAction("Copy (without formatting)", self)
        copy_plain_action.triggered.connect(self.copy_without_formatting)
        copy_rich_action = QAction("Copy (with formatting)", self)
        copy_rich_action.triggered.connect(self.copy_with_formatting)
        menu.addAction(copy_plain_action)
        menu.addAction(copy_rich_action)
        menu.addSeparator()
        ignore_action = QAction("Ignore the word in the current note", self)
        ignore_action.triggered.connect(
            lambda checked=False, w=raw_word: self.ignore_in_this_note(w)
        )
        menu.addAction(ignore_action)
        add_dict_action = QAction("Add to Dictionary", self)
        add_dict_action.triggered.connect(
            lambda checked=False, w=raw_word: self.add_to_dictionary(w)
        )
        menu.addAction(add_dict_action)
        replace_menu = menu.addMenu("Replace")
        user_menu = replace_menu.addMenu("From your personal dictionary")
        if user_candidates:
            for s in user_candidates:
                act = user_menu.addAction(s)
                act.triggered.connect(
                    lambda _, s=s, c=QTextCursor(word_cursor): self.replace_word(c, s)
                )
        else:
            a = user_menu.addAction("— There are no options —")
            a.setEnabled(False)
        spell_menu = replace_menu.addMenu("Spelling options")
        if spell_candidates:
            for s in spell_candidates:
                act = spell_menu.addAction(s)
                act.triggered.connect(
                    lambda _, s=s, c=QTextCursor(word_cursor): self.replace_word(c, s)
                )
        else:
            a = spell_menu.addAction("— There are no options —")
            a.setEnabled(False)
        doc_menu = replace_menu.addMenu("From the current note")
        if doc_candidates:
            for s in doc_candidates:
                act = doc_menu.addAction(s)
                act.triggered.connect(
                    lambda _, s=s, c=QTextCursor(word_cursor): self.replace_word(c, s)
                )
        else:
            a = doc_menu.addAction("— There are no options —")
            a.setEnabled(False)
        menu.exec(self.mapToGlobal(event.pos()))

    def _current_table_pos(self):
        cur = self.textCursor()
        tbl = cur.currentTable()
        if not tbl:
            return None
        cell = tbl.cellAt(cur)
        if not cell.isValid():
            return None
        return tbl, cell.row(), cell.column()

    def _inject_table_context_menu(self, menu: QMenu, pos) -> None:
        cur = self.cursorForPosition(pos)
        tbl = cur.currentTable()
        if tbl:
            cell = tbl.cellAt(cur)
            if not cell.isValid():
                return
            r, c = cell.row(), cell.column()
            tmenu = menu.addMenu("Table")
            a_ins_row_above = tmenu.addAction("Вставить строку сверху")
            a_ins_row_below = tmenu.addAction("Вставить строку снизу")
            a_del_row = tmenu.addAction("Удалить текущую строку")
            tmenu.addSeparator()
            a_ins_col_left = tmenu.addAction("Вставить столбец слева")
            a_ins_col_right = tmenu.addAction("Вставить столбец справа")
            a_del_col = tmenu.addAction("Удалить текущий столбец")
            tmenu.addSeparator()
            a_split_h = tmenu.addAction("Разделить ячейку по горизонтали (2 строки)")
            a_split_v = tmenu.addAction("Разделить ячейку по вертикали (2 столбца)")
            a_merge = tmenu.addAction("Слить выделенные ячейки")
            tmenu.addSeparator()
            a_del_cell = tmenu.addAction("Удалить ячейку (под курсором)")
            a_del_table = tmenu.addAction("Удалить таблицу целиком")
            a_ins_row_above.triggered.connect(
                lambda: self._table_insert_row(r, above=True)
            )
            a_ins_row_below.triggered.connect(
                lambda: self._table_insert_row(r, above=False)
            )
            a_del_row.triggered.connect(lambda: self._table_delete_row(r))
            a_ins_col_left.triggered.connect(
                lambda: self._table_insert_col(c, left=True)
            )
            a_ins_col_right.triggered.connect(
                lambda: self._table_insert_col(c, left=False)
            )
            a_del_col.triggered.connect(lambda: self._table_delete_col(c))
            a_split_h.triggered.connect(lambda: self._table_split_cell(rows=2, cols=1))
            a_split_v.triggered.connect(lambda: self._table_split_cell(rows=1, cols=2))
            a_merge.triggered.connect(self._table_merge_selection)
            a_del_cell.triggered.connect(self._table_delete_cell)
            a_del_table.triggered.connect(self._table_delete_table)
        else:
            tmenu = menu.addMenu("Table")
            a_new = tmenu.addAction("Вставить таблицу 2×2")
            a_new.triggered.connect(lambda: self._insert_table(rows=2, cols=2))

    def _table_delete_cell(self) -> None:
        cur = self.textCursor()
        tbl = cur.currentTable()
        if not tbl:
            return
        cell = tbl.cellAt(cur)
        if not cell.isValid():
            return
        r, c = cell.row(), cell.column()
        rows, cols = tbl.rows(), tbl.columns()
        try:
            rs, cs = cell.rowSpan(), cell.columnSpan()
            if rs > 1 or cs > 1:
                tbl.splitCell(r, c, 1, 1)
                rows, cols = tbl.rows(), tbl.columns()
        except Exception:
            pass
        if cols > 1:
            tbl.removeColumns(c, 1)
            return
        if rows > 1:
            tbl.removeRows(r, 1)
            return
        self._table_delete_table()

    def _table_delete_table(self) -> None:
        cur = self.textCursor()
        tbl = cur.currentTable()
        if not tbl:
            return
        first = tbl.cellAt(0, 0).firstCursorPosition()
        last = tbl.cellAt(tbl.rows() - 1, tbl.columns() - 1).lastCursorPosition()
        c = QTextCursor(first)
        c.setPosition(last.position(), QTextCursor.KeepAnchor)
        c.beginEditBlock()
        c.removeSelectedText()
        c.endEditBlock()

    def _insert_table(self, rows=2, cols=2) -> None:
        cur = self.textCursor()
        table_fmt = QTextTableFormat()
        table_fmt.setCellPadding(4)
        table_fmt.setCellSpacing(0)
        border_qcolor = self.palette().text().color()
        table_fmt.setBorder(1)
        try:
            table_fmt.setBorderBrush(QBrush(border_qcolor))
        except Exception:
            pass
        table = cur.insertTable(rows, cols, table_fmt)
        cell_fmt = QTextTableCellFormat()
        cell_fmt.setBorder(1)
        try:
            cell_fmt.setBorderStyle(QTextFrameFormat.BorderStyle_Solid)
            cell_fmt.setBorderBrush(QBrush(border_qcolor))
        except Exception:
            pass
        for r in range(rows):
            for c in range(cols):
                try:
                    table.cellAt(r, c).setFormat(cell_fmt)
                except Exception:
                    pass

    def _table_insert_row(self, row: int, *, above: bool) -> None:
        cur = self.textCursor()
        tbl = cur.currentTable()
        if not tbl:
            return
        pos = max(0, min(row + (0 if above else 1), tbl.rows()))
        tbl.insertRows(pos, 1)

    def _table_delete_row(self, row: int) -> None:
        cur = self.textCursor()
        tbl = cur.currentTable()
        if not tbl:
            return
        if 0 <= row < tbl.rows():
            tbl.removeRows(row, 1)

    def _table_insert_col(self, col: int, *, left: bool) -> None:
        cur = self.textCursor()
        tbl = cur.currentTable()
        if not tbl:
            return
        pos = max(0, min(col + (0 if left else 1), tbl.columns()))
        tbl.insertColumns(pos, 1)

    def _table_delete_col(self, col: int) -> None:
        cur = self.textCursor()
        tbl = cur.currentTable()
        if not tbl:
            return
        if 0 <= col < tbl.columns():
            tbl.removeColumns(col, 1)

    def _table_split_cell(self, *, rows: int, cols: int) -> None:
        cur = self.textCursor()
        tbl = cur.currentTable()
        if not tbl:
            return
        cell = tbl.cellAt(cur)
        if not cell.isValid():
            return
        r, c = cell.row(), cell.column()
        rs, cs = cell.rowSpan(), cell.columnSpan()
        if (rows > 1 and rs > 1) or (cols > 1 and cs > 1):
            try:
                tbl.splitCell(r, c, rs, cs)
            except Exception:
                pass
            return
        if rows > 1 and cols == 1:
            tbl.insertRows(r + 1, 1)
            ncols = tbl.columns()
            for j in range(ncols):
                if j == c:
                    continue
                try:
                    tbl.mergeCells(r, j, 2, 1)
                except Exception:
                    pass
            return
        if cols > 1 and rows == 1:
            tbl.insertColumns(c + 1, 1)
            nrows = tbl.rows()
            for i in range(nrows):
                if i == r:
                    continue
                try:
                    tbl.mergeCells(i, c, 1, 2)
                except Exception:
                    pass
            return

    def _table_merge_selection(self) -> None:
        cur = self.textCursor()
        tbl = cur.currentTable()
        if not tbl:
            return
        if not cur.hasSelection():
            cell = tbl.cellAt(cur)
            if cell.isValid():
                tbl.mergeCells(cell.row(), cell.column(), 1, 1)
            return
        start = min(cur.selectionStart(), cur.selectionEnd() - 1)
        end = max(cur.selectionStart(), cur.selectionEnd() - 1)
        tl = tbl.cellAt(start)
        br = tbl.cellAt(end)
        if not (tl.isValid() and br.isValid()):
            return
        r1, c1 = tl.row(), tl.column()
        r2, c2 = br.row(), br.column()
        top, left = min(r1, r2), min(c1, c2)
        nrows = abs(r2 - r1) + 1
        ncols = abs(c2 - c1) + 1
        tbl.mergeCells(top, left, nrows, ncols)

    def _sanitize_plain_for_copy(self, s: str) -> str:
        s = s.replace("▾", "").replace("▼", "")
        s = re.sub(r"[\u200b\u200c\u200d\u200e\u200f\u202a-\u202e\u2066-\u2069]", "", s)
        s = re.sub(r"[ \t]+(\r?\n)", r"\1", s)
        return s

    def _sanitize_html_for_copy(self, html: str) -> str:
        if not html:
            return html
        html = html.replace("▾", "").replace("▼", "")
        html = re.sub(r"&(?:#9(?:660|662);|#9660;|#9662;)", "", html, flags=re.I)
        html = re.sub(
            r"[\u200b\u200c\u200d\u200e\u200f\u202a-\u202e\u2066-\u2069]", "", html
        )
        html = re.sub(
            r'<a\b[^>]*\bhref\s*=\s*["\']dropdown://[^"\']*["\'][^>]*>(.*?)</a>',
            r"\1",
            html,
            flags=re.I | re.S,
        )
        html = re.sub(
            r'\bhref\s*=\s*["\']dropdown://[^"\']*["\']', "", html, flags=re.I
        )
        return html

    def _build_rich_mime_from_selection(self) -> QMimeData:
        cur = self.textCursor()
        if cur.hasSelection():
            frag = cur.selection()
            html = frag.toHtml()
            plain = frag.toPlainText()
        else:
            html = self.document().toHtml()
            plain = self.toPlainText()
        html = self._sanitize_html_for_copy(html)
        plain = self._sanitize_plain_for_copy(plain)
        md = QMimeData()
        md.setHtml(html)
        md.setText(plain)
        return md

    def createMimeDataFromSelection(self):
        if self.textCursor().charFormat().isImageFormat():
            return super().createMimeDataFromSelection()
        return self._build_rich_mime_from_selection()

    def startDrag(self, supportedActions: Qt.DropActions) -> None:
        cursor = self.textCursor()
        if cursor.charFormat().isImageFormat():
            image_format = cursor.charFormat().toImageFormat()
            image_path = image_format.name()
            if os.path.exists(image_path):
                drag = QDrag(self)
                mimeData = self.createMimeDataFromSelection()
                drag.setMimeData(mimeData)
                drag.setPixmap(self.create_drag_image(self))
                drag.exec(supportedActions, Qt.CopyAction)
                return
        super().startDrag(supportedActions)
