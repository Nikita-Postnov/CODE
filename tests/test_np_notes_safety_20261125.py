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


class CloseWindowSafetyTests(unittest.TestCase):
    def test_failed_save_keeps_window_open_instead_of_hiding_in_tray(self):
        source = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(node for node in tree.body
                   if isinstance(node, ast.ClassDef) and node.name == "NotesApp")
        method = next(node for node in cls.body
                      if isinstance(node, ast.FunctionDef) and node.name == "closeEvent")
        module = ast.Module(body=[method], type_ignores=[])
        ast.fix_missing_locations(module)
        warnings = []
        class Box:
            @staticmethod
            def warning(*args):
                warnings.append(args)
        namespace = {
            "QCloseEvent": object,
            "QMessageBox": Box,
            "logging": type("Log", (), {"exception": staticmethod(lambda *a: None)}),
        }
        exec(compile(module, "<close-safety>", "exec"), namespace)
        class Event:
            ignored = False
            def ignore(self):
                self.ignored = True
        class Fake:
            hidden = False
            dirty = False
            def save_settings(self):
                pass
            def save_note_quiet(self, *, force):
                raise OSError("simulated disk full")
            def save_all_notes_to_disk(self):
                raise AssertionError("No second save after error")
            def _set_unsaved(self, flag):
                self.dirty = flag
            def hide(self):
                self.hidden = True
        owner = Fake()
        evt = Event()
        namespace["closeEvent"](owner, evt)
        self.assertTrue(evt.ignored)
        self.assertTrue(owner.dirty)
        self.assertFalse(owner.hidden)
        self.assertEqual(len(warnings), 1)

class FirstNoteDialogTests(unittest.TestCase):
    def test_creation_dialog_has_russian_action_buttons(self):
        source = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                   and n.name == "NotesApp")
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                      and n.name == "_prompt_new_note_title")
        body = ast.get_source_segment(source, method)
        self.assertIn('dialog.setOkButtonText("Создать")', body)
        self.assertIn('dialog.setCancelButtonText("Отмена")', body)


class QuietAutosaveHistoryTests(unittest.TestCase):
    def test_quiet_disk_flush_does_not_add_history(self):
        source = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                   and n.name == "NotesApp")
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                      and n.name == "save_note_quiet")
        text = ast.get_source_segment(source, method)
        self.assertNotIn("self.record_state_for_undo()", text)
        self.assertIn("self.save_note_to_file(self.current_note)", text)
        self.assertIn("self._set_unsaved(False)", text)
        self.assertIn("self._save_debouncer.setInterval(1400)", source)


class RenameSafetyTests(unittest.TestCase):
    def test_failed_folder_rename_restores_original_note_and_path(self):
        import os
        import tempfile
        from types import SimpleNamespace
        source = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                   and n.name == "NotesApp")
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                      and n.name == "rename_note")
        body = ast.Module(body=[method], type_ignores=[])
        ast.fix_missing_locations(body)
        class Dialog:
            def __init__(self, parent):
                pass
            def setWindowTitle(self, value):
                pass
            def setLabelText(self, value):
                pass
            def setTextValue(self, value):
                pass
            def findChild(self, kind):
                return None
            def exec(self):
                return True
            def textValue(self):
                return "new"
        class Box:
            warnings = []
            @classmethod
            def warning(cls, *args):
                cls.warnings.append(args)
        class Log:
            @staticmethod
            def exception(*args):
                pass
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "old-u").mkdir()
            namespace = {
                "QInputDialog": Dialog, "QLineEdit": object,
                "QMessageBox": Box, "logging": Log,
                "NOTES_DIR": root, "os": os, "Note": object,
                "safe_folder_name": lambda title, uuid, timestamp: title + "-" + uuid,
            }
            exec(compile(body, "<rename-safety>", "exec"), namespace)
            note = SimpleNamespace(title="old", uuid="u", timestamp="now")
            class Owner:
                notes = [note]
                updated = False
                def save_note_to_file(self, current):
                    raise OSError("Disk full after rename")
                def refresh_notes_list(self):
                    self.updated = True
            owner = Owner()
            namespace["rename_note"](owner, note)
            self.assertEqual(note.title, "old")
            self.assertTrue((root / "old-u").is_dir())
            self.assertFalse((root / "new-u").exists())
            self.assertFalse(owner.updated)
            self.assertEqual(len(Box.warnings), 1)

class AsyncPreloadSafetyTests(unittest.TestCase):
    def test_startup_snapshot_does_not_replace_newly_created_note(self):
        source = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                   and n.name == "NotesApp")
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                      and n.name == "_merge_preloaded_notes")
        namespace = {"Note": object}
        body = ast.Module(body=[method], type_ignores=[])
        ast.fix_missing_locations(body)
        exec(compile(body, "<startup-snapshot>", "exec"), namespace)
        merge = namespace["_merge_preloaded_notes"]
        class Note:
            def __init__(self, uuid, content):
                self.uuid, self.content = uuid, content
        stale = Note("same-uuid", "old disk snapshot")
        modified = Note("same-uuid", "new user edits")
        new = Note("created-during-load", "new first note")
        another = Note("unrelated", "previously on disk")
        output = merge([stale, another], [modified, new])
        mapped = {n.uuid: n for n in output}
        self.assertEqual(len(mapped), 3)
        self.assertIs(mapped["same-uuid"], modified)
        self.assertIs(mapped["created-during-load"], new)
        self.assertIs(mapped["unrelated"], another)

class EmptyFirstRunTests(unittest.TestCase):
    def test_initial_window_has_visible_create_note_action(self):
        source = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(node for node in tree.body
                   if isinstance(node, ast.ClassDef) and node.name == "NotesApp")
        init_ui = next(node for node in cls.body
                       if isinstance(node, ast.FunctionDef) and node.name == "init_ui")
        body = ast.get_source_segment(source, init_ui)
        self.assertIn('self.empty_notes_create_button.clicked.connect(self.new_note)', body)
        self.assertIn('self.resize(1080, 720)', body)
        self.assertIn('editor_layout_combined.addWidget(self.empty_notes_page, 1)', body)

    def test_first_note_reveals_editor_after_welcome(self):
        source = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(node for node in tree.body
                   if isinstance(node, ast.ClassDef) and node.name == "NotesApp")
        creation = next(node for node in cls.body
                        if isinstance(node, ast.FunctionDef) and node.name == "new_note")
        body = ast.get_source_segment(source, creation)
        self.assertIn("self.show_note_with_attachments(note)\n            self._update_editor_visibility()", body)

    def test_crash_snapshot_is_wired_to_editor_signal(self):
        source = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(node for node in tree.body
                   if isinstance(node, ast.ClassDef) and node.name == "NotesApp")
        method = next(node for node in cls.body
                      if isinstance(node, ast.FunctionDef) and node.name == "init_ui")
        body = ast.get_source_segment(source, method)
        self.assertIn("self.text_edit.textChanged.connect(self._schedule_recovery_snapshot)", body)

    def test_editor_visibility_tracks_empty_page(self):
        source = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(node for node in tree.body
                   if isinstance(node, ast.ClassDef) and node.name == "NotesApp")
        update = next(node for node in cls.body if isinstance(node, ast.FunctionDef)
                      and node.name == "_update_editor_visibility")
        method = ast.get_source_segment(source, update)
        self.assertIn('self.empty_notes_page.setVisible(not has)', method)
        apply = next(node for node in cls.body if isinstance(node, ast.FunctionDef)
                     and node.name == "_apply_preloaded_notes")
        self.assertIn("self._update_editor_visibility()", ast.get_source_segment(source, apply))


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
