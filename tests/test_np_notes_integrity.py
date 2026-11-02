"""Регрессии сохранности заметок, повторений и контроля загрузки плагинов."""
import ast
import json
import os
import pathlib
import shutil
import tempfile
import time
import types
import unittest
import uuid
from calendar import monthrange
from datetime import datetime, timedelta
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / "Other_dev" / "noteapp" / "app"


def node_from(path, name, owner=None):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    body = tree.body
    if owner:
        body = next(x.body for x in body if isinstance(x, ast.ClassDef) and x.name == owner)
    return next(x for x in body if isinstance(x, ast.FunctionDef) and x.name == name)


def compile_methods(path, names, owner, namespace):
    nodes = [node_from(path, name, owner) for name in names]
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                 "<note-tests>", "exec"), namespace)
    return namespace


class TestNotesStorage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.cfg = types.SimpleNamespace()
        namespace = {
            "Path": pathlib.Path, "json": json, "os": os, "time": time, "uuid": uuid,
            "shutil": shutil, "logging": __import__("logging"), "NotePersistenceMixin": self.cfg,
            "qt_path": str,
        }
        funcs = compile_methods(APP / "persistence.py", [
            "_atomic_write_json_static", "_make_backup_if_exists", "_rotate_backups",
            "_recover_note_payload", "_save_payload_to_folder",
        ], "NotePersistenceMixin", namespace)
        for name in ("_atomic_write_json_static", "_make_backup_if_exists", "_rotate_backups",
                     "_recover_note_payload", "_save_payload_to_folder"):
            fn = funcs[name]
            setattr(self.cfg, name,
                    staticmethod(fn) if name in ("_atomic_write_json_static", "_recover_note_payload") else fn)
        self.worker = types.SimpleNamespace()
        self.worker._make_backup_if_exists = types.MethodType(funcs["_make_backup_if_exists"], self.worker)
        self.worker._rotate_backups = types.MethodType(funcs["_rotate_backups"], self.worker)
        self.worker._atomic_write_json = funcs["_atomic_write_json_static"]
        self.worker._as_path = pathlib.Path

    def test_unique_backups_even_when_saved_in_same_second(self):
        folder = self.root / "a"
        folder.mkdir()
        file = folder / "note.json"
        file.write_text('{"revision":1}', encoding="utf-8")
        for _ in range(3):
            self.worker._make_backup_if_exists(file)
        backups = list(folder.glob("note_backup_*.json"))
        self.assertEqual(len(backups), 3)

    def test_unchanged_note_does_not_replace_or_generate_backup(self):
        path = self.root / "b"
        payload = {"title": "important", "content": "abc"}
        save = types.MethodType(
            compile_methods(APP / "persistence.py", ["_save_payload_to_folder"],
                            "NotePersistenceMixin", {"Path": pathlib.Path, "json": json})["_save_payload_to_folder"], self.worker)
        self.assertEqual(save(path, payload), path / "note.json")
        before = (path / "note.json").stat().st_mtime_ns
        self.assertEqual(save(path, payload), path / "note.json")
        self.assertEqual((path / "note.json").stat().st_mtime_ns, before)
        self.assertEqual(list(path.glob("note_backup_*.json")), [])
        save(path, {**payload, "content": "new"})
        self.assertEqual(len(list(path.glob("note_backup_*.json"))), 1)

    def test_corrupt_main_note_falls_back_to_backup(self):
        folder = self.root / "c"
        folder.mkdir()
        (folder / "note.json").write_text("{broken")
        (folder / "note_backup_123.json").write_text(json.dumps({"title": "restored"}))
        data = self.cfg._recover_note_payload(folder)
        self.assertEqual(data["title"], "restored")
        self.assertEqual((folder / "note.json").read_text(), "{broken")


class TestReminders(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        namespace = {"datetime": datetime, "timedelta": timedelta, "monthrange": monthrange}
        fns = ["normalize_reminder_repeat", "parse_reminder_datetime", "next_reminder_datetime"]
        nodes = [node_from(APP / "reminders.py", x) for x in fns]
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                     "<reminder-tests>", "exec"), namespace)
        cls.f = namespace
        cls.f["REPEAT_CODES"] = {
            "": "", "once": "", "однократно": "", "daily": "daily",
            "каждый день": "daily", "workdays": "workdays", "по будням": "workdays",
            "weekends": "weekends", "по выходным": "weekends",
            "weekly": "weekly", "каждую неделю": "weekly",
            "monthly": "monthly", "каждый месяц": "monthly",
            "hourly": "hourly", "minutely": "minutely"}

    def test_russian_recurrence_compatibility(self):
        f = self.f["normalize_reminder_repeat"]
        self.assertEqual(f("Каждый день"), "daily")
        self.assertEqual(f("По будням"), "workdays")
        self.assertEqual(f("Каждый месяц"), "monthly")

    def test_missed_recurrence_is_advanced_beyond_now(self):
        f = self.f["next_reminder_datetime"]
        self.assertEqual(f(datetime(2026, 11, 1, 10), datetime(2026, 11, 4, 12), "daily"),
                         datetime(2026, 11, 5, 10))
        self.assertEqual(f(datetime(2026, 10, 30, 9), datetime(2026, 11, 2, 8), "workdays"),
                         datetime(2026, 11, 2, 9))

    def test_month_end_and_leap_year(self):
        f = self.f["next_reminder_datetime"]
        self.assertEqual(f(datetime(2028, 1, 31, 9), datetime(2028, 2, 1), "monthly"),
                         datetime(2028, 2, 29, 9))

    def test_iso_legacy_dates(self):
        f = self.f["parse_reminder_datetime"]
        self.assertEqual(f("2026-11-02 09:30"), datetime(2026, 11, 2, 9, 30))
        self.assertEqual(f("2026-11-02T09:30:00"), datetime(2026, 11, 2, 9, 30))
        self.assertIsNone(f("incorrect"))


class TestGuardrails(unittest.TestCase):
    def test_plugin_modules_are_not_imported_until_enabled(self):
        code = ast.unparse(node_from(APP / "plugins.py", "load_plugins", "PluginsMixin"))
        self.assertIn("if not plugins_state.get(plugin_name, False):", code)
        self.assertLess(code.index("if not plugins_state.get(plugin_name, False):"),
                        code.index("spec_from_file_location"))

    def test_only_one_text_change_save_listener(self):
        source = (APP / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("self.text_edit.textChanged.connect(self._schedule_autosave)", source)
        self.assertNotIn("self.text_edit.textChanged.connect(self.on_text_changed_autosave)", source)
        self.assertNotIn("threading.Thread(\n                    target=_bg_save", source)

    def test_autosave_timer_uses_configured_delay(self):
        code = ast.unparse(node_from(APP / "autosave.py", "_schedule_autosave", "AutosaveMixin"))
        self.assertIn("self.autosave_timer.start(self._get_autosave_debounce_ms())", code)
        self.assertNotIn("self.autosave_timer.start(0)", code)


if __name__ == "__main__":
    unittest.main()
