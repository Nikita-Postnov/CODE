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

    def test_drag_existing_shape_by_center_with_drawing_tool(self):
        self.view.resize(500, 360)
        self.view.show()
        self.app.processEvents()
        self.view.set_tool(shot.Tool.RECT)
        item = self.add_rect(40, 40)
        item.setFlag(shot.QGraphicsItem.ItemIsMovable, False)
        before = QPointF(item.pos())
        start = self.view.mapFromScene(QPointF(65, 55))
        end = self.view.mapFromScene(QPointF(95, 75))
        QTest.mousePress(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(self.view.viewport(), end)
        QTest.mouseRelease(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, end)
        self.assertEqual(item.pos(), before + QPointF(30, 20))
        self.assertEqual(len(self.view._resizable_items()), 1)
        self.view.undo()
        self.assertEqual(self.view._resizable_items()[0].pos(), before)
        self.view.redo()
        self.assertEqual(self.view._resizable_items()[0].pos(), before + QPointF(30, 20))

    def test_new_shape_is_selected_and_can_be_undone(self):
        self.view.resize(500, 360)
        self.view.show()
        self.app.processEvents()
        self.view.set_tool(shot.Tool.RECT)
        start = self.view.mapFromScene(QPointF(20, 20))
        end = self.view.mapFromScene(QPointF(80, 70))
        QTest.mousePress(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(self.view.viewport(), end)
        QTest.mouseRelease(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, end)
        items = self.view._resizable_items()
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]._show_handles)
        self.assertTrue(items[0].isSelected())
        self.view.undo()
        self.assertFalse(self.view._resizable_items())

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

    def test_private_data_detector_maps_ocr_coordinates_and_ignores_prose(self):
        payload = {"lines": [
            {"text": "Контакты", "x": 100, "y": 10, "width": 120,
             "height": 14, "words": []},
            {"text": "person@example.com", "x": 100, "y": 42,
             "width": 190, "height": 20,
             "words": [{"text": "person@example.com", "x": 100, "y": 42,
                        "width": 190, "height": 20}]},
            {"text": "+7 (912) 345-67-89", "x": 100, "y": 80,
             "width": 200, "height": 20,
             "words": [
                 {"text": "+7", "x": 100, "y": 80, "width": 24, "height": 20},
                 {"text": "(912)", "x": 132, "y": 80, "width": 48, "height": 20},
                 {"text": "345-67-89", "x": 186, "y": 80, "width": 110, "height": 20}]},
            {"text": "api_key: abcdef0123456789", "x": 100, "y": 122,
             "width": 260, "height": 20,
             "words": [
                 {"text": "api_key:", "x": 100, "y": 122,
                  "width": 85, "height": 20},
                 {"text": "abcdef0123456789", "x": 195, "y": 122,
                  "width": 170, "height": 20}]},
            {"text": "2026-11-17", "x": 100, "y": 160,
             "width": 90, "height": 20,
             "words": [{"text": "2026-11-17", "x": 100, "y": 160,
                        "width": 90, "height": 20}]},
        ]}
        # WinRT OCR работает с увеличенной картинкой 480x340.
        matches = shot.find_private_data_regions(
            payload, shot.QSize(240, 170), shot.QSize(480, 340))
        self.assertEqual({item["kind"] for item in matches},
                         {"email", "phone", "secret"})
        email_rect = next(item["rect"] for item in matches
                          if item["kind"] == "email")
        self.assertTrue(email_rect.contains(shot.QPoint(80, 25)))
        self.assertTrue(all(isinstance(item["rect"], shot.QRect)
                            for item in matches))
        self.assertTrue(all("text" not in item for item in matches))

    def test_private_data_combines_separate_ocr_lines_into_five_targets(self):
        """В Windows OCR отдельные части одного значения бывают разными Lines."""
        def line(value, x, y, w=120, h=25):
            return {"text": value, "x": x, "y": y,
                    "width": w, "height": h,
                    "words": [{"text": value, "x": x, "y": y,
                               "width": w, "height": h}]}
        lines = [
            line("support.demo@example.com", 80, 50, 280),
            line("+7", 80, 125, 36), line("(912)", 124, 127, 55),
            line("345-67-89", 191, 124, 120),
            line("api_key:", 80, 200, 105),
            line("FAKEKEY1234567890", 193, 201, 230),
            line("password:", 80, 275, 130),
            line("DemoPass12345", 218, 276, 192),
            line("ghp_FAKEDEMOABCDEF1234567890", 80, 350, 350),
            # Вторая колонка содержит обычные сведения, которые не скрываем.
            line("TASK ID", 700, 25, 95), line("58216", 700, 50, 75),
            line("DATE", 700, 100, 70), line("2026-11-17", 700, 125, 135),
            line("PRICE", 700, 200, 95), line("7 900 RUB", 700, 225, 140),
        ]
        matches = shot.find_private_data_regions(
            {"lines": lines}, shot.QSize(1000, 500), shot.QSize(1000, 500))
        self.assertEqual(len(matches), 5)
        self.assertEqual(sorted(item["kind"] for item in matches),
                         ["email", "phone", "secret", "secret", "secret"])
        boxes = [item["rect"] for item in matches]
        for y in (50, 125, 200, 275, 350):
            self.assertTrue(any(box.contains(shot.QPoint(100, y + 10))
                                for box in boxes), f"Пропущена строка {y}")
        self.assertTrue(all(box.right() < 600 for box in boxes))

    def test_private_data_labels_recover_punctuation_damaged_values(self):
        """Подписи API KEY/PASSWORD/PHONE и текст на строке ниже."""
        def item(value, x, y):
            return {"text": value, "x": x, "y": y,
                    "width": 280, "height": 23,
                    "words": [{"text": value, "x": x, "y": y,
                               "width": 280, "height": 23}]}
        payload = {"lines": [
            item("PHONE", 35, 40),
            item("+7(912)345-67-8O", 35, 75),  # OCR спутал 0 с O
            item("API KEY", 35, 150),
            item("FAKEKEY1234567890", 35, 185),
            item("PASSWORD", 35, 255),
            item("DemoPass12345", 35, 290),
            item("TASK ID", 650, 40),
            item("58216", 650, 75),
            item("DATE", 650, 150),
            item("2026-11-17", 650, 185),
        ]}
        matches = shot.find_private_data_regions(
            payload, shot.QSize(1000, 450), shot.QSize(1000, 450))
        self.assertEqual(len(matches), 3)
        self.assertCountEqual([m["kind"] for m in matches],
                              ["phone", "secret", "secret"])
        self.assertTrue(all(m["rect"].left() < 350 for m in matches))

    def test_private_data_review_fit_and_native_zoom(self):
        picture = QImage(1400, 1000, QImage.Format_ARGB32)
        picture.fill(Qt.white)
        proposals = [{"kind": "phone", "rect": shot.QRect(30, 180, 250, 30)}]
        dialog = shot.PrivateDataReviewDialog(picture, proposals)
        try:
            dialog.resize(970, 730)
            self.app.processEvents()
            dialog._refresh_preview()
            self.assertLess(dialog.preview_scale, 1.0)
            fitted = dialog.preview.pixmap().size()
            self.assertLess(fitted.width(), picture.width())
            dialog.zoom_choice.setCurrentIndex(1)
            self.assertEqual(dialog.zoom_choice.currentData(), "native")
            self.assertEqual(dialog.preview_scale, 1.0)
            self.assertEqual(dialog.preview.pixmap().size(), picture.size())
        finally:
            dialog.close()

    def test_private_data_reviewer_allows_selective_masking_without_values(self):
        image = example_image()
        matches = [
            {"kind": "email", "rect": shot.QRect(5, 8, 95, 20)},
            {"kind": "phone", "rect": shot.QRect(5, 40, 95, 20)},
        ]
        dialog = shot.PrivateDataReviewDialog(image, matches)
        try:
            self.assertEqual(len(dialog.selected_rects()), 2)
            self.assertNotIn("person@", dialog.results.item(0).text())
            dialog.results.item(1).setCheckState(Qt.Unchecked)
            self.assertEqual(dialog.selected_rects(),
                             [shot.QRect(5, 8, 95, 20)])
        finally:
            dialog.close()

    def test_private_redaction_deletes_original_pixels_and_undo_history(self):
        original = QColor("#ee0000")
        first = shot.QRect(25, 30, 100, 24)
        second = shot.QRect(150, 75, 50, 35)
        painter = shot.QPainter(self.view.bg_img)
        painter.fillRect(first, original)
        painter.end()
        text_item = self.add_text("SECRET_PRIVATE_TEXT", x=25, y=30)
        self.view.push_undo()
        painter = shot.QPainter(self.view.ov_img)
        painter.fillRect(second, QColor("#aa0099"))
        painter.end()
        self.view._refresh()
        self.assertTrue(self.view.apply_private_redactions([first, second]))
        self.assertEqual(len(self.view.undo_stack), 0)
        self.assertEqual(len(self.view.redo_stack), 0)
        self.assertFalse(self.view._resizable_items())
        self.assertFalse(self.view.ov_img.pixelColor(155, 80).alpha())
        self.assertEqual(self.view.bg_img.pixelColor(28, 32).name(), "#161616")
        self.assertEqual(self.view.bg_img.pixelColor(160, 80).name(), "#161616")
        self.assertEqual(QApplication.clipboard().image()
                         .pixelColor(28, 32).name(), "#161616")
        self.assertEqual(self.view.bg_img.pixelColor(5, 5).name(), "#a1b2c3")
        self.assertTrue(self.view.is_dirty())
        self.view.undo()
        self.assertEqual(self.view.bg_img.pixelColor(28, 32).name(), "#161616")
        self.assertFalse(any(isinstance(it, shot.EditableTextItem)
                             for it in self.view._resizable_items()))

    def test_private_redaction_writes_only_redacted_project_layers(self):
        image = QImage(240, 170, QImage.Format_ARGB32)
        image.fill(QColor("white"))
        view = shot.CanvasView(image)
        self.addCleanup(view.close)
        item = shot.EditableTextItem(
            "VISIBLE_SECRET_9900", 17, QColor("black"))
        item.setPos(shot.QPointF(15, 15))
        view._scene.addItem(item)
        mask = shot.QRect(10, 10, 220, 45)
        self.assertTrue(view.apply_private_redactions([mask]))
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "redacted.npshot"
            self.assertTrue(shot.save_editable_project(target, view))
            with __import__("zipfile").ZipFile(target) as archive:
                self.assertNotIn(b"VISIBLE_SECRET_9900",
                                 archive.read("project.json"))
            bg, ov, shapes, _ = shot.load_editable_project(target)
            self.assertFalse(shapes)
            self.assertEqual(bg.pixelColor(32, 22).name(), "#161616")
            self.assertEqual(ov.pixelColor(32, 22).alpha(), 0)
            png = Path(tmp) / "public.png"
            self.assertTrue(view.save_rendered_image(png))
            self.assertEqual(QImage(str(png)).pixelColor(32, 22).name(),
                             "#161616")

    def test_multiline_edit_dialog_has_fonts_styles_alignment_and_autofit(self):
        item = self.add_text("Первая строка")
        dlg = shot.TextEditorDialog(item, self.view)
        try:
            self.assertEqual(dlg.text_edit.toPlainText(), "Первая строка")
            dlg.text_edit.setPlainText("Первая строка\nВторая строка")
            dlg.size_box.setValue(27)
            dlg.bold_check.setChecked(True)
            dlg.italic_check.setChecked(True)
            dlg.align_combo.setCurrentIndex(dlg.align_combo.findData("right"))
            values = dlg.values()
            self.assertIn("\n", values["text"])
            self.assertEqual(values["font_size"], 27)
            self.assertTrue(values["bold"])
            self.assertTrue(values["italic"])
            self.assertEqual(values["alignment"], "right")
            self.assertTrue(values["auto_fit"])
        finally:
            dlg.close()

    def test_apply_multiline_text_and_style_can_undo(self):
        item = self.add_text("Начало")
        original_height = item._rect.height()
        def edit(dialog):
            dialog.text_edit.setPlainText("Заголовок\nПодробный комментарий")
            dialog.size_box.setValue(25)
            dialog.bold_check.setChecked(True)
            dialog.align_combo.setCurrentIndex(
                dialog.align_combo.findData("center"))
            return shot.QDialog.Accepted
        with patch.object(shot.TextEditorDialog, "exec", new=edit):
            self.assertTrue(self.view.edit_selected_text(item))
        self.assertIn("\n", item.text)
        self.assertTrue(item.bold)
        self.assertEqual(item.alignment, "center")
        self.assertGreater(item._rect.height(), original_height)
        self.view.undo()
        reverted = next(obj for obj in self.view._resizable_items()
                        if isinstance(obj, shot.EditableTextItem))
        self.assertEqual(reverted.text, "Начало")
        self.assertFalse(reverted.bold)
        self.view.redo()
        redone = next(obj for obj in self.view._resizable_items()
                      if isinstance(obj, shot.EditableTextItem))
        self.assertIn("\n", redone.text)
        self.assertEqual(redone.alignment, "center")

    def test_multiline_raster_export_uses_alignment_and_keeps_two_lines(self):
        item = shot.EditableTextItem(
            "Первая строка\nВторая", 19, QColor("#112233"),
            alignment="left", auto_fit=False)
        item._rect = QRectF(0, 0, 280, 105)

        def painted():
            canvas = QImage(300, 125, QImage.Format_ARGB32)
            canvas.fill(QColor("white"))
            painter = shot.QPainter(canvas)
            item.rasterize_to(painter)
            painter.end()
            pixels = [(x, y) for y in range(125) for x in range(300)
                      if canvas.pixelColor(x, y) != QColor("white")]
            self.assertTrue(pixels)
            return pixels

        left_pixels = painted()
        item.alignment = "right"
        right_pixels = painted()
        self.assertGreater(min(x for x, y in right_pixels),
                           min(x for x, y in left_pixels) + 40)
        self.assertGreater(max(y for x, y in right_pixels) -
                           min(y for x, y in right_pixels), 25)

    def test_dialog_cancel_does_not_dirty_clean_editor(self):
        item = self.add_text("Без изменений")
        self.view.mark_clean()
        previous = len(self.view.undo_stack)
        with patch.object(shot.TextEditorDialog, "exec",
                          return_value=shot.QDialog.Rejected):
            self.assertFalse(self.view.edit_selected_text(item))
        self.assertEqual(len(self.view.undo_stack), previous)
        self.assertFalse(self.view.is_dirty())

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
        def edit(dialog):
            dialog.text_edit.setPlainText("После")
            return shot.QDialog.Accepted

        with patch.object(shot.TextEditorDialog, "exec", new=edit):
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
        self.assertIn("◉ Затемнение вокруг", names)
        self.assertIn("💬 Выноска", names)
        self.assertIn("📏 Линейка", names)
        self.assertIn("💾 Сохранить", names)

    def test_spotlight_ruler_and_callout_draw_into_overlay_layer(self):
        image = QImage(120, 90, QImage.Format_ARGB32)
        image.fill(QColor("#ffffff"))
        overlay = QImage(image.size(), QImage.Format_ARGB32)
        overlay.fill(Qt.transparent)
        painter = shot.QPainter(overlay)
        shot.draw_spotlight(painter, shot.QRect(30, 20, 50, 35), image.size())
        painter.end()
        self.assertGreater(overlay.pixelColor(5, 5).alpha(), 0)
        self.assertEqual(overlay.pixelColor(40, 30).alpha(), 0)

        painter = shot.QPainter(overlay)
        shot.draw_ruler(painter, QPoint(5, 70), QPoint(100, 70),
                        QColor("#ff0000"), 2)
        shot.draw_callout(painter, shot.QRect(10, 5, 70, 25),
                          "Пояснение", QColor("#333333"))
        painter.end()
        self.assertGreater(overlay.pixelColor(50, 70).alpha(), 0)
        self.assertGreater(overlay.pixelColor(20, 10).alpha(), 0)

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
