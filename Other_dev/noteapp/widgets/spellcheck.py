"""Подсветка орфографии (QSyntaxHighlighter) на движке Hunspell (spylls).

Hunspell валидирует словоформы через аффиксные правила, поэтому склонения и
спряжения проверяются корректно без ручного отрезания суффиксов. Прежний
бэкенд (pyspellchecker) был плоским частотным списком, а компенсирующий его
самодельный стеммер (_ru_base_forms) и давал ложные срабатывания на косвенных
падежах ("требованиям", "потребностям", "пользователей").

Словари ru и en_US поставляются вместе с пакетом spylls — внешние .dic/.aff
шипать не нужно. Грузятся один раз на процесс (ленивый синглтон ниже).
"""

from PySide6.QtCore import (
    Qt,
    QFileSystemWatcher,
)

from PySide6.QtGui import (
    QTextCharFormat,
    QSyntaxHighlighter,
)

from pathlib import Path
import os
import re

from ..config import USER_DICT_PATH, qt_path


# --- Общие на весь процесс словари Hunspell (ленивая загрузка ~1 с) -----------
_DICTS_LOADED = False
_DICT_RU = None
_DICT_EN = None


def _get_dicts():
    """Возвращает (ru, en) объекты spylls Dictionary; None, если недоступны.

    Грузится единожды: инстансов хайлайтера может быть много (по редактору на
    заметку), а загрузка словаря стоит ~1 с — держать её в __init__ нельзя.
    """
    global _DICTS_LOADED, _DICT_RU, _DICT_EN
    if _DICTS_LOADED:
        return _DICT_RU, _DICT_EN
    _DICTS_LOADED = True
    try:
        from spylls.hunspell import Dictionary
    except ImportError:
        return None, None
    try:
        _DICT_RU = Dictionary.from_files("ru")
    except Exception:
        _DICT_RU = None
    try:
        _DICT_EN = Dictionary.from_files("en_US")
    except Exception:
        _DICT_EN = None
    return _DICT_RU, _DICT_EN


# --- Склоняемый личный словарь --------------------------------------------- #
# Слово из личного словаря внедряется в загруженный Hunspell с парадигмой
# слова-модели, подобранной по окончанию, — тогда оно валидируется во всех
# падежах, а не только в точной форме. Для окончаний вне карты внедряется без
# флага (только точная форма — как fallback). Инъекция идемпотентна и общая на
# процесс: _USER_INJECTED защищает от повторов при переоткрытии редакторов.
_USER_INJECTED: set[str] = set()

# окончание -> слово-модель в словаре ru (род/склонение однозначны, безопасно)
_USER_WORD_MODELS = (
    ("ость", "совместимость"),  # ж.р. 3-е скл.: проверяемость, тестируемость
    ("ция", "верификация"),     # ж.р.: валидация, локализация
    ("сия", "верификация"),
    ("зия", "верификация"),
)


def _inject_user_word(lw: str) -> None:
    """Добавляет слово личного словаря в общий Hunspell (склоняемо, если модель
    подобрана по окончанию; иначе — точной формой)."""
    if not lw or lw in _USER_INJECTED:
        return
    dru, _ = _get_dicts()
    if dru is None:
        return
    _USER_INJECTED.add(lw)
    try:
        from spylls.hunspell.data import dic as _dicmod
        if list(dru.dic.homonyms(lw)):  # уже есть в словаре — ничего не делаем
            return
        model = None
        for end, m in _USER_WORD_MODELS:
            if lw.endswith(end) and len(lw) - len(end) >= 2:
                hom = list(dru.dic.homonyms(m))
                if hom:
                    model = hom[0]
                break
        default_cap = list(dru.dic.homonyms("верификация"))[0].captype
        if model is not None:
            w = _dicmod.Word(stem=lw, flags=set(model.flags), data=dict(model.data),
                             alt_spellings=list(model.alt_spellings), captype=model.captype)
        else:
            w = _dicmod.Word(stem=lw, flags=set(), data={}, alt_spellings=[],
                             captype=default_cap)
        dru.dic.append(w, lower=[lw])
    except Exception:
        pass


class SpellCheckHighlighter(QSyntaxHighlighter):
    def __init__(self, parent):
        super().__init__(parent)
        self.err_fmt = QTextCharFormat()
        self.err_fmt.setUnderlineColor(Qt.red)
        self.err_fmt.setUnderlineStyle(QTextCharFormat.SpellCheckUnderline)

        # word -> is_known; кэшируем только чистый результат словарного лукапа.
        # user_words/local_ignored проверяются ДО кэша, поэтому их изменения
        # не требуют его сброса.
        self._checked_cache: dict[str, bool] = {}
        self.online_enabled = False

        self.user_words: set[str] = set()
        self.local_ignored: set[str] = set()
        self._load_user_dictionary()
        try:
            paths = []
            try:
                p = Path(USER_DICT_PATH) if not isinstance(USER_DICT_PATH, Path) else USER_DICT_PATH
                if p.exists():
                    paths.append(qt_path(p))
            except Exception:
                pass

            if paths:
                self._dict_watcher = QFileSystemWatcher(paths)
                self._dict_watcher.fileChanged.connect(self._reload_user_dictionary)
            else:
                self._dict_watcher = None

        except Exception:
            self._dict_watcher = None

    def set_online_enabled(self, enabled: bool) -> None:
        self.online_enabled = bool(enabled)
        self._checked_cache.clear()
        self.rehighlight()

    @staticmethod
    def normalize_e(word: str) -> str:
        return word.replace("ё", "е").replace("Ё", "Е")

    def _load_user_dictionary(self) -> None:
        prev_local = getattr(self, "local_ignored", set())
        self.user_words = set()
        self.local_ignored = set()
        try:
            with open(USER_DICT_PATH, "r", encoding="utf-8") as f:
                words = [line.strip().lower() for line in f if line.strip()]
            self.user_words.update(self.normalize_e(w) for w in words)
            # Внедряем в Hunspell для склонения (идемпотентно, общее на процесс).
            for uw in self.user_words:
                _inject_user_word(uw)
        except Exception:
            pass
        # словарь мог пополниться — прежние результаты лукапа устарели
        if hasattr(self, "_checked_cache"):
            self._checked_cache.clear()
        self.local_ignored = prev_local

    def add_to_dictionary(self, word: str) -> None:
        w = (word or "").strip().lower()
        if not w or self.normalize_e(w) in getattr(self, "user_words", set()):
            return
        try:
            p = Path(USER_DICT_PATH) if not isinstance(USER_DICT_PATH, Path) else USER_DICT_PATH
            p.parent.mkdir(parents=True, exist_ok=True)

            with open(p, "a", encoding="utf-8") as f:
                f.write(w + "\n")
                f.flush()
                os.fsync(f.fileno())

        except Exception:
            return
        self._load_user_dictionary()
        self.rehighlight()

    def set_local_ignored(self, words: list[str] | set[str]) -> None:
        self.local_ignored = {self.normalize_e(w.strip().lower()) for w in words if w.strip()}
        self.rehighlight()

    def _reload_user_dictionary(self, path: str) -> None:
        if self._dict_watcher and path not in self._dict_watcher.files():
            try:
                self._dict_watcher.addPath(path)
            except Exception:
                pass
        self._load_user_dictionary()
        self.rehighlight()

    def _dict_lookup(self, lw: str) -> bool:
        """Чистая проверка по словарю Hunspell с кэшем. lw — уже нормализован."""
        cached = self._checked_cache.get(lw)
        if cached is not None:
            return cached
        dru, den = _get_dicts()
        if dru is None and den is None:
            return True  # бэкенд недоступен — ничего не подчёркиваем
        if re.search(r"[А-Яа-яЁё]", lw):
            if dru is None:
                res = True
            else:
                res = bool(dru.lookup(lw))
                # Продуктивная приставка "не-": словарь содержит лишь часть
                # не-слов ("некорректный" есть, "нефункциональный" нет), но
                # "не" + валидная основа почти всегда корректно. Отрезаем и
                # проверяем остаток тем же Hunspell (морфология остатка цела).
                if not res and lw.startswith("не") and len(lw) - 2 >= 4:
                    res = bool(dru.lookup(lw[2:]))
        elif re.search(r"[A-Za-z]", lw):
            res = True if den is None else bool(den.lookup(lw))
        else:
            res = True
        self._checked_cache[lw] = res
        return res

    def _is_known_local(self, w: str) -> bool:
        if not w:
            return False
        lw = self.normalize_e(w.strip().lower())
        if lw in self.user_words or lw in self.local_ignored:
            return True
        return self._dict_lookup(lw)

    def suggest(self, word: str, limit: int = 7) -> list[str]:
        """Варианты замены для неверного слова (для контекстного меню)."""
        lw = self.normalize_e((word or "").strip().lower())
        if not lw:
            return []
        dru, den = _get_dicts()
        d = dru if re.search(r"[А-Яа-яЁё]", lw) else den
        if d is None:
            return []
        try:
            out: list[str] = []
            for s in d.suggest(lw):
                out.append(s)
                if len(out) >= limit:
                    break
            return out
        except Exception:
            return []

    def highlightBlock(self, text: str) -> None:
        if not self.online_enabled:
            return
        if not text or len(text) < 3:
            return
        if len(text) > 1500:
            return
        matches = list(re.finditer(r"[A-Za-zА-Яа-яЁё']+", text))
        if not matches:
            return
        for match in matches:
            raw = match.group()
            start = match.start()
            end = match.end()
            left = text[start - 1] if start - 1 >= 0 else ""
            right = text[end] if end < len(text) else ""
            if left == "@" or right == "@":
                continue
            if "@" in text[max(0, start - 2): min(len(text), end + 2)]:
                continue
            if (left == "." or right == ".") and len(raw) <= 6:
                continue
            if len(raw) < 3:
                continue

            if raw.isupper():
                continue
            if sum(ch.isdigit() for ch in raw) >= 2:
                continue

            w = self.normalize_e(raw.lower())
            if w in self.user_words or w in self.local_ignored:
                continue

            if not self._is_known_local(w):
                self.setFormat(match.start(), match.end() - match.start(), self.err_fmt)
