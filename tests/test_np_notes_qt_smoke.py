"""Изолированный Qt smoke-test: не открывает реальные заметки и не трогает Data."""
import ast
import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTextEdit, QWidget, QLabel
from PySide6.QtGui import QTextCursor, QTextDocument
from PySide6.QtCore import QDateTime, Qt

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


def extract_notesapp_method(name):
    file = APP_DIR / "__init__.py"
    tree = ast.parse(file.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == "NotesApp")
    method = next(node for node in cls.body
                  if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = {}
    body = ast.Module(body=[method], type_ignores=[])
    exec(compile(ast.fix_missing_locations(body), "<notesapp-qt-test>", "exec"), namespace)
    return namespace[name]


class UndoRetentionQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_formatting_only_change_creates_undo_revision(self):
        from types import SimpleNamespace
        edit = QTextEdit()
        self.addCleanup(edit.close)
        edit.setPlainText("Форматирование")
        original = edit.toHtml()
        note = SimpleNamespace(history=[original], history_index=0)
        class Owner:
            current_note = note
            text_edit = edit
            def update_history_list(self):
                pass
            def update_history_list_selection(self):
                pass
        source = (APP_DIR / "__init__.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                   and n.name == "NotesApp")
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                      and n.name == "record_state_for_undo")
        namespace = {"MAX_HISTORY": 50}
        module = ast.Module(body=[method], type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, "<rich-undo>", "exec"), namespace)
        cursor = edit.textCursor()
        cursor.select(QTextCursor.Document)
        edit.setTextCursor(cursor)
        edit.setFontWeight(700)
        namespace["record_state_for_undo"](Owner())
        self.assertEqual(len(note.history), 2)
        namespace["record_state_for_undo"](Owner())
        self.assertEqual(len(note.history), 2)
        self.assertNotEqual(note.history[0], note.history[1])

    def test_history_overflow_keeps_recent_versions(self):
        from types import SimpleNamespace
        text = QTextEdit()
        self.addCleanup(text.close)
        source = (APP_DIR / "__init__.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                   and n.name == "NotesApp")
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                      and n.name == "record_state_for_undo")
        namespace = {"QTextDocument": QTextDocument, "MAX_HISTORY": 4}
        module = ast.Module(body=[method], type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, "<undo-retention>", "exec"), namespace)
        note = SimpleNamespace(history=[""], history_index=0)
        class Owner:
            current_note = note
            text_edit = text
            def update_history_list(self):
                pass
            def update_history_list_selection(self):
                pass
        obj = Owner()
        for i in range(10):
            text.setPlainText("Шаг " + str(i))
            namespace["record_state_for_undo"](obj)
        self.assertEqual(len(note.history), 4)
        self.assertEqual(note.history_index, 3)
        plain = []
        for html in note.history:
            doc = QTextDocument()
            doc.setHtml(html)
            plain.append(doc.toPlainText())
        self.assertEqual(plain, ["Шаг 6", "Шаг 7", "Шаг 8", "Шаг 9"])

class RecentNotesQtTests(unittest.TestCase):
    def test_recent_sort_uses_datetime_including_offsets(self):
        source = (APP_DIR / "__init__.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        owner = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                     and n.name == "NotesApp")
        method = next(n for n in owner.body if isinstance(n, ast.FunctionDef)
                      and n.name == "_timestamp_sort_key")
        ns = {"QDateTime": QDateTime, "Qt": Qt, "Note": object}
        module = ast.Module(body=[method], type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, "<recent-notes-sort>", "exec"), ns)
        fn = ns["_timestamp_sort_key"]
        class Note:
            def __init__(self, timestamp):
                self.timestamp = timestamp
        older = Note("2026-11-25T09:00:00+03:00")
        newer = Note("2026-11-25T07:30:00+00:00")
        self.assertLess(fn(older), fn(newer))
        self.assertEqual(fn(Note("bad timestamp")), 0)


class EmptyFirstRunQtSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_empty_notes_keep_central_widget_visible(self):
        window = QWidget()
        window.show()
        self.addCleanup(window.close)
        center = QWidget(window)
        center.show()
        empty = QWidget(center)
        empty.show()
        class Fake:
            current_note = None
            notes = []
            def __init__(self):
                self.dock_editor = center
                self.empty_notes_page = empty
                self.empty_notes_title = type("Label", (), {"setText": lambda self, v: None})()
                self.empty_notes_hint = type("Label", (), {"setText": lambda self, v: None})()
                self.dock_toolbar = QWidget(window)
                self.visibility_toolbar = QWidget(window)
                self.text_edit = QTextEdit(center)
                self.tags_label = QLabel("Теги: нет", center)
                self._add_field_panel = QWidget(center)
                self.add_field_btn = QWidget(center)
                self.attachments_scroll = QWidget(center)
                self.password_manager_row = QWidget(center)
                self.custom_fields_widgets = []
        owner = Fake()
        extract_notesapp_method("_update_editor_visibility")(owner)
        self.assertTrue(center.isVisible())
        self.assertTrue(empty.isVisible())
        self.assertFalse(owner.text_edit.isVisible())


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
        self.assertAlmostEqual(widget.windowOpacity(), 0.85, delta=1 / 255 + 1e-6)
        set_opacity(proxy, 0.1)
        self.assertAlmostEqual(widget.windowOpacity(), 0.6, delta=1 / 255 + 1e-6)
        self.assertEqual(proxy.saved, 2)


class EditorQtSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.edit = QTextEdit()
        self.addCleanup(self.edit.close)

    def test_checklist_works_with_notesapp_history_when_qt_undo_is_disabled(self):
        from types import SimpleNamespace, MethodType
        self.edit.setUndoRedoEnabled(False)
        self.edit.setPlainText("☐ Задача")
        cursor = self.edit.textCursor()
        cursor.movePosition(QTextCursor.Start)
        self.edit.setTextCursor(cursor)
        note = SimpleNamespace(history=[], history_index=-1)
        class Owner:
            current_note = note
            text_edit = self.edit
            def update_history_list(self):
                pass
            def update_history_list_selection(self):
                pass
            def _set_html_preserve_view(self, html):
                self.text_edit.setHtml(html)
            def insert_checkbox(self):
                raise AssertionError("Checkbox already exists")
        owner = Owner()
        source = (APP_DIR / "__init__.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                   and n.name == "NotesApp")
        methods = [n for n in cls.body if isinstance(n, ast.FunctionDef)
                   and n.name in {"record_state_for_undo", "undo"}]
        namespace = {"QTextDocument": QTextDocument, "MAX_HISTORY": 50}
        module = ast.Module(body=methods, type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, "<notesapp-undo>", "exec"), namespace)
        owner.record_state_for_undo = MethodType(namespace["record_state_for_undo"], owner)
        owner.undo = MethodType(namespace["undo"], owner)
        # Isolated editor test: persistence itself is covered separately.
        owner._persist_history_navigation = lambda: None
        toggle = extract_editor_method("toggle_checkbox_at_cursor")
        toggle(owner)
        self.assertEqual(self.edit.toPlainText(), "☑ Задача")
        self.assertEqual(len(note.history), 2)
        owner.undo()
        self.assertEqual(self.edit.toPlainText(), "☐ Задача")

    def test_checklist_toggle_and_undo(self):
        self.edit.setPlainText("☐ Проверить")
        cursor = self.edit.textCursor()
        cursor.movePosition(QTextCursor.Start)
        self.edit.setTextCursor(cursor)
        class Owner:
            pass
        owner = Owner()
        owner.text_edit = self.edit
        owner.record_state_for_undo = lambda: None
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
