"""Выбор действия и источника захвата NP Screenshot: две независимые группы."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

SOURCE = Path(__file__).resolve().parents[1] / "Other_dev" / "screenshot.py"
SPEC = importlib.util.spec_from_file_location("np_screenshot_capture_choices", SOURCE)
shot = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = shot
SPEC.loader.exec_module(shot)


class ActionTargetMapTests(unittest.TestCase):
    def test_all_four_capture_combinations_and_both_ocr_sources(self):
        overlay = object.__new__(shot.SelectionOverlay)
        for kind, target, mode in (
            ("shot", "area", "shot"),
            ("shot", "window", "window"),
            ("record", "area", "record"),
            ("record", "window", "record_window"),
            ("ocr", "area", "ocr"),
            ("ocr", "window", "ocr_window"),
        ):
            with self.subTest(kind=kind, target=target):
                self.assertEqual(overlay.mode_for_choice(kind, target), mode)
                overlay.mode = mode
                self.assertEqual(overlay.capture_kind(), kind)
                self.assertEqual(overlay.capture_target(), target)

    def test_unsupported_choices_are_disabled(self):
        overlay = object.__new__(shot.SelectionOverlay)
        overlay.mode = overlay.MODE_SHOT
        overlay.record_available = False
        self.assertFalse(overlay.capture_button_enabled("kind:record"))
        with patch.object(shot.sys, "platform", "linux"):
            self.assertFalse(overlay.capture_button_enabled("target:window"))
            self.assertFalse(overlay.capture_button_enabled("kind:ocr"))
        self.assertFalse(overlay.capture_button_enabled("invalid:mode"))


class CaptureChoicesGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_overlay(self, mode="shot", ffmpeg=True):
        with patch.object(shot, "list_capturable_windows", return_value=[]):
            return shot.SelectionOverlay(
                frozen=False, switchable=True, mode=mode,
                record_available=ffmpeg,
            )

    def test_area_and_window_are_always_visible_and_area_selected_by_default(self):
        overlay = self.make_overlay()
        try:
            pane = next(p for p in overlay._panes if p.has_bar)
            bar, buttons, _ = pane._bar_layout()
            keys = [key for key, _ in buttons]
            self.assertEqual(keys, [
                "kind:shot", "kind:record", "kind:ocr",
                "target:area", "target:window",
            ])
            self.assertTrue(bar.width() > 0)
            self.assertEqual(overlay.capture_kind(), "shot")
            self.assertEqual(overlay.capture_target(), "area")
            self.assertIn("Область", overlay._BAR_LABELS["target:area"])
            self.assertIn("Окно", overlay._BAR_LABELS["target:window"])
            positions = {key: rect for key, rect in buttons}
            self.assertLess(positions["target:area"].right(),
                            positions["target:window"].left())
            self.assertEqual(
                pane._bar_hit(positions["target:area"].center()), "target:area")
            self.assertEqual(
                pane._bar_hit(positions["target:window"].center()), "target:window")
        finally:
            overlay.dispose()

    def test_switch_action_without_resetting_target_and_switch_target_without_action(self):
        overlay = self.make_overlay()
        try:
            with patch.object(shot.sys, "platform", "win32"):
                overlay.choose_bar_button("target:window")
                self.assertEqual(overlay.mode, "window")
                overlay.choose_bar_button("kind:record")
                self.assertEqual(overlay.mode, "record_window")
                overlay.choose_bar_button("target:area")
                self.assertEqual(overlay.mode, "record")
                overlay.choose_bar_button("kind:shot")
                self.assertEqual(overlay.mode, "shot")
                overlay.choose_bar_button("kind:ocr")
                self.assertEqual(overlay.mode, "ocr")
                overlay.choose_bar_button("target:window")
                self.assertEqual(overlay.mode, "ocr_window")
                overlay.choose_bar_button("kind:shot")
                self.assertEqual(overlay.mode, "window")
        finally:
            overlay.dispose()

    def test_tab_cycles_action_and_shift_tab_cycles_target(self):
        overlay = self.make_overlay()
        try:
            with patch.object(shot.sys, "platform", "win32"):
                overlay.toggle_mode()
                self.assertEqual(overlay.mode, "record")
                overlay.toggle_target()
                self.assertEqual(overlay.mode, "record_window")
                overlay.toggle_mode()
                self.assertEqual(overlay.mode, "ocr_window")
                overlay.toggle_mode()
                self.assertEqual(overlay.mode, "window")
                overlay.toggle_target()
                self.assertEqual(overlay.mode, "shot")
        finally:
            overlay.dispose()

    def test_recording_unavailable_does_not_allow_switching_to_record(self):
        overlay = self.make_overlay(ffmpeg=False)
        try:
            with patch.object(shot.sys, "platform", "win32"):
                overlay.choose_bar_button("kind:record")
                self.assertEqual(overlay.mode, "shot")
                overlay.toggle_mode()
                self.assertEqual(overlay.mode, "ocr")
                overlay.toggle_target()
                self.assertEqual(overlay.mode, "ocr_window")
        finally:
            overlay.dispose()

    def test_screenshot_record_and_ocr_choose_corresponding_output(self):
        img = QImage(20, 20, QImage.Format_ARGB32)
        img.fill(0xFFFFFFFF)
        area = QRect(10, 15, 400, 300)

        def init_overlay(self, *args, **kwargs):
            self.mode = kwargs["mode"]
            self.selected_window_hwnd = 101
            self.selected_window_title = "Контрольное окно"
            self._panes = []

        scenarios = [
            ("shot", "image"),
            ("window", "image"),
            ("record", "record_area"),
            ("record_window", "record_window"),
            ("ocr", "ocr"),
            ("ocr_window", "ocr"),
        ]
        for mode, expected in scenarios:
            with self.subTest(mode=mode), \
                 patch.object(shot.SelectionOverlay, "__init__", init_overlay), \
                 patch.object(shot.SelectionOverlay, "shots", return_value=[]), \
                 patch.object(shot.SelectionOverlay, "dispose"), \
                 patch.object(shot, "_run_selection", return_value=area), \
                 patch.object(shot, "ffmpeg_path", return_value="ffmpeg.exe"), \
                 patch.object(shot, "compose_region_from_shots", return_value=img), \
                 patch.object(shot, "_begin_recording") as record, \
                 patch.object(shot, "start_ocr") as ocr:
                result = shot.run_capture_flow(mode)
                if expected == "image":
                    self.assertIs(result, img)
                    record.assert_not_called()
                    ocr.assert_not_called()
                elif expected == "record_area":
                    self.assertIsNone(result)
                    record.assert_called_once_with(area, None)
                    ocr.assert_not_called()
                elif expected == "record_window":
                    self.assertIsNone(result)
                    record.assert_called_once_with(
                        area, None, window_hwnd=101, window_title="Контрольное окно")
                    ocr.assert_not_called()
                else:
                    self.assertIsNone(result)
                    record.assert_not_called()
                    ocr.assert_called_once_with(img, None)


if __name__ == "__main__":
    unittest.main()
