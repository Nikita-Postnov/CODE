"""Регрессионные тесты заметок без зависимости от Qt и пользовательского Data.

Запуск: python -m unittest discover -s tests -p 'test_np_notes_safety_20261125.py'
"""
import ast
import datetime as dt
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "Other_dev" / "noteapp"


def isolated_functions(module_path, names, assignments=()):
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    selected = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
        or isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in assignments
            for target in node.targets
        )
    ]
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "datetime": dt.datetime,
        "timedelta": dt.timedelta,
        "monthrange": __import__("calendar").monthrange,
    }
    exec(compile(module, str(module_path), "exec"), namespace)
    return namespace


class ReminderSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = isolated_functions(
            ROOT / "app" / "reminders.py",
            {"normalize_reminder_repeat", "parse_reminder_datetime",
             "reminder_now_for_due", "next_reminder_datetime"},
            {"REPEAT_CODES"},
        )

    def test_timezone_aware_now_and_due_can_be_compared(self):
        parse = self.mod["parse_reminder_datetime"]
        clock = self.mod["reminder_now_for_due"]
        due = parse("2026-11-25T05:00:00Z")
        now = dt.datetime(2026, 11, 25, 8, 0, tzinfo=dt.timezone(dt.timedelta(hours=3)))
        self.assertEqual(clock(due, now), due)
        self.assertLessEqual(due, clock(due, now))

    def test_naive_legacy_date_preserves_naive_clock(self):
        clock = self.mod["reminder_now_for_due"]
        due = dt.datetime(2026, 11, 25, 5)
        now = dt.datetime(2026, 11, 25, 6)
        self.assertIsNone(clock(due, now).tzinfo)
        self.assertEqual(clock(due, now), now)

    def test_hourly_rolls_to_first_future_occurrence(self):
        next_due = self.mod["next_reminder_datetime"]
        due = dt.datetime(2026, 11, 25, 5, tzinfo=dt.timezone.utc)
        now = dt.datetime(2026, 11, 25, 9, 20, tzinfo=dt.timezone.utc)
        self.assertEqual(next_due(due, now, "каждый час"), dt.datetime(
            2026, 11, 25, 10, tzinfo=dt.timezone.utc))

    def test_weekends_skip_weekdays(self):
        next_due = self.mod["next_reminder_datetime"]
        due = dt.datetime(2026, 11, 23, 9)  # Monday
        now = dt.datetime(2026, 11, 25, 10)
        result = next_due(due, now, "по выходным")
        self.assertEqual(result.date(), dt.date(2026, 11, 28))
        self.assertEqual(result.hour, 9)

    def test_old_repeat_code_is_still_supported(self):
        normalize = self.mod["normalize_reminder_repeat"]
        self.assertEqual(normalize("monthly"), "monthly")
        self.assertEqual(normalize("Каждый месяц"), "monthly")

    def test_user_text_escaped_in_reminder_popup(self):
        text = (ROOT / "app" / "reminders.py").read_text(encoding="utf-8")
        self.assertIn("escape_html(note.title", text)


class DataCompatibilityTests(unittest.TestCase):
    def test_no_data_migration_in_changed_modules(self):
        for name in ("autosave.py", "search.py", "reminders.py"):
            text = (ROOT / "app" / name).read_text(encoding="utf-8")
            ast.parse(text)
            self.assertNotIn("shutil.rmtree(", text)

    def test_autosave_keeps_dirty_flag_and_schedules_retry(self):
        text = (ROOT / "app" / "autosave.py").read_text(encoding="utf-8")
        self.assertIn("self._set_unsaved(True)", text)
        self.assertIn("self._autosave_timer.start(5000)", text)

    def test_search_mode_has_compatibility_default(self):
        text = (ROOT / "app" / "search.py").read_text(encoding="utf-8")
        self.assertIn('"Везде"', text)
        self.assertIn("if selected in modes:", text)



class DesktopWidgetTests(unittest.TestCase):
    def test_copy_widget_note_without_decoration(self):
        source = (ROOT / "widgets" / "desktop_notes.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(n for n in tree.body
                   if isinstance(n, ast.ClassDef) and n.name == "DesktopNotesWidget")
        method = next(n for n in cls.body
                      if isinstance(n, ast.FunctionDef) and n.name == "copy_note_text")
        # Извлекаем только метод: тест не требует Qt и не показывает GUI.
        module = ast.Module(body=[method], type_ignores=[])
        ast.fix_missing_locations(module)
        class Clipboard:
            value = None
            def setText(self, value):
                self.value = value
        clipboard = Clipboard()
        class QApplication:
            @staticmethod
            def clipboard():
                return clipboard
        namespace = {"QApplication": QApplication, "QListWidgetItem": object}
        exec(compile(module, "<widget-copy>", "exec"), namespace)
        copy_text = namespace["copy_note_text"]
        class Item:
            def __init__(self, text, src):
                self.value, self.src = text, src
            def text(self):
                return self.value
            def data(self, role):
                return self.src
        class Qt:
            UserRole = 1
        namespace["Qt"] = Qt
        copy_text(None, Item("📝 Important", "app"))
        self.assertEqual(clipboard.value, "Important")
        copy_text(None, Item("📌 Personal", "widget"))
        self.assertEqual(clipboard.value, "Personal")


class DesktopWidgetSettingsTests(unittest.TestCase):
    def test_opacity_setting_is_clamped_and_saved(self):
        source = (ROOT / "widgets" / "desktop_notes.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(node for node in tree.body
                   if isinstance(node, ast.ClassDef) and node.name == "DesktopNotesWidget")
        method = next(node for node in cls.body
                      if isinstance(node, ast.FunctionDef) and node.name == "set_widget_opacity")
        module = ast.Module(body=[method], type_ignores=[])
        ast.fix_missing_locations(module)
        ns = {}
        exec(compile(module, "<opacity>", "exec"), ns)
        class Fake:
            def setWindowOpacity(self, value):
                self.opacity = value
            def _save_pos(self):
                self.saved = True
        obj = Fake()
        ns["set_widget_opacity"](obj, 0.1)
        self.assertEqual(obj.opacity, 0.6)
        ns["set_widget_opacity"](obj, 3.0)
        self.assertEqual(obj.opacity, 1.0)
        self.assertTrue(obj.saved)
        self.assertIn('s.setValue("opacity",', source)

    def test_topmost_setting_is_persisted_with_default_enabled(self):
        code = (ROOT / "widgets" / "desktop_notes.py").read_text(encoding="utf-8")
        self.assertIn('s.value("always_on_top", "true")', code)
        self.assertIn('s.setValue("always_on_top",', code)
        self.assertIn("topmost.toggled.connect(self.set_always_on_top)", code)


class ConfidentialClipboardTests(unittest.TestCase):
    def test_copy_secret_clears_only_if_clipboard_unchanged(self):
        source = (ROOT / "app" / "images.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(node for node in tree.body
                   if isinstance(node, ast.ClassDef) and node.name == "ImagesMixin")
        method = next(node for node in cls.body
                      if isinstance(node, ast.FunctionDef)
                      and node.name == "_clear_private_clipboard_if_unchanged")
        # The method is a staticmethod; no Qt import required for this test.
        module = ast.Module(body=[method], type_ignores=[])
        ast.fix_missing_locations(module)
        class Clipboard:
            value = "secret"
            cleared = False
            def text(self):
                return self.value
            def clear(self):
                self.cleared = True
                self.value = ""
        clipboard = Clipboard()
        class QApplication:
            @staticmethod
            def clipboard():
                return clipboard
        namespace = {"QApplication": QApplication}
        exec(compile(module, "<secure-clipboard>", "exec"), namespace)
        operation = namespace["_clear_private_clipboard_if_unchanged"]
        operation("something else")
        self.assertFalse(clipboard.cleared)
        operation("secret")
        self.assertTrue(clipboard.cleared)
        self.assertIn("QTimer.singleShot(", source)
        self.assertIn("30000,", source)


class EditorChecklistTests(unittest.TestCase):
    def test_checklist_toggle_uses_edit_block_and_is_exposed_in_ui(self):
        editor = (ROOT / "app" / "editor.py").read_text(encoding="utf-8")
        main = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
        tree = ast.parse(editor)
        cls = next(node for node in tree.body
                   if isinstance(node, ast.ClassDef) and node.name == "EditorMixin")
        toggle = next(node for node in cls.body
                      if isinstance(node, ast.FunctionDef)
                      and node.name == "toggle_checkbox_at_cursor")
        method = ast.get_source_segment(editor, toggle)
        self.assertIn("beginEditBlock()", method)
        self.assertIn("endEditBlock()", method)
        self.assertIn('text.startswith("☐ ")', method)
        self.assertIn('text.startswith("☑ ")', method)
        self.assertIn('QKeySequence("Ctrl+Shift+K")', main)
        self.assertIn("self.toggle_checkbox_at_cursor)", main)


class ExitSafetyTests(unittest.TestCase):
    def test_failed_save_prevents_process_exit(self):
        source = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(n for n in tree.body
                   if isinstance(n, ast.ClassDef) and n.name == "NotesApp")
        method = next(n for n in cls.body
                      if isinstance(n, ast.FunctionDef) and n.name == "exit_app")
        module = ast.Module(body=[method], type_ignores=[])
        ast.fix_missing_locations(module)
        class QMessageBox:
            calls = 0
            @classmethod
            def warning(cls, *args):
                cls.calls += 1
        class Logging:
            @staticmethod
            def exception(*args):
                pass
        class QApplication:
            @staticmethod
            def instance():
                raise AssertionError("app.quit must not be reached")
        namespace = {"QMessageBox": QMessageBox, "logging": Logging,
                     "QApplication": QApplication}
        exec(compile(module, "<exit-safety>", "exec"), namespace)
        class Fake:
            def __init__(self):
                self.dirty = []
            def save_note_quiet(self, **kwargs):
                raise OSError("disk full")
            def save_all_notes_to_disk(self):
                raise AssertionError("should not be reached")
            def _set_unsaved(self, value):
                self.dirty.append(value)
        fake = Fake()
        namespace["exit_app"](fake)
        self.assertEqual(fake.dirty, [True])
        self.assertEqual(QMessageBox.calls, 1)

    def test_search_keyboard_shortcut_configured(self):
        source = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn('QKeySequence("Ctrl+Shift+F")', source)
        self.assertIn("search_focus_shortcut.activated.connect(self.search_bar.setFocus)", source)


class NotesOrganizationTests(unittest.TestCase):
    def test_recent_view_is_limited_to_15_and_read_only(self):
        source = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(node for node in tree.body
                   if isinstance(node, ast.ClassDef) and node.name == "NotesApp")
        method = next(node for node in cls.body
                      if isinstance(node, ast.FunctionDef) and node.name == "show_recent_notes")
        method_source = ast.get_source_segment(source, method)
        self.assertIn("[:15]", method_source)
        self.assertIn("reverse=True", method_source)
        self.assertIn("self._timestamp_sort_key(note)", method_source)
        self.assertNotIn("save_note_to_file(", method_source)
        self.assertIn("recent_button.clicked.connect(self.show_recent_notes)", source)

    def test_untagged_view_is_non_destructive(self):
        source = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(node for node in tree.body
                   if isinstance(node, ast.ClassDef) and node.name == "NotesApp")
        method = next(node for node in cls.body
                      if isinstance(node, ast.FunctionDef)
                      and node.name == "show_untagged_notes")
        calls = [n.func.attr for n in ast.walk(method)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        self.assertNotIn("save_note_to_file", calls)
        self.assertNotIn("unlink", calls)
        self.assertNotIn("remove", calls)
        self.assertIn("if note.tags:", ast.get_source_segment(source, method))
        self.assertIn('self.search_mode_combo.addItems(["Заголовок", "Содержимое", "Напоминание", "Везде"])', source)


class SearchPerformanceTests(unittest.TestCase):
    def test_global_search_short_circuits_metadata(self):
        code = (ROOT / "app" / "search.py").read_text(encoding="utf-8")
        self.assertIn('mode == "Везде" and (title_match or reminder_match', code)
        self.assertIn("return matches_tag_filter", code)




if __name__ == "__main__":
    unittest.main()
