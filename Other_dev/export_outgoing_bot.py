import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from dateutil import tz
from pathlib import Path
from PyQt6.QtGui import QIcon
from dateutil.parser import isoparse
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import User, Chat, Channel
from telethon.errors.rpcerrorlist import ChatForwardsRestrictedError
try:
    from telethon.tl.types import InputMessagesFilterFromMe
    FROM_ME_FILTER = InputMessagesFilterFromMe()
except Exception:
    FROM_ME_FILTER = None
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass
from PyQt6.QtCore import Qt, QDateTime, QDate, QTime, QProcess
from PyQt6.QtWidgets import (
QApplication, QWidget, QVBoxLayout, QFormLayout, QLineEdit, QDateTimeEdit, QComboBox, QPushButton, QTextEdit, QHBoxLayout, QLabel, QFileDialog,
QMessageBox, QCheckBox, QInputDialog, QMenuBar)
from PyQt6.QtGui import QTextCursor, QKeySequence, QAction, QShortcut, QIcon
from qasync import QEventLoop

APP_TZ_NAME = os.getenv("APP_TZ", "Europe/Amsterdam")
APP_TZ = tz.gettz(APP_TZ_NAME)
DATE_FROM = "2025-09-01T00:00:00"
DATE_TO   = "2025-10-01T00:00:00"
DEFAULT_DESTINATION = os.getenv("TG_DEST", "@npostnov_notesbot")

@dataclass
class Settings:
    api_id: int
    api_hash: str
    dest: str
    mode: str
    date_from: datetime
    date_to: datetime
    include_service: bool = False
    include_forwards: bool = True

def parse_iso_local(s: str) -> datetime:
    dt = isoparse(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=APP_TZ)
    return dt.astimezone(tz.UTC)

def as_local(dt_utc: datetime) -> datetime:
    return dt_utc.astimezone(APP_TZ)

class LogView(QTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setMinimumHeight(220)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)

    def log(self, text: str):
        self.append(text)
        self.moveCursor(QTextCursor.MoveOperation.End)

def classify_entity(e) -> str:
    if isinstance(e, User):
        return "dm"
    if isinstance(e, Chat):
        return "group"
    if isinstance(e, Channel):
        if getattr(e, "megagroup", False):
            return "megagroup"
        if getattr(e, "broadcast", False):
            return "broadcast"
        return "channel"
    return "other"

def origin_full(entity) -> str:
    if isinstance(entity, User):
        uname = f"@{entity.username}" if getattr(entity, "username", None) else None
        name = " ".join(filter(None, [getattr(entity, "first_name", None), getattr(entity, "last_name", None)])).strip()
        who = uname or (name if name else str(getattr(entity, "id", "?")))
        return f"ЛС с {who}"
    if isinstance(entity, Chat):
        return f"Группа: {getattr(entity, 'title', 'Без названия')}"
    if isinstance(entity, Channel) and getattr(entity, "megagroup", False):
        return f"Группа: {getattr(entity, 'title', 'Без названия')}"
    title = getattr(entity, "title", None) or getattr(entity, "username", None) or str(getattr(entity, "id", "?"))
    return f"Диалог: {title}"

def origin_short(entity) -> str:
    if isinstance(entity, User):
        if getattr(entity, "username", None):
            return f"@{entity.username}"
        name = " ".join(filter(None, [getattr(entity, "first_name", None), getattr(entity, "last_name", None)])).strip()
        return name or str(getattr(entity, "id", "?"))
    if isinstance(entity, (Chat, Channel)):
        return getattr(entity, "title", None) or str(getattr(entity, "id", "?"))
    return str(getattr(entity, "id", "?"))

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Telegram Outgoing Reporter (Telethon + Qt)")
        self.setMinimumWidth(680)
        self.client: Optional[TelegramClient] = None
        self.task: Optional[asyncio.Task] = None
        self.cancelled = False
        self.api_id_edit = QLineEdit("29056943")
        self.api_hash_edit = QLineEdit("ebe5243bf0f216d18362df7c67476992")
        self.api_hash_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.dest_edit = QLineEdit(DEFAULT_DESTINATION)
        self.mode_box = QComboBox()
        self.mode_box.addItems(["Переслать", "Копия"])
        self.service_chk = QCheckBox("Включать сервисные сообщения (join/leave/pinned)")
        self.service_chk.setChecked(False)
        self.fwd_chk = QCheckBox("Оставлять пересланные (fwd_from)")
        self.fwd_chk.setChecked(True)
        self.from_dt = QDateTimeEdit()
        self.from_dt.setCalendarPopup(True)
        self.from_dt.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.to_dt = QDateTimeEdit()
        self.to_dt.setCalendarPopup(True)
        self.to_dt.setDisplayFormat("yyyy-MM-dd HH:mm")
        now_app = datetime.now(APP_TZ)
        today_app = now_app.date()
        tomorrow_app = today_app + timedelta(days=1)
        from_default = QDateTime(QDate(today_app.year, today_app.month, today_app.day), QTime(0, 0))
        to_default   = QDateTime(QDate(tomorrow_app.year, tomorrow_app.month, tomorrow_app.day), QTime(1, 59))
        self.from_dt.setDateTime(from_default)
        self.to_dt.setDateTime(to_default)
        self.save_btn = QPushButton("Сохранить настройки в .env…")
        self.run_btn = QPushButton("Старт")
        self.stop_btn = QPushButton("Стоп")
        self.stop_btn.setEnabled(False)
        self.stats_lbl = QLabel("Готово.")
        self.log = LogView()
        self.tz_lbl = QLabel(f"Текущая зона: {APP_TZ_NAME}")
        self.tz_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        form = QFormLayout()
        form.addRow("API ID:", self.api_id_edit)
        form.addRow("API Hash:", self.api_hash_edit)
        form.addRow("Куда слать отчёт:", self.dest_edit)
        form.addRow("Режим:", self.mode_box)
        form.addRow(self.service_chk)
        form.addRow(self.fwd_chk)
        form.addRow("С (локальное время):", self.from_dt)
        form.addRow("По (локальное время):", self.to_dt)
        self.login_btn = QPushButton("Войти в Telegram")
        btns = QHBoxLayout()
        btns.addWidget(self.save_btn)
        btns.addWidget(self.login_btn)
        btns.addStretch(1)
        btns.addWidget(self.run_btn)
        btns.addWidget(self.stop_btn)
        root = QVBoxLayout(self)
        self._install_apps_menu(root)
        root.addLayout(form)
        root.addLayout(btns)
        root.addWidget(self.stats_lbl)
        root.addWidget(self.log)
        root.addWidget(self.tz_lbl)
        self.run_btn.clicked.connect(self.on_start)
        self.stop_btn.clicked.connect(self.on_stop)
        self.save_btn.clicked.connect(self.on_save_env)
        self.login_btn.clicked.connect(self.on_login_clicked)

    def _install_apps_menu(self, root_layout: QVBoxLayout):
        self.menu_bar = QMenuBar(self)
        apps_menu = self.menu_bar.addMenu("Приложения")
        act = QAction("Выбрать приложение…  (Ctrl+Alt+L)", self)
        act.triggered.connect(self.show_app_launcher)
        apps_menu.addAction(act)
        root_layout.setMenuBar(self.menu_bar)
        sc = QShortcut(QKeySequence("Ctrl+Alt+L"), self)
        sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc.activated.connect(self.show_app_launcher)

    def show_app_launcher(self):
        import os, sys
        candidates = ["NotesPM.exe", "launcher.exe", "launcher.py", "launcher.pyw"]
        search_dirs = [os.path.dirname(sys.argv[0]), os.getcwd(), os.path.dirname(__file__)]
        for d in filter(None, map(os.path.abspath, search_dirs)):
            for name in candidates:
                path = os.path.join(d, name)
                if os.path.isfile(path):
                    if path.lower().endswith((".py", ".pyw")):
                        ok = QProcess.startDetached(sys.executable, [path])
                    else:
                        ok = QProcess.startDetached(path, [])
                    if not ok:
                        QMessageBox.warning(self, "Приложения", "Не удалось запустить Launcher.")
                    return
        QMessageBox.warning(self, "Приложения", "Файл Launcher не найден.")

    def get_settings(self) -> Optional[Settings]:
        try:
            api_id = int(self.api_id_edit.text().strip())
        except ValueError:
            QMessageBox.critical(self, "Ошибка", "API ID должен быть числом.")
            return None
        api_hash = self.api_hash_edit.text().strip()
        if not api_hash:
            QMessageBox.critical(self, "Ошибка", "API Hash не заполнен.")
            return None
        dest = self.dest_edit.text().strip() or "@npostnov_notesbot"
        mode = self.mode_box.currentText()
        qf = self.from_dt.dateTime().toPyDateTime()
        qt = self.to_dt.dateTime().toPyDateTime()
        df = datetime(qf.year, qf.month, qf.day, qf.hour, qf.minute, qf.second, tzinfo=APP_TZ).astimezone(tz.UTC)
        dt = datetime(qt.year, qt.month, qt.day, qt.hour, qt.minute, qt.second, tzinfo=APP_TZ).astimezone(tz.UTC)
        if dt <= df:
            QMessageBox.critical(self, "Ошибка", "Дата 'По' должна быть больше, чем 'С'.")
            return None
        return Settings(
            api_id=api_id,
            api_hash=api_hash,
            dest=dest,
            mode=mode,
            date_from=df,
            date_to=dt,
            include_service=self.service_chk.isChecked(),
            include_forwards=self.fwd_chk.isChecked(),
        )
    
    async def resolve_dest_peer(self, client: TelegramClient, dest: str):
        d = (dest or "").strip()
        if not d:
            return "me"

        if d.lower() in {"me", "saved", "saved messages"}:
            return "me"

        if d.startswith("http://") or d.startswith("https://") or d.startswith("t.me/") or d.startswith("https://t.me/"):
            try:
                return await client.get_entity(d)
            except Exception as e:
                self.log.log(f"💥 Не удалось распознать ссылку {d!r}: {e!r}")
                return None

        if d.startswith("@"):
            d = d[1:]

        if d.isdigit():
            try:
                return int(d)
            except Exception:
                pass

        try:
            return await client.get_entity(d)
        except Exception as e:
            self.log.log(f"💥 Не удалось найти пользователя/чат по имени {d!r}: {e!r}")
            return None

    def on_save_env(self):
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить .env", ".env", "Env files (*.env);;All files (*.*)")
        if not path:
            return
        text = (
            f"TG_API_ID={self.api_id_edit.text().strip()}\n"
            f"TG_API_HASH={self.api_hash_edit.text().strip()}\n"
            f"TG_DEST={self.dest_edit.text().strip() or '@npostnov_notesbot'}\n"
            f"APP_TZ={APP_TZ_NAME}\n"
        )
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            QMessageBox.information(self, "Готово", f".env сохранён: {path}")
        except Exception as e:
            self.log.log(f"💥 Ошибка: {e!r}")

    async def ensure_login(self, client: TelegramClient) -> bool:
        if await client.is_user_authorized():
            self.log.log("🔐 Сессия уже авторизована.")
            return True
        ok, phone = await self.ask_text("Авторизация", "Введи номер телефона (в формате +7999...):")
        if not ok or not phone:
            self.log.log("Отмена авторизации (нет телефона).")
            return False

        try:
            await client.send_code_request(phone)
            self.log.log("Код отправлен. Проверь Telegram/СМС.")
            await asyncio.sleep(0)
        except Exception as e:
            self.log.log(f"💥 Ошибка отправки кода: {e!r}")
            return False
        ok, code = await self.ask_text("Авторизация", "Введи код из Telegram/СМС:")
        if not ok or not code:
            self.log.log("Отмена авторизации (нет кода).")
            return False
        try:
            await client.sign_in(phone=phone, code=code)
            await asyncio.sleep(0)
            self.log.log("✅ Авторизация выполнена.")
            return True
        except SessionPasswordNeededError:
            ok, pwd = await self.ask_text("Двухфакторная защита", "Введи пароль:", password=True)
            if not ok or not pwd:
                self.log.log("Отмена авторизации (нет пароля 2FA).")
                return False
            try:
                await client.sign_in(password=pwd)
                await asyncio.sleep(0)
                self.log.log("✅ Авторизация (2FA) выполнена.")
                return True
            except Exception as e:
                self.log.log(f"💥 Ошибка отправки кода: {e!r}")
                return False
        except Exception as e:
            self.log.log(f"💥 Ошибка отправки кода: {e!r}")
            return False
        
    def _ask_text_dialog(self, title: str, label: str, password: bool = False):
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[tuple[bool, str]] = loop.create_future()
        dlg = QInputDialog(self)
        dlg.setWindowTitle(title)
        dlg.setLabelText(label)
        if password:
            dlg.setTextEchoMode(QLineEdit.EchoMode.Password)

        def on_accept():
            if not fut.done():
                fut.set_result((True, dlg.textValue()))
            dlg.deleteLater()

        def on_reject():
            if not fut.done():
                fut.set_result((False, ""))
            dlg.deleteLater()

        dlg.accepted.connect(on_accept)
        dlg.rejected.connect(on_reject)
        dlg.open()
        return dlg, fut

    async def ask_text(self, title: str, label: str, password: bool = False) -> tuple[bool, str]:
        dlg, fut = self._ask_text_dialog(title, label, password=password)
        try:
            ok, text = await fut
            return ok, text
        finally:
            await asyncio.sleep(0)
        
    def on_login_clicked(self):
        settings = self.get_settings()
        if not settings:
            return
        loop = asyncio.get_running_loop()
        loop.create_task(self._login_flow(settings))

    async def _login_flow(self, settings):
        client = TelegramClient(
            "user_session",
            settings.api_id, settings.api_hash,
            device_model="Report",
            app_version="Report 1.0",
            system_version="ReportOS"
        )
        try:
            await client.connect()
            if await self.ensure_login(client):
                me = await client.get_me()
                QMessageBox.information(self, "Готово", f"Вошли как: {me.username or me.id}")
        except Exception as e:
            self.log.log(f"💥 Ошибка: {e!r}")
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    def on_start(self):
        if self.task and not self.task.done():
            QMessageBox.information(self, "Идёт работа", "Уже выполняется.")
            return
        settings = self.get_settings()
        if not settings:
            return
        self.cancelled = False
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.log.clear()
        self.stats_lbl.setText("Подключаюсь…")
        loop = asyncio.get_running_loop()
        self.task = loop.create_task(self.run_export(settings))

    async def run_export(self, settings: Settings):
        total = 0
        client = TelegramClient(
            "user_session",
            settings.api_id, settings.api_hash,
            device_model="Report",
            app_version="Report 1.0",
            system_version="ReportOS"
        )
        try:
            self.log.log("📦 Сессия: user_session")
            await client.connect()
            if not await self.ensure_login(client):
                self.log.log("❌ Не удалось авторизоваться.")
                return
            me = await client.get_me()
            self_id = me.id
            self.log.log(f"✅ Вошли как: {getattr(me, 'username', None) or me.id}")
            dest_peer = await self.resolve_dest_peer(client, settings.dest)
            if not dest_peer:
                self.log.log("❌ Адрес доставки не распознан. Поставь 'me' или корректный @username/ссылку/ID.")
                return
            header = (
                f"📤 Отчёт по ИСХОДЯЩИМ за период\n"
                f"с {as_local(settings.date_from):%Y-%m-%d %H:%M} "
                f"по {as_local(settings.date_to):%Y-%m-%d %H:%M} ({APP_TZ_NAME})"
            )
            await client.send_message(dest_peer, header)
            self.log.log(f"➡️ Отправил шапку в: {settings.dest!r}")
            dialogs = await client.get_dialogs(limit=None)
            self.log.log(f"Найдено диалогов: {len(dialogs)}")
            mode_key = "forward" if ("пересл" in settings.mode.lower() or settings.mode.lower() == "forward") else "copy"
            effective_to = settings.date_to + timedelta(minutes=1)
            for i, dlg in enumerate(dialogs, 1):
                if self.cancelled:
                    self.log.log("⛔ Остановлено пользователем.")
                    break
                entity = dlg.entity
                if not entity:
                    continue
                etype = classify_entity(entity)
                if etype in ("broadcast", "channel"):
                    continue
                title = (
                    getattr(entity, "title", None)
                    or getattr(entity, "username", None)
                    or str(getattr(entity, "id", "?"))
                )
                src_full = origin_full(entity)
                src_short = origin_short(entity)
                sent_header = False
                self.stats_lbl.setText(f"Обработка: {title} ({i}/{len(dialogs)})")
                await asyncio.sleep(0)
                iter_kwargs = dict(
                    offset_date=effective_to,
                    reverse=False
                )
                if FROM_ME_FILTER is not None:
                    iter_kwargs["filter"] = FROM_ME_FILTER
                else:
                    iter_kwargs["from_user"] = self_id
                async for msg in client.iter_messages(entity, **iter_kwargs):
                    if self.cancelled:
                        break
                    if not getattr(msg, "date", None):
                        continue
                    if msg.date < settings.date_from:
                        break
                    if not getattr(msg, "out", False):
                        continue
                    if not settings.include_forwards and getattr(msg, "fwd_from", None):
                        continue
                    if not settings.include_service and getattr(msg, "action", None):
                        continue
                    try:
                        if not sent_header:
                            await client.send_message(dest_peer, f"🧭 Источник: {src_full}")
                            sent_header = True

                        if mode_key == "forward":
                            # Текст ботам — копией с префиксом, всё остальное — форвардом
                            if isinstance(settings.dest, str) and settings.dest.lower().endswith("_bot") and not msg.media:
                                text = msg.text or " "
                                await client.send_message(dest_peer, f"〔{src_short}〕 {text}")
                            else:
                                await client.forward_messages(dest_peer, msg, from_peer=entity)
                        else:
                            # Режим «Копия»: тексты — копией с префиксом, медиа — форвардом (быстро и без скачивания)
                            if msg.media:
                                await client.forward_messages(dest_peer, msg, from_peer=entity)
                            else:
                                text = msg.text or " "
                                await client.send_message(dest_peer, f"〔{src_short}〕 {text}")
                        total += 1
                    except ChatForwardsRestrictedError:
                        if msg.media:
                            self.log.log("⛔ Группа с защитой контента: медиа нельзя переслать, пропущено.")
                        else:
                            text = msg.text or " "
                            if not sent_header:
                                await client.send_message(dest_peer, f"🧭 Источник: {src_full}")
                                sent_header = True
                            await client.send_message(dest_peer, f"〔{src_short}〕 {text}")
                            total += 1
                    except Exception as e:
                        self.log.log(f"⚠️ Ошибка при отправке: {e!r}")
                        await asyncio.sleep(0)
            await client.send_message(dest_peer, f"✅ Готово. Переслано исходящих: {total}")
            self.log.log(f"✅ Готово. Переслано: {total}")
        except Exception as e:
            self.log.log(f"💥 Ошибка: {e!r}")
        finally:
            self.stats_lbl.setText(f"Завершено. Итого: {total}")
            self.run_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            try:
                await client.disconnect()
            except Exception:
                pass

    def on_stop(self):
        self.cancelled = True
        self.stop_btn.setEnabled(False)
        self.stats_lbl.setText("Остановка…")
        self.log.log("Запрошена остановка…")

def main():
    app = QApplication(sys.argv)
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent
    icon_path = base / "icon.ico"
    app.setWindowIcon(QIcon(str(icon_path)))
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    win = MainWindow()
    win.setWindowIcon(QIcon(str(icon_path)))
    win.show()

    with loop:
        loop.run_forever()

if __name__ == "__main__":
    main()