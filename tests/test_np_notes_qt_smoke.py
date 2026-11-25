"""Изолированный Qt smoke-test: не открывает реальные заметки и не трогает Data."""
import ast
import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTextEdit
from PySide6.QtGui import QTextCursor

APP_DIR = Path(__file__).resolve().parents[1] / "Other_dev" / "noteapp" / "app"


def extract_editor_method(name):
    file = APP_DIR / "editor.py"
    tree = ast.parse(file.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == "EditorMixin")
    method = next(node for node in cls.body
                  if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = {"QTextCursor": QTextCursor}
    body = ast.Module(body=[method], type_ignores=[])
    exec(compile(ast.fix_missing_locations(body), "<editor-qt-test>", "exec"), namespace)
    return namespace[name]


class EditorQtSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.edit = QTextEdit()
        self.addCleanup(self.edit.close)

    def test_checklist_toggle_and_undo(self):
        self.edit.setPlainText("☐ Проверить")
        cursor = self.edit.textCursor()
        cursor.movePosition(QTextCursor.Start)
        self.edit.setTextCursor(cursor)
        class Owner:
            pass
        owner = Owner()
        owner.text_edit = self.edit
        toggle = extract_editor_method("toggle_checkbox_at_cursor")
        owner.insert_checkbox = lambda: None
        toggle(owner)
        self.assertEqual(self.edit.toPlainText(), "☑ Проверить")
        self.edit.undo()
        self.assertEqual(self.edit.toPlainText(), "☐ Проверить")
        toggle(owner)
        self.assertEqual(self.edit.toPlainText(), "☑ Проверить")
        toggle(owner)
        self.assertEqual(self.edit.toPlainText(), "☐ Проверить")


if __name__ == "__main__":
    unittest.main()
