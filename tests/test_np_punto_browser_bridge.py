"""Проверка маршрутизации Ctrl+Ins из Windows в браузерное расширение."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / "Other_dev" / "punto_like_work_safe.py"
SPEC = importlib.util.spec_from_file_location("np_punto_browser_bridge", SOURCE)
punto = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = punto
SPEC.loader.exec_module(punto)


class BrowserBridgeTests(unittest.TestCase):
    def test_bridge_disabled_by_default_and_preserved_in_settings(self):
        self.assertFalse(punto.Settings().browser_extension_hotkey_bridge)
        data = punto._settings_to_dict(punto.Settings(browser_extension_hotkey_bridge=True))
        self.assertTrue(data["browser_extension_hotkey_bridge"])
        parsed, warnings = punto._settings_from_dict(data)
        self.assertFalse(warnings)
        self.assertTrue(parsed.browser_extension_hotkey_bridge)

    def test_invalid_bridge_value_falls_back_to_disabled(self):
        parsed, warnings = punto._settings_from_dict(
            {"browser_extension_hotkey_bridge": "true"}
        )
        self.assertFalse(parsed.browser_extension_hotkey_bridge)
        self.assertTrue(any("browser_extension_hotkey_bridge" in item for item in warnings))

    def check_route(self, exe, enabled, extension_expected):
        api = Mock()
        api.GetForegroundWindow.return_value = 42
        with patch.object(punto, "user32", api), \
             patch.object(punto, "_settings", punto.Settings(
                 browser_extension_hotkey_bridge=enabled,
             )), \
             patch.object(punto, "_get_exe_name_for_hwnd", return_value=exe) as lookup, \
             patch.object(punto, "_send_browser_extension_shortcut") as send, \
             patch.object(punto, "convert_before_caret_text") as legacy:
            punto._convert_before_caret_with_browser_bridge(punto.Timings())
        if extension_expected:
            lookup.assert_called_once_with(42)
            send.assert_called_once()
            legacy.assert_not_called()
        else:
            send.assert_not_called()
            legacy.assert_called_once()

    def test_enabled_extension_bridge_targets_chromium(self):
        for exe in ("chrome.exe", "msedge.exe", "brave.exe", "vivaldi.exe", "opera.exe"):
            with self.subTest(exe=exe):
                self.check_route(exe, enabled=True, extension_expected=True)

    def test_unrelated_applications_continue_native_conversion(self):
        for exe in ("notepad.exe", "code.exe", "powershell.exe", "firefox.exe"):
            with self.subTest(exe=exe):
                self.check_route(exe, enabled=True, extension_expected=False)

    def test_disabled_bridge_preserves_existing_browser_clipboard_behavior(self):
        self.check_route("chrome.exe", enabled=False, extension_expected=False)

    def test_synthetic_shortcut_releases_all_modifiers_even_on_failure(self):
        calls = []
        def record(inputs):
            calls.append(inputs)
        with patch.object(punto, "_send_input", side_effect=record), \
             patch.object(punto, "_physical_modifier_release_events", return_value=[]), \
             patch.object(punto.time, "sleep"):
            punto._send_browser_extension_shortcut(punto.Timings())
        self.assertEqual(len(calls), 3)
        pressed = [event.ki.wVk for event in calls[0]]
        self.assertEqual(pressed, [punto.VK_CONTROL, punto.VK_MENU, punto.VK_SHIFT])
        self.assertEqual([event.ki.wVk for event in calls[1]], [punto.VK_F8, punto.VK_F8])
        self.assertEqual(
            [event.ki.wVk for event in calls[2]],
            [punto.VK_SHIFT, punto.VK_MENU, punto.VK_CONTROL],
        )


if __name__ == "__main__":
    unittest.main()
