import os
import sys
import json
import re
import string
import random
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import webbrowser
import base64
import pyperclip
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend


# ------------------ config_manager.py ------------------
def get_app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(sys.argv[0]))


def create_default_config():
    config_path = os.path.join(get_app_dir(), "config.json")
    if not os.path.exists(config_path):
        default_config = {
            "salt_file": "salt.bin",
            "max_password_length": 32,
            "default_length": 18,
            "use_uppercase": True,
            "use_lowercase": True,
            "use_digits": True,
            "use_symbols": True,
            "excluded_chars": "O0DQl1I|i!S5Z2B8G6CGceaouvwxX",
            "passwords_file": "passwords.json",
        }
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=4)
        except Exception as e:
            print(f"Ошибка создания конфигурации: {str(e)}")


# ------------------ password_generator.py ------------------
class PasswordGenerator:
    def __init__(self):
        self.password_length = 15
        self.use_uppercase = True
        self.use_lowercase = True
        self.use_digits = True
        self.use_symbols = True
        self.excluded_chars = ""
        self.load_config()

    def load_config(self):
        config_path = os.path.join(get_app_dir(), "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    if "max_password_length" in config:
                        self.max_password_length = config["max_password_length"]
                    if "default_length" in config:
                        self.password_length = config["default_length"]
                    if "use_uppercase" in config:
                        self.use_uppercase = config["use_uppercase"]
                    if "use_lowercase" in config:
                        self.use_lowercase = config["use_lowercase"]
                    if "use_digits" in config:
                        self.use_digits = config["use_digits"]
                    if "use_symbols" in config:
                        self.use_symbols = config["use_symbols"]
                    if "excluded_chars" in config:
                        self.excluded_chars = config["excluded_chars"]
            except Exception as e:
                print(f"Ошибка загрузки конфигурации: {str(e)}")
        else:
            self.max_password_length = 32
            create_default_config()
            self.load_config()

    def generate_password(self):
        char_sets = []
        if self.use_uppercase:
            char_sets.append(string.ascii_uppercase)
        if self.use_lowercase:
            char_sets.append(string.ascii_lowercase)
        if self.use_digits:
            char_sets.append(string.digits)
        if self.use_symbols:
            char_sets.append(string.punctuation)
        if not char_sets:
            return ""
        charset = "".join(char_sets)
        for char in self.excluded_chars:
            charset = charset.replace(char, "")
        if not charset:
            return ""
        password = []
        for char_set in char_sets:
            valid_chars = "".join(c for c in char_set if c not in self.excluded_chars)
            if valid_chars:
                password.append(random.choice(valid_chars))
        remaining_length = max(0, self.password_length - len(password))
        if remaining_length > 0:
            password += random.choices(charset, k=remaining_length)
        random.shuffle(password)
        return "".join(password)

    def evaluate_password_strength(self, password):
        score = 0
        if len(password) >= 8:
            score += 10
        if len(password) >= 12:
            score += 10
        if len(password) >= 16:
            score += 10
        if re.search(r"[A-Z]", password):
            score += 10
        if re.search(r"[a-z]", password):
            score += 10
        if re.search(r"[0-9]", password):
            score += 10
        if re.search(r"[^A-Za-z0-9]", password):
            score += 10
        if not re.search(r"(.)\1\1", password):
            score += 10
        unique_chars = len(set(password))
        score += min(20, unique_chars * 2)
        if re.search(r"[A-Z].*[0-9]|[0-9].*[A-Z]", password) and re.search(
            r"[a-z].*[0-9]|[0-9].*[a-z]", password
        ):
            score += 10
        return min(100, score)


# ------------------ password_manager.py ------------------
class PasswordManager:
    def __init__(self, master_password=None):
        self.master_password = master_password
        self.passwords = []
        self.key = None
        self.salt = None
        self._create_default_config()
        self.load_config()
        if self.master_password:
            self._initialize_encryption()
        self.load_passwords()

    def backup_passwords(self):
        backup_dir = os.path.join(get_app_dir(), "backups")
        backup_filename = os.path.join(backup_dir, "backup_passwords.bin")
        os.makedirs(backup_dir, exist_ok=True)
        try:
            data = json.dumps(self.passwords, indent=4, ensure_ascii=False)
            with open(backup_filename, "w", encoding="utf-8") as backup_file:
                backup_file.write(data)
            return True, f"Резервная копия создана: {backup_filename}"
        except Exception as e:
            return False, f"Ошибка резервного копирования: {str(e)}"

    def regenerate_salt(self, master_password):
        new_salt = os.urandom(16)
        backup_passwords = self.get_all_passwords()
        try:
            with open("salt.bin", "wb") as salt_file:
                salt_file.write(new_salt)
            self.salt = new_salt
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=self.salt,
                iterations=100000,
                backend=default_backend(),
            )
            key = kdf.derive(master_password.encode())
            self.key = base64.urlsafe_b64encode(key)
            self.passwords = []
            for item in backup_passwords:
                self.add_password(
                    item["password"],
                    item["description"],
                    item.get("tags", []),
                    item.get("url", ""),
                )
            return True, "Соль успешно обновлена. Все пароли перешифрованы."
        except Exception as e:
            self.passwords = backup_passwords
            return False, f"Ошибка обновления соли: {str(e)}"

    def _initialize_encryption(self):
        if not os.path.exists("salt.bin"):
            self.salt = os.urandom(16)
            with open("salt.bin", "wb") as salt_file:
                salt_file.write(self.salt)
        else:
            with open("salt.bin", "rb") as salt_file:
                self.salt = salt_file.read()
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self.salt,
            iterations=100000,
            backend=default_backend(),
        )
        key = kdf.derive(self.master_password.encode())
        self.key = base64.urlsafe_b64encode(key)

    def encrypt(self, data):
        fernet = Fernet(self.key)
        return fernet.encrypt(data.encode()).decode()

    def decrypt(self, encrypted_data):
        fernet = Fernet(self.key)
        return fernet.decrypt(encrypted_data.encode()).decode()

    def load_config(self):
        config_path = os.path.join(get_app_dir(), "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    if "passwords_file" in config:
                        self.filename = config["passwords_file"]
                    else:
                        self.filename = os.path.join(get_app_dir(), "passwords.json")
            except Exception as e:
                self.filename = os.path.join(get_app_dir(), "passwords.json")
        else:
            self.filename = os.path.join(get_app_dir(), "passwords.json")

    def add_password(self, password, description, tags=None, url=None):
        encrypted_password = self.encrypt(password)
        self.passwords.append(
            {
                "password": encrypted_password,
                "description": description.strip(),
                "tags": tags or [],
                "url": url.strip() if url else "",
                "encrypted": True,
            }
        )
        self._save_passwords()
        return True

    def _create_default_config(self):
        config_path = os.path.join(get_app_dir(), "config.json")
        if not os.path.exists(config_path):
            default_config = {
                "max_password_length": 32,
                "default_length": 15,
                "use_uppercase": True,
                "use_lowercase": True,
                "use_digits": True,
                "use_symbols": True,
                "excluded_chars": "1l0Oo|",
                "passwords_file": "passwords.json",
            }
            try:
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(default_config, f, indent=4)
            except Exception as e:
                print(f"Ошибка создания конфигурации: {str(e)}")

    def update_password(self, index, password, description, tags=None, url=None):
        if 0 <= index < len(self.passwords):
            encrypted_password = self.encrypt(password)
            self.passwords[index] = {
                "password": encrypted_password,
                "description": description,
                "tags": tags or [],
                "url": url.strip() if url else "",
                "encrypted": True,
            }
            self._save_passwords()
            return True
        return False

    def export_to_txt(self, filename):
        try:
            decrypted_passwords = self.get_all_passwords()
            with open(filename, "w", encoding="utf-8") as f:
                for pwd in decrypted_passwords:
                    f.write(f"Описание: {pwd['description']}\n")
                    f.write(f"Пароль: {pwd['password']}\n")
                    f.write(f"Теги: {', '.join(pwd['tags'])}\n")
                    f.write(f"URL: {pwd.get('url', '')}\n")
                    f.write("-" * 40 + "\n")
            return True, "Пароли успешно экспортированы"
        except Exception as e:
            return False, f"Ошибка экспорта: {str(e)}"

    def import_from_txt(self, filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                content = f.read().strip()
            password_blocks = []
            current_block = []
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("-----") or line == "":
                    if current_block:
                        password_blocks.append("\n".join(current_block))
                        current_block = []
                else:
                    current_block.append(line)
            if current_block:
                password_blocks.append("\n".join(current_block))
            imported_data = []
            for block in password_blocks:
                password_info = {"description": "", "password": "", "tags": []}
                lines = block.strip().split("\n")
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    if ":" in line:
                        key_part, value_part = line.split(":", 1)
                        key = key_part.strip().lower()
                        value = value_part.strip()
                        if key.startswith("опис"):
                            password_info["description"] = value
                        elif key.startswith("парол"):
                            password_info["password"] = value
                        elif key.startswith("url"):
                            password_info["url"] = value
                        elif key.startswith("тег"):
                            tags = [
                                t.strip() for t in re.split(r"[,;]", value) if t.strip()
                            ]
                            password_info["tags"] = tags
                if password_info["description"] and password_info["password"]:
                    imported_data.append(password_info)
                else:
                    print(f"Пропущен неполный блок: {block[:50]}...")
            if not imported_data:
                return False, "Не удалось найти валидные пароли в файле"
            imported_count = 0
            existing_descriptions = {p["description"] for p in self.passwords}
            for item in imported_data:
                if item["description"] in existing_descriptions:
                    print(f"Пропущен дубликат: {item['description']}")
                    continue
                encrypted_password = self.encrypt(item["password"])
                self.passwords.append(
                    {
                        "password": encrypted_password,
                        "description": item["description"],
                        "tags": item.get("tags", []),
                        "url": item.get("url", ""),
                        "encrypted": True,
                    }
                )
                imported_count += 1
            self._save_passwords()
            return True, f"Успешно импортировано {imported_count} паролей"
        except Exception as e:
            return False, f"Ошибка импорта: {str(e)}"

    def delete_password(self, index):
        if 0 <= index < len(self.passwords):
            del self.passwords[index]
            self._save_passwords()
            return True
        return False

    def get_password(self, index):
        if 0 <= index < len(self.passwords):
            item = self.passwords[index]
            try:
                return {
                    "password": self.decrypt(item["password"]),
                    "description": item["description"],
                    "tags": item.get("tags", []),
                    "url": item.get("url", ""),
                }
            except:
                return {"error": "Неверный мастер-пароль для расшифровки"}
        return None

    def get_all_passwords(self):
        return [
            {
                "password": self.decrypt(p["password"]),
                "description": p["description"],
                "tags": p.get("tags", []),
                "url": p.get("url", ""),
            }
            for p in self.passwords
        ]

    def load_passwords(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r", encoding="utf-8") as f:
                    self.passwords = json.load(f)
                if self.passwords:
                    test_item = self.passwords[0]
                    self.decrypt(test_item["password"])
                if self.key and any(
                    not p.get("encrypted", False) for p in self.passwords
                ):
                    self._migrate_old_passwords()
            except (InvalidToken, json.JSONDecodeError):
                self.passwords = []
            except Exception:
                self.passwords = []

    def _save_passwords(self):
        data = [
            {
                "password": p["password"],
                "description": p["description"],
                "tags": p.get("tags", []),
                "url": p.get("url", ""),
                "encrypted": True,
            }
            for p in self.passwords
        ]
        try:
            with open(self.filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                self.backup_passwords()
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка сохранения: {str(e)}")

    def _migrate_old_passwords(self):
        migrated = False
        for item in self.passwords:
            if not item.get("encrypted", False):
                try:
                    item["password"] = self.encrypt(item["password"])
                    item["encrypted"] = True
                    migrated = True
                except Exception as e:
                    messagebox.showerror(
                        "Ошибка шифрования",
                        f"Не удалось зашифровать пароль для '{item['description']}': {str(e)}",
                    )
        if migrated:
            self._save_passwords()
            messagebox.showinfo(
                "Миграция", "Существующие пароли были успешно зашифрованы"
            )

    def change_master_password(self, old_password, new_password):
        if old_password != self.master_password:
            return False, "Неверный текущий мастер-пароль"
        decrypted_passwords = []
        try:
            for item in self.passwords:
                decrypted_password = (
                    self.decrypt(item["password"])
                    if item.get("encrypted", False)
                    else item["password"]
                )
                decrypted_passwords.append(
                    {
                        "password": decrypted_password,
                        "description": item["description"],
                        "tags": item.get("tags", []),
                        "url": item.get("url", ""),
                    }
                )
        except Exception as e:
            return False, f"Ошибка расшифровки паролей: {str(e)}"
        self.master_password = new_password
        self._initialize_encryption()
        self.passwords = []
        for item in decrypted_passwords:
            self.add_password(
                item["password"], item["description"], item["tags"], item.get("url", "")
            )
        return True, "Мастер-пароль успешно изменен"


# ------------------ authentication.py ------------------
class AuthenticationDialog(tk.Toplevel):
    def __init__(self, parent, title="Аутентификация"):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.grab_set()
        self.parent = parent
        self.result = None
        self.master_password = None
        self.max_attempts = 3
        self.attempts = 0
        self._setup_ui()
        self._center_window()
        self.protocol("WM_DELETE_WINDOW", self._safe_destroy)
        self.after(100, lambda: self.parent.focus_force())

    def _center_window(self):
        self.update_idletasks()
        parent_x = self.parent.winfo_x()
        parent_y = self.parent.winfo_y()
        parent_width = self.parent.winfo_width()
        parent_height = self.parent.winfo_height()
        width = self.winfo_width()
        height = self.winfo_height()
        x = parent_x + (parent_width - width) // 2
        y = parent_y + (parent_height - height) // 2
        if parent_width == 1 or parent_height == 1:
            screen_width = self.winfo_screenwidth()
            screen_height = self.winfo_screenheight()
            x = (screen_width - width) // 2
            y = (screen_height - height) // 2
        self.geometry(f"+{x}+{y}")

    def _setup_ui(self):
        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            main_frame, text="Введите мастер-пароль для шифрования/расшифрования:"
        ).pack(pady=(0, 10))
        self.password_var = tk.StringVar()
        self.password_entry = ttk.Entry(
            main_frame, textvariable=self.password_var, show="*", width=30
        )
        self.password_entry.pack(pady=(0, 10), fill=tk.X)
        self.password_entry.focus_force()
        self.attempts_label = ttk.Label(main_frame, text="", foreground="red")
        self.attempts_label.pack(pady=(0, 10), fill=tk.X)
        buttons_frame = ttk.Frame(main_frame)
        buttons_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(buttons_frame, text="ОК", command=self._on_ok).pack(
            side=tk.RIGHT, padx=5
        )
        ttk.Button(buttons_frame, text="Отмена", command=self._on_cancel).pack(
            side=tk.RIGHT, padx=5
        )
        self.bind("<Return>", lambda event: self._on_ok())
        self.minsize(300, 150)
        self.show_password_var = tk.BooleanVar(value=False)
        checkbox_frame = ttk.Frame(main_frame)
        checkbox_frame.pack(fill=tk.X, pady=(0, 10))
        self.show_password_var = tk.BooleanVar(value=False)
        self.show_checkbutton = ttk.Checkbutton(
            checkbox_frame,
            text="Показать пароль",
            variable=self.show_password_var,
            command=self._toggle_password_visibility,
        )
        self.show_checkbutton.pack(side=tk.LEFT, anchor=tk.W)
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(
            label="Вставить", command=self._paste_from_clipboard
        )
        self.password_entry.bind("<Button-3>", self._show_context_menu)

    def _toggle_password_visibility(self):
        show = self.show_password_var.get()
        self.password_entry.config(show="" if show else "*")

    def _paste_from_clipboard(self):
        try:
            self.password_entry.delete(0, tk.END)
            self.password_entry.insert(0, pyperclip.paste())
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось вставить из буфера: {str(e)}")

    def _show_context_menu(self, event):
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def _validate_master_password(self, password):
        try:
            if os.path.exists("passwords.json"):
                with open("passwords.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data:
                        test_item = data[0]
                        fernet = Fernet(self._generate_key(password))
                        fernet.decrypt(test_item["password"].encode())
            return True
        except Exception:
            return False

    def _generate_key(self, password):
        with open("salt.bin", "rb") as salt_file:
            salt = salt_file.read()
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend(),
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return key

    def _on_ok(self):
        password = self.password_var.get()
        if not password:
            messagebox.showerror("Ошибка", "Пароль не может быть пустым")
            return
        self.attempts += 1
        try:
            if self._validate_master_password(password):
                self.master_password = password
                self.result = True
                if self.winfo_exists():
                    self.destroy()
            else:
                remaining = self.max_attempts - self.attempts
                if remaining > 0:
                    self.attempts_label.config(
                        text=f"Неверный пароль. Осталось попыток: {remaining}"
                    )
                    self.password_var.set("")
                    self.password_entry.focus_set()
                else:
                    if self.parent.winfo_exists():
                        self.parent.destroy()
                    self.destroy()
        except Exception as e:
            if self.parent.winfo_exists():
                self.parent.destroy()
            self.destroy()

    def _on_cancel(self):
        self.result = False
        self.destroy()
        self.parent.grab_release()

    def _safe_destroy(self):
        self.result = False
        self.destroy()
        self.parent.focus_set()


# ------------------ dialogs.py (весь код, только классы) ------------------
class BasePasswordDialog(tk.Toplevel):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.grab_set()
        self.parent = parent
        self.result = None
        self._setup_ui()
        self._center_window()

    def _center_window(self):
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"+{x}+{y}")

    def _setup_ui(self):
        raise NotImplementedError("Subclasses must implement _setup_ui")


class PasswordDialog(BasePasswordDialog):
    def __init__(self, parent, title, password_data=None):
        self.password_data = password_data or {
            "description": "",
            "password": "",
            "tags": [],
            "url": "",
        }
        super().__init__(parent, title)
        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        ttk.Label(self, text="Описание:").grid(
            row=0, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.description_entry = ttk.Entry(self, width=30)
        self.description_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        ttk.Label(self, text="Пароль:").grid(
            row=1, column=0, padx=5, pady=5, sticky=tk.W
        )
        password_frame = ttk.Frame(self)
        password_frame.grid(row=1, column=1, padx=5, pady=5, sticky=tk.EW)
        self.password_entry = ttk.Entry(password_frame, width=25, show="*")
        self.password_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.paste_button = ttk.Button(
            password_frame,
            text="Вст.",
            command=self._paste_from_clipboard,
            style="Small.TButton",
        )
        self.paste_button.pack(side=tk.RIGHT, padx=2, ipady=0)
        self.password_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=2)
        style = ttk.Style()
        style.configure("Small.TButton", width=6, font=("Arial", 8), padding=(1, 1))
        ttk.Label(self, text="Теги:").grid(row=2, column=0, padx=5, pady=5, sticky=tk.W)
        self.tags_entry = ttk.Entry(self, width=30)
        self.tags_entry.grid(row=2, column=1, padx=5, pady=5, sticky=tk.EW)
        ttk.Label(self, text="URL:").grid(row=3, column=0, padx=5, pady=5, sticky=tk.W)
        self.url_entry = ttk.Entry(self, width=30)
        self.url_entry.grid(row=3, column=1, padx=5, pady=5, sticky=tk.EW)
        self.show_password_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self,
            text="Показать пароль",
            variable=self.show_password_var,
            command=self._toggle_password_visibility,
        ).grid(row=4, column=1, padx=5, pady=5, sticky=tk.E)
        button_frame = ttk.Frame(self)
        button_frame.grid(row=5, column=0, columnspan=2, pady=10)
        ttk.Button(button_frame, text="Сохранить", command=self._save).pack(
            side=tk.RIGHT, padx=5
        )
        ttk.Button(button_frame, text="Отмена", command=self.destroy).pack(
            side=tk.RIGHT
        )

    def _load_data(self):
        self.description_entry.insert(0, self.password_data.get("description", ""))
        self.password_entry.insert(0, self.password_data.get("password", ""))
        self.tags_entry.insert(0, ", ".join(self.password_data.get("tags", [])))
        self.url_entry.insert(0, self.password_data.get("url", ""))

    def _toggle_password_visibility(self):
        show = self.show_password_var.get()
        self.password_entry.config(show="" if show else "*")

    def _paste_from_clipboard(self):
        try:
            self.password_entry.delete(0, tk.END)
            self.password_entry.insert(0, pyperclip.paste())
        except Exception as e:
            tk.messagebox.showerror(
                "Ошибка", f"Не удалось вставить из буфера: {str(e)}"
            )

    def _save(self):
        description = self.description_entry.get()
        password = self.password_entry.get()
        url = self.url_entry.get().strip()
        tags = [tag.strip() for tag in self.tags_entry.get().split(",") if tag.strip()]
        if not description or not password:
            tk.messagebox.showerror("Ошибка", "Заполните описание и пароль!")
            return
        if len(password) < 4:
            messagebox.showerror("Ошибка", "Пароль должен быть не короче 4 символов!")
            return
        url = self.url_entry.get()
        self.result = {
            "description": description,
            "password": password,
            "tags": tags,
            "url": url.strip(),
        }
        self.destroy()


class ChangeMasterPasswordDialog(tk.Toplevel):
    # Диалоговое окно для смены мастер-пароля
    def __init__(self, parent, password_manager):
        super().__init__(parent)
        self.title("Смена мастер-пароля")
        self.transient(parent)
        self.grab_set()
        self.parent = parent
        self.password_manager = password_manager
        self.result = None

        # Создаем элементы интерфейса
        self._setup_ui()  # Вызываем ПЕРЕД созданием контекстного меню
        self._center_window()

        # Инициализация контекстного меню
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(
            label="Вставить", command=self._paste_from_clipboard
        )

        # Привязка правого клика к полям
        self.old_password_entry.bind("<Button-3>", self._show_context_menu)
        self.new_password_entry.bind("<Button-3>", self._show_context_menu)
        self.confirm_password_entry.bind("<Button-3>", self._show_context_menu)

    def _center_window(self):
        # Центрирование окна относительно родительского окна
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"+{x}+{y}")

    def _setup_ui(self):
        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Поле для текущего пароля
        ttk.Label(main_frame, text="Текущий мастер-пароль:").pack(
            anchor=tk.W, pady=(0, 5)
        )
        self.old_password_var = tk.StringVar()
        self.old_password_entry = ttk.Entry(
            main_frame, textvariable=self.old_password_var, show="*", width=30
        )
        self.old_password_entry.pack(fill=tk.X, pady=(0, 10))

        # Поле для нового пароля
        ttk.Label(main_frame, text="Новый мастер-пароль:").pack(
            anchor=tk.W, pady=(0, 5)
        )
        self.new_password_var = tk.StringVar()
        self.new_password_entry = ttk.Entry(
            main_frame, textvariable=self.new_password_var, show="*", width=30
        )
        self.new_password_entry.pack(fill=tk.X, pady=(0, 10))

        # Поле подтверждения
        ttk.Label(main_frame, text="Подтвердите новый пароль:").pack(
            anchor=tk.W, pady=(0, 5)
        )
        self.confirm_password_var = tk.StringVar()
        self.confirm_password_entry = ttk.Entry(
            main_frame, textvariable=self.confirm_password_var, show="*", width=30
        )
        self.confirm_password_entry.pack(fill=tk.X, pady=(0, 10))

        # Кнопки
        buttons_frame = ttk.Frame(main_frame)
        buttons_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(buttons_frame, text="Сменить пароль", command=self._on_change).pack(
            side=tk.RIGHT, padx=5
        )
        ttk.Button(buttons_frame, text="Отмена", command=self._on_cancel).pack(
            side=tk.RIGHT, padx=5
        )

    def _on_change(self):
        # Теперь old_password_var доступен
        old_password = self.old_password_var.get()
        new_password = self.new_password_var.get()
        confirm_password = self.confirm_password_var.get()

        if not old_password or not new_password:
            messagebox.showerror("Ошибка", "Все поля должны быть заполнены")
            return

        if new_password != confirm_password:
            messagebox.showerror("Ошибка", "Новые пароли не совпадают")
            return

        success, message = self.password_manager.change_master_password(
            old_password, new_password
        )
        if success:
            messagebox.showinfo("Успех", message)
            self.result = True
            self.destroy()
        else:
            messagebox.showerror("Ошибка", message)

    def _on_cancel(self):
        # Отмена смены мастер-пароля
        self.result = False
        self.destroy()

    def _show_context_menu(self, event):
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def _paste_from_clipboard(self):
        try:
            widget = self.focus_get()
            if widget in [
                self.old_password_entry,
                self.new_password_entry,
                self.confirm_password_entry,
            ]:
                widget.delete(0, tk.END)
                widget.insert(0, pyperclip.paste())
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось вставить: {str(e)}")


class ConfigEditorDialog(BasePasswordDialog):
    # Диалоговое окно для редактирования конфигурации пароля
    def __init__(self, parent, config_data):
        self.config_data = config_data
        super().__init__(parent, "Редактирование конфигурации")

    def _setup_ui(self):
        # Создание интерфейса для редактирования конфигурации пароля
        ttk.Label(self, text="Макс. длина пароля:").grid(
            row=0, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.max_length_entry = ttk.Spinbox(self, from_=8, to=128, width=10)
        self.max_length_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
        self.max_length_entry.set(self.config_data.get("max_password_length", 32))

        ttk.Label(self, text="Длина по умолчанию:").grid(
            row=1, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.default_length_entry = ttk.Spinbox(
            self, from_=4, to=self.config_data.get("max_password_length", 32), width=10
        )
        self.default_length_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)
        self.default_length_entry.set(self.config_data.get("default_length", 18))

        self.use_upper_var = tk.BooleanVar(
            value=self.config_data.get("use_uppercase", True)
        )
        ttk.Checkbutton(
            self, text="Исп. заглавные буквы", variable=self.use_upper_var
        ).grid(row=2, column=0, columnspan=2, padx=5, pady=2, sticky=tk.W)

        self.use_lower_var = tk.BooleanVar(
            value=self.config_data.get("use_lowercase", True)
        )
        ttk.Checkbutton(
            self, text="Исп. строчные буквы", variable=self.use_lower_var
        ).grid(row=3, column=0, columnspan=2, padx=5, pady=2, sticky=tk.W)

        self.use_digits_var = tk.BooleanVar(
            value=self.config_data.get("use_digits", True)
        )
        ttk.Checkbutton(self, text="Исп. цифры", variable=self.use_digits_var).grid(
            row=4, column=0, columnspan=2, padx=5, pady=2, sticky=tk.W
        )

        self.use_symbols_var = tk.BooleanVar(
            value=self.config_data.get("use_symbols", True)
        )
        ttk.Checkbutton(self, text="Исп. символы", variable=self.use_symbols_var).grid(
            row=5, column=0, columnspan=2, padx=5, pady=2, sticky=tk.W
        )

        ttk.Label(self, text="Исключенные символы:").grid(
            row=6, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.excluded_chars_entry = ttk.Entry(self, width=30)
        self.excluded_chars_entry.grid(row=6, column=1, padx=5, pady=5)
        self.excluded_chars_entry.insert(0, self.config_data.get("excluded_chars", ""))

        ttk.Label(self, text="Файл для паролей:").grid(
            row=7, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.pass_file_entry = ttk.Entry(self, width=30)
        self.pass_file_entry.grid(row=7, column=1, padx=5, pady=5)
        self.pass_file_entry.insert(
            0, self.config_data.get("passwords_file", "passwords.json")
        )

        button_frame = ttk.Frame(self)
        button_frame.grid(row=8, column=0, columnspan=2, pady=10)

        ttk.Button(button_frame, text="Сохранить", command=self._save).pack(
            side=tk.RIGHT, padx=5
        )
        ttk.Button(button_frame, text="Отмена", command=self.destroy).pack(
            side=tk.RIGHT
        )

    def _save(self):
        # Сохранение изменений в конфигурации пароля
        new_config = {
            "max_password_length": int(self.max_length_entry.get()),
            "default_length": int(self.default_length_entry.get()),
            "use_uppercase": self.use_upper_var.get(),
            "use_lowercase": self.use_lower_var.get(),
            "use_digits": self.use_digits_var.get(),
            "use_symbols": self.use_symbols_var.get(),
            "excluded_chars": self.excluded_chars_entry.get(),
            "passwords_file": self.pass_file_entry.get(),
        }

        if new_config["default_length"] > new_config["max_password_length"]:
            messagebox.showerror(
                "Ошибка", "Длина по умолчанию не может превышать максимальную"
            )
            return

        self.config_data.update(new_config)
        self.result = True
        self.destroy()


class RegenerateSaltDialog(tk.Toplevel):
    # Диалоговое окно для обновления криптографической соли
    def __init__(self, parent, password_manager):
        super().__init__(parent)
        self.title("Обновление криптографической соли")
        self.password_manager = password_manager

        # Сначала создаем элементы интерфейса
        self._setup_ui()
        self._center_window()

        # Теперь инициализируем контекстное меню
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(
            label="Вставить", command=self._paste_from_clipboard
        )

        # Правильное имя поля - password_entry
        self.password_entry.bind("<Button-3>", self._show_context_menu)

    def _center_window(self):
        # Центрирование окна на экране
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"+{x}+{y}")

    def _show_context_menu(self, event):
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def _paste_from_clipboard(self):
        try:
            # Используем правильное имя поля
            self.password_entry.delete(0, tk.END)
            self.password_entry.insert(0, pyperclip.paste())
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось вставить: {str(e)}")

    def _setup_ui(self):
        # Создание интерфейса для обновления криптографической соли
        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Введите текущий мастер-пароль:").pack(pady=(0, 10))

        self.password_var = tk.StringVar()
        self.password_entry = ttk.Entry(  # СОЗДАЕМ ПРАВИЛЬНЫЙ АТРИБУТ
            main_frame, textvariable=self.password_var, show="*", width=30
        )
        self.password_entry.pack(pady=(0, 10))

        buttons_frame = ttk.Frame(main_frame)
        buttons_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(buttons_frame, text="Обновить", command=self._regenerate).pack(
            side=tk.RIGHT, padx=5
        )
        ttk.Button(buttons_frame, text="Отмена", command=self.destroy).pack(
            side=tk.RIGHT, padx=5
        )

    def _regenerate(self):
        # Обновление криптографической соли
        password = self.password_var.get()
        if not password:
            messagebox.showerror("Ошибка", "Введите мастер-пароль")
            return

        success, message = self.password_manager.regenerate_salt(password)
        if success:
            messagebox.showinfo("Успех", message)
            self.destroy()
        else:
            messagebox.showerror("Ошибка", message)


class PasswordGeneratorApp:
    def __init__(self, master):
        self.master = master
        master.title("Генератор паролей")
        master.geometry("800x600")
        master.minsize(800, 600)

        self.idle_timer = None
        self.idle_timeout = 120000  # (2 минуты)

        self.setup_activity_tracking()

        if not self._initialize_password_manager():
            return

        self._full_ui_initialization()

    def _full_ui_initialization(self):
        # Создаем экземпляр PasswordManager
        self.password_generator = PasswordGenerator()
        self._setup_styles()
        self._create_tabs()
        self._setup_context_menu()
        self._create_menu()
        self.length_slider.config(to=self.password_generator.max_password_length)
        self.schedule_backup()
        self._refresh_password_list()
        self.master.deiconify()

    def _edit_configuration(self):
        # Загрузка текущей конфигурации из файла config.json
        config_path = os.path.join(get_app_dir(), "config.json")

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
        except Exception as e:
            messagebox.showerror(
                "Ошибка", f"Не удалось загрузить конфигурацию: {str(e)}"
            )
            return

        dialog = ConfigEditorDialog(self.master, config_data)
        dialog.wait_window()

        if getattr(dialog, "result", False):
            try:
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, indent=4, ensure_ascii=False)

                self.password_generator.load_config()
                self.length_slider.config(
                    to=self.password_generator.max_password_length
                )
                messagebox.showinfo("Успех", "Конфигурация успешно обновлена!")

            except Exception as e:
                messagebox.showerror(
                    "Ошибка", f"Ошибка сохранения конфигурации: {str(e)}"
                )

    def _export_passwords_txt(self):
        # Открываем диалог выбора пути для сохранения паролей
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")],
            title="Сохранить пароли в TXT",
        )
        if not file_path:
            return

        success, message = self.password_manager.export_to_txt(file_path)
        if success:
            messagebox.showinfo("Успех", message)
        else:
            messagebox.showerror("Ошибка", message)

    def schedule_backup(self):
        # Запланировать бэкап паролей через 1 час
        self.password_manager.backup_passwords()
        self.master.after(3600000, self.schedule_backup)  # 1 час

    def _initialize_password_manager(self):
        # Создаем экземпляр класса PasswordManager с пустым паролем
        attempts = 3
        while attempts > 0:
            auth_dialog = AuthenticationDialog(self.master)
            auth_dialog.wait_window()

            if not auth_dialog.result:
                if self.master.winfo_exists():
                    self.master.destroy()
                return False

            try:
                self.password_manager = PasswordManager(auth_dialog.master_password)
                self.password_manager.load_passwords()
                self.master.withdraw()
                return True
            except Exception:
                attempts -= 1
                if attempts > 0:
                    messagebox.showwarning(
                        "Ошибка", f"Неверный пароль. Осталось попыток: {attempts}"
                    )
                else:
                    if self.master.winfo_exists():
                        self.master.destroy()
                    return

    def _show_change_master_password(self):
        # Отображаем диалоговое окно для смены мастер-пароля
        dialog = ChangeMasterPasswordDialog(self.master, self.password_manager)
        dialog.wait_window()

        if dialog.result:
            self._refresh_password_list()

    def _create_default_config(self):
        # Создаем файл конфигурации по умолчанию, если его нет
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "config.json"
        )
        if not os.path.exists(config_path):
            default_config = {
                "max_password_length": 32,
                "default_length": 15,
                "use_uppercase": True,
                "use_lowercase": True,
                "use_digits": True,
                "use_symbols": True,
                "excluded_chars": "1l0Oo|",
                "passwords_file": "passwords.json",
            }
            try:
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(default_config, f, indent=4)
            except Exception as e:
                print(f"Ошибка создания конфигурации: {str(e)}")

    def _setup_styles(self):
        # Настройка стилей для виджетов
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TButton", font=("Arial", 10))
        style.configure("TLabel", font=("Arial", 10))
        style.configure("TEntry", font=("Arial", 10))
        style.configure("TCheckbutton", font=("Arial", 10))
        style.configure("red.Horizontal.TProgressbar", background="red")
        style.configure("yellow.Horizontal.TProgressbar", background="yellow")
        style.configure("green.Horizontal.TProgressbar", background="green")

        style.configure("Treeview.Cell", borderwidth=1, relief="solid", padding=(5, 2))
        style.layout(
            "Treeview.Item",
            [
                (
                    "Treeitem.padding",
                    {
                        "sticky": "nswe",
                        "children": [
                            ("Treeitem.indicator", {"side": "left", "sticky": ""}),
                            ("Treeitem.image", {"side": "left", "sticky": ""}),
                            ("Treeitem.text", {"side": "left", "sticky": ""}),
                            ("Treeitem.Cell", {"sticky": "nswe"}),
                        ],
                    },
                )
            ],
        )

    def _create_tabs(self):
        # Создаем вкладки и настраиваем их содержимое
        if not hasattr(self, "password_manager"):
            return

        self.tab_control = ttk.Notebook(self.master)
        self.generator_tab = ttk.Frame(self.tab_control)
        self.tab_control.add(self.generator_tab, text="Генератор")
        self._setup_generator_tab()

        self.manager_tab = ttk.Frame(self.tab_control)
        self.tab_control.add(self.manager_tab, text="Менеджер паролей")
        self._setup_manager_tab()

        self.tab_control.pack(expand=1, fill="both")

    def _setup_generator_tab(self):
        # Настройка содержимого вкладки "Генератор"
        settings_frame = ttk.LabelFrame(
            self.generator_tab, text="Настройки генератора", padding=10
        )
        settings_frame.pack(padx=10, pady=10, fill=tk.BOTH)

        ttk.Label(settings_frame, text="Длина пароля:").grid(
            row=0, column=0, sticky=tk.W, pady=5
        )
        self.length_var = tk.IntVar(value=self.password_generator.password_length)

        length_entry = ttk.Entry(settings_frame, textvariable=self.length_var, width=5)
        length_entry.grid(row=0, column=1, sticky=tk.W, pady=5)

        self.length_slider = ttk.Scale(
            settings_frame,
            from_=4,
            to=32,
            orient=tk.HORIZONTAL,
            variable=self.length_var,
            length=200,
            command=lambda _: self.length_var.set(int(self.length_slider.get())),
        )
        self.length_slider.grid(row=0, column=2, sticky=tk.W, pady=5, padx=10)

        self.use_uppercase = tk.BooleanVar(value=self.password_generator.use_uppercase)
        ttk.Checkbutton(
            settings_frame, text="Заглавные буквы (A-Z)", variable=self.use_uppercase
        ).grid(row=1, column=0, columnspan=3, sticky=tk.W)

        self.use_lowercase = tk.BooleanVar(value=self.password_generator.use_lowercase)
        ttk.Checkbutton(
            settings_frame, text="Строчные буквы (a-z)", variable=self.use_lowercase
        ).grid(row=2, column=0, columnspan=3, sticky=tk.W)

        self.use_digits = tk.BooleanVar(value=self.password_generator.use_digits)
        ttk.Checkbutton(
            settings_frame, text="Цифры (0-9)", variable=self.use_digits
        ).grid(row=3, column=0, columnspan=3, sticky=tk.W)

        self.use_symbols = tk.BooleanVar(value=self.password_generator.use_symbols)
        ttk.Checkbutton(
            settings_frame,
            text="Специальные символы (!@#$%)",
            variable=self.use_symbols,
        ).grid(row=4, column=0, columnspan=3, sticky=tk.W)

        ttk.Label(settings_frame, text="Исключить:").grid(
            row=5, column=0, sticky=tk.W, pady=5
        )
        self.excluded_chars_var = tk.StringVar(
            value=self.password_generator.excluded_chars
        )
        ttk.Entry(settings_frame, textvariable=self.excluded_chars_var, width=30).grid(
            row=5, column=1, columnspan=2, sticky=tk.W, pady=5
        )

        ttk.Button(
            settings_frame, text="Сгенерировать пароль", command=self._generate_password
        ).grid(row=6, column=0, columnspan=3, pady=10)

        output_frame = ttk.LabelFrame(
            self.generator_tab, text="Сгенерированный пароль", padding=10
        )
        output_frame.pack(padx=10, pady=10, fill=tk.BOTH)

        self.password_var = tk.StringVar()
        password_entry_frame = ttk.Frame(output_frame)
        password_entry_frame.pack(fill=tk.X)

        self.password_entry = ttk.Entry(
            password_entry_frame, textvariable=self.password_var, width=30
        )
        self.password_entry.pack(side=tk.LEFT, expand=True, fill=tk.X)
        self.password_entry.config(show="*")

        self.show_password_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            password_entry_frame,
            text="Показать",
            variable=self.show_password_var,
            command=lambda: self.password_entry.config(
                show="" if self.show_password_var.get() else "*"
            ),
        ).pack(side=tk.RIGHT)

        ttk.Label(output_frame, text="Сложность пароля:").pack(anchor=tk.W)
        self.strength_var = tk.IntVar()
        self.strength_bar = ttk.Progressbar(
            output_frame,
            orient=tk.HORIZONTAL,
            length=200,
            mode="determinate",
            variable=self.strength_var,
        )
        self.strength_bar.pack(fill=tk.X, pady=5)

        button_frame = ttk.Frame(output_frame)
        button_frame.pack(fill=tk.X, pady=5)

        ttk.Button(button_frame, text="Копировать", command=self._copy_password).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(
            button_frame, text="Очистить", command=lambda: self.password_var.set("")
        ).pack(side=tk.LEFT, padx=5)
        ttk.Button(
            button_frame, text="Сохранить", command=self._save_password_dialog
        ).pack(side=tk.LEFT, padx=5)

    def _setup_manager_tab(self):
        # Настройка содержимого вкладки "Менеджер паролей"
        control_frame = ttk.Frame(self.manager_tab, padding=10)
        control_frame.pack(fill=tk.X)

        self.hide_passwords_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            control_frame,
            text="Скрыть пароли",
            variable=self.hide_passwords_var,
            command=self._refresh_password_list,
        ).pack(side=tk.LEFT, padx=5)

        ttk.Button(
            control_frame, text="Обновить список", command=self._refresh_password_list
        ).pack(side=tk.LEFT, padx=5)
        ttk.Button(
            control_frame, text="Добавить новый пароль", command=self._add_new_password
        ).pack(side=tk.LEFT, padx=5)

        ttk.Label(control_frame, text="Поиск:").pack(side=tk.LEFT, padx=(10, 0))
        self.search_var = tk.StringVar()
        self.search_var.trace("w", lambda *args: self._filter_passwords())
        ttk.Entry(control_frame, textvariable=self.search_var, width=20).pack(
            side=tk.LEFT, padx=5
        )

        ttk.Label(control_frame, text="Теги:").pack(side=tk.LEFT, padx=(10, 0))
        self.tag_filter_var = tk.StringVar(value="Все")
        self.tag_filter = ttk.Combobox(
            control_frame,
            textvariable=self.tag_filter_var,
            values=["Все"],
            state="readonly",
        )
        self.tag_filter.pack(side=tk.LEFT, padx=5)
        self.tag_filter.bind("<<ComboboxSelected>>", lambda e: self._filter_passwords())

        list_frame = ttk.Frame(self.manager_tab, padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("description", "password", "tags")
        self.password_tree = ttk.Treeview(
            list_frame, columns=columns, show="headings", selectmode="browse"
        )

        headings = {"description": "Описание", "password": "Пароль", "tags": "Теги"}

        for col in columns:
            self.password_tree.heading(col, text=headings[col], anchor="center")
            if col == "description":
                self.password_tree.column(col, anchor="e", stretch=True, width=150)
            elif col == "password":
                self.password_tree.column(col, anchor="center", stretch=True, width=200)
            else:
                self.password_tree.column(col, anchor="center", stretch=True, width=100)

        vscroll = ttk.Scrollbar(
            list_frame, orient="vertical", command=self.password_tree.yview
        )
        hscroll = ttk.Scrollbar(
            list_frame, orient="horizontal", command=self.password_tree.xview
        )
        self.password_tree.configure(
            yscrollcommand=vscroll.set, xscrollcommand=hscroll.set
        )

        vscroll.pack(side=tk.RIGHT, fill=tk.Y)
        hscroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.password_tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        action_frame = ttk.Frame(self.manager_tab, padding=10)
        action_frame.pack(fill=tk.X)

        ttk.Button(
            action_frame, text="Копировать", command=self._copy_selected_password
        ).pack(side=tk.LEFT, padx=5)
        ttk.Button(
            action_frame, text="Просмотреть", command=self._view_selected_password
        ).pack(side=tk.LEFT, padx=5)
        ttk.Button(
            action_frame, text="Редактировать", command=self._edit_selected_password
        ).pack(side=tk.LEFT, padx=5)
        ttk.Button(
            action_frame, text="Удалить", command=self._delete_selected_password
        ).pack(side=tk.LEFT, padx=5)

        self._refresh_password_list()
        self.password_tree.bind("<Double-1>", lambda e: self._edit_selected_password())

    def _setup_context_menu(self):
        # Настройка контекстного меню
        self.entry_context_menu = tk.Menu(self.master, tearoff=0)
        self.entry_context_menu.add_command(
            label="Копировать",
            command=lambda: self._copy_to_clipboard(self.master.focus_get()),
        )
        self.entry_context_menu.add_command(
            label="Вырезать",
            command=lambda: self._cut_to_clipboard(self.master.focus_get()),
        )
        self.entry_context_menu.add_command(
            label="Вставить",
            command=lambda: self._paste_from_clipboard(self.master.focus_get()),
        )
        self.entry_context_menu.add_command(
            label="Выбрать всё",
            command=lambda: self._select_all(self.master.focus_get()),
        )

        self.tree_context_menu = tk.Menu(self.master, tearoff=0)
        self.tree_context_menu.add_command(
            label="Копировать", command=self._copy_selected_password
        )
        self.tree_context_menu.add_command(
            label="Просмотреть", command=self._view_selected_password
        )
        self.tree_context_menu.add_command(
            label="Редактировать", command=self._edit_selected_password
        )
        self.tree_context_menu.add_command(
            label="Удалить", command=self._delete_selected_password
        )

        self.master.bind("<Button-3>", self._on_right_click)
        self.password_tree.bind("<Button-3>", self._on_tree_right_click)

    def setup_activity_tracking(self):
        # Настройка отслеживания активности пользователя
        def track_activity(event):
            self.reset_inactivity_timer()

        def bind_recursive(widget):
            widget.bind("<Motion>", track_activity)
            widget.bind("<KeyPress>", track_activity)
            for child in widget.winfo_children():
                bind_recursive(child)

        bind_recursive(self.master)
        self.reset_inactivity_timer()

    def reset_inactivity_timer(self, event=None):
        # Сброс таймера неактивности
        if self.idle_timer is not None:
            self.master.after_cancel(self.idle_timer)

        self.idle_timer = self.master.after(self.idle_timeout, self.lock_application)

    def lock_application(self):
        # Заблокировать приложение
        if not hasattr(self, "password_manager") or not self.password_manager:
            return
        self.master.withdraw()
        auth_window = tk.Toplevel(self.master)
        auth_window.title("Блокировка")
        auth_window.protocol("WM_DELETE_WINDOW", lambda: None)
        auth_window.grab_set()

        auth_window.update_idletasks()
        parent_width = self.master.winfo_width()
        parent_height = self.master.winfo_height()
        parent_x = self.master.winfo_x()
        parent_y = self.master.winfo_y()

        width = auth_window.winfo_width()
        height = auth_window.winfo_height()

        x = parent_x + (parent_width - width) // 2
        y = parent_y + (parent_height - height) // 2
        auth_window.geometry(f"+{x}+{y}")

        auth_dialog = AuthenticationDialog(auth_window)
        auth_dialog.wait_window()

        if auth_dialog.result:
            try:
                self.password_manager = PasswordManager(auth_dialog.master_password)
                self.password_manager.load_passwords()
                self._refresh_password_list()
                auth_window.destroy()
                self.master.deiconify()
            except Exception as e:
                messagebox.showerror("Ошибка", f"Ошибка разблокировки: {str(e)}")
                self.master.destroy()
        else:
            self.master.destroy()

        self.reset_inactivity_timer()

    def _create_menu(self):
        # Настройка главного меню
        self.menu_bar = tk.Menu(self.master)
        self.master.config(menu=self.menu_bar)
        security_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Безопасность", menu=security_menu)
        security_menu.add_command(
            label="Обновить криптографическую соль", command=self._regenerate_salt
        )
        security_menu.add_command(
            label="Сменить мастер-пароль", command=self._show_change_master_password
        )
        security_menu.add_command(
            label="Заблокировать", command=lambda: self.lock_application()
        )
        file_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Файл", menu=file_menu)
        file_menu.add_command(
            label="Изменить конфигурацию", command=self._edit_configuration
        )
        file_menu.add_command(label="Экспорт в TXT", command=self._export_passwords_txt)

        file_menu.add_command(label="Импорт из TXT", command=self._import_passwords_txt)

        file_menu.add_command(
            label="Создать резервную копию", command=self._create_backup
        )
        file_menu.add_command(
            label="Открыть резервную копию", command=self._open_backup
        )
        file_menu.add_separator()
        file_menu.add_command(label="Выход", command=self.master.destroy)

        help_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Справка", menu=help_menu)
        help_menu.add_command(label="О программе", command=self._show_about)

    def _show_text_context_menu(self, event, menu):
        # Отображение контекстного меню для текстового поля
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _regenerate_salt(self):
        # Обновить криптографическую соль
        dialog = RegenerateSaltDialog(self.master, self.password_manager)
        dialog.wait_window()
        self._refresh_password_list()

    def _open_backup(self):
        # Открыть резервную копию
        backup_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "backups"
        )
        backup_file = os.path.join(backup_dir, "backup_passwords.bin")

        if not os.path.exists(backup_file):
            messagebox.showerror("Ошибка", f"Файл не найден:\n{backup_file}")
            return

        try:
            with open(backup_file, "r", encoding="utf-8") as f:
                encrypted_data = f.read()

            backup_passwords = json.loads(encrypted_data)
            decrypted_passwords = []

            for item in backup_passwords:
                try:
                    decrypted_pwd = self.password_manager.decrypt(item["password"])
                    decrypted_item = {
                        "description": item["description"],
                        "password": decrypted_pwd,
                        "tags": item.get("tags", []),
                    }
                    decrypted_passwords.append(decrypted_item)
                except Exception as e:
                    messagebox.showerror(
                        "Ошибка расшифровки",
                        f"Не удалось расшифровать пароль для '{item['description']}': {str(e)}",
                    )
                    return

            text_window = tk.Toplevel(self.master)
            text_window.title("Резервная копия (расшифровано)")

            text = tk.Text(text_window, wrap=tk.WORD)
            text.pack(fill=tk.BOTH, expand=True)

            formatted_data = json.dumps(
                decrypted_passwords, indent=4, ensure_ascii=False
            )
            text.insert(tk.END, formatted_data)

            context_menu = tk.Menu(text_window, tearoff=0)
            context_menu.add_command(
                label="Копировать", command=lambda: self._copy_from_text_widget(text)
            )

            text.bind(
                "<Button-3>", lambda e: self._show_text_context_menu(e, context_menu)
            )

        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось обработать файл: {str(e)}")

    def _copy_from_text_widget(self, text_widget):
        # Копирование выделенного текста из виджета текста
        try:
            selected = text_widget.get("sel.first", "sel.last")
            self.master.clipboard_clear()
            self.master.clipboard_append(selected)
        except tk.TclError:
            pass

    def _create_backup(self):
        # Создать резервную копию паролей
        success, message = self.password_manager.backup_passwords()
        if success:
            messagebox.showinfo("Успех", message)
        else:
            messagebox.showerror("Ошибка", message)

    def _show_about(self):
        # Отображение окна информации о программе
        messagebox.showinfo("О программе", "Менеджер паролей с шифрованием\n\n")

    def _import_passwords_txt(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Выберите файл для импорта",
        )

        if not file_path:
            return

        try:
            # Показать превью файла
            with open(file_path, "r", encoding="utf-8") as f:
                preview = f.read(1000)

            if not messagebox.askyesno(
                "Подтверждение",
                f"Импортировать пароли из файла?\n\nПревью:\n{preview[:200]}...",
            ):
                return

            success, message = self.password_manager.import_from_txt(file_path)
            if success:
                messagebox.showinfo("Успех", message)
                self._refresh_password_list()
            else:
                messagebox.showerror("Ошибка", message)

        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось прочитать файл: {str(e)}")

    def _generate_password(self):
        # Генерация нового пароля
        self.password_generator.password_length = int(self.length_var.get())
        self.password_generator.use_uppercase = self.use_uppercase.get()
        self.password_generator.use_lowercase = self.use_lowercase.get()
        self.password_generator.use_digits = self.use_digits.get()
        self.password_generator.use_symbols = self.use_symbols.get()
        self.password_generator.excluded_chars = self.excluded_chars_var.get().replace(
            " ", ""
        )

        new_password = self.password_generator.generate_password()
        self.password_var.set(new_password)
        self._update_strength_bar(new_password)

    def _update_strength_bar(self, password):
        # Обновление шкалы сложности пароля
        score = self.password_generator.evaluate_password_strength(password)
        self.strength_var.set(score)

        if score < 40:
            self.strength_bar.config(style="red.Horizontal.TProgressbar")
        elif score < 70:
            self.strength_bar.config(style="yellow.Horizontal.TProgressbar")
        else:
            self.strength_bar.config(style="green.Horizontal.TProgressbar")

    def _copy_password(self):
        # Копирование пароля в буфер обмена
        password = self.password_var.get()
        if password:
            pyperclip.copy(password)
            messagebox.showinfo("Успешно", "Пароль скопирован в буфер обмена!")
        else:
            messagebox.showerror("Ошибка", "Нет пароля для копирования.")

    def _save_password_dialog(self):
        # Отображение диалогового окна для сохранения пароля
        password = self.password_var.get()
        if not password:
            messagebox.showerror("Ошибка", "Сначала сгенерируйте пароль!")
            return

        initial_data = {"password": password, "description": "", "tags": [], "url": ""}

        dialog = PasswordDialog(self.master, "Сохранение пароля", initial_data)
        dialog.wait_window()

        if hasattr(dialog, "result") and dialog.result:
            data = dialog.result
            if not data["description"]:
                messagebox.showerror("Ошибка", "Заполните описание!")
                return

            self.password_manager.add_password(
                data["password"],
                data["description"],
                data.get("tags", []),
                data.get("url", ""),
            )
            messagebox.showinfo("Успешно", "Пароль сохранен!")
            self._refresh_password_list()

    def _add_new_password(self):
        # Добавление нового пароля с помощью диалогового окна
        dialog = PasswordDialog(self.master, "Добавить новый пароль")
        dialog.wait_window()

        if hasattr(dialog, "result") and dialog.result:
            data = dialog.result
            self.password_manager.add_password(
                data["password"],
                data["description"],
                data.get("tags", []),
                data.get("url", ""),
            )
            self._refresh_password_list()

    def _refresh_password_list(self):
        # Обновление списка сохраненных паролей
        self.password_tree.delete(*self.password_tree.get_children())

        passwords = self.password_manager.get_all_passwords()

        for idx, pwd in enumerate(passwords):
            pwd_copy = pwd.copy()
            if self.hide_passwords_var.get():
                pwd_copy["password"] = "••••••••"

            self.password_tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    pwd_copy["description"],
                    pwd_copy["password"],
                    ", ".join(pwd.get("tags", [])),
                ),
            )

        self._update_tag_filter_options()
        self._filter_passwords()

    def _update_tag_filter_options(self):
        # Обновление списка доступных тегов для фильтрации паролей
        tags = set()
        for pwd in self.password_manager.get_all_passwords():
            tags.update(pwd.get("tags", []))

        all_tags = ["Все"] + sorted(tags)
        self.tag_filter["values"] = all_tags
        self.tag_filter.config(
            width=max(
                10, max(len(str(tag)) for tag in all_tags) + 2 if all_tags else 10
            )
        )

    def _filter_passwords(self):
        # Фильтрация сохраненных паролей по поисковому запросу и выбранному тегу
        search_term = self.search_var.get().lower()
        selected_tag = self.tag_filter_var.get()

        self.password_tree.delete(*self.password_tree.get_children())

        passwords = self.password_manager.get_all_passwords()

        for idx, pwd in enumerate(passwords):
            tags = [t.lower() for t in pwd.get("tags", [])]

            match_search = (
                not search_term
                or search_term in pwd["description"].lower()
                or search_term in pwd["password"].lower()
                or any(search_term in tag for tag in tags)
            )

            match_tag = selected_tag == "Все" or selected_tag.lower() in tags

            if match_search and match_tag:
                display_password = (
                    "••••••••••••••••••••••••••••••••••••••••••••••••••••••••"
                    if self.hide_passwords_var.get()
                    else pwd["password"]
                )

                self.password_tree.insert(
                    "",
                    tk.END,
                    iid=str(idx),
                    values=(
                        pwd["description"],
                        display_password,
                        ", ".join(pwd.get("tags", [])),
                    ),
                )

    def _get_selected_password_index(self):
        # Получение индекса выбранного пароля в дереве паролей
        selection = self.password_tree.selection()
        return int(selection[0]) if selection else None

    def _copy_selected_password(self):
        # Копирование выбранного пароля в буфер обмена
        index = self._get_selected_password_index()
        if index is None:
            messagebox.showerror("Ошибка", "Выберите пароль для копирования.")
            return

        pwd = self.password_manager.get_password(index)
        if pwd:
            pyperclip.copy(pwd["password"])
            messagebox.showinfo("Успешно", "Пароль скопирован в буфер обмена!")

    def _view_selected_password(self):
        index = self._get_selected_password_index()
        if index is None:
            messagebox.showerror("Ошибка", "Выберите пароль для просмотра.")
            return

        pwd = self.password_manager.get_password(index)
        if pwd:
            dialog = PasswordDialog(self.master, "Просмотр пароля", pwd)
            dialog.paste_button.pack_forget()
            dialog.paste_button.destroy()
            dialog.password_entry.config(state="readonly")
            dialog.description_entry.config(state="readonly")
            dialog.tags_entry.config(state="readonly")
            dialog.url_entry.config(state="readonly")

            # Удаляем стандартные кнопки
            for child in dialog.winfo_children():
                if isinstance(child, ttk.Button):
                    child.destroy()

            # Добавляем кнопку "Открыть ссылку" в отдельную строку
            url = pwd.get("url", "")
            if url.startswith(("http://", "https://")):
                link_frame = ttk.Frame(dialog)
                link_frame.grid(row=5, column=0, columnspan=2, pady=10, sticky="ew")

                ttk.Button(
                    link_frame,
                    text="Открыть ссылку",
                    command=lambda: webbrowser.open(url),
                    cursor="hand2",
                ).pack(side=tk.TOP, fill=tk.X)

            # Добавляем кнопку закрытия
            ttk.Button(dialog, text="Закрыть", command=dialog.destroy).grid(
                row=6, column=0, columnspan=2, pady=10, sticky="ew"
            )

    def _edit_selected_password(self):
        # Редактирование выбранного пароля с помощью диалогового окна
        index = self._get_selected_password_index()
        if index is None:
            messagebox.showerror("Ошибка", "Выберите пароль для редактирования.")
            return

        pwd = self.password_manager.get_password(index)
        if pwd:
            dialog = PasswordDialog(self.master, "Редактировать пароль", pwd)
            dialog.wait_window()

            if hasattr(dialog, "result") and dialog.result:
                data = dialog.result
                self.password_manager.update_password(
                    index,
                    data["password"],
                    data["description"],
                    data.get("tags", []),
                    data.get("url", ""),
                )
                self._refresh_password_list()

    def _delete_selected_password(self):
        # Удаление выбранного пароля
        index = self._get_selected_password_index()
        if index is None:
            messagebox.showerror("Ошибка", "Выберите пароль для удаления.")
            return

        if messagebox.askyesno(
            "Подтверждение", "Вы уверены, что хотите удалить этот пароль?"
        ):
            if self.password_manager.delete_password(index):
                messagebox.showinfo("Успех", "Пароль удален.")
                self._refresh_password_list()
            else:
                messagebox.showerror("Ошибка", "Не удалось удалить пароль.")

    def _copy_to_clipboard(self, widget):
        # Копирование выбранного текста в буфер обмена
        if widget.selection_present():
            self.master.clipboard_clear()
            self.master.clipboard_append(widget.selection_get())

    def _cut_to_clipboard(self, widget):
        # Вырезание выбранного текста и копирование в буфер обмена
        if widget.selection_present():
            self._copy_to_clipboard(widget)
            widget.delete("sel.first", "sel.last")

    def _paste_from_clipboard(self, widget):
        # Вставка текста из буфера обмена в виджет
        try:
            text = self.master.clipboard_get()
            if widget.selection_present():
                widget.delete("sel.first", "sel.last")
            widget.insert(tk.INSERT, text)
        except:
            pass

    def _select_all(self, widget):
        # Выделение всего текста в виджете
        widget.select_range(0, tk.END)
        widget.icursor(tk.END)

    def _on_right_click(self, event):
        # Обработка правого клика на виджетах Entry и Treeview
        widget = event.widget
        if isinstance(widget, (tk.Entry, ttk.Entry)):
            self.entry_context_menu.tk_popup(event.x_root, event.y_root)

    def _on_tree_right_click(self, event):
        # Обработка правого клика на виджете Treeview
        item = self.password_tree.identify_row(event.y)
        if item:
            self.password_tree.selection_set(item)
            self.tree_context_menu.tk_popup(event.x_root, event.y_root)


if __name__ == "__main__":
    root = tk.Tk()
    app = PasswordGeneratorApp(root)
    root.mainloop()
