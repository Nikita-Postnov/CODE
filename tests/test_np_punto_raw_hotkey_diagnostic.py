"""Независимая диагностика физического Ctrl+Ins/F9 и WM_HOTKEY."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[1] / "Other_dev" / "punto_like_work_safe.py"
SPEC = importlib.util.spec_from_file_location("np_punto_raw_hotkeys", SOURCE)
punto = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = punto
SPEC.loader.exec_module(punto)


class RawHotkeyDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        punto._raw_hotkey_counts.update({punto.VK_INSERT: 0, punto.VK_F9: 0})
        punto._raw_hotkey_pressed.clear()
        self.addCleanup(punto._raw_hotkey_pressed.clear)

    def hit(self, key, ctrl=True):
        with patch.object(punto, "_is_any_vk_pressed", return_value=ctrl):
            punto._diagnose_raw_hotkey(key, True, False)

    def release(self, key):
        punto._diagnose_raw_hotkey(key, False, True)

    def test_detects_actual_ctrl_insert_even_when_wm_hotkey_count_zero(self):
        self.hit(punto.VK_INSERT)
        self.assertEqual(punto._raw_hotkey_counts[punto.VK_INSERT], 1)
        self.assertEqual(punto._hotkey_hit_counts.get(punto._HK_CONVERT_BEFORE_CARET, 0), 0)

    def test_detects_ctrl_f9_and_does_not_record_plain_f9(self):
        self.hit(punto.VK_F9, ctrl=False)
        self.release(punto.VK_F9)
        self.hit(punto.VK_F9, ctrl=True)
        self.assertEqual(punto._raw_hotkey_counts[punto.VK_F9], 1)

    def test_auto_repeat_does_not_count_as_separate_keypress(self):
        self.hit(punto.VK_INSERT)
        self.hit(punto.VK_INSERT)
        self.release(punto.VK_INSERT)
        self.hit(punto.VK_INSERT)
        self.assertEqual(punto._raw_hotkey_counts[punto.VK_INSERT], 2)

    def test_other_keys_are_not_logged(self):
        self.hit(ord("A"))
        self.assertEqual(sum(punto._raw_hotkey_counts.values()), 0)

    def test_paused_and_excluded_applications_still_have_independent_raw_counter(self):
        fake_keyboard = Mock(vkCode=punto.VK_INSERT, dwExtraInfo=0)
        fake_ptr = Mock()
        fake_ptr.contents = fake_keyboard
        fake_cast = Mock(return_value=fake_ptr)
        with patch.object(punto.ctypes, "cast", fake_cast), \
             patch.object(punto, "_is_any_vk_pressed", return_value=True), \
             patch.object(punto, "_is_paused", True), \
             patch.object(punto, "_foreground_info") as fg:
            punto._handle_keyboard_event(punto.WM_KEYDOWN, 12345)
        self.assertEqual(punto._raw_hotkey_counts[punto.VK_INSERT], 1)
        fg.assert_not_called()

    def test_diagnostics_contains_raw_and_delivered_counters(self):
        with patch.object(punto, "_desired_hotkeys", {
            punto._HK_CONVERT_BEFORE_CARET: (punto.MOD_CONTROL, punto.VK_INSERT),
        }), patch.object(punto, "_active_hotkeys", {
            punto._HK_CONVERT_BEFORE_CARET: (
                punto._HK_CONVERT_BEFORE_CARET, (punto.MOD_CONTROL, punto.VK_INSERT)
            ),
        }), patch.object(punto, "_hotkey_names", {
            punto._HK_CONVERT_BEFORE_CARET: "convert-before-caret",
        }), patch.object(punto, "_hotkey_hit_counts", {
            punto._HK_CONVERT_BEFORE_CARET: 1,
        }):
            punto._raw_hotkey_counts[punto.VK_INSERT] = 2
            report = "\n".join(punto._hotkey_diagnostic_lines())
            self.assertIn("срабатываний 1", report)
            self.assertIn("Ctrl+Ins=2", report)
            self.assertIn("Ctrl+F9=0", report)

    def test_keyup_resets_pressed_state(self):
        self.hit(punto.VK_INSERT)
        self.release(punto.VK_INSERT)
        self.assertNotIn(punto.VK_INSERT, punto._raw_hotkey_pressed)


if __name__ == "__main__":
    unittest.main()
