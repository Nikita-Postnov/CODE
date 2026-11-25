"""Изолированный Qt smoke-test: не открывает реальные заметки и не трогает Data."""
import ast
import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTextEdit, QWidget
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


def extract_widget_method(name):
    file = APP_DIR.parent / "widgets" / "desktop_notes.py"
    tree = ast.parse(file.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == "DesktopNotesWidget")
    method = next(node for node in cls.body
                  if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = {}
    body = ast.Module(body=[method], type_ignores=[])
    exec(compile(ast.fix_missing_locations(body), "<widget-qt-test>", "exec"), namespace)
    return namespace[name]


def extract_search_method(name):
    file = APP_DIR / "search.py"
    tree = ast.parse(file.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == "SearchMixin")
    method = next(node for node in cls.body
                  if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = {}
    body = ast.Module(body=[method], type_ignores=[])
    exec(compile(ast.fix_missing_locations(body), "<search-qt-test>", "exec"), namespace)
    return namespace[name]


class SearchQtSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_find_next_wraps_and_only_selects(self):
        edit = QTextEdit()
        self.addCleanup(edit.close)
        edit.setPlainText("alpha beta alpha")
        class Bar:
            def text(self):
                return "alpha"
        class Owner:
            pass
        owner = Owner()
        owner.current_note = object()
        owner.search_bar = Bar()
        owner.text_edit = edit
        find = extract_search_method("find_next_in_current_note")
        self.assertTrue(find(owner))
        self.assertEqual(edit.textCursor().selectionStart(), 0)
        self.assertTrue(find(owner))
        self.assertEqual(edit.textCursor().selectionStart(), 11)
        self.assertTrue(find(owner))
        self.assertEqual(edit.textCursor().selectionStart(), 0)
        self.assertEqual(edit.toPlainText(), "alpha beta alpha")


class WidgetQtSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_desktop_widget_opacity_on_real_qwidget(self):
        widget = QWidget()
        self.addCleanup(widget.close)
        class Proxy:
            def __init__(self):
                self.widget = widget
                self.saved = 0
            def setWindowOpacity(self, opacity):
                self.widget.setWindowOpacity(opacity)
            def _save_pos(self):
                self.saved += 1
        proxy = Proxy()
        set_opacity = extract_widget_method("set_widget_opacity")
        set_opacity(proxy, 0.85)
        self.assertAlmostEqual(widget.windowOpacity(), 0.85)
        set_opacity(proxy, 0.1)
        self.assertAlmostEqual(widget.windowOpacity(), 0.6)
        self.assertEqual(proxy.saved, 2)


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
