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

    def test_snapshot_sequence_change_aborts_before_user_action(self):
        snapshot = punto.ClipboardSnapshot(((punto.CF_UNICODETEXT, b"A\\x00"),), sequence=12)
        api = Mock()
        api.GetClipboardSequenceNumber.return_value = 13
        with patch.object(punto, "_clipboard_take_snapshot", return_value=snapshot), \
             patch.object(punto, "user32", api), \
             patch.object(punto, "_clipboard_restore_snapshot") as restore:
            with self.assertRaises(punto.ClipboardSnapshotUnsafe):
                with punto._clipboard_guard(punto.Timings()):
                    self.fail("Must not operate on a changed clipboard")
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
    def test_space_is_scheduled_after_target_has_processed_character(self):
        worker = Mock()
        idle = Mock()
        with patch.object(punto, "_worker", worker), \
             patch.object(punto, "_idle", idle), \
             patch.object(punto, "_settings", punto.Settings(auto_layout_correction=True)), \
             patch.object(punto, "_get_focused_control_hwnd", return_value=17), \
             patch.object(punto, "_is_text_input_focus", return_value=True), \
             patch.object(punto, "_space_keydown_blocked", False), \
             patch.object(punto, "_space_keydown_fg_hwnd", 45):
            punto._on_space_up(45, "notepad.exe")
        worker.run_sync.assert_not_called()
        worker.submit.assert_not_called()
        idle.schedule.assert_called_once()
        self.assertGreaterEqual(idle.schedule.call_args.args[0], 0.05)

    def test_space_callback_runs_only_if_focus_and_input_unchanged(self):
        idle = Mock()
        current = punto._keyboard_input_revision
        api = Mock()
        api.GetForegroundWindow.return_value = 45
        with patch.object(punto, "user32", api), \
             patch.object(punto, "_idle", idle), \
             patch.object(punto, "_settings", punto.Settings(auto_layout_correction=True)), \
             patch.object(punto, "_get_focused_control_hwnd", return_value=17), \
             patch.object(punto, "_is_text_input_focus", return_value=True), \
             patch.object(punto, "_space_keydown_blocked", False), \
             patch.object(punto, "_space_keydown_fg_hwnd", 45), \
             patch.object(punto, "_keyboard_input_revision", current), \
             patch.object(punto, "_apply_rules_in_edit") as apply:
            punto._on_space_up(45, "notepad.exe")
            callback = idle.schedule.call_args.args[1]
            callback()
            apply.assert_called_once_with(17, after_space=True)
            punto._keyboard_input_revision += 1
            callback()
            apply.assert_called_once()

    def test_legacy_notepad_and_modern_notepad_text_controls_recognized(self):
        self.assertTrue(punto._is_edit_like_class("Edit"))
        self.assertTrue(punto._is_edit_like_class("RichEditD2DPT"))
        self.assertTrue(punto._is_edit_like_class("RichEdit20W"))
        self.assertFalse(punto._is_edit_like_class("PasswordBox"))

    def test_auto_layout_replaces_dictionary_word_in_notepad(self):
        with patch.object(punto, "_settings", punto.Settings(auto_layout_correction=True)), \
             patch.object(punto, "_layout_words", frozenset({"привет"})), \
             patch.object(punto, "_get_collapsed_caret_from_edit", return_value=7), \
             patch.object(punto, "_read_edit_full_text", return_value="ghbdtn "), \
             patch.object(punto, "_replace_range_in_edit_safely", return_value=True) as replace, \
             patch.object(punto, "_switch_layout_toward_text") as switch:
            punto._apply_rules_in_edit(17, after_space=True)
        replace.assert_called_once_with(17, 0, 6, "ghbdtn", "привет", 7)
        switch.assert_called_once_with("привет")

    def test_no_auto_layout_in_standard_mode(self):
        with patch.object(punto, "_settings", punto.Settings(auto_layout_correction=False)), \
             patch.object(punto, "_layout_words", frozenset({"привет"})), \
             patch.object(punto, "_get_collapsed_caret_from_edit", return_value=7), \
             patch.object(punto, "_read_edit_full_text", return_value="ghbdtn "), \
             patch.object(punto, "_replace_range_in_edit_safely") as replace:
            punto._apply_rules_in_edit(17, after_space=True)
        replace.assert_not_called()




class RecoveryTests(unittest.TestCase):
    def test_busy_hotkey_does_not_disable_other_functions(self):
        candidates = [(1, [(0, punto.VK_INSERT)], "convert-selected"),
                      (2, [(punto.MOD_CONTROL, punto.VK_INSERT)], "convert-before-caret"),
                      (3, [(punto.MOD_CONTROL | punto.MOD_ALT, punto.VK_F11)], "pause")]
        def register(ident, combos, purpose):
            if ident == 2:
                raise OSError(1409, "already in use")
            return combos[0]
        with patch.object(punto, "_register_hotkey_with_fallback", side_effect=register):
            result = punto._register_available_hotkeys(candidates)
        self.assertEqual(result, [1, 3])

    def test_all_hotkeys_busy_still_allows_tray_and_auto_layout(self):
        candidates = [(1, [(0, punto.VK_INSERT)], "convert-selected")]
        with patch.object(punto, "_register_hotkey_with_fallback", side_effect=OSError(1409, "busy")):
            result = punto._register_available_hotkeys(candidates)
        self.assertEqual(result, [])

    def test_watchdog_recovers_dead_worker_and_idle_scheduler(self):
        worker = Mock()
        worker._thread = Mock()
        worker._thread.is_alive.return_value = False
        worker.current_job.return_value = ("", 0.0)
        idle = Mock()
        idle._thread = Mock()
        idle._thread.is_alive.return_value = False
        with patch.object(punto, "_worker", worker), patch.object(punto, "_idle", idle):
            punto._watchdog_check_worker()
        worker.start.assert_called_once_with()
        idle.start.assert_called_once_with()

    def test_watchdog_preserves_healthy_threads(self):
        worker = Mock()
        worker._thread = Mock()
        worker._thread.is_alive.return_value = True
        worker.current_job.return_value = ("", 0.0)
        idle = Mock()
        idle._thread = Mock()
        idle._thread.is_alive.return_value = True
        with patch.object(punto, "_worker", worker), patch.object(punto, "_idle", idle):
            punto._watchdog_check_worker()
        worker.start.assert_not_called()
        idle.start.assert_not_called()

    def test_resuming_clears_pause_and_single_window_restriction(self):
        with patch.object(punto, "_is_paused", True), \
             patch.object(punto, "_active_window_only", True), \
             patch.object(punto, "_allowed_hwnd", 123), \
             patch.object(punto, "_idle") as idle, \
             patch.object(punto, "_post_tray_refresh"), \
             patch.object(punto, "_invalidate_fg_cache"):
            punto._resume_in_all_windows()
            self.assertFalse(punto._is_paused)
            self.assertFalse(punto._active_window_only)
            self.assertEqual(punto._allowed_hwnd, 0)
            idle.cancel.assert_called_once()

    def test_diagnostic_exposes_paused_and_disabled_app_without_user_text(self):
        worker = Mock()
        worker._thread = Mock()
        worker._thread.is_alive.return_value = True
        idle = Mock()
        idle._thread = Mock()
        idle._thread.is_alive.return_value = True
        with patch.object(punto, "_worker", worker), patch.object(punto, "_idle", idle), \
             patch.object(punto, "_disabled_apps", frozenset({"notepad.exe"})), \
             patch.object(punto, "_settings", punto.Settings(auto_layout_correction=True)), \
             patch.object(punto, "_layout_words", frozenset({"привет"})), \
             patch.object(punto, "_is_paused", True):
            report = punto._runtime_diagnostics("notepad.exe")
        self.assertIn("ПАУЗА", report)
        self.assertIn("Исключено: ДА", report)
        self.assertIn("Исправление раскладки: включено", report)
        self.assertIn("Слов в словаре: 1", report)

    def test_conflicting_ctrl_insert_reports_real_fallback(self):
        primary = (punto.MOD_CONTROL, punto.VK_INSERT)
        fallback = (punto.MOD_ALT, punto.VK_INSERT)
        definitions = [(punto._HK_CONVERT_BEFORE_CARET,
                        [primary, fallback], "convert-before-caret")]
        with patch.object(punto, "_register_hotkey_with_fallback", return_value=fallback):
            self.assertEqual(punto._register_available_hotkeys(definitions),
                             [punto._HK_CONVERT_BEFORE_CARET])
        report = "\\n".join(punto._hotkey_diagnostic_lines())
        self.assertIn("Ctrl+Ins", report)
        self.assertIn("Alt+Ins", report)
        self.assertIn("запасное сочетание", report)

    def test_preferred_key_recovered_when_windows_releases_it(self):
        logical = punto._HK_CONVERT_BEFORE_CARET
        primary = (punto.MOD_CONTROL, punto.VK_INSERT)
        fallback = (punto.MOD_ALT, punto.VK_INSERT)
        bindings = {logical: (logical, fallback)}
        with patch.object(punto, "_desired_hotkeys", {logical: primary}), \
             patch.object(punto, "_active_hotkeys", bindings), \
             patch.object(punto, "user32") as api:
            api.RegisterHotKey.return_value = 1
            api.UnregisterHotKey.return_value = 1
            punto._retry_preferred_hotkeys()
            new_id, new_combo = bindings[logical]
        self.assertEqual(new_id, punto._HOTKEY_RECOVERY_ID_OFFSET + logical)
        self.assertEqual(new_combo, primary)
        api.RegisterHotKey.assert_called_once_with(
            None, new_id, punto.MOD_CONTROL | punto.MOD_NOREPEAT, punto.VK_INSERT)
        api.UnregisterHotKey.assert_called_once_with(None, logical)

    def test_failed_preferred_retry_keeps_fallback_registered(self):
        logical = punto._HK_CONVERT_BEFORE_CARET
        primary = (punto.MOD_CONTROL, punto.VK_INSERT)
        fallback = (punto.MOD_ALT, punto.VK_INSERT)
        bindings = {logical: (logical, fallback)}
        with patch.object(punto, "_desired_hotkeys", {logical: primary}), \
             patch.object(punto, "_active_hotkeys", bindings), \
             patch.object(punto, "user32") as api:
            api.RegisterHotKey.return_value = 0
            punto._retry_preferred_hotkeys()
        self.assertEqual(bindings[logical], (logical, fallback))
        api.UnregisterHotKey.assert_not_called()

    def test_recovery_does_not_reregister_preferred_hotkey(self):
        logical = punto._HK_CONVERT_BEFORE_CARET
        primary = (punto.MOD_CONTROL, punto.VK_INSERT)
        with patch.object(punto, "_desired_hotkeys", {logical: primary}), \
             patch.object(punto, "_active_hotkeys", {logical: (102, primary)}), \
             patch.object(punto, "user32") as api:
            punto._retry_preferred_hotkeys()
        api.RegisterHotKey.assert_not_called()
        api.UnregisterHotKey.assert_not_called()

    def test_unregister_failure_releases_temporary_and_keeps_fallback(self):
        logical = punto._HK_CONVERT_BEFORE_CARET
        primary = (punto.MOD_CONTROL, punto.VK_INSERT)
        fallback = (punto.MOD_ALT, punto.VK_INSERT)
        bindings = {logical: (logical, fallback)}
        with patch.object(punto, "_desired_hotkeys", {logical: primary}), \
             patch.object(punto, "_active_hotkeys", bindings), \
             patch.object(punto, "user32") as api:
            api.RegisterHotKey.return_value = 1
            api.UnregisterHotKey.side_effect = [0, 1]
            punto._retry_preferred_hotkeys()
        self.assertEqual(bindings[logical], (logical, fallback))
        self.assertEqual(api.UnregisterHotKey.call_count, 2)

    def test_language_indicator_default_shortcuts_do_not_overlap(self):
        forbidden = {(punto.MOD_CONTROL | punto.MOD_ALT, ord("Q")),
                     (punto.MOD_CONTROL | punto.MOD_ALT, ord("R"))}
        for _, candidates, _ in punto._hotkey_definitions(punto.Hotkeys()):
            self.assertTrue(forbidden.isdisjoint(candidates))


if __name__ == "__main__":
    unittest.main()
