import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QToolBar

from choice_dev import FriendlyLauncher, choice_window_icon, choice_icon_paths, set_choice_windows_identity


class ChoiceWindowSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_choice_has_dedicated_icon_even_without_files(self):
        with patch("choice_dev.choice_icon_paths", return_value=[]):
            icon = choice_window_icon()
        self.assertFalse(icon.isNull())
        self.assertFalse(icon.pixmap(32, 32).isNull())

    def test_installed_and_portable_icon_locations(self):
        paths = [str(p).replace("\\\\", "/") for p in choice_icon_paths()]
        self.assertTrue(any(p.lower().endswith("/data/choice.ico") for p in paths))
        self.assertTrue(any(p.lower().endswith("/choice.ico") for p in paths))

    def test_app_id_non_windows_does_not_modify_identity(self):
        with patch("choice_dev.sys.platform", "linux"):
            self.assertFalse(set_choice_windows_identity())

    def test_ui_builds_with_no_initial_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("choice_dev.config_file", return_value=Path(directory) / "launcher_config.json"):
                window = FriendlyLauncher()
                try:
                    window._startup_deferred()
                    self.assertEqual(window.scripts_list.selectedItems(), [])
                    self.assertEqual(window.running_list.selectedItems(), [])
                    self.assertFalse(window.advanced_button.isChecked())
                    self.assertFalse(window.env_editor.isVisible())
                    self.assertIsNotNone(window.tools_button.menu())
                    actions = window.tools_button.menu().actions()
                    self.assertEqual(len(actions), 8)
                    toolbars = window.findChildren(QToolBar)
                    self.assertTrue(toolbars)
                    self.assertLessEqual(len(toolbars[0].actions()), 6)
                    window.advanced_button.setChecked(True)
                    self.assertTrue(window.advanced_button.isChecked())
                    self.assertIn("▴", window.advanced_button.text())
                    window.advanced_button.setChecked(False)
                    self.assertIn("▾", window.advanced_button.text())
                finally:
                    window._allow_quit = True
                    window.close()


if __name__ == "__main__":
    unittest.main()
