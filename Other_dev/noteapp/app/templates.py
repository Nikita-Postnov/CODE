"""TemplatesMixin: шаблоны заметок — загрузка, сохранение, вставка, управление.

Вырезано из NotesApp (step 4.7). Апстрим-методы (_apply_dynamic_tokens,
_render_date_placeholders, _center_on_parent, record_state_for_undo)
остаются в NotesApp и доступны через self.
"""

import json
import os
import re

from PySide6.QtCore import (
    QDate,
    Qt,
)
from PySide6.QtGui import (
    QFont,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from ..config import DATA_DIR


class TemplatesMixin:
    def load_templates(self) -> list[dict]:
        templates_path = os.path.join(DATA_DIR, "templates.json")
        base_templates = [
            {
                "name": "Список дел",
                "category": "Работа",
                "description": "Чекбокс-лист для задач",
                "content_html": "<b>Список дел:</b><br>☐ Первая задача<br>☐ Вторая задача<br>☐ Третья задача<br>",
            },
            {
                "name": "Встреча",
                "category": "Встречи",
                "description": "Заготовка для заметки о встрече",
                "content_html": "<b>Встреча</b><br>Дата: <br>Участники: <br>Цели: <br>Результаты: <br>",
            },
            {
                "name": "Дневник",
                "category": "Личное",
                "description": "Дневниковая запись",
                "content_html": "<b>Дневник</b><br>Дата: <br>Сегодня:<br><br>Настроение:<br>События:<br>",
            },
            {
                "name": "UPD блок",
                "category": "Работа",
                "description": "Блок обновления с датой, базой, пользователем, результатом и деталями",
                "content_html": "<b>UPD [{date}]</b><br><b>Base:</b> <br><b>User:</b> <br><b>Result:</b> <br><b>Details:</b> <br><br>",
            },
        ]
        auto_today_tpl = {
            "name": "Сегодня",
            "category": "Работа",
            "description": "Строка с текущей датой",
            "content_html": (
                '<table style="border-collapse:collapse;">'
                '<tr><td style="border:1px solid #bdbdbd; padding:4px 8px; border-radius:4px;">'
                'UPD [<span data-dyn="today">{today}</span>]'
                "</td></tr></table><br>"
            ),
        }
        correct_range5 = {
            "name": "Интервал 5 дней",
            "category": "Работа",
            "description": "Таблица 1×1 с диапазоном дат (N=5 дней, редактируемая начальная дата)",
            "content_html": (
                '<table style="border-collapse:collapse;">'
                '<tr><td style="border:1px solid #bdbdbd; padding:4px 8px; border-radius:4px;">'
                '<span style="font-weight:600;">{date}-{date+4}</span>'
                "</td></tr></table><br>"
            ),
        }
        if not os.path.exists(templates_path):
            templates = base_templates + [auto_today_tpl, correct_range5]
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            self._atomic_write_json(templates_path, templates)
            return templates
        try:
            with open(templates_path, "r", encoding="utf-8") as f:
                templates = json.load(f)
                if not isinstance(templates, list):
                    templates = []
        except Exception:
            templates = []
        by_name = {t.get("name"): t for t in templates}

        def upsert(tpl: dict) -> None:
            cur = by_name.get(tpl["name"])
            if cur is None:
                templates.append(tpl)
                by_name[tpl["name"]] = tpl
            else:
                if cur.get("content_html") != tpl.get("content_html"):
                    cur.update(tpl)

        for t in base_templates:
            upsert(t)
        upsert(auto_today_tpl)
        upsert(correct_range5)
        self._atomic_write_json(templates_path, templates)
        return templates

    def save_templates(self, templates: list[dict]) -> None:
        templates_path = os.path.join(DATA_DIR, "templates.json")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        # Атомарная запись: сбой посреди записи раньше оставлял обрезанный
        # templates.json, и при следующем запуске все шаблоны пропадали.
        self._atomic_write_json(templates_path, templates)

    def save_current_as_template(self) -> None:
        if not self.current_note:
            QMessageBox.warning(self, "Нет заметки", "Сначала выбери заметку.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Сохранить как шаблон")
        layout = QFormLayout(dialog)
        name_edit = QLineEdit()
        category_edit = QLineEdit()
        description_edit = QLineEdit()
        only_selection = QCheckBox("Только выделенный фрагмент")
        layout.addRow("Название:", name_edit)
        layout.addRow("Категория:", category_edit)
        layout.addRow("Описание:", description_edit)
        layout.addRow("", only_selection)
        preview = QTextEdit()
        preview.setMinimumHeight(180)
        layout.addRow("Содержимое:", preview)

        def fill_preview():
            cur = self.text_edit.textCursor()
            if only_selection.isChecked() and cur.hasSelection():
                frag = cur.selection()
                preview.setHtml(frag.toHtml())
            else:
                preview.setHtml(self.text_edit.toHtml())

        only_selection.toggled.connect(fill_preview)
        fill_preview()
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        layout.addRow(buttons)

        def on_accept():
            name = name_edit.text().strip()
            if not name:
                QMessageBox.warning(dialog, "Ошибка", "Укажи название шаблона.")
                return
            tpl = {
                "name": name,
                "category": (category_edit.text().strip() or "Без категории"),
                "description": description_edit.text().strip(),
                "content_html": preview.toHtml(),
            }
            templates = self.load_templates()
            exist_idx = next(
                (i for i, t in enumerate(templates) if t.get("name") == name), -1
            )
            if exist_idx >= 0:
                r = QMessageBox.question(
                    dialog,
                    "Перезаписать?",
                    f"Шаблон «{name}» уже существует. Перезаписать?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if r == QMessageBox.No:
                    return
                templates[exist_idx] = tpl
            else:
                templates.append(tpl)
            self.save_templates(templates)
            dialog.accept()
            self.show_toast("Шаблон сохранён")

        buttons.accepted.connect(on_accept)
        buttons.rejected.connect(dialog.reject)
        self._center_on_parent(dialog)
        dialog.exec()

    def insert_template(self) -> None:
        if not self.current_note:
            QMessageBox.warning(self, "Нет заметки", "Создайте или выберите заметку.")
            return
        templates = self.load_templates()
        dialog = QDialog(self)
        dialog.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        dialog.setWindowTitle("Вставить шаблон")
        layout = QVBoxLayout(dialog)
        combo = QComboBox(dialog)
        categories = sorted({tpl.get("category", "Без категории") for tpl in templates})
        category_combo = QComboBox(dialog)
        category_combo.addItem("Все категории")
        category_combo.addItems(categories)
        filtered_templates = templates.copy()

        def filter_templates():
            cat = category_combo.currentText()
            combo.clear()
            filtered = [
                tpl
                for tpl in templates
                if cat == "Все категории" or tpl.get("category", "Без категории") == cat
            ]
            filtered_templates.clear()
            filtered_templates.extend(filtered)
            combo.addItems(
                [f"{tpl['name']} ({tpl.get('description','')})" for tpl in filtered]
            )

        category_combo.currentIndexChanged.connect(filter_templates)
        layout.addWidget(category_combo)
        layout.addWidget(combo)
        preview = QTextEdit(dialog)
        preview.setReadOnly(True)
        preview.setMinimumHeight(100)
        layout.addWidget(preview)

        def update_preview(idx):
            if 0 <= idx < len(filtered_templates):
                content = filtered_templates[idx]["content_html"]
                today = QDate.currentDate()
                content = self._render_date_placeholders(content, today)
                preview.setHtml(content)
            else:
                preview.setHtml("")

        combo.currentIndexChanged.connect(update_preview)
        filter_templates()
        combo.setCurrentIndex(0)
        update_preview(0)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(buttons)
        dialog.setLayout(layout)

        def _toggle_launcher_topmost(self, checked: bool) -> None:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, checked)
            self.settings.setValue("ui/launcher_always_on_top", checked)
            self.show()

        def keyPressEvent(event):
            if event.key() == Qt.Key_Escape:
                dialog.reject()
            else:
                QDialog.keyPressEvent(dialog, event)

        dialog.keyPressEvent = keyPressEvent
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        self._center_on_parent(dialog)
        if dialog.exec() == QDialog.Accepted:
            idx = combo.currentIndex()
            if 0 <= idx < len(filtered_templates):
                tpl = filtered_templates[idx]
                content_html = tpl["content_html"]
                date_pattern = re.compile(r"\{date(?:[+-]\s*\d+)?\}", re.I)
                base_date = QDate.currentDate()
                if date_pattern.search(content_html):
                    ask = QDialog(self)
                    ask.setWindowTitle("Начальная дата")
                    form = QFormLayout(ask)
                    de = QDateTimeEdit(ask)
                    de.setDisplayFormat("dd.MM.yyyy")
                    de.setCalendarPopup(True)
                    de.setDate(QDate.currentDate())
                    form.addRow("Начальная дата:", de)
                    buttons = QDialogButtonBox(
                        QDialogButtonBox.Ok | QDialogButtonBox.Cancel, ask
                    )
                    form.addRow(buttons)
                    buttons.accepted.connect(ask.accept)
                    buttons.rejected.connect(ask.reject)
                    self._center_on_parent(ask)
                    if ask.exec() != QDialog.Accepted:
                        return
                    base_date = de.date()
                content_html = self._render_date_placeholders(content_html, base_date)
                content_html = self._apply_dynamic_tokens(content_html)
                cursor = self.text_edit.textCursor()
                start = cursor.position()
                self.text_edit.insertHtml(content_html)
                end = self.text_edit.textCursor().position()
                if end > start:
                    cursor.setPosition(start)
                    cursor.setPosition(end, QTextCursor.KeepAnchor)
                    fmt = QTextCharFormat()
                    font = QFont("Times New Roman", 14)
                    fmt.setFont(font)
                    cursor.mergeCharFormat(fmt)
                    cursor.clearSelection()
                    self.text_edit.setTextCursor(cursor)
                self.record_state_for_undo()

    def manage_templates_dialog(self) -> None:
        templates = self.load_templates()
        dlg = QDialog(self)
        dlg.setWindowTitle("Шаблоны")
        v = QVBoxLayout(dlg)
        lst = QListWidget()

        def refresh():
            lst.clear()
            for t in templates:
                lst.addItem(f"{t.get('name','')} — {t.get('category','Без категории')}")

        refresh()
        v.addWidget(lst)
        form = QFormLayout()
        name_edit = QLineEdit()
        category_edit = QLineEdit()
        desc_edit = QLineEdit()
        form.addRow("Название:", name_edit)
        form.addRow("Категория:", category_edit)
        form.addRow("Описание:", desc_edit)
        v.addLayout(form)
        content = QTextEdit()
        content.setMinimumHeight(180)
        v.addWidget(content)
        btns_line = QHBoxLayout()
        btn_new = QPushButton("Новый")
        btn_save = QPushButton("Сохранить")
        btn_del = QPushButton("Удалить")
        btn_close = QPushButton("Закрыть")
        for b in (btn_new, btn_save, btn_del, btn_close):
            btns_line.addWidget(b)
        v.addLayout(btns_line)

        def load_current(i):
            if i < 0 or i >= len(templates):
                name_edit.clear()
                category_edit.clear()
                desc_edit.clear()
                content.clear()
                return
            t = templates[i]
            name_edit.setText(t.get("name", ""))
            category_edit.setText(t.get("category", ""))
            desc_edit.setText(t.get("description", ""))
            content.setHtml(t.get("content_html", ""))

        lst.currentRowChanged.connect(load_current)
        if templates:
            lst.setCurrentRow(0)

        def on_new():
            templates.append(
                {
                    "name": "Новый шаблон",
                    "category": "Без категории",
                    "description": "",
                    "content_html": "",
                }
            )
            refresh()
            lst.setCurrentRow(len(templates) - 1)

        def on_save():
            i = lst.currentRow()
            if i < 0:
                return
            templates[i] = {
                "name": name_edit.text().strip() or "Без имени",
                "category": category_edit.text().strip() or "Без категории",
                "description": desc_edit.text().strip(),
                "content_html": content.toHtml(),
            }
            self.save_templates(templates)
            refresh()
            lst.setCurrentRow(i)
            self.show_toast("Сохранено")

        def on_del():
            i = lst.currentRow()
            if i < 0:
                return
            r = QMessageBox.question(
                dlg,
                "Удалить",
                "Удалить выбранный шаблон?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if r == QMessageBox.Yes:
                templates.pop(i)
                self.save_templates(templates)
                refresh()
                lst.setCurrentRow(min(i, len(templates) - 1))

        btn_new.clicked.connect(on_new)
        btn_save.clicked.connect(on_save)
        btn_del.clicked.connect(on_del)
        btn_close.clicked.connect(dlg.accept)
        self._center_on_parent(dlg)

        def _on_show(ev):
            QDialog.showEvent(dlg, ev)
            self._center_on_parent(dlg)

        dlg.showEvent = _on_show
        self._center_on_parent(dlg)
        dlg.exec()
