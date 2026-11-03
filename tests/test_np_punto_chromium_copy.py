"""Отложенная публикация текста в Chrome и безопасность clipboard fallback."""
import importlib.util
from contextlib import contextmanager
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / "Other_dev" / "punto_like_work_safe.py"
SPEC = importlib.util.spec_from_file_location("np_punto_chromium_copy", SOURCE)
punto = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = punto
SPEC.loader.exec_module(punto)


class CopyWaitTests(unittest.TestCase):
    def run_wait(self, sequence, text_values):
        clock = [100.0]
        user32 = Mock()
        user32.GetClipboardSequenceNumber.side_effect = sequence
        get_text = Mock(side_effect=text_values)
        mark = Mock()

        def sleep(seconds):
            clock[0] += seconds

        with patch.object(punto, "user32", user32), \
             patch.object(punto, "_clipboard_get_text", get_text), \
             patch.object(punto, "_clipboard_mark_expected_sequence", mark), \
             patch.object(punto.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(punto.time, "sleep", side_effect=sleep):
            result = punto._wait_for_new_clipboard_text(
                100,
                punto.Timings(
                    copy_poll_timeout_seconds=0.12,
                    copy_poll_interval_seconds=0.02,
                ),
            )
        return result, get_text, mark

    def test_chrome_first_change_empty_then_unicode_text_arrives(self):
        result, get_text, mark = self.run_wait(
            [101, 101, 101], ["", "ghbdtn"],
        )
        self.assertEqual(result, "ghbdtn")
        self.assertEqual(get_text.call_count, 2)
        self.assertEqual(mark.call_count, 2)

    def test_chrome_clipboard_temporarily_locked_then_text_arrives(self):
        result, get_text, mark = self.run_wait(
            [101, 101, 101], [OSError("Busy clipboard"), "ghbdtn"],
        )
        self.assertEqual(result, "ghbdtn")
        self.assertEqual(get_text.call_count, 2)
        self.assertEqual(mark.call_count, 2)

    def test_unchanged_clipboard_does_not_return_stale_text(self):
        result, get_text, mark = self.run_wait([100] * 12, [])
        self.assertIsNone(result)
        get_text.assert_not_called()
        mark.assert_not_called()

    def test_copy_without_unicode_text_does_not_report_false_success(self):
        result, get_text, mark = self.run_wait([101] * 12, [""] * 12)
        self.assertIsNone(result)
        self.assertGreater(get_text.call_count, 1)
        self.assertGreater(mark.call_count, 1)


@contextmanager
def fake_clipboard_guard(_timings):
    yield object()


class ChromeFocusTests(unittest.TestCase):
    def setUp(self):
        self.windows = Mock()
        self.windows.GetForegroundWindow.return_value = 101
        self.windows.GetClipboardSequenceNumber.return_value = 55
        self.focus = [202]

    def run_fallback(self, *, foreground=None, focus=None, selected="ghbdtn"):
        if foreground is not None:
            self.windows.GetForegroundWindow.side_effect = foreground
        if focus is not None:
            self.focus = focus

        with patch.object(punto, "user32", self.windows), \
             patch.object(punto, "_get_focused_control_hwnd", side_effect=lambda: self.focus[0]), \
             patch.object(punto, "_clipboard_guard", fake_clipboard_guard), \
             patch.object(punto, "_press_combo_shift") as select_line, \
             patch.object(punto, "_press_combo_ctrl") as copy, \
             patch.object(punto, "_wait_for_new_clipboard_text", return_value=selected), \
             patch.object(punto, "_transform_run_before_caret_text",
                          return_value=(0, 6, "привет")), \
             patch.object(punto, "_replace_selection_with_text", return_value=False) as paste, \
             patch.object(punto, "_collapse_selection_to_right") as collapse, \
             patch.object(punto.time, "sleep"):
            value = punto._transform_run_before_caret_via_clipboard(
                punto.Timings(), punto.convert_keyboard_layout,
            )
        return value, select_line, copy, paste, collapse

    def test_chrome_normal_copy_converts_without_discarding_target(self):
        value, select_line, copy, paste, collapse = self.run_fallback()
        self.assertEqual(value, "привет")
        select_line.assert_called_once()
        copy.assert_called_once()
        paste.assert_called_once_with("привет", unittest.mock.ANY)
        collapse.assert_not_called()

    def test_chrome_switches_tab_during_copy_and_stale_paste_is_aborted(self):
        value, select_line, copy, paste, collapse = self.run_fallback(
            foreground=[101, 101, 303],
        )
        self.assertIsNone(value)
        select_line.assert_called_once()
        copy.assert_called_once()
        paste.assert_not_called()
        collapse.assert_not_called()

    def test_chrome_focus_changed_during_copy_and_stale_paste_is_aborted(self):
        calls = [202, 202, 303]

        def next_focus():
            return calls.pop(0) if calls else 303

        with patch.object(punto, "user32", self.windows), \
             patch.object(punto, "_get_focused_control_hwnd", side_effect=next_focus), \
             patch.object(punto, "_clipboard_guard", fake_clipboard_guard), \
             patch.object(punto, "_press_combo_shift"), \
             patch.object(punto, "_press_combo_ctrl"), \
             patch.object(punto, "_wait_for_new_clipboard_text", return_value="ghbdtn"), \
             patch.object(punto, "_replace_selection_with_text") as paste, \
             patch.object(punto, "_collapse_selection_to_right") as collapse, \
             patch.object(punto.time, "sleep"):
            value = punto._transform_run_before_caret_via_clipboard(
                punto.Timings(), punto.convert_keyboard_layout,
            )
        self.assertIsNone(value)
        paste.assert_not_called()
        collapse.assert_not_called()


if __name__ == "__main__":
    unittest.main()
