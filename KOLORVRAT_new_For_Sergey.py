import imaplib
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import json
import os
import sys
import base64
import re
from email.utils import parsedate_to_datetime, getaddresses
from email.parser import BytesParser
from email import policy
import threading
import traceback
import logging

BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE_DIR, "kolovrat.log")
REPORTS_DIR = os.path.join(BASE_DIR, "Отчеты")

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

def _safe_filename(s: str, max_len: int = 80) -> str:
    s = (s or "").strip()
    s = re.sub(r"[^0-9A-Za-zА-Яа-я._-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        s = "report"
    return s[:max_len]

def save_full_report(
    title: str,
    message: str,
    username: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> str | None:
    try:
        os.makedirs(REPORTS_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        user_part = _safe_filename(username or "account", 40)
        period_part = _safe_filename(f"{from_date or ''}_{to_date or ''}", 30)
        name = f"Отчет_{user_part}_{period_part}_{ts}.txt"
        out_path = os.path.join(REPORTS_DIR, name)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write((title or "Результат") + "\n\n")
            f.write(message or "")
            f.write("\n")
        return out_path
    except Exception:
        logging.exception("Не удалось сохранить отчёт")
        return None

def ensure_required_files():
    cfg = os.path.join(BASE_DIR, "mailsettings.json")
    acc = os.path.join(BASE_DIR, "accounts.csv")
    hosts = os.path.join(BASE_DIR, "imap_hosts.csv")

    if not os.path.exists(cfg):
        with open(cfg, "w", encoding="utf-8") as f:
            f.write("{}")
    if not os.path.exists(acc):
        with open(acc, "w", encoding="utf-8") as f:
            f.write("# логин:пароль\n")
    if not os.path.exists(hosts):
        with open(hosts, "w", encoding="utf-8") as f:
            f.write("# host:port\n")
            f.write("imap.yandex.ru:993\n")
            f.write("mail.klvrt.ru:993\n")

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

def fetch_message_ids(mail, uid_list, step: int = 800) -> set[str]:
    if not uid_list:
        return set()
    res: set[str] = set()
    norm_uids: list[bytes] = []
    for u in uid_list:
        if u is None:
            continue
        if isinstance(u, bytes):
            norm_uids.append(u)
        else:
            norm_uids.append(str(u).encode("ascii", "ignore"))
    uid_re = re.compile(rb"\bUID\s+(\d+)\b", re.IGNORECASE)
    for i in range(0, len(norm_uids), step):
        chunk = norm_uids[i:i + step]
        uid_set = b",".join(chunk)
        status, data = mail.uid(
            "FETCH",
            uid_set,
            "(UID BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])"
        )
        if status != "OK" or not data:
            continue
        for item in data:
            if not item or not isinstance(item, tuple) or len(item) < 2:
                continue
            meta, payload = item[0], item[1]
            if not isinstance(payload, (bytes, bytearray)):
                continue
            uid = None
            try:
                meta_b = meta if isinstance(meta, (bytes, bytearray)) else str(meta).encode("utf-8", "ignore")
                m = uid_re.search(meta_b)
                if m:
                    uid = m.group(1).decode("ascii", "ignore")
            except Exception:
                uid = None
            mid = ""
            try:
                lines = bytes(payload).splitlines()
                for idx, line in enumerate(lines):
                    if line.lower().startswith(b"message-id:"):
                        val = line.split(b":", 1)[1].strip()
                        j = idx + 1
                        while j < len(lines) and (lines[j].startswith(b" ") or lines[j].startswith(b"\t")):
                            val += b" " + lines[j].strip()
                            j += 1
                        val = val.strip().strip(b"<").strip(b">").strip()
                        mid = val.decode("utf-8", "ignore").strip()
                        break
            except Exception:
                mid = ""

            if mid:
                res.add(mid)
            elif uid:
                res.add("uid:" + uid)
            else:

                pass
    return res


def fetch_message_id_map(mail, uid_list, step: int = 800) -> dict[str, str]:
    if not uid_list:
        return {}
    out: dict[str, str] = {}
    norm_uids: list[bytes] = []
    for u in uid_list:
        if u is None:
            continue
        if isinstance(u, bytes):
            norm_uids.append(u)
        else:
            norm_uids.append(str(u).encode("ascii", "ignore"))
    uid_re = re.compile(rb"\bUID\s+(\d+)\b", re.IGNORECASE)
    for i in range(0, len(norm_uids), step):
        chunk = norm_uids[i:i + step]
        uid_set = b",".join(chunk)
        status, data = mail.uid(
            "FETCH",
            uid_set,
            "(UID BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])"
        )
        if status != "OK" or not data:
            continue
        for item in data:
            if not item or not isinstance(item, tuple) or len(item) < 2:
                continue
            meta, payload = item[0], item[1]
            if not isinstance(payload, (bytes, bytearray)):
                continue
            uid = ""
            try:
                meta_b = meta if isinstance(meta, (bytes, bytearray)) else str(meta).encode("utf-8", "ignore")
                m = uid_re.search(meta_b)
                if m:
                    uid = m.group(1).decode("ascii", "ignore").strip()
            except Exception:
                uid = ""
            mid = ""
            try:
                lines = bytes(payload).splitlines()
                for idx, line in enumerate(lines):
                    if line.lower().startswith(b"message-id:"):
                        val = line.split(b":", 1)[1].strip()
                        j = idx + 1
                        while j < len(lines) and (lines[j].startswith(b" ") or lines[j].startswith(b"\t")):
                            val += b" " + lines[j].strip()
                            j += 1
                        val = val.strip().strip(b"<").strip(b">").strip()
                        mid = val.decode("utf-8", "ignore").strip()
                        break
            except Exception:
                mid = ""
            if uid:
                out[uid] = mid if mid else ("uid:" + uid)
    return out

def fetch_from_to_map(mail, uid_list, step: int = 400) -> dict[str, tuple[str, str]]:
    if not uid_list:
        return {}
    out: dict[str, tuple[str, str]] = {}
    norm_uids: list[bytes] = []
    for u in uid_list:
        if u is None:
            continue
        if isinstance(u, bytes):
            norm_uids.append(u)
        else:
            norm_uids.append(str(u).encode("ascii", "ignore"))

    uid_re = re.compile(rb"\bUID\s+(\d+)\b", re.IGNORECASE)
    parser = BytesParser(policy=policy.default)

    for i in range(0, len(norm_uids), step):
        chunk = norm_uids[i:i + step]
        uid_set = b",".join(chunk)
        status, data = mail.uid(
            "FETCH",
            uid_set,
            "(UID BODY.PEEK[HEADER.FIELDS (FROM TO)])",
        )
        if status != "OK" or not data:
            continue

        for item in data:
            if not item or not isinstance(item, tuple) or len(item) < 2:
                continue
            meta, payload = item[0], item[1]
            if not isinstance(payload, (bytes, bytearray)):
                continue

            uid = ""
            try:
                meta_b = meta if isinstance(meta, (bytes, bytearray)) else str(meta).encode("utf-8", "ignore")
                m = uid_re.search(meta_b)
                if m:
                    uid = m.group(1).decode("ascii", "ignore").strip()
            except Exception:
                uid = ""
            if not uid:
                continue

            try:
                msg = parser.parsebytes(bytes(payload))
                from_h = (msg.get("From") or "").strip()
                to_h = (msg.get("To") or "").strip()
            except Exception:
                from_h = ""
                to_h = ""

            out[uid] = (from_h, to_h)

    return out

def _load_mid_cache(path: str) -> dict:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            if isinstance(obj, dict):
                return obj
    except Exception:
        pass
    return {}

def _save_mid_cache(path: str, obj: dict) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
    except Exception:
        pass

def _get_uidvalidity(mail, encoded_folder: str) -> str:
    safe_name = encoded_folder.replace("\\", "\\\\").replace('"', r'\"')
    try:
        status, data = mail.status(f'"{safe_name}"', "(UIDVALIDITY)")
        if status == "OK" and data:
            blob = b" ".join(x for x in data if isinstance(x, (bytes, bytearray)))
            m = re.search(rb"UIDVALIDITY\s+(\d+)", blob)
            if m:
                return m.group(1).decode("ascii", "ignore")
    except Exception:
        pass
    return ""

def _replace_sent_with_internal(criteria: list[str]) -> list[str]:
    alt = list(criteria)
    for i, v in enumerate(alt):
        try:
            up = v.upper()
        except Exception:
            continue
        if up == "SENTSINCE":
            alt[i] = "SINCE"
        elif up == "SENTBEFORE":
            alt[i] = "BEFORE"
    return alt

def search_uids(mail, encoded_folder, from_date, to_date, extra_criteria=None, include_deleted=False, use_sent_date=False):
    safe_name = encoded_folder.replace("\\", "\\\\").replace('"', r"\"")
    status, _ = mail.select(f'"{safe_name}"', readonly=True)
    if status != "OK":
        raise RuntimeError("Не удалось открыть одну из папок почты. Проверь доступ к папкам и попробуй ещё раз.")
    criteria: list[str] = ["ALL" if include_deleted else "UNDELETED"]
    dt_to = datetime.strptime(to_date, "%Y-%m-%d") + timedelta(days=1)
    if use_sent_date:
        criteria.extend(["SENTSINCE", to_imap_date(from_date), "SENTBEFORE", to_imap_date(dt_to.strftime("%Y-%m-%d"))])
    else:
        criteria.extend(["SINCE", to_imap_date(from_date), "BEFORE", to_imap_date(dt_to.strftime("%Y-%m-%d"))])
    if extra_criteria:
        criteria.extend(extra_criteria)
    status, data = mail.uid("SEARCH", *criteria)
    if status != "OK":
        if use_sent_date:
            try:
                alt = _replace_sent_with_internal(criteria)
                status2, data2 = mail.uid("SEARCH", *alt)
                if status2 == "OK" and data2 and data2[0]:
                    return data2[0].split()
            except Exception:
                pass
        raise RuntimeError("Не удалось выполнить поиск писем в одной из папок. Попробуй уменьшить период и повторить.")
    result = data[0].split() if data and data[0] else []
    if use_sent_date and not result:
        try:
            alt = _replace_sent_with_internal(criteria)
            status2, data2 = mail.uid("SEARCH", *alt)
            if status2 == "OK" and data2 and data2[0]:
                result = data2[0].split()
        except Exception:
            pass
    return result

def search_count(mail, encoded_folder, from_date, to_date, extra_criteria=None, include_deleted=False, use_sent_date=False) -> int:
    safe_name = encoded_folder.replace("\\", "\\\\").replace('"', r"\"")
    status, _ = mail.select(f'"{safe_name}"', readonly=True)
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
    try:
        status, data = mail.uid("SEARCH", "RETURN", "(COUNT)", *criteria)
        if status == "OK" and data:
            blob = b" ".join(x for x in data if isinstance(x, (bytes, bytearray)))
            m = re.search(rb"\bCOUNT\s+(\d+)\b", blob)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    uids = search_uids(
        mail, encoded_folder, from_date, to_date,
        extra_criteria=extra_criteria,
        include_deleted=include_deleted,
        use_sent_date=use_sent_date,
    )
    return len(uids)

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
        self._config_path = os.path.join(BASE_DIR, "mailsettings.json")
        self._accounts_path = os.path.join(BASE_DIR, "accounts.csv")
        self._imap_hosts_path = os.path.join(BASE_DIR, "imap_hosts.csv")
        self._accounts: dict[str, str] = {}
        self._imap_hosts: dict[str, int] = {}
        self._load_accounts()
        self._load_imap_hosts()
        self._build_ui()
        self._load_config()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._worker_thread: threading.Thread | None = None
        self._cancel_event = threading.Event()
        self._busy = False

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
        delim_map = {}
        all_delims = set()
        for flags_part, decoded_name, encoded_name, delim in boxes:
            if not encoded_name:
                continue
            d = delim if delim and str(delim).upper() != "NIL" else None
            if d:
                delim_map[encoded_name] = d
                all_delims.add(d)
        root_delim = delim_map.get(root_encoded)
        delims = {root_delim} if root_delim else set(all_delims)
        if not delims:
            delims = {"/", "."}
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

    def _ask_password(self, title: str, prompt: str) -> str | None:
        dlg = tk.Toplevel(self)
        dlg.transient(self)
        dlg.title(title or "Пароль")
        dlg.resizable(False, False)
        dlg.grab_set()
        frm = ttk.Frame(dlg, padding=10)
        frm.pack(fill="both", expand=True)
        lbl = ttk.Label(frm, text=prompt)
        lbl.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        pwd_var = tk.StringVar()
        entry = ttk.Entry(frm, show="*", textvariable=pwd_var, width=40)
        entry.grid(row=1, column=0, columnspan=2, sticky="we", pady=(0, 6))
        entry.focus_set()
        result = {"value": None}

        def on_ok(event=None):
            result["value"] = pwd_var.get()
            dlg.destroy()

        def on_cancel(event=None):
            result["value"] = None
            dlg.destroy()

        btn_ok = ttk.Button(frm, text="OK", command=on_ok)
        btn_ok.grid(row=2, column=0, sticky="e", padx=(0, 6))
        btn_cancel = ttk.Button(frm, text="Отмена", command=on_cancel)
        btn_cancel.grid(row=2, column=1, sticky="w")
        dlg.bind("<Return>", on_ok)
        dlg.bind("<Escape>", on_cancel)
        self.update_idletasks()
        dlg.update_idletasks()
        px = self.winfo_rootx()
        py = self.winfo_rooty()
        pw = self.winfo_width()
        ph = self.winfo_height()
        dw = dlg.winfo_reqwidth()
        dh = dlg.winfo_reqheight()
        x = px + max(0, (pw - dw) // 2)
        y = py + max(0, (ph - dh) // 2)
        dlg.geometry(f"+{x}+{y}")
        entry.icursor(tk.END)
        entry.selection_range(0, "end")
        dlg.wait_window()
        return result["value"]

    def _add_account(self) -> None:
        login = simpledialog.askstring("Добавить аккаунт", "Логин (email):", parent=self)
        if not login:
            return
        login = login.strip()
        if not login:
            return
        pwd = self._ask_password("Добавить аккаунт", "Пароль:")
        if pwd is None:
            return
        pwd = pwd.strip()
        if not pwd:
            messagebox.showwarning("Внимание", "Пароль пустой — запись не добавлена.", parent=self)
            return
        if login in self._accounts:
            overwrite = messagebox.askyesno(
                "Аккаунт уже есть",
                f"Аккаунт {login} уже существует. Перезаписать пароль?",
                parent=self
            )
            if not overwrite:
                return
        try:
            updated = False
            if os.path.exists(self._accounts_path):
                try:
                    with open(self._accounts_path, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                except Exception:
                    lines = None
                if lines is not None:
                    out_lines = []
                    for line in lines:
                        if line.strip().startswith("#"):
                            out_lines.append(line)
                            continue
                        if ":" not in line:
                            out_lines.append(line)
                            continue
                        lg, _ = line.split(":", 1)
                        if lg.strip() == login:
                            out_lines.append(f"{login}:{pwd}\n")
                            updated = True
                        else:
                            out_lines.append(line)
                    try:
                        with open(self._accounts_path, "w", encoding="utf-8") as f:
                            f.writelines(out_lines)
                    except Exception:
                        with open(self._accounts_path, "a", encoding="utf-8") as f:
                            f.write(f"{login}:{pwd}\n")
                            updated = True
            if not updated:
                with open(self._accounts_path, "a", encoding="utf-8") as f:
                    f.write(f"{login}:{pwd}\n")
            self._accounts[login] = pwd
            try:
                vals = sorted(self._accounts.keys())
                self.entry_username["values"] = vals
                self.entry_username.set(login)
                try:
                    self.entry_password.focus_set()
                except Exception:
                    pass
            except Exception:
                pass
            messagebox.showinfo("ОК", f"Аккаунт {login} сохранён.", parent=self)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить аккаунт:\n{e}", parent=self)

    def _build_ui(self) -> None:
        padding = {"padx": 5, "pady": 3}
        main_frame = ttk.Frame(self)
        main_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        row = 0
        ttk.Label(main_frame, text="IMAP хост:").grid(row=row, column=0, sticky="w", **padding)
        host_values = sorted(self._imap_hosts.keys()) if self._imap_hosts else []
        self.entry_host = ttk.Combobox(main_frame, width=28, values=host_values)
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
        self.entry_username = ttk.Combobox(main_frame, width=28, values=sorted(self._accounts.keys()))
        self.entry_username.grid(row=row, column=1, **padding)
        self.entry_username.bind("<<ComboboxSelected>>", self._on_login_selected)
        self.entry_username.bind("<FocusOut>", self._on_login_selected)
        self._attach_context_menu(self.entry_username)
        btn_add_account = ttk.Button(main_frame, text="+", width=3, command=self._add_account)
        btn_add_account.grid(row=row, column=2, sticky="w", padx=(0, 5))
        row += 1
        ttk.Label(main_frame, text="Пароль:").grid(row=row, column=0, sticky="w", **padding)
        self.entry_password = ttk.Entry(main_frame, width=30, show="*")
        self.entry_password.grid(row=row, column=1, **padding)
        self._attach_context_menu(self.entry_password)
        row += 1
        ttk.Label(main_frame, text="Папка входящих:").grid(row=row, column=0, sticky="w", **padding)
        self.entry_inbox = ttk.Entry(main_frame, width=30)
        self.entry_inbox.grid(row=row, column=1, **padding)
        self.entry_inbox.insert(0, "Входящие")
        self._attach_context_menu(self.entry_inbox)
        row += 1
        ttk.Label(main_frame, text="Папка исходящих:").grid(row=row, column=0, sticky="w", **padding)
        self.entry_sent = ttk.Entry(main_frame, width=30)
        self.entry_sent.grid(row=row, column=1, **padding)
        self.entry_sent.insert(0, "Исходящие")
        self._attach_context_menu(self.entry_sent)
        row += 1
        ttk.Label(main_frame, text="Фильтр домена для исходящих:").grid(row=row, column=0, sticky="w", **padding)
        self.entry_sent_domain = ttk.Entry(main_frame, width=30)
        self.entry_sent_domain.grid(row=row, column=1, **padding)
        self._attach_context_menu(self.entry_sent_domain)
        row += 1
        ttk.Label(main_frame, text="Фильтр домена для входящих:").grid(row=row, column=0, sticky="w", **padding)
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
        self.from_date_var.trace_add("write", lambda *args: self._on_date_change(self.from_date_var, "from", self.entry_from_date))
        self._attach_context_menu(self.entry_from_date)
        row += 1
        ttk.Label(main_frame, text="Дата по (YYYY-MM-DD):").grid(row=row, column=0, sticky="w", **padding)
        self.to_date_var = tk.StringVar()
        self.entry_to_date = ttk.Entry(main_frame, width=30, textvariable=self.to_date_var)
        self.entry_to_date.grid(row=row, column=1, **padding)
        self.to_date_var.trace_add("write", lambda *args: self._on_date_change(self.to_date_var, "to", self.entry_to_date))
        self._attach_context_menu(self.entry_to_date)
        row += 1
        self.btn_calc = ttk.Button(main_frame, text="Посчитать", command=self.on_calculate)
        self.btn_calc.grid(row=row, column=0, columnspan=2, pady=(10, 5))
        row += 1
        self.progress = ttk.Progressbar(main_frame, mode="determinate", length=260)
        self.progress.grid(row=row, column=0, columnspan=2, sticky="we", pady=(0, 6))
        row += 1
        self.label_status = ttk.Label(main_frame, text="Статус: готово")
        self.label_status.grid(row=row, column=0, columnspan=2, sticky="w", **padding)
        row += 1
        self.btn_cancel = ttk.Button(main_frame, text="Отмена", command=self.on_cancel)
        self.btn_cancel.grid(row=row, column=0, columnspan=2, pady=(0, 8))
        self.btn_cancel.config(state="disabled")
        row += 1
        self.label_result_inbox = ttk.Label(main_frame, text="Писем за период: -")
        self.label_result_inbox.grid(row=row, column=0, columnspan=2, sticky="w", **padding)
        row += 1
        self.label_result_sent = ttk.Label(main_frame, text="Проверено папок: -")
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
            print(f"Ошибка сохранения конфига: {e}")

    def _iter_mailboxes(self, mail, name_cache: dict | None = None):
        boxes = []

        def _try_list():
            for args in (None, ('', '*'), ('""', '*')):
                try:
                    if args is None:
                        typ, data = mail.list()
                    else:
                        typ, data = mail.list(*args)
                    if typ == "OK" and data:
                        return data
                except Exception:
                    continue
            return []
        data = _try_list()
        if not data:
            return boxes
        rx = re.compile(r'^\((?P<flags>[^)]*)\)\s+(?P<delim>NIL|"[^"]*")\s+(?P<name>.+)$', re.IGNORECASE)
        for raw in data:
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
            line = line.strip()
            m = rx.match(line)
            if not m:
                logging.info("LIST: не удалось разобрать строку: %r", line)
                continue
            flags_part = (m.group("flags") or "").strip()
            delim_tok = (m.group("delim") or "").strip()
            if delim_tok.upper() == "NIL":
                delim = None
            else:
                delim = delim_tok.strip('"')
            name_tok = (m.group("name") or "").strip()
            if len(name_tok) >= 2 and name_tok.startswith('"') and name_tok.endswith('"'):
                encoded_name = name_tok[1:-1]
            else:
                encoded_name = name_tok
            encoded_name = encoded_name.strip()
            if not encoded_name:
                continue
            if name_cache is not None and encoded_name in name_cache:
                decoded_name = name_cache.get(encoded_name) or decode_imap_utf7(encoded_name)
            else:
                decoded_name = decode_imap_utf7(encoded_name)
                if name_cache is not None:
                    name_cache[encoded_name] = decoded_name
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

    def _last_seg_upper(self, name: str) -> str:
        s = (name or "").strip()
        for sep in ("/", "\\", "."):
            if sep in s:
                s = s.split(sep)[-1]
        return s.strip().upper()

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
        if decoded_name in ("|", "|:") or (decoded_name or "").startswith("|:"):
            return True
        if self._is_drafts_folder(flags_part, decoded_name):
            return True
        if self._is_spam_folder(flags_part, decoded_name):
            return True
        if self._is_trash_folder(flags_part, decoded_name):
            return True
        return False


    def _select_main_folders(self, boxes: list[tuple[str, str, str, str]]) -> tuple[str | None, str | None]:
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
        if not host:
            messagebox.showerror("Ошибка", "Укажите IMAP хост.", parent=self)
            return
        if not username and not password:
            try:
                self.entry_username.focus_set()
            except Exception:
                pass
            messagebox.showerror("Ошибка", "Не заполнены логин и пароль.", parent=self)
            return
        if not username:
            try:
                self.entry_username.focus_set()
            except Exception:
                pass
            messagebox.showerror("Ошибка", "Не заполнен логин.", parent=self)
            return
        if not password:
            try:
                self.entry_password.focus_set()
            except Exception:
                pass
            messagebox.showerror("Ошибка", "Не заполнен пароль.", parent=self)
            return

        try:
            port = int(port_str)
        except ValueError:
            messagebox.showerror("Ошибка", "Порт должен быть числом.", parent=self)
            return
        cache_path = os.path.join(BASE_DIR, "mid_cache.json")
        cache_obj = None
        try:
            mail = connect_imap(host, port, username, password)
        except imaplib.IMAP4.error as e:
            messagebox.showerror("Ошибка подключения", f"Не удалось подключиться к почте.\n\nПричина: {e}", parent=self)
            return
        except Exception as e:
            messagebox.showerror("Ошибка подключения", f"Не удалось подключиться к почте.\n\nПричина: {e}", parent=self)
            return
        try:
            cache_path = os.path.join(BASE_DIR, "mid_cache.json")
            cache_obj = _load_mid_cache(cache_path)
            fn_all = cache_obj.get("folder_names")
            if not isinstance(fn_all, dict):
                fn_all = {}
                cache_obj["folder_names"] = fn_all
            fn_key = f"{host}|{username}"
            fn_map = fn_all.get(fn_key)
            if not isinstance(fn_map, dict):
                fn_map = {}
                fn_all[fn_key] = fn_map
            boxes = self._iter_mailboxes(mail, name_cache=fn_map)
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
                messagebox.showinfo("Результат", f"Определены папки:\nВходящие: {inbox_candidate}\nИсходящие: {sent_candidate}")
            elif inbox_candidate and not sent_candidate:
                messagebox.showinfo("Результат", "Папка входящих определена, исходящих не найдена.")
            elif sent_candidate and not inbox_candidate:
                messagebox.showinfo("Результат", "Папка исходящих определена, входящих не найдена.")
            else:
                messagebox.showinfo("Результат", "Не удалось автоматически определить папки.")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка при определении папок:\n{e}")
        finally:
            try:
                if cache_obj is not None:
                    _save_mid_cache(cache_path, cache_obj)
            except Exception:
                pass
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
            raise ValueError("При указании фильтра домена для исходящих нужно задать период (дата с и/или дата по).")
        if not from_date or not to_date:
            raise ValueError("Для ускорения работы нужно задать обе даты: 'Дата с' и 'Дата по'.")
        if from_date and to_date:
            d1 = datetime.strptime(from_date, "%Y-%m-%d")
            d2 = datetime.strptime(to_date, "%Y-%m-%d")
            if d1 > d2:
                raise ValueError("Дата 'с' не может быть позже даты 'по'.")
        return host, port, username, password, inbox_folder, sent_folder, from_date, to_date, sent_domain, inbox_domain

    def _display_folder_name(self, dn: str) -> str:
        s = (dn or "").strip()
        up = s.upper()
        if up == "INBOX":
            return "Входящие"
        for sep in ("/", "\\", "."):
            pref = "INBOX" + sep
            if up.startswith(pref):
                return "Входящие" + sep + s[len(pref):]
        return s

    def _set_busy(self, busy: bool, status: str | None = None) -> None:
        self._busy = busy
        self.btn_calc.config(state=("disabled" if busy else "normal"))
        self.btn_cancel.config(state=("normal" if busy else "disabled"))
        if status is not None:
            self.label_status.config(text=f"Статус: {status}")
        if not busy:
            try:
                self.progress["value"] = 0
            except Exception:
                pass

    def _update_progress(self, current: int, total: int, status: str | None = None) -> None:
        try:
            total = max(1, int(total))
            current = max(0, int(current))
            pct = min(100.0, (current / total) * 100.0)
            self.progress["value"] = pct
        except Exception:
            pass
        if status is not None:
            self.label_status.config(text=f"Статус: {status}")
        self.label_result_sent.config(text=f"Проверено папок: {current}/{total}")
        self.update_idletasks()

    def on_cancel(self) -> None:
        if not self._busy:
            return
        self._cancel_event.set()
        self.label_status.config(text="Статус: останавливаю расчёт")

    def _start_worker(self, target, args: tuple) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._cancel_event.clear()
        self._worker_thread = threading.Thread(target=target, args=args, daemon=True)
        self._worker_thread.start()

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
            messagebox.showerror("Ошибка", str(e), parent=self)
            return
        sent_domain_norm = sent_domain.strip() if sent_domain else None
        inbox_domain_norm = inbox_domain.strip() if inbox_domain else None
        inbox_cfg_ui = (self.entry_inbox.get() or "").strip()
        sent_cfg_ui = (self.entry_sent.get() or "").strip()
        self.label_result_inbox.config(text="Писем за период: считаю")
        self.label_result_sent.config(text="Проверено папок: 0/0")
        try:
            self.progress["value"] = 0
        except Exception:
            pass
        self._set_busy(True, status="подключаюсь к почте")
        self._start_worker(
            self._calculate_worker,
            (host, port, username, password, from_date, to_date,
             sent_domain_norm, inbox_domain_norm, inbox_cfg_ui, sent_cfg_ui),
        )

    def _calculate_worker(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        from_date: str,
        to_date: str,
        sent_domain_norm: str | None,
        inbox_domain_norm: str | None,
        inbox_cfg_ui: str,
        sent_cfg_ui: str,
    ) -> None:
        mail = None
        cache_path = os.path.join(BASE_DIR, "mid_cache.json")
        cache_obj = _load_mid_cache(cache_path)
        folders_cache = cache_obj.get("folders")
        if not isinstance(folders_cache, dict):
            folders_cache = {}
            cache_obj["folders"] = folders_cache
        folder_names_all = cache_obj.get("folder_names")
        if not isinstance(folder_names_all, dict):
            folder_names_all = {}
            cache_obj["folder_names"] = folder_names_all
        fn_key = f"{host}|{username}"
        folder_names = folder_names_all.get(fn_key)
        if not isinstance(folder_names, dict):
            folder_names = {}
            folder_names_all[fn_key] = folder_names
        try:
            mail = connect_imap(host, port, username, password, timeout=30.0)
            _before_fn_len = len(folder_names)
            boxes = self._iter_mailboxes(mail, name_cache=folder_names)
            _after_fn_len = len(folder_names)
            main_inbox, main_sent = self._select_main_folders(boxes)

            enc_to_dec: dict[str, str] = {}
            enc_to_flags: dict[str, str] = {}
            for flags, dn, en, _dl in boxes:
                if en:
                    enc_to_dec[en] = dn or en
                    enc_to_flags[en] = flags or ""

            def check_cancel() -> None:
                if self._cancel_event.is_set():
                    raise RuntimeError("Отменено пользователем.")
            inbox_list: list[tuple[str, str]] = []
            sent_list: list[tuple[str, str]] = []
            if main_inbox:
                inbox_list = self._collect_descendants(boxes, main_inbox)
            if main_sent:
                sent_list = self._collect_descendants(boxes, main_sent)

            def _uniq_by_enc(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
                seen_enc: set[str] = set()
                out: list[tuple[str, str]] = []
                for dn, en in pairs:
                    if not en or en in seen_enc:
                        continue
                    seen_enc.add(en)
                    out.append((dn, en))
                return out
            inbox_list = _uniq_by_enc(inbox_list)
            sent_list = _uniq_by_enc(sent_list)
            inbox_list = [(dn, en) for dn, en in inbox_list if not self._should_skip_folder(enc_to_flags.get(en, ""), dn)]
            sent_list = [(dn, en) for dn, en in sent_list if not self._should_skip_folder(enc_to_flags.get(en, ""), dn)]
            total_folders = max(1, len(inbox_list) + len(sent_list))
            processed = 0

            def tick(status: str | None = None) -> None:
                self.after(0, lambda: self._update_progress(processed, total_folders, status))

            self.after(0, lambda: self.label_status.config(text="Статус: считаю письма за выбранный период"))
            tick()
            global_seen: set[str] = set()
            seen_inbox: set[str] = set()
            seen_sent: set[str] = set()
            unique_inbox = 0
            unique_sent = 0
            multi_to_by_key: dict[str, dict] = {}

            def build_inbox_criteria(domain: str | None) -> list[str] | None:
                if not domain:
                    return None
                return ["FROM", domain]

            def build_sent_criteria(domain: str | None) -> list[str] | None:
                if not domain:
                    return None
                dom = (domain or "").strip()
                if dom and not dom.startswith("@"):
                    dom = "@" + dom
                return ["OR", "TO", dom, "OR", "CC", dom, "BCC", dom]

            def ensure_folder_cache(enc_folder: str) -> dict:
                cache_key = f"{host}|{username}|{enc_folder}"
                entry = folders_cache.get(cache_key)
                if not isinstance(entry, dict):
                    entry = {}
                    folders_cache[cache_key] = entry
                uidv = _get_uidvalidity(mail, enc_folder)
                if uidv and entry.get("uidvalidity") != uidv:
                    entry["uidvalidity"] = uidv
                    entry["map"] = {}
                if "map" not in entry or not isinstance(entry.get("map"), dict):
                    entry["map"] = {}
                return entry

            def process_folder(kind: str, dec_name: str, enc_name: str) -> None:
                nonlocal processed, unique_inbox, unique_sent
                check_cancel()
                try:
                    if kind == "inbox":
                        extra = build_inbox_criteria(inbox_domain_norm)
                        use_sent_date = False
                    else:
                        extra = build_sent_criteria(sent_domain_norm)
                        use_sent_date = False
                    cnt = search_count(
                        mail,
                        enc_name,
                        from_date,
                        to_date,
                        extra_criteria=extra,
                        include_deleted=False,
                        use_sent_date=use_sent_date,
                    )
                    if kind == "sent" and sent_domain_norm and cnt == 0:
                        try:
                            cnt2 = search_count(
                                mail,
                                enc_name,
                                from_date,
                                to_date,
                                extra_criteria=extra,
                                include_deleted=False,
                                use_sent_date=True,
                            )
                            if cnt2:
                                cnt = cnt2
                                use_sent_date = True
                        except Exception:
                            pass
                    if int(cnt) <= 0:
                        return
                    uids_b = search_uids(
                        mail,
                        enc_name,
                        from_date,
                        to_date,
                        extra_criteria=extra,
                        include_deleted=False,
                        use_sent_date=use_sent_date,
                    )
                    if not uids_b:
                        return
                    entry = ensure_folder_cache(enc_name)
                    mp: dict = entry.get("map", {})
                    uids = []
                    missing = []
                    for ub in uids_b:
                        uid = ub.decode("ascii", "ignore") if isinstance(ub, (bytes, bytearray)) else str(ub)
                        uid = uid.strip()
                        if not uid:
                            continue
                        uids.append(uid)
                        if uid not in mp:
                            missing.append(uid)
                    if missing:
                        missing_b = [x.encode("ascii", "ignore") for x in missing]
                        got = fetch_message_id_map(mail, missing_b, step=800)
                        for uid, key in got.items():
                            if key:
                                mp[uid] = key
                    entry["map"] = mp
                    headers_map = None
                    if kind == "inbox":
                        try:
                            headers_map = fetch_from_to_map(mail, uids_b, step=400)
                        except Exception:
                            headers_map = None

                    def _fmt_addrs(header_val: str) -> list[str]:
                        items = []
                        me = (username or "").strip().lower()
                        try:
                            for nm, addr in getaddresses([header_val or ""]):
                                nm = (nm or "").strip().strip('"')
                                addr = (addr or "").strip()
                                if not addr and not nm:
                                    continue
                                if addr and nm:
                                    items.append(f"{nm} <{addr}>")
                                elif addr:
                                    items.append(addr)
                                else:
                                    items.append(nm)
                        except Exception:
                            pass
                        return items
                    for uid in uids:
                        raw_key = mp.get(uid) or ("uid:" + uid)
                        if isinstance(raw_key, str) and raw_key.startswith("uid:"):
                            uidv_cur = (entry.get("uidvalidity") or "").strip()
                            key = f"{enc_name}|{uidv_cur}|{raw_key}"
                        else:
                            key = raw_key
                        if key not in global_seen:
                            global_seen.add(key)
                        if kind == "inbox":
                            if key in seen_inbox:
                                continue
                            seen_inbox.add(key)
                            unique_inbox += 1
                        else:
                            if key in seen_sent:
                                continue
                            seen_sent.add(key)
                            unique_sent += 1
                        if kind == "inbox" and headers_map is not None and key not in multi_to_by_key:
                            try:
                                from_h, to_h = headers_map.get(uid, ("", ""))
                                to_items = _fmt_addrs(to_h)
                                if len(to_items) > 1:
                                    multi_to_by_key[key] = {
                                        "account": username,
                                        "folder": self._display_folder_name(dec_name),
                                        "from": (from_h or "").strip(),
                                        "to": to_items,
                                        "kind": kind,
                                    }
                            except Exception:
                                pass
                finally:
                    processed += 1
                    if kind == "inbox":
                        tick(f"Проверяю папку «{self._display_folder_name(dec_name)}» (входящие)")
                    else:
                        tick(f"Проверяю папку «{self._display_folder_name(dec_name)}» (исходящие)")
            for dec_name, enc_name in inbox_list:
                process_folder("inbox", dec_name, enc_name)
            for dec_name, enc_name in sent_list:
                process_folder("sent", dec_name, enc_name)
            total_unique = unique_inbox + unique_sent
            label_line = f"Писем за период: {total_unique}"
            title = "Результат"
            inbox_filter_note = ""
            if inbox_domain_norm:
                inbox_filter_note = f" (фильтр: FROM {inbox_domain_norm})"
            sent_filter_note = ""
            if sent_domain_norm:
                _sd = sent_domain_norm.strip()
                if _sd and not _sd.startswith("@"):
                    _sd = "@" + _sd
                sent_filter_note = f" (фильтр: TO/CC/BCC {_sd})"
            msg_lines = [
                f"Всего уникальных писем за период: {total_unique}",
                f"Уникальные входящие{inbox_filter_note}: {unique_inbox}",
                f"Уникальные исходящие{sent_filter_note}: {unique_sent}",
            ]
            if multi_to_by_key:
                msg_lines.append("")
                msg_lines.append("Входящие письма, где в поле 'Кому' более одного адреса:")
                for _k, rec in multi_to_by_key.items():
                    frm = (rec.get("from") or "").strip() or "(не указано)"
                    folder = (rec.get("folder") or "").strip()
                    to_list = rec.get("to") or []
                    to_s = "; ".join(str(x) for x in to_list) if to_list else "(не указано)"
                    acc = (rec.get("account") or "").strip()
                    if folder:
                        msg_lines.append(f"- Ящик: {acc} | Папка: {folder} | От: {frm} | Кому: {to_s}")
                    else:
                        msg_lines.append(f"- Ящик: {acc} | От: {frm} | Кому: {to_s}")

            result = {
                "ok": True,
                "username": username,
                "from_date": from_date,
                "to_date": to_date,
                "title": title,
                "message": "\n".join(msg_lines),
                "label_line": label_line,
                "folders_processed": len(inbox_list) + len(sent_list),
                "multi_to": list(multi_to_by_key.values()),
            }
            _save_mid_cache(cache_path, cache_obj)
            self.after(0, lambda r=result: self._finish_calculation(r))
        except Exception as e:
            logging.exception("Ошибка расчёта")
            result = {
                "ok": False,
                "error": str(e),
                "trace": traceback.format_exc(),
            }
            self.after(0, lambda r=result: self._finish_calculation(r))
        finally:
            try:
                _save_mid_cache(cache_path, cache_obj)
            except Exception:
                pass
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
                self.after(0, lambda: self._set_busy(False))

    def _show_result_window(
        self,
        title: str,
        summary_text: str,
        multi_to: list[dict] | None,
        report_path: str | None,
    ) -> None:
        win = tk.Toplevel(self)
        win.title(title or "Результат")
        win.resizable(True, True)
        win.transient(self)
        try:
            win.geometry("980x640")
        except Exception:
            pass
        outer = ttk.Frame(win, padding=10)
        outer.pack(fill="both", expand=True)
        lbl = ttk.Label(outer, text=summary_text, justify="left")
        lbl.pack(anchor="w", fill="x")
        if report_path:
            ttk.Label(outer, text=f"Отчёт сохранён: {report_path}", justify="left").pack(anchor="w", pady=(6, 0))
        ttk.Separator(outer, orient="horizontal").pack(fill="x", pady=(10, 10))
        if not multi_to:
            btn = ttk.Button(outer, text="OK", command=win.destroy)
            btn.pack(anchor="e", pady=(10, 0))
            win.grab_set()
            win.focus_set()
            return
        ttk.Label(
            outer,
            text="Входящие",
            justify="left",
        ).pack(anchor="w")
        tree_frame = ttk.Frame(outer)
        tree_frame.pack(fill="both", expand=True, pady=(6, 0))
        cols = ("folder",)
        tree = ttk.Treeview(tree_frame, columns=cols, show="tree headings")
        tree.heading("#0", text="Отправитель | Получатели")
        tree.heading("folder", text="Папка")
        tree.column("#0", width=720, stretch=True)
        tree.column("folder", width=220, stretch=False)
        ysb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        xsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        for rec in multi_to:
            frm = (rec.get("from") or "").strip() or "(не указано)"
            folder = (rec.get("folder") or "").strip()
            to_list = rec.get("to") or []
            acc = (rec.get("account") or "").strip()
            parent_text = f"Ящик: {acc} | От: {frm} | Кому: {len(to_list)} адрес(а/ов)"
            pid = tree.insert("", "end", text=parent_text, values=(folder,))
            for addr in to_list:
                tree.insert(pid, "end", text=str(addr), values=("",))
        btns = ttk.Frame(outer)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="OK", command=win.destroy).pack(side="right")
        self.update_idletasks()
        win.update_idletasks()
        try:
            px = self.winfo_rootx()
            py = self.winfo_rooty()
            pw = self.winfo_width()
            ph = self.winfo_height()
            dw = win.winfo_width()
            dh = win.winfo_height()
            x = px + max(0, (pw - dw) // 2)
            y = py + max(0, (ph - dh) // 2)
            win.geometry(f"+{x}+{y}")
        except Exception:
            pass
        win.grab_set()
        win.focus_set()


    def _finish_calculation(self, result: dict) -> None:
        try:
            if result.get("ok"):
                self.label_result_inbox.config(text=result.get("label_line", "Всего писем: -"))
                self.label_result_sent.config(text=f"Проверено папок: {result.get('folders_processed', 0)}")
                self.label_status.config(text="Статус: готово")
                try:
                    self.progress["value"] = 100
                except Exception:
                    pass
                full_msg = result.get("message", "")
                report_path = save_full_report(
                    title=result.get("title", "Результат"),
                    message=full_msg,
                    username=result.get("username"),
                    from_date=result.get("from_date"),
                    to_date=result.get("to_date"),
                )
                msg = full_msg or ""
                if report_path:
                    msg = (msg.rstrip() + "\n\nОтчёт сохранён: " + report_path + "\n")

                multi_to = result.get("multi_to") or None
                if multi_to:
                    try:
                        summary_lines = (full_msg or "").splitlines()[:3]
                    except Exception:
                        summary_lines = []
                    summary_text = "\n".join(summary_lines).strip() or (result.get("title", "Результат") or "Результат")
                    self._show_result_window(result.get("title", "Результат"), summary_text, multi_to, report_path)
                else:
                    messagebox.showinfo(result.get("title", "Результат"), msg, parent=self)
            else:
                err_raw = result.get("error", "Неизвестная ошибка")
                self.label_status.config(text="Статус: ошибка")
                self.label_result_inbox.config(text="Писем за период: ошибка")
                self.label_result_sent.config(text="Проверено папок: ошибка")
                trace = result.get("trace", "")
                full_for_report = err_raw + ("\n\n" + trace if trace else "")
                report_path = save_full_report(
                    title="Ошибка",
                    message=full_for_report,
                    username=result.get("username"),
                    from_date=result.get("from_date"),
                    to_date=result.get("to_date"),
                )
                err_ui = (
                    "Не получилось посчитать письма.\n\n"
                    f"Причина: {err_raw}\n\n"
                    "Что можно сделать:\n"
                    "1) Проверь логин и пароль\n"
                    "2) Убедись, что IMAP включён в настройках почты\n"
                    "3) Попробуй уменьшить период (например, 7–14 дней)\n"
                    "4) Если ошибка повторяется — пришли файл отчёта"
                )
                if report_path:
                    err_ui += "\n\nОтчёт сохранён: " + report_path
                messagebox.showerror("Ошибка", err_ui, parent=self)
        finally:
            self._set_busy(False)
            self._save_config()

    def on_close(self) -> None:
        self._save_config()
        self.destroy()

if __name__ == "__main__":
    ensure_required_files()
    app = MailStatsUI()
    app.mainloop()

# pyinstaller --noconfirm --clean --onefile --windowed --name KOLORVRAT_new_For_Sergey --add-data "mid_cache.json;." --add-data "mailsettings.json;." --add-data "imap_hosts.csv;." --add-data "accounts.csv;." --add-data "Отчеты;Отчеты" --collect-submodules openpyxl --collect-data openpyxl KOLORVRAT_new_For_Sergey.py