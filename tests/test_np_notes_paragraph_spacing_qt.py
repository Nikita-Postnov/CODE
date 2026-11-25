"""Qt offscreen regression: paragraph spacing is scoped and serialized.

Only synthetic documents; never opens real notes, tokens or sync state.
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Other_dev"))

try:
    from PySide6.QtGui import QFont, QTextBlockFormat, QTextCursor
    from PySide6.QtWidgets import QApplication, QComboBox
    from noteapp.widgets.text_edit import CustomTextEdit
    from noteapp.app.editor import EditorMixin
except ImportError:
    QApplication = None


class FakeNotesEditor(EditorMixin):
    def __init__(self):
        self.text_edit = CustomTextEdit()
        self.text_edit.setFixedSize(640, 300)
        self.text_edit.setPlainText("First paragraph\nSecond paragraph\nThird")
        self.unsaved = []
        self.line_spacing_combo = QComboBox()
        for value in (1.0, 1.15, 1.5, 2.0):
            self.line_spacing_combo.addItem(str(value), value)
        self.paragraph_after_combo = QComboBox()
        for value in (0, 4, 8, 12):
            self.paragraph_after_combo.addItem(str(value), value)
        self.font_combo = None
        self.font_size_spin = None

    def _set_unsaved(self, flag: bool):
        self.unsaved.append(flag)

    def update_font_controls(self):
        self._update_paragraph_spacing_controls()


@unittest.skipIf(QApplication is None, "PySide6 missing")
class ParagraphSpacingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_default_controls_show_1_0_and_zero(self):
        editor = FakeNotesEditor()
        editor._update_paragraph_spacing_controls()
        self.assertEqual(editor.line_spacing_combo.currentData(), 1.0)
        self.assertEqual(editor.paragraph_after_combo.currentData(), 0)

    def test_selected_paragraphs_preserve_text_and_html_roundtrip(self):
        editor = FakeNotesEditor()
        cursor = editor.text_edit.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(len("First paragraph\nSecond paragraph"),
                           QTextCursor.KeepAnchor)
        editor.text_edit.setTextCursor(cursor)
        original = editor.text_edit.toPlainText()
        editor.set_paragraph_line_spacing(1.5)
        editor.set_paragraph_after_spacing(8)
        self.assertEqual(editor.text_edit.toPlainText(), original)
        self.assertEqual(editor.unsaved, [True, True])
        self.assertEqual(editor.line_spacing_combo.currentData(), 1.5)
        self.assertEqual(editor.paragraph_after_combo.currentData(), 8)

        first = editor.text_edit.document().findBlockByNumber(0).blockFormat()
        second = editor.text_edit.document().findBlockByNumber(1).blockFormat()
        third = editor.text_edit.document().findBlockByNumber(2).blockFormat()
        for fmt in (first, second):
            self.assertEqual(fmt.lineHeightType(),
                             QTextBlockFormat.ProportionalHeight)
            self.assertAlmostEqual(fmt.lineHeight(), 150)
            self.assertGreater(fmt.bottomMargin(), 0)
        self.assertLess(third.bottomMargin(), first.bottomMargin())
        self.assertNotEqual(third.lineHeight(), first.lineHeight())

        html = editor.text_edit.toHtml()
        restored = CustomTextEdit()
        restored.setHtml(html)
        self.assertEqual(restored.toPlainText(), original)
        for blocknum in (0, 1):
            fmt = restored.document().findBlockByNumber(blocknum).blockFormat()
            self.assertAlmostEqual(fmt.lineHeight(), 150, delta=2)
            self.assertAlmostEqual(fmt.bottomMargin(),
                                   first.bottomMargin(), delta=2)

    def test_cursor_movement_updates_controls_without_editing(self):
        editor = FakeNotesEditor()
        editor.set_paragraph_line_spacing(2.0)
        editor.set_paragraph_after_spacing(12)
        previous_edits = len(editor.unsaved)
        cursor = editor.text_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        editor.text_edit.setTextCursor(cursor)
        editor._update_paragraph_spacing_controls()
        self.assertEqual(editor.line_spacing_combo.currentData(), 1.0)
        self.assertEqual(editor.paragraph_after_combo.currentData(), 0)
        self.assertEqual(len(editor.unsaved), previous_edits)

    def test_inserting_existing_horizontal_rule_is_not_reformatted(self):
        editor = FakeNotesEditor()
        cursor = editor.text_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        editor.text_edit.setTextCursor(cursor)
        editor.insert_horizontal_line()
        before = editor.text_edit.toPlainText()
        cursor = editor.text_edit.textCursor()
        cursor.setPosition(0)
        editor.text_edit.setTextCursor(cursor)
        editor.set_paragraph_line_spacing(1.15)
        editor.set_paragraph_after_spacing(0)
        self.assertEqual(editor.text_edit.toPlainText(), before)
        self.assertIn("─", editor.text_edit.toHtml())


if __name__ == "__main__":
    unittest.main()
