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
        self.assertIn("<table", html.lower())
        self.assertIn('width="100%"', html.lower())
        self.assertIn('bgcolor="#989898"', html.lower())
        self.assertNotIn("<p>.</p>", html.lower())
        self.assertTrue(editor.changed)
        reopened = QTextEdit()
        reopened.setHtml(html)
        html2 = reopened.toHtml().lower()
        self.assertIn("<table", html2)
        self.assertIn("before", html2)
        self.assertIn("after", html2)
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
        self.assertIn("<table", html.lower())
        self.assertIn("first", html.lower())
        self.assertIn("second", html.lower())

    def test_repeat_insertion_keeps_two_separators(self):
        editor = _Editor()
        editor.text_edit.setPlainText("Test")
        cursor = editor.text_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        editor.text_edit.setTextCursor(cursor)
        editor.insert_horizontal_line()
        editor.insert_horizontal_line()
        html = editor.text_edit.toHtml().lower()
        self.assertEqual(html.count("<table"), 2)
        self.assertIn("test", html)


    def test_visible_full_width_after_roundtrip(self):
        from PySide6.QtGui import QImage
        editor = _Editor()
        editor.text_edit.setFixedSize(600, 160)
        editor.text_edit.setStyleSheet(
            "QTextEdit { background-color: #2d2d2d; color: #eeeeee; border: 0px; }"
        )
        editor.text_edit.setPlainText("Above")
        c = editor.text_edit.textCursor()
        c.movePosition(QTextCursor.End)
        editor.text_edit.setTextCursor(c)
        editor.insert_horizontal_line()
        editor.text_edit.show()
        self.app.processEvents()
        for sample in (editor.text_edit,):
            pic = sample.viewport().grab().toImage().convertToFormat(
                QImage.Format.Format_RGBA8888
            )
            total_width = pic.width()
            strong_rows = []
            for y in range(15, min(90, pic.height())):
                bright = sum(
                    1 for x in range(20, total_width - 20)
                    if pic.pixelColor(x, y).red() >= 125
                )
                if bright >= (total_width - 40) * 0.85:
                    strong_rows.append(y)
            self.assertTrue(strong_rows,
                "Divider did not render across most of the dark QTextEdit viewport")

        reopened = QTextEdit()
        reopened.setFixedSize(600, 160)
        reopened.setStyleSheet(
            "QTextEdit { background-color: #2d2d2d; color: #eeeeee; border: 0px; }"
        )
        reopened.setHtml(editor.text_edit.toHtml())
        reopened.show()
        self.app.processEvents()
        pic = reopened.viewport().grab().toImage().convertToFormat(
            QImage.Format.Format_RGBA8888
        )
        strong_rows = []
        for y in range(15, min(90, pic.height())):
            bright = sum(
                1 for x in range(20, pic.width() - 20)
                if pic.pixelColor(x, y).red() >= 125
            )
            if bright >= (pic.width() - 40) * 0.85:
                strong_rows.append(y)
        self.assertTrue(strong_rows,
            "Divider disappeared after QTextDocument HTML serialization")

    def test_after_divider_typing_is_not_in_shaded_cell(self):
        editor = _Editor()
        editor.text_edit.setPlainText("Before")
        c = editor.text_edit.textCursor()
        c.movePosition(QTextCursor.End)
        editor.text_edit.setTextCursor(c)
        editor.insert_horizontal_line()
        c = editor.text_edit.textCursor()
        self.assertIsNone(c.currentTable(), "Caret remained inside separator table")
        c.insertText("After")
        html = editor.text_edit.toHtml().lower()
        self.assertIn("after", html)
        self.assertEqual(html.count("<table"), 1)

if __name__ == "__main__":
    unittest.main()
