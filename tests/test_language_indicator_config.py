from __future__ import annotations

import ast
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import unittest
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "Other_dev" / "Language_indicator.py"
CODE = SOURCE.read_text(encoding="utf-8")


def load_pure_config():
    """Run pure settings in isolation: no Windows API or Qt GUI required."""
    tree = ast.parse(CODE, filename=str(SOURCE))
    selected = {"AppConfig", "_read_config_dict", "_parse_config", "_save_config", "_load_config"}
    assignments = {"_BOOL_SETTINGS", "_COLOR_SETTINGS", "_INT_RANGES", "_FLOAT_RANGES"}
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in selected:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in assignments for t in node.targets
        ):
            nodes.append(node)
    ns = {
        "__name__": __name__, "dataclass": dataclass, "fields": fields,
        "replace": replace, "asdict": asdict, "Path": Path, "json": json,
        "os": os, "re": re, "shutil": shutil, "logging": logging,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), ns)
    return ns


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load_pure_config()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        folder = Path(self.temp.name)
        self.cfg["DATA_DIR"] = folder
        self.cfg["CONFIG_FILE"] = folder / "language_indicator_settings.json"

    def test_defaults(self):
        config = self.cfg["AppConfig"]()
        self.assertTrue(config.popup_enabled)
        self.assertFalse(config.popup_on_focus_change)
        self.assertTrue(config.indicators_visible)
        self.assertEqual(config.placement_mode, "taskbar")
        self.assertLessEqual(config.update_interval_ms, 100)

    def test_roundtrip_portable_json(self):
        config = replace(self.cfg["AppConfig"](), popup_duration_ms=1200,
                         placement_mode="corners", popup_enabled=False,
                         en_text_color="#123ABC", small_width=64,
                         small_height=32)
        self.assertTrue(self.cfg["_save_config"](config))
        self.assertEqual(self.cfg["_load_config"](), config)

    def test_corrupt_primary_restores_backup(self):
        base = replace(self.cfg["AppConfig"](), popup_duration_ms=400)
        newer = replace(base, popup_duration_ms=1200)
        self.assertTrue(self.cfg["_save_config"](base))
        self.assertTrue(self.cfg["_save_config"](newer))
        self.cfg["CONFIG_FILE"].write_text("{invalid JSON", encoding="utf-8")
        self.assertEqual(self.cfg["_load_config"](), base)

    def test_invalid_settings_ignored(self):
        conf = self.cfg["_parse_config"]({
            "small_width": True, "popup_duration_ms": -100,
            "normal_alpha": 1000, "en_text_color": "bad",
            "popup_enabled": "false", "placement_mode": "../../something",
            "unknown_key": "x", "popup_on_focus_change": True,
        })
        default = self.cfg["AppConfig"]()
        for key in ("small_width", "popup_duration_ms", "normal_alpha",
                    "en_text_color", "popup_enabled", "placement_mode"):
            self.assertEqual(getattr(conf, key), getattr(default, key))
        self.assertTrue(conf.popup_on_focus_change)

    def test_bom_settings_load(self):
        self.cfg["CONFIG_FILE"].write_text(
            "\ufeff" + json.dumps({"popup_enabled": False}), encoding="utf-8")
        self.assertFalse(self.cfg["_load_config"]().popup_enabled)

    def test_invalid_primary_not_saved_as_backup(self):
        path = self.cfg["CONFIG_FILE"]
        path.write_text("invalid json", encoding="utf-8")
        self.assertTrue(self.cfg["_save_config"](self.cfg["AppConfig"]()))
        self.assertFalse(path.with_suffix(".json.bak").exists())


class IntegrationSourceTests(unittest.TestCase):
    def test_valid_python(self):
        compile(CODE, str(SOURCE), "exec")

    def test_choice_process_owner(self):
        self.assertIn('if os.environ.get("CHOICE_PID"):', CODE)
        self.assertIn("Restart inside Choice: reload settings and recreate widgets in place", CODE)

    def test_layout_poll_and_geometry_split(self):
        self.assertIn('get_active_keyboard_lang(hwnd)', CODE)
        self.assertIn('self.should_force_topmost_now()', CODE)
        self.assertIn('if relayout:', CODE)

    def test_no_popup_on_focus_change_by_default(self):
        self.assertIn('and (CONFIG.popup_on_focus_change or not focus_changed)', CODE)

    def test_tray_settings(self):
        for item in ("Размер маленького индикатора", "Размер большого уведомления",
                     "Длительность большого уведомления", "Расположение индикатора",
                     "Перезагрузить настройки из файла", "Восстановить настройки по умолчанию",
                     "choose_color", "change_settings"):
            self.assertIn(item, CODE)

    @unittest.skipUnless(sys.platform == "win32", "Windows tray test")
    def test_windows_tray_menu_constructs(self):
        import importlib.util
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        spec = importlib.util.spec_from_file_location("np_language_indicator_menu", SOURCE)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(module)
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        self.addCleanup(app.quit)
        controller = module.LanguageIndicatorApp.__new__(module.LanguageIndicatorApp)
        menu = controller.create_tray_menu()
        self.assertIn("Настройки", [action.text() for action in menu.actions()])
        settings = next(action.menu() for action in menu.actions()
                        if action.text() == "Настройки")
        self.assertIsNotNone(settings)
        self.assertGreaterEqual(len(settings.actions()), 8)
        self.assertTrue(any(action.isCheckable() and action.isChecked()
                            for action in settings.actions()))

    @unittest.skipUnless(sys.platform == "win32", "Windows import smoke test")
    def test_windows_module_import(self):
        import importlib.util
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        spec = importlib.util.spec_from_file_location("np_language_indicator_smoke", SOURCE)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(module)
        self.assertIsNotNone(module.LanguageIndicatorApp)


if __name__ == "__main__":
    unittest.main()
