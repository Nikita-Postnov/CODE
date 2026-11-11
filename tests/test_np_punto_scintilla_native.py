"""Прямые операции Scintilla без модификации буфера обмена OLE."""
import importlib.util
from contextlib import contextmanager
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[1] / "Other_dev" / "punto_like_work_safe.py"
SPEC = importlib.util.spec_from_file_location("punto_scintilla_native", SOURCE)
punto = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = punto
SPEC.loader.exec_module(punto)


@contextmanager
def temporary_remote(_hwnd, _capacity):
    yield object(), 4096


class FakeScintilla:
    def __init__(self, text, readonly=False, codepage=65001):
        self.doc = bytearray(text.encode("utf-8"))
        self.caret = len(self.doc)
        self.selection = (self.caret, self.caret)
        self.target = [2, 4]
        self.remote = b""
        self.replacement_bytes = None
        self.replace_count = 0
        self.readonly = readonly
        self.codepage = codepage
        self.copy_count = 0

    def message(self, hwnd, msg, wparam=0, lparam=0):
        if msg == punto._SCI_GETCODEPAGE:
            return self.codepage
        if msg == punto._SCI_GETREADONLY:
            return int(self.readonly)
        if msg == punto._SCI_GETTARGETSTART:
            return self.target[0]
        if msg == punto._SCI_GETTARGETEND:
            return self.target[1]
        if msg == punto._SCI_GETTARGETTEXT:
            self.remote = bytes(self.doc[self.target[0]:self.target[1]])
            return len(self.remote)
        if msg == punto._SCI_REPLACETARGET:
            assert self.replacement_bytes is not None
            assert len(self.replacement_bytes) == wparam
            self.doc[self.target[0]:self.target[1]] = self.replacement_bytes
            self.replace_count += 1
            return len(self.replacement_bytes)
        if msg == punto._SCI_COPY:
            self.copy_count += 1
        return 0

    def message_ok(self, hwnd, msg, wparam, lparam):
        if msg == punto._SCI_SETTARGETSTART:
            self.target[0] = wparam
        elif msg == punto._SCI_SETTARGETEND:
            self.target[1] = wparam
        elif msg == punto._SCI_SETEMPTYSELECTION:
            self.caret = wparam
            self.selection = (wparam, wparam)
        return True


class ScintillaNativeTests(unittest.TestCase):
    def run_native(self, editor, *, focus=42, data_available=True):
        user = Mock()
        user.GetForegroundWindow.return_value = 7
        clipboard = Mock()
        if data_available:
            reader = lambda process, address, n: editor.remote[:n]
        else:
            reader = lambda process, address, n: None
        writer = Mock(side_effect=lambda process, address, payload:
                      setattr(editor, "replacement_bytes", payload) or True)
        with patch.object(punto, "user32", user), \
             patch.object(punto, "_scintilla_line_before_caret",
                          side_effect=lambda hwnd, limit: (0, editor.caret)), \
             patch.object(punto, "_get_focused_control_hwnd", return_value=focus), \
             patch.object(punto, "_clipboard_capture_target_matches", return_value=True), \
             patch.object(punto, "_scintilla_remote_memory", temporary_remote), \
             patch.object(punto, "_scintilla_remote_read", side_effect=reader), \
             patch.object(punto, "_scintilla_remote_write", writer), \
             patch.object(punto, "_sendmsg", side_effect=editor.message), \
             patch.object(punto, "_sendmsg_ok", side_effect=editor.message_ok), \
             patch.object(punto, "_clipboard_guard") as forbidden_clipboard:
            result = punto._scintilla_clipboard_free(
                42, punto.Timings(), punto.convert_keyboard_layout)
        forbidden_clipboard.assert_not_called()
        return result, writer

    def test_notepadplusplus_ghbdtn_to_privet_without_clipboard(self):
        editor = FakeScintilla("ghbdtn")
        result, writer = self.run_native(editor)
        self.assertEqual(result, "привет")
        self.assertEqual(editor.doc.decode("utf-8"), "привет")
        self.assertEqual(editor.replace_count, 1)
        self.assertEqual(editor.copy_count, 0)
        self.assertEqual(editor.target, [2, 4])
        self.assertEqual(editor.caret, len("привет".encode("utf-8")))
        writer.assert_called_once()

    def test_mixed_language_replaces_only_latin_run_using_utf8_byte_offsets(self):
        editor = FakeScintilla("привет ghbdtn")
        result, writer = self.run_native(editor)
        self.assertEqual(result, "привет")
        self.assertEqual(editor.doc.decode("utf-8"), "привет привет")
        self.assertEqual(editor.caret, len("привет привет".encode("utf-8")))
        self.assertEqual(editor.replace_count, 1)

    def test_readonly_and_non_utf8_skip_without_writing(self):
        for option in ({"readonly": True}, {"codepage": 1251}):
            with self.subTest(option=option):
                editor = FakeScintilla("ghbdtn", **option)
                result, writer = self.run_native(editor)
                self.assertIsNone(result)
                self.assertEqual(editor.doc.decode("utf-8"), "ghbdtn")
                writer.assert_not_called()

    def test_missing_remote_read_skips_safely(self):
        editor = FakeScintilla("ghbdtn")
        result, writer = self.run_native(editor, data_available=False)
        self.assertIsNone(result)
        self.assertEqual(editor.replace_count, 0)
        writer.assert_not_called()

    def test_unfocused_editor_is_never_changed(self):
        editor = FakeScintilla("ghbdtn")
        result, writer = self.run_native(editor, focus=999)
        self.assertIsNone(result)
        self.assertEqual(editor.replace_count, 0)
        writer.assert_not_called()

    def test_native_route_precedes_unportable_clipboard_guard(self):
        with patch.object(punto, "_scintilla_clipboard_free", return_value="привет") as native, \
             patch.object(punto, "_clipboard_guard") as clipboard:
            result = punto._transform_run_before_caret_scintilla(
                42, punto.Timings(), punto.convert_keyboard_layout)
        self.assertEqual(result, "привет")
        native.assert_called_once()
        clipboard.assert_not_called()

    def test_unportable_dataobject_fallback_skips_without_exception(self):
        user = Mock()
        user.GetForegroundWindow.return_value = 7
        @contextmanager
        def unsafe(_timings):
            raise punto.ClipboardSnapshotUnsafe(
                "Небезопасно заменять буфер: непереносимый формат 49161 (DataObject)")
            yield
        with patch.object(punto, "user32", user), \
             patch.object(punto, "_scintilla_clipboard_free", return_value=None), \
             patch.object(punto, "_scintilla_line_before_caret", return_value=(0, 6)), \
             patch.object(punto, "_get_focused_control_hwnd", return_value=42), \
             patch.object(punto, "_clipboard_guard", unsafe), \
             patch.object(punto, "_clipboard_capture_target_matches", return_value=True):
            result = punto._transform_run_before_caret_scintilla(
                42, punto.Timings(), punto.convert_keyboard_layout)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
