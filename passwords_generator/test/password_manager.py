import os
import json
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import pyperclip


class PasswordManager:
    def __init__(self, master_password=None):
        self.master_password = master_password
        self.encryption_key = None
        self.passwords = []
        self.filename = os.path.join(os.path.dirname(
            os.path.abspath(__file__)), "passwords.json")
        self.initialize_encryption()
        self.load_passwords()

    def initialize_encryption(self):
        if self.master_password:
            salt = b'salt_' + b'0' * 12
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(
                kdf.derive(self.master_password.encode()))
            self.encryption_key = Fernet(key)

    def encrypt_password(self, password):
        if self.encryption_key:
            return self.encryption_key.encrypt(password.encode()).decode()
        return password

    def decrypt_password(self, encrypted_password):
        if self.encryption_key:
            try:
                return self.encryption_key.decrypt(encrypted_password.encode()).decode()
            except:
                return "Невозможно расшифровать"
        return encrypted_password

    def add_password(self, password, description):
        encrypted_password = self.encrypt_password(password)
        self.passwords.append({
            "password": encrypted_password,
            "description": description,
        })
        self.save_passwords()
        return True

    def update_password(self, index, password, description):
        if 0 <= index < len(self.passwords):
            encrypted_password = self.encrypt_password(password)
            self.passwords[index]["password"] = encrypted_password
            self.passwords[index]["description"] = description
            self.passwords[index]["updated_at"] = self._get_timestamp()
            self.save_passwords()
            return True
        return False

    def delete_password(self, index):
        if 0 <= index < len(self.passwords):
            del self.passwords[index]
            self.save_passwords()
            return True
        return False

    def get_password(self, index):
        if 0 <= index < len(self.passwords):
            encrypted_password = self.passwords[index]["password"]
            return {
                "password": self.decrypt_password(encrypted_password),
                "description": self.passwords[index]["description"]
            }
        return None

    def get_all_passwords(self):
        decrypted_passwords = []
        for item in self.passwords:
            decrypted_passwords.append({
                "password": self.decrypt_password(item["password"]),
                "description": item["description"]
            })
        return decrypted_passwords

    def _get_timestamp(self):
        import datetime
        return datetime.datetime.now().isoformat()

    def load_passwords(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r') as f:
                    self.passwords = json.load(f)
            except json.JSONDecodeError:
                self.passwords = []
        else:
            with open(self.filename, 'w') as f:
                json.dump([], f)
            self.passwords = []

    def save_passwords(self):
        with open(self.filename, 'w') as f:
            json.dump(self.passwords, f, indent=4)
