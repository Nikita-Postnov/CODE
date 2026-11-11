"""Notepad++/Scintilla regression tests for Ctrl+Insert."""
import importlib.util
from contextlib import contextmanager
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, call, patch

SOURCE = Path(__file__).resolve().parents[1] / "Other_dev" / "punto_like_work_safe.py"
SPEC = importlib.util.spec_from_file_location("np_punto_scintilla", SOURCE)
punto = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = punto
SPEC.loader.exec_module(punto)


@contextmanager
def clipboard_guard(_timings):
    yield None


class ScintillaTests(unittest.TestCase):
    def test_scintilla_class_does_not_masquerade_as_win32_edit(self):
        with patch.object(punto, "_get_class_name", return_value="Scintilla"):
            self.assertTrue(punto._is_scintilla_control(42))
            self.assertFalse(punto._is_edit_like_class("Scintilla"))
        with patch.object(punto, "_get_class_name", return_value="Edit"):
            self.assertFalse(punto._is_scintilla_control(42))

    def test_scintilla_line_bounds_use_byte_positions(self):
        responses = {
            punto._SCI_GETSELECTIONS: 1,
            punto._SCI_GETCURRENTPOS: 6,
            punto._SCI_GETSELECTIONSTART: 6,
            punto._SCI_GETSELECTIONEND: 6,
            punto._SCI_LINEFROMPOSITION: 0,
            punto._SCI_POSITIONFROMLINE: 0,
        }
        with patch.object(punto, "_is_scintilla_control", return_value=True), \
             patch.object(punto, "_sendmsg", side_effect=lambda hwnd, msg, *args: responses[msg]):
            self.assertEqual(punto._scintilla_line_before_caret(42, 40000), (0, 6))
            self.assertIsNone(punto._scintilla_line_before_caret(42, 3))

    def test_scintilla_multiselection_is_left_alone(self):
        with patch.object(punto, "_is_scintilla_control", return_value=True), \
             patch.object(punto, "_sendmsg", return_value=2):
            self.assertIsNone(punto._scintilla_line_before_caret(42, 40000))

    def test_routing_is_specific_to_scintilla(self):
        timing = punto.Timings()
        with patch.object(punto, "_get_focused_control_hwnd", return_value=42), \
             patch.object(punto, "_is_password_edit", return_value=False), \
             patch.object(punto, "_is_scintilla_control", return_value=True), \
             patch.object(punto, "_transform_run_before_caret_scintilla", return_value="привет") as specialized, \
             patch.object(punto, "_edit_get_sel") as edit, \
             patch.object(punto, "user32", Mock()):
            value = punto._transform_run_before_caret(timing, punto.convert_keyboard_layout)
        self.assertEqual(value, "привет")
        specialized.assert_called_once_with(42, timing, punto.convert_keyboard_layout)
        edit.assert_not_called()

    def perform(self, copied, *, focus_changes=None, copy_wait=None):
        windows = Mock()
        windows.GetForegroundWindow.return_value = 7
        windows.GetClipboardSequenceNumber.return_value = 100
        focus_list = focus_changes or [42] * 10
        def focus():
            return focus_list.pop(0) if focus_list else 42
        selection = [0, 6]
        messages = []
        def send(hwnd, msg, wparam=0, lparam=0):
            messages.append((msg, wparam, lparam))
            if msg == punto._SCI_GETSELECTIONSTART:
                return selection[0]
            if msg == punto._SCI_GETSELECTIONEND:
                return selection[1]
            return 0
        def sent_ok(hwnd, msg, a, b):
            messages.append((msg, a, b))
            if msg == punto._SCI_SETSEL:
                selection[:] = [min(a,b), max(a,b)]
            return True
        def paste(text, timings):
            selection[:] = [len(text.encode("utf-8")), len(text.encode("utf-8"))]
            return True
        copier = Mock(side_effect=copy_wait or [copied])
        with patch.object(punto, "user32", windows), \
             patch.object(punto, "_get_focused_control_hwnd", side_effect=focus), \
             patch.object(punto, "_clipboard_guard", clipboard_guard), \
             patch.object(punto, "_scintilla_line_before_caret", return_value=(0,6)), \
             patch.object(punto, "_sendmsg", side_effect=send), \
             patch.object(punto, "_sendmsg_ok", side_effect=sent_ok), \
             patch.object(punto, "_wait_for_new_clipboard_text", copier), \
             patch.object(punto, "_press_combo_ctrl") as ctrl_copy, \
             patch.object(punto, "_replace_selection_with_text", side_effect=paste) as replace, \
             patch.object(punto.time, "sleep"):
            result = punto._transform_run_before_caret_scintilla(
                42, punto.Timings(), punto.convert_keyboard_layout
            )
        return result, messages, ctrl_copy, replace

    def test_notepadplusplus_word_becomes_privet(self):
        result, messages, ctrl_copy, replace = self.perform("ghbdtn")
        self.assertEqual(result, "привет")
        self.assertIn((punto._SCI_SETSEL, 0, 6), messages)
        self.assertIn((punto._SCI_COPY, 0, 0), messages)
        replace.assert_called_once()
        self.assertEqual(replace.call_args.args[0], "привет")
        ctrl_copy.assert_not_called()

    def test_copy_retry_for_unresponsive_scintilla_plugin(self):
        result, messages, ctrl_copy, replace = self.perform(
            "ghbdtn", copy_wait=[None, "ghbdtn"]
        )
        self.assertEqual(result, "привет")
        ctrl_copy.assert_called_once()
        self.assertEqual(replace.call_count, 1)

    def test_missing_text_restores_caret_without_paste(self):
        result, messages, ctrl_copy, replace = self.perform(
            None, copy_wait=[None, None]
        )
        self.assertIsNone(result)
        replace.assert_not_called()
        self.assertIn((punto._SCI_SETSEL, 6, 6), messages)

    def test_foreground_change_aborts_without_paste(self):
        windows = Mock()
        windows.GetForegroundWindow.side_effect = [7, 7, 99, 99]
        windows.GetClipboardSequenceNumber.return_value = 100
        with patch.object(punto, "user32", windows), \
             patch.object(punto, "_get_focused_control_hwnd", return_value=42), \
             patch.object(punto, "_scintilla_line_before_caret", return_value=(0, 6)), \
             patch.object(punto, "_clipboard_guard", clipboard_guard), \
             patch.object(punto, "_sendmsg", return_value=0), \
             patch.object(punto, "_sendmsg_ok", return_value=True) as send, \
             patch.object(punto, "_wait_for_new_clipboard_text", return_value="ghbdtn"), \
             patch.object(punto, "_replace_selection_with_text") as replace:
            value = punto._transform_run_before_caret_scintilla(
                42, punto.Timings(), punto.convert_keyboard_layout
            )
        self.assertIsNone(value)
        replace.assert_not_called()
        send.assert_called_once_with(42, punto._SCI_SETSEL, 0, 6)



if __name__ == "__main__":
    unittest.main()
