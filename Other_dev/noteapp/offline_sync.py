"""Offline-first delivery queue for NP Notes.

Safe building block: never reads or alters notes, never sends unencrypted data.
An authenticated encrypted GitHub transport must be configured separately.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
import threading
import time
from pathlib import Path
from typing import Callable

SYNC_INTERVAL_SECONDS = 300
RETRY_INTERVAL_SECONDS = 15


class OfflineSyncQueue:
    """Durable coalescing queue of note identifiers, not note contents."""

    def __init__(self, state_directory: Path):
        self.directory = Path(state_directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db_path = self.directory / "pending_sync.sqlite3"
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.db_path), timeout=10)
        try:
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def _initialize(self):
        with self._lock, self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS pending (
                item_id TEXT PRIMARY KEY NOT NULL,
                revision INTEGER NOT NULL,
                modified_ns INTEGER NOT NULL
            )""")

    @staticmethod
    def _validate_item(item_id: str):
        if (not isinstance(item_id, str) or not item_id or
                len(item_id) > 200 or "/" in item_id or
                chr(92) in item_id or item_id in (".", "..")):
            raise ValueError("Invalid sync item identifier")

    def mark_changed(self, item_id: str):
        """Call only *after* the local note and attachments were saved."""
        self._validate_item(item_id)
        with self._lock, self._connect() as db:
            db.execute("""INSERT INTO pending(item_id, revision, modified_ns)
                          VALUES (?, 1, ?)
                          ON CONFLICT(item_id) DO UPDATE SET
                          revision=revision+1,
                          modified_ns=excluded.modified_ns""",
                       (item_id, time.time_ns()))

    def pending(self):
        with self._lock, self._connect() as db:
            return db.execute(
                "SELECT item_id, revision FROM pending ORDER BY modified_ns, item_id"
            ).fetchall()

    def acknowledge(self, item_id: str, revision: int):
        """Never drop an edit made while an older revision was uploading."""
        with self._lock, self._connect() as db:
            cur = db.execute(
                "DELETE FROM pending WHERE item_id=? AND revision=?",
                (item_id, revision),
            )
            return cur.rowcount == 1

    def count(self):
        with self._lock, self._connect() as db:
            return db.execute("SELECT COUNT(*) FROM pending").fetchone()[0]


class OfflineSyncWorker:
    """Inject network probe and *encrypted* upload callback; fail closed.

    A probe checks transport reachability, not general internet. Sender must
    raise on error and return True only after remote durable confirmation.
    """

    def __init__(
        self,
        queue: OfflineSyncQueue,
        online: Callable[[], bool],
        send_encrypted: Callable[[str], bool],
        *,
        interval_seconds: float = SYNC_INTERVAL_SECONDS,
        retry_seconds: float = RETRY_INTERVAL_SECONDS,
    ):
        if interval_seconds <= 0 or retry_seconds <= 0:
            raise ValueError("Intervals must be positive")
        self.queue = queue
        self.online = online
        self.send_encrypted = send_encrypted
        self.interval_seconds = interval_seconds
        self.retry_seconds = retry_seconds
        self.state = "idle"
        self._wakeup = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def sync_once(self):
        if not self.online():
            self.state = "waiting_for_network"
            return False
        self.state = "synchronizing"
        try:
            for item_id, revision in self.queue.pending():
                if not self.online():
                    self.state = "waiting_for_network"
                    return False
                if self.send_encrypted(item_id) is not True:
                    self.state = "retry_pending"
                    return False
                self.queue.acknowledge(item_id, revision)
        except Exception:
            self.state = "retry_pending"
            return False
        self.state = "synchronized"
        return True

    def _run(self):
        while not self._stop.is_set():
            ok = self.sync_once()
            delay = self.interval_seconds if ok else self.retry_seconds
            self._wakeup.wait(delay)
            self._wakeup.clear()

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="NPNotesOfflineSync", daemon=True
        )
        self._thread.start()

    def wake(self):
        """Trigger retry, e.g. after an OS network-available notification."""
        self._wakeup.set()

    def stop(self, timeout=5):
        self._stop.set()
        self._wakeup.set()
        if self._thread is not None:
            self._thread.join(timeout)
