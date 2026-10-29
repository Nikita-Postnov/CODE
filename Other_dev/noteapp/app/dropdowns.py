"""DropdownsMixin: inline-выпадающие токены в тексте заметки —
вставка, редактирование значений, контекстное меню, сериализация в HTML.

Вырезано из NotesApp (step 4.10). Апстрим-методы (_ensure_dd_map, _html_escape,
_edit_values_and_reopen, record_state_for_undo, save_note_quiet) остаются
в NotesApp и доступны через self.
"""

import json
import re
import uuid
from urllib.parse import quote, unquote

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..constants import CUSTOM_MENU_STYLE


class DropdownsMixin:
    def _load_dropdown_values(self) -> list[str]:
        try:
            vals = json.loads(self.settings.value("dropdown_values", "[]"))
            if not isinstance(vals, list):
                vals = []
        except Exception:
            vals = []
        if not vals:
            vals = ["Вариант 1", "Вариант 2", "Вариант 3"]
        return [str(v) for v in vals]

    def _dropdown_palette(self) -> tuple[str, str, str]:
        is_dark = self.settings.value("theme", "dark") == "dark"
        if is_dark:
            return ("#303030", "#ffffff", "#7a7a7a")
        return ("#f0f0f0", "#111111", "#b0b0b0")

    def _get_dropdown_token_info(self, dd_id: str) -> dict | None:
        self._ensure_dd_map()
        if dd_id in self._dropdown_tokens:
            return self._dropdown_tokens[dd_id]

        html = self.text_edit.toHtml()
        href_prefix = f"dropdown://{re.escape(dd_id)}"
        m = re.search(
            rf'<a[^>]*href="{href_prefix}[^"]*"[^>]*>(.*?)</a>', html, flags=re.S
        )
        if not m:
            return None

        full_tag = m.group(0)
        inner = m.group(1)

        vals = None
        href_m = re.search(r'href="([^"]+)"', full_tag)
        if href_m:
            href_val = href_m.group(1)
            v_m = re.search(r'[?#]v=([^"&]*)', href_val)
            if v_m:
                try:
                    vals = json.loads(unquote(v_m.group(1)))
                except Exception:
                    vals = None

        if vals is None:
            title_m = re.search(r'title=(["\'])(.*?)\1', full_tag)
            if title_m:
                try:
                    vals = json.loads(unquote(title_m.group(2)))
                except Exception:
                    vals = None

        if vals is None:
            vals = self._load_dropdown_values()

        text = re.sub(r"<[^>]+>", "", inner)
        text = text.replace("▼", "").replace("&#9662;", "").strip()

        info = {"value": text, "values": vals}
        self._dropdown_tokens[dd_id] = info
        return info

    def _insert_dropdown_token(
        self, value: str, dd_id: str | None = None, values: list[str] | None = None
    ) -> str:
        self._ensure_dd_map()
        if dd_id is None:
            dd_id = uuid.uuid4().hex[:8]
        if values is None:
            values = self._load_dropdown_values()
        self._dropdown_tokens[dd_id] = {"value": value, "values": list(values)}
        bg, fg, br = self._dropdown_palette()
        inner = (
            f'<span style="display:inline-block; padding:2px 8px; '
            f"border-radius:6px; border:1px solid {br}; "
            f'background:{bg}; color:{fg};">{self._html_escape(value)} &#9662;</span>'
        )
        encoded = quote(json.dumps(values, ensure_ascii=False))
        html = (
            f'<a href="dropdown://{dd_id}" title="{encoded}" '
            f'style="text-decoration:none;">{inner}</a>&nbsp;'
        )
        c = self.text_edit.textCursor()
        c.insertHtml(html)
        self.text_edit.setTextCursor(c)
        self.record_state_for_undo()
        if hasattr(self, "debounce_timer"):
            if self.autosave_enabled:
                self.save_note_quiet(force=True)
        return dd_id

    def _update_dropdown_token(self, dd_id: str, new_value: str) -> None:
        info = self._get_dropdown_token_info(dd_id)
        if not info:
            return
        info["value"] = new_value
        values = info.get("values", [])
        bg, fg, br = self._dropdown_palette()
        inner = (
            f'<span style="display:inline-block; padding:2px 8px; '
            f"border-radius:6px; border:1px solid {br}; "
            f'background:{bg}; color:{fg};">{self._html_escape(new_value)} &#9662;</span>'
        )
        encoded = quote(json.dumps(values, ensure_ascii=False))
        new_anchor = (
            f'<a href="dropdown://{dd_id}?v={encoded}" '
            f'style="text-decoration:none;">{inner}</a>'
        )
        html = self.text_edit.toHtml()
        href_prefix = f"dropdown://{re.escape(dd_id)}"
        pattern = re.compile(rf'<a[^>]*href="{href_prefix}[^"]*"[^>]*>.*?</a>', re.S)
        new_html, count = pattern.subn(new_anchor, html, count=1)
        if count == 0:
            return
        self.text_edit.blockSignals(True)
        self.text_edit.setHtml(new_html)
        self.text_edit.blockSignals(False)
        self.record_state_for_undo()
        if hasattr(self, "debounce_timer"):
            if self.autosave_enabled:
                self.save_note_quiet(force=True)

    def _persist_dropdown_values_in_html(self, html: str) -> str:
        pattern = re.compile(
            r'<a[^>]*href="dropdown://([0-9a-fA-F]{8})[^"]*"[^>]*>(.*?)</a>', re.S
        )

        def repl(m):
            dd_id = m.group(1)
            _ = m.group(2)

            info = self._get_dropdown_token_info(dd_id)
            if not info:
                return m.group(0)
            value = info.get("value", "")
            values = info.get("values", []) or []
            bg, fg, br = self._dropdown_palette()
            inner = (
                f'<span style="display:inline-block; padding:2px 8px; '
                f"border-radius:6px; border:1px solid {br}; "
                f'background:{bg}; color:{fg};">{self._html_escape(value)} &#9662;</span>'
            )

            encoded = quote(json.dumps(values, ensure_ascii=False))
            return (
                f'<a href="dropdown://{dd_id}?v={encoded}" '
                f'style="text-decoration:none;">{inner}</a>'
            )

        return pattern.sub(repl, html)

    def show_dropdown_menu_for_token(self, dd_id: str, global_pos=None) -> None:
        info = self._get_dropdown_token_info(dd_id)
        values = (
            info.get("values", self._load_dropdown_values())
            if info
            else self._load_dropdown_values()
        )
        menu = QMenu(self)
        menu.setStyleSheet(CUSTOM_MENU_STYLE)
        for v in values:
            act = menu.addAction(v)
            act.triggered.connect(
                lambda _, val=v: self._update_dropdown_token(dd_id, val)
            )
        menu.addSeparator()
        add_act = menu.addAction("➕ Добавить значение…")
        add_act.triggered.connect(lambda: self._add_value_to_dropdown(dd_id))
        curr = (info or {}).get("value", "")
        del_act = menu.addAction(f"➖ Удалить «{curr}» из списка")
        del_act.setEnabled(bool(curr and curr in values))
        del_act.triggered.connect(lambda: self._remove_value_from_dropdown(dd_id, curr))
        menu.addSeparator()
        edit_act = menu.addAction("✏️ Редактировать список…")
        edit_act.triggered.connect(lambda: self._edit_values_and_reopen(dd_id))
        if global_pos is None:
            cr = self.text_edit.cursorRect(self.text_edit.textCursor())
            global_pos = self.text_edit.viewport().mapToGlobal(cr.bottomLeft())
        menu.exec(global_pos)

    def _set_dropdown_values(self, dd_id: str, values: list[str]) -> None:
        info = self._get_dropdown_token_info(dd_id)
        if not info:
            return
        cleaned = []
        for v in values:
            v = (v or "").strip()
            if v and v not in cleaned:
                cleaned.append(v)
        info["values"] = cleaned
        self._update_dropdown_token(dd_id, info.get("value", ""))

    def _add_value_to_dropdown(self, dd_id: str) -> None:
        text, ok = QInputDialog.getText(self, "Добавить значение", "Текст:")
        if not ok:
            return
        val = (text or "").strip()
        if not val:
            return
        info = self._get_dropdown_token_info(dd_id)
        if not info:
            return
        values = list(info.get("values", []))
        if val not in values:
            values.append(val)
            self._set_dropdown_values(dd_id, values)
        self.show_dropdown_menu_for_token(dd_id)

    def _remove_value_from_dropdown(self, dd_id: str, value: str) -> None:
        info = self._get_dropdown_token_info(dd_id)
        if not info:
            return
        values = [v for v in info.get("values", []) if v != value]
        self._set_dropdown_values(dd_id, values)
        self.show_dropdown_menu_for_token(dd_id)

    def insert_dropdown(self) -> None:
        if not self.current_note:
            QMessageBox.warning(
                self, "Нет заметки", "Сначала выбери или создай заметку."
            )
            return
        values = self._load_dropdown_values()
        initial = values[0] if values else "Выбрать…"
        dd_id = self._insert_dropdown_token(initial, values=values)
        cr = self.text_edit.cursorRect(self.text_edit.textCursor())
        pos = self.text_edit.viewport().mapToGlobal(cr.bottomLeft())
        self.show_dropdown_menu_for_token(dd_id, pos)

    def _open_dropdown_values_editor(
        self, initial_values: list[str] | None = None
    ) -> list[str] | None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Значения выпадающего списка")
        v = QVBoxLayout(dlg)
        lst = QListWidget(dlg)
        v.addWidget(lst)
        if initial_values is None:
            try:
                last = json.loads(self.settings.value("dropdown_values", "[]"))
                if not isinstance(last, list):
                    last = []
            except Exception:
                last = []
            if not last:
                last = ["Вариант 1", "Вариант 2", "Вариант 3"]
        else:
            last = (
                list(initial_values)
                if initial_values
                else ["Вариант 1", "Вариант 2", "Вариант 3"]
            )
        for s in last:
            lst.addItem(str(s))
        btns_line = QHBoxLayout()
        btn_add = QPushButton("Добавить")
        btn_ren = QPushButton("Переименовать")
        btn_del = QPushButton("Удалить")
        btn_up = QPushButton("↑")
        btn_dn = QPushButton("↓")
        btns_line.addWidget(btn_add)
        btns_line.addWidget(btn_ren)
        btns_line.addWidget(btn_del)
        btns_line.addStretch(1)
        btns_line.addWidget(btn_up)
        btns_line.addWidget(btn_dn)
        v.addLayout(btns_line)

        def add_item():
            text, ok = QInputDialog.getText(dlg, "Добавить значение", "Текст:")
            if ok and text.strip():
                lst.addItem(text.strip())

        def rename_item():
            it = lst.currentItem()
            if not it:
                return
            text, ok = QInputDialog.getText(
                dlg, "Переименовать", "Текст:", text=it.text()
            )
            if ok and text.strip():
                it.setText(text.strip())

        def delete_item():
            row = lst.currentRow()
            if row >= 0:
                lst.takeItem(row)

        def move_up():
            row = lst.currentRow()
            if row > 0:
                it = lst.takeItem(row)
                lst.insertItem(row - 1, it)
                lst.setCurrentRow(row - 1)

        def move_dn():
            row = lst.currentRow()
            if 0 <= row < lst.count() - 1:
                it = lst.takeItem(row)
                lst.insertItem(row + 1, it)
                lst.setCurrentRow(row + 1)

        btn_add.clicked.connect(add_item)
        btn_ren.clicked.connect(rename_item)
        btn_del.clicked.connect(delete_item)
        btn_up.clicked.connect(move_up)
        btn_dn.clicked.connect(move_dn)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dlg)
        v.addWidget(buttons)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        fg = dlg.frameGeometry()
        fg.moveCenter(self.frameGeometry().center())
        dlg.move(fg.topLeft())
        if dlg.exec() == QDialog.Accepted:
            values = [
                lst.item(i).text().strip()
                for i in range(lst.count())
                if lst.item(i).text().strip()
            ]
            if initial_values is None:
                self.settings.setValue(
                    "dropdown_values", json.dumps(values, ensure_ascii=False)
                )
            return values
        return None

    def _commit_dropdown_value(self, combo: QComboBox, value: str) -> None:
        fmt = self.text_edit.currentCharFormat()
        cursor = self.text_edit.textCursor()
        cursor.insertText(value, fmt)
        self.text_edit.setTextCursor(cursor)
        combo.hide()
        self.record_state_for_undo()
        if hasattr(self, "debounce_timer"):
            if self.autosave_enabled:
                self.save_note_quiet(force=True)

    def _insert_dropdown_plain(self, value: str) -> None:
        fmt = self.text_edit.currentCharFormat()
        c = self.text_edit.textCursor()
        c.insertText(value, fmt)
        self.text_edit.setTextCursor(c)
        self.record_state_for_undo()
        if hasattr(self, "debounce_timer"):
            if self.autosave_enabled:
                self.save_note_quiet(force=True)
