import os
import json
import asyncio
from datetime import datetime
import traceback
import tempfile
from telethon.utils import get_peer_id
import zipfile
import subprocess
import platform
from PySide6.QtCore import Qt, QThread, Signal, QObject, QByteArray, QTimer, QEvent
from PySide6.QtGui import QAction, QPixmap, QMouseEvent, QShortcut, QKeySequence
from typing import Optional, List, Any
import mimetypes
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QWidget,
    QLineEdit,
    QPushButton,
    QLabel,
    QMessageBox,
    QFileDialog,
    QScrollArea,
    QApplication, 
    QSizePolicy,
)
import sqlite3
import time
import shutil


def _temp_dir() -> str:
    d = os.path.join(_data_dir(), "Temp")
    os.makedirs(d, exist_ok=True)
    return d


def _open_in_default_app(path: str):
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(path)
        elif system == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        print("Не удалось открыть файл по умолчанию:", e)


def _app_dir_from_plugin() -> str:
    here = os.path.abspath(os.path.dirname(__file__))
    return os.path.dirname(here)


def _data_dir() -> str:
    d = os.path.join(_app_dir_from_plugin(), "Data")
    os.makedirs(d, exist_ok=True)
    return d
    
SIZE_LIMIT = 100 * 1024 * 1024

def _cache_dir(peer_id: str) -> str:
    d = os.path.join(_data_dir(), "TelegramCache", str(peer_id))
    os.makedirs(d, exist_ok=True)
    return d

SESSION_PATH = os.path.join(_data_dir(), "telegram_user.session")
CONFIG_PATH = os.path.join(_data_dir(), "telegram_user.json")
_TELETHON_ERR = None
_TELETHON_AVAILABLE = True
try:
    from telethon import TelegramClient, events
    from telethon.tl.types import Message, Dialog, User, Channel, Chat
    from telethon.errors import SessionPasswordNeededError
except Exception as e:

    _TELETHON_ERR = e
    _TELETHON_AVAILABLE = False
    TelegramClient = Any
    events = Any
    Message = Any
    Dialog = Any

    class SessionPasswordNeededError(Exception):

        def __init__(
            self, message: str = "Требуется пароль двухэтапной аутентификации (2FA)"
        ):
            super().__init__(message)
            self.message = message

        ...


def _error_box(parent, title, text):
    QMessageBox.critical(parent, title, text)


def _info_box(parent, title, text):
    QMessageBox.information(parent, title, text)


class TgUserConfig:
    def __init__(self):
        self.api_id: Optional[int] = None
        self.api_hash: str = ""
        self.phone: str = ""

    def load(self):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.api_id = data.get("api_id") or None
            self.api_hash = data.get("api_hash") or ""
            self.phone = data.get("phone") or ""
        except Exception:
            pass

    def save(self):
        data = {"api_id": self.api_id, "api_hash": self.api_hash, "phone": self.phone}
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, CONFIG_PATH)


class TelegramWorker(QObject):
    connected = Signal()
    auth_needed = Signal()
    code_needed = Signal()
    password_needed = Signal()
    dialogs_loaded = Signal(list)
    history_loaded = Signal(str, list)
    new_message = Signal(str, dict)
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.client: Optional[TelegramClient] = None  # type: ignore[assignment]
        self.config = TgUserConfig()
        self.config.load()
        self._dlg_search: str | None = None
        self._dlg_offset_date = None
        self._dlg_offset_id = 0
        self._self_id: Optional[int] = None
        self._self_display: str = ""
        self._entities_by_id: dict[str, Any] = {}
        self._dlg_offset_peer = None
        self.current_peer_id: Optional[str] = None
        self._running = False

    async def _serialize_message(self, msg: Message) -> dict:  # type: ignore[type-arg]
        data = {
            "id": getattr(msg, "id", 0),
            "peer_id": str(get_peer_id(getattr(msg, "peer_id", None) or getattr(msg, "to_id", None))),
            "out": bool(getattr(msg, "out", False)),
            "sender_name": "",
            "text": getattr(msg, "message", "") or "",
            "date": "",
            "ts": 0,
            "has_media": bool(getattr(msg, "media", None)),
            "media_kind": "",
            "is_photo_inline": False,
        }
        try:
            raw_dt = getattr(msg, "date", None)
            if raw_dt:
                local_tz = datetime.now().astimezone().tzinfo
                dt_local = raw_dt.astimezone(local_tz)
                data["ts"] = int(dt_local.timestamp())
                data["date"] = dt_local.strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass
        try:
            # 1) для исходящих — всегда показываем своё кешированное имя
            if bool(getattr(msg, "out", False)):
                data["sender_name"] = self._self_display or "Я"
            else:
                name = ""
                try:
                    sender = await msg.get_sender()
                    if isinstance(sender, User):
                        first = sender.first_name or ""
                        last  = sender.last_name or ""
                        name = (f"{first} {last}").strip() or (sender.username or "")
                    elif isinstance(sender, (Channel, Chat)):
                        name = sender.title or ""
                except Exception:
                    name = ""

                if not name:
                    # 2) fallback: берём заголовок собеседника/чата по peer_id
                    peer = str(get_peer_id(getattr(msg, "peer_id", None) or getattr(msg, "to_id", None)))
                    ent = self._entities_by_id.get(peer)
                    if ent is None:
                        try:
                            ent = await self.client.get_entity(int(peer))
                            self._entities_by_id[peer] = ent
                        except Exception:
                            ent = None
                    if isinstance(ent, User):
                        first = ent.first_name or ""
                        last  = ent.last_name or ""
                        name = (f"{first} {last}").strip() or (getattr(ent, "username", "") or "")
                    elif isinstance(ent, (Channel, Chat)):
                        name = getattr(ent, "title", "") or ""

                data["sender_name"] = name or "(неизвестный)"
        except Exception:
            data["sender_name"] = "(неизвестный)"
        try:
            size = None
            f = getattr(msg, "file", None)
            if f:
                data["file_name"] = getattr(f, "name", "") or ""
                data["file_ext"]  = getattr(f, "ext", "") or ""
                data["mime_type"] = getattr(f, "mime_type", "") or ""
                size = getattr(f, "size", None)
                if isinstance(size, int):
                    data["file_size"] = size
            if getattr(msg, "photo", None):
                data["media_kind"] = "photo"
                peer = data.get("peer_id") or str(getattr(msg, "chat_id", "")) or "unknown"
                fname = data.get("file_name") or f"tg_{data.get('id', 0)}{data.get('file_ext') or ''}"
                if not os.path.splitext(fname)[1]:
                    fname = f"{fname}.jpg"
                out_path = os.path.join(_cache_dir(peer), fname)
                if not os.path.exists(out_path):
                    try:
                        await self.client.download_media(msg, file=out_path)
                    except Exception:
                        out_path = ""
                if out_path and os.path.exists(out_path):
                    data["cached_path"] = out_path
                    data["is_photo_inline"] = True
            elif getattr(msg, "sticker", None):
                data["media_kind"] = "sticker"
                b = await self.client.download_media(msg, file=bytes)
                if isinstance(b, (bytes, bytearray)):
                    data["is_photo_inline"] = True
                    data["photo_bytes"] = bytes(b)
            elif getattr(msg, "document", None):
                data["media_kind"] = "document"
            elif getattr(msg, "video", None):
                data["media_kind"] = "video"
            elif getattr(msg, "audio", None):
                data["media_kind"] = "audio"
            elif getattr(msg, "voice", None):
                data["media_kind"] = "voice"
            if (data.get("media_kind") and isinstance(size, int) and size <= SIZE_LIMIT):
                peer = data.get("peer_id") or "unknown"
                fname = data.get("file_name") or f"tg_{data.get('id', 0)}{data.get('file_ext') or ''}"
                if not os.path.splitext(fname)[1]:
                    fname = f"{fname}"
                out_path = os.path.join(_cache_dir(peer), fname)
                if not os.path.exists(out_path):
                    try:
                        await self.client.download_media(msg, file=out_path)
                    except Exception:
                        out_path = ""
                if out_path and os.path.exists(out_path):
                    data["cached_path"] = out_path
        except Exception:
            pass
        return data

    async def ensure_client(self):
        if _TELETHON_ERR is not None:
            raise RuntimeError(
                "Не удалось импортировать Telethon. Установи пакет:\n\n    pip install telethon\n\n"
                f"Техническая ошибка: {repr(_TELETHON_ERR)}"
            )
        if self.client:
            return self.client
        if not self.config.api_id or not self.config.api_hash:
            self.auth_needed.emit()
            return None
        self.loop = asyncio.get_event_loop()
        self.client = TelegramClient(
            SESSION_PATH,
            int(self.config.api_id),
            self.config.api_hash,
            device_model="NotesPM",
            system_version="NotesPM",
            app_version="NotesPM 1.0",
            system_lang_code="ru",
            lang_code="ru",
        )  # type: ignore[call-arg]
        return self.client

    async def connect_and_auth(self):
        client = await self.ensure_client()
        if client is None:
            return
        try:
            await client.connect()
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e).lower():
                try:
                    if os.path.exists(SESSION_PATH):
                        bak = SESSION_PATH + f".bak_{int(time.time())}"
                        try:
                            client.disconnect()
                        except Exception:
                            pass
                        try:
                            os.replace(SESSION_PATH, bak)
                        except Exception:
                            pass
                    self.client = None
                    await self.ensure_client()
                    if self.client:
                        await self.client.connect()
                except Exception as ee:
                    self.error.emit(f"Сессия Telegram повреждена/заблокирована: {ee}")
                    return
            else:
                self.error.emit(f"Ошибка подключения к Telegram: {e}")
                return
        if not await client.is_user_authorized():
            if not self.config.phone:
                self.auth_needed.emit()
                return
            try:
                await client.send_code_request(self.config.phone)
                self.code_needed.emit()
            except Exception as e:
                self.error.emit(f"Не удалось запросить код авторизации: {e}")
                return
        else:
            self.connected.emit()
            me = await client.get_me()
            try:
                self._self_id = int(getattr(me, "id", 0) or 0)
                first = getattr(me, "first_name", "") or ""
                last  = getattr(me, "last_name", "") or ""
                uname = getattr(me, "username", "") or ""
                disp = (f"{first} {last}").strip() or uname or ""
                self._self_display = disp or "Я"
            except Exception:
                self._self_id = None
                self._self_display = "Я"
            await self._start_listening()

    async def sign_in_with_code(self, code: str):
        if not self.client:
            return
        try:
            await self.client.sign_in(self.config.phone, code)
            self.config.save()
            self.connected.emit()
            await self._start_listening()
        except SessionPasswordNeededError:
            self.password_needed.emit()
        except Exception as e:
            self.error.emit(f"Код не подошёл: {e}")

    async def sign_in_with_password(self, password: str):
        if not self.client:
            return
        try:
            await self.client.sign_in(password=password)
            self.connected.emit()
            await self._start_listening()
        except Exception as e:
            self.error.emit(f"Пароль не подошёл: {e}")

    async def _start_listening(self):
        if not self.client or self._running:
            return
        self._running = True

        @self.client.on(events.NewMessage)  # type: ignore[attr-defined]
        async def handler(event):
            try:
                msg: Message = event.message  # type: ignore[assignment]
                peer = str(get_peer_id(getattr(msg, "peer_id", None) or getattr(msg, "to_id", None)))
                data = await self._serialize_message(msg)
                self.new_message.emit(peer, data)
            except Exception as e:
                self.error.emit(f"Ошибка при обработке входящего: {e}")

    async def reset_dialogs_pagination(self):
        self._dlg_offset_date = None
        self._dlg_offset_id = 0
        self._dlg_offset_peer = None

    async def load_dialogs(self, limit: int = 20, search: str | None = None):
        await self.reset_dialogs_pagination()
        self._dlg_search = (search or None)
        return await self.load_more_dialogs(limit=limit)

    def _dlg_match(self, d, q: str) -> bool:
        if not q:
            return True
        q = q.lower()
        title = (getattr(d, "name", "") or "").lower()
        if title and q in title:
            return True
        ent = getattr(d, "entity", None)
        uname = (getattr(ent, "username", "") or "").lower() if ent else ""
        return bool(uname and q in uname)

    async def load_more_dialogs(self, limit: int = 20):
        if not self.client:
            return
        try:
            offs = {}
            if self._dlg_offset_peer is not None:
                offs = {
                    "offset_date": self._dlg_offset_date,
                    "offset_id": int(self._dlg_offset_id or 0),
                    "offset_peer": self._dlg_offset_peer,
                }

            dialogs = []
            if self._dlg_search:
                try:
                    n = 0
                    async for d in self.client.iter_dialogs(limit=limit, **offs, search=self._dlg_search):
                        dialogs.append(d)
                        n += 1
                        if n >= limit:
                            break
                except TypeError:
                    n = 0
                    async for d in self.client.iter_dialogs(limit=200, **offs):
                        if self._dlg_match(d, self._dlg_search):
                            dialogs.append(d)
                            n += 1
                            if n >= limit:
                                break
            else:
                dialogs = await self.client.get_dialogs(limit=limit, **offs)

            result = []
            next_offset_peer = None
            next_offset_id = 0
            next_offset_date = None

            for d in dialogs:
                title = getattr(d, "name", None) or "(без названия)"
                ent = getattr(d, "entity", None)
                peer_id = str(get_peer_id(ent)) if ent else ""
                cls_name = ent.__class__.__name__ if ent else ""
                is_user = (cls_name == "User")
                is_channel = (cls_name == "Channel")
                is_group = (cls_name == "Chat") or (is_channel and getattr(ent, "megagroup", False))
                unread = int(getattr(d, "unread_count", 0) or 0)

                result.append((peer_id, title, is_user, is_group, is_channel, unread))

                if ent is not None:
                    self._entities_by_id[peer_id] = ent

                next_offset_peer = ent
                last_msg = getattr(d, "message", None)
                if last_msg is not None:
                    next_offset_id = int(getattr(last_msg, "id", 0)) or 0
                    next_offset_date = getattr(last_msg, "date", None)
                else:
                    next_offset_id = 0
                    next_offset_date = getattr(d, "date", None)

            if result and next_offset_peer is not None:
                self._dlg_offset_peer = next_offset_peer
                self._dlg_offset_id = next_offset_id
                self._dlg_offset_date = next_offset_date

            self.dialogs_loaded.emit(result)
        except Exception as e:
            self.error.emit(f"Не удалось получить чаты: {e}")

    async def load_history(self, peer_id: str, limit: int = 20, before_id: Optional[int] = None):
        if not self.client:
            return
        try:
            entity = self._entities_by_id.get(str(peer_id))
            if entity is None:
                entity = await self.client.get_entity(int(peer_id))

            self.current_peer_id = peer_id

            items = []
            async for msg in self.client.iter_messages(
                entity, limit=limit, offset_id=(before_id or 0)
            ):
                items.append(await self._serialize_message(msg))
            items.reverse()

            self.history_loaded.emit(peer_id, items)
        except Exception as e:
            self.error.emit(f"Не удалось загрузить историю: {e}")

    async def search_messages(self, peer_id: str, query: str, limit: int = 50):
        if not self.client or not query.strip():
            return []
        try:
            entity = self._entities_by_id.get(str(peer_id))
            if entity is None:
                entity = await self.client.get_entity(int(peer_id))
            hits = []
            async for msg in self.client.iter_messages(entity, limit=limit, search=query):
                hits.append(await self._serialize_message(msg))
            hits.sort(key=lambda m: int(m.get("id", 0)))
            return hits
        except Exception as e:
            self.error.emit(f"Поиск сообщений не удался: {e}")
            return []

    async def send_text(self, peer_id: str, text: str):
        if not self.client:
            return
        try:
            entity = await self.client.get_entity(int(peer_id))
            sent_msg = await self.client.send_message(entity, text)
            try:
                data = await self._serialize_message(sent_msg)
                data["peer_id"] = str(peer_id)
                data["out"] = True
                self.new_message.emit(str(peer_id), data)
            except Exception:
                pass
        except Exception as e:
            self.error.emit(f"Не удалось отправить сообщение: {e}")

    async def send_files(self, peer_id: str, paths: list[str], caption: str = ""):
        if not self.client:
            return
        try:
            entity = await self.client.get_entity(int(peer_id))
            for i, p in enumerate(paths):
                if not os.path.isfile(p):
                    raise FileNotFoundError(f"Файл не найден: {p}")
                size = os.path.getsize(p)
                cap = caption if i == 0 else ""
                mime, _ = mimetypes.guess_type(p)
                is_image = (mime or "").startswith("image/")
                ext = os.path.splitext(p)[1].lower()
                if ext in (".tgs", ".webm"):
                    is_image = False
                upload_path = p
                upload_name = os.path.basename(p)
                if size <= 0:
                    try:
                        tmp_dir = _temp_dir()
                        zip_name = upload_name + ".zip"
                        zip_path = os.path.join(tmp_dir, zip_name)
                        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                            zf.writestr(upload_name, b"")
                        upload_path = zip_path
                        upload_name = zip_name
                        is_image = False
                        if not cap:
                            cap = f"(Файл упакован в архив)"
                    except Exception as ee:
                        raise ValueError(f"Файл пустой (0 байт) и не удалось создать ZIP: {ee}")
                uploaded = await self.client.upload_file(
                    upload_path,
                    file_name=upload_name
                )
                sent = await self.client.send_file(
                    entity,
                    uploaded,
                    caption=cap,
                    force_document=not is_image,
                )
                try:
                    data = await self._serialize_message(sent)
                    data["peer_id"] = str(peer_id)
                    data["out"] = True
                    self.new_message.emit(str(peer_id), data)
                except Exception:
                    pass
        except Exception as e:
            self.error.emit(f"Не удалось отправить файл(ы): {e}")

    async def download_media_to(self, msg_id: int, peer_id: str, path: str):
        if not self.client:
            return
        def _ensure_ext(p: str, dot_ext: str) -> str:
            if not dot_ext:
                return p
            root, cur = os.path.splitext(p)
            return p if cur else root + dot_ext
        try:
            entity = await self.client.get_entity(int(peer_id))
            msg = await self.client.get_messages(entity, ids=msg_id)
            dot_ext = ""
            file_name = ""
            mime = ""
            f = getattr(msg, "file", None)
            if f:
                file_name = getattr(f, "name", "") or ""
                dot_ext   = getattr(f, "ext", "") or ""
                mime      = (getattr(f, "mime_type", "") or "").lower()
            if os.path.isdir(path):
                if not file_name:
                    file_name = f"telegram_{msg_id}"
                path = os.path.join(path, file_name)
            if not dot_ext:
                if file_name and "." in file_name:
                    dot_ext = os.path.splitext(file_name)[1]
                if not dot_ext and mime:
                    mime_map = {
                        "image/jpeg": ".jpg",
                        "image/png": ".png",
                        "image/webp": ".webp",
                        "video/mp4": ".mp4",
                        "video/webm": ".webm",
                        "audio/ogg": ".ogg",
                        "audio/mpeg": ".mp3",
                        "application/x-tgsticker": ".tgs",
                        "application/pdf": ".pdf",
                        "text/plain": ".txt",
                        "application/zip": ".zip",
                    }
                    dot_ext = mime_map.get(mime, "")
                if not dot_ext:
                    if getattr(msg, "photo", None):
                        dot_ext = ".jpg"
                    elif getattr(msg, "video", None):
                        dot_ext = ".mp4"
                    elif getattr(msg, "voice", None):
                        dot_ext = ".ogg"
                    elif getattr(msg, "audio", None):
                        dot_ext = ".mp3"
                    elif getattr(msg, "sticker", None):
                        dot_ext = ".webp"
            if dot_ext in (".oga", ".opus"):
                dot_ext = ".ogg"
            path = _ensure_ext(path, dot_ext)
            await self.client.download_media(msg, file=path)
        except Exception as e:
            self.error.emit(f"Не удалось скачать файл: {e}")

    async def shutdown(self):
        try:
            if self.client:
                await self.client.disconnect()
        except Exception:
            pass


class TelegramThread(QThread):
    def __init__(self, worker: TelegramWorker):
        super().__init__()
        self.worker = worker

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.worker.loop = loop
        try:
            loop.run_until_complete(self.worker.connect_and_auth())
            loop.run_forever()
        except Exception:
            traceback.print_exc()
        finally:
            try:
                pending = set(asyncio.all_tasks(loop))  # type: ignore[arg-type]
                for t in pending:
                    t.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:
                pass
            try:
                loop.stop()
            except Exception:
                pass
            loop.close()

    def stop(self):
        if self.worker and self.worker.loop:
            fut = asyncio.run_coroutine_threadsafe(
                self.worker.shutdown(), self.worker.loop
            )
            try:
                fut.result(timeout=5)
            except Exception:
                pass
            self.worker.loop.call_soon_threadsafe(self.worker.loop.stop)


class MessageWidget(QWidget):
    class _ClickableImage(QLabel):
        def __init__(self, pix: QPixmap, msg_id: int):
            super().__init__()
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            self._pix = pix
            self._msg_id = msg_id
            self.setPixmap(pix)
            self.setScaledContents(True)
            self.setMaximumHeight(320)
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip(
                "Ctrl + ЛКМ — открыть изображение в приложении по умолчанию"
            )

        def mousePressEvent(self, ev: QMouseEvent):
            if ev.button() == Qt.LeftButton and (
                QApplication.keyboardModifiers() & Qt.ControlModifier
            ):
                try:
                    out_dir = _temp_dir()
                    out_path = os.path.join(out_dir, f"tg_{self._msg_id}.png")
                    self._pix.save(out_path, "PNG")
                    _open_in_default_app(out_path)
                except Exception as e:
                    QMessageBox.critical(
                        self, "Ошибка", f"Не удалось открыть изображение: {e}"
                    )
            else:
                super().mousePressEvent(ev)

    def __init__(self, msg: dict, download_cb):
        super().__init__()
        self.msg = msg
        self.download_cb = download_cb
        lay = QVBoxLayout(self)
        name = (msg.get("sender_name") or "").strip()
        date = msg.get("date") or ""
        arrow = "→ " if msg.get("out") else "← "
        meta = QHBoxLayout()
        meta.setSpacing(8)
        lbl_arrow = QLabel(arrow)
        lbl_arrow.setStyleSheet("color: gray; font-size: 11px;")
        meta.addWidget(lbl_arrow)
        if name:
            my_name_color   = "#D7A9FF"
            other_name_color= "#5a8"
            name_color = my_name_color if self.msg.get("out") else other_name_color
            lbl_name = QLabel(name)
            lbl_name.setStyleSheet(f"color: {name_color}; font-weight: bold; font-size: 12px;")
            meta.addWidget(lbl_name)
        lbl_date = QLabel(date)
        lbl_date.setStyleSheet("color: gray; font-size: 11px;")
        meta.addWidget(lbl_date)
        meta.addStretch(1)
        lay.addLayout(meta)
        text = msg.get("text") or ""
        if text.strip():
            lbl = QLabel(
                text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            )
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lbl.setWordWrap(True)
            lay.addWidget(lbl)
        if msg.get("has_media"):
            kind = msg.get("media_kind") or ""
            if kind == "photo":
                cached = msg.get("cached_path")
                pix = QPixmap()
                ok = False
                if cached and os.path.isfile(cached):
                    ok = pix.load(cached)
                if not ok and msg.get("photo_bytes"):
                    try:
                        raw = msg.get("photo_bytes")
                        if isinstance(raw, (bytes, bytearray)):
                            ok = pix.loadFromData(raw)
                    except Exception:
                        ok = False
                if not ok or pix.isNull():
                    btn = QPushButton("Загрузить изображение")
                    btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                    btn.setMinimumHeight(36)
                    btn.clicked.connect(lambda: self.download_cb(self.msg))
                    lay.addWidget(btn)
                else:
                    thumb = pix.scaled(240, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    img = self._ClickableImage(pix, int(msg.get("id", 0)))
                    img.setPixmap(thumb)
                    img.setScaledContents(False)
                    img.setMaximumSize(thumb.size())
                    lay.addWidget(img)
            elif kind != "photo":
                cached = msg.get("cached_path")
                if cached and os.path.isfile(cached):
                    btn = QPushButton("Открыть файл")
                    btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                    btn.setMinimumHeight(36)
                    btn.clicked.connect(lambda: _open_in_default_app(cached))
                else:
                    btn = QPushButton("Загрузить файл")
                    btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                    btn.setMinimumHeight(36)
                    btn.clicked.connect(lambda: self.download_cb(self.msg))
                lay.addWidget(btn)


class ChatListItem(QWidget):
    def __init__(self, title: str, unread: int = 0):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 2, 8, 2)
        h.setSpacing(8)
        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet("color: #ddd;")
        h.addWidget(self.lbl_title)
        h.addStretch(1)
        self.badge = QLabel()
        self.badge.setMinimumWidth(24)
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setStyleSheet("""
            border-radius: 10px; padding: 2px 6px;
            background: #8a2be2; color: white; font-weight: bold;
        """)
        h.addWidget(self.badge)
        self.set_unread(unread)

    def set_unread(self, n: int):
        if n and n > 0:
            self.badge.setText(str(n))
            self.badge.show()
        else:
            self.badge.hide()

    def set_title(self, title: str):
        self.lbl_title.setText(title)


class TelegramChatsDialog(QDialog):
    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.setWindowTitle("Telegram чаты (NotesPM)")
        self._history_future = None  # type: Optional[asyncio.Future]
        self.resize(980, 640)
        self._esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self._esc.activated.connect(self._handle_esc)
        self._loading_more = False
        self._suppress_autoscroll = False
        self._pre_scroll = (0, 0)
        root = QHBoxLayout(self)
        self._unread_by_peer: dict[str, int] = {}
        self._chat_widgets: dict[str, ChatListItem] = {}
        self._closing = False
        self._page_size = 20
        self._current_peer_id: Optional[str] = None
        self._append_dialogs = False
        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        self._oldest_id: Optional[int] = None
        self.ed_search_chats = QLineEdit()
        self.ed_search_chats.setPlaceholderText("Поиск чатов...")
        left_col.addWidget(self.ed_search_chats)
        self._search_chats_timer = QTimer(self)
        self._search_chats_timer.setSingleShot(True)
        self._search_chats_timer.setInterval(300)
        self.ed_search_chats.textChanged.connect(lambda: self._search_chats_timer.start())
        self._search_chats_timer.timeout.connect(self._do_search_chats)
        self.list_chats = QListWidget()
        self.list_chats.setMinimumWidth(260)
        left_col.addWidget(self.list_chats)
        self.btn_more_dialogs = QPushButton("Ещё 20 чатов")
        self.btn_more_dialogs.setVisible(False)
        self.btn_more_dialogs.setMinimumHeight(36)
        self.btn_more_dialogs.setFocusPolicy(Qt.NoFocus)
        left_bottom = QHBoxLayout()
        left_bottom.setContentsMargins(0, 0, 0, 0)
        left_bottom.addStretch(1)
        left_bottom.addWidget(self.btn_more_dialogs)
        left_col.addLayout(left_bottom)
        root.addLayout(left_col)
        self.btn_more_dialogs.clicked.connect(self._on_more_dialogs_clicked)
        right = QVBoxLayout()
        root.addLayout(right)
        search_row = QHBoxLayout()
        self.ed_search_msgs = QLineEdit()
        self.ed_search_msgs.setPlaceholderText("Найти в диалоге…")
        self.btn_prev_hit = QPushButton("←")
        self.btn_next_hit = QPushButton("→")
        self.btn_prev_hit.setEnabled(False)
        self.btn_next_hit.setEnabled(False)
        search_row.addWidget(self.ed_search_msgs)
        search_row.addWidget(self.btn_prev_hit)
        search_row.addWidget(self.btn_next_hit)
        right.addLayout(search_row)
        self._msg_hits: list[int] = []
        self._msg_hit_index = -1
        self.ed_search_msgs.returnPressed.connect(self._run_msg_search)
        self.btn_next_hit.clicked.connect(lambda: self._step_msg_hit(+1))
        self.btn_prev_hit.clicked.connect(lambda: self._step_msg_hit(-1))
        self.btn_load_more = QPushButton("Ещё 20 сообщений")
        self.btn_load_more.setVisible(False)
        self.btn_load_more.clicked.connect(self._on_load_more_clicked)
        right.addWidget(self.btn_load_more)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.history_container = QWidget()
        self.history_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.history_layout = QVBoxLayout(self.history_container)
        self.scroll.setWidget(self.history_container)
        self.history_layout.addStretch(1)
        self.scroll.viewport().installEventFilter(self)
        send_row = QHBoxLayout()
        self.btn_attach = QPushButton("📎 Прикрепить")
        self.btn_attach.setFocusPolicy(Qt.NoFocus)
        self.btn_attach.clicked.connect(self._attach_files)
        right.addWidget(self.scroll)
        send_row.addWidget(self.btn_attach)
        self.ed_input = QLineEdit()
        self.ed_input.setPlaceholderText("Написать сообщение…  (Enter — отправить)")
        send_row.addWidget(self.ed_input)
        self.btn_send = QPushButton("Отправить")
        self.btn_send.setDefault(False)
        self.btn_send.setAutoDefault(False)
        self.btn_send.setEnabled(False)
        self.ed_input.setFocus(Qt.TabFocusReason)
        self.ed_input.textEdited.connect(self._on_input_edited)
        self.ed_input.textChanged.connect(self._on_input_edited)
        right.addLayout(send_row)
        self._anchor_id = None
        self._anchor_offset = 0
        self.cfg = TgUserConfig()
        self.cfg.load()
        self.worker = TelegramWorker()
        self.thread = TelegramThread(self.worker)
        self._wire_worker_signals()
        self._need_bottom_after_history = False
        self.btn_attach.setEnabled(False)
        self.list_chats.currentItemChanged.connect(self._on_chat_selected)
        self.btn_send.clicked.connect(self._send_current)
        self.ed_input.returnPressed.connect(self._send_current)
        if _TELETHON_ERR is not None:
            _error_box(
                self,
                "Telethon не установлен",
                "Установи зависимость:\n\n    pip install telethon\n\n"
                f"Техническая ошибка: {repr(_TELETHON_ERR)}",
            )
        else:
            self.thread.start()
        send_row.addWidget(self.btn_send)

    def _wire_worker_signals(self):
        w = self.worker
        w.connected.connect(self._on_connected)
        w.auth_needed.connect(self._on_auth_needed)
        w.code_needed.connect(self._on_code_needed)
        w.password_needed.connect(self._on_password_needed)
        w.dialogs_loaded.connect(self._on_dialogs_loaded)
        w.history_loaded.connect(self._on_history_loaded)
        w.new_message.connect(self._on_new_message)
        w.error.connect(lambda text: _error_box(self, "Ошибка", text))
  
    def _restore_visible_anchor_deferred(self, msg_id: int, offset: int):
        def _apply():
            self.history_container.setUpdatesEnabled(True)
            self._restore_visible_anchor(msg_id, offset)

        QTimer.singleShot(0, _apply)
        QTimer.singleShot(16, _apply)
        QTimer.singleShot(33, _apply)

    def _run_msg_search(self):
        if not self._current_peer_id:
            return
        query = (self.ed_search_msgs.text() or "").strip()
        if not query:
            self._msg_hits = []
            self._msg_hit_index = -1
            self.btn_prev_hit.setEnabled(False)
            self.btn_next_hit.setEnabled(False)
            return
        fut = asyncio.run_coroutine_threadsafe(
            self.worker.search_messages(self._current_peer_id, query, limit=200),
            self.worker.loop
        )
        def _done(f):
            try:
                hits = f.result() or []
            except Exception:
                hits = []
            self._msg_hits = [int(m.get("id", 0)) for m in hits if int(m.get("id", 0)) > 0]
            self._msg_hits = sorted(set(self._msg_hits))
            if not self._msg_hits:
                self._msg_hit_index = -1
                self.btn_prev_hit.setEnabled(False)
                self.btn_next_hit.setEnabled(False)
                return
            target_id = self._msg_hits[0]
            self._msg_hit_index = 0
            self._ensure_message_visible(target_id)
            self.btn_prev_hit.setEnabled(len(self._msg_hits) > 1)
            self.btn_next_hit.setEnabled(len(self._msg_hits) > 1)
        try:
            fut.add_done_callback(_done)
        except Exception:
            pass

    def _step_msg_hit(self, delta: int):
        if not self._msg_hits:
            return
        self._msg_hit_index = (self._msg_hit_index + delta) % len(self._msg_hits)
        target_id = self._msg_hits[self._msg_hit_index]
        self._ensure_message_visible(target_id)

    def _ensure_message_visible(self, target_id: int):
        w = self._find_message_widget_by_id(target_id)
        if w is None:
            def _load_more_until():
                if self._oldest_id is not None and target_id >= self._oldest_id:
                    self._highlight_and_scroll(target_id)
                    return
                if not self.btn_load_more.isVisible() or not self.btn_load_more.isEnabled():
                    self._highlight_and_scroll(target_id)  # не смогли — просто прокрутим к низу
                    return
                self._on_load_more_clicked()
                QTimer.singleShot(150, _load_more_until)
            _load_more_until()
        else:
            self._highlight_and_scroll(target_id)

    def _highlight_and_scroll(self, msg_id: int):
        w = self._find_message_widget_by_id(msg_id)
        if not w:
            self._scroll_to_bottom()
            return
        vsb = self.scroll.verticalScrollBar()
        vsb.setValue(max(0, w.y() - 12))
        old = w.styleSheet()
        w.setStyleSheet(old + "; background-color: rgba(255, 230, 120, 0.25); border-radius: 8px;")
        QTimer.singleShot(1500, lambda: w.setStyleSheet(old))

    def _do_search_chats(self):
        text = (self.ed_search_chats.text() or "").strip()
        self._append_dialogs = False
        asyncio.run_coroutine_threadsafe(
            self.worker.load_dialogs(limit=20, search=text if text else None),
            self.worker.loop
        )

    def _handle_esc(self):
        if self._current_peer_id:
            self._leave_current_chat()
        else:
            self.close()

    def _find_message_widget_by_id(self, msg_id: int):
        lay = self.history_layout
        for i in range(max(0, lay.count() - 1)):
            item = lay.itemAt(i)
            w = item.widget()
            if w and hasattr(w, "msg") and int(w.msg.get("id", -1)) == int(msg_id):
                return w
        return None
    
    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            if self._current_peer_id:
                self._leave_current_chat()
            else:
                self.close()
            ev.accept()
            return
        return super().keyPressEvent(ev)
  
    def eventFilter(self, obj, ev):
        if obj is self.scroll.viewport() and ev.type() == QEvent.Resize:
            self.history_container.setMinimumWidth(self.scroll.viewport().width())
        return super().eventFilter(obj, ev)

    def _get_visible_anchor(self):
        vsb = self.scroll.verticalScrollBar()
        y_view = vsb.value()
        lay = self.history_layout
        for i in range(max(0, lay.count() - 1)):
            item = lay.itemAt(i)
            w = item.widget()
            if not w or not hasattr(w, "msg"):
                continue
            wy = w.y()
            h  = w.height()
            if wy + h >= y_view:
                offset = y_view - wy
                offset = max(0, offset)
                return (int(w.msg.get("id", 0)), offset)
        return (None, 0)

    def _restore_visible_anchor(self, msg_id: int, offset: int):
        if msg_id is None:
            return
        w = self._find_message_widget_by_id(msg_id)
        if not w:
            return
        vsb = self.scroll.verticalScrollBar()
        target = w.y() + max(0, int(offset))
        vsb.setValue(max(0, target))

    def _on_input_edited(self, text: str):
        txt = text if isinstance(text, str) else self.ed_input.text()
        has_text = bool(txt.strip())
        self.btn_send.setEnabled(has_text)
        if self.focusWidget() is not self.ed_input:
            self.ed_input.setFocus(Qt.TabFocusReason)

    def _on_load_more_clicked(self):
        if not self._current_peer_id:
            return
        vsb = self.scroll.verticalScrollBar()
        self._pre_scroll = (vsb.value(), vsb.maximum())
        self._loading_more = True
        self._suppress_autoscroll = True
        if self._oldest_id is None:
            return
        self._anchor_id, self._anchor_offset = self._get_visible_anchor()
        self.history_container.setUpdatesEnabled(False)
        self.btn_load_more.setEnabled(False)
        if self._history_future and not self._history_future.done():
            self._history_future.cancel()
        self._history_future = asyncio.run_coroutine_threadsafe(
            self.worker.load_history(
                self._current_peer_id, limit=self._page_size, before_id=self._oldest_id
            ),
            self.worker.loop,
        )

    def _on_auth_needed(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Настройка Telegram авторизации")
        v = QVBoxLayout(dlg)
        lab = QLabel(
            "Введи api_id, api_hash и номер телефона (в международном формате).\n"
            "api_id/api_hash берутся на https://my.telegram.org"
        )
        lab.setWordWrap(True)
        v.addWidget(lab)

        from PySide6.QtWidgets import QFormLayout, QDialogButtonBox

        form = QFormLayout()
        ed_id = QLineEdit(str(self.cfg.api_id or ""))
        ed_hash = QLineEdit(self.cfg.api_hash or "")
        ed_phone = QLineEdit(self.cfg.phone or "")
        form.addRow("api_id:", ed_id)
        form.addRow("api_hash:", ed_hash)
        form.addRow("Телефон:", ed_phone)
        v.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        v.addWidget(btns)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)

        if dlg.exec() != QDialog.Accepted:
            return
        try:
            self.cfg.api_id = int(ed_id.text().strip())
        except Exception:
            self.cfg.api_id = None
        self.cfg.api_hash = ed_hash.text().strip()
        self.cfg.phone = ed_phone.text().strip()
        self.cfg.save()
        self.worker.config.api_id = self.cfg.api_id
        self.worker.config.api_hash = self.cfg.api_hash
        self.worker.config.phone = self.cfg.phone
        asyncio.run_coroutine_threadsafe(
            self.worker.connect_and_auth(), self.worker.loop
        )

    def _on_code_needed(self):
        from PySide6.QtWidgets import QInputDialog

        code, ok = QInputDialog.getText(self, "Код подтверждения", "Код из Telegram:")
        if not ok or not code:
            return
        asyncio.run_coroutine_threadsafe(
            self.worker.sign_in_with_code(code.strip()), self.worker.loop
        )

    def _on_password_needed(self):
        from PySide6.QtWidgets import QInputDialog

        pwd, ok = QInputDialog.getText(
            self, "Пароль 2FA", "Пароль:", echo=QLineEdit.Password
        )
        if not ok or not pwd:
            return
        asyncio.run_coroutine_threadsafe(
            self.worker.sign_in_with_password(pwd), self.worker.loop
        )

    def _on_connected(self):
        self._append_dialogs = False
        asyncio.run_coroutine_threadsafe(self.worker.load_dialogs(limit=20), self.worker.loop)

    def _on_dialogs_loaded(self, rows: list):
        if not self._append_dialogs:
            self.list_chats.clear()
            self._chat_widgets.clear()
            self._unread_by_peer.clear()

        for row in rows:
            if len(row) >= 6:
                peer_id, title, is_user, is_group, is_channel, unread = row
            else:
                peer_id, title, is_user, is_group, is_channel = row
                unread = 0
            item = QListWidgetItem()
            item.setData(Qt.UserRole, peer_id)
            widget = ChatListItem(title, unread)
            self._chat_widgets[str(peer_id)] = widget
            self._unread_by_peer[str(peer_id)] = int(unread or 0)
            self.list_chats.addItem(item)
            self.list_chats.setItemWidget(item, widget)
        if not self._append_dialogs:
            self.list_chats.clearSelection()
            self.list_chats.setCurrentRow(-1)
            self._current_peer_id = None
            self._oldest_id = None
            self._clear_history()
            self.btn_attach.setEnabled(False)
            self.btn_send.setEnabled(False)
            self.btn_load_more.setVisible(False)
            self.btn_load_more.setEnabled(False)
        if len(rows) < 20:
            self.btn_more_dialogs.setVisible(False)
            self.btn_more_dialogs.setEnabled(False)
        else:
            self.btn_more_dialogs.setVisible(True)
            self.btn_more_dialogs.setEnabled(True)
        self._append_dialogs = False

    def _on_more_dialogs_clicked(self):
        self.btn_more_dialogs.setEnabled(False)
        self._append_dialogs = True
        asyncio.run_coroutine_threadsafe(self.worker.load_more_dialogs(limit=20), self.worker.loop)
        self.ed_input.setFocus(Qt.TabFocusReason)

    def _on_chat_selected(self, cur: QListWidgetItem, prev: QListWidgetItem):
        if not cur:
            return
        self.btn_attach.setEnabled(True)
        peer_id = cur.data(Qt.UserRole)
        self._current_peer_id = str(peer_id)
        self._oldest_id = None
        self._clear_history()
        self.ed_search_msgs.clear()
        self._msg_hits = []
        self._msg_hit_index = -1
        self.btn_prev_hit.setEnabled(False)
        self.btn_next_hit.setEnabled(False)
        self._need_bottom_after_history = True
        if self._history_future and not self._history_future.done():
            self._history_future.cancel()
        self.btn_load_more.setVisible(True)
        self.btn_load_more.setEnabled(False)
        self._history_future = asyncio.run_coroutine_threadsafe(
            self.worker.load_history(
                self._current_peer_id, limit=self._page_size, before_id=None
            ),
            self.worker.loop,
        )

    def _clear_history(self):
        lay = self.history_layout
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        lay.addStretch(1)

    def _leave_current_chat(self):
        self._current_peer_id = None
        self._oldest_id = None
        self._clear_history()
        self.btn_load_more.setVisible(False)
        self.btn_load_more.setEnabled(False)
        self.btn_attach.setEnabled(False)
        self.btn_send.setEnabled(False)
        self.ed_input.clear()
        self.list_chats.clearSelection()
        self.list_chats.setCurrentRow(-1)
        self.list_chats.setFocus(Qt.TabFocusReason)

    def _insert_msg_sorted(self, msg: dict):
        target_id = int(msg.get("id", 0))
        w = MessageWidget(msg, self._download_media)
        lay = self.history_layout
        insert_at = max(0, lay.count() - 1)
        for i in range(max(0, lay.count() - 1)):
            item = lay.itemAt(i)
            ex = item.widget()
            if ex and hasattr(ex, "msg"):
                ex_id = int(ex.msg.get("id", 0))
                if ex_id > target_id:
                    insert_at = i
                    break
        lay.insertWidget(insert_at, w)
        if not self._suppress_autoscroll:
            self._scroll_to_bottom()

    def _append_msg(self, msg: dict):
        self._insert_msg_sorted(msg)

    def _on_new_message(self, peer_id: str, msg: dict):
        if self._closing:
            return
        if not bool(msg.get("out")):
            pid = str(peer_id)
            self._unread_by_peer[pid] = int(self._unread_by_peer.get(pid, 0)) + 1
            w = self._chat_widgets.get(pid)
            if w:
                w.set_unread(self._unread_by_peer[pid])
        cur_item = self.list_chats.currentItem()
        if not cur_item:
            return
        cur_peer = cur_item.data(Qt.UserRole)
        if str(cur_peer) == str(peer_id):
            self._append_msg(msg)
            self._scroll_to_bottom()

    def _on_history_loaded(self, peer_id: str, items: list):
        if not items:
            self.btn_load_more.setEnabled(False)
            self.btn_load_more.setVisible(False)
            return
        items.sort(key=lambda m: (int(m.get("id", 0)), int(m.get("ts", 0))))
        for msg in items:
            self._insert_msg_sorted(msg)
        batch_min = min(int(m.get("id", 0)) for m in items)
        if self._oldest_id is None or batch_min < self._oldest_id:
            self._oldest_id = batch_min
        if len(items) < self._page_size:
            self.btn_load_more.setEnabled(False)
            self.btn_load_more.setVisible(False)
        else:
            self.btn_load_more.setEnabled(True)
            self.btn_load_more.setVisible(True)
        if self._loading_more:
            self._restore_visible_anchor_deferred(self._anchor_id, self._anchor_offset)
            self._loading_more = False
            self._suppress_autoscroll = False
            self._anchor_id = None
            self._anchor_offset = 0
            return
        self._scroll_to_bottom()
        if self._need_bottom_after_history:
            self._need_bottom_after_history = False
            self._scroll_to_bottom()

    def _send_current(self):
        text = self.ed_input.text().strip()
        if not text:
            return
        cur = self.list_chats.currentItem()
        if not cur:
            return
        peer_id = cur.data(Qt.UserRole)
        self.ed_input.clear()
        self.btn_send.setEnabled(False)
        self.ed_input.setFocus(Qt.TabFocusReason)
        asyncio.run_coroutine_threadsafe(
            self.worker.send_text(peer_id, text), self.worker.loop
        )

    def _attach_files(self):
        cur = self.list_chats.currentItem()
        if not cur:
            return
        peer_id = cur.data(Qt.UserRole)
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Выбрать файл(ы) для отправки",
            "",
            "Все файлы (*.*)"
        )
        if not paths:
            return
        caption = (self.ed_input.text() or "").strip()
        self.btn_attach.setEnabled(False)
        self.btn_send.setEnabled(False)

        def _done(_):
            self.btn_attach.setEnabled(True)
            self._on_input_edited(self.ed_input.text())
        fut = asyncio.run_coroutine_threadsafe(
            self.worker.send_files(str(peer_id), paths, caption),
            self.worker.loop,
        )
        if caption:
            self.ed_input.clear()
        try:
            fut.add_done_callback(_done)
        except Exception:
            _done(None)

    def closeEvent(self, e):
        self._closing = True
        try:
            if self._history_future and not self._history_future.done():
                self._history_future.cancel()
        except Exception:
            pass
        try:
            if self.thread and self.thread.isRunning():
                self.thread.stop()
                self.thread.wait(3000)
        except Exception:
            pass
        try:
            cache_root = os.path.join(_data_dir(), "TelegramCache")
            if os.path.isdir(cache_root):
                shutil.rmtree(cache_root, ignore_errors=True)
        except Exception:
            pass
        return super().closeEvent(e)

    def _suggest_filename(self, msg: dict) -> tuple[str, str]:
        orig = (msg.get("file_name") or "").strip()
        ext  = (msg.get("file_ext")  or "").strip().lstrip(".")
        mime = (msg.get("mime_type") or "").lower()
        if orig:
            return orig, (orig.split(".")[-1] if "." in orig else ext)
        mime_map = {
            "image/jpeg": "jpg",
            "image/webp": "webp",
            "image/png": "png",
            "video/mp4": "mp4",
            "video/webm": "webm",
            "audio/ogg": "ogg",
            "audio/mpeg": "mp3",
            "application/x-tgsticker": "tgs",
            "application/octet-stream": "",
            "application/pdf": "pdf",
            "text/plain": "txt",
            "application/zip": "zip",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        }
        mime_ext = mime_map.get(mime, "")
        kind = (msg.get("media_kind") or "").lower()
        kind_map = {
            "photo": "jpg",
            "video": "mp4",
            "audio": "mp3",
            "voice": "ogg",
            "sticker": "webp",
            "document": "",
        }
        kind_ext = kind_map.get(kind, "")
        use_ext = ext or mime_ext or kind_ext
        mid = int(msg.get("id", 0))
        name = f"tg_{mid}" + (f".{use_ext}" if use_ext else "")
        return name, use_ext

    def _download_media(self, msg: dict):
        peer_id = msg.get("peer_id")
        msg_id = msg.get("id")
        if not peer_id or not msg_id:
            return
        default_name, _ = self._suggest_filename(msg)
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить файл", default_name, "Все файлы (*.*)"
        )
        if not path:
            return
        asyncio.run_coroutine_threadsafe(
            self.worker.download_media_to(int(msg_id), str(peer_id), path),
            self.worker.loop,
        )


    def _scroll_to_bottom(self):
        if self._closing or not self.isVisible():
            return

        def _do():
            if self._closing or not self.isVisible():
                return
            vsb = self.scroll.verticalScrollBar()
            vsb.setValue(vsb.maximum())

        QTimer.singleShot(0, _do)
        QTimer.singleShot(50, _do)


_action = None
_installed = False


def on_enable(parent):
    global _action, _installed
    if _installed:
        return
    try:
        mbar = parent.menuBar()
        plugins_menu = None
        for menu in mbar.children():
            try:
                if menu.title() == "Плагины":
                    plugins_menu = menu
                    break
            except Exception:
                continue
        if plugins_menu is None:
            plugins_menu = mbar.addMenu("Плагины")

        _action = QAction("Telegram чаты", parent)
        _action.triggered.connect(lambda: TelegramChatsDialog(parent).exec())
        plugins_menu.addAction(_action)
        _installed = True
    except Exception as e:
        print("Ошибка включения плагина telegram_chats:", e)
        traceback.print_exc()


def on_disable(parent):
    global _action, _installed
    try:
        if _action is not None:
            for menu in parent.menuBar().children():
                try:
                    if getattr(menu, "title", None) and menu.title() == "Плагины":
                        try:
                            menu.removeAction(_action)
                        except Exception:
                            pass
                        break
                except Exception:
                    continue
            _action.deleteLater()
            _action = None
    except Exception:
        pass
    _installed = False
