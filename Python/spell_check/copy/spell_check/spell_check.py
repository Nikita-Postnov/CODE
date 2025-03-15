import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox, Menu
from spellchecker import SpellChecker
import os
import sys
import ctypes
import re
from functools import partial
import logging
from datetime import datetime
import importlib.util
import inspect
from pathlib import Path
from tkinter import messagebox


# Base directories setup
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
DICTIONARY_DIR = os.path.join(BASE_DIR, "dictionary")
CUSTOM_DICTIONARY_FILE = os.path.join(
    DICTIONARY_DIR, "Personal_Dictionary.txt")
APP_VERSION = "1.0.0"

# Create necessary directories
if not os.path.exists(LOG_DIR):
    try:
        os.makedirs(LOG_DIR)
        print(f"✅ Создана папка для логов: {LOG_DIR}")
    except Exception as e:
        print(f"❌ Ошибка при создании папки логов: {str(e)}")
        LOG_DIR = BASE_DIR
        print(f"⚠️ Логи будут сохраняться в: {LOG_DIR}")

if not os.path.exists(DICTIONARY_DIR):
    try:
        os.makedirs(DICTIONARY_DIR)
        print(f"✅ Создана папка для словаря: {DICTIONARY_DIR}")
    except Exception as e:
        print(f"❌ Ошибка при создании папки словаря: {str(e)}")
        DICTIONARY_DIR = BASE_DIR
        CUSTOM_DICTIONARY_FILE = os.path.join(
            BASE_DIR, "Personal_Dictionary.txt")
        print(f"⚠️ Файл словаря будет сохранен в: {CUSTOM_DICTIONARY_FILE}")

# Setup logging
log_file = os.path.join(
    LOG_DIR, f"hotkeys_log_{datetime.now().strftime('%Y-%m-%d')}.log")
logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


class Plugin:
    """Базовый класс для плагинов"""

    def __init__(self, app):
        self.app = app

    def register(self):
        """Метод для регистрации плагина"""
        pass


class PluginManager:
    def __init__(self, app):
        self.app = app
        self.plugins = []
        self.plugins_dir = os.path.abspath(os.path.join(BASE_DIR, "plugins"))
        self.run_diagnostics()
        self.load_plugins()  # Вызываем загрузку плагинов сразу при инициализации

    def load_plugins(self):
        """Загружает плагины из директории"""
        print("\n" + "="*40 + " ЗАГРУЗКА ПЛАГИНОВ " + "="*40)

        try:
            if not os.path.exists(self.plugins_dir):
                os.makedirs(self.plugins_dir)
                print(f"✅ Создана директория для плагинов: {self.plugins_dir}")
                return

            plugin_files = [f for f in os.listdir(self.plugins_dir)
                            if f.endswith('.py') and f != '__init__.py']

            print(f"Найдено файлов плагинов: {len(plugin_files)}")

            for file_name in plugin_files:
                module_name = file_name[:-3]
                module_path = os.path.join(self.plugins_dir, file_name)
                print(f"\n🔌 Загрузка плагина: {file_name}")

                try:
                    spec = importlib.util.spec_from_file_location(
                        module_name, module_path)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)

                    # DEBUG: Вывести все классы модуля
                    print(f"Классы в модуле {module_name}:")
                    for name, obj in inspect.getmembers(module):
                        if inspect.isclass(obj):
                            print(f" - {name} (родитель: {obj.__bases__})")

                    for name, obj in inspect.getmembers(module):
                        if (inspect.isclass(obj)
                            and issubclass(obj, Plugin)
                                and obj != Plugin):
                            try:
                                plugin = obj(self.app)
                                plugin.register()
                                self.plugins.append(plugin)
                                print(
                                    f"✅ Успешно зарегистрирован: {obj.__name__}")
                            except Exception as e:
                                print(
                                    f"❌ Ошибка создания плагина {name}: {str(e)}")
                                import traceback
                                traceback.print_exc()

                except Exception as e:
                    print(f"❌ Критическая ошибка загрузки {file_name}:")
                    import traceback
                    traceback.print_exc()

            print(f"\nВсего загружено плагинов: {len(self.plugins)}")
            print("="*90)

        except Exception as e:
            print(f"❌ Фатальная ошибка: {str(e)}")
            import traceback
            traceback.print_exc()

    def run_diagnostics(self):
        """Запуск комплексной диагностики плагинов"""
        print("\n" + "="*40 + " ДИАГНОСТИКА ПЛАГИНОВ " + "="*40)
        self._check_folder_permissions()
        self._print_environment_info()
        self._list_plugin_files()
        print("="*100 + "\n")

    def _check_folder_permissions(self):
        """Проверка прав доступа к папке"""
        print(f"🔐 Проверка прав доступа:")
        print(f"Путь: {self.plugins_dir}")

        checks = {
            'Существует': os.path.exists,
            'Это папка': os.path.isdir,
            'Доступ на чтение': os.R_OK,
            'Доступ на запись': os.W_OK
        }

        for check_name, check_func in checks.items():
            try:
                if isinstance(check_func, int):  # Для флагов доступа
                    result = os.access(self.plugins_dir, check_func)
                else:
                    result = check_func(self.plugins_dir)

                status = "✅" if result else "❌"
                print(f"{status} {check_name}: {result}")
            except Exception as e:
                print(f"⚠️ Ошибка проверки {check_name}: {str(e)}")

    def _print_environment_info(self):
        """Информация о среде выполнения"""
        print("\n🌐 Информация о среде:")
        print(f"Python: {sys.version}")
        print(f"Рабочая директория: {os.getcwd()}")
        print(f"Кодировка файловой системы: {sys.getfilesystemencoding()}")

    def _list_plugin_files(self):
        """Список обнаруженных файлов плагинов"""
        print("\n📂 Содержимое папки плагинов:")
        try:
            files = list(Path(self.plugins_dir).glob('*'))
            if not files:
                print("⛔ Папка плагинов пуста")
                return

            for f in files:
                icon = "📄" if f.is_file() else "📁"
                print(f"{icon} {f.name:<20} | Размер: {f.stat().st_size/1024:.1f} KB | Создан: {datetime.fromtimestamp(f.stat().st_ctime):%Y-%m-%d %H:%M}")
        except Exception as e:
            print(f"❌ Ошибка чтения папки: {str(e)}")

    def get_plugins_info(self):
        """Форматированная информация о загруженных плагинах"""
        info = []
        for plugin in self.plugins:
            plugin_info = {
                "Имя": plugin.__class__.__name__,
                "Версия": getattr(plugin, 'version', '0.0.1'),
                "Автор": getattr(plugin, 'author', 'Неизвестно'),
                "Описание": getattr(plugin, 'description', 'Нет описания')
            }
            info.append(plugin_info)
        return info


class CustomDictionary:
    def __init__(self, spellchecker):
        self.spellchecker = spellchecker
        self.words = set()
        self.create_dictionary_file()
        self.load()

    def create_dictionary_file(self):
        """Создает файл словаря, если он не существует"""
        try:
            if not os.path.exists(CUSTOM_DICTIONARY_FILE):
                print(
                    f"Создаем файл словаря по пути: {os.path.abspath(CUSTOM_DICTIONARY_FILE)}")
                with open(CUSTOM_DICTIONARY_FILE, "w", encoding="utf-8") as file:
                    pass
                if os.path.exists(CUSTOM_DICTIONARY_FILE):
                    print(
                        f"✅ Файл словаря успешно создан: {CUSTOM_DICTIONARY_FILE}")
                else:
                    print(f"❌ Не удалось создать файл словаря")
                    self.try_alternative_location()
            else:
                print(
                    f"✅ Файл словаря уже существует: {CUSTOM_DICTIONARY_FILE}")
        except Exception as e:
            print(f"❌ Ошибка при создании файла словаря: {str(e)}")
            self.try_alternative_location()

    def try_alternative_location(self):
        """Пробует создать файл в альтернативном месте в случае ошибки"""
        global CUSTOM_DICTIONARY_FILE
        try:
            home_dir = os.path.expanduser("~")
            alt_file = os.path.join(home_dir, "Personal_Dictionary.txt")
            print(
                f"Пробуем создать файл словаря в альтернативном месте: {alt_file}")
            with open(alt_file, "w", encoding="utf-8") as file:
                pass
            if os.path.exists(alt_file):
                CUSTOM_DICTIONARY_FILE = alt_file
                print(
                    f"✅ Файл словаря создан в альтернативном месте: {CUSTOM_DICTIONARY_FILE}")
                messagebox.showinfo("Информация",
                                    f"Файл словаря создан в вашей домашней директории:\n{CUSTOM_DICTIONARY_FILE}")
            else:
                print(f"❌ Не удалось создать файл словаря в альтернативном месте")
        except Exception as e:
            print(
                f"❌ Ошибка при создании файла в альтернативном месте: {str(e)}")

    def load(self):
        """Загружает слова из файла в орфографический словарь"""
        try:
            if os.path.exists(CUSTOM_DICTIONARY_FILE):
                with open(CUSTOM_DICTIONARY_FILE, "r", encoding="utf-8") as file:
                    self.words = {line.strip()
                                  for line in file if line.strip()}
                if self.words:
                    self.refresh_spellchecker()
                    print(
                        f"✅ Загружено {len(self.words)} слов из словаря: {CUSTOM_DICTIONARY_FILE}")
                else:
                    print(
                        f"⚠️ Файл словаря существует, но пуст: {CUSTOM_DICTIONARY_FILE}")
            else:
                print(f"⚠️ Файл словаря не найден: {CUSTOM_DICTIONARY_FILE}")
                self.create_dictionary_file()
        except Exception as e:
            print(f"❌ Ошибка при загрузке словаря: {str(e)}")

    def clear(self):
        """Очищает персональный словарь"""
        self.words.clear()
        try:
            with open(CUSTOM_DICTIONARY_FILE, "w", encoding="utf-8") as file:
                pass
            self.refresh_spellchecker()
            print(f"✅ Персональный словарь очищен: {CUSTOM_DICTIONARY_FILE}")
            return True
        except Exception as e:
            print(f"❌ Ошибка при очистке словаря: {str(e)}")
            messagebox.showerror(
                "Ошибка", f"Не удалось очистить словарь:\n{str(e)}")
            return False

    def add(self, word):
        """Добавляет слово в персональный словарь"""
        if not word:
            print("⚠️ Пустое слово не может быть добавлено")
            return False

        word = word.lower().strip()
        if word in self.words:
            print(f"⚠️ Слово '{word}' уже есть в словаре")
            return False

        self.words.add(word)
        try:
            if not os.path.exists(CUSTOM_DICTIONARY_FILE):
                self.create_dictionary_file()

            with open(CUSTOM_DICTIONARY_FILE, "a", encoding="utf-8") as file:
                file.write(word + "\n")

            self.refresh_spellchecker()
            print(
                f"✅ Добавлено слово: '{word}' в файл {CUSTOM_DICTIONARY_FILE}")
            return True
        except Exception as e:
            error_msg = f"❌ Ошибка при добавлении слова '{word}': {str(e)}"
            print(error_msg)
            messagebox.showerror("Ошибка", error_msg)
            return False

    def save(self):
        """Сохраняет все слова из self.words в файл словаря"""
        try:
            if not os.path.exists(CUSTOM_DICTIONARY_FILE):
                self.create_dictionary_file()

            with open(CUSTOM_DICTIONARY_FILE, "w", encoding="utf-8") as file:
                for word in sorted(self.words):
                    file.write(word + "\n")
            print(
                f"✅ Словарь сохранен: {len(self.words)} слов/а/о в файл {CUSTOM_DICTIONARY_FILE}")
            return True
        except Exception as e:
            error_msg = f"❌ Ошибка при сохранении словаря: {str(e)}"
            print(error_msg)
            messagebox.showerror("Ошибка", error_msg)
            return False

    def refresh_spellchecker(self):
        """Обновляет встроенный словарь SpellChecker"""
        try:
            self.spellchecker.word_frequency.load_words(self.words)
            print(f"🔄 Персональный словарь обновлён: {len(self.words)} слов")
        except Exception as e:
            print(
                f"❌ Ошибка при обновлении орфографического словаря: {str(e)}")

    def remove(self, word):
        """Удаляет слово из персонального словаря"""
        if not word:
            print("⚠️ Пустое слово не может быть удалено")
            return False

        word = word.lower().strip()
        if word not in self.words:
            print(f"⚠️ Слово '{word}' отсутствует в словаре")
            return False

        self.words.remove(word)
        try:
            if not os.path.exists(CUSTOM_DICTIONARY_FILE):
                self.create_dictionary_file()

            # Перезаписываем файл без удаленного слова
            self.save()

            # Обновляем словарь для проверки орфографии
            self.refresh_spellchecker()
            print(
                f"✅ Удалено слово: '{word}' из файла {CUSTOM_DICTIONARY_FILE}")
            return True
        except Exception as e:
            error_msg = f"❌ Ошибка при удалении слова '{word}': {str(e)}"
            print(error_msg)
            messagebox.showerror("Ошибка", error_msg)
            return False


class SpellCheckerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Проверка орфографии")
        self.root.geometry("850x600")
        self.plugin_manager = PluginManager(self)
        self.restoring_state = False
        self.root.configure(bg="#f4f4f4")

        # Инициализация атрибутов ДО вызова методов
        self.debug_console = True  # Переносим выше
        self.history = []
        self.history_index = -1
        self.punctuation_errors = []

        # Инициализация компонентов
        self.spell = SpellChecker(language='ru')
        self.dictionary = CustomDictionary(self.spell)
        # Настройка интерфейса
        self.setup_ui()
        self.setup_menu()
        self.setup_history()
        self.entry.focus_set()

        # Дополнительные настройки
        self.setup_punctuation_rules()
        self.bind_hotkeys()

        # Консоль отладки (теперь атрибут debug_console инициализирован)
        if self.debug_console and sys.platform == "win32":
            ctypes.windll.kernel32.AllocConsole()
            sys.stdout = open("CONOUT$", "w", encoding="utf-8")

    def check_spelling(self):  # <-- Исправлен отступ здесь
        """Основной метод проверки орфографии"""
        self.highlight_errors()
        self.check_punctuation()

        text = self.entry.get("1.0", tk.END)
        words = re.findall(r'\b\w+\b', text)
        errors = list(self.spell.unknown(words))

        # Проверка пунктуации
        punctuation_errors = len(self.punctuation_errors)

        # Формирование отчета
        total_words = len(words)
        error_percent = (len(errors) / total_words *
                         100) if total_words > 0 else 0

        report = (f"Найдено ошибок: {len(errors)}\n"
                  f"Ошибки пунктуации: {punctuation_errors}\n"
                  f"Процент ошибок: {error_percent:.1f}%")

        self.update_result(report, "red" if errors else "green")
        self.status_bar.config(text="Проверка завершена")

    def bind_hotkeys(self):
        """Привязывает горячие клавиши"""
        hotkeys = {
            "<Control-c>": self.copy_text,
            "<Control-v>": self.paste_text,
            "<Control-x>": self.cut_text,
            "<Control-a>": self.select_all,
            "<Control-s>": self.save_dictionary,
            "<Control-d>": self.show_dictionary,
            "<Control-l>": self.clear_text,
            "<Control-z>": self.undo,
            "<Control-y>": self.redo
        }

        for key, func in hotkeys.items():
            self.root.bind_all(key, lambda event,
                               f=func: self.handle_hotkey(event, f))

        # Вывод отладочной информации
        print(f"📁 Путь к файлу словаря: {CUSTOM_DICTIONARY_FILE}")
        print(f"📂 Текущая директория: {BASE_DIR}")
        print(f"📁 Папка логов: {LOG_DIR}")
        print(
            f"✅ Существует ли файл: {os.path.exists(CUSTOM_DICTIONARY_FILE)}")
        print(f"📝 Права на запись: {os.access(BASE_DIR, os.W_OK)}")

        # Скрываем консоль, если debug_console = False
        if sys.platform == "win32" and not self.debug_console:
            ctypes.windll.user32.ShowWindow(
                ctypes.windll.kernel32.GetConsoleWindow(), 0)

    def handle_hotkey(self, event, func):
        """Централизованный обработчик горячих клавиш"""
        try:
            sig = inspect.signature(func)
            if 'event' in sig.parameters:
                result = func(event)
            else:
                result = func()

            # Логируем использование горячей клавиши
            hotkey_name = event.keysym
            if event.state & 0x4:  # Control key
                hotkey_name = f"Ctrl+{hotkey_name}"
            self.log_hotkey(f"{hotkey_name}")

            # Возвращаем результат функции или "break" по умолчанию
            return result if result else "break"
        except Exception as e:
            print(f"❌ Ошибка при обработке горячей клавиши: {str(e)}")
            return "break"

    def show_about(self):
        """Показывает информацию о программе"""
        about_text = (
            "Проверка орфографии\n\n"
            f"Версия: {APP_VERSION}\n"
            "Автор: Никита Постнов\n"
            "Лицензия: Community\n"
            "GitHub: https://github.com/Nikita-Postnov"
        )

        messagebox.showinfo(
            "О программе",
            about_text,
            icon=messagebox.INFO
        )

    def add_word_dialog(self):
        """Диалог добавления слова в словарь"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Добавить слово")
        dialog.geometry("300x100")

        tk.Label(dialog, text="Введите слово:").pack(pady=5)
        entry = tk.Entry(dialog)
        entry.pack(pady=5)

        def add_and_close():
            word = entry.get().strip()
            if word:
                if self.dictionary.add(word):
                    self.highlight_errors()
                    dialog.destroy()
                else:
                    messagebox.showerror("Ошибка", "Не удалось добавить слово")

        btn_frame = tk.Frame(dialog)
        btn_frame.pack(pady=5)

        ttk.Button(btn_frame, text="Добавить",
                   command=add_and_close).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Отмена", command=dialog.destroy).pack(
            side=tk.RIGHT, padx=5)

    def remove_word_dialog(self):
        """Диалог удаления слова из словаря"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Удалить слово")
        dialog.geometry("300x100")

        tk.Label(dialog, text="Введите слово:").pack(pady=5)
        entry = tk.Entry(dialog)
        entry.pack(pady=5)

        def remove_and_close():
            word = entry.get().strip()
            if word:
                if self.dictionary.remove(word):
                    self.highlight_errors()
                    dialog.destroy()
                else:
                    messagebox.showerror("Ошибка", "Не удалось удалить слово")

        btn_frame = tk.Frame(dialog)
        btn_frame.pack(pady=5)

        ttk.Button(btn_frame, text="Удалить", command=remove_and_close).pack(
            side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Отмена", command=dialog.destroy).pack(
            side=tk.RIGHT, padx=5)

    def show_plugins_manager(self):
        plugins_window = tk.Toplevel(self.root)
        plugins_window.title("Управление плагинами")
        plugins_window.geometry("600x400")

        # Добавляем список плагинов
        listbox = tk.Listbox(plugins_window)
        listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        for plugin in self.plugin_manager.plugins:
            listbox.insert(tk.END, f"• {plugin.__class__.__name__}")

        # Статистика
        status_label = tk.Label(
            plugins_window,
            text=f"Загружено плагинов: {len(self.plugin_manager.plugins)}",
            relief=tk.SUNKEN
        )
        status_label.pack(fill=tk.X, side=tk.BOTTOM)

    def setup_history(self):
        """Инициализация системы истории"""
        self.save_state()
        self.entry.bind("<<Modified>>", self.on_text_modified)

    def on_text_modified(self, event):
        if self.entry.edit_modified():
            if not self.restoring_state:  # Сохраняем только если не восстановление
                self.save_state()
            self.entry.edit_modified(False)

    def save_state(self):
        """Сохранение текущего состояния"""
        current_text = self.entry.get("1.0", tk.END)
        if self.history_index < len(self.history)-1:
            self.history = self.history[:self.history_index+1]
        self.history.append(current_text)
        self.history_index = len(self.history)-1

    def undo(self, event=None):
        """Отмена последнего действия"""
        if self.history_index > 0:
            self.history_index -= 1
            self.restore_state()
        return "break"

    def redo(self, event=None):
        if self.history_index < len(self.history)-1:
            self.history_index += 1
            self.restore_state()
        return "break"

    def restore_state(self):
        self.restoring_state = True  # Устанавливаем флаг
        self.entry.delete("1.0", tk.END)
        self.entry.insert("1.0", self.history[self.history_index])
        self.highlight_errors()
        self.check_punctuation()
        self.entry.edit_modified(False)  # Сбрасываем флаг модификации
        self.restoring_state = False

    def setup_punctuation_rules(self):
        """Настройка правил пунктуации"""
        self.rules = [
            (r'(?<!\s)([.,:;!?])', "Пропущен пробел перед знаком препинания"),
            (r'([.,:;!?])(?!\s|$)', "Пропущен пробел после знака препинания"),
            (r'\s([.,:;!?])', "Лишний пробел перед знаком препинания"),
            (r'([а-яА-Я])([A-Za-z])', "Смешение языков"),
            (r'\b\s{2,}\b', "Двойной пробел")
        ]

    def check_punctuation(self, event=None):
        """Проверка пунктуации в тексте"""
        self.entry.tag_remove("punctuation", "1.0", tk.END)
        self.punctuation_errors.clear()
        text = self.entry.get("1.0", tk.END)

        for pattern, message in self.rules:
            for match in re.finditer(pattern, text):
                start = match.start()
                end = match.end()
                self.entry.tag_add("punctuation",
                                   f"1.0+{start}c",
                                   f"1.0+{end}c")
                self.punctuation_errors.append({
                    'start': start,
                    'end': end,
                    'message': message
                })

        self.entry.tag_config("punctuation",
                              underline=True,
                              foreground="orange")

    def setup_menu(self):
        """Инициализация главного меню"""
        # Создаем главное меню
        self.menu = tk.Menu(self.root, tearoff=0)
        self.root.config(menu=self.menu)

        # Основное меню
        main_menu = tk.Menu(self.menu, tearoff=0)
        self.menu.add_cascade(label="Меню", menu=main_menu)
        # main_menu.add_command(label="Проверить орфографию", command=self.check_spelling)
        main_menu.add_command(label="Очистить текст", command=self.clear_text)
        main_menu.add_separator()
        main_menu.add_command(label="Выход", command=self.root.quit)

        # Меню словаря
        dict_menu = tk.Menu(self.menu, tearoff=0)
        self.menu.add_cascade(label="Словарь", menu=dict_menu)
        dict_menu.add_command(label="Показать словарь",
                              command=self.show_dictionary)
        dict_menu.add_command(label="Добавить слово",
                              command=self.add_word_dialog)
        dict_menu.add_command(label="Удалить слово",
                              command=self.remove_word_dialog)

        # Меню плагинов
        plugin_menu = tk.Menu(self.menu, tearoff=0)
        self.menu.add_cascade(label="Плагины", menu=plugin_menu)
        plugin_menu.add_command(
            label="Управление плагинами", command=self.show_plugins_manager)
        plugin_menu.add_command(label="Диагностика",
                                command=self.show_plugins_diagnostics)

        # Помощь
        help_menu = tk.Menu(self.menu, tearoff=0)
        self.menu.add_cascade(label="Справка", menu=help_menu)
        help_menu.add_command(label="О программе", command=self.show_about)

    def show_plugins_diagnostics(self):
        """Окно с расширенной диагностикой"""
        diag_window = tk.Toplevel(self.root)
        diag_window.title("Диагностика плагинов")

        text = tk.Text(diag_window, wrap=tk.WORD, width=80, height=20)
        scroll = tk.Scrollbar(diag_window, command=text.yview)
        text.configure(yscrollcommand=scroll.set)

        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        text.pack(fill=tk.BOTH, expand=True)

        # Собираем информацию
        info = [
            f"Версия приложения: {APP_VERSION}",
            f"Python: {sys.version.split()[0]}",
            f"Путь к плагинам: {self.plugin_manager.plugins_dir}",
            "\nЗагруженные плагины:"
        ]

        for p in self.plugin_manager.get_plugins_info():
            info.append(
                f"• {p['Имя']} v{p['Версия']}\n"
                f"   Автор: {p['Автор']}\n"
                f"   Описание: {p['Описание']}\n"
            )

        text.insert(tk.END, "\n".join(info))
        text.configure(state=tk.DISABLED)

    def toggle_theme(self):
        """Переключение между светлой и темной темой"""
        if self.root.cget("bg") == "#f4f4f4":  # Светлая тема
            self.root.configure(bg="#2d2d2d")
            self.entry.configure(bg="#3d3d3d", fg="white")
            self.path_label.configure(bg="#2d2d2d", fg="white")
            self.result_label.configure(bg="#2d2d2d", fg="white")
            self.title_label.configure(bg="#2d2d2d", fg="white")
        else:  # Темная тема
            self.root.configure(bg="#f4f4f4")
            self.entry.configure(bg="white", fg="black")
            self.path_label.configure(bg="#f4f4f4", fg="black")
            self.result_label.configure(bg="#f4f4f4", fg="black")
            self.title_label.configure(bg="#f4f4f4", fg="#333")

    def highlight_errors(self):
        """Подсвечивает ошибки в тексте"""
        text = self.entry.get("1.0", tk.END).strip()
        self.entry.tag_remove("misspelled", "1.0", tk.END)

        words = [(m.group(), m.start(), m.end())
                 for m in re.finditer(r'\b\w+\b', text)]

        for word, start, end in words:
            if word and word in self.spell.unknown([word]):
                self.entry.tag_add(
                    "misspelled", f"1.0+{start}c", f"1.0+{end}c")

    def get_word_under_cursor(self, event):
        """Получает слово под курсором мыши"""
        index = self.entry.index(tk.CURRENT)
        text = self.entry.get("1.0", tk.END).strip()
        if not text:
            return None, None, None
        cursor_pos = int(index.split(".")[1])
        words = [(m.group(), m.start(), m.end())
                 for m in re.finditer(r'\b\w+\b', text)]
        for word, start, end in words:
            if start <= cursor_pos < end:
                return word, start, end
        return None, None, None

    def show_suggestions(self, event):
        """Показывает контекстное меню с исправлениями"""
        self.context_menu = tk.Menu(self.root, tearoff=0)
        word, word_start, word_end = self.get_word_under_cursor(event)

        if word and word in self.spell.unknown([word]):
            suggestions = self.spell.candidates(word)
            if suggestions:
                sorted_suggestions = sorted(suggestions)
                for suggestion in sorted_suggestions:
                    self.context_menu.add_command(label=suggestion, command=partial(
                        self.replace_word, word_start, word_end, suggestion))
                self.context_menu.add_separator()
            self.context_menu.add_command(
                label="Добавить в словарь", command=lambda: self.add_word_and_update(word))
            self.highlight_errors()
            self.context_menu.post(event.x_root, event.y_root)
        elif word and word in self.dictionary.words:
            self.context_menu.add_command(
                label="Удалить из словаря", command=lambda: self.remove_word_and_update(word))
            self.context_menu.post(event.x_root, event.y_root)

    def add_word_and_update(self, word):
        """Добавляет слово в словарь и обновляет интерфейс"""
        if not word:
            self.update_result("Нет слова для добавления!", "orange")
            return

        if self.dictionary.add(word):
            self.update_result(f"Слово '{word}' добавлено в словарь", "green")
            self.highlight_errors()
        else:
            self.update_result(f"Ошибка при добавлении слова '{word}'", "red")

    def remove_word_and_update(self, word):
        """Удаляет слово из словаря и обновляет интерфейс"""
        if not word:
            self.update_result("Нет слова для удаления!", "orange")
            return

        confirm = messagebox.askyesno("Подтверждение",
                                      f"Вы уверены, что хотите удалить слово '{word}' из словаря?")
        if confirm:
            if self.dictionary.remove(word):
                self.update_result(
                    f"Слово '{word}' удалено из словаря", "green")
                self.highlight_errors()
            else:
                self.update_result(
                    f"Ошибка при удалении слова '{word}'", "red")

    def replace_word(self, start, end, replacement):
        """Заменяет слово на предложенное исправление"""
        self.entry.delete(f"1.0+{start}c", f"1.0+{end}c")
        self.entry.insert(f"1.0+{start}c", replacement)
        self.highlight_errors()

    def paste_text(self, event=None):
        """Вставляет текст из буфера обмена"""
        try:
            text = self.root.clipboard_get()
            self.entry.insert(tk.INSERT, text)
            self.highlight_errors()
            self.update_result("Текст вставлен", "blue")
        except tk.TclError:
            self.update_result("Буфер обмена пуст!", "orange")
        return "break"

    def clear_text(self, event=None):
        """Очищает текстовое поле"""
        self.entry.delete("1.0", tk.END)
        self.update_result("Текст очищен", "blue")
        return "break"

    def copy_text(self, event=None):
        """Копирует текст в буфер обмена"""
        try:
            selected_text = self.entry.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            selected_text = self.entry.get("1.0", tk.END).strip()

        if selected_text:
            self.root.clipboard_clear()
            self.root.clipboard_append(selected_text)
            self.root.update()
            self.update_result("Текст скопирован!", "blue")
        else:
            self.update_result("Нет текста для копирования!", "orange")
        return "break"

    def cut_text(self, event=None):
        """Вырезает выделенный текст"""
        try:
            selected_text = self.entry.get(tk.SEL_FIRST, tk.SEL_LAST)
            self.root.clipboard_clear()
            self.root.clipboard_append(selected_text)
            self.entry.delete(tk.SEL_FIRST, tk.SEL_LAST)
            self.root.update()
            self.update_result("Текст вырезан!", "blue")
        except tk.TclError:
            self.update_result("Нет выделенного текста!", "orange")
        return "break"

    def select_all(self, event=None):
        """Выделяет весь текст"""
        self.entry.tag_add(tk.SEL, "1.0", tk.END)
        self.update_result("Весь текст выделен", "blue")
        return "break"

    def log_hotkey(self, hotkey_name):
        """Логирует нажатие горячей клавиши"""
        logging.info(f"Нажата горячая клавиша: {hotkey_name}")
        print(f"🔑 Нажата горячая клавиша: {hotkey_name}")

    def show_dictionary(self, event=None):
        """Выводит содержимое персонального словаря в отдельном окне"""
        dict_window = tk.Toplevel(self.root)
        dict_window.title("Персональный словарь")
        dict_window.geometry("400x450")
        self.log_hotkey("Ctrl+D (Показать словарь)")

        path_label = tk.Label(dict_window, text=f"Файл: {CUSTOM_DICTIONARY_FILE}",
                              font=("Arial", 9), anchor="w")
        path_label.pack(pady=(5, 0), padx=10, fill=tk.X)

        # Добавляем фрейм для поиска
        search_frame = tk.Frame(dict_window)
        search_frame.pack(pady=(5, 0), padx=10, fill=tk.X)

        tk.Label(search_frame, text="Поиск:").pack(side=tk.LEFT)
        search_entry = tk.Entry(search_frame)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # Список слов
        words_frame = tk.Frame(dict_window)
        words_frame.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)

        # Создаем Listbox вместо ScrolledText для более удобного управления
        scrollbar = tk.Scrollbar(words_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        listbox = tk.Listbox(words_frame, height=15, width=50, font=("Arial", 12),
                             yscrollcommand=scrollbar.set, selectmode=tk.SINGLE)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=listbox.yview)

        # Заполняем Listbox словами
        words = sorted(self.dictionary.words)
        for word in words:
            listbox.insert(tk.END, word)

        # Функция для обновления списка при поиске
        def filter_words(event=None):
            search_text = search_entry.get().lower()
            listbox.delete(0, tk.END)
            for word in sorted(self.dictionary.words):
                if search_text in word.lower():
                    listbox.insert(tk.END, word)

        search_entry.bind("<KeyRelease>", filter_words)

        # Функция для удаления выбранного слова
        def remove_selected_word():
            selected_indices = listbox.curselection()
            if not selected_indices:
                messagebox.showinfo(
                    "Информация", "Выберите слово для удаления")
                return

            selected_word = listbox.get(selected_indices[0])
            confirm = messagebox.askyesno("Подтверждение",
                                          f"Вы уверены, что хотите удалить слово '{selected_word}'?")
            if confirm:
                if self.dictionary.remove(selected_word):
                    # Обновляем список
                    filter_words()
                    # Обновляем проверку текста
                    self.highlight_errors()
                    self.update_result(
                        f"Слово '{selected_word}' удалено из словаря", "green")

        button_frame = tk.Frame(dict_window)
        button_frame.pack(pady=5, fill=tk.X)

        ttk.Button(button_frame, text="Удалить выбранное слово",
                   command=remove_selected_word).pack(side=tk.LEFT, padx=5)

        def save_changes():
            # Получаем все слова из Listbox
            all_words = [listbox.get(i) for i in range(listbox.size())]
            # Обновляем словарь
            self.dictionary.words = set(all_words)
            if self.dictionary.save():
                self.dictionary.refresh_spellchecker()
                self.update_result("Словарь успешно сохранен!", "green")
                dict_window.destroy()
                self.highlight_errors()  # Повторно проверяем текст
            else:
                self.update_result("Ошибка при сохранении словаря!", "red")

        ttk.Button(button_frame, text="Сохранить изменения",
                   command=save_changes).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Отмена",
                   command=dict_window.destroy).pack(side=tk.RIGHT, padx=5)

        def choose_file_from_dialog():
            global CUSTOM_DICTIONARY_FILE
            file_path = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=[("Текстовые файлы", "*.txt")],
                title="Выберите расположение для словаря",
                initialfile="Personal_Dictionary.txt"
            )
            if file_path:
                CUSTOM_DICTIONARY_FILE = file_path
                self.dictionary.save()
                path_label.config(text=f"Файл: {CUSTOM_DICTIONARY_FILE}")
                self.update_result(
                    f"Словарь перемещен: {CUSTOM_DICTIONARY_FILE}", "green")

        ttk.Button(button_frame, text="Изменить расположение",
                   command=choose_file_from_dialog).pack(side=tk.LEFT, padx=5)

        # Добавляем контекстное меню для работы со словами
        context_menu = tk.Menu(listbox, tearoff=0)
        context_menu.add_command(label="Удалить", command=remove_selected_word)

        def show_context_menu(event):
            if listbox.size() > 0:
                listbox.selection_clear(0, tk.END)
                listbox.selection_set(listbox.nearest(event.y))
                context_menu.post(event.x_root, event.y_root)

        listbox.bind("<Button-3>", show_context_menu)  # Правый клик мыши

        def show_suggestions(self, event):
            """Показывает контекстное меню с исправлениями"""
            self.context_menu = tk.Menu(self.root, tearoff=0)
            word, word_start, word_end = self.get_word_under_cursor(event)

            if word:
                if word in self.spell.unknown([word]):
                    # Для неизвестного слова предлагаем варианты и добавление в словарь
                    suggestions = self.spell.candidates(word)
                    if suggestions:
                        sorted_suggestions = sorted(suggestions)
                        for suggestion in sorted_suggestions:
                            self.context_menu.add_command(label=suggestion, command=partial(
                                self.replace_word, word_start, word_end, suggestion))
                        self.context_menu.add_separator()
                    self.context_menu.add_command(
                        label="Добавить в словарь", command=lambda: self.add_word_and_update(word))
                else:
                    # Для известного слова (включая слова из персонального словаря)
                    # предлагаем возможность удалить его из словаря
                    if word in self.dictionary.words:
                        self.context_menu.add_command(
                            label="Удалить из словаря", command=lambda: self.remove_word_and_update(word))

                self.highlight_errors()
                self.context_menu.post(event.x_root, event.y_root)

    def remove_word_and_update(self, word):
        """Удаляет слово из словаря и обновляет интерфейс"""
        if not word:
            self.update_result("Нет слова для удаления!", "orange")
            return

        confirm = messagebox.askyesno("Подтверждение",
                                      f"Вы уверены, что хотите удалить слово '{word}' из словаря?")
        if confirm:
            if self.dictionary.remove(word):
                self.update_result(
                    f"Слово '{word}' удалено из словаря", "green")
                self.highlight_errors()  # Перепроверяем весь текст
            else:
                self.update_result(
                    f"Ошибка при удалении слова '{word}'", "red")
        ##########

        def save_changes():
            content = text_widget.get("1.0", tk.END).strip()
            new_words = {word.strip().lower()
                         for word in content.split("\n") if word.strip()}
            self.dictionary.words = new_words
            if self.dictionary.save():
                self.dictionary.refresh_spellchecker()
                self.update_result("Словарь успешно сохранен!", "green")
                dict_window.destroy()
                self.highlight_errors()
            else:
                self.update_result("Ошибка при сохранении словаря!", "red")

        ttk.Button(button_frame, text="Сохранить изменения",
                   command=save_changes).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Отмена",
                   command=dict_window.destroy).pack(side=tk.RIGHT, padx=5)

        def choose_file_from_dialog():
            global CUSTOM_DICTIONARY_FILE
            file_path = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=[("Текстовые файлы", "*.txt")],
                title="Выберите расположение для словаря",
                initialfile="Personal_Dictionary.txt"
            )
            if file_path:
                CUSTOM_DICTIONARY_FILE = file_path
                self.dictionary.save()
                path_label.config(text=f"Файл: {CUSTOM_DICTIONARY_FILE}")
                self.update_result(
                    f"Словарь перемещен: {CUSTOM_DICTIONARY_FILE}", "green")

        ttk.Button(button_frame, text="Изменить расположение",
                   command=choose_file_from_dialog).pack(side=tk.LEFT, padx=5)

    def save_dictionary(self, event=None):
        """Сохраняет словарь в файл"""
        if self.dictionary.save():
            self.update_result("Словарь успешно сохранен!", "green")
        else:
            self.update_result("Ошибка при сохранении словаря!", "red")
        return "break"

    def choose_dictionary_file(self):
        """Выбор нового расположения для файла словаря"""
        global CUSTOM_DICTIONARY_FILE
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Текстовые файлы", "*.txt")],
            title="Выберите расположение для словаря",
            initialfile="Personal_Dictionary.txt"
        )
        if file_path:
            CUSTOM_DICTIONARY_FILE = file_path
            self.dictionary.save()
            self.path_label.config(
                text=f"Файл словаря: {CUSTOM_DICTIONARY_FILE}")
            self.update_result(
                f"Новое расположение словаря: {CUSTOM_DICTIONARY_FILE}", "green")

    def setup_ui(self):
        """Настраивает пользовательский интерфейс"""
        self.title_label = tk.Label(self.root, text="Проверка орфографии",
                                    font=("Arial", 16, "bold"),
                                    bg=self.root.cget("bg"),
                                    fg="#333")
        self.title_label.pack(pady=10)

        self.path_label = tk.Label(self.root,
                                   text=f"Файл словаря: {CUSTOM_DICTIONARY_FILE}",
                                   font=("Arial", 9),
                                   anchor="w",
                                   bg=self.root.cget("bg"))
        self.path_label.pack(pady=(0, 5), padx=10, fill=tk.X)

        self.entry = scrolledtext.ScrolledText(self.root,
                                               height=10,
                                               width=70,
                                               font=("Arial", 12),
                                               wrap="word",
                                               bg="white",
                                               fg="black")
        self.entry.pack(pady=5, padx=10, fill=tk.BOTH, expand=True)
        self.entry.tag_configure(
            "misspelled", foreground="red", underline=True)
        self.entry.bind("<KeyRelease>", self.on_key_release)
        self.entry.bind("<Button-3>", self.show_suggestions)
        self.entry.bind("<space>", lambda event: self.highlight_errors())
        self.result_label = tk.Label(self.root,
                                     text="",
                                     font=("Arial", 12, "bold"),
                                     bg=self.root.cget("bg"))
        self.result_label.pack(pady=10)

        self.entry.bind("<KeyRelease>", lambda e: [self.highlight_errors(),
                                                   self.check_punctuation()])
        # Панель статуса
        self.status_bar = tk.Label(self.root,
                                   text="Готово",
                                   bd=1,
                                   relief=tk.SUNKEN,
                                   anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        # Кнопки истории
        history_frame = tk.Frame(self.root)
        history_frame.pack(pady=5)

        ttk.Button(history_frame,
                   text="Отменить (Ctrl+Z)",
                   command=self.undo).pack(side=tk.LEFT)
        ttk.Button(history_frame,
                   text="Повторить (Ctrl+Y)",
                   command=self.redo).pack(side=tk.LEFT)
        button_frame = tk.Frame(self.root, bg="#f4f4f4")
        button_frame.pack(pady=10)

        # Кнопки управления
        ttk.Button(button_frame, text="Проверить", command=self.check_spelling).pack(
            side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Очистить", command=self.clear_text).pack(
            side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Словарь", command=self.show_dictionary).pack(
            side=tk.LEFT, padx=5)

        # Добавляем ссылку на GitHub
        github_btn = ttk.Button(
            button_frame,
            text="GitHub",
            command=lambda: self.open_github()
        )
        github_btn.pack(side=tk.RIGHT, padx=5)

    def open_github(self):
        try:
            import webbrowser
            webbrowser.open("https://github.com/Nikita-Postnov")
        except Exception as e:
            messagebox.showerror(
                "Ошибка", f"Не удалось открыть ссылку: {str(e)}")

    def on_key_release(self, event):
        """Обработчик отпускания клавиши"""
        self.highlight_errors()
        self.check_punctuation()

    def update_result(self, message, color):
        """Обновляет метку результата"""
        self.result_label.config(text=message, foreground=color)

    def create_handler(self, func):
        """Создает обработчик для горячих клавиш"""
        def handler(event):
            # Check if the function expects an event parameter
            sig = inspect.signature(func)
            if len(sig.parameters) > 0:
                return func(event)
            else:
                func()
                return "break"
        return handler  # Возвращаем созданный обработчик


def check_system_info():
    """Выводит информацию о системе для отладки"""
    print(f"🖥️ Операционная система: {sys.platform}")
    print(f"📁 Путь к файлу словаря: {CUSTOM_DICTIONARY_FILE}")
    print(f"📂 Текущая директория скрипта: {BASE_DIR}")
    print(f"📂 Папка для логов: {LOG_DIR}")
    print(f"📂 Текущая рабочая директория: {os.getcwd()}")
    print(
        f"✅ Существует ли файл словаря: {os.path.exists(CUSTOM_DICTIONARY_FILE)}")
    print(f"✅ Существует ли папка логов: {os.path.exists(LOG_DIR)}")
    print(f"📝 Права на запись в директории: {os.access(BASE_DIR, os.W_OK)}")
    print(
        f"📝 Права на запись в папке логов: {os.access(LOG_DIR, os.W_OK) if os.path.exists(LOG_DIR) else 'Папка не существует'}")

    try:
        test_file = os.path.join(BASE_DIR, "test_write.tmp")
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        print("✅ Проверка записи в директорию успешна")
    except Exception as e:
        print(f"❌ Ошибка при проверке записи: {str(e)}")


if __name__ == "__main__":
    check_system_info()

    logging.info("--- Приложение запущено ---")

    root = tk.Tk()
    app = SpellCheckerApp(root)
    root.mainloop()

    logging.info("--- Приложение закрыто ---")
