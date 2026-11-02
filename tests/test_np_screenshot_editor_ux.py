"""NP Screenshot: compact UI, object tools, clipboard, key movements and editable text."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCloseEvent, QImage, QPen, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolBar, QToolButton

SOURCE = Path(__file__).resolve().parents[1] / "Other_dev" / "screenshot.py"
SPEC = importlib.util.spec_from_file_location("np_screenshot_ux_under_test", SOURCE)
shot = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = shot
SPEC.loader.exec_module(shot)


def example_image():
    image = QImage(240, 170, QImage.Format_ARGB32)
    image.fill(QColor("#a1b2c3"))
    return image


class ObjectEditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.view = shot.CanvasView(example_image())
        self.addCleanup(self.view.close)
        self.view.set_tool(shot.Tool.PAN)

    def add_text(self, label="Пример", x=20, y=20):
        item = shot.EditableTextItem(label, 14, QColor("#334455"))
        item.setPos(QPointF(x, y))
        self.view._scene.addItem(item)
        item.setSelected(True)
        return item

    def add_rect(self, x=15, y=15):
        item = shot.ResizableRectItem(
            QRectF(0, 0, 50, 30), QPen(QColor("#123456"), 2), Qt.NoBrush)
        item.setPos(QPointF(x, y))
        self.view._scene.addItem(item)
        item.setSelected(True)
        return item

    def test_copy_and_paste_retains_vector_text_and_undo(self):
        original = self.add_text()
        self.assertTrue(self.view.copy_selected_objects())
        mime = QApplication.clipboard().mimeData()
        self.assertTrue(mime.hasFormat("application/x-np-screenshot-objects+json"))
        self.assertTrue(self.view.paste_selected_objects())
        texts = [obj for obj in self.view._resizable_items()
                 if isinstance(obj, shot.EditableTextItem)]
        self.assertEqual(len(texts), 2)
        self.assertEqual({x.text for x in texts}, {"Пример"})
        self.assertEqual({round(x.pos().x()) for x in texts}, {20, 36})
        self.view.undo()
        self.assertEqual(len(self.view._resizable_items()), 1)
        self.view.redo()
        self.assertEqual(len(self.view._resizable_items()), 2)

    def test_copy_sticker_remains_editable(self):
        sticker = shot.StickerItem(QPixmap.fromImage(example_image()), self.view.bg_img.size())
        self.view._scene.addItem(sticker)
        sticker.setSelected(True)
        self.assertTrue(self.view.copy_selected_objects())
        self.assertTrue(self.view.paste_selected_objects())
        self.assertEqual(len(self.view.stickers), 2)

    def test_nudge_by_one_and_ten_pixels_then_undo(self):
        item = self.add_rect()
        self.assertTrue(self.view.nudge_selected_objects(1, -1))
        self.assertEqual(item.pos(), QPointF(16, 14))
        self.assertTrue(self.view.nudge_selected_objects(10, -10))
        self.assertEqual(item.pos(), QPointF(26, 4))
        self.view.undo()
        moved = next(x for x in self.view._resizable_items()
                     if type(x) is shot.ResizableRectItem)
        self.assertEqual(moved.pos(), QPointF(16, 14))

    def test_alignment_one_object_to_image_and_multiple_to_each_other(self):
        item = self.add_rect(20, 25)
        self.assertTrue(self.view.align_selected_objects("left"))
        self.assertEqual(item.pos().x(), 0)
        self.view._scene.clearSelection()
        other = self.add_rect(100, 40)
        item.setSelected(True)
        self.assertTrue(self.view.align_selected_objects("top"))
        self.assertAlmostEqual(
            self.view._visible_object_rect(item).top(),
            self.view._visible_object_rect(other).top())
        self.assertFalse(self.view.align_selected_objects("not-a-valid-mode"))

    def test_text_color_and_font_size_undo(self):
        item = self.add_text()
        self.assertTrue(self.view.apply_selected_properties(
            color=QColor("#ff0000"), font_size=27))
        self.assertEqual(item.font_size, 27)
        self.assertEqual(item.text_color.name(), "#ff0000")
        self.view.undo()
        restored = next(x for x in self.view._resizable_items()
                        if isinstance(x, shot.EditableTextItem))
        self.assertEqual(restored.font_size, 14)
        self.assertEqual(restored.text_color.name(), "#334455")

    def test_arrow_and_rectangle_properties_change_line_geometry(self):
        rect = self.add_rect()
        self.assertTrue(self.view.apply_selected_properties(
            QColor("#c02211"), line_width=12))
        self.assertEqual(rect._pen.widthF(), 12)
        self.assertEqual(rect._pen.color().name(), "#c02211")
        self.view._scene.clearSelection()
        arrow = shot.ResizableArrowItem(QPointF(0, 0), QPointF(40, 40),
                                        QColor("#000000"), 3)
        self.view._scene.addItem(arrow)
        arrow.setSelected(True)
        self.assertTrue(self.view.apply_selected_properties(
            QColor("#336699"), line_width=8))
        self.assertEqual(arrow._width, 8)
        self.assertEqual(arrow._color.name(), "#336699")

    def test_unchanged_property_does_not_change_clean_state(self):
        item = self.add_text()
        self.view.mark_clean()
        self.assertFalse(self.view.apply_selected_properties(
            color=QColor("#334455"), font_size=14))
        self.assertFalse(self.view.is_dirty())

    def test_unchanged_properties_keep_redo_stack(self):
        original = self.add_text()
        self.view.push_undo()
        original.text = "Изменение"
        self.view.undo()
        restored = next(obj for obj in self.view._resizable_items()
                        if isinstance(obj, shot.EditableTextItem))
        restored.setSelected(True)
        self.assertEqual(len(self.view.redo_stack), 1)
        self.assertFalse(self.view.apply_selected_properties(
            color=QColor("#334455"), font_size=14))
        self.assertEqual(len(self.view.redo_stack), 1)
        self.view.redo()
        after = next(obj for obj in self.view._resizable_items()
                     if isinstance(obj, shot.EditableTextItem))
        self.assertEqual(after.text, "Изменение")

    def test_object_clipboard_survives_project_round_trip(self):
        text = self.add_text("Редактируемый объект")
        self.assertTrue(self.view.copy_selected_objects())
        self.assertTrue(self.view.paste_selected_objects())
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "changed.npshot"
            self.assertTrue(shot.save_editable_project(output, self.view))
            bg, ov, objects, count = shot.load_editable_project(output)
            self.assertEqual([x["type"] for x in objects], ["text", "text"])
            self.assertEqual([x["text"] for x in objects],
                             ["Редактируемый объект", "Редактируемый объект"])

    def test_double_click_invokes_text_edit(self):
        item = self.add_text("До", x=80, y=75)
        self.view.resize(500, 350)
        self.view.show()
        QTest.qWait(20)
        point = self.view.mapFromScene(item.sceneBoundingRect().center())
        with patch.object(shot.QInputDialog, "getText", return_value=("После", True)):
            QTest.mouseDClick(self.view.viewport(), Qt.LeftButton, pos=point)
        self.assertEqual(item.text, "После")


class EditorToolbarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = shot.EditorWindow(example_image())
        self.addCleanup(lambda: (self.editor.view.mark_clean(), self.editor.close()))

    def test_confirmation_dialog_has_only_russian_buttons(self):
        cases = (
            (
                shot.QMessageBox.Save | shot.QMessageBox.Discard | shot.QMessageBox.Cancel,
                shot.QMessageBox.Cancel,
                {
                    shot.QMessageBox.Save: "Сохранить",
                    shot.QMessageBox.Discard: "Не сохранять",
                    shot.QMessageBox.Cancel: "Отмена",
                },
            ),
            (
                shot.QMessageBox.Yes | shot.QMessageBox.No,
                shot.QMessageBox.No,
                {
                    shot.QMessageBox.Yes: "Да",
                    shot.QMessageBox.No: "Нет",
                },
            ),
        )
        for standard_buttons, default, expected in cases:
            inspected = {}

            def inspect(dialog):
                inspected["labels"] = {
                    standard: dialog.button(standard).text()
                    for standard in expected
                }
                inspected["default"] = dialog.defaultButton().text()
                return default

            with patch.object(shot.QMessageBox, "exec", new=inspect):
                result = shot._question_ru(
                    self.editor, "Подтверждение", "Проверка", standard_buttons, default
                )
            self.assertEqual(result, default)
            self.assertEqual(inspected["labels"], expected)
            self.assertEqual(inspected["default"], expected[default])

    def test_cancel_unsaved_close_keeps_editor_dirty(self):
        self.editor.view._set_dirty(True)
        close_event = QCloseEvent()
        with patch.object(shot, "_question_ru",
                          return_value=shot.QMessageBox.Cancel) as question:
            self.editor.closeEvent(close_event)
        self.assertFalse(close_event.isAccepted())
        self.assertTrue(self.editor.view.is_dirty())
        self.assertEqual(question.call_count, 1)

    def test_exactly_two_toolbar_rows_and_menus_keep_all_tools(self):
        self.assertEqual(len(self.editor.tb_rows), 2)
        self.assertEqual(len(self.editor.findChildren(QToolBar)), 2)
        buttons = self.editor.tb_rows[0].findChildren(QToolButton)
        menus = [button.menu() for button in buttons if button.menu()]
        self.assertGreaterEqual(len(menus), 6)
        names = {action.text() for menu in menus for action in menu.actions()}
        self.assertIn("✎ Перо", names)
        self.assertIn("➤ Стрелка", names)
        self.assertIn("🅣 Текст", names)
        self.assertIn("💾 Сохранить", names)

    def test_real_keyboard_shortcuts_move_selected_object(self):
        rect = shot.ResizableRectItem(
            QRectF(0, 0, 60, 30), QPen(QColor("#112233"), 2), Qt.NoBrush)
        self.editor.view._scene.addItem(rect)
        self.editor.view.set_tool(shot.Tool.PAN)
        rect.setSelected(True)
        self.editor.show()
        self.editor.view.setFocus()
        QTest.qWait(15)
        QTest.keyClick(self.editor.view.viewport(), Qt.Key_Right)
        self.assertEqual(rect.pos(), QPointF(1, 0))
        QTest.keyClick(self.editor.view.viewport(), Qt.Key_Down, Qt.ShiftModifier)
        self.assertEqual(rect.pos(), QPointF(1, 10))

    def test_regular_copy_without_selection_still_copies_flat_image(self):
        self.assertTrue(self.editor.copy_to_clipboard())
        self.assertEqual(QApplication.clipboard().image().size(), example_image().size())

    def test_copy_selected_object_uses_custom_mime_and_ctrl_v(self):
        obj = shot.EditableTextItem("Метка", 20, QColor("#001122"))
        self.editor.view._scene.addItem(obj)
        obj.setSelected(True)
        self.assertTrue(self.editor.copy_to_clipboard())
        self.editor.paste_from_clipboard()
        self.assertEqual(len(self.editor.view._resizable_items()), 2)

    def test_png_clipboard_still_replaces_current_image(self):
        src = QImage(40, 50, QImage.Format_ARGB32)
        src.fill(QColor("#ff0000"))
        QApplication.clipboard().setImage(src)
        self.editor.paste_from_clipboard()
        self.assertEqual(self.editor.view.bg_img.size(), src.size())


if __name__ == "__main__":
    unittest.main()
