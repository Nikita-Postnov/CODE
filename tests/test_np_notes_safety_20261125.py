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


if __name__ == "__main__":
    unittest.main()
