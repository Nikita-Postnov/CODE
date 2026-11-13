"""История скриншотов и быстрые действия: портативность, приватность и регрессии."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication, QMessageBox

SOURCE = Path(__file__).resolve().parents[1] / "Other_dev" / "screenshot.py"
SPEC = importlib.util.spec_from_file_location("np_screenshot_history_under_test", SOURCE)
shot = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = shot
SPEC.loader.exec_module(shot)


def sample_image(color="#a422cc"):
    img = QImage(100, 80, QImage.Format_ARGB32)
    img.fill(QColor(color))
    return img


class HistoryStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.cfg = patch.object(shot, "SCREENSHOT_HISTORY_SETTINGS",
                                self.folder / "Data" / "screenshot_history_settings.json")
        self.hist = patch.object(shot, "SCREENSHOT_HISTORY_DIR",
                                 self.folder / "Data" / "ScreenshotHistory")
        self.cfg.start()
        self.hist.start()
        self.addCleanup(self.cfg.stop)
        self.addCleanup(self.hist.stop)

    def test_history_and_quick_actions_disabled_by_default(self):
        self.assertEqual(shot.load_capture_preferences(),
                         {"quick_actions": False, "history_enabled": False,
                          "capture_target": "area", "capture_kind": "shot"})
        self.assertFalse(shot.SCREENSHOT_HISTORY_DIR.exists())

    def test_preferences_are_portable_and_written_atomically(self):
        self.assertTrue(shot.save_capture_preferences(
            {"quick_actions": True, "history_enabled": False}))
        self.assertEqual(shot.load_capture_preferences(),
                         {"quick_actions": True, "history_enabled": False,
                          "capture_target": "area", "capture_kind": "shot"})
        self.assertEqual(list(shot.SCREENSHOT_HISTORY_SETTINGS.parent.glob("*.tmp")), [])

    def test_broken_preferences_fail_closed_without_dropping_history(self):
        shot.SCREENSHOT_HISTORY_SETTINGS.parent.mkdir(parents=True)
        shot.SCREENSHOT_HISTORY_SETTINGS.write_text("{not json", encoding="utf-8")
        self.assertFalse(shot.load_capture_preferences()["history_enabled"])
        self.assertEqual(shot.SCREENSHOT_HISTORY_SETTINGS.read_text(encoding="utf-8"), "{not json")

    def test_capture_action_and_target_restore_after_restarting_capture(self):
        self.assertTrue(shot.remember_capture_selection("ocr", "window"))
        self.assertEqual(shot.load_capture_preferences()["capture_kind"], "ocr")
        self.assertEqual(shot.load_capture_preferences()["capture_target"], "window")
        self.assertEqual(shot.preferred_capture_mode(shot.SelectionOverlay.MODE_SHOT),
                         shot.SelectionOverlay.MODE_OCR_WINDOW)
        self.assertEqual(shot.preferred_capture_mode(shot.SelectionOverlay.MODE_RECORD),
                         shot.SelectionOverlay.MODE_RECORD_WINDOW)
        self.assertEqual(shot.preferred_capture_mode(shot.SelectionOverlay.MODE_WINDOW),
                         shot.SelectionOverlay.MODE_WINDOW)

    def test_switching_target_preserves_action_and_other_preferences(self):
        self.assertTrue(shot.save_capture_preferences({
            "quick_actions": True, "history_enabled": True,
            "capture_kind": "record", "capture_target": "area",
        }))
        self.assertTrue(shot.remember_capture_target("window"))
        self.assertEqual(shot.load_capture_preferences(), {
            "quick_actions": True, "history_enabled": True,
            "capture_kind": "record", "capture_target": "window",
        })

    def test_invalid_saved_capture_choice_uses_defaults(self):
        shot.SCREENSHOT_HISTORY_SETTINGS.parent.mkdir(parents=True)
        shot.SCREENSHOT_HISTORY_SETTINGS.write_text(
            '{"capture_kind":"bad","capture_target":"bad"}', encoding="utf-8")
        self.assertEqual(shot.load_capture_preferences()["capture_kind"], "shot")
        self.assertEqual(shot.load_capture_preferences()["capture_target"], "area")
        self.assertFalse(shot.remember_capture_selection("bad", "area"))

    def test_capture_archive_is_unique_and_persists_without_automatic_deletion(self):
        first = shot.archive_screenshot(sample_image())
        second = shot.archive_screenshot(sample_image("#11ccbb"))
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertNotEqual(first, second)
        self.assertEqual(len(shot.screenshot_history_files()), 2)
        self.assertEqual(len(shot.screenshot_history_files(limit=1)), 1)
        self.assertEqual(shot.screenshot_history_files(limit=0), [])
        self.assertEqual(QImage(str(first)).pixelColor(0, 0).name(), "#a422cc")
        self.assertEqual(QImage(str(second)).pixelColor(0, 0).name(), "#11ccbb")
        self.assertTrue(first.exists())

    def test_failed_archive_does_not_leave_partial_image(self):
        with patch.object(shot, "save_image_atomically", return_value=False):
            self.assertIsNone(shot.archive_screenshot(sample_image()))
        self.assertEqual(shot.screenshot_history_files(), [])


class HistoryGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.hist = patch.object(shot, "SCREENSHOT_HISTORY_DIR",
                                 Path(self.tmp.name) / "ScreenshotHistory")
        self.hist.start()
        self.addCleanup(self.hist.stop)

    def test_history_open_copy_and_explicit_delete(self):
        image = sample_image()
        path = shot.archive_screenshot(image)
        launcher = Mock()
        dialog = shot.ScreenshotHistoryDialog(launcher)
        self.addCleanup(dialog.close)
        self.assertEqual(dialog.items.count(), 1)
        dialog.open_selected()
        launcher._open_editor_image.assert_called_once()
        self.assertEqual(launcher._open_editor_image.call_args.args[0].size(), image.size())
        dialog.copy_selected()
        self.assertEqual(QApplication.clipboard().image().size(), image.size())
        with patch.object(shot, "_question_ru", return_value=QMessageBox.No):
            dialog.delete_selected()
        self.assertTrue(path.exists())
        with patch.object(shot, "_question_ru", return_value=QMessageBox.Yes):
            dialog.delete_selected()
        self.assertFalse(path.exists())
        self.assertEqual(dialog.items.count(), 0)

    def test_rejects_history_path_outside_capture_directory(self):
        path = shot.archive_screenshot(sample_image())
        outside = Path(self.tmp.name) / "outside.png"
        outside.write_bytes(path.read_bytes())
        dialog = shot.ScreenshotHistoryDialog(Mock())
        self.addCleanup(dialog.close)
        dialog.items.currentItem().setData(shot.Qt.UserRole, str(outside))
        self.assertIsNone(dialog._selected_path())
        with patch.object(shot, "_question_ru") as question:
            dialog.delete_selected()
        question.assert_not_called()
        self.assertTrue(outside.exists())

    def test_quick_actions_editor_keeps_original_image(self):
        launcher = Mock()
        image = sample_image()
        panel = shot.ScreenshotQuickActionsDialog(image, launcher)
        panel.edit_image()
        launcher._open_editor_image.assert_called_once()
        self.assertEqual(launcher._open_editor_image.call_args.args[0].size(), image.size())

    def test_quick_actions_can_store_image_without_enabling_auto_history(self):
        launcher = Mock()
        panel = shot.ScreenshotQuickActionsDialog(sample_image(), launcher)
        panel.to_history()
        self.assertEqual(len(shot.screenshot_history_files()), 1)
        launcher.open_history.assert_called_once()

    def test_quick_actions_do_not_duplicate_an_already_archived_capture(self):
        launcher = Mock()
        image = sample_image()
        original = shot.archive_screenshot(image)
        panel = shot.ScreenshotQuickActionsDialog(image, launcher, history_path=original)
        panel.to_history()
        self.assertEqual(shot.screenshot_history_files(), [original])
        launcher.open_history.assert_called_once()


class CaptureRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = patch.object(shot, "SCREENSHOT_HISTORY_SETTINGS",
                                Path(self.tmp.name) / "preferences.json")
        self.hist = patch.object(shot, "SCREENSHOT_HISTORY_DIR",
                                 Path(self.tmp.name) / "ScreenshotHistory")
        self.cfg.start()
        self.hist.start()
        self.addCleanup(self.cfg.stop)
        self.addCleanup(self.hist.stop)
        with patch.object(shot.Launcher, "_install_global_hotkey"):
            self.launcher = shot.Launcher()
        self.addCleanup(self.close_launcher)

    def close_launcher(self):
        self.launcher._real_quit = True
        self.launcher.close()

    def test_overlay_button_changes_both_saved_action_and_target(self):
        with patch.object(shot.SelectionOverlay, "mode_enabled", return_value=True):
            overlay = shot.SelectionOverlay(frozen=False, switchable=True,
                                            mode=shot.SelectionOverlay.MODE_SHOT)
            try:
                overlay.set_capture_kind("ocr")
                self.assertEqual(shot.load_capture_preferences()["capture_kind"], "ocr")
                overlay.toggle_target()
                self.assertEqual(shot.load_capture_preferences()["capture_target"], "window")
                overlay.toggle_mode()
                self.assertEqual(shot.load_capture_preferences()["capture_kind"], "shot")
            finally:
                overlay.dispose()

    def test_new_printscreen_uses_saved_action_and_target(self):
        shot.remember_capture_selection("ocr", "window")
        modes = []
        def record_initial_mode(overlay):
            modes.append(overlay.mode)
            return None
        with patch.object(shot, "_run_selection", side_effect=record_initial_mode), \
             patch.object(shot.SelectionOverlay, "mode_enabled", return_value=True):
            self.assertIsNone(shot.run_capture_flow(shot.SelectionOverlay.MODE_SHOT))
        self.assertEqual(modes, [shot.SelectionOverlay.MODE_OCR_WINDOW])

    def test_normal_printscreen_still_opens_editor_and_does_not_archive(self):
        with patch.object(shot, "run_capture_flow", return_value=sample_image()), \
             patch.object(self.launcher, "_open_editor_image") as editor:
            self.launcher._capture(shot.SelectionOverlay.MODE_SHOT)
        editor.assert_called_once()
        self.assertFalse(shot.SCREENSHOT_HISTORY_DIR.exists())

    def test_opt_in_history_stores_original_and_keeps_editor(self):
        self.launcher._capture_preferences["history_enabled"] = True
        with patch.object(shot, "run_capture_flow", return_value=sample_image()), \
             patch.object(self.launcher, "_open_editor_image") as editor:
            self.launcher._capture(shot.SelectionOverlay.MODE_WINDOW)
        editor.assert_called_once()
        self.assertEqual(len(shot.screenshot_history_files()), 1)

    def test_quick_actions_opt_in_does_not_open_editor_automatically(self):
        self.launcher._capture_preferences["quick_actions"] = True
        with patch.object(shot, "run_capture_flow", return_value=sample_image()), \
             patch.object(self.launcher, "_open_editor_image") as editor:
            self.launcher._capture(shot.SelectionOverlay.MODE_SHOT)
        editor.assert_not_called()
        self.assertIsNotNone(self.launcher._quick_panel)
        self.launcher._quick_panel.close()

    def test_cancelled_capture_creates_no_history(self):
        self.launcher._capture_preferences.update(
            {"quick_actions": True, "history_enabled": True})
        with patch.object(shot, "run_capture_flow", return_value=None), \
             patch.object(self.launcher, "_open_editor_image") as editor:
            self.launcher._capture(shot.SelectionOverlay.MODE_SHOT)
        editor.assert_not_called()
        self.assertFalse(shot.SCREENSHOT_HISTORY_DIR.exists())


if __name__ == "__main__":
    unittest.main()
