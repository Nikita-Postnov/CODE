"""Regression tests for the actual NP Notes toolbar/editor callback.

Only synthetic in-memory documents, with Qt offscreen. No real notes, GitHub
credentials, sync state, or user files are accessed.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Other_dev"))

try:
    from PySide6.QtGui import QFontMetrics, QImage, QTextCursor, QTextOption
    from PySide6.QtWidgets import QApplication, QPushButton, QMessageBox, QWidget
    from noteapp.widgets.text_edit import CustomTextEdit
    from noteapp.app.editor import EditorMixin
except ImportError:
    QApplication = None


class FakeNotesApp(QWidget, EditorMixin):
    """Match NotesApp's real _set_unsaved(flag: bool) signature."""

    def __init__(self):
        super().__init__()
        self.text_edit = CustomTextEdit(parent=self)
        self.text_edit.setFixedSize(640, 220)
        self.text_edit.setLineWrapMode(CustomTextEdit.LineWrapMode.NoWrap)
        self.text_edit.setWordWrapMode(QTextOption.NoWrap)
        self.text_edit.setStyleSheet(
            "QTextEdit { background: #2d2d2d; color: #eeeeee; border: 0; }"
        )
        self.unsaved_calls = []
        self.line_button = QPushButton("▁", self)
        self.line_button.clicked.connect(self.insert_horizontal_line)
        self.repair_button = QPushButton("═", self)
        self.repair_button.clicked.connect(self.restore_legacy_horizontal_lines)

    def _set_unsaved(self, flag: bool):
        self.unsaved_calls.append(flag)


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class HorizontalLineRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def new_editor(self, text):
        obj = FakeNotesApp()
        obj.text_edit.setPlainText(text)
        obj.text_edit.show()
        self.app.processEvents()
        return obj

    def test_toolbar_clicked_calls_real_signature_and_inserts_visible_line(self):
        editor = self.new_editor("Before\nAfter")
        cursor = editor.text_edit.textCursor()
        cursor.setPosition(len("Before"))
        editor.text_edit.setTextCursor(cursor)
        editor.line_button.click()
        output = editor.text_edit.toPlainText()
        lines = output.splitlines()
        self.assertEqual(lines[0], "Before")
        self.assertEqual(lines[-1], "After")
        rule = [line for line in lines if "─" in line]
        self.assertEqual(len(rule), 1)
        self.assertEqual(set(rule[0]), {"─"})
        self.assertGreater(len(rule[0]), 40)
        self.assertEqual(editor.unsaved_calls, [True])

        metrics = QFontMetrics(editor.text_edit.textCursor().charFormat().font())
        self.assertGreater(editor.text_edit.viewport().width(), 100)
        self.assertIn("─", editor.text_edit.toHtml())
        cloned = CustomTextEdit()
        cloned.setHtml(editor.text_edit.toHtml())
        self.assertEqual(cloned.toPlainText(), output)

    def test_real_qt_viewport_paints_visible_rule_after_button_click(self):
        editor = self.new_editor("Above")
        cursor = editor.text_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        editor.text_edit.setTextCursor(cursor)
        editor.line_button.click()
        self.app.processEvents()
        image = editor.text_edit.viewport().grab().toImage().convertToFormat(
            QImage.Format.Format_RGBA8888
        )
        values = []
        for y in range(0, min(140, image.height())):
            lit = sum(
                1 for x in range(15, image.width() - 15)
                if (lambda color: color.red() >= 110
                    and color.green() >= 110
                    and color.blue() >= 110)(image.pixelColor(x, y))
            )
            values.append((lit, y))
        best = max(values)
        print("NP_NOTES_RULE_PIXELS=" + str(best[0]), flush=True)
        self.assertGreater(
            best[0], int((image.width() - 30) * 0.55),
            "Actual NP Notes-style dark editor did not paint a long rule",
        )

    def test_existing_selected_text_is_not_deleted(self):
        editor = self.new_editor("Important\nOther")
        cursor = editor.text_edit.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(9, QTextCursor.KeepAnchor)
        editor.text_edit.setTextCursor(cursor)
        editor.line_button.click()
        plain = editor.text_edit.toPlainText()
        self.assertIn("Important", plain)
        self.assertIn("Other", plain)
        self.assertIn("─", plain)

    def test_second_line_insertion_does_not_overwrite_first(self):
        editor = self.new_editor("Above")
        cursor = editor.text_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        editor.text_edit.setTextCursor(cursor)
        editor.line_button.click()
        editor.line_button.click()
        self.assertEqual(
            len([line for line in editor.text_edit.toPlainText().splitlines()
                 if len(line) > 40 and set(line) == {"─"}]), 2
        )

    def test_explicit_target_dot_only(self):
        editor = self.new_editor("Above\n.\nBelow\n.")
        cursor = editor.text_edit.textCursor()
        cursor.setPosition(len("Above\n"))
        editor.text_edit.setTextCursor(cursor)
        editor.line_button.click()
        plain = editor.text_edit.toPlainText()
        self.assertIn("Above", plain)
        self.assertIn("Below", plain)
        self.assertIn("─", plain)
        self.assertEqual(plain.splitlines()[-1], ".")

    def test_restore_existing_standalone_dots_on_approval(self):
        editor = self.new_editor("Top\n.\nMiddle\n.\nEnd. A real dot.")
        with patch("noteapp.app.editor.QMessageBox.question",
                   return_value=QMessageBox.Yes) as question:
            editor.repair_button.click()
        self.assertEqual(question.call_count, 1)
        plain = editor.text_edit.toPlainText()
        self.assertNotIn("\n.\n", plain)
        self.assertEqual(sum(1 for line in plain.splitlines()
                             if len(line)>40 and set(line)=={"─"}), 2)
        self.assertIn("End. A real dot.", plain)
        self.assertEqual(editor.unsaved_calls, [True])
        reopened = CustomTextEdit()
        reopened.setHtml(editor.text_edit.toHtml())
        self.assertEqual(reopened.toPlainText(), plain)


    def test_replacing_old_dot_does_not_add_blank_line_before_heading(self):
        editor = self.new_editor("Above\n.\nHeading")
        cursor = editor.text_edit.textCursor()
        cursor.setPosition(len("Above\n"))
        editor.text_edit.setTextCursor(cursor)
        editor.line_button.click()
        lines = editor.text_edit.toPlainText().splitlines()
        self.assertEqual(len(lines), 3, lines)
        self.assertEqual(lines[0], "Above")
        self.assertGreater(len(lines[1]), 40)
        self.assertEqual(set(lines[1]), {"─"})
        self.assertEqual(lines[2], "Heading")
        copy = CustomTextEdit()
        copy.setHtml(editor.text_edit.toHtml())
        self.assertEqual(copy.toPlainText(), editor.text_edit.toPlainText())

    def test_inserting_into_blank_paragraph_does_not_duplicate_blank_line(self):
        editor = self.new_editor("Above\n\nHeading")
        cursor = editor.text_edit.textCursor()
        cursor.setPosition(len("Above\n"))
        editor.text_edit.setTextCursor(cursor)
        editor.line_button.click()
        lines = editor.text_edit.toPlainText().splitlines()
        self.assertEqual(len(lines), 3, lines)
        self.assertEqual(lines[0], "Above")
        self.assertEqual(set(lines[1]), {"─"})
        self.assertEqual(lines[2], "Heading")

    def test_inserting_in_middle_preserves_suffix_without_empty_paragraph(self):
        editor = self.new_editor("BeforeAfter")
        cursor = editor.text_edit.textCursor()
        cursor.setPosition(len("Before"))
        editor.text_edit.setTextCursor(cursor)
        editor.line_button.click()
        lines = editor.text_edit.toPlainText().splitlines()
        self.assertEqual(len(lines), 3, lines)
        self.assertEqual(lines[0], "Before")
        self.assertEqual(set(lines[1]), {"─"})
        self.assertEqual(lines[2], "After")

    def test_repair_removes_only_one_old_blank_after_rule_and_keeps_heading(self):
        rule = "─" * 60
        original = "Before\n" + rule + "\n\nHeading\nElse\n\nIntended blank"
        editor = self.new_editor(original)
        before = editor.text_edit.toPlainText()
        self.assertEqual(before, original)
        with patch("noteapp.app.editor.QMessageBox.question",
                   return_value=QMessageBox.Yes) as question:
            editor.repair_button.click()
        self.assertEqual(question.call_count, 1)
        self.assertIn("Пустых строк после линий: 1", question.call_args.args[2])
        expected = "Before\n" + rule + "\nHeading\nElse\n\nIntended blank"
        self.assertEqual(editor.text_edit.toPlainText(), expected)
        copy = CustomTextEdit()
        copy.setHtml(editor.text_edit.toHtml())
        self.assertEqual(copy.toPlainText(), expected)

    def test_declining_repair_of_old_gap_preserves_document_exactly(self):
        rule = "─" * 60
        editor = self.new_editor("Before\\n" + rule + "\\n\\nHeading")
        original = editor.text_edit.toHtml()
        with patch("noteapp.app.editor.QMessageBox.question",
                   return_value=QMessageBox.No) as question:
            editor.repair_button.click()
        self.assertEqual(question.call_count, 1)
        self.assertEqual(editor.text_edit.toHtml(), original)
        self.assertEqual(editor.unsaved_calls, [])

    def test_declining_repair_does_not_modify_text(self):
        editor = self.new_editor("Top\n.\nBottom")
        initial = editor.text_edit.toHtml()
        with patch("noteapp.app.editor.QMessageBox.question",
                   return_value=QMessageBox.No):
            editor.repair_button.click()
        self.assertEqual(editor.text_edit.toHtml(), initial)
        self.assertEqual(editor.unsaved_calls, [])


if __name__ == "__main__":
    unittest.main()
