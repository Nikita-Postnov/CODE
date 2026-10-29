"""Плавающий desktop-виджет липких заметок."""

from PySide6.QtCore import (
    Qt,
    QTimer,
    QUrl,
    QSettings,
    QEvent,
    QDateTime,
    QPoint,
    QRect,
)

from PySide6.QtGui import (
    QCursor,
    QCloseEvent,
    QDesktopServices,
)

from PySide6.QtWidgets import (
    QApplication,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QWidget,
    QLabel,
    QMessageBox,
    QInputDialog,
    QAbstractItemView,
    QMenu,
    QToolButton,
    QSizeGrip,
)

from pathlib import Path
import datetime
import html as html_lib
import json
import logging
import os
import shutil
import uuid

from ..config import DATA_DIR, NOTES_DIR, NOTES_WIDGET_BAK, NOTES_WIDGET_PATH, SETTINGS_PATH, qt_path
from ..models import Note
from ..utils import safe_folder_name


class DesktopNotesWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Заметки на рабочем столе")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(340, 420)
        self.setMinimumWidth(260)
        self.setMinimumHeight(120)
        self._resize_active = False
        self._resize_edge = 0
        self._RESIZE_MARGIN = 8
        self._drag_active = False
        self._drag_offset = QPoint()
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)
        self.title_lbl = QLabel("📋 Заметки", self)
        self.title_lbl.setStyleSheet("font-size: 18px; font-weight: 600; color: white;")
        self.btn_close = QToolButton(self)
        self.btn_close.setObjectName("dnw_close")
        self.btn_close.setText("✕")
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setToolTip("Закрыть")
        self.btn_close.clicked.connect(self.close)

        header_layout.addWidget(self.title_lbl)
        header_layout.addStretch(1)
        header_layout.addWidget(self.btn_close)

        self.header_widget = QWidget(self)
        self.header_widget.setLayout(header_layout)
        self.header_widget.setProperty("drag_handle", True)

        root.addWidget(self.header_widget)
        self.notes_list = QListWidget(self)
        self.notes_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.notes_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.notes_list.setSelectionMode(QAbstractItemView.SingleSelection)
        root.addWidget(self.notes_list, 1)
        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Добавить", self)
        add_btn.clicked.connect(self.add_note)
        btn_row.addWidget(add_btn)
        refresh_btn = QPushButton("Обновить", self)
        refresh_btn.clicked.connect(self.reload_notes)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch(1)
        self._buttons_widget = QWidget(self)
        self._buttons_widget.setLayout(btn_row)
        root.addWidget(self._buttons_widget)
        self.setStyleSheet(
            """
            QWidget {
                background-color: rgba(30, 30, 30, 252);
                border-radius: 12px;
                color: white;
                font-family: Segoe UI;
            }
            QListWidget {
                background-color: rgba(30, 30, 30, 255);
                border: none;
                color: white;
                font-size: 14px;
            }
            QPushButton {
                background-color: #3a3f47;
                border-radius: 8px;
                padding: 6px 12px;
                color: white;
            }
            QPushButton:hover {
                background-color: #505860;
            }
            QToolButton#dnw_close {
                background: transparent;
                border: none;
                padding: 2px 8px;
                font-weight: 700;
                font-size: 14px;
                color: #ffffff;
                border-radius: 8px;
            }
            QToolButton#dnw_close:hover { background-color: rgba(255, 255, 255, 0.18); }
            QToolButton#dnw_close:pressed { background-color: rgba(255, 255, 255, 0.28); }
        """
        )
        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 0, 0)
        grip_row.addStretch(1)
        self._grip = QSizeGrip(self)
        self._grip.setToolTip("Потяните за угол, чтобы изменить размер")
        grip_row.addWidget(self._grip, 0, Qt.AlignRight | Qt.AlignBottom)
        self._grip_widget = QWidget(self)
        self._grip_widget.setLayout(grip_row)
        root.addWidget(self._grip_widget)
        self._grip_top_right = QSizeGrip(self)
        self._grip_top_right.setToolTip(
            "Потяните за верхний правый угол, чтобы изменить размер"
        )
        self._grip_top_right.setFixedSize(16, 16)
        self._grip_top_right.raise_()
        self.notes_list.itemDoubleClicked.connect(self._on_item_activated)
        self.notes_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.notes_list.customContextMenuRequested.connect(self.show_context_menu)
        self.title_lbl.setProperty("drag_handle", True)
        self.installEventFilter(self)
        self.title_lbl.installEventFilter(self)
        self.notes_list.installEventFilter(self)
        self.header_widget.installEventFilter(self)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load_pos()
        self.reload_notes()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not hasattr(self, "_resize_deb"):
            self._resize_deb = QTimer(self)
            self._resize_deb.setSingleShot(True)
            self._resize_deb.setInterval(0)
            self._resize_deb.timeout.connect(self._apply_auto_min_height)
        self._resize_deb.start()

    def changeEvent(self, e):
        if e.type() == QEvent.WindowStateChange:
            QTimer.singleShot(0, self._apply_auto_min_height)
        super().changeEvent(e)

    def _calc_needed_height(self) -> int:
        root: QVBoxLayout = self.layout()
        header_h = (
            self.header_widget.sizeHint().height()
            if hasattr(self, "header_widget")
            else 0
        )
        buttons_h = (
            self._buttons_widget.sizeHint().height()
            if hasattr(self, "_buttons_widget")
            else 0
        )
        grip_h = (
            self._grip_widget.sizeHint().height()
            if hasattr(self, "_grip_widget")
            else 0
        )
        count = self.notes_list.count()
        if count > 0:
            row_h = max(1, self.notes_list.sizeHintForRow(0))
        else:
            row_h = self.notes_list.fontMetrics().height() + 8
        list_h = row_h * max(1, count) + 2 * self.notes_list.frameWidth()
        m = root.contentsMargins()
        margins = m.top() + m.bottom()
        spacings = root.spacing() * 3
        total = margins + header_h + list_h + buttons_h + grip_h + spacings
        try:
            avail_h = (
                self.screen().availableGeometry().height() if self.screen() else 1000
            ) - 20
            total = min(total, max(200, avail_h))
        except Exception:
            pass
        return max(total, self.minimumSizeHint().height(), 120)

    def _apply_auto_min_height(self) -> None:
        h_min = int(self._calc_needed_height())
        self.setMinimumHeight(h_min)
        if self.height() < h_min:
            self.resize(self.width(), h_min)

    def _edge_at(self, pos: QPoint) -> int:
        m = getattr(self, "_RESIZE_MARGIN", 8)
        r = self.rect()
        edge = 0
        if pos.x() <= r.left() + m:
            edge |= 1
        if pos.x() >= r.right() - m:
            edge |= 2
        if pos.y() <= r.top() + m:
            edge |= 4
        if pos.y() >= r.bottom() - m:
            edge |= 8
        return edge

    def _set_cursor_for_edge(self, edge: int) -> None:
        if edge in (1, 2):
            self.setCursor(Qt.SizeHorCursor)
        elif edge in (4, 8):
            self.setCursor(Qt.SizeVerCursor)
        elif edge in (1 | 4, 2 | 8):
            self.setCursor(Qt.SizeFDiagCursor)
        elif edge in (1 | 8, 2 | 4):
            self.setCursor(Qt.SizeBDiagCursor)
        else:
            self.unsetCursor()

    def _read_json_any(self, path: str) -> list[dict]:
        if not os.path.exists(path):
            return []

        try:
            raw = open(path, "r", encoding="utf-8").read().strip()
            if not raw:
                return []
            data = json.loads(raw)
        except Exception:
            logging.exception("DesktopNotesWidget: load error: %s", path)
            return []

        def _now_iso():
            return datetime.datetime.now().isoformat(timespec="seconds")

        notes: list[dict] = []
        if isinstance(data, list) and all(isinstance(x, dict) for x in data):
            for x in data:
                txt = (x.get("text") or "").strip()
                if not txt:
                    continue
                nid = x.get("id") or str(uuid.uuid4())
                created = x.get("created") or _now_iso()
                updated = x.get("updated") or created
                notes.append(
                    {"id": nid, "text": txt, "created": created, "updated": updated}
                )
            return notes
        if isinstance(data, list) and all(isinstance(x, str) for x in data):
            for s in data:
                txt = (s or "").strip()
                if txt:
                    ts = _now_iso()
                    notes.append(
                        {
                            "id": str(uuid.uuid4()),
                            "text": txt,
                            "created": ts,
                            "updated": ts,
                        }
                    )
            return notes
        if isinstance(data, dict) and "notes" in data:
            return self._read_json_any_from_list_like(data.get("notes"))
        if isinstance(data, dict):
            for k, v in data.items():
                txt = (v or "").strip() if isinstance(v, str) else ""
                if txt:
                    ts = _now_iso()
                    nid = k if isinstance(k, str) else str(uuid.uuid4())
                    notes.append({"id": nid, "text": txt, "created": ts, "updated": ts})
            return notes
        return []

    def _is_drag_source(self, obj, ev) -> bool:
        try:
            if getattr(obj, "property") and obj.property("drag_handle") is True:
                return True
        except Exception:
            pass
        return bool(ev.modifiers() & Qt.AltModifier)

    def _create_app_note_from_text(self, text: str) -> None:
        lines = [ln.strip() for ln in (text or "").splitlines()]
        title = next((ln for ln in lines if ln), "Новая заметка")[:120]
        parts = []
        for ln in (text or "").splitlines():
            if ln.strip():
                parts.append(f"<p>{html_lib.escape(ln)}</p>")
            else:
                parts.append("<p><br/></p>")
        content_html = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>"
            + "".join(parts)
            + "</body></html>"
        )
        note_uuid = str(uuid.uuid4())
        timestamp = QDateTime.currentDateTime().toString(Qt.ISODate)
        note = Note(
            title=title,
            content=content_html,
            tags=[],
            favorite=False,
            timestamp=timestamp,
            reminder=None,
            uuid=note_uuid,
        )
        note.history = [content_html]
        note.history_index = 0
        folder_name = safe_folder_name(title, note_uuid, timestamp)
        note_dir = NOTES_DIR / folder_name
        os.makedirs(note_dir, exist_ok=True)
        note_path = os.path.join(note_dir, "note.json")
        with open(note_path, "w", encoding="utf-8") as f:
            json.dump(note.to_dict(), f, ensure_ascii=False, indent=2)

    def eventFilter(self, obj, ev):
        et = ev.type()
        if hasattr(ev, "globalPosition"):
            gp = ev.globalPosition().toPoint()
        else:
            gp = QCursor.pos()
        lp = self.mapFromGlobal(gp)
        if et == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
            edge = self._edge_at(lp)
            if edge:
                self._resize_active = True
                self._resize_edge = edge
                self._resize_start_geom = self.frameGeometry()
                self._resize_start_pos = gp
                return True
            if self._is_drag_source(obj, ev):
                self._drag_active = True
                self._drag_offset = gp - self.frameGeometry().topLeft()
                return True
        elif et == QEvent.MouseMove:
            if self._resize_active:
                dx = gp.x() - self._resize_start_pos.x()
                dy = gp.y() - self._resize_start_pos.y()
                g = QRect(self._resize_start_geom)
                if self._resize_edge & 1:
                    g.setLeft(g.left() + dx)
                if self._resize_edge & 2:
                    g.setRight(g.right() + dx)
                if self._resize_edge & 4:
                    g.setTop(g.top() + dy)
                if self._resize_edge & 8:
                    g.setBottom(g.bottom() + dy)
                minw, minh = self.minimumWidth(), self.minimumHeight()
                if g.width() < minw:
                    if self._resize_edge & 1:
                        g.setLeft(g.right() - minw)
                    else:
                        g.setRight(g.left() + minw)
                if g.height() < minh:
                    if self._resize_edge & 4:
                        g.setTop(g.bottom() - minh)
                    else:
                        g.setBottom(g.top() + minh)
                self.setGeometry(g)
                return True
            edge = self._edge_at(lp)
            self._set_cursor_for_edge(edge)
            if self._drag_active:
                self.move(gp - self._drag_offset)
                return True
        elif et == QEvent.MouseButtonRelease and ev.button() == Qt.LeftButton:
            if self._resize_active:
                self._resize_active = False
                self._resize_edge = 0
                self._save_pos()
                self.unsetCursor()
                return True
            if self._drag_active:
                self._drag_active = False
                self._save_pos()
                return True
        return False

    def _load_pos(self):
        try:
            s = QSettings(qt_path(SETTINGS_PATH), QSettings.IniFormat)
            s.beginGroup("DesktopNotesWidget")
            if s.contains("x") and s.contains("y"):
                self.move(int(s.value("x", type=int)), int(s.value("y", type=int)))
            if s.contains("w") and s.contains("h"):
                w = int(s.value("w", type=int))
                h = int(s.value("h", type=int))
                if w > 100 and h > 100:
                    self.resize(w, h)
            s.endGroup()
        except Exception:
            pass

    def _save_pos(self):
        try:
            s = QSettings(qt_path(SETTINGS_PATH), QSettings.IniFormat)
            s.beginGroup("DesktopNotesWidget")
            s.setValue("x", self.x())
            s.setValue("y", self.y())
            s.setValue("w", self.width())
            s.setValue("h", self.height())
            s.endGroup()
        except Exception:
            pass

    def _read_json_any_from_list_like(self, value) -> list[dict]:
        if isinstance(value, list):
            out = []
            for item in value:
                if isinstance(item, str):
                    ts = datetime.datetime.now().isoformat(timespec="seconds")
                    out.append(
                        {
                            "id": str(uuid.uuid4()),
                            "text": item.strip(),
                            "created": ts,
                            "updated": ts,
                        }
                    )
                elif isinstance(item, dict):
                    txt = (item.get("text") or "").strip()
                    if not txt:
                        continue
                    nid = item.get("id") or str(uuid.uuid4())
                    created = item.get("created") or datetime.datetime.now().isoformat(
                        timespec="seconds"
                    )
                    updated = item.get("updated") or created
                    out.append(
                        {"id": nid, "text": txt, "created": created, "updated": updated}
                    )
            return out
        return []

    def _scan_app_notes(self) -> list[dict]:
        items: list[dict] = []
        try:
            if not os.path.isdir(NOTES_DIR):
                return items
            max_depth = 3
            base = os.path.abspath(NOTES_DIR)

            def depth(path: str) -> int:
                rel = os.path.relpath(path, base)
                if rel == ".":
                    return 0
                return rel.count(os.sep) + 1

            note_json_paths: list[str] = []
            for root, dirs, files in os.walk(base):
                dirs[:] = [d for d in dirs if d != "Trash"]
                if depth(root) > max_depth:
                    dirs[:] = []
                    continue
                if "note.json" in files:
                    note_json_paths.append(os.path.join(root, "note.json"))
            for file_path in note_json_paths:
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    title = (data.get("title") or data.get("text") or os.path.basename(os.path.dirname(file_path))).strip()
                    created = (data.get("timestamp") or data.get("created") or "").strip()
                    nid = (data.get("uuid") or data.get("id") or str(uuid.uuid4())).strip()
                    items.append({
                        "id": nid,
                        "text": title,
                        "created": created,
                        "updated": (data.get("updated") or created or "").strip(),
                        "source": "app",
                        "path": file_path,
                    })
                except Exception:
                    logging.exception("scan app notes error: %s", file_path)
            if not items:
                for folder in os.listdir(NOTES_DIR):
                    if folder == "Trash":
                        continue
                    folder_path = os.path.join(NOTES_DIR, folder)
                    if not os.path.isdir(folder_path):
                        continue
                    candidates = [fn for fn in os.listdir(folder_path) if fn.lower().endswith(".json")]
                    for fn in candidates:
                        p = os.path.join(folder_path, fn)
                        try:
                            with open(p, "r", encoding="utf-8") as f:
                                data = json.load(f)
                            if not isinstance(data, dict):
                                continue
                            if not any(k in data for k in ("title", "text", "uuid", "id", "timestamp", "created")):
                                continue
                            title = (data.get("title") or data.get("text") or folder).strip()
                            created = (data.get("timestamp") or data.get("created") or "").strip()
                            nid = (data.get("uuid") or data.get("id") or str(uuid.uuid4())).strip()
                            items.append({
                                "id": nid,
                                "text": title,
                                "created": created,
                                "updated": (data.get("updated") or created or "").strip(),
                                "source": "app",
                                "path": p,
                            })
                            break
                        except Exception:
                            continue
        except Exception:
            logging.exception("scan app notes failed")
        return items

    def _atomic_write(self, path: Path | str, payload: list[dict]) -> None:
        path = path if isinstance(path, Path) else Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = json.dumps(payload, ensure_ascii=False, indent=2)
        tmp = path.with_name(path.name + ".tmp")

        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

        try:
            if path.exists():
                shutil.copy2(path, NOTES_WIDGET_BAK)
        except Exception:
            pass

        os.replace(tmp, path)

    def _model_from_ui(self) -> list[dict]:
        out = []
        now_iso = datetime.datetime.now().isoformat(timespec="seconds")
        for i in range(self.notes_list.count()):
            it = self.notes_list.item(i)
            src = it.data(Qt.UserRole + 2) or "widget"
            if src != "widget":
                continue
            txt = (it.text() or "").removeprefix("📌 ").strip()
            if not txt:
                continue
            nid = it.data(Qt.UserRole) or str(uuid.uuid4())
            created = it.data(Qt.UserRole + 1) or now_iso
            updated = now_iso
            out.append({"id": nid, "text": txt, "created": created, "updated": updated})
        return out

    def _ui_from_model(self, notes: list[dict]) -> None:
        self.notes_list.clear()
        for n in notes:
            txt = n.get("text", "")
            src = n.get("source", "widget")
            prefix = "📝 " if src == "app" else ""
            item = QListWidgetItem(prefix + txt)
            item.setData(Qt.UserRole, n.get("id"))
            item.setData(Qt.UserRole + 1, n.get("created"))
            item.setData(Qt.UserRole + 2, src)
            item.setData(Qt.UserRole + 3, n.get("path"))
            self.notes_list.addItem(item)

    def reload_notes(self):
        widget_notes = self._read_json_any(NOTES_WIDGET_PATH)
        for n in widget_notes:
            n["source"] = "widget"
            n["path"] = qt_path(NOTES_WIDGET_PATH)
        app_notes = self._scan_app_notes()
        combined = app_notes + widget_notes
        self._ui_from_model(combined)
        self._apply_auto_min_height()

    def save_notes(self):
        notes = self._model_from_ui()
        self._atomic_write(NOTES_WIDGET_PATH, notes)

    def add_note(self):
        text, ok = QInputDialog.getMultiLineText(
            self, "Новая заметка (виджет)", "Введите текст:"
        )
        if ok:
            text = (text or "").strip()
            if not text:
                return
            self._create_app_note_from_text(text)
            self.reload_notes()
            self._apply_auto_min_height()
            QMessageBox.information(self, "Создано", "Заметка добавлена.")

    def _on_item_activated(self, item: QListWidgetItem):
        src = item.data(Qt.UserRole + 2) or "widget"
        if src == "app":
            self.open_app_note_in_app(item)
        else:
            self.edit_note(item)

    def edit_note(self, item: QListWidgetItem):
        src = item.data(Qt.UserRole + 2) or "widget"
        if src == "app":
            self.open_app_note_in_app(item)
            return
        cur_text = (item.text() or "").removeprefix("📌 ").strip()
        text, ok = QInputDialog.getMultiLineText(
            self, "Редактировать заметку", "Текст:", cur_text
        )
        if ok:
            item.setText("📌 " + (text or "").strip())
            self.save_notes()

    def delete_selected(self):
        row = self.notes_list.currentRow()
        if row < 0:
            return
        it = self.notes_list.item(row)
        src = it.data(Qt.UserRole + 2) or "widget"
        if src == "app":
            QMessageBox.information(
                self,
                "Удаление запрещено",
                "Удаление системных заметок из виджета отключено.",
            )
            return
        self.notes_list.takeItem(row)
        self.save_notes()
        self._apply_auto_min_height()

    def open_app_note_folder(self, item: QListWidgetItem):
        path = item.data(Qt.UserRole + 3)
        if path and os.path.isfile(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    def open_app_note_in_app(self, item: QListWidgetItem) -> None:
        try:
            target_uuid = item.data(Qt.UserRole) or None
            path = item.data(Qt.UserRole + 3) or None
            title_text = (item.text() or "").removeprefix("📝 ").strip()
            app = QApplication.instance()
            launcher = getattr(app, "launcher_window", None) if app else None
            notes_win = None
            if launcher is not None and hasattr(launcher, "launch_notes"):
                launcher.launch_notes()
                notes_win = launcher.notes_window
            else:
                from noteapp.app import NotesApp  # локальный импорт: разрыв цикла
                notes_win = NotesApp()
                notes_win.show()
                notes_win.raise_()
                notes_win.activateWindow()
            if hasattr(notes_win, "load_notes_from_disk"):
                notes_win.load_notes_from_disk()
            if hasattr(notes_win, "refresh_notes_list"):
                notes_win.refresh_notes_list()
            if not target_uuid and path and os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    target_uuid = data.get("uuid")
                except Exception:
                    target_uuid = None
            matched_item = None
            for i in range(notes_win.notes_list.count()):
                it = notes_win.notes_list.item(i)
                note_obj = it.data(Qt.UserRole)
                if not note_obj:
                    continue
                if (target_uuid and getattr(note_obj, "uuid", None) == target_uuid) or (
                    not target_uuid
                    and title_text
                    and getattr(note_obj, "title", "") == title_text
                ):
                    matched_item = it
                    break
            if matched_item is not None:
                notes_win.notes_list.setCurrentItem(matched_item)
                notes_win.select_note(matched_item.data(Qt.UserRole))
                notes_win.raise_()
                notes_win.activateWindow()
            else:
                QMessageBox.information(
                    self,
                    "Заметка не найдена",
                    "Не удалось найти заметку в приложении. Список был обновлён.",
                )
        except Exception as e:
            QMessageBox.warning(
                self, "Ошибка", f"Не удалось открыть заметку в приложении: {e}"
            )

    def open_notes_app(self):
        app = QApplication.instance()
        launcher = getattr(app, "launcher_window", None) if app else None
        try:
            if launcher is not None and hasattr(launcher, "launch_notes"):
                launcher.launch_notes()
            else:
                from noteapp.app import NotesApp  # локальный импорт: разрыв цикла
                win = NotesApp()
                win.show()
                win.raise_()
                win.activateWindow()
        except Exception as e:
            QMessageBox.warning(
                self, "Ошибка", f"Не удалось открыть приложение 'Заметки': {e}"
            )

    def show_context_menu(self, pos):
        item = self.notes_list.itemAt(pos)
        menu = QMenu(self)
        if item is not None and (item.data(Qt.UserRole + 2) or "widget") == "app":
            menu.addAction(
                "Открыть в «Заметках»", lambda: self.open_app_note_in_app(item)
            )
            menu.addAction(
                "Открыть папку заметки", lambda: self.open_app_note_folder(item)
            )
            menu.addSeparator()
            menu.addAction("Обновить", self.reload_notes)
        else:
            menu.addAction("Удалить", self.delete_selected)
            menu.addSeparator()
            menu.addAction("Обновить", self.reload_notes)
            menu.addAction(
                "Открыть файл хранилища",
                lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(qt_path(NOTES_WIDGET_PATH))),
            )
            menu.addAction("Очистить всё", self.clear_all)
        menu.exec(self.notes_list.mapToGlobal(pos))

    def clear_all(self):
        if (
            QMessageBox.question(self, "Подтверждение", "Удалить все виджет-заметки?")
            == QMessageBox.Yes
        ):
            for i in reversed(range(self.notes_list.count())):
                it = self.notes_list.item(i)
                if (it.data(Qt.UserRole + 2) or "widget") == "widget":
                    self.notes_list.takeItem(i)
            self.save_notes()
            self._apply_auto_min_height()

    def closeEvent(self, e: QCloseEvent):
        self.save_notes()
        self._save_pos()
        super().closeEvent(e)

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._apply_auto_min_height)
