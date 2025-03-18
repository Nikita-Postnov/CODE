import tkinter as tk
from __main__ import Plugin
import logging

class HotkeyPlugin(Plugin):

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.logger = logging.getLogger(__name__)  # Logger instance
        self.logger.setLevel(logging.INFO)

    def register(self):

        self.logger.info("Регистрация плагина горячих клавиш...")

        self.app.root.bind("<Control-s>", self.save_shortcut)
        self.app.root.bind("<Control-o>", self.open_shortcut)
        self.app.root.bind("<Control-n>", self.new_shortcut)
        self.app.root.bind("<Control-z>", self.undo_shortcut)
        self.app.root.bind("<Control-y>", self.redo_shortcut)
        self.app.root.bind("<Control-x>", self.cut_shortcut)
        self.app.root.bind("<Control-c>", self.copy_shortcut)
        self.app.root.bind("<Control-v>", self.paste_shortcut)
        
        
        self.logger.info("Горячие клавиши зарегистрированы.")

    def save_shortcut(self, event=None):
        self.logger.info("Сочетание клавиш сохранения нажато.")
        self.app.save_file()

    def open_shortcut(self, event=None):
        self.logger.info("Нажато сочетание клавиш Открыть.")
        self.app.open_file()
    def new_shortcut(self, event=None):
        self.logger.info("Нажато сочетание клавиш New.")
        self.app.new_file()
    def undo_shortcut(self, event=None):
        self.logger.info("Нажато сочетание клавиш Отмена.")
        self.app.undo()

    def redo_shortcut(self, event=None):
        self.logger.info("Нажато сочетание клавиш Повтор.")
        self.app.redo()

    def cut_shortcut(self, event=None):
        self.logger.info("Нажато сочетание клавиш Вырезать.")
        self.app.cut_text()

    def copy_shortcut(self, event=None):
        self.logger.info("Нажато сочетание клавиш Копировать.")
        self.app.copy_text()

    def paste_shortcut(self, event=None):
        self.logger.info("Нажато сочетание клавиш Вставить.")
        self.app.paste_text()
