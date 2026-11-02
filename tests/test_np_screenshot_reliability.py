"""Проверки сохранности снимков, записей и отложенного захвата NP_Screenshot."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication

SCRIPT = Path(__file__).resolve().parents[1] / "Other_dev" / "screenshot.py"
SPEC = importlib.util.spec_from_file_location("np_screenshot_under_test", SCRIPT)
shot = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = shot
SPEC.loader.exec_module(shot)


class FakeImage:
    def __init__(self, succeed=True):
        self.succeed = succeed
        self.saves = []

    def save(self, path, fmt, quality):
        self.saves.append((path, fmt, quality))
        Path(path).write_bytes(b"partial" if not self.succeed else b"new-image")
        return self.succeed


class ScreenshotReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def test_new_image_is_written_and_temp_is_removed(self):
        out = self.folder / "capture.png"
        self.assertTrue(shot.save_image_atomically(FakeImage(), out, "PNG"))
        self.assertEqual(out.read_bytes(), b"new-image")
        self.assertEqual(list(self.folder.glob("*.tmp")), [])

    def test_failed_encoder_never_replaces_existing_screenshot(self):
        out = self.folder / "important.png"
        out.write_bytes(b"original")
        self.assertFalse(shot.save_image_atomically(FakeImage(False), out, "PNG"))
        self.assertEqual(out.read_bytes(), b"original")
        self.assertEqual(list(self.folder.glob("*.tmp")), [])

    def test_failed_replace_keeps_existing_image_and_removes_temp(self):
        out = self.folder / "important.png"
        out.write_bytes(b"original")
        with patch.object(shot.os, "replace", side_effect=OSError("locked")):
            self.assertFalse(shot.save_image_atomically(FakeImage(), out, "PNG"))
        self.assertEqual(out.read_bytes(), b"original")
        self.assertEqual(list(self.folder.glob("*.tmp")), [])

    def test_actual_qimage_round_trip(self):
        out = self.folder / "real.png"
        image = QImage(4, 3, QImage.Format_ARGB32)
        image.fill(QColor("#bb0000"))
        self.assertTrue(shot.save_image_atomically(image, out, "PNG"))
        loaded = QImage(str(out))
        self.assertFalse(loaded.isNull())
        self.assertEqual((loaded.width(), loaded.height()), (4, 3))
        self.assertEqual(loaded.pixelColor(1, 1).name(), "#bb0000")

    def test_old_recordings_survive_temp_cleanup(self):
        tmp = self.folder / "Data" / "_rec_tmp"
        tmp.mkdir(parents=True)
        old_video = tmp / "rec_2026-01-01_10-00-00.mp4"
        old_temp = tmp / "frame_cache.png"
        for entry in (old_video, old_temp):
            entry.write_bytes(b"file")
            ago = time.time() - 30 * 86400
            os.utime(entry, (ago, ago))
        with patch.object(shot, "DATA_DIR", self.folder / "Data"):
            shot._cleanup_rec_tmp()
        self.assertTrue(old_video.exists())
        self.assertFalse(old_temp.exists())

    def test_permanent_recording_directory_is_independent_of_temp(self):
        with patch.object(shot, "DATA_DIR", self.folder / "Data"):
            permanent = shot._recordings_dir()
            permanent_video = permanent / "rec_2026-01-01_10-00-00.mp4"
            permanent_video.write_bytes(b"recording")
            ago = time.time() - 30 * 86400
            os.utime(permanent_video, (ago, ago))
            shot._cleanup_rec_tmp()
        self.assertEqual(permanent.name, "Recordings")
        self.assertEqual(permanent_video.read_bytes(), b"recording")


class DelayedCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.launcher = shot.Launcher()
        self.addCleanup(self.close_launcher)

    def close_launcher(self):
        self.launcher.cancel_delayed_capture()
        self.launcher._real_quit = True
        self.launcher.close()

    def test_delay_triggers_capture_only_after_countdown(self):
        with patch.object(self.launcher, "_capture") as capture:
            self.launcher.capture_delayed(3)
            self.assertTrue(self.launcher._delayed_capture_timer.isActive())
            self.assertEqual(self.launcher._delayed_capture_timer.remainingTime() > 0, True)
            capture.assert_not_called()
            self.launcher._delayed_capture_timer.stop()
            self.launcher._finish_delayed_capture()
            capture.assert_called_once_with(shot.SelectionOverlay.MODE_SHOT)

    def test_cancel_prevents_delayed_capture(self):
        with patch.object(self.launcher, "_capture") as capture:
            self.launcher.capture_delayed(5)
            self.launcher.cancel_delayed_capture()
            self.assertFalse(self.launcher._delayed_capture_timer.isActive())
            capture.assert_not_called()

    def test_delay_values_are_restricted(self):
        with self.assertRaises(ValueError):
            self.launcher.capture_delayed(-1)
        with self.assertRaises(ValueError):
            self.launcher.capture_delayed(120)


if __name__ == "__main__":
    unittest.main()
