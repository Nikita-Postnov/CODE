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
        self.logger = logging.getLogger(__name__)  # Logger instance
        self.logger.setLevel(logging.INFO)

    def register(self):
        """
        Регистрирует горячие клавиши в приложении.
        """
        self.logger.info("Регистрация плагина горячих клавиш...")

        self.app.root.bind("<Alt-s>", self.save_shortcut)
        self.app.root.bind("<Alt-o>", self.open_shortcut)
        self.app.root.bind("<Alt-n>", self.new_shortcut)
        self.app.root.bind("<Alt-z>", self.undo_shortcut)
        self.app.root.bind("<Alt-y>", self.redo_shortcut)
        self.app.root.bind("<Alt-x>", self.cut_shortcut)
        self.app.root.bind("<Alt-c>", self.copy_shortcut)
        self.app.root.bind("<Alt-v>", self.paste_shortcut)
        self.logger.info("Горячие клавиши зарегистрированы.")

    def save_shortcut(self, event=None):
        """Обработчик горячей клавиши для сохранения."""
        self.logger.info("Сочетание клавиш сохранения нажато.")
        self.app.save_file()  # Вызываем метод сохранения из основного приложения

    def open_shortcut(self, event=None):
        """Обработчик горячей клавиши для открытия."""
        self.logger.info("Нажато сочетание клавиш Открыть.")
        self.app.open_file()  # Вызываем метод открытия из основного приложения

    def new_shortcut(self, event=None):
        """Обработчик горячей клавиши для создания нового файла."""
        self.logger.info("Нажато сочетание клавиш New.")
        self.app.new_file()  # Вызываем метод для нового файла из основного приложения

    def undo_shortcut(self, event=None):
        """Обработчик горячей клавиши для отмены действия."""
        self.logger.info("Нажато сочетание клавиш Отмена.")
        self.app.undo()

    def redo_shortcut(self, event=None):
        """Обработчик горячей клавиши для повтора действия."""
        self.logger.info("Нажато сочетание клавиш Повтор.")
        self.app.redo()

    def cut_shortcut(self, event=None):
        """Обработчик горячей клавиши для вырезания."""
        self.logger.info("Нажато сочетание клавиш Вырезать.")
        self.app.cut_text()

    def copy_shortcut(self, event=None):
        """Обработчик горячей клавиши для копирования."""
        self.logger.info("Нажато сочетание клавиш Копировать.")
        self.app.copy_text()

    def paste_shortcut(self, event=None):
        """Обработчик горячей клавиши для вставки."""
        self.logger.info("Нажато сочетание клавиш Вставить.")
        self.app.paste_text()
