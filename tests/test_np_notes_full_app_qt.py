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

from PySide6.QtCore import QSettings, QCoreApplication, QEvent
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

    def tearDown(self):
        window = getattr(self, "window", None)
        if window is None:
            return
        loader = getattr(window, "_background_loader", None)
        if loader is not None and loader.isRunning():
            loader.wait(5000)
        for attr in ("autosave_timer", "_autosave_timer",
                     "_recovery_snapshot_timer", "reminder_timer",
                     "_timer", "_save_debouncer", "_layout_counter_timer"):
            timer = getattr(window, attr, None)
            if timer is not None:
                timer.stop()
        window._unregister_global_hotkeys()
        window.hide()
        window.deleteLater()
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def test_empty_data_then_create_first_note(self):
        window = self.NotesApp()
        self.window = window
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
