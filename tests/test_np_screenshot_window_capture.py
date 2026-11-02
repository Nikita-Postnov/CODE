"""Регрессионные проверки режима захвата отдельного окна."""
import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication

SOURCE = Path(__file__).resolve().parents[1] / "Other_dev" / "screenshot.py"
SPEC = importlib.util.spec_from_file_location("np_screenshot_window_under_test", SOURCE)
shot = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = shot
SPEC.loader.exec_module(shot)


class WindowSelectionTests(unittest.TestCase):
    def test_topmost_window_wins_over_background(self):
        windows = [
            ("Chrome", QRect(100, 100, 500, 400)),
            ("IDE", QRect(0, 0, 1000, 700)),
        ]
        self.assertEqual(shot.window_at_point(QPoint(200, 200), windows), QRect(100, 100, 500, 400))
        self.assertEqual(shot.window_at_point(QPoint(800, 600), windows), QRect(0, 0, 1000, 700))
        self.assertIsNone(shot.window_at_point(QPoint(-100, 100), windows))

    def test_tiny_windows_are_ignored(self):
        windows = [
            ("tooltip", QRect(200, 200, 10, 10)),
            ("main", QRect(100, 100, 500, 400)),
        ]
        self.assertEqual(shot.window_at_point(QPoint(205, 205), windows), QRect(100, 100, 500, 400))

    def test_dpi_mapping_respects_screen_origin_and_scale(self):
        screen = types.SimpleNamespace(
            geometry=lambda: QRect(1920, 0, 1280, 720),
            devicePixelRatio=lambda: 1.5,
        )
        with patch.object(shot.QGuiApplication, "screens", return_value=[screen]):
            mapped = shot._native_window_to_qt_rect(QRect(2070, 150, 900, 600))
        self.assertEqual(mapped, QRect(2020, 100, 600, 400))

    def test_hover_repaints_all_monitors_and_click_selects_only_one_window(self):
        selected = []
        pane_a = types.SimpleNamespace(update=Mock())
        pane_b = types.SimpleNamespace(update=Mock())
        overlay = object.__new__(shot.SelectionOverlay)
        overlay._windows = [
            ("browser", QRect(200, 150, 600, 400)),
            ("desktop", QRect(0, 0, 1400, 800)),
        ]
        overlay._panes = [pane_a, pane_b]
        overlay._hover_window_g = None
        overlay.selection_made = selected.append
        overlay.hide = Mock()
        overlay._on_window_hover(QPoint(300, 300))
        self.assertEqual(overlay._hover_window_g, QRect(200, 150, 600, 400))
        pane_a.update.assert_called_once()
        pane_b.update.assert_called_once()
        overlay._on_window_hover(QPoint(301, 300))
        pane_a.update.assert_called_once()
        overlay._on_pick_window(QPoint(301, 300))
        overlay.hide.assert_called_once()
        self.assertEqual(selected, [QRect(200, 150, 600, 400)])

    def test_click_without_window_stays_in_selection(self):
        overlay = object.__new__(shot.SelectionOverlay)
        overlay._windows = []
        overlay.selection_made = Mock()
        overlay.hide = Mock()
        overlay._on_pick_window(QPoint(300, 300))
        overlay.hide.assert_not_called()
        overlay.selection_made.assert_not_called()

    def test_mode_is_windows_only_and_existing_modes_remain_available(self):
        overlay = object.__new__(shot.SelectionOverlay)
        overlay.record_available = True
        with patch.object(shot.sys, "platform", "linux"):
            self.assertFalse(overlay.mode_enabled(shot.SelectionOverlay.MODE_WINDOW))
            self.assertTrue(overlay.mode_enabled(shot.SelectionOverlay.MODE_SHOT))
        with patch.object(shot.sys, "platform", "win32"):
            self.assertTrue(overlay.mode_enabled(shot.SelectionOverlay.MODE_WINDOW))
            self.assertTrue(overlay.mode_enabled(shot.SelectionOverlay.MODE_RECORD))
            self.assertTrue(overlay.mode_enabled(shot.SelectionOverlay.MODE_OCR))
        self.assertEqual(shot.SelectionOverlay._MODES,
                         ("shot", "window", "record", "ocr"))


class WindowModeGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_mode_switch_and_overlay_preview_do_not_change_screenshot_output(self):
        windows = [("Chrome", QRect(150, 100, 500, 300))]
        with patch.object(shot.sys, "platform", "win32"), \
             patch.object(shot, "list_capturable_windows", return_value=windows):
            overlay = shot.SelectionOverlay(frozen=False, switchable=True, mode="shot")
            try:
                overlay.set_mode(overlay.MODE_WINDOW)
                self.assertEqual(overlay.mode, overlay.MODE_WINDOW)
                self.assertEqual(overlay._hover_window_g,
                                 shot.window_at_point(shot.QCursor.pos(), windows))
                overlay.set_mode(overlay.MODE_SHOT)
                self.assertIsNone(overlay._hover_window_g)
                self.assertTrue(overlay.mode_enabled(overlay.MODE_SHOT))
            finally:
                overlay.dispose()

    def test_tray_and_launcher_window_actions_are_present(self):
        with patch.object(shot.Launcher, "_install_global_hotkey"), \
             patch.object(shot.QSystemTrayIcon, "isSystemTrayAvailable", return_value=True):
            launcher = shot.Launcher()
        try:
            self.assertEqual(launcher.act_tray_window.text(), "Снимок отдельного окна")
            with patch.object(shot.sys, "platform", "win32"), \
                 patch.object(shot.QTimer, "singleShot") as scheduled:
                launcher.make_window_shot()
                scheduled.assert_called_once()
                self.assertEqual(scheduled.call_args.args[0], 200)
                with patch.object(launcher, "_capture") as capture:
                    scheduled.call_args.args[1]()
                    capture.assert_called_once_with(shot.SelectionOverlay.MODE_WINDOW)
        finally:
            launcher._real_quit = True
            launcher.close()


if __name__ == "__main__":
    unittest.main()
