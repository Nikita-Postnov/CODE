import os
import sys
import json
import uuid
import shutil
import datetime
from pathlib import Path
import subprocess
import re

from PyQt6.QtCore import Qt, QSettings, QTimer, QPoint, QRect
from PyQt6.QtGui import QIcon, QCursor, QAction
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QInputDialog,
    QMessageBox,
    QMenu,
    QSizeGrip,
    QLabel,
)

if getattr(sys, "frozen", False):
    APPDIR = os.path.dirname(sys.executable)
else:
    APPDIR = os.path.abspath(os.path.dirname(__file__))

DATA_DIR = os.path.join(APPDIR, "Data")
NOTES_DIR = os.path.join(APPDIR, "Notes")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.ini")
NOTES_WIDGET_PATH = os.path.join(DATA_DIR, "desktop_notes.json")
NOTES_WIDGET_BAK = os.path.join(DATA_DIR, "desktop_notes.json.bak")
ICON_PATH = os.path.join(DATA_DIR, "icon.ico")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(NOTES_DIR, exist_ok=True)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


class DesktopNotesWindow(QWidget):

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Заметки (Виджет)")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowOpacity(0.95)
        if os.path.isfile(ICON_PATH):
            self.setWindowIcon(QIcon(ICON_PATH))
            QApplication.instance().setWindowIcon(QIcon(ICON_PATH))
        self._drag_active = False
        self._drag_offset = None
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self.lbl_title = QLabel("📋 Заметки", self)
        self.lbl_title.setProperty("drag_handle", True)
        btn_add = QPushButton("+ Добавить", self)
        btn_add.clicked.connect(self.add_note)
        btn_refresh = QPushButton("Обновить", self)
        btn_refresh.clicked.connect(self.reload_notes)
        btn_close = QPushButton("✕", self)
        btn_close.clicked.connect(self.close)
        btn_close.setToolTip("Закрыть виджет")
        header.addWidget(self.lbl_title)
        header.addStretch(1)
        header.addWidget(btn_add)
        header.addWidget(btn_refresh)
        header.addWidget(btn_close)
        header_w = QWidget(self)
        header_w.setLayout(header)
        header_w.setProperty("drag_handle", True)
        root.addWidget(header_w)
        self.list = QListWidget(self)
        self.list.itemDoubleClicked.connect(self._on_item_activated)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        root.addWidget(self.list, 1)
        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 0, 0)
        grip_row.addStretch(1)
        self._grip = QSizeGrip(self)
        grip_row.addWidget(self._grip, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        grip_w = QWidget(self)
        grip_w.setLayout(grip_row)
        root.addWidget(grip_w)
        self.setStyleSheet(
            """
            /* Общий фон делаем чуть темнее и слегка менее непрозрачным */
            QWidget { background-color: rgba(18,18,18,210); color: #fff; border-radius: 12px; font-family: Segoe UI; }
            QListWidget { background-color: transparent; border: none; font-size: 14px; }
            QPushButton { background-color: rgba(60,65,72,220); border-radius: 8px; padding: 6px 10px; }
            QPushButton:hover { background-color: rgba(80,88,96,220); }
            """
        )
        self.installEventFilter(self)
        header_w.installEventFilter(self)
        self.lbl_title.installEventFilter(self)
        self.resize(340, 420)
        self.setMinimumSize(260, 140)
        self._load_geometry()
        self._ensure_on_screen()
        self.reload_notes()

    def _load_geometry(self) -> None:
        try:
            s = QSettings(SETTINGS_PATH, QSettings.Format.IniFormat)
            s.beginGroup("DesktopNotesWidget")
            if s.contains("x") and s.contains("y"):
                self.move(int(s.value("x", type=int)), int(s.value("y", type=int)))
            if s.contains("w") and s.contains("h"):
                w = int(s.value("w", type=int)); h = int(s.value("h", type=int))
                if w > 100 and h > 100:
                    self.resize(w, h)
            s.endGroup()
        except Exception:
            pass

    def _save_geometry(self) -> None:
        try:
            s = QSettings(SETTINGS_PATH, QSettings.Format.IniFormat)
            s.beginGroup("DesktopNotesWidget")
            s.setValue("x", self.x()); s.setValue("y", self.y())
            s.setValue("w", self.width()); s.setValue("h", self.height())
            s.endGroup()
        except Exception:
            pass

    def _ensure_on_screen(self) -> None:
        try:
            screen = QApplication.primaryScreen()
            if not screen:
                return
            avail = screen.availableGeometry()
            geo = self.frameGeometry()
            offscreen = (
                geo.right() < avail.left() + 20 or
                geo.bottom() < avail.top() + 20 or
                geo.left() > avail.right() - 20 or
                geo.top() > avail.bottom() - 20 or
                self.width() < 140 or self.height() < 120
            )
            if offscreen:
                self.resize(min(max(self.width(), 320), avail.width()-80),
                            min(max(self.height(), 380), avail.height()-80))
                self.move(avail.center() - self.rect().center())
        except Exception:
            pass

    def eventFilter(self, obj, ev):
        et = ev.type()
        if et == ev.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
            try:
                if obj.property("drag_handle") is True:
                    self._drag_active = True
                    self._drag_offset = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
                    return True
            except Exception:
                pass
        elif et == ev.Type.MouseMove and self._drag_active:
            self.move(ev.globalPosition().toPoint() - self._drag_offset)
            return True
        elif et == ev.Type.MouseButtonRelease and ev.button() == Qt.MouseButton.LeftButton:
            if self._drag_active:
                self._drag_active = False
                self._save_geometry()
                return True
        return False

    def _atomic_write(self, path: str, payload: list[dict]) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        try:
            if os.path.exists(path):
                shutil.copy2(path, NOTES_WIDGET_BAK)
        except Exception:
            pass
        os.replace(tmp, path)

    def _read_notes(self) -> list[dict]:
        if not os.path.exists(NOTES_WIDGET_PATH):
            return []
        try:
            raw = Path(NOTES_WIDGET_PATH).read_text("utf-8").strip()
            if not raw:
                return []
            data = json.loads(raw)
        except Exception:
            return []
        notes: list[dict] = []
        if isinstance(data, list):
            for x in data:
                if isinstance(x, dict):
                    txt = (x.get("text") or "").strip()
                    if not txt:
                        continue
                    notes.append({
                        "id": x.get("id") or str(uuid.uuid4()),
                        "text": txt,
                        "created": x.get("created") or _now_iso(),
                        "updated": x.get("updated") or _now_iso(),
                        "source": "widget",
                        "path": NOTES_WIDGET_PATH,
                    })
                elif isinstance(x, str) and x.strip():
                    ts = _now_iso()
                    notes.append({"id": str(uuid.uuid4()), "text": x.strip(), "created": ts, "updated": ts, "source": "widget", "path": NOTES_WIDGET_PATH})
        return notes

    def _scan_app_notes(self) -> list[dict]:
        items: list[dict] = []
        try:
            if not os.path.isdir(NOTES_DIR):
                return items
            for folder in os.listdir(NOTES_DIR):
                if folder == "Trash":
                    continue
                folder_path = os.path.join(NOTES_DIR, folder)
                if not os.path.isdir(folder_path):
                    continue
                file_path = os.path.join(folder_path, "note.json")
                if not os.path.isfile(file_path):
                    continue
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    title = (data.get("title") or folder).strip()
                    created = (data.get("timestamp") or "").strip()
                    nid = (data.get("uuid") or str(uuid.uuid4())).strip()
                    items.append({
                        "id": nid,
                        "text": title,
                        "created": created,
                        "updated": created or "",
                        "source": "app",
                        "path": file_path,
                    })
                except Exception as e:
                    print("scan app notes error:", e)
        finally:
            return items

    def _safe_title(self, text: str) -> str:
        base = (text.splitlines()[0] if text else "").strip()
        base = base[:60] if len(base) > 60 else base
        base = re.sub(r'[\\/:*?"<>|]+', '_', base)
        return base or "Note"

    def _materialize_widget_note(self, item: QListWidgetItem) -> str | None:
        txt = (item.text() or "").lstrip("📌 ").strip()
        if not txt:
            return None
        nid = item.data(Qt.ItemDataRole.UserRole) or str(uuid.uuid4())
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        title = self._safe_title(txt)
        folder = f"{title}_{nid[:8]}_{ts}"
        note_dir = os.path.join(NOTES_DIR, folder)
        os.makedirs(note_dir, exist_ok=True)
        note_json = os.path.join(note_dir, "note.json")
        payload = {
            "uuid": nid,
            "title": title,
            "timestamp": _now_iso(),
            "text": txt,
        }
        try:
            with open(note_json, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "Ошибка сохранения", f"Не удалось создать заметку в Notes:{e}")
            return None
        item.setText("📝 " + title)
        item.setData(Qt.ItemDataRole.UserRole + 2, "app")
        item.setData(Qt.ItemDataRole.UserRole + 3, note_json)
        return note_json

    def _launch_notespm(self, note_json_path: str | None) -> None:
        exe = os.path.join(APPDIR, "NotesPM.exe")
        if not os.path.isfile(exe):
            QMessageBox.warning(self, "Не найден NotesPM.exe", "Положи NotesPM.exe рядом с виджетом.")
            return
        try:
            arg = os.path.dirname(note_json_path) if note_json_path else ""
            if arg:
                subprocess.Popen([exe, arg], shell=False)
            else:
                subprocess.Popen([exe], shell=False)
        except Exception as e:
            QMessageBox.warning(self, "Ошибка запуска", f"Не удалось запустить NotesPM.exe:{e}")

    def _save_notes(self) -> None:
        payload = []
        now = _now_iso()
        for i in range(self.list.count()):
            it = self.list.item(i)
            txt = (it.text() or "").lstrip("📌 ").strip()
            if not txt:
                continue
            payload.append({
                "id": it.data(Qt.ItemDataRole.UserRole) or str(uuid.uuid4()),
                "text": txt,
                "created": it.data(Qt.ItemDataRole.UserRole + 1) or now,
                "updated": now,
            })
        self._atomic_write(NOTES_WIDGET_PATH, payload)

    def reload_notes(self) -> None:
        self.list.clear()
        for n in self._scan_app_notes():
            it = QListWidgetItem("📝 " + n["text"])
            it.setData(Qt.ItemDataRole.UserRole, n["id"])
            it.setData(Qt.ItemDataRole.UserRole + 1, n["created"])
            it.setData(Qt.ItemDataRole.UserRole + 2, "app")
            it.setData(Qt.ItemDataRole.UserRole + 3, n.get("path"))
            self.list.addItem(it)
        for n in self._read_notes():
            it = QListWidgetItem("📌 " + n["text"])
            it.setData(Qt.ItemDataRole.UserRole, n["id"])
            it.setData(Qt.ItemDataRole.UserRole + 1, n["created"])
            it.setData(Qt.ItemDataRole.UserRole + 2, "widget")
            it.setData(Qt.ItemDataRole.UserRole + 3, n.get("path"))
            self.list.addItem(it)

    def add_note(self) -> None:
        text, ok = QInputDialog.getMultiLineText(self, "Новая заметка", "Введите текст:")
        if ok:
            text = (text or "").strip()
            if not text:
                return
            it = QListWidgetItem("📌 " + text)
            ts = _now_iso()
            it.setData(Qt.ItemDataRole.UserRole, str(uuid.uuid4()))
            it.setData(Qt.ItemDataRole.UserRole + 1, ts)
            self.list.addItem(it)
            self._save_notes()

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        src = item.data(Qt.ItemDataRole.UserRole + 2) or "widget"
        if src == "app":
            note_path = item.data(Qt.ItemDataRole.UserRole + 3)
            if note_path and os.path.isfile(note_path):
                self._launch_notespm(note_path)
                return
            self.reload_notes()
            return
        note_path = self._materialize_widget_note(item)
        if note_path:
            self._launch_notespm(note_path)
        else:
            self.edit_note(item)

    def edit_note(self, item: QListWidgetItem | None = None) -> None:
        if item is None:
            item = self.list.currentItem()
            if not item:
                return
        cur = item.text().lstrip("📌 ").strip()
        text, ok = QInputDialog.getMultiLineText(self, "Редактировать заметку", "Текст:", cur)
        if ok:
            item.setText("📌 " + (text or "").strip())
            self._save_notes()

    def delete_selected(self) -> None:
        row = self.list.currentRow()
        if row < 0:
            return
        item = self.list.item(row)
        src = item.data(Qt.ItemDataRole.UserRole + 2) or "widget"
        if src == "app":
            QMessageBox.information(self, "Удаление запрещено",
                                    "Заметки приложения нельзя удалять из виджета. Открой их в приложении.")
            return
        if QMessageBox.question(self, "Удаление", "Удалить выбранную заметку?") == QMessageBox.StandardButton.Yes:
            self.list.takeItem(row)
            self._save_notes()

    def clear_all(self) -> None:
        if QMessageBox.question(self, "Подтверждение", "Очистить все заметки виджета?") == QMessageBox.StandardButton.Yes:
            self.list.clear()
            self._save_notes()

    def _context_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        menu = QMenu(self)
        act_add = menu.addAction("Добавить…")
        act_edit = menu.addAction("Редактировать…")
        act_del = menu.addAction("Удалить")
        menu.addSeparator()
        act_reload = menu.addAction("Обновить")
        menu.addSeparator()
        act_clear = menu.addAction("Очистить всё")
        act_add.triggered.connect(self.add_note)
        act_edit.triggered.connect(lambda: self.edit_note(item))
        act_del.triggered.connect(self.delete_selected)
        act_reload.triggered.connect(self.reload_notes)
        act_clear.triggered.connect(self.clear_all)
        menu.exec(self.list.mapToGlobal(pos))

def main():
    app = QApplication(sys.argv)
    if os.path.isfile(ICON_PATH):
        app.setWindowIcon(QIcon(ICON_PATH))

    w = DesktopNotesWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()