"""Regression tests for the Screenshot editor's Applications action."""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

SOURCE = Path(__file__).resolve().parents[1] / "Other_dev" / "screenshot.py"
SPEC = importlib.util.spec_from_file_location("np_screenshot_apps_under_test", SOURCE)
shot = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = shot
SPEC.loader.exec_module(shot)


class AppLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        image = QImage(40, 30, QImage.Format_ARGB32)
        image.fill(0xFF000000)
        self.editor = shot.EditorWindow(image)
        self.addCleanup(lambda: (self.editor.view.mark_clean(), self.editor.close()))

    def test_existing_choice_is_activated_without_new_process(self):
        with patch.object(self.editor, "_activate_existing_choice", return_value=True), \
             patch.object(shot.QProcess, "startDetached") as spawn, \
             patch.object(self.editor, "_find_launcher_candidate") as lookup:
            self.editor.show_app_launcher()
        spawn.assert_not_called()
        lookup.assert_not_called()

    def test_missing_choice_warns_without_spawning(self):
        with patch.object(self.editor, "_activate_existing_choice", return_value=False), \
             patch.object(self.editor, "_find_launcher_candidate", return_value=None), \
             patch.object(shot.QProcess, "startDetached") as spawn, \
             patch.object(shot.QMessageBox, "warning") as warning:
            self.editor.show_app_launcher()
        spawn.assert_not_called()
        warning.assert_called_once()

    def test_choice_starts_with_portable_pythonw_when_not_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "Choice.pyw"
            app.write_text("pass\n", encoding="utf-8")
            runtime = root / "Runtime"
            runtime.mkdir()
            pythonw = runtime / "pythonw.exe"
            pythonw.write_bytes(b"test")
            with patch.object(self.editor, "_activate_existing_choice", return_value=False), \
                 patch.object(self.editor, "_find_launcher_candidate", return_value=app), \
                 patch.object(shot.QProcess, "startDetached") as spawn:
                self.editor.show_app_launcher()
            spawn.assert_called_once_with(str(pythonw), [str(app)])


if __name__ == "__main__":
    unittest.main()
