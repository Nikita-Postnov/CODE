"""Project round-trip, vector annotations, editable text, safe writes and corrupt file handling."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPen, QPixmap
from PySide6.QtWidgets import QApplication

SOURCE = Path(__file__).resolve().parents[1] / "Other_dev" / "screenshot.py"
SPEC = importlib.util.spec_from_file_location("np_screenshot_project_under_test", SOURCE)
shot = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = shot
SPEC.loader.exec_module(shot)


def image(color="#3070c0"):
    result = QImage(280, 180, QImage.Format_ARGB32)
    result.fill(QColor(color))
    return result


class ProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.view = shot.CanvasView(image())
        self.addCleanup(self.view.close)

    def populate_shapes(self):
        text = shot.EditableTextItem("Подпись 1", 20, QColor("#ee2020"))
        text.setPos(QPointF(18, 22))
        self.view._scene.addItem(text)
        arrow = shot.ResizableArrowItem(
            QPointF(4, 8), QPointF(88, 44), QColor("#20ee20"), 5)
        arrow.setPos(QPointF(45, 12))
        self.view._scene.addItem(arrow)
        rect = shot.ResizableRectItem(
            QRectF(7, 8, 90, 40), QPen(QColor("#7d34da"), 3),
            QColor("#ff00ff"))
        rect.setPos(QPointF(100, 60))
        self.view._scene.addItem(rect)
        sticker = shot.StickerItem(QPixmap.fromImage(image("#ffdd00")),
                                   self.view.bg_img.size())
        sticker.setPos(QPointF(30, 40))
        self.view._scene.addItem(sticker)
        self.view.stickers.append(sticker)
        return text

    def test_project_saves_both_layers_shapes_and_counter(self):
        self.populate_shapes()
        self.view.step_counter = 12
        painter = shot.QPainter(self.view.ov_img)
        painter.fillRect(shot.QRect(0, 0, 11, 11), QColor("#aabbcc"))
        painter.end()
        output = self.folder / "capture.npshot"
        self.assertTrue(shot.save_editable_project(output, self.view))
        bg, ov, shapes, count = shot.load_editable_project(output)
        self.assertEqual(bg.pixelColor(0, 0).name(), "#3070c0")
        self.assertEqual(ov.pixelColor(0, 0).name(), "#aabbcc")
        self.assertEqual({x["type"] for x in shapes},
                         {"text", "arrow", "rect", "sticker"})
        self.assertEqual(count, 12)
        self.assertEqual(next(x["text"] for x in shapes if x["type"] == "text"),
                         "Подпись 1")
        self.assertIsInstance(next(x["pix"] for x in shapes
                                   if x["type"] == "sticker"), QPixmap)

        restored = shot.CanvasView(bg)
        self.addCleanup(restored.close)
        restored.ov_img = ov
        restored.step_counter = count
        restored._restore_scene(shapes)
        restored._refresh()
        snap = restored._snapshot_scene()
        self.assertEqual(len(snap), 4)
        self.assertEqual(next(x["text"] for x in snap if x["type"] == "text"), "Подпись 1")
        self.assertEqual(next(x["width"] for x in snap if x["type"] == "arrow"), 5)

    def test_text_can_be_edited_and_undone(self):
        item = shot.EditableTextItem("Старый текст", 14, QColor("#e60011"))
        self.view._scene.addItem(item)
        self.view.set_tool(shot.Tool.PAN)
        item.setSelected(True)
        with patch.object(shot.QInputDialog, "getText", return_value=("Новый текст", True)):
            self.assertTrue(self.view.edit_selected_text())
        self.assertEqual(item.text, "Новый текст")
        self.assertEqual(len(self.view.undo_stack), 1)
        self.view.undo()
        self.assertEqual(
            next(it.text for it in self.view._scene.items()
                 if isinstance(it, shot.EditableTextItem)), "Старый текст")
        self.view.redo()
        self.assertEqual(
            next(it.text for it in self.view._scene.items()
                 if isinstance(it, shot.EditableTextItem)), "Новый текст")

    def test_atomic_save_failure_keeps_original_archive(self):
        target = self.folder / "existing.npshot"
        self.assertTrue(shot.save_editable_project(target, self.view))
        before = target.read_bytes()
        with patch.object(shot.os, "replace", side_effect=OSError("locked")):
            self.assertFalse(shot.save_editable_project(target, self.view))
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(list(self.folder.glob("*.tmp")), [])

    def test_corrupt_project_is_rejected(self):
        bad = self.folder / "corrupt.npshot"
        bad.write_bytes(b"not an archive")
        with self.assertRaises(shot.zipfile.BadZipFile):
            shot.load_editable_project(bad)

    def test_unexpected_members_and_unsupported_format_rejected(self):
        archive = self.folder / "tampered.npshot"
        self.assertTrue(shot.save_editable_project(archive, self.view))
        with shot.zipfile.ZipFile(archive, "a") as zipf:
            zipf.writestr("../escape.py", "print('unsafe')")
        with self.assertRaises(ValueError):
            shot.load_editable_project(archive)

    def test_editor_can_open_project_without_overwriting_original(self):
        self.populate_shapes()
        file = self.folder / "project.npshot"
        self.assertTrue(shot.save_editable_project(file, self.view))
        editor = shot.EditorWindow(image("#abcdef"))
        self.addCleanup(editor.close)
        with patch.object(shot.QFileDialog, "getOpenFileName",
                          return_value=(str(file), "")), \
             patch.object(shot, "_register_editor_in_launcher"):
            self.assertTrue(editor.open_project())
        new = [w for w in QApplication.topLevelWidgets()
               if isinstance(w, shot.EditorWindow) and w is not editor]
        self.assertTrue(new)
        for window in new:
            self.addCleanup(window.close)
        self.assertEqual(new[0].view.bg_img.pixelColor(0, 0).name(), "#3070c0")
        self.assertEqual(editor.view.bg_img.pixelColor(0, 0).name(), "#abcdef")

    def test_project_opens_from_launcher_and_restores_project_name(self):
        self.populate_shapes()
        project = self.folder / "saved_project.npshot"
        self.assertTrue(shot.save_editable_project(project, self.view))
        with patch.object(shot.Launcher, "_install_global_hotkey"):
            launcher = shot.Launcher()
        self.addCleanup(lambda: (setattr(launcher, "_real_quit", True), launcher.close()))
        with patch.object(shot.QFileDialog, "getOpenFileName",
                          return_value=(str(project), "")):
            launcher._open_project()
        self.assertEqual(len(launcher._editors), 1)
        editor = launcher._editors[0]
        self.assertEqual(editor._last_project_path, project)
        self.assertIn("saved_project.npshot", editor.windowTitle())
        self.assertEqual(len(editor.view._snapshot_scene()), 4)
        editor.close()

    def test_editor_corrupt_project_does_not_mutate_current(self):
        file = self.folder / "corrupt.npshot"
        file.write_bytes(b"x")
        editor = shot.EditorWindow(image("#123456"))
        self.addCleanup(editor.close)
        with patch.object(shot.QFileDialog, "getOpenFileName",
                          return_value=(str(file), "")), \
             patch.object(shot.QMessageBox, "warning"):
            self.assertFalse(editor.open_project())
        self.assertEqual(editor.view.bg_img.pixelColor(0, 0).name(), "#123456")


if __name__ == "__main__":
    unittest.main()
