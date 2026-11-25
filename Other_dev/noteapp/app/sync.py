"""Optional non-blocking sync integration for NP Notes Qt GUI.

No configuration => no worker, network request or file scan.
A background thread runs at most once per five minutes; the editor remains usable
when GitHub or the internet is unavailable.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QThread, QTimer, Signal

from ..config import DATA_DIR, NOTES_DIR
from ..github_sync import SYNC_INTERVAL_MS, enabled_config, run_configured_sync, apply_configured_pending


class SyncThread(QThread):
    completed = Signal(object)

    def __init__(self, protected_uuid: str | None = None, parent=None):
        super().__init__(parent)
        self.protected_uuid = protected_uuid

    def run(self):
        try:
            outcome = run_configured_sync(DATA_DIR, protected_uuid=self.protected_uuid,
                                          stage_downloads=True, cancelled=self.isInterruptionRequested)
            self.completed.emit(outcome)
        except Exception as exc:
            # Do not log token, passphrase or note contents.
            logging.warning("NP Notes GitHub sync suspended: %s", type(exc).__name__)
            self.completed.emit(None)


class SyncMixin:
    def _setup_github_sync(self):
        self._github_sync_thread = None
        self._github_sync_timer = QTimer(self)
        self._github_sync_timer.setInterval(SYNC_INTERVAL_MS)
        self._github_sync_timer.timeout.connect(self._trigger_github_sync)
        self._github_sync_timer.start()
        # The first scan runs after the standard note preload has finished.
        QTimer.singleShot(12000, self._trigger_github_sync)

    def _trigger_github_sync(self):
        thread = getattr(self, "_github_sync_thread", None)
        if thread is not None and thread.isRunning():
            return
        try:
            if enabled_config(DATA_DIR) is None:
                return
        except Exception:
            logging.warning("NP Notes GitHub sync configuration invalid")
            return
        active = getattr(self, "current_note", None)
        protected = getattr(active, "uuid", None)
        # Any unsaved editor content must remain exclusively in memory/local disk.
        thread = SyncThread(protected_uuid=protected, parent=self)
        thread.completed.connect(self._github_sync_completed)
        thread.finished.connect(self._github_sync_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._github_sync_thread = thread
        thread.start()

    def _github_sync_thread_finished(self):
        self._github_sync_thread = None

    def _stop_github_sync(self) -> bool:
        timer = getattr(self, "_github_sync_timer", None)
        if timer is not None:
            timer.stop()
        worker = getattr(self, "_github_sync_thread", None)
        if worker is None:
            return True
        try:
            if worker.isRunning():
                worker.requestInterruption()
                # GitHub's HTTP timeout is 12 seconds; do not destroy a live QThread.
                if not worker.wait(15000):
                    return False
        except RuntimeError:
            return True
        return True

    def _github_sync_completed(self, result):
        if result is None:
            self._github_sync_status = "error"
            return
        self._github_sync_status = result.status
        if getattr(self, "_unsaved", False):
            return
        active = getattr(self, "current_note", None)
        protected = getattr(active, "uuid", None)
        try:
            # Only Qt main thread applies staged encrypted remote updates.
            updated = apply_configured_pending(DATA_DIR, protected_uuid=protected)
        except Exception:
            logging.exception("Unable to apply verified sync downloads")
            return
        if not updated:
            return
        try:
            # Replace only imported UUIDs in memory. Preserve selected editor
            # and unsaved notes, and never start a second preload race.
            changed = set(updated)
            by_id = {note.uuid: note for note in getattr(self, "notes", [])
                     if note.uuid not in changed}
            for folder in NOTES_DIR.iterdir():
                file = folder / "note.json"
                if folder.is_dir() and not folder.is_symlink() and file.is_file():
                    payload = self._load_note_from_path(str(file))
                    if payload.uuid in changed:
                        by_id[payload.uuid] = payload
            self.notes = list(by_id.values())
            self._apply_saved_notes_order()
            self.refresh_notes_list()
            self.update_tag_filter_items()
            self.update_search_filter_items()
        except Exception:
            logging.exception("Imported note files are safe, but GUI refresh failed")
