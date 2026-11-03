"""Проверки записи выбранного окна без изменения режимов снимка и записи экрана."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication, QPushButton

SOURCE = Path(__file__).resolve().parents[1] / "Other_dev" / "screenshot.py"
SPEC = importlib.util.spec_from_file_location("np_screenshot_window_recording", SOURCE)
shot = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = shot
SPEC.loader.exec_module(shot)


class WindowRecordModelTests(unittest.TestCase):
    def test_window_entry_keeps_previous_tuple_interface(self):
        rect = QRect(50, 80, 640, 480)
        selected = shot.CapturableWindow("Блокнот", rect, 38120)
        self.assertEqual(selected, ("Блокнот", rect))
        title, area = selected
        self.assertEqual(title, "Блокнот")
        self.assertEqual(area, rect)
        self.assertEqual(selected.hwnd, 38120)
        self.assertIs(
            shot.window_entry_at_point(QPoint(200, 220), [selected]), selected)
        self.assertEqual(
            shot.window_at_point(QPoint(200, 220), [selected]), rect)

    def test_record_window_tracks_exact_hwnd_in_ffmpeg(self):
        with patch.object(shot.sys, "platform", "win32"), \
             patch.object(shot, "ffmpeg_path", return_value="ffmpeg.exe"):
            cmd = shot.build_window_record_cmd(
                "recording.mp4", 38120, 30, "none", None)
            self.assertEqual(cmd[cmd.index("-i") + 1], "hwnd=38120")
            self.assertNotIn("desktop", cmd)
            self.assertNotIn("-offset_x", cmd)
            self.assertNotIn("-video_size", cmd)
            self.assertEqual(
                cmd[cmd.index("-vf") + 1],
                "pad=ceil(iw/2)*2:ceil(ih/2)*2",
            )
            self.assertIn("libx264", cmd)
            self.assertEqual(cmd[-1], "recording.mp4")

    def test_window_recording_preserves_audio_mapping(self):
        with patch.object(shot.sys, "platform", "win32"), \
             patch.object(shot, "ffmpeg_path", return_value="ffmpeg.exe"):
            cmd = shot.build_window_record_cmd(
                "recording.mp4", 43, 25, "mic", "Microphone A")
        self.assertIn("audio=Microphone A", cmd)
        self.assertEqual(cmd[cmd.index("-map") + 1], "0:v")
        self.assertEqual(cmd[cmd.index("-map", cmd.index("-map") + 1) + 1], "1:a")
        self.assertIn("aac", cmd)

    def test_refuse_invalid_hwnd_and_non_windows_platform(self):
        with patch.object(shot.sys, "platform", "win32"):
            for handle in (0, -1, "not-a-window", None):
                with self.subTest(handle=handle):
                    with self.assertRaises(ValueError):
                        shot.build_window_record_cmd("out.mp4", handle, 30, "none", None)
        with patch.object(shot.sys, "platform", "linux"):
            with self.assertRaises(ValueError):
                shot.build_window_record_cmd("out.mp4", 123, 30, "none", None)
            self.assertFalse(shot.recordable_window_is_ready(123))

    def test_original_area_recording_is_unchanged(self):
        with patch.object(shot, "ffmpeg_path", return_value="ffmpeg.exe"), \
             patch.object(shot, "_physical_rect", return_value=(10, 20, 300, 200)):
            cmd = shot.build_record_cmd(
                "original.mp4", QRect(10, 20, 300, 200), 30, "none", None)
        self.assertEqual(cmd[cmd.index("-i") + 1], "desktop")
        self.assertEqual(cmd[cmd.index("-video_size") + 1], "300x200")
        self.assertNotIn("hwnd=123", cmd)


class WindowRecordOverlayTests(unittest.TestCase):
    def test_select_specific_window_without_changing_screenshot_selection(self):
        record = shot.SelectionOverlay.__new__(shot.SelectionOverlay)
        record._windows = [
            shot.CapturableWindow("Chrome", QRect(100, 100, 500, 400), 111),
            shot.CapturableWindow("Chrome", QRect(0, 0, 800, 700), 222),
        ]
        record.mode = shot.SelectionOverlay.MODE_RECORD_WINDOW
        record.selected_window_hwnd = None
        record.selected_window_title = ""
        record._hover_window_g = None
        record.hide = Mock()
        record.selection_made = Mock()
        record._on_pick_window(QPoint(200, 200))
        self.assertEqual(record.selected_window_hwnd, 111)
        self.assertEqual(record.selected_window_title, "Chrome")
        record.selection_made.assert_called_once_with(QRect(100, 100, 500, 400))

        shot_mode = shot.SelectionOverlay.__new__(shot.SelectionOverlay)
        shot_mode._windows = record._windows
        shot_mode.mode = shot.SelectionOverlay.MODE_WINDOW
        shot_mode._hover_window_g = None
        shot_mode.hide = Mock()
        shot_mode.selection_made = Mock()
        shot_mode._on_pick_window(QPoint(200, 200))
        shot_mode.selection_made.assert_called_once_with(QRect(100, 100, 500, 400))

    def test_window_recording_mode_requires_windows_and_ffmpeg(self):
        overlay = object.__new__(shot.SelectionOverlay)
        with patch.object(shot.sys, "platform", "win32"):
            overlay.record_available = True
            self.assertTrue(overlay.mode_enabled(overlay.MODE_RECORD_WINDOW))
            overlay.record_available = False
            self.assertFalse(overlay.mode_enabled(overlay.MODE_RECORD_WINDOW))
        with patch.object(shot.sys, "platform", "linux"):
            overlay.record_available = True
            self.assertFalse(overlay.mode_enabled(overlay.MODE_RECORD_WINDOW))
            self.assertTrue(overlay.mode_enabled(overlay.MODE_RECORD))

    def test_record_window_capture_flow_passes_hwnd_to_hud(self):
        def fake_init(self, *args, **kwargs):
            self.mode = kwargs["mode"]
            self.selected_window_hwnd = 111
            self.selected_window_title = "Chrome"
            self._panes = []

        with patch.object(shot.SelectionOverlay, "__init__", fake_init), \
             patch.object(shot.SelectionOverlay, "shots", return_value=[]), \
             patch.object(shot.SelectionOverlay, "dispose"), \
             patch.object(shot, "_run_selection", return_value=QRect(10, 15, 400, 300)), \
             patch.object(shot, "ffmpeg_path", return_value="ffmpeg.exe"), \
             patch.object(shot, "_begin_recording") as begin:
            result = shot.run_capture_flow(shot.SelectionOverlay.MODE_RECORD_WINDOW)
        self.assertIsNone(result)
        begin.assert_called_once_with(
            QRect(10, 15, 400, 300), None,
            window_hwnd=111, window_title="Chrome")


class WindowRecordGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_launcher_and_tray_provide_separate_record_window_action(self):
        with patch.object(shot.Launcher, "_install_global_hotkey"), \
             patch.object(shot.QSystemTrayIcon, "isSystemTrayAvailable", return_value=True):
            launcher = shot.Launcher()
        try:
            names = [button.text() for button in launcher.findChildren(QPushButton)]
            self.assertIn("Снимок отдельного окна", names)
            self.assertIn("Запись экрана", names)
            self.assertIn("Запись отдельного окна", names)
            self.assertEqual(launcher.act_tray_window_rec.text(), "Запись отдельного окна")
            with patch.object(shot.sys, "platform", "win32"), \
                 patch.object(shot, "ffmpeg_path", return_value="ffmpeg.exe"), \
                 patch.object(shot.QTimer, "singleShot") as scheduled:
                launcher.start_window_recording()
                scheduled.assert_called_once()
                self.assertEqual(scheduled.call_args.args[0], 200)
                with patch.object(launcher, "_capture") as capture:
                    scheduled.call_args.args[1]()
                    capture.assert_called_once_with(
                        shot.SelectionOverlay.MODE_RECORD_WINDOW)
        finally:
            launcher._real_quit = True
            launcher.close()

    def test_window_is_closed_before_start_prevents_recording(self):
        with patch.object(shot, "list_dshow_audio", return_value=[]), \
             patch.object(shot, "recordable_window_is_ready", return_value=False), \
             patch.object(shot, "ffmpeg_path", return_value="ffmpeg.exe"):
            hud = shot.RecordHUD(QRect(100, 100, 320, 240),
                                 window_hwnd=111, window_title="Chrome")
            try:
                with patch.object(shot.QMessageBox, "warning") as warn, \
                     patch.object(shot, "build_window_record_cmd") as build:
                    hud._on_start()
                warn.assert_called_once()
                build.assert_not_called()
                self.assertFalse(hud._recording)
            finally:
                hud.close()


if __name__ == "__main__":
    unittest.main()
