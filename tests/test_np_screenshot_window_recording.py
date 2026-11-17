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

    def test_recording_mixes_system_and_microphone_with_separate_gains(self):
        with patch.object(shot, "ffmpeg_path", return_value="ffmpeg.exe"), \
             patch.object(shot, "_physical_rect", return_value=(0, 0, 640, 480)):
            cmd = shot.build_record_cmd(
                "mixed.mp4", QRect(0, 0, 640, 480), 30, "none", None,
                audio_inputs=[("Speakers", 0.75), ("Microphone", 1.25)])
        self.assertIn("audio=Speakers", cmd)
        self.assertIn("audio=Microphone", cmd)
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("volume=0.750", graph)
        self.assertIn("volume=1.250", graph)
        self.assertIn("amix=inputs=2", graph)
        self.assertIn("[aout]", graph)

    def test_gif_export_uses_palette_and_trim_range(self):
        with patch.object(shot, "ffmpeg_path", return_value="ffmpeg.exe"):
            cmd = shot.build_gif_export_cmd("source.mp4", "out.gif", 2.5, 7.5)
        self.assertEqual(cmd[cmd.index("-ss") + 1], "2.500")
        self.assertEqual(cmd[cmd.index("-t") + 1], "5.000")
        self.assertIn("palettegen", cmd[cmd.index("-filter_complex") + 1])
        self.assertIn("paletteuse", cmd[cmd.index("-filter_complex") + 1])
        self.assertEqual(cmd[-1], "out.gif")
        self.assertIn("-loop", cmd)

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

    def test_audio_settings_keep_system_and_microphone_levels_independent(self):
        with patch.object(shot, "guess_system_audio", return_value="Speakers"):
            dialog = shot.AudioSettingsDialog(["Speakers", "Microphone"])
        self.addCleanup(dialog.close)
        dialog.system_check.setChecked(True)
        dialog.mic_check.setChecked(True)
        dialog.system_gain.setValue(75)
        dialog.mic_gain.setValue(130)
        selected = dialog.selected_inputs()
        self.assertEqual(selected, [("Speakers", 0.75), ("Microphone", 1.3)])

    def test_record_hud_exposes_pause_and_optional_input_overlay(self):
        with patch.object(shot, "list_dshow_audio", return_value=[]):
            hud = shot.RecordHUD(QRect(100, 100, 320, 240))
        try:
            self.assertEqual(hud.pause_btn.text(), "Ⅱ Пауза")
            self.assertFalse(hud.pause_btn.isEnabled())
            self.assertFalse(hud.input_overlay_check.isChecked())
            self.assertTrue(hud.audio_settings_btn.isEnabled())
        finally:
            hud.close()

    def test_recording_quality_and_fps_control_ffmpeg_for_area_and_window(self):
        with patch.object(shot, "ffmpeg_path", return_value="ffmpeg.exe"), \
             patch.object(shot, "_physical_rect",
                          return_value=(0, 0, 640, 480)), \
             patch.object(shot.sys, "platform", "win32"):
            for key, expected in (("high", "17"), ("standard", "20"),
                                  ("compact", "25")):
                for cmd in (
                    shot.build_record_cmd(
                        "clip.mp4", QRect(0, 0, 640, 480), 60,
                        "none", None, draw_mouse=False, quality=key),
                    shot.build_window_record_cmd(
                        "clip.mp4", 38120, 60,
                        "none", None, draw_mouse=False, quality=key),
                ):
                    self.assertEqual(cmd[cmd.index("-crf") + 1], expected)
                    self.assertEqual(cmd[cmd.index("-framerate") + 1], "60")
                    self.assertEqual(cmd[cmd.index("-draw_mouse") + 1], "0")
            with self.assertRaises(ValueError):
                shot.build_record_cmd(
                    "clip.mp4", QRect(0, 0, 640, 480), 30,
                    "none", None, quality="invalid")

    def test_recording_settings_persist_and_reject_invalid_values(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(shot, "_recording_settings_file",
                          return_value=Path(folder) / "recording.json"):
            self.assertEqual(shot.load_recording_settings()["fps"], 30)
            self.assertTrue(shot.save_recording_settings({
                "fps": 60, "quality": "high", "show_actions": True,
                "show_mouse": False}))
            self.assertEqual(shot.load_recording_settings(), {
                "fps": 60, "quality": "high", "show_actions": True,
                "show_mouse": False})
            self.assertFalse(shot.save_recording_settings({
                "fps": 10000, "quality": "high",
                "show_actions": True, "show_mouse": False}))
            (Path(folder) / "recording.json").write_text(
                '{"fps": 120, "quality": "bogus", "show_actions":"yes"}',
                encoding="utf-8")
            self.assertEqual(shot.load_recording_settings()["fps"], 30)
            self.assertEqual(shot.load_recording_settings()["quality"],
                             "standard")
            self.assertFalse(shot.load_recording_settings()["show_actions"])

    def test_record_hud_uses_current_video_settings_for_both_capture_types(self):
        with patch.object(shot, "list_dshow_audio", return_value=[]), \
             patch.object(shot, "load_recording_settings",
                          return_value={"fps": 30, "quality": "standard",
                                        "show_actions": False, "show_mouse": True}), \
             patch.object(shot, "save_recording_settings",
                          return_value=True), \
             patch.object(shot, "ffmpeg_path", return_value="ffmpeg.exe"), \
             patch.object(shot, "_physical_rect",
                          return_value=(0, 0, 640, 480)):
            hud = shot.RecordHUD(QRect(100, 100, 640, 480))
            try:
                hud.fps_combo.setCurrentIndex(hud.fps_combo.findData(60))
                hud.quality_combo.setCurrentIndex(
                    hud.quality_combo.findData("compact"))
                hud.mouse_check.setChecked(False)
                hud.input_overlay_check.setChecked(True)
                args = hud._build_segment_command("out.mp4")
                self.assertEqual(args[args.index("-framerate") + 1], "60")
                self.assertEqual(args[args.index("-crf") + 1], "25")
                self.assertEqual(args[args.index("-draw_mouse") + 1], "0")
                self.assertTrue(hud._video_settings()["show_actions"])
            finally:
                hud.close()

            with patch.object(shot.sys, "platform", "win32"):
                win = shot.RecordHUD(QRect(100, 100, 640, 480),
                                     window_hwnd=123, window_title="App")
                try:
                    self.assertFalse(win.input_overlay_check.isEnabled())
                    win.fps_combo.setCurrentIndex(win.fps_combo.findData(24))
                    win.quality_combo.setCurrentIndex(
                        win.quality_combo.findData("high"))
                    cmd = win._build_segment_command("win.mp4")
                    self.assertEqual(cmd[cmd.index("-framerate") + 1], "24")
                    self.assertEqual(cmd[cmd.index("-crf") + 1], "17")
                finally:
                    win.close()

    def test_overlay_ignores_plain_letters_but_shows_shortcuts(self):
        with patch.object(shot.sys, "platform", "win32"):
            overlay = shot.RecordingInputOverlay(QRect(0, 0, 100, 100))
            try:
                with patch.object(overlay, "_down", side_effect=lambda k: k == 0x41):
                    overlay._poll()
                self.assertEqual(overlay._key_label, "")
                overlay._keys_down.clear()
                with patch.object(overlay, "_down",
                                  side_effect=lambda k: k in (0x41, 0xA2)):
                    overlay._poll()
                self.assertEqual(overlay._key_label, "Ctrl+A")
            finally:
                overlay.stop()

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
