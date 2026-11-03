"""Очередь приоритетных сочетаний NP Punto и защита исходного поля ввода."""
import importlib.util
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[1] / "Other_dev" / "punto_like_work_safe.py"
SPEC = importlib.util.spec_from_file_location("np_punto_hotkey_priority", SOURCE)
punto = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = punto
SPEC.loader.exec_module(punto)


class JobPriorityTests(unittest.TestCase):
    def test_hotkey_runs_before_queued_clipboard_image(self):
        worker = punto._JobWorker("test-priority")
        begun = threading.Event()
        release = threading.Event()
        completed = threading.Event()
        order = []

        def hold():
            begun.set()
            self.assertTrue(release.wait(3.0))

        worker.start()
        try:
            self.assertTrue(worker.submit("hold", hold, priority=0))
            self.assertTrue(begun.wait(2.0))
            self.assertTrue(worker.submit("clipboard-capture", lambda: order.append("clipboard"), priority=10))
            self.assertTrue(worker.submit("manual-hotkey", lambda: (order.append("hotkey"), completed.set()), priority=0))
            release.set()
            self.assertTrue(completed.wait(2.0))
            worker.stop()
            self.assertEqual(order, ["hotkey", "clipboard"])
        finally:
            release.set()
            worker.stop()

    def test_same_priority_is_fifo(self):
        worker = punto._JobWorker("test-fifo")
        begun = threading.Event()
        release = threading.Event()
        executed = []
        worker.start()
        try:
            worker.submit("hold", lambda: (begun.set(), release.wait(3.0)), priority=0)
            self.assertTrue(begun.wait(2.0))
            worker.submit("first", lambda: executed.append(1), priority=0)
            worker.submit("second", lambda: executed.append(2), priority=0)
            release.set()
            worker.stop()
            self.assertEqual(executed, [1, 2])
        finally:
            release.set()
            worker.stop()

    def test_clipboard_job_allows_new_event_to_be_queued_during_capture(self):
        punto._capture_pending.set()
        observed = []

        def capture(*args, **kwargs):
            #НП: Пока worker читает старый буфер, новое изменение должно
            #НП: иметь возможность поставить ещё одну задачу сохранения.
            observed.append(punto._capture_pending.is_set())

        try:
            with patch.object(punto, "_capture_clipboard_to_history", side_effect=capture), \
                 patch.object(punto, "_is_paused", False):
                punto._clipboard_capture_job()
            self.assertEqual(observed, [False])
            self.assertFalse(punto._capture_pending.is_set())
        finally:
            punto._capture_pending.clear()

    def test_clipboard_job_clears_pending_on_error(self):
        punto._capture_pending.set()
        try:
            with patch.object(punto, "_capture_clipboard_to_history", side_effect=RuntimeError("copy fail")), \
                 patch.object(punto, "_is_paused", False):
                with self.assertRaises(RuntimeError):
                    punto._clipboard_capture_job()
            self.assertFalse(punto._capture_pending.is_set())
        finally:
            punto._capture_pending.clear()


class HotkeyContextTests(unittest.TestCase):
    def setUp(self):
        self.fg = [101]
        self.focus = [202]
        self.worker = Mock()
        self.pending = []

        def submit(name, fn, *, priority):
            self.pending.append((name, fn, priority))
            return True

        self.worker.submit.side_effect = submit
        self.windows = Mock()
        self.windows.GetForegroundWindow.side_effect = lambda: self.fg[0]
        self.mock_user32 = patch.object(punto, "user32", self.windows)
        self.mock_worker = patch.object(punto, "_worker", self.worker)
        self.mock_focus = patch.object(
            punto, "_get_focused_control_hwnd", side_effect=lambda: self.focus[0]
        )
        self.mock_pause = patch.object(punto, "_is_paused", False)
        self.mock_user32.start()
        self.mock_worker.start()
        self.mock_focus.start()
        self.mock_pause.start()
        self.addCleanup(self.mock_user32.stop)
        self.addCleanup(self.mock_worker.stop)
        self.addCleanup(self.mock_focus.stop)
        self.addCleanup(self.mock_pause.stop)

    def enqueue(self):
        action = Mock()
        self.assertTrue(punto._queue_hotkey_action("Ctrl+Ins", action))
        self.assertEqual(len(self.pending), 1)
        self.assertEqual(self.pending[0][0], "Ctrl+Ins")
        self.assertEqual(self.pending[0][2], 0)
        return action, self.pending[0][1]

    def test_same_window_and_control_executes_hotkey(self):
        action, fn = self.enqueue()
        fn()
        action.assert_called_once_with()

    def test_switch_to_choice_or_browser_discards_old_command(self):
        action, fn = self.enqueue()
        self.fg[0] = 303
        fn()
        action.assert_not_called()

    def test_switch_field_in_same_application_discards_old_command(self):
        action, fn = self.enqueue()
        self.focus[0] = 404
        fn()
        action.assert_not_called()

    def test_unknown_focus_keeps_existing_fallback_behavior(self):
        self.focus[0] = 0
        action, fn = self.enqueue()
        fn()
        action.assert_called_once_with()

    def test_delayed_work_is_skipped_to_avoid_editing_stale_text(self):
        fake_clock = [100.0]
        with patch.object(punto.time, "monotonic", side_effect=lambda: fake_clock[0]):
            action, fn = self.enqueue()
            fake_clock[0] = 105.0
            fn()
        action.assert_not_called()

    def test_pausing_after_keypress_discards_queued_action(self):
        action, fn = self.enqueue()
        with patch.object(punto, "_is_paused", True):
            fn()
        action.assert_not_called()

    def test_queue_rejection_is_reported(self):
        self.worker.submit.side_effect = lambda *args, **kwargs: False
        self.assertFalse(punto._queue_hotkey_action("Ctrl+F9", Mock()))

    def test_both_primary_shortcuts_use_guarded_priority_queue(self):
        calls = []
        with patch.object(punto, "_queue_hotkey_action",
                          side_effect=lambda name, action: calls.append(name) or True), \
             patch.object(punto, "_idle", Mock()):
            self.assertTrue(punto._on_hotkey(punto._HK_CONVERT_BEFORE_CARET))
            self.assertTrue(punto._on_hotkey(punto._HK_TOGGLE_CASE_BEFORE_CARET))
        self.assertEqual(calls, ["convert-before-caret", "toggle-case-before-caret"])


if __name__ == "__main__":
    unittest.main()
