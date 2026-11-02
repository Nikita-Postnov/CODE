"""Regression tests for NP Punto safety and portable Choice execution."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "Other_dev" / "punto_like_work_safe.py"
SPEC = importlib.util.spec_from_file_location("np_punto_reliability", SOURCE)
punto = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = punto
SPEC.loader.exec_module(punto)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_backup_recovers_settings(self):
        path = self.root / "settings.json"
        with patch.object(punto, "_settings_path", return_value=path):
            first = punto.Settings(idle_replace_delay_seconds=3.0)
            second = punto.Settings(idle_replace_delay_seconds=4.0)
            punto._atomic_write_text(path, json.dumps(punto._settings_to_dict(first)))
            punto._atomic_write_text(path, json.dumps(punto._settings_to_dict(second)))
            self.assertTrue((self.root / "settings.json.bak").is_file())
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(punto._load_settings().idle_replace_delay_seconds, 3.0)

    def test_corrupt_current_does_not_overwrite_good_backup(self):
        path = self.root / "settings.json"
        path.write_text("{bad", encoding="utf-8")
        backup = path.with_suffix(".json.bak")
        backup.write_text('{"ok": true}', encoding="utf-8")
        punto._atomic_write_text(path, '{"new": true}')
        self.assertEqual(json.loads(backup.read_text(encoding="utf-8")), {"ok": True})

    def test_rules_recover_from_backup(self):
        path = self.root / "rules.json"
        dictionary = self.root / "dictionary.txt"
        dictionary.write_text("", encoding="utf-8")
        with patch.object(punto, "_rules_path", return_value=path), \
             patch.object(punto, "_dictionary_path", return_value=dictionary):
            punto._save_rules(punto.RulesConfig(replace_rules=(punto.TextRule("aa", "first"),)))
            punto._save_rules(punto.RulesConfig(replace_rules=(punto.TextRule("bb", "second"),)))
            path.write_text("{", encoding="utf-8")
            restored = punto._load_rules()
            self.assertEqual(restored.replace_rules[0].trigger, "aa")

    def test_layout_correction_is_opt_in(self):
        self.assertFalse(punto.Settings().auto_layout_correction)
        config = punto._settings_to_dict(punto.Settings())
        self.assertFalse(config["auto_layout_correction"])
        valid, issues = punto._settings_from_dict(dict(config, auto_layout_correction=True))
        self.assertTrue(valid.auto_layout_correction)
        invalid, issues = punto._settings_from_dict(dict(config, auto_layout_correction="yes"))
        self.assertFalse(invalid.auto_layout_correction)
        self.assertTrue(issues)

    def test_layout_dictionary_only_unambiguous_whitelisted_words(self):
        words = frozenset({"привет", "спасибо", "hello"})
        self.assertEqual(punto._candidate_layout_correction("ghbdtn", words), "привет")
        self.assertEqual(punto._candidate_layout_correction("ghbdtn".upper(), words), "ПРИВЕТ")
        for sample in ("abc", "ghbвtn", "hello", "1234", "x", "https://example.com"):
            self.assertIsNone(punto._candidate_layout_correction(sample, words))

    def test_choice_owns_launcher_process(self):
        with patch.object(punto.sys, "platform", "win32"), \
             patch.dict(os.environ, {"CHOICE_PID": "12345"}), \
             patch.object(punto, "subprocess") as subprocess:
            punto._relaunch_under_own_exe()
        subprocess.Popen.assert_not_called()

    def test_default_undo_never_uses_plain_ctrl_z(self):
        config = punto._hotkey_definitions(punto.Hotkeys())
        undo = [items for ident, items, purpose in config if purpose == "undo-last-change"][0]
        self.assertNotIn((punto.MOD_CONTROL, punto.VK_Z), undo)


class ClipboardTests(unittest.TestCase):
    def test_snapshot_rejects_unsaved_formats_instead_of_erasing_them(self):
        unsupported = punto.CF_ENHMETAFILE
        self.assertFalse(punto._clipboard_snapshot_can_skip(unsupported, "", frozenset({unsupported})))
        with self.assertRaises(punto.ClipboardSnapshotUnsafe):
            punto._clipboard_snapshot_validate_format(unsupported, "", frozenset({unsupported}))

    def test_snapshot_deadline_and_memory_limits(self):
        with self.assertRaises(punto.ClipboardSnapshotUnsafe):
            punto._clipboard_snapshot_require_deadline(-1.0)
        with self.assertRaises(punto.ClipboardSnapshotUnsafe):
            punto._clipboard_snapshot_require_data(punto.CF_UNICODETEXT, b"hello", 10, 12)
        with self.assertRaises(punto.ClipboardSnapshotUnsafe):
            punto._clipboard_snapshot_require_data(punto.CF_UNICODETEXT, b"", 0, 100)

    def test_failed_snapshot_does_not_modify_clipboard(self):
        with patch.object(punto, "_clipboard_take_snapshot",
                          side_effect=punto.ClipboardSnapshotUnsafe("unsafe")), \
             patch.object(punto, "_clipboard_restore_snapshot") as restore:
            with self.assertRaises(punto.ClipboardSnapshotUnsafe):
                with punto._clipboard_guard(punto.Timings()):
                    self.fail("Guard must refuse operation when snapshot is incomplete")
        restore.assert_not_called()

    def test_guard_does_not_restore_on_read_only_operation(self):
        snapshot = punto.ClipboardSnapshot(((punto.CF_UNICODETEXT, b"A\x00\x00\x00"),))
        api = Mock()
        api.GetClipboardSequenceNumber.return_value = 5
        with patch.object(punto, "_clipboard_take_snapshot", return_value=snapshot), \
             patch.object(punto, "user32", api), \
             patch.object(punto, "_clipboard_restore_snapshot") as restore:
            with punto._clipboard_guard(punto.Timings()):
                pass
        restore.assert_not_called()

    def test_guard_restores_only_expected_sequence(self):
        snapshot = punto.ClipboardSnapshot()
        api = Mock()
        api.GetClipboardSequenceNumber.side_effect = [10, 11]
        with patch.object(punto, "_clipboard_take_snapshot", return_value=snapshot), \
             patch.object(punto, "user32", api), \
             patch.object(punto, "_clipboard_restore_snapshot", return_value=False) as restore:
            with punto._clipboard_guard(punto.Timings()):
                punto._clipboard_mark_expected_sequence()
        restore.assert_called_once()
        self.assertEqual(restore.call_args.kwargs["expected_seq"], 11)

    def test_restore_does_not_open_or_erase_changed_clipboard(self):
        snapshot = punto.ClipboardSnapshot(((punto.CF_UNICODETEXT, b"A\x00\x00\x00"),))
        api = Mock()
        api.GetClipboardSequenceNumber.return_value = 999
        with patch.object(punto, "user32", api), \
             patch.object(punto, "_open_clipboard_with_retry") as open_clip:
            self.assertFalse(punto._clipboard_restore_snapshot(
                snapshot, punto.Timings(), expected_seq=11))
        open_clip.assert_not_called()
        api.EmptyClipboard.assert_not_called()


class KeyboardTests(unittest.TestCase):
    def test_space_hotkey_never_waits_on_worker(self):
        worker = Mock()
        worker.busy = False
        with patch.object(punto, "_worker", worker), \
             patch.object(punto, "_idle"), \
             patch.object(punto, "_get_focused_control_hwnd", return_value=17), \
             patch.object(punto, "_is_text_input_focus", return_value=True), \
             patch.object(punto, "_space_keydown_blocked", False), \
             patch.object(punto, "_space_keydown_fg_hwnd", 45):
            punto._on_space_up(45, "notepad.exe")
        worker.run_sync.assert_not_called()
        worker.submit.assert_called_once()

    def test_stale_space_job_does_not_modify_text(self):
        worker = Mock()
        worker.busy = False
        current = punto._keyboard_input_revision
        with patch.object(punto, "_worker", worker), \
             patch.object(punto, "_idle"), \
             patch.object(punto, "_get_focused_control_hwnd", return_value=17), \
             patch.object(punto, "_is_text_input_focus", return_value=True), \
             patch.object(punto, "_space_keydown_blocked", False), \
             patch.object(punto, "_space_keydown_fg_hwnd", 45), \
             patch.object(punto, "_keyboard_input_revision", current), \
             patch.object(punto, "_apply_rules_in_edit") as apply:
            punto._on_space_up(45, "notepad.exe")
            callback = worker.submit.call_args.args[1]
            punto._keyboard_input_revision += 1
            callback()
        apply.assert_not_called()


if __name__ == "__main__":
    unittest.main()
