import os
import json
import uuid as _uuid
import mimetypes
import time
import re
from typing import Optional
from PySide6.QtCore import Qt, QDateTime
from PySide6.QtGui import QAction, QTextDocument
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QDialogButtonBox,
    QCheckBox, QMessageBox, QLabel, QPushButton, QHBoxLayout
)
from urllib import request as _urlreq
from urllib import parse as _urlparse
from urllib.error import HTTPError, URLError

def _app_dir_from_plugin() -> str:
    here = os.path.abspath(os.path.dirname(__file__))
    appdir = os.path.dirname(here)
    return appdir

def _data_dir() -> str:
    return os.path.join(_app_dir_from_plugin(), "Data")

def _notes_dir() -> str:
    return os.path.join(_app_dir_from_plugin(), "Notes")

def _read_file_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()

def _parse_tg_http_error(e: HTTPError) -> dict:
    try:
        raw = e.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        if isinstance(data, dict):
            if "ok" not in data:
                data["ok"] = False
            if "description" not in data:
                data["description"] = f"HTTP {e.code}: {raw[:200]}"
            return data
        return {"ok": False, "description": f"HTTP {e.code}: {raw[:200]}"}
    except Exception:
        return {"ok": False, "description": f"{e}"}

def _http_post_form(url: str, data: dict, timeout: int = 20) -> dict:
    body = _urlparse.urlencode(data).encode("utf-8")
    req = _urlreq.Request(url, data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded; charset=utf-8"
    })
    try:
        with _urlreq.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)
    except HTTPError as e:
        return _parse_tg_http_error(e)
    except URLError as e:
        return {"ok": False, "description": f"Network error: {e}"}
    except Exception as e:
        return {"ok": False, "description": f"{e}"}

def _http_get(url: str, timeout: int = 20) -> dict:
    req = _urlreq.Request(url)
    try:
        with _urlreq.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)
    except HTTPError as e:
        return _parse_tg_http_error(e)
    except URLError as e:
        return {"ok": False, "description": f"Network error: {e}"}
    except Exception as e:
        return {"ok": False, "description": f"{e}"}

def _http_post_multipart(url: str, fields: dict, files: list[tuple]) -> dict:
    boundary = f"----Boundary{int(time.time()*1000)}{_uuid.uuid4().hex}"
    CRLF = b"\r\n"
    parts = []
    for name, value in fields.items():
        parts.append(b"--" + boundary.encode("ascii"))
        header = f'Content-Disposition: form-data; name="{name}"'.encode("utf-8")
        parts.append(header)
        parts.append(b"")
        parts.append(str(value).encode("utf-8"))
    for fieldname, filename, filebytes in files:
        parts.append(b"--" + boundary.encode("ascii"))
        disp = f'Content-Disposition: form-data; name="{fieldname}"; filename="{os.path.basename(filename)}"'.encode("utf-8")
        parts.append(disp)
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        parts.append(f"Content-Type: {ctype}".encode("utf-8"))
        parts.append(b"")
        parts.append(filebytes)
    parts.append(b"--" + boundary.encode("ascii") + b"--")
    parts.append(b"")
    body = CRLF.join(parts)
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    req = _urlreq.Request(url, data=body, headers=headers)
    try:
        with _urlreq.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)
    except HTTPError as e:
        return _parse_tg_http_error(e)
    except URLError as e:
        return {"ok": False, "description": f"Network error: {e}"}
    except Exception as e:
        return {"ok": False, "description": f"{e}"}


def _split_message(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts = []
    start = 0
    while start < len(text):
        end = min(len(text), start + limit)
        cut = text.rfind("\n", start, end)
        if cut == -1 or cut <= start + 100:
            cut = end
        parts.append(text[start:cut])
        start = cut
    return parts

class _Config:
    def __init__(self):
        self.token: str = ""
        self.chat_id: str = ""
        self.send_attachments: bool = False

    @property
    def path(self) -> str:
        os.makedirs(_data_dir(), exist_ok=True)
        return os.path.join(_data_dir(), "telegram_sender.json")

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.token = data.get("token", "")
            self.chat_id = data.get("chat_id", "")
            self.send_attachments = bool(data.get("send_attachments", False))
        except Exception:
            pass

    def save(self):
        data = {
            "token": self.token.strip(),
            "chat_id": self.chat_id.strip(),
            "send_attachments": bool(self.send_attachments),
        }
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, self.path)

_token_re = re.compile(r"^\d+:[A-Za-z0-9_-]{30,}$")
_chatid_re = re.compile(r"^-?\d{5,15}$")

def _validate_token(token: str) -> tuple[bool, str]:
    if not token:
        return False, "Укажите токен бота."
    if not _token_re.match(token):
        return False, "Токен выглядит некорректно. Пример: 123456789:AA... (цифры, двоеточие, длинная строка)."
    return True, ""

def _validate_chat_id(chat_id: str) -> tuple[bool, str]:
    if not chat_id:
        return False, "Укажите chat_id получателя."
    if chat_id.startswith("@"):
        return True, ""
    if not _chatid_re.match(chat_id):
        return False, "chat_id должен быть числом (7–12 цифр, для групп может начинаться с «-»)."
    return True, ""

def _tg_api_url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"

def _tg_get_me(token: str) -> dict:
    return _http_get(_tg_api_url(token, "getMe"))

def _tg_get_updates(token: str, limit: int = 10) -> dict:
    return _http_get(_tg_api_url(token, f"getUpdates?limit={limit}"))

def _tg_send_message(token: str, chat_id: str, text: str) -> dict:
    return _http_post_form(_tg_api_url(token, "sendMessage"),
                           {"chat_id": chat_id, "text": text, "disable_web_page_preview": True})

def _tg_send_document(token: str, chat_id: str, file_path: str, caption: str = "") -> dict:
    files = [("document", os.path.basename(file_path), _read_file_bytes(file_path))]
    fields = {"chat_id": chat_id}
    if caption:
        fields["caption"] = caption[:1000]
    return _http_post_multipart(_tg_api_url(token, "sendDocument"), fields, files)


class _SendDialog(QDialog):
    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.setWindowTitle("Отправить текущую заметку в Telegram")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.cfg = _Config()
        self.cfg.load()
        layout = QFormLayout(self)
        self.ed_token = QLineEdit(self.cfg.token)
        self.ed_token.setEchoMode(QLineEdit.Password)
        layout.addRow("Bot Token:", self.ed_token)
        self.ed_chat = QLineEdit(self.cfg.chat_id)
        self.ed_chat.setPlaceholderText("Напр.: 123456789  или  -1001234567890  или  @channelusername")
        layout.addRow("Target Chat ID:", self.ed_chat)
        self.cb_attach = QCheckBox("Отправлять вложения из папки заметки")
        self.cb_attach.setChecked(self.cfg.send_attachments)
        layout.addRow("", self.cb_attach)
        btn_row = QHBoxLayout()
        self.btn_detect = QPushButton("Определить chat_id")
        self.btn_test = QPushButton("Отправить тест")
        self.btn_detect.clicked.connect(self.on_detect_chat_id)
        self.btn_test.clicked.connect(self.on_send_test)
        btn_row.addWidget(self.btn_detect)
        btn_row.addWidget(self.btn_test)
        layout.addRow(btn_row)
        help_lbl = QLabel(
            "Подсказка:\n"
            "1) Создать бота в @BotFather\n"
            "2) «Start» в боте\n"
            "3) «Определить chat_id»\n"
        )
        help_lbl.setWordWrap(True)
        help_lbl.setStyleSheet("color: gray; font-size: 12px;")
        layout.addRow(help_lbl)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_values(self) -> tuple[str, str, bool]:
        token = self.ed_token.text().strip()
        chat_id = self.ed_chat.text().strip()
        send_atts = self.cb_attach.isChecked()
        self.cfg.token, self.cfg.chat_id, self.cfg.send_attachments = token, chat_id, send_atts
        self.cfg.save()
        return token, chat_id, send_atts
    def on_detect_chat_id(self):
        token = self.ed_token.text().strip()
        ok, msg = _validate_token(token)
        if not ok:
            QMessageBox.warning(self, "Проверка токена", msg); return
        info = _tg_get_updates(token)
        if not info.get("ok"):
            QMessageBox.critical(self, "getUpdates", f"Не удалось получить обновления:\n{info.get('description')}")
            return
        updates = info.get("result", [])
        if not updates:
            QMessageBox.information(self, "getUpdates", "Новых сообщений нет. Напишите боту «/start» и попробуйте ещё раз.")
            return
        chat = None
        for upd in reversed(updates):
            for k in ("message", "edited_message", "channel_post", "edited_channel_post"):
                if k in upd and "chat" in upd[k]:
                    chat = upd[k]["chat"]; break
            if chat: break
        if not chat:
            QMessageBox.information(self, "getUpdates", "Не нашли chat в последних обновлениях.")
            return
        cid = str(chat.get("id", ""))
        title = chat.get("title") or chat.get("username") or chat.get("first_name", "")
        self.ed_chat.setText(cid)
        QMessageBox.information(self, "Готово", f"Определили chat_id: {cid}\n{title or ''}")

    def on_send_test(self):
        token = self.ed_token.text().strip()
        chat_id = self.ed_chat.text().strip()
        ok_t, msg_t = _validate_token(token)
        if not ok_t:
            QMessageBox.warning(self, "Проверка токена", msg_t); return
        ok_c, msg_c = _validate_chat_id(chat_id)
        if not ok_c:
            QMessageBox.warning(self, "Проверка chat_id", msg_c); return
        resp = _tg_send_message(token, chat_id, "🔧 Тест: соединение с ботом и chat_id работает.")
        if resp.get("ok"):
            QMessageBox.information(self, "Тест", "Сообщение отправлено.")
        else:
            QMessageBox.critical(self, "Тест", f"Не удалось отправить тест:\n{resp.get('description')}")

def _current_note(parent) -> Optional[object]:
    try:
        return getattr(parent, "current_note", None)
    except Exception:
        return None


def _note_plain_text(note_html: str) -> str:
    doc = QTextDocument()
    doc.setHtml(note_html or "")
    return doc.toPlainText()


def _note_folder(parent, note) -> str:
    folder_name = parent.safe_folder_name(note.title, note.uuid, note.timestamp)
    return os.path.join(_notes_dir(), folder_name)


def _send_text_via_bot(token: str, chat_id: str, text: str) -> None:
    chunks = _split_message(text, 4000)
    for part in chunks:
        resp = _tg_send_message(token, chat_id, part)
        if not resp.get("ok", False):
            raise RuntimeError(resp.get("description", "Telegram error"))


def _send_file_via_bot(token: str, chat_id: str, file_path: str, caption: str = "") -> None:
    resp = _tg_send_document(token, chat_id, file_path, caption=caption)
    if not resp.get("ok", False):
        raise RuntimeError(resp.get("description", "Telegram error"))


def _build_text_for_note(note) -> str:
    title = note.title or "(без названия)"
    try:
        dt = QDateTime.fromString(note.timestamp or "", Qt.ISODate)
        date_str = dt.toString("dd.MM.yyyy HH:mm") if dt and dt.isValid() else ""
    except Exception:
        date_str = ""
    html = getattr(note, "content", "") or ""
    body = _note_plain_text(html).strip()
    header = f"📝 {title}"
    if date_str:
        header += f"\nДата: {date_str}"
    if getattr(note, "tags", None):
        try:
            tags_line = ", ".join(note.tags)
            if tags_line:
                header += f"\nТеги: {tags_line}"
        except Exception:
            pass
    text = f"{header}\n\n{body}" if body else header
    return text


def _send_current_note_impl(parent):
    note = _current_note(parent)
    if not note:
        QMessageBox.information(parent, "Telegram", "Нет открытой заметки для отправки.")
        return

    dlg = _SendDialog(parent)
    if dlg.exec() != QDialog.Accepted:
        return
    token, chat_id, send_attachments = dlg.get_values()

    ok_t, msg_t = _validate_token(token)
    ok_c, msg_c = _validate_chat_id(chat_id)
    if not ok_t or not ok_c:
        QMessageBox.warning(parent, "Проверка данных", msg_t if not ok_t else msg_c)
        return
    try:
        if getattr(parent, "text_edit", None) is not None:
            note.content = parent.text_edit.toHtml()
    except Exception:
        pass
    text = _build_text_for_note(note)
    resp = _tg_send_message(token, chat_id, text)
    if not resp.get("ok"):
        QMessageBox.critical(parent, "Telegram", f"Не удалось отправить текст:\n{resp.get('description')}")
        return
    if send_attachments:
        try:
            folder = _note_folder(parent, note)
            if os.path.isdir(folder):
                for name in os.listdir(folder):
                    if name == "note.json":
                        continue
                    fpath = os.path.join(folder, name)
                    if os.path.isfile(fpath):
                        caption = f"Вложение: {name}"
                        doc_resp = _tg_send_document(token, chat_id, fpath, caption=caption)
                        if not doc_resp.get("ok"):
                            raise RuntimeError(doc_resp.get("description", "Telegram error"))
        except Exception as e:
            QMessageBox.warning(parent, "Telegram", f"Текст отправлен, но вложения не отправились:\n{e}")

    QMessageBox.information(parent, "Telegram", "Заметка успешно отправлена.")
_action_send = None

def on_enable(parent):
    global _action_send
    plugins_menu = None
    try:
        mbar = parent.menuBar()
        for menu in mbar.children():
            try:
                if menu.title() == "Плагины":
                    plugins_menu = menu
                    break
            except Exception:
                continue
        if plugins_menu is None:
            plugins_menu = mbar.addMenu("Плагины")
    except Exception:
        return
    _action_send = QAction("Отправить текущую заметку в Telegram…", parent)
    _action_send.triggered.connect(lambda: _send_current_note_impl(parent))
    plugins_menu.addAction(_action_send)

def on_disable(parent):
    global _action_send
    try:
        if _action_send is not None:
            for menu in parent.menuBar().children():
                try:
                    if getattr(menu, "title", None) and menu.title() == "Плагины":
                        try:
                            menu.removeAction(_action_send)
                        except Exception:
                            pass
                        break
                except Exception:
                    continue
            _action_send.deleteLater()
            _action_send = None
    except Exception:
        pass
