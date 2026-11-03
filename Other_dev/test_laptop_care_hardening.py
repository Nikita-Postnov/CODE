"""Регрессии LaptopCare: питание, снижение фоновой нагрузки, сохранение настроек."""
import ast
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import threading
import types
import unittest
import uuid
from unittest.mock import Mock, patch


SOURCE = Path(__file__).with_name("laptop_care.py")
TREE = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"
MODE = "00000000-0000-0000-0000-000000000000"


def isolated_function(name, *, owner=None, scope=None):
    body = TREE.body
    if owner is not None:
        cls = next(
            n for n in TREE.body
            if isinstance(n, ast.ClassDef) and n.name == owner
        )
        body = cls.body
    fn = next(
        n for n in body
        if isinstance(n, ast.FunctionDef) and n.name == name
    )
    namespace = dict(scope or {})
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
            str(SOURCE), "exec",
        ),
        namespace,
    )
    return namespace[name]


class MonitorEfficiencyTests(unittest.TestCase):
    def setUp(self):
        self.interval = isolated_function("monitor_poll_interval_s")

    def test_hidden_monitor_without_journal_polls_at_most_once_every_30_seconds(self):
        for interval in (2, 5, 15, 29):
            self.assertEqual(self.interval(False, False, interval), 30)

    def test_enabled_journal_preserves_user_interval(self):
        self.assertEqual(self.interval(False, True, 5), 5)
        self.assertEqual(self.interval(False, True, 2), 2)

    def test_visible_process_tab_preserves_user_interval_even_if_journal_off(self):
        self.assertEqual(self.interval(True, False, 5), 5)
        self.assertEqual(self.interval(True, False, 2), 2)

    def test_poll_interval_is_limited_to_supported_range(self):
        self.assertEqual(self.interval(True, True, -15), 2)
        self.assertEqual(self.interval(False, False, 2000), 120)

    def test_tab_and_stop_wake_monitor_immediately(self):
        namespace = {}
        functions = {}
        for name in ("request_refresh", "set_live_details", "stop"):
            functions[name] = isolated_function(name, owner="ProcMonitor")
        state = types.SimpleNamespace(
            _wake=threading.Event(),
            _live_details=threading.Event(),
            _stop=threading.Event(),
            _thread=Mock(),
        )
        state.request_refresh = lambda: functions["request_refresh"](state)
        functions["set_live_details"](state, True)
        self.assertTrue(state._wake.is_set())
        self.assertTrue(state._live_details.is_set())

        state._wake.clear()
        functions["set_live_details"](state, False)
        self.assertTrue(state._wake.is_set())
        self.assertFalse(state._live_details.is_set())

        state._wake.clear()
        functions["stop"](state)
        self.assertTrue(state._stop.is_set())
        self.assertTrue(state._wake.is_set())
        state._thread.join.assert_called_once_with(timeout=3)


class PowerRetryTests(unittest.TestCase):
    def setUp(self):
        self.clock = [100.0]
        self.log = Mock()
        self.tick = isolated_function(
            "tick", owner="PowerManager",
            scope={"time": types.SimpleNamespace(monotonic=lambda: self.clock[0]),
                   "log": self.log},
        )
        self.messages = []
        self.manager = types.SimpleNamespace(
            _last_target=None,
            _last_failed_target=None,
            _last_failed_at=0.0,
            desired=lambda: (f"plan:{BALANCED}", "от сети"),
            apply_profile=Mock(side_effect=[OSError("Access denied"), None]),
            _emit=self.messages.append,
            profile_name=lambda profile: "Сбалансированная",
        )

    def test_failed_powercfg_is_not_marked_as_applied(self):
        self.tick(self.manager)
        self.assertIsNone(self.manager._last_target)
        self.assertEqual(self.manager._last_failed_target, f"plan:{BALANCED}")
        self.assertEqual(self.manager._last_failed_at, 100.0)
        self.assertEqual(self.manager.apply_profile.call_count, 1)
        self.assertIn("не удалось применить", self.messages[0])

    def test_retries_after_cooldown_and_only_then_marks_success(self):
        self.tick(self.manager)
        self.clock[0] = 110.0
        self.tick(self.manager)
        self.assertEqual(self.manager.apply_profile.call_count, 1)
        self.clock[0] = 130.0
        self.tick(self.manager)
        self.assertEqual(self.manager.apply_profile.call_count, 2)
        self.assertEqual(self.manager._last_target, f"plan:{BALANCED}")
        self.assertIsNone(self.manager._last_failed_target)
        self.assertIn("→", self.messages[-1])

    def test_different_target_bypasses_failed_target_cooldown(self):
        second = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
        self.tick(self.manager)
        self.clock[0] = 105.0
        self.manager.desired = lambda: (f"plan:{second}", "запущен процесс")
        self.tick(self.manager)
        self.assertEqual(self.manager.apply_profile.call_count, 2)
        self.assertEqual(self.manager._last_target, f"plan:{second}")


class PowerCommandTests(unittest.TestCase):
    def setUp(self):
        self.run_cmd = Mock(return_value=(0, ""))
        self.overlay = Mock()
        self.apply = isolated_function(
            "apply_profile", owner="PowerManager",
            scope={
                "_GUID_RE": re.compile(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
                                       r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                                       r"[0-9a-fA-F]{12})"),
                "BALANCED": BALANCED,
                "OVERLAY_MODES": {MODE: "Сбалансированный"},
                "run_cmd": self.run_cmd,
                "set_overlay": self.overlay,
            },
        )
        self.manager = types.SimpleNamespace(
            has_overlay=True,
            plans=[(BALANCED, "Сбалансированная", True)],
        )

    def test_rejects_unknown_profile_type_or_invalid_guid(self):
        for profile in ("", "bad", f"unknown:{BALANCED}", "plan:bogus",
                        f"mode:{BALANCED}"):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                self.apply(self.manager, profile)
        self.run_cmd.assert_not_called()
        self.overlay.assert_not_called()

    def test_powercfg_failure_does_not_report_success(self):
        self.run_cmd.return_value = (5, "Access denied")
        with self.assertRaisesRegex(RuntimeError, "Access denied"):
            self.apply(self.manager, f"plan:{BALANCED}")

    def test_power_overlay_not_applied_if_balanced_profile_activation_fails(self):
        self.run_cmd.return_value = (5, "cannot activate Balanced")
        with self.assertRaisesRegex(RuntimeError, "cannot activate Balanced"):
            self.apply(self.manager, f"mode:{MODE}")
        self.overlay.assert_not_called()

    def test_valid_power_overlay_activates_balanced_then_mode(self):
        self.apply(self.manager, f"mode:{MODE}")
        self.run_cmd.assert_called_once_with(
            ["powercfg", "/setactive", BALANCED], 30)
        self.overlay.assert_called_once_with(MODE)


class AtomicSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "nested" / "settings.json"
        self.save = isolated_function(
            "save", owner="Settings",
            scope={"os": os, "json": json, "uuid": uuid, "log": logging.getLogger("test")},
        )
        self.settings = types.SimpleNamespace(
            path=self.path,
            data={"mon_enabled": False, "interval": 15, "title": "Ноутбук"},
        )

    def test_atomic_write_creates_directory_and_valid_json(self):
        self.save(self.settings)
        self.assertEqual(
            json.loads(self.path.read_text(encoding="utf-8")),
            self.settings.data,
        )
        self.assertEqual(list(self.path.parent.glob(".*.tmp")), [])

    def test_replace_error_preserves_previous_settings_and_cleans_temp(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"original":true}', encoding="utf-8")
        with patch.object(os, "replace", side_effect=OSError("Disk error")):
            self.save(self.settings)
        self.assertEqual(
            json.loads(self.path.read_text(encoding="utf-8")),
            {"original": True},
        )
        self.assertEqual(list(self.path.parent.glob(".*.tmp")), [])


class PortableRootTests(unittest.TestCase):
    def test_choice_batch_only_is_detected_as_launcher(self):
        fn = isolated_function("_is_launcher_dir", scope={"Path": Path})
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            self.assertFalse(fn(root))
            (root / "Choice.bat").write_text("", encoding="utf-8")
            self.assertTrue(fn(root))


if __name__ == "__main__":
    unittest.main()
