"""Optional non-blocking sync integration for NP Notes Qt GUI.

No configuration => no worker, network request or file scan.
A background thread runs at most once per five minutes; the editor remains usable
when GitHub or the internet is unavailable.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QThread, QTimer, Signal

from ..config import DATA_DIR
from ..github_sync import SYNC_INTERVAL_MS, enabled_config, run_configured_sync


class SyncThread(QThread):
    completed = Signal(object)

    def __init__(self, protected_uuid: str | None = None, parent=None):
        super().__init__(parent)
        self.protected_uuid = protected_uuid

    def run(self):
        try:
            outcome = run_configured_sync(DATA_DIR, protected_uuid=self.protected_uuid)
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
        thread.finished.connect(thread.deleteLater)
        self._github_sync_thread = thread
        thread.start()

    def _github_sync_completed(self, result):
        if result is None:
            self._github_sync_status = "error"
            return
        self._github_sync_status = result.status
        if result.downloaded and not getattr(self, "_unsaved", False):
            # Reconcile disk imports via the existing preload mechanism on GUI thread.
            # Current selected note is protected by the worker and is never overwritten.
            try:
                self._start_background_preload()
            except Exception:
                logging.exception("Unable to refresh imported notes")
