import ast
import unittest
from pathlib import Path


SOURCE = Path(__file__).with_name("laptop_care.py")


def load_monitor_policy():
    source = SOURCE.read_text(encoding="utf-8-sig")
    syntax = ast.parse(source, filename=str(SOURCE))
    function = next(
        node for node in syntax.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "monitor_needs_process_details"
    )
    module = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {}
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace["monitor_needs_process_details"]


class MonitorPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.should_collect = staticmethod(load_monitor_policy())

    def test_inactive_tab_normal_load_does_not_enumerate_processes(self):
        self.assertFalse(self.should_collect(False, True, [], 100.0, 0.0))

    def test_monitor_disabled_and_tab_hidden_does_not_enumerate_processes(self):
        self.assertFalse(self.should_collect(False, False, ["cpu"], 100.0, 0.0))

    def test_visible_process_tab_always_gets_live_details(self):
        self.assertTrue(self.should_collect(True, False, [], 100.0, 90.0))
        self.assertTrue(self.should_collect(True, True, ["ram"], 100.0, 99.0))

    def test_high_load_is_logged_after_cooldown(self):
        self.assertFalse(self.should_collect(False, True, ["cpu"], 59.99, 30.0))
        self.assertTrue(self.should_collect(False, True, ["cpu"], 60.0, 30.0))

    def test_high_memory_or_disk_retains_logging(self):
        self.assertTrue(self.should_collect(False, True, ["ram"], 90.0, 30.0))
        self.assertTrue(self.should_collect(False, True, ["disk"], 90.0, 30.0))

    def test_no_threshold_does_not_scan_even_after_cooldown(self):
        self.assertFalse(self.should_collect(False, True, [], 600.0, 0.0))


if __name__ == "__main__":
    unittest.main()
