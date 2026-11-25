"""Qt offscreen regression: horizontal divider must be a real full-width HR.

Synthetic QTextEdit only; never touches notes, attachments, credentials or GitHub.
"""
import os
import sys
import unittest
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Other_dev"))
try:
    from PySide6.QtGui import QTextCursor
    from PySide6.QtWidgets import QApplication, QTextEdit
    from noteapp.app.editor import EditorMixin
except ImportError:
    QApplication = None


class _Editor(EditorMixin):
    def __init__(self):
        self.text_edit = QTextEdit()
        self.current_note = object()
        self.changed = False
    def _set_unsaved(self):
        self.changed = True


@unittest.skipIf(QApplication is None, "PySide6 missing")
class HorizontalRuleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_rule_in_middle_of_text_survives_html_roundtrip(self):
        editor = _Editor()
        editor.text_edit.setPlainText("Before\nAfter")
        cursor = editor.text_edit.textCursor()
        cursor.setPosition(len("Before"))
        editor.text_edit.setTextCursor(cursor)
        editor.insert_horizontal_line()
        html = editor.text_edit.toHtml()
        self.assertIn("<hr", html.lower())
        self.assertIn('width="100%"', html.lower())
        self.assertNotIn("<p>.</p>", html.lower())
        self.assertTrue(editor.changed)
        reopened = QTextEdit()
        reopened.setHtml(html)
        html2 = reopened.toHtml().lower()
        self.assertIn("<hr", html2)
        self.assertIn("Before", html2)
        self.assertIn("After", html2)
        self.assertNotIn("<p>.</p>", html2)

    def test_existing_content_preserved_when_cursor_has_selection(self):
        editor = _Editor()
        editor.text_edit.setPlainText("first\nsecond")
        cursor = editor.text_edit.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(5, QTextCursor.KeepAnchor)
        editor.text_edit.setTextCursor(cursor)
        editor.insert_horizontal_line()
        html = editor.text_edit.toHtml()
        self.assertIn("<hr", html.lower())
        self.assertIn("first", html)
        self.assertIn("second", html)

    def test_repeat_insertion_keeps_two_separators(self):
        editor = _Editor()
        editor.text_edit.setPlainText("Test")
        cursor = editor.text_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        editor.text_edit.setTextCursor(cursor)
        editor.insert_horizontal_line()
        editor.insert_horizontal_line()
        html = editor.text_edit.toHtml().lower()
        self.assertGreaterEqual(html.count("<hr"), 2)
        self.assertIn("Test", html)

if __name__ == "__main__":
    unittest.main()
