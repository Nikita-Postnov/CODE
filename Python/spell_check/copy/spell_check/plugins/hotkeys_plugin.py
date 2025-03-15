import tkinter as tk
from __main__ import Plugin
import logging


class HotkeyPlugin(Plugin):
    """
    Плагин для добавления горячих клавиш в приложение.
    """

    def __init__(self, app):
        super().__init__(app)
        self.app = app

        # Настройка логгера с выводом на консоль
        self.logger = logging.getLogger(__name__)
        # Изменено на DEBUG для большей детализации
        self.logger.setLevel(logging.DEBUG)

        # Добавляем обработчик для вывода в консоль, если его еще нет
        if not self.logger.handlers:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)

        self.logger.debug("HotkeyPlugin инициализирован")

    def register(self):
        """
        Регистрирует горячие клавиши в приложении.
        """
        self.logger.info("Регистрация плагина горячих клавиш...")

        # Проверяем существование root в приложении
        if not hasattr(self.app, 'root') or not isinstance(self.app.root, tk.Tk):
            self.logger.error(
                "self.app.root не является экземпляром tk.Tk или не существует")
            return

        try:
            # Alt combinations as backup
            self.app.root.bind("<Alt-s>", self.save_shortcut)
            self.app.root.bind("<Alt-o>", self.open_shortcut)
            self.app.root.bind("<Alt-n>", self.new_shortcut)
            self.app.root.bind("<Alt-z>", self.undo_shortcut)
            self.app.root.bind("<Alt-y>", self.redo_shortcut)
            self.app.root.bind("<Alt-x>", self.cut_shortcut)
            self.app.root.bind("<Alt-c>", self.copy_shortcut)
            self.app.root.bind("<Alt-v>", self.paste_shortcut)

            # Проверяем существование всех методов приложения
            self._check_app_methods()

            self.logger.info("Горячие клавиши зарегистрированы успешно")
        except Exception as e:
            self.logger.error(f"Ошибка при регистрации горячих клавиш: {e}")

    def _check_app_methods(self):
        """Проверяет наличие всех необходимых методов в основном приложении"""
        required_methods = ['save_file', 'open_file', 'new_file', 'undo', 'redo',
                            'cut_text', 'copy_text', 'paste_text']

        for method in required_methods:
            if not hasattr(self.app, method) or not callable(getattr(self.app, method)):
                self.logger.warning(
                    f"Метод {method} не найден в основном приложении или не является вызываемым")

    def save_shortcut(self, event=None):
        """Обработчик горячей клавиши для сохранения."""
        self.logger.debug("Сочетание клавиш сохранения нажато.")
        try:
            if hasattr(self.app, 'save_file') and callable(self.app.save_file):
                self.app.save_file()
            else:
                self.logger.error("Метод save_file не найден в приложении")
        except Exception as e:
            self.logger.error(f"Ошибка при выполнении save_file: {e}")
        return "break"  # Предотвращаем дальнейшую обработку события

    # Остальные методы также нужно обновить с try-except и return "break"
    def open_shortcut(self, event=None):
        """Обработчик горячей клавиши для открытия."""
        self.logger.debug("Нажато сочетание клавиш Открыть.")
        try:
            if hasattr(self.app, 'open_file') and callable(self.app.open_file):
                self.app.open_file()
            else:
                self.logger.error("Метод open_file не найден в приложении")
        except Exception as e:
            self.logger.error(f"Ошибка при выполнении open_file: {e}")
        return "break"

    # Аналогично обновите остальные обработчики
