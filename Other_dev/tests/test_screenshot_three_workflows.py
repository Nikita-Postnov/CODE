"""Регрессия трёх функций NPCore Скриншоты.

Запуск: python -m unittest discover -s Other_dev/tests -p test_screenshot_three_workflows.py -v
Для CI используется QT_QPA_PLATFORM=offscreen.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt, QRect, QPoint
from PySide6.QtGui import QColor, QImage, QPainter, QFont
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QPushButton

from screenshot import (
    PinnedScreenshotWindow,
    Launcher,
    OCRResultDialog,
    _npcore_normalize_server,
    _npcore_pair_config,
    _npcore_translate,
    ScrollingCapturePanel,
    ScrollingScreenshotJob,
    ScrollingReviewDialog,
    _scroll_fixed_bands,
    _scroll_body_unchanged,
    _scroll_stationary_content,
    _scrollbar_progressed,
    _windows_scroll_state,
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

    def test_pixel_accurate_text_scroll_with_fixed_header(self):
        """Длинный снимок не должен разрывать слова даже при нечётном сдвиге."""
        width, height, offset = 520, 660, 237
        source = QImage(width, height + offset + 200, QImage.Format_RGB32)
        source.fill(Qt.white)
        painter = QPainter(source)
        painter.setPen(QColor("#18273a"))
        font = QFont("Arial", 16)
        painter.setFont(font)
        for line_no, y in enumerate(range(40, source.height(), 27)):
            painter.drawText(42, y, f"№{line_no:03d} Проверка текста: Алфавит-2026")
            painter.fillRect(55, y - 22, 3 + (line_no * 7) % 45, 4,
                             QColor.fromRgb((line_no * 37) % 230 + 20, 40, 80))
            painter.drawLine(40, y + 2, 470, y + 2)
        painter.end()
        first = source.copy(0, 0, width, height)
        second = source.copy(0, offset, width, height)
        for frame in (first, second):
            painter = QPainter(frame)
            painter.fillRect(0, 0, width, 68, QColor("#293450"))
            painter.setPen(Qt.white)
            painter.drawText(40, 40, "ФИКСИРОВАННОЕ МЕНЮ")
            painter.end()
        self.assertEqual(_scroll_overlap(first, second), offset)

    def test_text_scroll_pixel_fidelity_without_scaling(self):
        width, height, offset = 450, 480, 173
        source = QImage(width, height + offset, QImage.Format_RGB32)
        source.fill(Qt.white)
        painter = QPainter(source)
        painter.setPen(Qt.black)
        painter.setFont(QFont("Arial", 13))
        for y in range(25, source.height(), 24):
            painter.drawText(25, y, f"#{y:04d} Проверяем каждую строку при прокрутке")
            painter.fillRect(45, y - 20, 8 + (y * 7) % 75, 4,
                             QColor.fromRgb((y * 3) % 235 + 20, 40, 60))
        painter.end()
        before = source.copy(0, 0, width, height)
        after = source.copy(0, offset, width, height)
        shift = _scroll_overlap(before, after)
        self.assertEqual(shift, offset)
        stitched = _stitch_scroll_frames([before, after], [shift])
        self.assertEqual(stitched.height(), height + offset)
        for y in (10, 200, height - 1, height, height + 25, height + offset - 1):
            for x in (30, 120, 200, width - 10):
                self.assertEqual(stitched.pixel(x, y), source.pixel(x, y))

    def test_no_false_match_on_repeated_uniform_background(self):
        """Белая или одноцветная область не должна превращаться в ложный длинный снимок."""
        first = QImage(400, 600, QImage.Format_RGB32)
        second = QImage(400, 600, QImage.Format_RGB32)
        first.fill(Qt.white)
        second.fill(Qt.white)
        self.assertEqual(_scroll_overlap(first, second), 0)

    def test_scroll_speed_slider_updates_job_delay(self):
        panel = ScrollingCapturePanel(24)
        values = []
        panel.speed_changed.connect(values.append)
        try:
            self.assertEqual(panel.speed_slider.value(), 900)
            panel.speed_slider.setValue(1200)
            self.assertEqual(values, [1200])
            job = ScrollingScreenshotJob(QRect(0, 0, 200, 200))
            job.set_scroll_delay(1200)
            self.assertEqual(job.scroll_delay_ms, 1200)
            job.set_scroll_delay(100)
            self.assertEqual(job.scroll_delay_ms, 400)
        finally:
            panel.close_silently()

    def test_sticky_footer_is_detected_and_not_repeated_in_stitched_image(self):
        width, height, offset, footer = 80, 100, 30, 10
        before = QImage(width, height, QImage.Format_RGB32)
        after = QImage(width, height, QImage.Format_RGB32)
        painter = QPainter(before)
        for y in range(height - footer):
            painter.fillRect(0, y, width, 1, QColor(y, y, y))
        painter.fillRect(0, height - footer, width, footer, QColor("#eeeeee"))
        painter.end()
        painter = QPainter(after)
        for y in range(height - footer):
            value = y + offset
            painter.fillRect(0, y, width, 1, QColor(value, value, value))
        painter.fillRect(0, height - footer, width, footer, QColor("#eeeeee"))
        painter.end()

        _fixed_top, fixed_bottom = _scroll_fixed_bands(before, after)
        self.assertEqual(fixed_bottom, footer)
        stitched = _stitch_scroll_frames([before, after], [offset], [fixed_bottom])
        self.assertEqual(stitched.height(), height - footer + offset)
        self.assertEqual(stitched.pixelColor(10, height - footer - 1),
                         QColor(height - footer - 1, height - footer - 1, height - footer - 1))
        self.assertEqual(stitched.pixelColor(10, height - footer),
                         QColor(height - footer, height - footer, height - footer))
        self.assertEqual(stitched.pixelColor(10, stitched.height() - 1),
                         QColor(height + offset - footer - 1,
                                height + offset - footer - 1,
                                height + offset - footer - 1))

    def test_early_long_capture_preserves_first_frame_as_regular_screenshot(self):
        job = ScrollingScreenshotJob(QRect(0, 0, 80, 60))
        frame = QImage(80, 60, QImage.Format_RGB32)
        frame.fill(QColor("#445566"))
        job.frames.append(frame)
        launcher = Launcher.__new__(Launcher)
        launcher._scroll_job = job
        launcher._scroll_panel = None
        launcher._handle_captured_image = Mock()
        with patch("screenshot.ScrollingReviewDialog") as review:
            launcher._on_scrolling_finished(frame, "Прокрутка не обнаружена")
        review.assert_not_called()
        launcher._handle_captured_image.assert_called_once()
        self.assertEqual(launcher._handle_captured_image.call_args.kwargs["capture_kind"],
                         "shot")
        self.assertFalse(launcher._handle_captured_image.call_args.args[0].isNull())

    def test_scrolling_review_allows_manual_seam_adjustment(self):
        first = QImage(80, 100, QImage.Format_RGB32)
        second = QImage(80, 100, QImage.Format_RGB32)
        first.fill(QColor("#334455"))
        second.fill(QColor("#556677"))
        dialog = ScrollingReviewDialog([first, second], [30], [10], "Проверка")
        try:
            self.assertEqual(dialog.frame_strip.count(), 2)
            dialog.frame_strip.setCurrentRow(1)
            self.assertEqual(dialog.seam_combo.currentIndex(), 0)
            dialog.delta_spin.setValue(5)
            self.assertEqual(dialog.steps, [35])
            self.assertEqual(dialog.result_image().height(), 125)
        finally:
            dialog.close()

    def test_body_unchanged_detects_stopped_scroll(self):
        before = QImage(430, 600, QImage.Format_RGB32)
        before.fill(Qt.white)
        self.assertTrue(_scroll_body_unchanged(before, before.copy()))

        after = before.copy()
        painter = QPainter(after)
        painter.fillRect(45, 140, 300, 310, QColor("#293d66"))
        painter.end()
        self.assertFalse(_scroll_body_unchanged(before, after))

    @staticmethod
    def _animated_footer_frames():
        """Последняя страница с неподвижным текстом и анимированной карточкой."""
        width, height = 620, 720
        before = QImage(width, height, QImage.Format_RGB32)
        before.fill(Qt.white)
        painter = QPainter(before)
        painter.setPen(QColor("#162a3b"))
        painter.setFont(QFont("Arial", 15))
        for line, y in enumerate(range(35, height - 12, 25)):
            painter.drawText(38, y, f"Блок {line:03d}: длинный скриншот, проверка текста")
            painter.fillRect(290, y - 20, 18 + (line * 17) % 62, 4,
                             QColor("#5678a1"))
        painter.end()
        animated = before.copy()
        painter = QPainter(animated)
        painter.fillRect(30, 140, 165, 340, QColor("#bd4a2d"))
        for y in range(145, 475, 22):
            painter.fillRect(45, y, 126, 9, QColor("#467fae"))
        painter.end()
        return before, animated

    def test_dynamic_card_with_static_text_is_no_page_motion(self):
        before, animated = self._animated_footer_frames()
        self.assertFalse(_scroll_body_unchanged(before, animated))
        self.assertTrue(_scroll_stationary_content(before, animated))

    def test_visible_text_scroll_is_not_mistaken_for_stationary_page(self):
        width, height, offset = 620, 720, 88
        source = QImage(width, height + offset, QImage.Format_RGB32)
        source.fill(Qt.white)
        painter = QPainter(source)
        painter.setPen(QColor("#243447"))
        painter.setFont(QFont("Arial", 15))
        for index, y in enumerate(range(25, source.height(), 27)):
            painter.drawText(48, y,
                             f"Уникальная строка {index:03d} и её текстовый блок")
            painter.fillRect(185, y - 19, 10 + index * 3, 3,
                             QColor("#467fae"))
        painter.end()
        before = source.copy(0, 0, width, height)
        after = source.copy(0, offset, width, height)
        self.assertFalse(_scroll_stationary_content(before, after))
        self.assertTrue(_scrollbar_progressed((12, 100), (40, 100)))
        self.assertFalse(_scrollbar_progressed((40, 100), (40, 100)))

    def test_dynamic_footer_finishes_after_verified_still_frames(self):
        before, animated = self._animated_footer_frames()
        job = ScrollingScreenshotJob(QRect(0, 0, before.width(), before.height()))
        job.frames = [before.copy(), before.copy()]
        job.steps = [84]
        job.fixed_bottoms = [0]
        job._ever_scrolled = True
        outputs = []
        job.completed.connect(lambda image, message: outputs.append((image, message)))
        with patch("screenshot.grab_region_highdpi", return_value=animated), \
             patch("screenshot._scroll_overlap", return_value=0), \
             patch("screenshot._windows_scroll_state", return_value=None), \
             patch.object(job, "_advance") as advance:
            for _ in range(job.max_idle_retries - 1):
                job._take_next_frame()
                self.assertIsNone(job.finish_reason)
                self.assertFalse(job._paused)
            job._take_next_frame()
        self.assertEqual(job.finish_reason, "end")
        self.assertEqual(job.steps, [84])
        self.assertEqual(len(job.frames), 2)
        self.assertEqual(outputs[0][0].height(), before.height() + 84)
        self.assertIn("конец", outputs[0][1])
        self.assertEqual(advance.call_count, job.max_idle_retries - 1)

    def test_dynamic_footer_before_first_scroll_does_not_fake_completion(self):
        before, animated = self._animated_footer_frames()
        job = ScrollingScreenshotJob(QRect(0, 0, before.width(), before.height()))
        job.frames = [before.copy()]
        with patch("screenshot.grab_region_highdpi", return_value=animated), \
             patch("screenshot._scroll_overlap", return_value=0), \
             patch("screenshot._windows_scroll_state", return_value=None), \
             patch.object(job, "_advance"):
            for _ in range(job.max_idle_retries):
                job._take_next_frame()
        self.assertIsNone(job.finish_reason)
        self.assertTrue(job._paused)
        self.assertEqual(job._pause_reason, "no_movement")

    def test_real_native_scroll_motion_prevents_false_end(self):
        before, animated = self._animated_footer_frames()
        job = ScrollingScreenshotJob(QRect(0, 0, before.width(), before.height()))
        job.frames = [before.copy(), before.copy()]
        job.steps = [84]
        job.fixed_bottoms = [0]
        job._ever_scrolled = True
        job._last_scroll_state = (10, 100)
        with patch("screenshot.grab_region_highdpi", return_value=animated), \
             patch("screenshot._scroll_overlap", return_value=0), \
             patch("screenshot._windows_scroll_state", return_value=(24, 100)), \
             patch("screenshot.QTimer.singleShot") as timer:
            job._take_next_frame()
        self.assertIsNone(job.finish_reason)
        self.assertEqual(job._idle_retries, 0)
        self.assertEqual(job._alignment_retries, 1)
        self.assertEqual(timer.call_count, 1)

    def test_scrollbar_probe_returns_none_on_unsupported_platform(self):
        with patch("screenshot.sys.platform", "linux"):
            self.assertIsNone(_windows_scroll_state(QPoint(20, 20)))

    def test_scroll_panel_progress_and_finish_button(self):
        panel = ScrollingCapturePanel(24)
        called = []
        panel.finish_requested.connect(lambda: called.append(True))
        try:
            panel.set_progress(7, 24)
            panel.set_status("Прокрутка проверена")
            self.assertEqual(panel.counter.text(), "Прокруток: 7 из 24")
            self.assertEqual(panel.status.text(), "Прокрутка проверена")
            panel.findChild(QPushButton, "scroll_capture_finish").click()
            self.assertEqual(called, [True])
        finally:
            panel.close_silently()

    @staticmethod
    def _job_with_first_frame():
        job = ScrollingScreenshotJob(QRect(0, 0, 200, 200))
        frame = QImage(200, 200, QImage.Format_RGB32)
        frame.fill(QColor("white"))
        job.frames.append(frame)
        return job, frame

    def test_manual_finish_keeps_confirmed_frames_and_blocks_next_capture(self):
        job, frame = self._job_with_first_frame()
        second = frame.copy()
        second.fill(QColor("blue"))
        job.frames.append(second)
        job.steps.append(35)
        results = []
        job.completed.connect(lambda img, msg: results.append((img, msg)))
        job.stop()
        job.stop()
        self.assertEqual(job.finish_reason, "manual")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0].height(), 235)
        with patch("screenshot.grab_region_highdpi") as grab:
            job._take_next_frame()
            grab.assert_not_called()

    def test_native_scrollbar_at_end_does_not_stop_before_first_scroll(self):
        job, frame = self._job_with_first_frame()
        with patch("screenshot._windows_scroll_state", return_value=(100, 100)), \
             patch("screenshot.QTimer.singleShot") as timer:
            job._advance()
        self.assertIsNone(job.finish_reason)
        self.assertEqual(timer.call_args.args[1], job._send_scroll)

    def test_wheel_dispatch_targets_selected_window_before_capture(self):
        job, _frame = self._job_with_first_frame()
        job._target_hwnd = 1234
        with patch("screenshot._windows_focus_scroll_target", return_value=True) as focus, \
             patch("screenshot.ctypes.windll", create=True) as windll, \
             patch("screenshot.QTimer.singleShot") as timer:
            job._send_scroll()
        focus.assert_called_once_with(1234)
        windll.user32.mouse_event.assert_called_once()
        self.assertEqual(timer.call_count, 2)
        self.assertEqual(timer.call_args.args[1], job._capture_next)

    def test_progress_panel_is_hidden_before_dispatching_wheel(self):
        job, _frame = self._job_with_first_frame()
        panel = ScrollingCapturePanel(24)
        job.attach_panel(panel)
        try:
            with patch.object(panel, "hide") as hide, \
                 patch("screenshot.QTimer.singleShot") as timer:
                job._advance()
            hide.assert_called_once()
            self.assertEqual(timer.call_args.args[1], job._send_scroll)
        finally:
            panel.close_silently()

    def test_failed_long_capture_preserves_first_frame_as_regular_screenshot(self):
        with patch.object(Launcher, "_init_tray"), \
             patch.object(Launcher, "_install_global_hotkey"):
            launcher = Launcher()
        job, frame = self._job_with_first_frame()
        launcher._scroll_job = job
        try:
            with patch.object(launcher, "_handle_captured_image") as finish:
                launcher._on_scrolling_finished(frame.copy(), "Страница не прокрутилась.")
            finish.assert_called_once()
            self.assertEqual(finish.call_args.kwargs["capture_kind"], "shot")
        finally:
            launcher.close()

    def test_confirmed_scroll_still_passes_assembled_capture_to_launcher(self):
        with patch.object(Launcher, "_init_tray"), \
             patch.object(Launcher, "_install_global_hotkey"):
            launcher = Launcher()
        job, frame = self._job_with_first_frame()
        job.steps.append(20)
        launcher._scroll_job = job
        try:
            with patch.object(launcher, "_handle_captured_image") as finish:
                launcher._on_scrolling_finished(frame.copy(), "")
            finish.assert_called_once()
        finally:
            launcher.close()

    def test_false_native_scrollbar_end_does_not_stop_after_first_frame(self):
        job, frame = self._job_with_first_frame()
        next_frame = frame.copy()
        next_frame.fill(QColor("blue"))
        with patch("screenshot.grab_region_highdpi", return_value=next_frame), \
             patch("screenshot._scroll_body_unchanged", return_value=False), \
             patch("screenshot._scroll_overlap", return_value=60), \
             patch("screenshot._windows_scroll_state", return_value=(100, 100)), \
             patch.object(job, "_advance") as advance:
            job._take_next_frame()
        self.assertIsNone(job.finish_reason)
        self.assertEqual(job.steps, [60])
        advance.assert_called_once()

    def test_first_still_frame_retries_instead_of_finishing(self):
        job, frame = self._job_with_first_frame()
        job._last_scroll_state = (100, 100)
        with patch("screenshot.grab_region_highdpi", return_value=frame.copy()), \
             patch("screenshot._scroll_body_unchanged", return_value=True), \
             patch("screenshot._windows_scroll_state", return_value=(100, 100)), \
             patch.object(job, "_advance") as advance:
            job._take_next_frame()
        self.assertIsNone(job.finish_reason)
        self.assertEqual(job._idle_retries, 1)
        advance.assert_called_once()

    def test_real_end_requires_five_still_frames_after_movement(self):
        job, frame = self._job_with_first_frame()
        job._ever_scrolled = True
        output = []
        job.completed.connect(lambda img, msg: output.append(msg))
        with patch("screenshot.grab_region_highdpi", return_value=frame.copy()), \
             patch("screenshot._scroll_body_unchanged", return_value=True), \
             patch("screenshot._windows_scroll_state", return_value=None), \
             patch.object(job, "_advance"):
            for _ in range(job.max_idle_retries - 1):
                job._take_next_frame()
                self.assertIsNone(job.finish_reason)
            job._take_next_frame()
        self.assertEqual(job.finish_reason, "end")
        self.assertIn("конец", output[0])

    def test_native_bar_at_bottom_without_scroll_reports_no_movement(self):
        job, frame = self._job_with_first_frame()
        job._last_scroll_state = (100, 100)
        with patch("screenshot.grab_region_highdpi", return_value=frame.copy()), \
             patch("screenshot._scroll_body_unchanged", return_value=True), \
             patch("screenshot._windows_scroll_state", return_value=(100, 100)), \
             patch.object(job, "_advance"):
            for _ in range(job.max_idle_retries):
                job._take_next_frame()
        self.assertIsNone(job.finish_reason)
        self.assertTrue(job._paused)
        self.assertEqual(job._pause_reason, "no_movement")

    def test_scroll_panel_does_not_take_focus(self):
        panel = ScrollingCapturePanel(24)
        try:
            self.assertTrue(bool(panel.windowFlags() & Qt.WindowDoesNotAcceptFocus))
            panel.reposition_outside(QRect(0, 0, 200, 200))
        finally:
            panel.close_silently()

    def test_no_movement_is_distinct_from_end_of_page(self):
        job, frame = self._job_with_first_frame()
        job._last_scroll_state = (20, 100)
        with patch("screenshot.grab_region_highdpi", return_value=frame.copy()), \
             patch("screenshot._scroll_body_unchanged", return_value=True), \
             patch("screenshot._windows_scroll_state", return_value=(20, 100)), \
             patch.object(job, "_advance"):
            for _ in range(job.max_idle_retries):
                job._take_next_frame()
        self.assertIsNone(job.finish_reason)
        self.assertTrue(job._paused)
        self.assertEqual(job._pause_reason, "no_movement")

    def test_missing_native_scrollbar_uses_visual_no_change_signal(self):
        job, frame = self._job_with_first_frame()
        with patch("screenshot.grab_region_highdpi", return_value=frame.copy()), \
             patch("screenshot._scroll_body_unchanged", return_value=True), \
             patch("screenshot._windows_scroll_state", return_value=None), \
             patch.object(job, "_advance"):
            for _ in range(job.max_idle_retries):
                job._take_next_frame()
        self.assertIsNone(job.finish_reason)
        self.assertTrue(job._paused)
        self.assertEqual(job._pause_reason, "no_movement")

    def test_alignment_error_does_not_append_corrupt_frame(self):
        job, frame = self._job_with_first_frame()
        result = []
        job.completed.connect(lambda img, msg: result.append(img))
        with patch("screenshot.grab_region_highdpi", return_value=frame.copy()), \
             patch("screenshot._scroll_body_unchanged", return_value=False), \
             patch("screenshot._scroll_overlap", return_value=0), \
             patch("screenshot._windows_scroll_state", return_value=None), \
             patch("screenshot.QTimer.singleShot") as timer, \
             patch.object(job, "_advance") as advance:
            job._take_next_frame()
            self.assertIsNone(job.finish_reason)
            job._take_next_frame()
            self.assertIsNone(job.finish_reason)
            job._take_next_frame()
            advance.assert_not_called()
            self.assertEqual(timer.call_count, 2)
        self.assertIsNone(job.finish_reason)
        self.assertTrue(job._paused)
        self.assertEqual(job._pause_reason, "alignment")
        self.assertEqual(len(job.frames), 1)
        self.assertEqual(result, [])
        job.stop()
        self.assertEqual(job.finish_reason, "manual")
        self.assertEqual(result[0].height(), 200)

    def test_scroll_after_idle_retry_resets_idle_counter(self):
        job, frame = self._job_with_first_frame()
        job._idle_retries = 2
        changed = frame.copy()
        changed.fill(QColor("#665544"))
        with patch("screenshot.grab_region_highdpi", return_value=changed), \
             patch("screenshot._scroll_body_unchanged", return_value=False), \
             patch("screenshot._scroll_overlap", return_value=44), \
             patch("screenshot._windows_scroll_state", return_value=None), \
             patch.object(job, "_advance"):
            job._take_next_frame()
        self.assertEqual(job._idle_retries, 0)
        self.assertTrue(job._ever_scrolled)
        self.assertIsNone(job.finish_reason)
        self.assertEqual(job.steps, [44])

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

    def test_npcore_pair_config_requires_https_and_valid_code(self):
        code = "A" * 24
        self.assertEqual(_npcore_pair_config('{"server":"https://npcore.example","code":"' + code + '"}'),
                         ("https://npcore.example", code))
        self.assertEqual(_npcore_pair_config("https://npcore.example " + code),
                         ("https://npcore.example", code))
        for value in ("http://npcore.example " + code,
                      "https://npcore.example/path " + code,
                      "https://npcore.example " + "x" * 23):
            with self.assertRaises(ValueError):
                _npcore_pair_config(value)

    def test_npcore_translate_uses_paired_bearer_and_desk_endpoint(self):
        expected = {"ok": True, "text": "Hello", "detected_language": "Russian"}
        with patch("screenshot._npcore_load_link", return_value=("https://npcore.example", "T" * 43)), patch(
                "screenshot._npcore_http_json", return_value=expected) as request:
            result = _npcore_translate("Привет", "en")
        self.assertEqual(result, expected)
        request.assert_called_once_with(
            "POST", "https://npcore.example/api/desk/translate", "T" * 43,
            {"text": "Привет", "source": "auto", "target": "en"}, timeout=75)

    def test_ocr_dialog_shows_translation_inline_without_opening_browser(self):
        dialog = OCRResultDialog("Hello world")
        try:
            self.assertEqual(dialog.target_language.currentData(), "ru")
            self.assertFalse(dialog.translation_edit.isVisible())
            dialog._translation_completed({"ok": True, "result": {
                "text": "Привет, мир!", "detected_language": "English"}})
            self.assertEqual(dialog.translation_edit.toPlainText(), "Привет, мир!")
            self.assertIn("English", dialog.translation_status.text())
            self.assertFalse(dialog.translation_edit.isHidden())
        finally:
            dialog.close()

    def test_default_capture_is_not_changed_by_new_features(self):
        preferences = load_capture_preferences()
        self.assertIn("quick_actions", preferences)
        self.assertIn("edit_after_capture", preferences)
        self.assertIn("history_enabled", preferences)


    def test_tolerant_alignment_handles_color_drift_and_sticky_header(self):
        """Склейка должна переживать небольшое изменение цвета всех строк."""
        width, height, offset = 520, 660, 187
        source = QImage(width, height + offset + 100, QImage.Format_RGB32)
        source.fill(QColor("white"))
        painter = QPainter(source)
        painter.setPen(QColor("#15273a"))
        painter.setFont(QFont("Arial", 15))
        for i, y in enumerate(range(92, source.height(), 26)):
            painter.drawText(30, y, f"Строка №{i:03d}: проверка длинного снимка")
            painter.fillRect(40, y - 20, 8 + (i * 17) % 65, 3,
                             QColor("#4774a6"))
        painter.end()
        first = source.copy(0, 0, width, height)
        second = source.copy(0, offset, width, height)
        # Полупрозрачное перекрытие меняет яркость исходного текста и фона,
        # поэтому точное сопоставление целых строк больше невозможно.
        painter = QPainter(second)
        painter.fillRect(second.rect(), QColor(50, 35, 65, 38))
        painter.end()
        for frame in (first, second):
            painter = QPainter(frame)
            painter.fillRect(0, 0, width, 70, QColor("#293450"))
            painter.setPen(Qt.white)
            painter.drawText(30, 35, "ЗАКРЕПЛЁННОЕ МЕНЮ")
            painter.end()
        detected = _scroll_overlap(first, second)
        self.assertEqual(detected, offset)
        stitched = _stitch_scroll_frames([first, second], [detected])
        self.assertEqual(stitched.height(), height + offset)
        self.assertEqual(stitched.width(), width)

    def test_tolerant_alignment_rejects_uninformative_background(self):
        first = QImage(450, 560, QImage.Format_RGB32)
        second = QImage(450, 560, QImage.Format_RGB32)
        first.fill(QColor("#fdfdfd"))
        second.fill(QColor("#fafafa"))
        self.assertEqual(_scroll_overlap(first, second), 0)

    def test_repeated_text_rows_do_not_force_ambiguous_stitch(self):
        """Повторяющиеся одинаковые строки не определяют единственный сдвиг."""
        width, height, offset = 430, 620, 144
        source = QImage(width, height + offset + 50, QImage.Format_RGB32)
        source.fill(Qt.white)
        painter = QPainter(source)
        painter.setPen(Qt.black)
        painter.setFont(QFont("Arial", 14))
        for y in range(36, source.height(), 24):
            painter.drawText(32, y, "Повторяемая строка таблицы")
        painter.end()
        before = source.copy(0, 0, width, height)
        after = source.copy(0, offset, width, height)
        painter = QPainter(after)
        painter.fillRect(after.rect(), QColor(50, 35, 65, 38))
        painter.end()
        self.assertEqual(_scroll_overlap(before, after), 0)

    def test_no_movement_pauses_and_can_continue_from_user_pointer(self):
        job, frame = self._job_with_first_frame()
        panel = ScrollingCapturePanel(12)
        job.attach_panel(panel)
        try:
            with patch("screenshot.grab_region_highdpi", return_value=frame.copy()), \
                 patch("screenshot._scroll_body_unchanged", return_value=True), \
                 patch("screenshot._windows_scroll_state", return_value=None), \
                 patch.object(job, "_advance"):
                for _ in range(job.max_idle_retries):
                    job._take_next_frame()
            self.assertTrue(job._paused)
            self.assertIsNone(job.finish_reason)
            self.assertFalse(panel.continue_button.isHidden())
            with patch("screenshot._windows_target_for_scroll", return_value=123), \
                 patch("screenshot.QTimer.singleShot") as timer, \
                 patch.object(job, "_advance") as advance:
                job.resume()
                timer.assert_called_once_with(1700, job._resume_at_pointer)
                self.assertTrue(job._paused)
                job._resume_at_pointer()
            self.assertFalse(job._paused)
            self.assertEqual(job._idle_retries, 0)
            advance.assert_called_once()
        finally:
            panel.close_silently()

    def test_alignment_pause_retries_frame_before_scrolling_again(self):
        job, frame = self._job_with_first_frame()
        with patch("screenshot.grab_region_highdpi", return_value=frame.copy()), \
             patch("screenshot._scroll_body_unchanged", return_value=False), \
             patch("screenshot._scroll_overlap", return_value=0), \
             patch("screenshot.QTimer.singleShot") as timer:
            for _ in range(3):
                job._take_next_frame()
            self.assertTrue(job._paused)
            self.assertIsNone(job.finish_reason)
            self.assertEqual(timer.call_count, 2)
            job.resume()
            timer.assert_any_call(550, job._capture_next)
            self.assertFalse(job._paused)

    def test_output_pixel_limit_prevents_oversized_image(self):
        job, frame = self._job_with_first_frame()
        job.max_output_pixels = 200 * 210
        changed = frame.copy()
        changed.fill(QColor("#334455"))
        with patch("screenshot.grab_region_highdpi", return_value=changed), \
             patch("screenshot._scroll_body_unchanged", return_value=False), \
             patch("screenshot._scroll_overlap", return_value=60), \
             patch("screenshot._windows_scroll_state", return_value=None):
            job._take_next_frame()
        self.assertEqual(job.finish_reason, "limit")
        self.assertEqual(job.steps, [])

    def test_source_frame_budget_stops_before_memory_exhaustion(self):
        job, frame = self._job_with_first_frame()
        job.max_frame_pixels = frame.width() * frame.height()
        changed = frame.copy()
        changed.fill(QColor("#334455"))
        with patch("screenshot.grab_region_highdpi", return_value=changed), \
             patch("screenshot._scroll_body_unchanged", return_value=False), \
             patch("screenshot._scroll_overlap", return_value=45), \
             patch("screenshot._windows_scroll_state", return_value=None):
            job._take_next_frame()
        self.assertEqual(job.finish_reason, "limit")
        self.assertEqual(len(job.frames), 1)
        self.assertEqual(job.steps, [])

    def test_review_offers_native_resolution_seam(self):
        first = QImage(120, 170, QImage.Format_RGB32)
        second = QImage(120, 170, QImage.Format_RGB32)
        first.fill(Qt.white)
        second.fill(Qt.black)
        dialog = ScrollingReviewDialog([first, second], [62], [0])
        try:
            dialog.zoom_combo.setCurrentIndex(1)
            self.assertEqual(dialog.zoom_combo.currentData(), "seam")
            self.assertEqual(dialog.preview.pixmap().width(), 120)
        finally:
            dialog.close()

if __name__ == "__main__":
    unittest.main()
