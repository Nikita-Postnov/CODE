"""Генераторы паролей и случайных чисел + дефолтный конфиг паролей.

Чистая логика, зависит только от stdlib и путей из config.
"""

import json
import os
import random
import re
import secrets
import string

from .config import PASSWORDS_DIR

# Пароли — только криптостойким генератором. Обычный random предсказуем:
# по нескольким его выходам восстанавливается внутреннее состояние.
_secure_random = secrets.SystemRandom()


def create_default_config():
    config_path = os.path.join(PASSWORDS_DIR, "config.json")
    if not os.path.exists(config_path):
        os.makedirs(PASSWORDS_DIR, exist_ok=True)
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


class PasswordGenerator:
    def __init__(self):
        self.password_length = 15
        self.max_password_length = 32
        self.use_uppercase = True
        self.use_lowercase = True
        self.use_digits = True
        self.use_symbols = True
        self.excluded_chars = ""
        self.load_config()

    def load_config(self):
        config_path = os.path.join(PASSWORDS_DIR, "config.json")
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
            # Раньше здесь был рекурсивный self.load_config(): если файл не
            # создавался (нет прав, нет папки), рекурсия шла до RecursionError.
            create_default_config()
            if os.path.exists(config_path):
                self.load_config()

    def generate_password(self):
        char_sets: list[list[str]] = []
        if self.use_uppercase:
            char_sets.append(list(string.ascii_uppercase))
        if self.use_lowercase:
            char_sets.append(list(string.ascii_lowercase))
        if self.use_digits:
            char_sets.append(list(string.digits))
        if self.use_symbols:
            char_sets.append(list(string.punctuation))
        if not char_sets:
            return ""
        charset = [c for subset in char_sets for c in subset]
        charset = [c for c in charset if c not in self.excluded_chars]
        if not charset:
            return ""
        password_chars: list[str] = []
        for char_set in char_sets:
            valid_chars = [c for c in char_set if c not in self.excluded_chars]
            if valid_chars:
                password_chars.append(_secure_random.choice(valid_chars))
        remaining_length = max(0, self.password_length - len(password_chars))
        if remaining_length > 0:
            password_chars += _secure_random.choices(charset, k=remaining_length)
        _secure_random.shuffle(password_chars)
        return "".join(password_chars)

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


class NumberGenerator:
    def __init__(self, start: int = 0, end: int = 100):
        self.start = start
        self.end = end

    def generate(self) -> int:
        if self.start > self.end:
            self.start, self.end = self.end, self.start
        return random.randint(self.start, self.end)
