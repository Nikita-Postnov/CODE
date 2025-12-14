import imaplib
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import base64
import re


def ensure_required_files():
    if not os.path.exists("mailsettings.json"):
        with open("mailsettings.json", "w", encoding="utf-8") as f:
            f.write("{}")
    if not os.path.exists("accounts.csv"):
        with open("accounts.csv", "w", encoding="utf-8") as f:
            f.write("#логин:пароль\n")
    if not os.path.exists("imap_hosts.csv"):
        with open("imap_hosts.csv", "w", encoding="utf-8") as f:
            f.write("#host:port\n")
            f.write("imap.yandex.ru:993\n")
            f.write("mail.klvrt.ru:993\n")
            f.write("siderus.ru:993\n")

def to_imap_date(date_str: str) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{dt.day:02d}-{months[dt.month - 1]}-{dt.year}"

def connect_imap(host: str, port: int, username: str, password: str, timeout: float = 30.0) -> imaplib.IMAP4_SSL:
    mail = imaplib.IMAP4_SSL(host, port, timeout=timeout)
    mail.login(username, password)
    setattr(mail, "_kolovrat_host", host)
    return mail

def count_messages(mail, encoded_folder, from_date, to_date, extra_criteria=None, include_deleted=False, use_sent_date=False) -> int:
    safe_name = encoded_folder.replace("\\", "\\\\").replace('"', r"\"")
    select_arg = f'"{safe_name}"'
    status, _ = mail.select(select_arg, readonly=True)
    if status != "OK":
        raise RuntimeError(f"Не удалось открыть папку: {encoded_folder}")
    criteria: list[str] = ["ALL" if include_deleted else "UNDELETED"]
    dt_to = datetime.strptime(to_date, "%Y-%m-%d") + timedelta(days=1)
    if use_sent_date:
        criteria.extend(["SENTSINCE", to_imap_date(from_date), "SENTBEFORE", to_imap_date(dt_to.strftime("%Y-%m-%d"))])
    else:
        criteria.extend(["SINCE", to_imap_date(from_date), "BEFORE", to_imap_date(dt_to.strftime("%Y-%m-%d"))])
    if extra_criteria:
        criteria.extend(extra_criteria)
    host = str(getattr(mail, "_kolovrat_host", "")).lower()
    if "yandex" in host:
        has_esearch = False
    else:
        has_esearch = getattr(mail, "_kolovrat_has_esearch", None)
    if has_esearch is None:
        caps = b""
        try:
            t, d = mail.capability()
            if t == "OK" and d:
                caps = b" ".join(d)
        except Exception:
            try:
                caps = b" ".join(getattr(mail, "capabilities", []) or [])
            except Exception:
                caps = b""
        caps_up = caps.upper()
        has_esearch = (b"ESEARCH" in caps_up) or (b"IMAP4REV2" in caps_up)
        setattr(mail, "_kolovrat_has_esearch", has_esearch)
    if has_esearch:
        try:
            if hasattr(mail, "untagged_responses"):
                mail.untagged_responses.pop("ESEARCH", None)
                mail.untagged_responses.pop(b"ESEARCH", None)
            mail.uid("SEARCH", "RETURN", "(COUNT)", *criteria)
            es = None
            if hasattr(mail, "untagged_responses"):
                es = mail.untagged_responses.pop("ESEARCH", None)
                if es is None:
                    es = mail.untagged_responses.pop(b"ESEARCH", None)
            if es:
                if isinstance(es, (list, tuple)):
                    blob = b" ".join(x if isinstance(x, (bytes, bytearray)) else str(x).encode("utf-8", "ignore") for x in es)
                elif isinstance(es, (bytes, bytearray)):
                    blob = bytes(es)
                else:
                    blob = str(es).encode("utf-8", "ignore")
                m = re.search(rb"\bCOUNT\s+(\d+)\b", blob)
                if m:
                    return int(m.group(1))
        except Exception:
            pass
    status, data = mail.search(None, *criteria)
    if status != "OK":
        raise RuntimeError(f"Не удалось выполнить поиск в папке: {encoded_folder}")
    ids = data[0].split() if data and data[0] else []
    return len(ids)

def count_total_messages(mail, encoded_folder, extra_criteria=None, include_deleted=False) -> int:
    safe_name = encoded_folder.replace("\\", "\\\\").replace('"', r"\"")
    select_arg = f'"{safe_name}"'
    status, _ = mail.select(select_arg, readonly=True)
    if status != "OK":
        raise RuntimeError(f"Не удалось открыть папку: {encoded_folder}")
    criteria: list[str] = ["ALL" if include_deleted else "UNDELETED"]
    if extra_criteria:
        criteria.extend(extra_criteria)
    host = str(getattr(mail, "_kolovrat_host", "")).lower()
    if "yandex" in host:
        has_esearch = False
    else:
        has_esearch = getattr(mail, "_kolovrat_has_esearch", None)
    if has_esearch is None:
        caps = b""
        try:
            t, d = mail.capability()
            if t == "OK" and d:
                caps = b" ".join(d)
        except Exception:
            try:
                caps = b" ".join(getattr(mail, "capabilities", []) or [])
            except Exception:
                caps = b""
        caps_up = caps.upper()
        has_esearch = (b"ESEARCH" in caps_up) or (b"IMAP4REV2" in caps_up)
        setattr(mail, "_kolovrat_has_esearch", has_esearch)
    if has_esearch:
        try:
            if hasattr(mail, "untagged_responses"):
                mail.untagged_responses.pop("ESEARCH", None)
                mail.untagged_responses.pop(b"ESEARCH", None)
            mail.uid("SEARCH", "RETURN", "(COUNT)", *criteria)
            es = None
            if hasattr(mail, "untagged_responses"):
                es = mail.untagged_responses.pop("ESEARCH", None)
                if es is None:
                    es = mail.untagged_responses.pop(b"ESEARCH", None)
            if es:
                if isinstance(es, (list, tuple)):
                    blob = b" ".join(
                        x if isinstance(x, (bytes, bytearray)) else str(x).encode("utf-8", "ignore")
                        for x in es
                    )
                elif isinstance(es, (bytes, bytearray)):
                    blob = bytes(es)
                else:
                    blob = str(es).encode("utf-8", "ignore")
                m = re.search(rb"\bCOUNT\s+(\d+)\b", blob)
                if m:
                    return int(m.group(1))
        except Exception:
            pass
    status, data = mail.search(None, *criteria)
    if status != "OK":
        raise RuntimeError(f"Не удалось выполнить поиск в папке: {encoded_folder}")
    ids = data[0].split() if data and data[0] else []
    return len(ids)

def decode_imap_utf7(s: str) -> str:
    res: list[str] = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "&":
            j = s.find("-", i + 1)
            if j == -1:
                res.append(s[i:])
                break
            if j == i + 1:
                res.append("&")
                i = j + 1
                continue
            b64 = s[i + 1: j].replace(",", "/")
            try:
                pad = "=" * (-len(b64) % 4)
                data = base64.b64decode(b64 + pad)
                res.append(data.decode("utf-16-be"))
            except Exception:
                res.append(s[i: j + 1])
            i = j + 1
        else:
            res.append(c)
            i += 1
    return "".join(res)


class MailStatsUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("КОЛОВРАТ")
        self.resizable(False, False)
        self._date_guard = False
        self._config_path = "mailsettings.json"
        self._accounts_path = "accounts.csv"
        self._imap_hosts_path = "imap_hosts.csv"
        self._accounts: dict[str, str] = {}
        self._imap_hosts: dict[str, int] = {}
        self._load_accounts()
        self._load_imap_hosts()
        self._build_ui()
        self._load_config()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _load_accounts(self) -> None:
        self._accounts.clear()
        if not os.path.exists(self._accounts_path):
            return
        try:
            with open(self._accounts_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if ":" not in line:
                        continue
                    login, password = line.split(":", 1)
                    login = login.strip()
                    password = password.strip()
                    if login and password:
                        self._accounts[login] = password
        except Exception as e:
            print(f"Ошибка загрузки аккаунтов: {e}")

    def _is_archive_folder(self, flags_part: str, decoded_name: str) -> bool:
        flags_upper = (flags_part or "").upper()
        name_upper = (decoded_name or "").upper()
        if "\\ARCHIVE" in flags_upper:
            return True
        archive_keywords = [
            "ARCHIVE",
            "ARCHIVES",
            "АРХИВ",
            "ARCHIV",
        ]
        for kw in archive_keywords:
            if kw in name_upper:
                return True
        return False

    def _collect_descendants(self, boxes, root_encoded: str):
        delims = set()
        for flags_part, decoded_name, encoded_name, delim in boxes:
            if delim and str(delim).upper() != "NIL":
                delims.add(delim)
        if not delims:
            delims = {"/"}
        res = []
        for flags_part, decoded_name, encoded_name, delim in boxes:
            if self._should_skip_folder(flags_part, decoded_name):
                continue
            if encoded_name == root_encoded:
                res.append((decoded_name, encoded_name))
                continue
            for d in delims:
                if encoded_name.startswith(root_encoded + d):
                    res.append((decoded_name, encoded_name))
                    break
        return res
    
    def _collect_incoming_scope(self, boxes):
        res = []
        for fp, dn, en, dl in boxes:
            if self._should_skip_folder(fp, dn):
                continue
            if self._is_sent_folder(fp, dn):
                continue
            if self._is_trash_folder(fp, dn):
                continue
            res.append((dn, en))
        return res

    def _load_imap_hosts(self) -> None:
        self._imap_hosts.clear()
        if not os.path.exists(self._imap_hosts_path):
            return
        try:
            with open(self._imap_hosts_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if ":" not in line:
                        continue
                    host, port_str = line.split(":", 1)
                    host = host.strip()
                    port_str = port_str.strip()
                    if not host or not port_str:
                        continue
                    try:
                        port = int(port_str)
                    except ValueError:
                        continue
                    self._imap_hosts[host] = port
        except Exception as e:
            print(f"Ошибка загрузки IMAP хостов: {e}")
        if not self._imap_hosts:
            self._imap_hosts["imap.yandex.ru"] = 993

    def _on_host_selected(self, event=None) -> None:
        host = self.entry_host.get().strip()
        if host in self._imap_hosts:
            port = self._imap_hosts[host]
            self.entry_port.delete(0, tk.END)
            self.entry_port.insert(0, str(port))

    def _on_date_change(self, var: tk.StringVar, which: str, entry: ttk.Entry) -> None:
        if self._date_guard:
            return
        self._date_guard = True
        try:
            raw = var.get()
            digits = "".join(ch for ch in raw if ch.isdigit())
            digits = digits[:8]          
            year = digits[:4] if len(digits) >= 4 else digits
            month = digits[4:6] if len(digits) > 4 else ""
            day = digits[6:8] if len(digits) > 6 else ""
            parts = []
            if year:
                parts.append(year)
            if month:
                parts.append(month)
            if day:
                parts.append(day)
            value = "-".join(parts) if parts else ""
            if value != raw:
                var.set(value)

            def move_cursor() -> None:
                entry.icursor(tk.END)
            entry.after_idle(move_cursor)
        finally:
            self._date_guard = False

    def _attach_context_menu(self, entry: tk.Widget) -> None:
        menu = tk.Menu(entry, tearoff=0)
        menu.add_command(label="Копировать", command=lambda e=entry: e.event_generate("<<Copy>>"))
        menu.add_command(label="Вставить", command=lambda e=entry: e.event_generate("<<Paste>>"))
        menu.add_command(label="Вырезать", command=lambda e=entry: e.event_generate("<<Cut>>"))
        menu.add_separator()
        if isinstance(entry, (tk.Entry, ttk.Entry, ttk.Combobox)):
            menu.add_command(
                label="Выделить всё",
                command=lambda e=entry: (e.select_range(0, "end"), e.icursor("end"))
            )

        def popup(event, m=menu) -> None:
            m.tk_popup(event.x_root, event.y_root)
            m.grab_release()
        entry.bind("<Button-3>", popup)

    def _on_login_selected(self, event=None) -> None:
        login = self.entry_username.get().strip()
        pwd = self._accounts.get(login)
        if pwd:
            self.entry_password.delete(0, tk.END)
            self.entry_password.insert(0, pwd)

    def _build_ui(self) -> None:
        padding = {"padx": 5, "pady": 3}
        main_frame = ttk.Frame(self)
        main_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        row = 0
        ttk.Label(main_frame, text="IMAP хост:").grid(row=row, column=0, sticky="w", **padding)
        host_values = sorted(self._imap_hosts.keys()) if self._imap_hosts else []
        self.entry_host = ttk.Combobox(
            main_frame,
            width=28,
            values=host_values
        )
        self.entry_host.grid(row=row, column=1, **padding)
        if host_values:
            self.entry_host.set(host_values[0])
        else:
            self.entry_host.set("imap.yandex.ru")
        self.entry_host.bind("<<ComboboxSelected>>", self._on_host_selected)
        self._attach_context_menu(self.entry_host)
        row += 1
        ttk.Label(main_frame, text="IMAP порт:").grid(row=row, column=0, sticky="w", **padding)
        self.entry_port = ttk.Entry(main_frame, width=10)
        self.entry_port.grid(row=row, column=1, sticky="w", **padding)
        self.entry_port.insert(0, "993")
        self._attach_context_menu(self.entry_port)
        row += 1
        ttk.Label(main_frame, text="Логин (e-mail):").grid(row=row, column=0, sticky="w", **padding)
        self.entry_username = ttk.Combobox(
            main_frame,
            width=28,
            values=sorted(self._accounts.keys())
        )
        self.entry_username.grid(row=row, column=1, **padding)
        self.entry_username.bind("<<ComboboxSelected>>", self._on_login_selected)
        self.entry_username.bind("<FocusOut>", self._on_login_selected)
        self._attach_context_menu(self.entry_username)
        row += 1
        ttk.Label(main_frame, text="Пароль:").grid(row=row, column=0, sticky="w", **padding)
        self.entry_password = ttk.Entry(main_frame, width=30, show="*")
        self.entry_password.grid(row=row, column=1, **padding)
        self._attach_context_menu(self.entry_password)
        row += 1
        ttk.Label(main_frame, text="Папка входящих:").grid(row=row, column=0, sticky="w", **padding)
        self.entry_inbox = ttk.Entry(main_frame, width=30)
        self.entry_inbox.grid(row=row, column=1, **padding)
        self.entry_inbox.insert(0, "INBOX")
        self._attach_context_menu(self.entry_inbox)
        row += 1
        ttk.Label(main_frame, text="Папка исходящих:").grid(row=row, column=0, sticky="w", **padding)
        self.entry_sent = ttk.Entry(main_frame, width=30)
        self.entry_sent.grid(row=row, column=1, **padding)
        self.entry_sent.insert(0, "Sent")
        self._attach_context_menu(self.entry_sent)
        row += 1
        ttk.Label(main_frame, text="Фильтр домена для исходящих:").grid(
            row=row, column=0, sticky="w", **padding
        )
        self.entry_sent_domain = ttk.Entry(main_frame, width=30)
        self.entry_sent_domain.grid(row=row, column=1, **padding)
        self._attach_context_menu(self.entry_sent_domain)
        row += 1
        ttk.Label(main_frame, text="Фильтр домена для входящих:").grid(
            row=row, column=0, sticky="w", **padding
        )
        self.entry_inbox_domain = ttk.Entry(main_frame, width=30)
        self.entry_inbox_domain.grid(row=row, column=1, **padding)
        self._attach_context_menu(self.entry_inbox_domain)
        row += 1
        detect_btn = ttk.Button(main_frame, text="Определить папки", command=self.on_detect_folders)
        detect_btn.grid(row=row, column=0, columnspan=2, pady=(5, 5))
        row += 1
        ttk.Label(main_frame, text="Дата с (YYYY-MM-DD):").grid(row=row, column=0, sticky="w", **padding)
        self.from_date_var = tk.StringVar()
        self.entry_from_date = ttk.Entry(main_frame, width=30, textvariable=self.from_date_var)
        self.entry_from_date.grid(row=row, column=1, **padding)
        self.from_date_var.trace_add(
            "write",
            lambda *args: self._on_date_change(self.from_date_var, "from", self.entry_from_date)
        )
        self._attach_context_menu(self.entry_from_date)
        row += 1
        ttk.Label(main_frame, text="Дата по (YYYY-MM-DD):").grid(row=row, column=0, sticky="w", **padding)
        self.to_date_var = tk.StringVar()
        self.entry_to_date = ttk.Entry(main_frame, width=30, textvariable=self.to_date_var)
        self.entry_to_date.grid(row=row, column=1, **padding)
        self.to_date_var.trace_add(
            "write",
            lambda *args: self._on_date_change(self.to_date_var, "to", self.entry_to_date)
        )
        self._attach_context_menu(self.entry_to_date)
        row += 1
        self.btn_calc = ttk.Button(main_frame, text="Посчитать", command=self.on_calculate)
        self.btn_calc.grid(row=row, column=0, columnspan=2, pady=(10, 5))
        row += 1
        self.label_result_inbox = ttk.Label(main_frame, text="Всего писем: -")
        self.label_result_inbox.grid(row=row, column=0, columnspan=2, sticky="w", **padding)
        row += 1
        self.label_result_sent = ttk.Label(main_frame, text="Обработано папок: -")
        self.label_result_sent.grid(row=row, column=0, columnspan=2, sticky="w", **padding)

    def _load_config(self) -> None:
        if not os.path.exists(self._config_path):
            return
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            return
        host = cfg.get("host")
        port = cfg.get("port")
        inbox = cfg.get("inbox")
        sent = cfg.get("sent")
        sent_domain = cfg.get("sent_domain")
        inbox_domain = cfg.get("inbox_domain")
        from_date = cfg.get("from_date")
        to_date = cfg.get("to_date")

        if host:
            self.entry_host.delete(0, tk.END)
            self.entry_host.insert(0, host)
        if port:
            self.entry_port.delete(0, tk.END)
            self.entry_port.insert(0, str(port))
        if inbox:
            self.entry_inbox.delete(0, tk.END)
            self.entry_inbox.insert(0, inbox)
        if sent:
            self.entry_sent.delete(0, tk.END)
            self.entry_sent.insert(0, sent)
        if sent_domain:
            self.entry_sent_domain.delete(0, tk.END)
            self.entry_sent_domain.insert(0, sent_domain)
        if inbox_domain:
            self.entry_inbox_domain.delete(0, tk.END)
            self.entry_inbox_domain.insert(0, inbox_domain)
        if from_date:
            self.from_date_var.set(from_date)
        if to_date:
            self.to_date_var.set(to_date)

    def _save_config(self) -> None:
        cfg = {
            "host": self.entry_host.get().strip(),
            "port": self.entry_port.get().strip(),
            "inbox": self.entry_inbox.get().strip(),
            "sent": self.entry_sent.get().strip(),
            "sent_domain": self.entry_sent_domain.get().strip(),
            "inbox_domain": self.entry_inbox_domain.get().strip(),
            "from_date": self.from_date_var.get().strip(),
            "to_date": self.to_date_var.get().strip(),
        }
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка загрузки аккаунтов: {e}")

    def _iter_mailboxes(self, mail):
        boxes = []
        typ, data = mail.list()
        if typ != "OK" or not data:
            return boxes
        for raw in data:
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
            lp = line.find("(")
            rp = line.find(")", lp + 1) if lp != -1 else -1
            flags_part = line[lp + 1:rp].strip() if (lp != -1 and rp != -1) else ""
            rest = line[rp + 1:].strip() if rp != -1 else line.strip()
            delim = "/"
            if rest.startswith('"'):
                q2 = rest.find('"', 1)
                if q2 != -1:
                    delim = rest[1:q2]
                    rest = rest[q2 + 1:].strip()
            encoded_name = rest
            if encoded_name.startswith('"') and encoded_name.endswith('"') and len(encoded_name) >= 2:
                encoded_name = encoded_name[1:-1]
            encoded_name = encoded_name.strip()
            if not encoded_name:
                continue
            decoded_name = decode_imap_utf7(encoded_name)
            boxes.append((flags_part, decoded_name, encoded_name, delim))
        return boxes

    def _is_drafts_folder(self, flags_part: str, decoded_name: str) -> bool:
        flags_upper = (flags_part or "").upper()
        name_upper = (decoded_name or "").upper()
        if "\\DRAFTS" in flags_upper:
            return True
        drafts_keywords = [
            "DRAFTS",
            "DRAFT",
            "ЧЕРНОВИКИ",
            "ЧЕРНОВЫЕ",
        ]
        for kw in drafts_keywords:
            if kw in name_upper:
                return True
        return False

    def _is_sent_folder(self, flags_part: str, decoded_name: str) -> bool:
        flags_upper = (flags_part or "").upper()
        last = self._last_seg_upper(decoded_name)
        sent_cfg = self.entry_sent.get().strip()
        sent_cfg_upper = sent_cfg.upper() if sent_cfg else ""
        if "\\SENT" in flags_upper:
            return True
        if sent_cfg_upper and last == sent_cfg_upper:
            return True
        return last in {
            "SENT",
            "SENT ITEMS",
            "ОТПРАВЛЕННЫЕ",
            "ОТПРАВЛЕННЫЕ ПИСЬМА",
        }
    
    def _is_inbox_folder(self, flags_part: str, decoded_name: str) -> bool:
        flags_upper = (flags_part or "").upper()
        name_upper = (decoded_name or "").upper()
        inbox_cfg = self.entry_inbox.get().strip()
        inbox_cfg_upper = inbox_cfg.upper() if inbox_cfg else ""
        if "\\INBOX" in flags_upper:
            return True
        if inbox_cfg_upper and name_upper == inbox_cfg_upper:
            return True
        if name_upper == "INBOX":
            return True
        if "ВХОДЯЩИЕ" in name_upper:
            return True
        return False
    
    def _is_trash_folder(self, flags_part: str, decoded_name: str) -> bool:
        flags_upper = (flags_part or "").upper()
        last = self._last_seg_upper(decoded_name)
        if "\\TRASH" in flags_upper:
            return True
        return last in {
            "DELETED ITEMS",
            "DELETED MESSAGES",
            "TRASH",
            "BIN",
            "КОРЗИНА",
            "УДАЛЕННЫЕ",
            "УДАЛЁННЫЕ",
        }
    
    def _is_spam_folder(self, flags_part: str, decoded_name: str) -> bool:
        flags_upper = (flags_part or "").upper()
        name_upper = (decoded_name or "").upper()
        if "\\JUNK" in flags_upper or "\\SPAM" in flags_upper:
            return True
        spam_keywords = [
            "SPAM",
            "JUNK",
            "СПАМ",
            "НЕЖЕЛАТЕЛЬНЫЕ",
        ]
        for kw in spam_keywords:
            if kw in name_upper:
                return True
        return False
    
    def _should_skip_folder(self, flags_part: str, decoded_name: str) -> bool:
        flags_upper = (flags_part or "").upper()      
        if "\\NOSELECT" in flags_upper or "NOSELECT" in flags_upper:
            return True
        if decoded_name in ("|", "|:") or decoded_name.startswith("|:"):
            return True
        if self._is_drafts_folder(flags_part, decoded_name):
            return True
        if self._is_spam_folder(flags_part, decoded_name):
            return True
        if self._is_archive_folder(flags_part, decoded_name):
            return True
        return False
    
    def _last_seg_upper(self, name: str) -> str:
        s = (name or "").strip()
        for sep in ("/", "\\", "."):
            if sep in s:
                s = s.split(sep)[-1]
        return s.strip().upper()

    def _select_main_folders(self, boxes: list[tuple[str, str, str, str]],) -> tuple[str | None, str | None]:
        inbox_cfg = (self.entry_inbox.get() or "").strip()
        sent_cfg = (self.entry_sent.get() or "").strip()
        inbox_cfg_up = inbox_cfg.upper()
        sent_cfg_up = sent_cfg.upper()
        inbox_by_cfg: str | None = None
        inbox_by_flag: str | None = None
        inbox_first: str | None = None
        sent_by_cfg: str | None = None
        sent_by_flag: str | None = None
        sent_first: str | None = None
        for flags_part, decoded_name, encoded_name, delim in boxes:
            name_up = (decoded_name or "").upper()
            flags_up = (flags_part or "").upper()
            if self._is_inbox_folder(flags_part, decoded_name):
                if inbox_first is None:
                    inbox_first = encoded_name
                if inbox_cfg_up and name_up == inbox_cfg_up:
                    inbox_by_cfg = encoded_name
                if "\\INBOX" in flags_up:
                    inbox_by_flag = encoded_name
            if self._is_sent_folder(flags_part, decoded_name):
                if sent_first is None:
                    sent_first = encoded_name
                if sent_cfg_up and name_up == sent_cfg_up:
                    sent_by_cfg = encoded_name
                if "\\SENT" in flags_up:
                    sent_by_flag = encoded_name
        main_inbox = inbox_by_cfg or inbox_by_flag or inbox_first
        main_sent = sent_by_cfg or sent_by_flag or sent_first
        return main_inbox, main_sent

    def on_detect_folders(self) -> None:
        host = self.entry_host.get().strip()
        port_str = self.entry_port.get().strip()
        username = self.entry_username.get().strip()
        password = self.entry_password.get().strip()
        try:
            port = int(port_str)
        except ValueError:
            messagebox.showerror("Ошибка", "Порт должен быть числом.")
            return
        try:
            mail = connect_imap(host, port, username, password)
        except imaplib.IMAP4.error as e:
            messagebox.showerror("IMAP ошибка", f"Ошибка IMAP при подключении:\n{e}")
            return
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось подключиться:\n{e}")
            return
        try:
            boxes = self._iter_mailboxes(mail)                    
            inbox_candidate = None
            sent_candidate = None
            
            for flags_part, decoded_name, encoded_name, delim in boxes:
                if self._should_skip_folder(flags_part, decoded_name):
                    continue                    
                if self._is_inbox_folder(flags_part, decoded_name):
                    if inbox_candidate is None:
                        inbox_candidate = decoded_name
                if self._is_sent_folder(flags_part, decoded_name):
                    if sent_candidate is None:
                        sent_candidate = decoded_name                        
            if inbox_candidate is None:
                inbox_candidate = "INBOX"
            if inbox_candidate:
                self.entry_inbox.delete(0, tk.END)
                self.entry_inbox.insert(0, inbox_candidate)
            if sent_candidate:
                self.entry_sent.delete(0, tk.END)
                self.entry_sent.insert(0, sent_candidate)                
            if inbox_candidate and sent_candidate:
                messagebox.showinfo(
                    "Результат",
                    f"Определены папки:\nINBOX: {inbox_candidate}\nSent: {sent_candidate}",
                )
            elif inbox_candidate and not sent_candidate:
                messagebox.showinfo(
                    "Результат",
                    "Папка входящих определена, исходящих не найдена.",
                )
            elif sent_candidate and not inbox_candidate:
                messagebox.showinfo(
                    "Результат",
                    "Папка исходящих определена, входящих не найдена.",
                )
            else:
                messagebox.showinfo(
                    "Результат",
                    "Не удалось автоматически определить папки.",
                )
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка при определении папок:\n{e}")
        finally:
            try:
                mail.logout()
            except Exception:
                pass
        self._save_config()

    def _validate_common_params(self):
        host = self.entry_host.get().strip()
        port_str = self.entry_port.get().strip()
        inbox_folder = self.entry_inbox.get().strip()
        sent_folder = self.entry_sent.get().strip()
        sent_domain = self.entry_sent_domain.get().strip() or None
        inbox_domain = self.entry_inbox_domain.get().strip() or None
        from_date = self.from_date_var.get().strip() or None
        to_date = self.to_date_var.get().strip() or None
        username = self.entry_username.get().strip()
        password = self.entry_password.get().strip()
        if not host:
            raise ValueError("Укажите IMAP хост.")
        if not username and not password:
            try:
                self.entry_username.focus_set()
            except Exception:
                pass
            raise ValueError("Не заполнены логин и пароль.")
        if not username:
            try:
                self.entry_username.focus_set()
            except Exception:
                pass
            raise ValueError("Не заполнен логин.")
        if not password:
            try:
                self.entry_password.focus_set()
            except Exception:
                pass
            raise ValueError("Не заполнен пароль.")
        try:
            port = int(port_str)
        except ValueError:
            raise ValueError("Порт должен быть числом.")
        try:
            if from_date:
                datetime.strptime(from_date, "%Y-%m-%d")
            if to_date:
                datetime.strptime(to_date, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Дата должна быть в формате YYYY-MM-DD.")
        if sent_domain and not (from_date or to_date):
            raise ValueError(
                "При указании фильтра домена для исходящих нужно задать период "
                "(дата с и/или дата по)."
            )
        if not from_date or not to_date:
            raise ValueError(
                "Для ускорения работы нужно задать обе даты: 'Дата с' и 'Дата по'."
            )
        if from_date and to_date:
            d1 = datetime.strptime(from_date, "%Y-%m-%d")
            d2 = datetime.strptime(to_date, "%Y-%m-%d")
            if d1 > d2:
                raise ValueError("Дата 'с' не может быть позже даты 'по'.")
        return host, port, username, password, inbox_folder, sent_folder, from_date, to_date, sent_domain, inbox_domain

    def on_calculate(self) -> None:
        try:
            (
                host,
                port,
                username,
                password,
                inbox_folder,
                sent_folder,
                from_date,
                to_date,
                sent_domain,
                inbox_domain,
            ) = self._validate_common_params()
        except ValueError as e:
            messagebox.showerror("Ошибка", str(e))
            return
        sent_domain_norm = sent_domain.strip() if sent_domain else None
        inbox_domain_norm = inbox_domain.strip() if inbox_domain else None
        self.btn_calc.config(state="disabled")
        self.label_result_inbox.config(text="Всего писем: считаем...")
        self.label_result_sent.config(text="Обработано папок: ...")
        self.update_idletasks()
        mail = None
        try:
            mail = connect_imap(host, port, username, password, timeout=30.0)
            boxes = self._iter_mailboxes(mail)
            main_inbox, main_sent = self._select_main_folders(boxes)
            folder_results: list[tuple[str, str, int | None, int | None, str | None]] = []
            total_inbox = 0
            total_sent = 0
            total_count = 0
            if sent_domain_norm:
                if not main_sent:
                    self.label_result_inbox.config(text="Всего писем: 0")
                    self.label_result_sent.config(text="Обработано папок: 0")
                    messagebox.showinfo(
                        "Результат",
                        "Не найдены папки исходящих (Sent), к которым можно применить фильтр.",
                    )
                    return
                sent_list = self._collect_descendants(boxes, main_sent)
                extra = ["HEADER", "To", sent_domain_norm]
                for dec_name, enc_name in sent_list:
                    try:
                        cnt = count_messages(
                            mail,
                            enc_name,
                            from_date,
                            to_date,
                            extra_criteria=extra,
                            include_deleted=False,
                            use_sent_date=True,
                        )
                        total_sent += cnt

                        total_all = None
                        if cnt == 0:
                            total_all = count_total_messages(
                                mail,
                                enc_name,
                                extra_criteria=None,
                                include_deleted=False,
                            )

                        folder_results.append((dec_name, enc_name, cnt, total_all, None))
                    except Exception as e:
                        folder_results.append((dec_name, enc_name, None, None, str(e)))
                total_count = total_sent
                self.label_result_inbox.config(
                    text=f"Всего исходящих для домена '{sent_domain_norm}': {total_sent}"
                )
                self.label_result_sent.config(text=f"Обработано папок: {len(folder_results)}")
                title = "Результат по исходящим (фильтр по домену)"
                header = (
                    f"Всего исходящих для домена '{sent_domain_norm}': {total_sent}\n"
                    f"Обработано папок: {len(folder_results)}\n\n"
                )
            elif inbox_domain_norm:
                if not main_inbox:
                    self.label_result_inbox.config(text="Всего писем: 0")
                    self.label_result_sent.config(text="Обработано папок: 0")
                    messagebox.showinfo(
                        "Результат",
                        "Не найдены папки входящих (INBOX), к которым можно применить фильтр.",
                    )
                    return
                if "yandex" in host.lower():
                    inbox_list = self._collect_incoming_scope(boxes)
                else:
                    inbox_list = self._collect_descendants(boxes, main_inbox)
                extra = ["HEADER", "From", inbox_domain_norm]
                for dec_name, enc_name in inbox_list:
                    try:
                        cnt = count_messages(
                            mail,
                            enc_name,
                            from_date,
                            to_date,
                            extra_criteria=extra,
                            include_deleted=False,
                            use_sent_date=False,
                        )
                        total_inbox += cnt
                        total_all = None
                        if cnt == 0:
                            total_all = count_total_messages(mail, enc_name, extra_criteria=None, include_deleted=False)
                        folder_results.append((dec_name, enc_name, cnt, total_all, None))
                    except Exception as e:
                        folder_results.append((dec_name, enc_name, None, None, str(e)))
                total_count = total_inbox
                self.label_result_inbox.config(
                    text=f"Всего входящих с домена '{inbox_domain_norm}': {total_inbox}"
                )
                self.label_result_sent.config(text=f"Обработано папок: {len(folder_results)}")
                title = "Результат по входящим (фильтр по домену)"
                header = (
                    f"Всего входящих с домена '{inbox_domain_norm}': {total_inbox}\n"
                    f"Обработано папок: {len(folder_results)}\n\n"
                )
            else:
                inbox_list = []
                if main_inbox:
                    if "yandex" in host.lower():
                        inbox_list = self._collect_incoming_scope(boxes)
                    else:
                        inbox_list = self._collect_descendants(boxes, main_inbox)
                sent_list = []
                if main_sent:
                    sent_list = self._collect_descendants(boxes, main_sent)
                seen = set()
                for dec_name, enc_name in inbox_list:
                    if enc_name in seen:
                        continue
                    seen.add(enc_name)
                    try:
                        cnt = count_messages(
                            mail,
                            enc_name,
                            from_date,
                            to_date,
                            extra_criteria=None,
                            include_deleted=False,
                            use_sent_date=False,
                        )
                        total_inbox += cnt

                        total_all = None
                        if cnt == 0:
                            total_all = count_total_messages(
                                mail,
                                enc_name,
                                extra_criteria=None,
                                include_deleted=False,
                            )

                        folder_results.append((dec_name, enc_name, cnt, total_all, None))
                    except Exception as e:
                        folder_results.append((dec_name, enc_name, None, None, str(e)))

                for dec_name, enc_name in sent_list:
                    if enc_name in seen:
                        continue
                    seen.add(enc_name)
                    try:
                        cnt = count_messages(
                            mail,
                            enc_name,
                            from_date,
                            to_date,
                            extra_criteria=None,
                            include_deleted=False,
                            use_sent_date=True,
                        )
                        total_sent += cnt
                        total_all = None
                        if cnt == 0:
                            total_all = count_total_messages(
                                mail,
                                enc_name,
                                extra_criteria=None,
                                include_deleted=False,
                            )
                        folder_results.append((dec_name, enc_name, cnt, total_all, None))
                    except Exception as e:
                        folder_results.append((dec_name, enc_name, None, None, str(e)))
                total_count = total_inbox + total_sent
                self.label_result_inbox.config(
                    text=f"Всего писем: {total_count} (входящих: {total_inbox}, исходящих: {total_sent})"
                )
                self.label_result_sent.config(text=f"Обработано папок: {len(folder_results)}")
                title = "Результат (входящие/исходящие)"
                header = (
                    f"Всего писем: {total_count} (входящих: {total_inbox}, исходящих: {total_sent})\n"
                    f"Обработано папок: {len(folder_results)}\n\n"
                )
            lines = [header, "Детализация по папкам:\n"]
            for dec_name, enc_name, cnt, total_all, err in folder_results:
                if err:
                    lines.append(f"{dec_name}: ошибка ({err})")
                else:
                    if total_all is not None:
                        lines.append(f"{dec_name}: {cnt} писем за период (всего в папке: {total_all})")
                    else:
                        lines.append(f"{dec_name}: {cnt} писем за период")
            messagebox.showinfo(title, "\n".join(lines))
        except imaplib.IMAP4.error as e:
            messagebox.showerror("Ошибка IMAP", f"Ошибка IMAP:\n{e}")
            self.label_result_inbox.config(text="Всего писем: ошибка IMAP")
            self.label_result_sent.config(text="Обработано папок: ошибка IMAP")
        except TimeoutError as e:
            messagebox.showerror("Таймаут", f"Превышено время ожидания ответа IMAP-сервера:\n{e}")
            self.label_result_inbox.config(text="Всего писем: таймаут")
            self.label_result_sent.config(text="Обработано папок: таймаут")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Произошла ошибка:\n{e}")
            self.label_result_inbox.config(text="Всего писем: ошибка")
            self.label_result_sent.config(text="Обработано папок: ошибка")
        finally:
            try:
                if mail is not None:
                    try:
                        mail.close()
                    except Exception:
                        pass
                    try:
                        mail.logout()
                    except Exception:
                        pass
            finally:
                self.btn_calc.config(state="normal")
                self._save_config()

    def on_close(self) -> None:
        self._save_config()
        self.destroy()


if __name__ == "__main__":
    ensure_required_files()
    app = MailStatsUI()
    app.mainloop()
