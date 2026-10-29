"""Тонкая обёртка над QMessageBox в tkinter-подобном стиле.

Лист-класс: зависит только от Qt, ни от чего в пакете. Алиас ``messagebox``
сохранён ради совместимости со старыми вызовами вида ``messagebox.showerror``.
"""

from PySide6.QtWidgets import QMessageBox


class MessageBox:
    @staticmethod
    def showerror(title, message):
        QMessageBox.critical(None, title, message)

    @staticmethod
    def showinfo(title, message):
        QMessageBox.information(None, title, message)

    @staticmethod
    def askyesno(title, message):
        return (
            QMessageBox.question(None, title, message, QMessageBox.Yes | QMessageBox.No)
            == QMessageBox.Yes
        )

    @staticmethod
    def showwarning(title, message):
        QMessageBox.warning(None, title, message)


messagebox = MessageBox
