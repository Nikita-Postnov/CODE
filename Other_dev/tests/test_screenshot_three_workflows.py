"""Регрессия трёх функций NPCore Скриншоты.

Запуск: python -m unittest discover -s Other_dev/tests -p test_screenshot_three_workflows.py -v
Для CI используется QT_QPA_PLATFORM=offscreen.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QPushButton

from screenshot import (
    PinnedScreenshotWindow,
    Launcher,
    _scroll_overlap,
    _stitch_scroll_frames,
    compare_screenshot_images,
    load_capture_preferences,
)


class ScreenshotThreeWorkflowsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_equal_images_have_no_differences(self):
        before = QImage(110, 70, QImage.Format_RGB32)
        before.fill(QColor("#445566"))
        result, percent = compare_screenshot_images(before, before.copy())
        self.assertEqual(percent, 0.0)
        self.assertFalse(result.isNull())
        self.assertGreater(result.width(), before.width() * 2)

    def test_changed_area_is_detected(self):
        before = QImage(100, 90, QImage.Format_RGB32)
        before.fill(QColor("white"))
        after = before.copy()
        for y in range(15, 45):
            for x in range(15, 45):
                after.setPixelColor(x, y, QColor("black"))
        result, percent = compare_screenshot_images(before, after)
        self.assertGreater(percent, 8)
        self.assertLess(percent, 12)
        self.assertFalse(result.isNull())

    def test_different_dimensions_count_as_changes(self):
        first = QImage(100, 100, QImage.Format_RGB32)
        second = QImage(100, 110, QImage.Format_RGB32)
        first.fill(Qt.white)
        second.fill(Qt.white)
        _, percent = compare_screenshot_images(first, second)
        self.assertGreater(percent, 8)

    def test_identical_scroll_frames_stop(self):
        image = QImage(160, 240, QImage.Format_RGB32)
        image.fill(QColor("#101a3a"))
        self.assertEqual(_scroll_overlap(image, image.copy()), 0)

    def test_scroll_detects_known_offset(self):
        width, height, offset = 160, 270, 60
        source = QImage(width, height + offset, QImage.Format_RGB32)
        for y in range(height + offset):
            source.setPixelColor(0, y, QColor(y % 255, (y * 3) % 255, (y * 7) % 255))
            for x in range(1, width):
                source.setPixel(x, y, source.pixel(0, y))
        first = source.copy(0, 0, width, height)
        second = source.copy(0, offset, width, height)
        detected = _scroll_overlap(first, second)
        self.assertGreater(detected, 0)
        self.assertLessEqual(abs(detected - offset), 5)

    def test_stitch_keeps_only_new_bottom_rows(self):
        first = QImage(40, 100, QImage.Format_RGB32)
        second = QImage(40, 100, QImage.Format_RGB32)
        first.fill(QColor("red"))
        second.fill(QColor("blue"))
        image = _stitch_scroll_frames([first, second], [30])
        self.assertEqual(image.height(), 130)
        self.assertEqual(image.width(), 40)
        self.assertEqual(image.pixelColor(10, 20), QColor("red"))
        self.assertEqual(image.pixelColor(10, 120), QColor("blue"))

    def test_stitch_rejects_wrong_number_of_offsets(self):
        image = QImage(20, 20, QImage.Format_RGB32)
        with self.assertRaises(ValueError):
            _stitch_scroll_frames([image, image], [])

    def test_pinned_window_has_always_on_top_flag(self):
        image = QImage(160, 100, QImage.Format_RGB32)
        image.fill(QColor("green"))
        window = PinnedScreenshotWindow(image)
        try:
            self.assertTrue(bool(window.windowFlags() & Qt.WindowStaysOnTopHint))
            self.assertTrue(bool(window.windowFlags() & Qt.Tool))
        finally:
            window.close()

    def test_launcher_has_scrollable_content_and_readable_buttons(self):
        with patch.object(Launcher, "_init_tray"), patch.object(Launcher, "_install_global_hotkey"):
            window = Launcher()
        try:
            container = window.centralWidget()
            self.assertIsInstance(container, QScrollArea)
            self.assertTrue(container.widgetResizable())
            self.assertEqual(container.objectName(), "launcher_scroll_area")
            content = container.widget()
            buttons = content.findChildren(QPushButton)
            self.assertGreaterEqual(len(buttons), 11)
            self.assertTrue(all(button.minimumHeight() >= 38 for button in buttons))
            self.assertGreater(window.height(), 300)
            labels = [child.text() for child in content.findChildren(QLabel)]
            self.assertTrue(any("PrintScreen" in text for text in labels))
            self.assertTrue(any("Инструменты:" in text for text in labels))
        finally:
            window.close()

    def test_default_capture_is_not_changed_by_new_features(self):
        preferences = load_capture_preferences()
        self.assertIn("quick_actions", preferences)
        self.assertIn("edit_after_capture", preferences)
        self.assertIn("history_enabled", preferences)


if __name__ == "__main__":
    unittest.main()
