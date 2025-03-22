import random
import string
import re
import pyperclip


class PasswordGenerator:
    def __init__(self):
        self.password_length = 15
        self.use_uppercase = True
        self.use_lowercase = True
        self.use_digits = True
        self.use_symbols = True
        self.excluded_chars = ''

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

        charset = ''.join(char_sets)
        for char in self.excluded_chars:
            charset = charset.replace(char, '')

        if not charset:
            return ""

        password = ''
        for char_set in char_sets:
            valid_chars = ''.join(
                c for c in char_set if c not in self.excluded_chars)
            if valid_chars:
                password += random.choice(valid_chars)

        remaining_length = max(0, self.password_length - len(password))
        password += ''.join(random.choice(charset)
                            for _ in range(remaining_length))

        password_list = list(password)
        random.shuffle(password_list)
        return ''.join(password_list)

    def evaluate_password_strength(self, password):
        score = 0

        if len(password) >= 8:
            score += 10
        if len(password) >= 12:
            score += 10
        if len(password) >= 16:
            score += 10

        if re.search(r'[A-Z]', password):
            score += 10
        if re.search(r'[a-z]', password):
            score += 10
        if re.search(r'[0-9]', password):
            score += 10
        if re.search(r'[^A-Za-z0-9]', password):
            score += 10

        if not re.search(r'(.)\1\1', password):
            score += 10

        unique_chars = len(set(password))
        score += min(20, unique_chars * 2)

        if (re.search(r'[A-Z].*[0-9]|[0-9].*[A-Z]', password) and
                re.search(r'[a-z].*[0-9]|[0-9].*[a-z]', password)):
            score += 10

        return min(100, score)
