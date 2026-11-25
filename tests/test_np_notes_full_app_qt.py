"""Integration smoke test for the *actual* NotesApp first-run UI.

Temporary LAUNCHER_ROOT; never touches a user's existing Data.
Requires PySide6 and runs with QT_QPA_PLATFORM=offscreen.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

APP_ROOT = Path(__file__).resolve().parents[1] / "Other_dev"


class FullAppFirstRunSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="np-notes-full-smoke-"))
        cls.old_launcher_root = os.environ.get("LAUNCHER_ROOT")
        os.environ["LAUNCHER_ROOT"] = str(cls.root)
        (cls.root / "Data").mkdir()
        settings = QSettings(str(cls.root / "Data" / "settings.ini"), QSettings.IniFormat)
        settings.setValue("spellcheck/online_enabled", False)
        settings.setValue("ui/always_on_top", False)
        settings.sync()
        sys.path.insert(0, str(APP_ROOT))
        from noteapp.app import init_app_environment, NotesApp
        cls.NotesApp = NotesApp
        init_app_environment()
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        if cls.old_launcher_root is None:
            os.environ.pop("LAUNCHER_ROOT", None)
        else:
            os.environ["LAUNCHER_ROOT"] = cls.old_launcher_root
        if str(APP_ROOT) in sys.path:
            sys.path.remove(str(APP_ROOT))
        # Log handlers and Qt filesystem watchers remain alive until this
        # isolated Python process exits. GitHub Actions removes temporary Data
        # in the following step, after Windows releases the file handles.

    def test_empty_data_then_create_first_note(self):
        window = self.NotesApp()
        self.addCleanup(window.hide)
        window.show()
        self.app.processEvents()
        self.assertTrue(window.central_widget.isVisible())
        self.assertTrue(window.empty_notes_page.isVisible())
        self.assertFalse(window.text_edit.isVisible())
        self.assertEqual(window.notes_list.count(), 0)
        with patch("PySide6.QtWidgets.QInputDialog.getText",
                   return_value=("Проверка первого запуска", True)):
            window.new_note()
        self.app.processEvents()
        self.assertIsNotNone(window.current_note)
        self.assertTrue(window.text_edit.isVisible())
        self.assertFalse(window.empty_notes_page.isVisible())
        self.assertEqual(window.current_note.title, "Проверка первого запуска")
        self.assertEqual(window.notes_list.count(), 1)
        self.assertTrue((self.root / "Data" / "Notes").exists())


if __name__ == "__main__":
    unittest.main()
