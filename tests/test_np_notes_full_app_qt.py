"""Real NotesApp first-run UI smoke in a disposable Windows process.

Controller waits for a success marker from the worker, then terminates the GUI
process. This reflects a long-running desktop application: it does not pretend
that closing a window is the same as Python interpreter teardown.
Production Launcher/Data is never accessed.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


def gui_worker(root: Path) -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["LAUNCHER_ROOT"] = str(root)
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    data = root / "Data"
    data.mkdir(parents=True, exist_ok=True)
    settings = QSettings(str(data / "settings.ini"), QSettings.IniFormat)
    settings.setValue("spellcheck/online_enabled", False)
    settings.setValue("ui/always_on_top", False)
    settings.sync()

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Other_dev"))
    from noteapp.app import NotesApp, init_app_environment

    init_app_environment()
    app = QApplication([])
    window = NotesApp()
    window.show()
    app.processEvents()
    assert window.central_widget.isVisible(), "Central widget hidden on first run"
    assert window.empty_notes_page.isVisible(), "Welcome screen hidden"
    assert not window.text_edit.isVisible(), "Editor visible with no active note"
    assert window.notes_list.count() == 0, "Isolated Data is not empty"

    with patch("PySide6.QtWidgets.QInputDialog.getText",
               return_value=("Проверка первого запуска", True)):
        window.new_note()
    app.processEvents()
    assert window.current_note is not None, "First note was not created"
    assert window.text_edit.isVisible(), "Editor did not appear"
    assert not window.empty_notes_page.isVisible(), "Welcome screen still visible"
    assert window.current_note.title == "Проверка первого запуска"
    assert window.notes_list.count() == 1
    assert (root / "Data" / "Notes").exists()

    (root / "ready.flag").write_text("FIRST_RUN_GUI_OK", encoding="ascii")
    # Worker intentionally remains running; the controller stops this temporary
    # process after asserting that the GUI reached the correct state.
    app.exec()


class FullAppFirstRunSmoke(unittest.TestCase):
    def test_empty_data_then_create_first_note(self):
        with tempfile.TemporaryDirectory(prefix="np-notes-full-smoke-") as path:
            root = Path(path)
            env = os.environ.copy()
            env["QT_QPA_PLATFORM"] = "offscreen"
            env["LAUNCHER_ROOT"] = str(root)
            process = subprocess.Popen(
                [sys.executable, "-u", str(Path(__file__).resolve()),
                 "--worker", str(root)],
                cwd=str(Path(__file__).resolve().parents[1]),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                ready = root / "ready.flag"
                for _ in range(300):
                    if ready.is_file():
                        self.assertEqual(ready.read_text(encoding="ascii"),
                                         "FIRST_RUN_GUI_OK")
                        break
                    if process.poll() is not None:
                        output, errors = process.communicate(timeout=5)
                        self.fail("Full NotesApp quit before readiness: "
                                  + str(process.returncode) + "\n"
                                  + output[-2500:] + "\n" + errors[-2500:])
                    time.sleep(0.1)
                else:
                    self.fail("Full NotesApp did not reach readiness within 30 seconds")
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=5)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--worker":
        gui_worker(Path(sys.argv[2]).resolve())
    else:
        unittest.main()
