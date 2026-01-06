# Исправленная версия: более «человеческие» и понятные тексты для интерфейса
from __future__ import annotations
import os
import re
import sys
import uuid
import json
import shutil
import zipfile
import sqlite3
import hashlib
import datetime as dt
import mimetypes
import traceback
import xml.etree.ElementTree as ET
from typing import Optional, Any, Dict, List, Tuple, Mapping
from PySide6 import QtCore, QtGui, QtWidgets
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

APP_NAME = "Менеджер доказательств тестирования — личная копилка"
DATA_DIRNAME = "tem_data"
DB_FILENAME = "tem.db"
STORAGE_DIRNAME = "storage"
LOG_FILENAME = "tem.log"

# Статусы теперь выражены более разговорно — так понятнее пользователю
STATUS_CHOICES: List[Tuple[str, str]] = [
    ("PASS", "Пройдено"),
    ("FAIL", "Не прошёл"),
    ("BLOCKED", "Заблокирован"),
    ("SKIPPED", "Пропущен"),
    ("UNKNOWN", "Неизвестен"),
]

HELP_MARKDOWN = """Короткая инструкция — что делает это приложение и как им пользоваться

1) Что это за программа
- Это простое локальное приложение, где удобно хранить прогоны тестов и связанные с ними файлы (скриншоты, логи и т. п.).
- Все данные лежат в папке `tem_data` рядом со скриптом (или рядом с собранным exe).
- Внутри `tem_data` вы увидите папки и файлы:
  - projects — проекты
  - releases — релизы внутри проектов
  - testcases — тест-кейсы внутри релизов
  - runs — прогоны, связанные с тест-кейсами
  - attachments — физические файлы в `storage/`

2) Запуск и где искать файлы
- При первом запуске создаётся папка `tem_data`.
- В ней:
  - `tem.db` — sqlite-база
  - `storage/` — все вложения
  - `tem.log` — лог программы
- Также в `tem_data` создаётся `README.md` с этой инструкцией.

3) Быстро по интерфейсу
- Слева — дерево (Проекты → Релизы → Тест-кейсы).
- Справа — список прогонов, фильтры, список вложений и панель с деталями.
- Контекстное меню по узлам дерева — быстрые действия (создать/редактировать/удалить).
- Двойной клик по прогону открывает форму редактирования.

4) Проекты, релизы, тест-кейсы
- Проект: имя и описание. Имя обязательно и должно быть уникальным.
- Релиз: создаётся внутри проекта; можно указать период и описание.
- Тест-кейс: внутри релиза. Поля: набор (suite), имя, внешний ID, описание.
- Уникальность тест-кейсов проверяется по (release_id, suite, name).

5) Прогоны (Runs)
- Для прогона вводим: статус, время (ISO), сборку, окружение, исполнителя, длительность (сек), комментарий и meta (JSON).
- Meta — произвольный JSON. Если введён некорректный JSON — сохранится сырой текст в поле `_raw`.
- Редактирование: двойной клик или через меню.
- Удаление: выделите прогон и нажмите Delete.

6) Вложения
- Вложения привязаны к прогону.
- Добавление: кнопка "Добавить файлы…" или перетаскиванием в список вложений.
- Файлы копируются в `storage/<Project>/<Release>/<Suite>/<Test>/run_<ID>/...`.
- В базе хранится относительный путь от `storage/`, размер, sha256 и тип (screenshot/video/log/report/file).
- По вложению можно открыть файл, открыть папку, добавить заметку или удалить.

7) Импорт JUnit XML
- Меню: Импорт → JUnit XML...
- Поддерживаются файлы с тегами `testsuite`/`testcase`.
- Для каждого testcase:
  - ищем тест-кейс по (release + suite + name). Если не нашли — создаём и помечаем в описании.
  - создаём прогон с указанным статусом, длительностью (атрибут `time`) и сообщением из `failure`/`error`.
  - в meta добавляем `source: "junit"` и имя файла.

8) Экспорт
- ZIP выбранного прогона: включает вложения и `meta.json` с данными прогона.
- PDF отчёт по релизу: текстовый отчёт со списком прогонов и краткими комментариями.

9) Поиск и фильтры
- Фильтры по релизу: статус, сборка, окружение, исполнитель, произвольный текст.
- Поля сборка/окружение/исполнитель поддерживают автодополнение на основе уже существующих значений.
- Поиск "по тексту" ищет в suite, имени, external id и комментарии (по подстроке).

10) Логи
- Ошибки и трассировки сохраняются в `tem_data/tem.log`.
- Если падение произошло до создания `tem_data` — лог в рабочую папку `tem.log`.

11) Бэкап и перенос
- Для переноса достаточно скопировать папку `tem_data` целиком (включая `tem.db` и `storage`).
- Для бэкапа: закройте программу и скопируйте папку, либо создайте дамп sqlite.

12) Небольшие советы
- Давайте понятные имена — они используются в путях и в zip-архивах.
- При массовом импорте (JUnit) полезно заранее создать релиз.
- Следите за свободным местом на диске — вложения могут быстро занять много места.

13) Быстрые клавиши и действия
- Delete — удалить выделенный прогон или вложение.
- Двойной клик — редактировать прогон.
- Drag&Drop — добавить файлы во вложения.

14) Частые проблемы
- "Не вижу файлы" — проверьте папку `storage/` и `tem_data/tem.log`.
- "JUnit не импортируется" — проверьте корректность XML: есть ли теги `testcase` и атрибуты `name`/`time`.

15) Обратная связь
- При баге приложите `tem_data/tem.log` и, если нужно, архив `tem_data`.
"""

def now_iso() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")

def ensure_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)

def safe_filename(name: str) -> str:
    name = (name or "").strip().replace("\\", "_").replace("/", "_").replace(":", "_")
    name = re.sub(r"[^0-9A-Za-zА-Яа-я._\-()\[\] ]+", "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:160] if len(name) > 160 else name

def sha256_file(path: str, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def human_size(n: int) -> str:
    x = float(n)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if x < 1024.0:
            return f"{x:.0f} {unit}" if unit == "B" else f"{x:.1f} {unit}"
        x /= 1024.0
    return f"{x:.1f} PB"

def open_path(path: str) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)
        elif sys.platform == "darwin":
            QtCore.QProcess.startDetached("open", [path])
        else:
            QtCore.QProcess.startDetached("xdg-open", [path])
    except Exception:
        pass

def _log_message(data_dir: str, msg: str) -> None:
    try:
        ensure_dir(data_dir)
        with open(os.path.join(data_dir, LOG_FILENAME), "a", encoding="utf-8") as f:
            f.write(f"{now_iso()}  {msg}\n")
    except Exception:
        pass

# -- Диалоги (ProjectDialog, ReleaseDialog, TestCaseDialog, RunDialog, TextDialog, HelpDialog) --

class TextDialog(QtWidgets.QDialog):
    def __init__(self, title: str, label: str, text: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(620, 400)
        self.edit = QtWidgets.QPlainTextEdit()
        self.edit.setPlainText(text)
        lbl = QtWidgets.QLabel(label)
        btn_ok = QtWidgets.QPushButton("Готово")
        btn_cancel = QtWidgets.QPushButton("Отмена")
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(btn_ok)
        btns.addWidget(btn_cancel)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(lbl)
        lay.addWidget(self.edit, 1)
        lay.addLayout(btns)

    def value(self) -> str:
        return self.edit.toPlainText().strip()

class ProjectDialog(QtWidgets.QDialog):
    def __init__(self, title: str, name: str = "", description: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(520, 220)
        self.name = QtWidgets.QLineEdit(name)
        self.desc = QtWidgets.QPlainTextEdit(description)
        form = QtWidgets.QFormLayout()
        form.addRow("Имя проекта", self.name)
        form.addRow("Описание (необязательно)", self.desc)
        ok = QtWidgets.QPushButton("Сохранить")
        cancel = QtWidgets.QPushButton("Отмена")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(form)
        lay.addLayout(btns)

    def get(self) -> Tuple[str, str]:
        return self.name.text().strip(), self.desc.toPlainText().strip()

class ReleaseDialog(QtWidgets.QDialog):
    def __init__(self, title: str, name: str = "", description: str = "", start_date: str = "", end_date: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 260)
        self.name = QtWidgets.QLineEdit(name)
        self.desc = QtWidgets.QPlainTextEdit(description)
        self.start = QtWidgets.QLineEdit(start_date)
        self.end = QtWidgets.QLineEdit(end_date)
        form = QtWidgets.QFormLayout()
        form.addRow("Имя релиза", self.name)
        form.addRow("Описание (необязательно)", self.desc)
        form.addRow("Дата начала", self.start)
        form.addRow("Дата окончания", self.end)
        ok = QtWidgets.QPushButton("Сохранить")
        cancel = QtWidgets.QPushButton("Отмена")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(form)
        lay.addLayout(btns)

    def get(self) -> Tuple[str, str, str, str]:
        return (self.name.text().strip(), self.desc.toPlainText().strip(), self.start.text().strip(), self.end.text().strip())

class TestCaseDialog(QtWidgets.QDialog):
    def __init__(self, title: str, suite: str = "", name: str = "", external_id: str = "", description: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(600, 280)
        self.suite = QtWidgets.QLineEdit(suite)
        self.name = QtWidgets.QLineEdit(name)
        self.external_id = QtWidgets.QLineEdit(external_id)
        self.desc = QtWidgets.QPlainTextEdit(description)
        form = QtWidgets.QFormLayout()
        form.addRow("Набор (suite)", self.suite)
        form.addRow("Название теста", self.name)
        form.addRow("Внешний идентификатор (если есть)", self.external_id)
        form.addRow("Описание (необязательно)", self.desc)
        ok = QtWidgets.QPushButton("Сохранить")
        cancel = QtWidgets.QPushButton("Отмена")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(form)
        lay.addLayout(btns)

    def get(self) -> Tuple[str, str, str, str]:
        return (self.suite.text().strip(), self.name.text().strip(), self.external_id.text().strip(), self.desc.toPlainText().strip())

class RunDialog(QtWidgets.QDialog):
    def __init__(
        self,
        title: str,
        status: str = "PASS",
        executed_at: str = "",
        build: str = "",
        environment: str = "",
        executor: str = "",
        duration_sec: float = 0.0,
        comment: str = "",
        meta_json: str = "{}",
        parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 420)

        self.status = QtWidgets.QComboBox()
        for code, display in STATUS_CHOICES:
            self.status.addItem(display, code)
        found_index = None
        for i in range(self.status.count()):
            if self.status.itemData(i) == (status or "PASS"):
                found_index = i
                break
        if found_index is not None:
            self.status.setCurrentIndex(found_index)

        self.executed_at = QtWidgets.QLineEdit(executed_at or now_iso())
        self.build = QtWidgets.QLineEdit(build)
        self.environment = QtWidgets.QLineEdit(environment)
        self.executor = QtWidgets.QLineEdit(executor)
        self.duration = QtWidgets.QDoubleSpinBox()
        self.duration.setMinimum(0.0)
        self.duration.setMaximum(10_000_000.0)
        self.duration.setDecimals(3)
        self.duration.setValue(float(duration_sec or 0.0))
        self.comment = QtWidgets.QPlainTextEdit(comment)
        self.meta = QtWidgets.QPlainTextEdit(meta_json if meta_json else "{}")

        form = QtWidgets.QFormLayout()
        form.addRow("Статус", self.status)
        form.addRow("Время (ISO)", self.executed_at)
        form.addRow("Сборка", self.build)
        form.addRow("Окружение", self.environment)
        form.addRow("Исполнитель", self.executor)
        form.addRow("Длительность (сек)", self.duration)
        form.addRow("Комментарий", self.comment)
        form.addRow("Meta (JSON)", self.meta)

        ok = QtWidgets.QPushButton("Сохранить")
        cancel = QtWidgets.QPushButton("Отмена")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)

        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(ok)
        btns.addWidget(cancel)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(form)
        lay.addLayout(btns)

    def get(self) -> Tuple[str, str, str, str, str, float, str, Dict[str, Any]]:
        status_code = self.status.currentData() if self.status.currentData() else "PASS"
        meta_text = self.meta.toPlainText().strip() or "{}"
        try:
            meta = json.loads(meta_text)
            if not isinstance(meta, dict):
                meta = {"value": meta}
        except Exception:
            meta = {"_raw": meta_text}
        return (
            str(status_code),
            self.executed_at.text().strip(),
            self.build.text().strip(),
            self.environment.text().strip(),
            self.executor.text().strip(),
            float(self.duration.value()),
            self.comment.toPlainText().strip(),
            meta,
        )

class HelpDialog(QtWidgets.QDialog):
    def __init__(self, markdown: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Справка и подсказки")
        self.resize(900, 600)
        self.list = QtWidgets.QListWidget()
        self.browser = QtWidgets.QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.anchorClicked.connect(lambda url: QtGui.QDesktopServices.openUrl(url))
        splitter = QtWidgets.QSplitter()
        splitter.addWidget(self.list)
        splitter.addWidget(self.browser)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(splitter)
        self.sections = []
        self._parse_markdown(markdown)
        for sid, title, _ in self.sections:
            item = QtWidgets.QListWidgetItem(title)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, sid)
            self.list.addItem(item)
        self.list.currentItemChanged.connect(self.on_section_selected)
        if self.sections:
            self.list.setCurrentRow(0)

    def _parse_markdown(self, md: str) -> None:
        matches = list(re.finditer(r'(?m)^(\d+)\)\s*(.+)$', md))
        if not matches:
            html = self._md_to_html(md)
            self.sections.append(("s0", "Справка", html))
            self.browser.setHtml(html)
            return
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i+1].start() if i+1 < len(matches) else len(md)
            title = m.group(2).strip()
            content = md[start:end].strip()
            sid = f"s{m.group(1)}"
            html = f'<h2 id="{sid}">{m.group(1)}) {self._escape_html(title)}</h2>' + self._md_to_html(content)
            html = re.sub(r'(https?://[^\s<]+)', r'<a href="\1">\1</a>', html)
            self.sections.append((sid, f"{m.group(1)}) {title}", html))

    def _escape_html(self, s: str) -> str:
        return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    def _md_to_html(self, text: str) -> str:
        lines = text.strip().splitlines()
        out = []
        in_list = False
        para_lines = []
        i = 0
        while i < len(lines):
            line = lines[i].rstrip()
            if line.strip().startswith('- '):
                if para_lines:
                    out.append("<p>" + "<br>".join(self._escape_html(l) for l in para_lines) + "</p>")
                    para_lines = []
                if not in_list:
                    out.append("<ul>")
                    in_list = True
                out.append("<li>" + self._escape_html(line.strip()[2:]) + "</li>")
            elif line.strip() == "":
                if in_list:
                    out.append("</ul>")
                    in_list = False
                if para_lines:
                    out.append("<p>" + "<br>".join(self._escape_html(l) for l in para_lines) + "</p>")
                    para_lines = []
            else:
                para_lines.append(line)
            i += 1
        if in_list:
            out.append("</ul>")
        if para_lines:
            out.append("<p>" + "<br>".join(self._escape_html(l) for l in para_lines) + "</p>")
        return "\n".join(out)

    def on_section_selected(self, current: Optional[QtWidgets.QListWidgetItem], previous: Optional[QtWidgets.QListWidgetItem]) -> None:
        if not current:
            return
        sid = current.data(QtCore.Qt.ItemDataRole.UserRole)
        for s in self.sections:
            if s[0] == sid:
                self.browser.setHtml(s[2])
                self.browser.scrollToAnchor(sid)
                return

# -- Database class --

class TEMDatabase:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.migrate()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def migrate(self) -> None:
        c = self.conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS projects(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS releases(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            start_date TEXT NOT NULL DEFAULT '',
            end_date TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(project_id, name),
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS testcases(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            release_id INTEGER NOT NULL,
            suite TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL,
            external_id TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(release_id, suite, name),
            FOREIGN KEY(release_id) REFERENCES releases(id) ON DELETE CASCADE
        );
        """)
        try:
            cols = [r["name"] for r in self.q("PRAGMA table_info(testcases);")]
            if "last_status" not in cols:
                self.exec("ALTER TABLE testcases ADD COLUMN last_status TEXT NOT NULL DEFAULT 'UNKNOWN';")
        except Exception:
            pass
        c.execute("""
        CREATE TABLE IF NOT EXISTS runs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            testcase_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'PASS',
            executed_at TEXT NOT NULL,
            build TEXT NOT NULL DEFAULT '',
            environment TEXT NOT NULL DEFAULT '',
            executor TEXT NOT NULL DEFAULT '',
            duration_sec REAL NOT NULL DEFAULT 0,
            comment TEXT NOT NULL DEFAULT '',
            meta_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(testcase_id) REFERENCES testcases(id) ON DELETE CASCADE
        );
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS attachments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            kind TEXT NOT NULL DEFAULT 'file',
            original_name TEXT NOT NULL,
            stored_relpath TEXT NOT NULL,
            mime TEXT NOT NULL DEFAULT '',
            size_bytes INTEGER NOT NULL DEFAULT 0,
            sha256 TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
        );
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_runs_testcase_id ON runs(testcase_id);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_runs_filters ON runs(status, build, environment, executor);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_attachments_run_id ON attachments(run_id);")
        self.conn.commit()

    def exec(self, sql: str, params: Tuple[Any, ...] = ()) -> sqlite3.Cursor:
        cur = self.conn.cursor()
        cur.execute(sql, params)
        self.conn.commit()
        return cur

    def q(self, sql: str, params: Tuple[Any, ...] = ()) -> List[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return list(cur.fetchall())

    def q1(self, sql: str, params: Tuple[Any, ...] = ()) -> Optional[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return cur.fetchone()

    # CRUD methods (как прежде)
    def list_projects(self) -> List[sqlite3.Row]:
        return self.q("SELECT * FROM projects ORDER BY name;")
    def list_releases(self, project_id: int) -> List[sqlite3.Row]:
        return self.q("SELECT * FROM releases WHERE project_id=? ORDER BY created_at DESC, name;", (project_id,))
    def list_testcases(self, release_id: int) -> List[sqlite3.Row]:
        return self.q("SELECT * FROM testcases WHERE release_id=? ORDER BY suite, name;", (release_id,))
    def get_release_path_info(self, release_id: int) -> Tuple[str, str, str]:
        r = self.q1("""
        SELECT releases.name AS rname, projects.name AS pname
        FROM releases
        JOIN projects ON projects.id=releases.project_id
        WHERE releases.id=?;
        """, (release_id,))
        if not r:
            return ("", "", "")
        return (r["pname"], r["rname"], f"{safe_filename(r['pname'])}/{safe_filename(r['rname'])}")
    def create_project(self, name: str, description: str = "") -> int:
        cur = self.exec("INSERT INTO projects(name, description, created_at) VALUES(?,?,?);", (name.strip(), description.strip(), now_iso()))
        return int(cur.lastrowid)
    def update_project(self, project_id: int, name: str, description: str) -> None:
        self.exec("UPDATE projects SET name=?, description=? WHERE id=?;", (name.strip(), description.strip(), project_id))
    def delete_project(self, project_id: int) -> None:
        self.exec("DELETE FROM projects WHERE id=?;", (project_id,))
    def create_release(self, project_id: int, name: str, description: str = "", start_date: str = "", end_date: str = "") -> int:
        cur = self.exec("INSERT INTO releases(project_id, name, description, start_date, end_date, created_at) VALUES(?,?,?,?,?,?);",
                        (project_id, name.strip(), description.strip(), start_date.strip(), end_date.strip(), now_iso()))
        return int(cur.lastrowid)
    def update_release(self, release_id: int, name: str, description: str, start_date: str, end_date: str) -> None:
        self.exec("UPDATE releases SET name=?, description=?, start_date=?, end_date=? WHERE id=?;", (name.strip(), description.strip(), start_date.strip(), end_date.strip(), release_id))
    def delete_release(self, release_id: int) -> None:
        self.exec("DELETE FROM releases WHERE id=?;", (release_id,))
    def create_testcase(self, release_id: int, suite: str, name: str, external_id: str = "", description: str = "") -> int:
        cur = self.exec("INSERT INTO testcases(release_id, suite, name, external_id, description, created_at) VALUES(?,?,?,?,?,?);",
                        (release_id, suite.strip(), name.strip(), external_id.strip(), description.strip(), now_iso()))
        return int(cur.lastrowid)
    def update_testcase(self, testcase_id: int, suite: str, name: str, external_id: str, description: str) -> None:
        self.exec("UPDATE testcases SET suite=?, name=?, external_id=?, description=? WHERE id=?;", (suite.strip(), name.strip(), external_id.strip(), description.strip(), testcase_id))
    def delete_testcase(self, testcase_id: int) -> None:
        self.exec("DELETE FROM testcases WHERE id=?;", (testcase_id,))
    def create_run(self, testcase_id: int, status: str, executed_at: str, build: str, environment: str, executor: str, duration_sec: float, comment: str, meta: Dict[str, Any]) -> int:
        cur = self.exec("INSERT INTO runs(testcase_id, status, executed_at, build, environment, executor, duration_sec, comment, meta_json) VALUES(?,?,?,?,?,?,?,?,?);",
                        (testcase_id, status, executed_at, build.strip(), environment.strip(), executor.strip(), float(duration_sec), comment.strip(), json.dumps(meta, ensure_ascii=False)))
        return int(cur.lastrowid)
    def update_run(self, run_id: int, status: str, executed_at: str, build: str, environment: str, executor: str, duration_sec: float, comment: str, meta: Dict[str, Any]) -> None:
        self.exec("UPDATE runs SET status=?, executed_at=?, build=?, environment=?, executor=?, duration_sec=?, comment=?, meta_json=? WHERE id=?;",
                  (status, executed_at, build.strip(), environment.strip(), executor.strip(), float(duration_sec), comment.strip(), json.dumps(meta, ensure_ascii=False), run_id))
    def delete_run(self, run_id: int) -> None:
        self.exec("DELETE FROM runs WHERE id=?;", (run_id,))
    def list_runs_for_testcase(self, testcase_id: int) -> List[sqlite3.Row]:
        return self.q("SELECT * FROM runs WHERE testcase_id=? ORDER BY executed_at DESC, id DESC;", (testcase_id,))
    def list_runs_for_release(self, release_id: int, status: str = "", build: str = "", environment: str = "", executor: str = "", text: str = "") -> List[sqlite3.Row]:
        sql = """
        SELECT runs.*, testcases.suite AS suite, testcases.name AS tc_name, testcases.external_id AS external_id
        FROM runs
        JOIN testcases ON testcases.id=runs.testcase_id
        WHERE testcases.release_id=?
        """
        params: List[Any] = [release_id]
        if status:
            sql += " AND runs.status=?"
            params.append(status)
        if build:
            sql += " AND runs.build LIKE ?"
            params.append(f"%{build}%")
        if environment:
            sql += " AND runs.environment LIKE ?"
            params.append(f"%{environment}%")
        if executor:
            sql += " AND runs.executor LIKE ?"
            params.append(f"%{executor}%")
        if text.strip():
            t = f"%{text.strip()}%"
            sql += " AND (testcases.suite LIKE ? OR testcases.name LIKE ? OR testcases.external_id LIKE ? OR runs.comment LIKE ?)"
            params.extend([t, t, t, t])
        sql += " ORDER BY runs.executed_at DESC, runs.id DESC"
        return self.q(sql, tuple(params))
    def get_testcase_full(self, testcase_id: int) -> Optional[sqlite3.Row]:
        return self.q1("""
        SELECT testcases.*, releases.name AS release_name, projects.name AS project_name
        FROM testcases
        JOIN releases ON releases.id=testcases.release_id
        JOIN projects ON projects.id=releases.project_id
        WHERE testcases.id=?;
        """, (testcase_id,))
    def get_run_full(self, run_id: int) -> Optional[sqlite3.Row]:
        return self.q1("""
        SELECT runs.*, testcases.suite AS suite, testcases.name AS tc_name, testcases.external_id AS external_id,
               releases.id AS release_id, releases.name AS release_name, projects.name AS project_name
        FROM runs
        JOIN testcases ON testcases.id=runs.testcase_id
        JOIN releases ON releases.id=testcases.release_id
        JOIN projects ON projects.id=releases.project_id
        WHERE runs.id=?;
        """, (run_id,))
    def add_attachment(self, run_id: int, kind: str, original_name: str, stored_relpath: str, mime: str, size_bytes: int, sha256: str, note: str = "") -> int:
        cur = self.exec("INSERT INTO attachments(run_id, kind, original_name, stored_relpath, mime, size_bytes, sha256, created_at, note) VALUES(?,?,?,?,?,?,?,?,?);",
                        (run_id, kind, original_name, stored_relpath, mime, int(size_bytes), sha256, now_iso(), note.strip()))
        return int(cur.lastrowid)
    def update_attachment_note(self, attachment_id: int, note: str) -> None:
        self.exec("UPDATE attachments SET note=? WHERE id=?;", (note.strip(), attachment_id))
    def delete_attachment(self, attachment_id: int) -> None:
        self.exec("DELETE FROM attachments WHERE id=?;", (attachment_id,))
    def list_attachments(self, run_id: int) -> List[sqlite3.Row]:
        return self.q("SELECT * FROM attachments WHERE run_id=? ORDER BY created_at DESC, id DESC;", (run_id,))
    def distinct_run_values(self, release_id: int, column: str) -> List[str]:
        if column not in {"build", "environment", "executor", "status"}:
            return []
        rows = self.q(f"""
        SELECT DISTINCT runs.{column} AS v
        FROM runs
        JOIN testcases ON testcases.id=runs.testcase_id
        WHERE testcases.release_id=?
        ORDER BY v;
        """, (release_id,))
        vals = [r["v"] for r in rows if r["v"] is not None and str(r["v"]).strip() != ""]
        return vals

# -- UI models --

class AttachmentDropList(QtWidgets.QListWidget):
    filesDropped = QtCore.Signal(list)
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setAlternatingRowColors(True)
    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        md = event.mimeData()
        if md.hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()
    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
        md = event.mimeData()
        if md.hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()
    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        md = event.mimeData()
        if not md.hasUrls():
            return
        paths = []
        for u in md.urls():
            p = u.toLocalFile()
            if p and os.path.exists(p):
                paths.append(p)
        if paths:
            self.filesDropped.emit(paths)
        event.acceptProposedAction()

class RunTableModel(QtCore.QAbstractTableModel):
    HEADERS = ["№", "Время", "Статус", "Сборка", "Окружение", "Исполнитель", "Длительность, сек", "Набор", "Тест", "Внешний ID", "Комментарий"]
    EDITABLE_COLS = {1, 2, 3, 4, 5, 6, 10}
    def __init__(self):
        super().__init__()
        self.rows: List[Dict[str, Any]] = []
        self.on_row_edited = None
    def set_rows(self, rows: List[Mapping]) -> None:
        self.beginResetModel()
        new_rows: List[Dict[str, Any]] = []
        for r in rows:
            try:
                if isinstance(r, sqlite3.Row):
                    new_rows.append(dict(r))
                elif isinstance(r, dict):
                    new_rows.append(r)
                else:
                    new_rows.append(dict(r))
            except Exception:
                new_rows.append({})
        self.rows = new_rows
        self.endResetModel()
    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        return len(self.rows)
    def columnCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        return len(self.HEADERS)
    def headerData(self, section: int, orientation: QtCore.Qt.Orientation, role: int = QtCore.Qt.ItemDataRole.DisplayRole):
        if role != QtCore.Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == QtCore.Qt.Orientation.Horizontal:
            if 0 <= section < len(self.HEADERS):
                return self.HEADERS[section]
            return None
        return str(section + 1)
    
    def flags(self, index: QtCore.QModelIndex):
        if not index.isValid():
            return QtCore.Qt.ItemFlag.NoItemFlags
        f = super().flags(index)
        if index.column() in self.EDITABLE_COLS:
            f |= QtCore.Qt.ItemFlag.ItemIsEditable
        return f
    
    def setData(self, index: QtCore.QModelIndex, value, role: int = QtCore.Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or role != QtCore.Qt.ItemDataRole.EditRole:
            return False

        row = index.row()
        col = index.column()
        if not (0 <= row < len(self.rows)):
            return False

        keys = ["id", "executed_at", "status", "build", "environment", "executor", "duration_sec", "suite", "tc_name", "external_id", "comment"]
        key = keys[col] if col < len(keys) else ""
        if not key or col not in self.EDITABLE_COLS:
            return False

        v = value

        if key == "duration_sec":
            try:
                v = float(str(value).replace(",", "."))
            except Exception:
                return False

        if key == "status":
            # В таблице отображается “PASS/FAIL/BLOCKED” как текст (или локализованно),
            # поэтому аккуратно приводим к коду.
            txt = str(value).strip().upper()
            mapping = {disp.upper(): code for code, disp in STATUS_CHOICES}
            v = mapping.get(txt, txt)  # если ввели PASS/FAIL напрямую — тоже ок

        self.rows[row][key] = v
        self.dataChanged.emit(index, index, [QtCore.Qt.ItemDataRole.DisplayRole])

        # Сообщаем окну: “эту строку надо сохранить”
        if callable(self.on_row_edited):
            try:
                self.on_row_edited(dict(self.rows[row]))
            except Exception:
                pass

        return True

    def data(self, index: QtCore.QModelIndex, role: int = QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r = self.rows[index.row()]
        c = index.column()
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            keys = ["id", "executed_at", "status", "build", "environment", "executor", "duration_sec", "suite", "tc_name", "external_id", "comment"]
            key = keys[c] if c < len(keys) else ""
            v = r.get(key, "") if isinstance(r, dict) else ""
            if key == "duration_sec":
                try:
                    return f"{float(v):.3f}"
                except Exception:
                    return str(v)
            if key == "status":
                code = str(v or "")
                for sc, disp in STATUS_CHOICES:
                    if sc == code:
                        return disp
                return code
            return str(v) if v is not None else ""
        if role == QtCore.Qt.ItemDataRole.ForegroundRole:
            status = str(r.get("status", "")).upper()
            if status == "FAIL":
                return QtGui.QBrush(QtGui.QColor(180, 0, 0))
            if status == "PASS":
                return QtGui.QBrush(QtGui.QColor(0, 120, 0))
            if status == "BLOCKED":
                return QtGui.QBrush(QtGui.QColor(140, 90, 0))
        return None
    def get_row(self, row: int) -> Optional[Dict[str, Any]]:
        if 0 <= row < len(self.rows):
            return self.rows[row]
        return None

# -- MainWindow (с человеческими текстами) --

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, db: TEMDatabase, data_dir: str, storage_dir: str, help_markdown: str):
        super().__init__()
        self.db = db
        self.data_dir = data_dir
        self.storage_dir = storage_dir
        self.help_markdown = help_markdown

        self.setWindowTitle(APP_NAME)
        self.resize(1400, 820)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.on_tree_context_menu)
        self.tree.itemSelectionChanged.connect(self.on_tree_selection_changed)

        self.run_model = RunTableModel()
        self.run_model.on_row_edited = self._save_edited_run_row
        self.run_view = QtWidgets.QTableView()
        self.run_view.setModel(self.run_model)
        self.run_view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.run_view.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.run_view.setSortingEnabled(False)
        self.run_view.horizontalHeader().setStretchLastSection(True)
        self.run_view.doubleClicked.connect(self.on_edit_run_from_table)
        self.run_view.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
            | QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed
            | QtWidgets.QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.run_view.selectionModel().selectionChanged.connect(self.on_run_selected)

        self.filter_status = QtWidgets.QComboBox()
        self.filter_status.addItem("", "")
        self.filter_build = QtWidgets.QLineEdit()
        self.filter_env = QtWidgets.QLineEdit()
        self.filter_exec = QtWidgets.QLineEdit()
        self.filter_text = QtWidgets.QLineEdit()
        self.btn_apply_filters = QtWidgets.QPushButton("Применить")
        self.btn_clear_filters = QtWidgets.QPushButton("Сбросить")
        self.btn_apply_filters.clicked.connect(self.on_apply_filters_clicked)
        self.btn_clear_filters.clicked.connect(self.on_clear_filters_clicked)

        self.tc_label = QtWidgets.QLabel("Тест-кейс: не выбран")
        self.run_label = QtWidgets.QLabel("Прогон: не выбран")

        self.attach_list = AttachmentDropList()
        self.attach_list.filesDropped.connect(self.on_attachments_dropped)
        self.attach_list.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.attach_list.customContextMenuRequested.connect(self.on_attachments_context_menu)

        self.btn_add_files = QtWidgets.QPushButton("Добавить файлы…")
        self.btn_add_files.clicked.connect(self.on_add_files_clicked)
        self.btn_open_storage = QtWidgets.QPushButton("Открыть папку с вложениями")
        self.btn_open_storage.clicked.connect(lambda: open_path(self.storage_dir))

        self.details = QtWidgets.QPlainTextEdit()
        self.details.setReadOnly(True)

        right = QtWidgets.QWidget()
        right_lay = QtWidgets.QVBoxLayout(right)

        filt = QtWidgets.QGroupBox("Фильтры для прогонов в релизе")
        filt_lay = QtWidgets.QGridLayout(filt)
        filt_lay.addWidget(QtWidgets.QLabel("Статус"), 0, 0)
        filt_lay.addWidget(self.filter_status, 0, 1)
        filt_lay.addWidget(QtWidgets.QLabel("Сборка — поиск по подстроке"), 0, 2)
        filt_lay.addWidget(self.filter_build, 0, 3)
        filt_lay.addWidget(QtWidgets.QLabel("Окружение — поиск по подстроке"), 1, 0)
        filt_lay.addWidget(self.filter_env, 1, 1)
        filt_lay.addWidget(QtWidgets.QLabel("Исполнитель — поиск по подстроке"), 1, 2)
        filt_lay.addWidget(self.filter_exec, 1, 3)
        filt_lay.addWidget(QtWidgets.QLabel("Текст (набор / тест / внешний ID / комментарий) — по подстроке"), 2, 0)
        filt_lay.addWidget(self.filter_text, 2, 1, 1, 3)
        filt_lay.addWidget(self.btn_apply_filters, 3, 2)
        filt_lay.addWidget(self.btn_clear_filters, 3, 3)

        right_lay.addWidget(filt)
        right_lay.addWidget(self.run_view, 2)
        right_lay.addWidget(self.tc_label)
        right_lay.addWidget(self.run_label)

        att = QtWidgets.QGroupBox("Вложения выбранного прогона — перетаскивайте файлы сюда")
        att_lay = QtWidgets.QVBoxLayout(att)
        att_lay.addWidget(self.attach_list, 1)
        btnrow = QtWidgets.QHBoxLayout()
        btnrow.addWidget(self.btn_add_files)
        btnrow.addStretch(1)
        btnrow.addWidget(self.btn_open_storage)
        att_lay.addLayout(btnrow)
        right_lay.addWidget(att, 2)

        det = QtWidgets.QGroupBox("Информация")
        det_lay = QtWidgets.QVBoxLayout(det)
        det_lay.addWidget(self.details, 1)
        right_lay.addWidget(det, 1)

        splitter = QtWidgets.QSplitter()
        splitter.addWidget(self.tree)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        self._selected_project_id: Optional[int] = None
        self._selected_release_id: Optional[int] = None
        self._selected_testcase_id: Optional[int] = None
        self._selected_run_id: Optional[int] = None

        self.statusBar().showMessage("Готово — можно работать.")
        self.build_menu()
        self.refresh_filters_source()
        self.refresh_tree()

    def build_menu(self) -> None:
        mb = self.menuBar()
        m_file = mb.addMenu("Файл")
        a_open_data = m_file.addAction("Открыть папку с данными (tem_data)")
        a_open_data.triggered.connect(lambda: open_path(self.data_dir))
        a_open_storage = m_file.addAction("Открыть папку с вложениями")
        a_open_storage.triggered.connect(lambda: open_path(self.storage_dir))
        m_file.addSeparator()
        a_exit = m_file.addAction("Выйти")
        a_exit.triggered.connect(self.close)

        m_import = mb.addMenu("Импорт")
        a_junit = m_import.addAction("Импортировать JUnit XML…")
        a_junit.triggered.connect(self.import_junit)

        m_export = mb.addMenu("Экспорт")
        a_zip = m_export.addAction("Экспорт — ZIP выбранного прогона…")
        a_zip.triggered.connect(self.export_run_zip)
        a_pdf = m_export.addAction("Экспорт — PDF отчёт по релизу…")
        a_pdf.triggered.connect(self.export_release_pdf)
        a_tc_txt = m_export.addAction("Экспорт — тест-кейсы в TXT…")
        a_tc_txt.triggered.connect(self.export_testcases_txt)

        m_help = mb.addMenu("Помощь")
        a_help = m_help.addAction("Открыть справку")
        a_help.triggered.connect(self.show_help_dialog)
        a_about = m_help.addAction("О программе")
        a_about.triggered.connect(self.about)

        tb = self.addToolBar("Main")
        tb.setMovable(False)
        btn_new_proj = QtGui.QAction("Новый проект…", self)
        btn_new_rel = QtGui.QAction("Новый релиз…", self)
        btn_new_tc = QtGui.QAction("Новый тест-кейс…", self)
        btn_new_run = QtGui.QAction("Новый прогон…", self)
        btn_refresh = QtGui.QAction("Обновить", self)
        btn_new_proj.triggered.connect(self.create_project)
        btn_new_rel.triggered.connect(self.create_release)
        btn_new_tc.triggered.connect(self.create_testcase)
        btn_new_run.triggered.connect(self.create_run)
        btn_refresh.triggered.connect(self.refresh_all)
        tb.addAction(btn_new_proj)
        tb.addAction(btn_new_rel)
        tb.addAction(btn_new_tc)
        tb.addAction(btn_new_run)
        tb.addSeparator()
        tb.addAction(btn_refresh)

    def on_clear_filters_clicked(self) -> None:
        fw = QtWidgets.QApplication.focusWidget()
        if fw is not None and self.run_view.isAncestorOf(fw):
            self.run_view.closeEditor(
                fw,
                QtWidgets.QAbstractItemDelegate.EndEditHint.SubmitModelCache
            )
        self.clear_filters()
        
    def about(self) -> None:
        QtWidgets.QMessageBox.information(self, APP_NAME, "Привет! Это небольшая утилита для хранения прогонов и файлов.\n\nПодробную инструкцию можно открыть через Помощь → Открыть справку.")

    def show_help_dialog(self) -> None:
        dlg = HelpDialog(self.help_markdown, parent=self)
        dlg.exec()

    # ---- Импорт JUnit (человеческие сообщения) ----
    def import_junit(self) -> None:
        rid = self.require_release()
        if not rid:
            QtWidgets.QMessageBox.warning(self, "Внимание", "Пожалуйста, сначала выберите релиз, в который нужно импортировать результаты.")
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Выберите JUnit XML для импорта", "", "XML (*.xml);;Все файлы (*.*)")
        if not path:
            return
        try:
            tree = ET.parse(path)
            root = tree.getroot()
            imported = {"testcases": 0, "runs": 0}
            executed_at = now_iso()
            build_guess = os.path.splitext(os.path.basename(path))[0]

            def parse_case(el: ET.Element, suite_name: str) -> None:
                name = el.attrib.get("name", "").strip() or "Unnamed"
                classname = el.attrib.get("classname", "").strip()
                suite = suite_name.strip() or classname.strip()
                time_s = el.attrib.get("time", "0") or "0"
                try:
                    duration = float(time_s)
                except Exception:
                    duration = 0.0

                status = "PASS"
                comment = ""
                if el.find("failure") is not None:
                    status = "FAIL"
                    f = el.find("failure")
                    comment = (f.attrib.get("message", "") if f is not None else "") or ""
                elif el.find("error") is not None:
                    status = "FAIL"
                    er = el.find("error")
                    comment = (er.attrib.get("message", "") if er is not None else "") or ""
                elif el.find("skipped") is not None:
                    status = "SKIPPED"

                tc = self.db.q1("SELECT * FROM testcases WHERE release_id=? AND suite=? AND name=?;", (rid, suite, name))
                if not tc:
                    tcid = self.db.create_testcase(rid, suite, name, external_id="", description=f"Imported from JUnit: {os.path.basename(path)}")
                    imported["testcases"] += 1
                else:
                    tcid = int(tc["id"])

                meta = {"source": "junit", "file": os.path.basename(path), "classname": classname}
                run_id = self.db.create_run(
                    tcid,
                    status=status,
                    executed_at=executed_at,
                    build=build_guess,
                    environment="",
                    executor="",
                    duration_sec=duration,
                    comment=comment,
                    meta=meta,
                )
                imported["runs"] += 1

            if root.tag.endswith("testsuite"):
                suite_name = root.attrib.get("name", "").strip()
                for tc_el in root.findall(".//testcase"):
                    parse_case(tc_el, suite_name)
            else:
                for suite_el in root.findall(".//testsuite"):
                    suite_name = suite_el.attrib.get("name", "").strip()
                    for tc_el in suite_el.findall("testcase"):
                        parse_case(tc_el, suite_name)

            self.refresh_tree()
            self.refresh_runs()
            QtWidgets.QMessageBox.information(self, "Импорт завершён", f"Готово — импортировано тест-кейсов: {imported['testcases']}, прогоны: {imported['runs']}.")
            self.statusBar().showMessage("Импорт JUnit завершён.", 3000)
        except Exception as e:
            self.show_error("Ошибка при импорте JUnit", e)
    # ------------------------------------------------------------

    # остальные методы: refresh_all, clear_filters, show_error, refresh_tree, selection handling,
    # CRUD для projects/releases/testcases/runs и работа с вложениями — те же, что были в предыдущей версии,
    # но все сообщения сделаны более понятными и дружелюбными.

    def refresh_all(self) -> None:
        self.refresh_tree()
        self.refresh_runs()
        self.refresh_attachments()
        self.refresh_details()
        self.statusBar().showMessage("Обновлено — всё актуально.", 3000)

    def clear_filters(self) -> None:
        self.filter_status.blockSignals(True)
        self.filter_status.clear()
        self.filter_status.addItem("", "")
        self.filter_build.setText("")
        self.filter_env.setText("")
        self.filter_exec.setText("")
        self.filter_text.setText("")
        self.filter_status.blockSignals(False)
        self.refresh_runs()

    def show_error(self, title: str, exc: Exception) -> None:
        tb = traceback.format_exc()
        _log_message(self.data_dir, f"{title}: {type(exc).__name__}: {exc}")
        _log_message(self.data_dir, tb)
        dlg = TextDialog(title, "Произошла ошибка. Подробности ниже:", f"{type(exc).__name__}: {exc}\n\n{tb}", self)
        dlg.exec()

    def refresh_tree(self) -> None:
        try:
            self.tree.clear()
            root = QtWidgets.QTreeWidgetItem([APP_NAME])
            root.setData(0, QtCore.Qt.ItemDataRole.UserRole, {"type": "root"})
            self.tree.addTopLevelItem(root)
            root.setExpanded(True)

            for p in self.db.list_projects():
                pitem = QtWidgets.QTreeWidgetItem([p["name"]])
                pitem.setData(0, QtCore.Qt.ItemDataRole.UserRole, {"type": "project", "id": p["id"]})
                root.addChild(pitem)

                for r in self.db.list_releases(p["id"]):
                    rname = r["name"]
                    if r["start_date"] or r["end_date"]:
                        rname = f"{rname} [{r['start_date']}..{r['end_date']}]".strip()
                    ritem = QtWidgets.QTreeWidgetItem([rname])
                    ritem.setData(0, QtCore.Qt.ItemDataRole.UserRole, {"type": "release", "id": r["id"], "project_id": p["id"]})
                    pitem.addChild(ritem)

                    for tc in self.db.list_testcases(r["id"]):
                        label = tc["name"]
                        if tc["suite"]:
                            label = f"{tc['suite']} :: {tc['name']}"
                        if tc["external_id"]:
                            label = f"{label} ({tc['external_id']})"
                        tcitem = QtWidgets.QTreeWidgetItem([label])
                        tcitem.setData(0, QtCore.Qt.ItemDataRole.UserRole, {"type": "testcase", "id": tc["id"], "release_id": r["id"]})
                        ritem.addChild(tcitem)

            self.tree.expandToDepth(1)
        except Exception as e:
            self.show_error("Ошибка обновления дерева", e)

    def select_testcase_in_tree(self, testcase_id: int) -> bool:
        root = self.tree.topLevelItem(0)
        if not root:
            return False
        stack = [root]
        while stack:
            it = stack.pop()
            data = it.data(0, QtCore.Qt.ItemDataRole.UserRole)
            if isinstance(data, dict) and data.get("type") == "testcase" and int(data.get("id", 0)) == int(testcase_id):
                self.tree.setCurrentItem(it)   # вызовет on_tree_selection_changed()
                return True
            for i in range(it.childCount() - 1, -1, -1):
                stack.append(it.child(i))
        return False

    def selected_node(self) -> Dict[str, Any]:
        it = self.tree.currentItem()
        if not it:
            return {"type": "none"}
        data = it.data(0, QtCore.Qt.ItemDataRole.UserRole)
        return data if isinstance(data, dict) else {"type": "none"}

    def on_tree_selection_changed(self) -> None:
        node = self.selected_node()
        self._selected_project_id = None
        self._selected_release_id = None
        self._selected_testcase_id = None
        self._selected_run_id = None

        if node.get("type") == "project":
            self._selected_project_id = int(node["id"])
        elif node.get("type") == "release":
            self._selected_project_id = int(node["project_id"])
            self._selected_release_id = int(node["id"])
        elif node.get("type") == "testcase":
            self._selected_testcase_id = int(node["id"])
            self._selected_release_id = int(node["release_id"])

        self.refresh_filters_source()
        self.refresh_runs()
        self.refresh_attachments()
        self.refresh_details()

    def refresh_filters_source(self) -> None:
        release_id = self._selected_release_id
        self.filter_status.blockSignals(True)
        self.filter_status.clear()
        self.filter_status.addItem("", "")
        if release_id:
            for code, disp in STATUS_CHOICES:
                self.filter_status.addItem(disp, code)
            for col, widget in (("build", self.filter_build), ("environment", self.filter_env), ("executor", self.filter_exec)):
                vals = self.db.distinct_run_values(release_id, col)
                if vals:
                    comp = QtWidgets.QCompleter(vals, self)
                    comp.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
                    widget.setCompleter(comp)
                else:
                    widget.setCompleter(None)
        else:
            self.filter_build.setCompleter(None)
            self.filter_env.setCompleter(None)
            self.filter_exec.setCompleter(None)
        self.filter_status.blockSignals(False)

    def refresh_runs(self) -> None:
        try:
            release_id = self._selected_release_id
            testcase_id = self._selected_testcase_id

            if testcase_id:
                rows = self.db.list_runs_for_testcase(testcase_id)
                out: List[Dict[str, Any]] = []
                for r in rows:
                    rd = dict(r)
                    full = self.db.get_run_full(int(r["id"]))
                    if full:
                        merged = dict(full)
                        merged.update(rd)
                        out.append(merged)
                    else:
                        out.append(rd)
                self.run_model.set_rows(out)
            elif release_id:
                status_code = self.filter_status.currentData() or ""
                build = self.filter_build.text().strip()
                env = self.filter_env.text().strip()
                exe = self.filter_exec.text().strip()
                text = self.filter_text.text().strip()
                rows = self.db.list_runs_for_release(release_id, status=status_code, build=build, environment=env, executor=exe, text=text)
                self.run_model.set_rows([dict(rr) for rr in rows])
            else:
                self.run_model.set_rows([])

            self.run_view.resizeColumnsToContents()
            self._selected_run_id = None
            self.tc_label.setText("Тест-кейс: не выбран")
            self.run_label.setText("Прогон: не выбран")
            self.statusBar().showMessage("Список прогонов обновлён.", 2000)
        except Exception as e:
            self.show_error("Ошибка обновления прогонов", e)

    def on_apply_filters_clicked(self) -> None:
        # Если сейчас идёт редактирование ячейки таблицы, сначала коммитим правку,
        # иначе refresh_runs() сбросит модель и визуально покажется, что правка "не сохранилась".
        fw = QtWidgets.QApplication.focusWidget()
        if fw is not None and self.run_view.isAncestorOf(fw):
            self.run_view.closeEditor(
                fw,
                QtWidgets.QAbstractItemDelegate.EndEditHint.SubmitModelCache
            )

        self.refresh_runs()
    
    def on_run_selected(self) -> None:
        idxs = self.run_view.selectionModel().selectedRows()
        if not idxs:
            self._selected_run_id = None
            self.refresh_attachments()
            self.refresh_details()
            return
        row = idxs[0].row()
        d = self.run_model.get_row(row)
        if not d:
            return
        try:
            self._selected_run_id = int(d.get("id"))
        except Exception:
            self._selected_run_id = None
        self.refresh_attachments()
        self.refresh_details()

    def refresh_attachments(self) -> None:
        self.attach_list.clear()
        run_id = self._selected_run_id
        if not run_id:
            return
        try:
            for a in self.db.list_attachments(run_id):
                label = f"{a['original_name']}  |  {a['kind']}  |  {human_size(int(a['size_bytes']))}"
                if a["note"].strip():
                    label += f"  |  {a['note'].strip()}"
                it = QtWidgets.QListWidgetItem(label)
                it.setData(QtCore.Qt.ItemDataRole.UserRole, dict(a))
                self.attach_list.addItem(it)
        except Exception as e:
            self.show_error("Ошибка получения вложений", e)

    def refresh_details(self) -> None:
        node = self.selected_node()
        parts: List[str] = []

        try:
            if node.get("type") == "project":
                p = self.db.q1("SELECT * FROM projects WHERE id=?;", (int(node["id"]),))
                if p:
                    parts.append(f"Проект: {p['name']}")
                    if p["description"].strip():
                        parts.append(p["description"].strip())
                    parts.append(f"Создан: {p['created_at']}")
            elif node.get("type") == "release":
                r = self.db.q1("""
                SELECT releases.*, projects.name AS project_name
                FROM releases JOIN projects ON projects.id=releases.project_id
                WHERE releases.id=?;
                """, (int(node["id"]),))
                if r:
                    parts.append(f"Проект: {r['project_name']}")
                    parts.append(f"Релиз: {r['name']}")
                    if r["start_date"] or r["end_date"]:
                        parts.append(f"Период: {r['start_date']} .. {r['end_date']}")
                    if r["description"].strip():
                        parts.append(r["description"].strip())
                    parts.append(f"Создан: {r['created_at']}")
            elif node.get("type") == "testcase":
                tc = self.db.get_testcase_full(int(node["id"]))
                if tc:
                    parts.append(f"Проект: {tc['project_name']}")
                    parts.append(f"Релиз: {tc['release_name']}")
                    label = tc["name"]
                    if tc["suite"]:
                        label = f"{tc['suite']} :: {tc['name']}"
                    parts.append(f"Тест-кейс: {label}")
                    if tc["external_id"].strip():
                        parts.append(f"Внешний ID: {tc['external_id']}")
                    if tc["description"].strip():
                        parts.append(tc["description"].strip())
                    parts.append(f"Создан: {tc['created_at']}")
        except Exception as e:
            self.show_error("Ошибка получения деталей узла", e)

        run_id = self._selected_run_id
        if run_id:
            try:
                run = self.db.get_run_full(run_id)
                if run:
                    parts.append("")
                    parts.append(f"Прогон ID: {run['id']}  |  Статус: {run['status']}  |  Время: {run['executed_at']}")
                    parts.append(f"Сборка: {run['build']}  |  Окружение: {run['environment']}  |  Исполнитель: {run['executor']}")
                    parts.append(f"Длительность: {run['duration_sec']} сек")
                    if run["comment"].strip():
                        parts.append("Комментарий:")
                        parts.append(run["comment"].strip())
                    try:
                        meta = json.loads(run["meta_json"] or "{}")
                    except Exception:
                        meta = {"_raw": run["meta_json"]}
                    if meta and meta != {}:
                        parts.append("Meta:")
                        parts.append(json.dumps(meta, ensure_ascii=False, indent=2))
            except Exception as e:
                self.show_error("Ошибка получения деталей прогона", e)

        self.details.setPlainText("\n".join(parts))

        if self._selected_testcase_id:
            tc = self.db.get_testcase_full(self._selected_testcase_id)
            if tc:
                label = tc["name"]
                if tc["suite"]:
                    label = f"{tc['suite']} :: {tc['name']}"
                self.tc_label.setText(f"Тест-кейс: {label}")
        else:
            self.tc_label.setText("Тест-кейс: не выбран")

        if self._selected_run_id:
            run = self.db.get_run_full(self._selected_run_id)
            if run:
                self.run_label.setText(f"Прогон: {run['id']} | {run['status']} | {run['executed_at']}")
        else:
            self.run_label.setText("Прогон: не выбран")

    def on_tree_context_menu(self, pos: QtCore.QPoint) -> None:
        it = self.tree.itemAt(pos)
        if not it:
            return
        node = it.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if not isinstance(node, dict):
            return

        m = QtWidgets.QMenu(self)
        t = node.get("type")

        if t == "root":
            a1 = m.addAction("Создать проект…")
            a1.triggered.connect(self.create_project)
        elif t == "project":
            a1 = m.addAction("Создать релиз…")
            a1.triggered.connect(self.create_release)
            m.addSeparator()
            a2 = m.addAction("Переименовать / Редактировать проект…")
            a2.triggered.connect(self.edit_project)
            a3 = m.addAction("Удалить проект")
            a3.triggered.connect(self.delete_project)
        elif t == "release":
            a1 = m.addAction("Создать тест-кейс…")
            a1.triggered.connect(self.create_testcase)
            a2 = m.addAction("Импортировать JUnit XML…")
            a2.triggered.connect(self.import_junit)
            a6 = m.addAction("Экспортировать тест-кейсы в TXT…")
            a6.triggered.connect(self.export_testcases_txt)
            m.addSeparator()
            a3 = m.addAction("Редактировать релиз…")
            a3.triggered.connect(self.edit_release)
            a4 = m.addAction("Удалить релиз")
            a4.triggered.connect(self.delete_release)
            m.addSeparator()
            a5 = m.addAction("Экспортировать PDF отчёт по релизу…")
            a5.triggered.connect(self.export_release_pdf)
        elif t == "testcase":
            a1 = m.addAction("Создать прогон…")
            a1.triggered.connect(self.create_run)
            m.addSeparator()
            a2 = m.addAction("Редактировать тест-кейс…")
            a2.triggered.connect(self.edit_testcase)
            a3 = m.addAction("Удалить тест-кейс")
            a3.triggered.connect(self.delete_testcase)

        m.exec(self.tree.mapToGlobal(pos))

    def require_project(self) -> Optional[int]:
        if self._selected_project_id:
            return self._selected_project_id
        node = self.selected_node()
        if node.get("type") == "project":
            return int(node["id"])
        if node.get("type") == "release":
            return int(node["project_id"])
        if node.get("type") == "testcase":
            tc = self.db.q1("""
            SELECT releases.project_id AS project_id
            FROM testcases JOIN releases ON releases.id=testcases.release_id
            WHERE testcases.id=?;
            """, (int(node["id"]),))
            if tc:
                return int(tc["project_id"])
        return None

    def require_release(self) -> Optional[int]:
        if self._selected_release_id:
            return self._selected_release_id
        node = self.selected_node()
        if node.get("type") == "release":
            return int(node["id"])
        if node.get("type") == "testcase":
            return int(node["release_id"])
        return None

    def require_testcase(self) -> Optional[int]:
        if self._selected_testcase_id:
            return self._selected_testcase_id
        node = self.selected_node()
        if node.get("type") == "testcase":
            return int(node["id"])
        return None

    def create_project(self) -> None:
        dlg = ProjectDialog("Создать проект", parent=self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        name, desc = dlg.get()
        if not name:
            QtWidgets.QMessageBox.warning(self, "Пожалуйста", "Имя проекта обязательно — введите, пожалуйста.")
            return
        try:
            self.db.create_project(name, desc)
            self.refresh_tree()
            self.statusBar().showMessage("Проект создан.", 3000)
        except sqlite3.IntegrityError:
            QtWidgets.QMessageBox.warning(self, "Не получилось", "Проект с таким именем уже существует.")
        except Exception as e:
            self.show_error("Не удалось создать проект", e)

    def edit_project(self) -> None:
        pid = self.require_project()
        if not pid:
            QtWidgets.QMessageBox.information(self, "Подсказка", "Выберите проект, который хотите изменить.")
            return
        p = self.db.q1("SELECT * FROM projects WHERE id=?;", (pid,))
        if not p:
            return
        dlg = ProjectDialog("Редактировать проект", name=p["name"], description=p["description"], parent=self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        name, desc = dlg.get()
        if not name:
            QtWidgets.QMessageBox.warning(self, "Пожалуйста", "Имя проекта обязательно — введите, пожалуйста.")
            return
        try:
            self.db.update_project(pid, name, desc)
            self.refresh_tree()
            self.statusBar().showMessage("Проект обновлён.", 3000)
        except sqlite3.IntegrityError:
            QtWidgets.QMessageBox.warning(self, "Не получилось", "Проект с таким именем уже существует.")
        except Exception as e:
            self.show_error("Не удалось редактировать проект", e)

    def delete_project(self) -> None:
        pid = self.require_project()
        if not pid:
            QtWidgets.QMessageBox.information(self, "Информация", "Выберите проект для удаления.")
            return
        if QtWidgets.QMessageBox.question(self, "Подтвердите удаление", "Удалить проект и всё внутри (релизы, тест-кейсы, прогоны и файлы)?") != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            self.db.delete_project(pid)
            self._selected_project_id = None
            self._selected_release_id = None
            self._selected_testcase_id = None
            self._selected_run_id = None
            self.refresh_all()
            self.statusBar().showMessage("Проект удалён.", 3000)
        except Exception as e:
            self.show_error("Не удалось удалить проект", e)

    def create_release(self) -> None:
        pid = self.require_project()
        if not pid:
            QtWidgets.QMessageBox.warning(self, "Пожалуйста", "Выберите проект перед созданием релиза.")
            return
        dlg = ReleaseDialog("Создать релиз", parent=self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        name, desc, start, end = dlg.get()
        if not name:
            QtWidgets.QMessageBox.warning(self, "Пожалуйста", "Имя релиза обязательно — введите, пожалуйста.")
            return
        try:
            rid = self.db.create_release(pid, name, desc, start, end)
            self._selected_release_id = rid
            self.refresh_tree()
            self.statusBar().showMessage("Релиз создан.", 3000)
        except sqlite3.IntegrityError:
            QtWidgets.QMessageBox.warning(self, "Не получилось", "Релиз с таким именем уже существует в проекте.")
        except Exception as e:
            self.show_error("Не удалось создать релиз", e)

    def edit_release(self) -> None:
        rid = self.require_release()
        if not rid:
            QtWidgets.QMessageBox.information(self, "Информация", "Выберите релиз для редактирования.")
            return
        r = self.db.q1("SELECT * FROM releases WHERE id=?;", (rid,))
        if not r:
            return
        dlg = ReleaseDialog("Редактировать релиз", name=r["name"], description=r["description"], start_date=r["start_date"], end_date=r["end_date"], parent=self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        name, desc, start, end = dlg.get()
        if not name:
            QtWidgets.QMessageBox.warning(self, "Пожалуйста", "Имя релиза обязательно — введите, пожалуйста.")
            return
        try:
            self.db.update_release(rid, name, desc, start, end)
            self.refresh_tree()
            self.refresh_runs()
            self.statusBar().showMessage("Релиз обновлён.", 3000)
        except sqlite3.IntegrityError:
            QtWidgets.QMessageBox.warning(self, "Не получилось", "Релиз с таким именем уже существует в проекте.")
        except Exception as e:
            self.show_error("Не удалось редактировать релиз", e)

    def delete_release(self) -> None:
        rid = self.require_release()
        if not rid:
            QtWidgets.QMessageBox.information(self, "Информация", "Выберите релиз для удаления.")
            return
        if QtWidgets.QMessageBox.question(self, "Подтвердите удаление", "Удалить релиз и всё внутри (тест-кейсы, прогоны, файлы)?") != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            self.db.delete_release(rid)
            self._selected_release_id = None
            self._selected_testcase_id = None
            self._selected_run_id = None
            self.refresh_all()
            self.statusBar().showMessage("Релиз удалён.", 3000)
        except Exception as e:
            self.show_error("Не удалось удалить релиз", e)

    def create_testcase(self) -> None:
        rid = self.require_release()
        if not rid:
            QtWidgets.QMessageBox.warning(self, "Пожалуйста", "Сначала выберите релиз, в котором хотите создать тест-кейс.")
            return
        dlg = TestCaseDialog("Создать тест-кейс", parent=self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        suite, name, external_id, desc = dlg.get()
        if not name:
            QtWidgets.QMessageBox.warning(self, "Пожалуйста", "Название теста обязательно — введите, пожалуйста.")
            return
        try:
            tcid = self.db.create_testcase(rid, suite, name, external_id, desc)
            self._selected_testcase_id = tcid
            self.refresh_tree()
            self.refresh_runs()
            self.statusBar().showMessage("Тест-кейс создан.", 3000)
        except sqlite3.IntegrityError:
            QtWidgets.QMessageBox.warning(self, "Не получилось", "Тест-кейс с таким именем уже существует в релизе.")
        except Exception as e:
            self.show_error("Не удалось создать тест-кейс", e)

    def edit_testcase(self) -> None:
        tcid = self.require_testcase()
        if not tcid:
            QtWidgets.QMessageBox.information(self, "Информация", "Выберите тест-кейс для редактирования.")
            return
        tc = self.db.q1("SELECT * FROM testcases WHERE id=?;", (tcid,))
        if not tc:
            return
        dlg = TestCaseDialog("Редактировать тест-кейс", suite=tc["suite"], name=tc["name"], external_id=tc["external_id"], description=tc["description"], parent=self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        suite, name, external_id, desc = dlg.get()
        if not name:
            QtWidgets.QMessageBox.warning(self, "Пожалуйста", "Название теста обязательно — введите, пожалуйста.")
            return
        try:
            self.db.update_testcase(tcid, suite, name, external_id, desc)
            self.refresh_tree()
            self.select_testcase_in_tree(tcid)
            self.refresh_runs()
            self.statusBar().showMessage("Тест-кейс обновлён.", 3000)
        except sqlite3.IntegrityError:
            QtWidgets.QMessageBox.warning(self, "Не получилось", "Тест-кейс с таким именем уже существует в релизе.")
        except Exception as e:
            self.show_error("Не удалось редактировать тест-кейс", e)

    def delete_testcase(self) -> None:
        tcid = self.require_testcase()
        if not tcid:
            QtWidgets.QMessageBox.information(self, "Информация", "Выберите тест-кейс для удаления.")
            return
        if QtWidgets.QMessageBox.question(self, "Подтвердите удаление", "Удалить тест-кейс и все связанные прогоны?") != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            self.db.delete_testcase(tcid)
            self._selected_testcase_id = None
            self._selected_run_id = None
            self.refresh_all()
            self.statusBar().showMessage("Тест-кейс удалён.", 3000)
        except Exception as e:
            self.show_error("Не удалось удалить тест-кейс", e)

    def create_run(self) -> None:
        tcid = self.require_testcase()
        if not tcid:
            QtWidgets.QMessageBox.warning(self, "Пожалуйста", "Сначала выберите тест-кейс, затем создавайте прогон.")
            return
        dlg = RunDialog("Создать прогон", parent=self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        status, executed_at, build, env, exe, dur, comment, meta = dlg.get()
        try:
            run_id = self.db.create_run(tcid, status, executed_at, build, env, exe, dur, comment, meta)
            self._selected_run_id = run_id
            self.refresh_runs()
            self.select_run_in_table(run_id)
            self.refresh_attachments()
            self.refresh_details()
            self.statusBar().showMessage("Прогон создан.", 3000)
        except Exception as e:
            self.show_error("Не удалось создать прогон", e)

    def on_edit_run_from_table(self) -> None:
        idxs = self.run_view.selectionModel().selectedRows()
        if not idxs:
            return
        row = idxs[0].row()
        d = self.run_model.get_row(row)
        if not d:
            return
        run_id = int(d["id"])
        self.edit_run(run_id)

    def _save_edited_run_row(self, d: Dict[str, Any]) -> None:
        try:
            run_id = int(d.get("id") or 0)
            _log_message(self.data_dir, f"SAVE_EDIT run_id={run_id} status={d.get('status')!r}")
            if not run_id:
                return

            # meta_json может отсутствовать в строках из list_runs_for_release,
            # поэтому безопаснее подчитать из БД.
            run = self.db.q1("SELECT * FROM runs WHERE id=?", (run_id,))
            if not run:
                return

            status = str(d.get("status") or run["status"] or "PASS")
            executed_at = str(d.get("executed_at") or run["executed_at"] or now_iso())
            build = str(d.get("build") or "")
            env = str(d.get("environment") or "")
            exe = str(d.get("executor") or "")
            comment = str(d.get("comment") or "")

            # duration_sec
            dur_raw = d.get("duration_sec", run["duration_sec"])
            try:
                dur = float(dur_raw)
            except Exception:
                dur = float(run["duration_sec"] or 0.0)
            meta_json = run["meta_json"] or "{}"
            try:
                meta = json.loads(meta_json)
                if not isinstance(meta, dict):
                    meta = {}
            except Exception:
                meta = {}
            self.db.update_run(run_id, status, executed_at, build, env, exe, dur, comment, meta)
            self.db.exec(
                "UPDATE testcases SET last_status=? WHERE id=?;",
                (status, int(run["testcase_id"]))
            )
            self.refresh_runs()
            self.select_run_in_table(run_id)
            self._selected_run_id = run_id
            self.refresh_details()
            self.statusBar().showMessage("Изменения сохранены.", 1500)
        except Exception as e:
            self.show_error("Не удалось сохранить изменения прогона", e)

    def edit_run(self, run_id: int) -> None:
        run = self.db.q1("SELECT * FROM runs WHERE id=?;", (run_id,))
        if not run:
            return
        dlg = RunDialog(
            "Редактировать прогон",
            status=run["status"],
            executed_at=run["executed_at"],
            build=run["build"],
            environment=run["environment"],
            executor=run["executor"],
            duration_sec=float(run["duration_sec"]),
            comment=run["comment"],
            meta_json=run["meta_json"],
            parent=self,
        )
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        status, executed_at, build, env, exe, dur, comment, meta = dlg.get()
        try:
            self.db.update_run(run_id, status, executed_at, build, env, exe, dur, comment, meta)
            self.db.exec(
                "UPDATE testcases SET last_status=? WHERE id=?;",
                (status, int(run["testcase_id"]))
            )
            self.refresh_runs()
            self.select_run_in_table(run_id)
            self.refresh_attachments()
            self.refresh_details()
            self.statusBar().showMessage("Прогон обновлён.", 3000)
        except Exception as e:
            self.show_error("Не удалось редактировать прогон", e)

    def delete_selected_run(self) -> None:
        run_id = self._selected_run_id
        if not run_id:
            return
        if QtWidgets.QMessageBox.question(self, "Подтвердите удаление", "Удалить выбранный прогон?") != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            self.db.delete_run(run_id)
            self._selected_run_id = None
            self.refresh_runs()
            self.refresh_attachments()
            self.refresh_details()
            self.statusBar().showMessage("Прогон удалён.", 3000)
        except Exception as e:
            self.show_error("Не удалось удалить прогон", e)

    def select_run_in_table(self, run_id: int) -> None:
        for r in range(self.run_model.rowCount()):
            d = self.run_model.get_row(r)
            if d and int(d.get("id", -1)) == run_id:
                self.run_view.selectRow(r)
                self.run_view.scrollTo(self.run_model.index(r, 0), QtWidgets.QAbstractItemView.ScrollHint.PositionAtCenter)
                return

    def on_add_files_clicked(self) -> None:
        run_id = self._selected_run_id
        if not run_id:
            QtWidgets.QMessageBox.warning(self, "Пожалуйста", "Сначала выберите прогон, затем добавляйте файлы.")
            return
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Выберите файлы для добавления", "")
        if not files:
            return
        self.add_attachments(run_id, files)

    def on_attachments_dropped(self, paths: List[str]) -> None:
        run_id = self._selected_run_id
        if not run_id:
            QtWidgets.QMessageBox.warning(self, "Пожалуйста", "Выберите прогон в таблице, потом перетащите файлы сюда.")
            return
        self.add_attachments(run_id, paths)

    def detect_kind(self, path: str) -> str:
        mt, _ = mimetypes.guess_type(path)
        mt = mt or ""
        ext = os.path.splitext(path)[1].lower()
        if mt.startswith("image/") or ext in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}:
            return "screenshot"
        if mt.startswith("video/") or ext in {".mp4", ".mkv", ".avi", ".mov", ".webm", ".gif"}:
            return "video"
        if mt.startswith("text/") or ext in {".log", ".txt", ".json", ".xml", ".yml", ".yaml"}:
            return "log"
        if ext in {".pdf"}:
            return "report"
        if ext in {".html", ".htm"}:
            return "report"
        if ext in {".xlsx", ".xls", ".csv"}:
            return "report"
        return "file"

    def add_attachments(self, run_id: int, paths: List[str]) -> None:
        try:
            run = self.db.get_run_full(run_id)
            if not run:
                QtWidgets.QMessageBox.warning(self, "Ошибка", "Прогон не найден — возможно, он был удалён.")
                return
            project = safe_filename(run["project_name"])
            release = safe_filename(run["release_name"])
            suite = safe_filename(run["suite"] or "suite")
            tcname = safe_filename(run["tc_name"] or "test")
            run_dir = os.path.join(self.storage_dir, project, release, suite, tcname, f"run_{run_id}")
            ensure_dir(run_dir)

            added = 0
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            try:
                for p in paths:
                    if not os.path.isfile(p):
                        continue
                    original = os.path.basename(p)
                    kind = self.detect_kind(p)
                    h = sha256_file(p)
                    ext = os.path.splitext(original)[1]
                    target_name = safe_filename(os.path.splitext(original)[0]) or "file"
                    stored = f"{target_name}__{h[:12]}__{uuid.uuid4().hex[:8]}{ext}"
                    dst = os.path.join(run_dir, stored)
                    try:
                        shutil.copy2(p, dst)
                    except Exception:
                        shutil.copy(p, dst)
                    mt, _ = mimetypes.guess_type(dst)
                    mt = mt or ""
                    size = os.path.getsize(dst)
                    rel = os.path.relpath(dst, self.storage_dir).replace("\\", "/")
                    try:
                        self.db.add_attachment(run_id, kind, original, rel, mt, size, h, note="")
                        added += 1
                    except Exception:
                        try:
                            if os.path.exists(dst):
                                os.remove(dst)
                        except Exception:
                            pass
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()

            self.refresh_attachments()
            self.refresh_details()
            if added:
                QtWidgets.QMessageBox.information(self, "Готово", f"Файлов добавлено: {added}.")
                self.statusBar().showMessage(f"Добавлено {added} вложений.", 3000)
            else:
                QtWidgets.QMessageBox.information(self, "Ничего не добавлено", "Файлы не были добавлены — проверьте, что вы выбрали реальные файлы.")
        except Exception as e:
            self.show_error("Ошибка добавления вложений", e)

    def on_attachments_context_menu(self, pos: QtCore.QPoint) -> None:
        it = self.attach_list.itemAt(pos)
        m = QtWidgets.QMenu(self)
        a_open = m.addAction("Открыть файл")
        a_open_folder = m.addAction("Открыть папку с файлом")
        a_note = m.addAction("Добавить/изменить заметку…")
        a_del = m.addAction("Удалить запись и файл")
        if it is None:
            a_open.setEnabled(False)
            a_open_folder.setEnabled(False)
            a_note.setEnabled(False)
            a_del.setEnabled(False)
        else:
            a_open.triggered.connect(lambda: self.open_attachment(it))
            a_open_folder.triggered.connect(lambda: self.open_attachment_folder(it))
            a_note.triggered.connect(lambda: self.edit_attachment_note(it))
            a_del.triggered.connect(lambda: self.delete_attachment(it))
        m.exec(self.attach_list.mapToGlobal(pos))

    def attachment_from_item(self, it: Optional[QtWidgets.QListWidgetItem]) -> Optional[Dict[str, Any]]:
        if not it:
            return None
        d = it.data(QtCore.Qt.ItemDataRole.UserRole)
        return d if isinstance(d, dict) else None

    def open_attachment(self, it: Optional[QtWidgets.QListWidgetItem]) -> None:
        d = self.attachment_from_item(it)
        if not d:
            return
        p = os.path.join(self.storage_dir, d["stored_relpath"].replace("/", os.sep))
        if os.path.exists(p):
            open_path(p)
        else:
            QtWidgets.QMessageBox.warning(self, "Файл не найден", "Файл отсутствует в хранилище — возможно, его переместили или удалили.")

    def open_attachment_folder(self, it: Optional[QtWidgets.QListWidgetItem]) -> None:
        d = self.attachment_from_item(it)
        if not d:
            return
        p = os.path.join(self.storage_dir, d["stored_relpath"].replace("/", os.sep))
        folder = os.path.dirname(p)
        if os.path.exists(folder):
            open_path(folder)
        else:
            QtWidgets.QMessageBox.warning(self, "Папка не найдена", "Папка с файлом не найдена в хранилище.")

    def edit_attachment_note(self, it: Optional[QtWidgets.QListWidgetItem]) -> None:
        d = self.attachment_from_item(it)
        if not d:
            return
        dlg = TextDialog("Заметка к вложению", "Введите заметку:", d.get("note", ""), self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        try:
            self.db.update_attachment_note(int(d["id"]), dlg.value())
            self.refresh_attachments()
            self.statusBar().showMessage("Заметка сохранена.", 3000)
        except Exception as e:
            self.show_error("Не удалось сохранить заметку", e)

    def delete_attachment(self, it: Optional[QtWidgets.QListWidgetItem]) -> None:
        d = self.attachment_from_item(it)
        if not d:
            return
        if QtWidgets.QMessageBox.question(self, "Подтвердите удаление", "Удалить вложение и файл из хранилища?") != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            p = os.path.join(self.storage_dir, d["stored_relpath"].replace("/", os.sep))
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
            self.db.delete_attachment(int(d["id"]))
            self.refresh_attachments()
            self.statusBar().showMessage("Вложение удалено.", 3000)
        except Exception as e:
            self.show_error("Не удалось удалить вложение", e)

    def export_run_zip(self) -> None:
        run_id = self._selected_run_id
        if not run_id:
            QtWidgets.QMessageBox.warning(self, "Пожалуйста", "Сначала выберите прогон, который хотите экспортировать.")
            return
        run = self.db.get_run_full(run_id)
        if not run:
            return
        default_name = safe_filename(f"{run['project_name']}__{run['release_name']}__run_{run_id}.zip")
        out_path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Сохранить ZIP", default_name, "ZIP-файл (*.zip)")
        if not out_path:
            return
        try:
            att = self.db.list_attachments(run_id)
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            try:
                with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
                    meta = {
                        "run": {
                            "id": run["id"],
                            "status": run["status"],
                            "executed_at": run["executed_at"],
                            "build": run["build"],
                            "environment": run["environment"],
                            "executor": run["executor"],
                            "duration_sec": run["duration_sec"],
                            "comment": run["comment"],
                            "meta_json": run["meta_json"],
                        },
                        "testcase": {
                            "suite": run["suite"],
                            "name": run["tc_name"],
                            "external_id": run["external_id"],
                        },
                        "release": {"id": run["release_id"], "name": run["release_name"]},
                        "project": {"name": run["project_name"]},
                        "attachments": [],
                    }
                    for a in att:
                        p = os.path.join(self.storage_dir, a["stored_relpath"].replace("/", os.sep))
                        arc = f"attachments/{safe_filename(a['original_name'])}"
                        if os.path.exists(p):
                            z.write(p, arcname=arc)
                        meta["attachments"].append(dict(a))
                    z.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()
            QtWidgets.QMessageBox.information(self, "Готово", "ZIP-архив успешно создан.")
            self.statusBar().showMessage("ZIP экспорт завершён.", 3000)
        except Exception as e:
            self.show_error("Не удалось экспортировать ZIP", e)

    def export_testcases_txt(self) -> None:
        rid = self.require_release()
        tcid = self.require_testcase()
        if not rid and not tcid:
            QtWidgets.QMessageBox.warning(self, "Пожалуйста", "Выберите релиз или тест-кейс для экспорта.")
            return
        mode_single = bool(tcid)
        if mode_single:
            tc = self.db.get_testcase_full(int(tcid))
            if not tc:
                QtWidgets.QMessageBox.warning(self, "Ошибка", "Тест-кейс не найден.")
                return
            default_name = safe_filename(f"{tc['project_name']}__{tc['release_name']}__{tc['suite']}__{tc['name']}__testcase.txt")
            rows = [tc]
            header_project = tc["project_name"]
            header_release = tc["release_name"]
        else:
            r = self.db.q1("""
            SELECT releases.*, projects.name AS project_name
            FROM releases JOIN projects ON projects.id=releases.project_id
            WHERE releases.id=?
            """, (int(rid),))
            if not r:
                QtWidgets.QMessageBox.warning(self, "Ошибка", "Релиз не найден.")
                return
            rows = self.db.list_testcases(int(rid))
            default_name = safe_filename(f"{r['project_name']}__{r['name']}__testcases.txt")
            header_project = r["project_name"]
            header_release = r["name"]
        out_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Сохранить TXT",
            default_name,
            "Текстовый файл (*.txt)"
        )
        if not out_path:
            return
        try:
            lines = []
            lines.append(f"Проект: {header_project}")
            lines.append(f"Релиз: {header_release}")
            lines.append(f"Дата экспорта: {now_iso()}")
            lines.append("")
            lines.append(f"Тест-кейсов: {len(rows)}")
            lines.append("=" * 80)
            lines.append("")
            for i, tc in enumerate(rows, start=1):
                suite = (tc["suite"] if "suite" in tc.keys() else "") or ""
                name = (tc["name"] if "name" in tc.keys() else "") or ""
                external_id = (tc["external_id"] if "external_id" in tc.keys() else "") or ""
                description = (tc["description"] if "description" in tc.keys() else "") or ""
                created_at = (tc["created_at"] if "created_at" in tc.keys() else "") or ""
                title = f"{suite} :: {name}" if suite else name
                lines.append(f"{i}. {title}")
                if external_id.strip():
                    lines.append(f"   External ID: {external_id}")
                if created_at.strip():
                    lines.append(f"   Created: {created_at}")
                if description.strip():
                    lines.append("   Description:")
                    for dl in description.splitlines():
                        lines.append(f"     {dl}")
                lines.append("-" * 80)
            with open(out_path, "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(lines).rstrip() + "\n")
            QtWidgets.QMessageBox.information(self, "Готово", "TXT успешно сохранён.")
            self.statusBar().showMessage("Экспорт тест-кейсов в TXT завершён.", 3000)
        except Exception as e:
            self.show_error("Не удалось экспортировать тест-кейсы в TXT", e)

    def export_release_pdf(self) -> None:
        rid = self.require_release()
        if not rid:
            QtWidgets.QMessageBox.warning(self, "Пожалуйста", "Выберите релиз для экспорта.")
            return
        r = self.db.q1("""
        SELECT releases.*, projects.name AS project_name
        FROM releases JOIN projects ON projects.id=releases.project_id
        WHERE releases.id=?;
        """, (rid,))
        if not r:
            return
        default_name = safe_filename(f"{r['project_name']}__{r['name']}__report.pdf")
        out_path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Сохранить PDF", default_name, "PDF-файл (*.pdf)")
        if not out_path:
            return
        try:
            rows = self.db.list_runs_for_release(rid)
            c = canvas.Canvas(out_path, pagesize=A4)
            w, h = A4
            x = 40
            y = h - 50
            def line(txt: str, dy: int = 14):
                nonlocal y
                if y < 60:
                    c.showPage()
                    y = h - 50
                c.drawString(x, y, txt[:140])
                y -= dy
            c.setTitle(f"{APP_NAME} - Отчёт по релизу")
            line(f"Проект: {r['project_name']}")
            line(f"Релиз: {r['name']}")
            if r["start_date"] or r["end_date"]:
                line(f"Период: {r['start_date']} .. {r['end_date']}")
            line(f"Сформирован: {now_iso()}")
            line("")
            stats: Dict[str, int] = {}
            for rr in rows:
                st = str(rr["status"]).upper()
                stats[st] = stats.get(st, 0) + 1
            line("Итого по статусам:")
            for k in sorted(stats.keys()):
                line(f"  {k}: {stats[k]}")
            line("")
            line("Прогоны:")
            for rr in rows[:2000]:
                st = str(rr["status"]).upper()
                when = rr["executed_at"]
                build = rr["build"]
                env = rr["environment"]
                exe = rr["executor"]
                suite = rr.get("suite", "")
                name = rr.get("tc_name", "")
                ext = rr.get("external_id", "")
                line(f"[{st}] {when} | {build} | {env} | {exe}")
                tline = f"  {suite} :: {name}"
                if ext:
                    tline += f" ({ext})"
                line(tline)
                cm = (rr["comment"] or "").strip()
                if cm:
                    for chunk in self._wrap(cm, 110)[:6]:
                        line(f"    {chunk}")
            c.save()
            QtWidgets.QMessageBox.information(self, "Готово", "PDF-отчёт сохранён.")
            self.statusBar().showMessage("PDF экспорт завершён.", 3000)
        except Exception as e:
            self.show_error("Не удалось экспортировать PDF", e)

    def _wrap(self, s: str, width: int) -> List[str]:
        out: List[str] = []
        s = s.replace("\r", "")
        for para in s.split("\n"):
            p = para.strip()
            if not p:
                out.append("")
                continue
            while len(p) > width:
                cut = p.rfind(" ", 0, width)
                if cut <= 0:
                    cut = width
                out.append(p[:cut].rstrip())
                p = p[cut:].lstrip()
            out.append(p)
        return out

    # Дублирующий import_junit удалён — используется единственная реализация выше

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == QtCore.Qt.Key.Key_Delete:
            if self.run_view.hasFocus() and self._selected_run_id:
                self.delete_selected_run()
                return
            if self.attach_list.hasFocus():
                items = self.attach_list.selectedItems()
                if items:
                    self.delete_attachment(items[0])
                    return
        super().keyPressEvent(event)

# -- main --

def main() -> None:
    try:
        app = QtWidgets.QApplication(sys.argv)
        if getattr(sys, "frozen", False):
            app_dir = os.path.dirname(sys.executable)
        else:
            app_dir = os.path.dirname(os.path.abspath(__file__))
        base_dir = os.path.abspath(os.path.join(app_dir, DATA_DIRNAME))
        ensure_dir(base_dir)
        try:
            readme_path = os.path.join(base_dir, "README.md")
            with open(readme_path, "w", encoding="utf-8") as rf:
                rf.write(HELP_MARKDOWN)
        except Exception:
            pass
        storage_dir = os.path.join(base_dir, STORAGE_DIRNAME)
        ensure_dir(storage_dir)
        db_path = os.path.join(base_dir, DB_FILENAME)
        db = TEMDatabase(db_path)
        w = MainWindow(db, base_dir, storage_dir, HELP_MARKDOWN)
        w.show()
        code = app.exec()
        db.close()
        sys.exit(code)
    except Exception as e:
        try:
            with open(os.path.join(os.getcwd(), LOG_FILENAME), "a", encoding="utf-8") as f:
                f.write(f"{now_iso()} Сбой запуска: {type(e).__name__}: {e}\n")
                f.write(traceback.format_exc() + "\n")
        except Exception:
            pass
        raise

if __name__ == "__main__":
    main()