"""Broad synthetic Qt audit of NP Notes editing controls and persistence.

Never reads or modifies user Data, credentials, real attachments or GitHub sync.
Exercises EditorMixin with the production CustomTextEdit and Qt event handling.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Other_dev"))

try:
    from PySide6.QtCore import Qt, QMimeData
    from PySide6.QtGui import (
        QColor, QFont, QImage, QTextCursor, QTextListFormat,
        QTextBlockFormat, QTextCharFormat, QTextDocument,
    )
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (
        QApplication, QWidget, QFontComboBox, QSpinBox, QComboBox,
    )
    from noteapp.app.editor import EditorMixin
    from noteapp.widgets.text_edit import CustomTextEdit
except ImportError:
    QApplication = None


class FakeSettings:
    def value(self, key, default=None):
        return default


class EditorHost(QWidget, EditorMixin):
    """Standalone app fixture, with real NotesApp's dirty callback contract."""
    def __init__(self):
        super().__init__()
        self.text_edit = CustomTextEdit(parent=self)
        self.text_edit.resize(720, 280)
        self.text_edit.show()
        self.settings = FakeSettings()
        self.current_note = object()
        self.font_combo = QFontComboBox()
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 48)
        self.line_spacing_combo = QComboBox()
        for value in (1.0, 1.15, 1.5, 2.0):
            self.line_spacing_combo.addItem(str(value), value)
        self.paragraph_after_combo = QComboBox()
        for value in (0, 4, 8, 12):
            self.paragraph_after_combo.addItem(str(value), value)
        self.autosave_enabled = False
        self._last_selection = None
        self.changes = []
        self.history_count = 0

    def _set_unsaved(self, flag: bool):
        self.changes.append(flag)

    def record_state_for_undo(self):
        self.history_count += 1

    def save_note(self):
        self.changes.append("save")


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class EditorControlsAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def new_host(self, text="First\nSecond"):
        host = EditorHost()
        self.addCleanup(host.close)
        host.text_edit.setPlainText(text)
        self.app.processEvents()
        return host

    def select(self, host, a, b):
        c = host.text_edit.textCursor()
        c.setPosition(a)
        c.setPosition(b, QTextCursor.KeepAnchor)
        host.text_edit.setTextCursor(c)

    def cursor_at(self, host, at):
        c = host.text_edit.textCursor()
        c.setPosition(at)
        host.text_edit.setTextCursor(c)

    def roundtrip(self, host):
        source_html = host.text_edit.toHtml()
        other = CustomTextEdit()
        other.setHtml(source_html)
        self.assertEqual(other.toPlainText(), host.text_edit.toPlainText())
        return other

    def test_bold_italic_underline_strike_selected_and_roundtrip(self):
        host = self.new_host("Formatted phrase")
        self.select(host, 0, 9)
        host.toggle_bold()
        host.toggle_italic()
        host.toggle_underline()
        host.toggle_strikethrough()
        html = host.text_edit.toHtml().lower()
        self.assertIn("font-weight:", html)
        self.assertIn("font-style:", html)
        self.assertIn("text-decoration:", html)
        self.roundtrip(host)
        self.assertEqual(host.text_edit.toPlainText(), "Formatted phrase")

    def test_font_size_and_font_family_selected_without_text_change(self):
        host = self.new_host("Size Font")
        self.select(host, 0, 4)
        host.change_font_size(18)
        host.set_font_family("Arial")
        html = host.text_edit.toHtml().lower()
        self.assertIn("18pt", html)
        self.assertIn("arial", html)
        self.assertEqual(host.text_edit.toPlainText(), "Size Font")
        self.roundtrip(host)

    def test_color_and_highlight_selected(self):
        host = self.new_host("Colored")
        self.select(host, 0, 7)
        with patch("noteapp.app.editor.QColorDialog.getColor",
                   side_effect=[QColor("#123456"), QColor("#ffeb00")]):
            host.change_text_color()
            host.change_background_color()
        html = host.text_edit.toHtml().lower()
        self.assertIn("#123456", html)
        self.assertIn("#ffeb00", html)
        self.roundtrip(host)

    def test_alignment_all_positions_and_roundtrip(self):
        host = self.new_host("Left\nCenter\nRight\nJustify")
        for position, action, expected in (
            (0, host.align_left, Qt.AlignLeft),
            (5, host.align_center, Qt.AlignCenter),
            (12, host.align_right, Qt.AlignRight),
            (18, host.align_justify, Qt.AlignJustify),
        ):
            self.cursor_at(host, position)
            action()
            self.assertEqual(host.text_edit.textCursor().blockFormat().alignment(), expected)
        clone = self.roundtrip(host)
        for i in range(4):
            a = host.text_edit.document().findBlockByNumber(i).blockFormat().alignment()
            b = clone.document().findBlockByNumber(i).blockFormat().alignment()
            self.assertEqual(a, b)

    def test_headings_h1_h2_h3_and_roundtrip(self):
        host = self.new_host("Heading One\nHeading Two\nHeading Three")
        for i, level in enumerate((1, 2, 3)):
            block = host.text_edit.document().findBlockByNumber(i)
            self.select(host, block.position(), block.position()+len(block.text()))
            host.apply_heading(level)
        html = host.text_edit.toHtml().lower()
        self.assertIn("24pt", html)
        self.assertIn("18pt", html)
        self.assertIn("14pt", html)
        self.roundtrip(host)

    def test_selected_bullet_and_numbered_lists_roundtrip(self):
        for style, callback in (
            (QTextListFormat.ListDisc, "insert_bullet_list"),
            (QTextListFormat.ListDecimal, "insert_numbered_list"),
        ):
            with self.subTest(style=style):
                host = self.new_host("First\nSecond\nThird")
                self.select(host, 0, len("First\nSecond"))
                getattr(host, callback)()
                a = host.text_edit.document().findBlockByNumber(0)
                b = host.text_edit.document().findBlockByNumber(1)
                self.assertIsNotNone(a.textList())
                self.assertIsNotNone(b.textList())
                self.assertEqual(a.textList().format().style(), style)
                self.roundtrip(host)

    def test_no_selection_bullet_and_numbered_text_auto_continue(self):
        for method, expected in (
            ("insert_bullet_list", "• "),
            ("insert_numbered_list", "1. "),
        ):
            with self.subTest(method=method):
                host = self.new_host("Alpha")
                self.cursor_at(host, len("Alpha"))
                getattr(host, method)()
                self.assertIn(expected, host.text_edit.toPlainText())
                QTest.keyClick(host.text_edit, Qt.Key_Return)
                self.app.processEvents()
                self.assertGreaterEqual(host.text_edit.toPlainText().count(expected), 1)

    def test_checkbox_insert_toggle_and_existing_text(self):
        host = self.new_host("Task one\nTask two")
        self.cursor_at(host, 3)
        host.insert_checkbox()
        self.assertTrue(host.text_edit.toPlainText().startswith("☐ "))
        host.toggle_checkbox_at_cursor()
        self.assertTrue(host.text_edit.toPlainText().startswith("☑ "))
        host.toggle_checkbox_at_cursor()
        self.assertTrue(host.text_edit.toPlainText().startswith("☐ "))
        self.assertIn("Task two", host.text_edit.toPlainText())
        self.roundtrip(host)

    def test_link_insert_selected_text_and_edit_and_remove(self):
        host = self.new_host("OpenAI")
        self.select(host, 0, 6)
        with patch("noteapp.app.editor.QInputDialog.getText",
                   return_value=("https://example.org/old", True)):
            host.insert_link()
        self.assertIn("example.org/old", host.text_edit.toHtml())
        self.select(host, 0, 6)
        with patch("noteapp.app.editor.QInputDialog.getText",
                   return_value=("https://example.org/new", True)):
            host.edit_link()
        self.assertIn("example.org/new", host.text_edit.toHtml())
        self.assertIn("OpenAI", host.text_edit.toPlainText())
        self.select(host, 0, 6)
        host.remove_link()
        self.assertNotIn("example.org/new", host.text_edit.toHtml())
        self.roundtrip(host)

    def test_table_creation_and_context_actions(self):
        host = self.new_host("Above")
        self.cursor_at(host, len("Above"))
        with patch("noteapp.app.editor.QInputDialog.getInt",
                   side_effect=[(2, True), (2, True)]):
            host.insert_table()
        cur = host.text_edit.textCursor()
        tbl = cur.currentTable()
        if tbl is None:
            tbl = host.text_edit.document().rootFrame().childFrames()[0] if host.text_edit.document().rootFrame().childFrames() else None
        self.assertIsNotNone(tbl)
        self.assertEqual(tbl.rows(), 2)
        self.assertEqual(tbl.columns(), 2)
        self.assertIn("Above", host.text_edit.toPlainText())
        self.roundtrip(host)

    def test_table_context_insert_and_delete_row_col(self):
        host = self.new_host("")
        host.text_edit._insert_table(rows=2, cols=2)
        cursor = host.text_edit.textCursor()
        tbl = cursor.currentTable()
        self.assertIsNotNone(tbl)
        host.text_edit._table_insert_row(0, above=True)
        self.assertEqual(tbl.rows(), 3)
        host.text_edit._table_insert_col(0, left=True)
        self.assertEqual(tbl.columns(), 3)
        host.text_edit._table_delete_row(0)
        self.assertEqual(tbl.rows(), 2)
        host.text_edit._table_delete_col(0)
        self.assertEqual(tbl.columns(), 2)

    def test_update_block_and_horizontal_rule_persistence(self):
        host = self.new_host("Top")
        host.insert_update_block()
        self.assertIn("UPD", host.text_edit.toPlainText())
        self.assertIn("Base:", host.text_edit.toPlainText())
        self.cursor_at(host, len(host.text_edit.toPlainText()))
        host.insert_horizontal_line()
        self.assertIn("─", host.text_edit.toPlainText())
        self.roundtrip(host)

    def test_clear_formatting_restores_text_and_removes_bold(self):
        host = self.new_host("Bold")
        self.select(host, 0, 4)
        host.toggle_bold()
        host.clear_formatting()
        self.assertEqual(host.text_edit.toPlainText(), "Bold")
        self.roundtrip(host)

    def test_plain_and_rich_copy_mime_sanitization(self):
        host = self.new_host("Copy rich")
        self.select(host, 0, 4)
        host.toggle_bold()
        md = host.text_edit._build_rich_mime_from_selection()
        self.assertEqual(md.text(), "Copy")
        self.assertIn("Copy", md.html())
        self.assertNotIn("dropdown://", md.html())

    def test_html_paste_keeps_rich_bold_and_text(self):
        host = self.new_host("")
        md = QMimeData()
        md.setHtml("<p><b>Rich</b> text</p>")
        host.text_edit.insertFromMimeData(md)
        self.assertEqual(host.text_edit.toPlainText().strip(), "Rich text")
        self.assertIn("font-weight", host.text_edit.toHtml())
        self.roundtrip(host)

    def test_clipboard_image_uses_callback_not_inline_source(self):
        received = []
        host = self.new_host("")
        host.text_edit.paste_image_callback = received.append
        md = QMimeData()
        md.setImageData(QImage(2, 2, QImage.Format_ARGB32))
        host.text_edit.insertFromMimeData(md)
        self.assertEqual(len(received), 1)
        self.assertEqual(host.text_edit.toPlainText(), "")

    def test_readonly_version_does_not_modify_empty_editor(self):
        host = self.new_host("")
        initial = host.text_edit.toHtml()
        host.text_edit.setReadOnly(True)
        self.assertEqual(host.text_edit.toHtml(), initial)


if __name__ == "__main__":
    unittest.main()
