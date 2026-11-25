"""Crash-draft recovery UI for Windows, backed by DPAPI-encrypted sidecars.

The legacy JSON note format is unchanged. Recovery is never applied silently.
"""
import logging
import os

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QMessageBox

from ..config import DATA_DIR, NOTES_DIR
from ..recovery import clear_draft, list_drafts, read_draft, save_draft

RECOVERY_DIR = DATA_DIR / "Recovery"


class RecoveryMixin:
    def _setup_recovery_snapshot_timer(self) -> None:
        if os.name != "nt":
            return
        if getattr(self, "_recovery_snapshot_timer", None) is not None:
            return
        self._recovery_snapshot_timer = QTimer(self)
        self._recovery_snapshot_timer.setSingleShot(True)
        self._recovery_snapshot_timer.timeout.connect(self._write_recovery_snapshot)
        self._recovery_snapshot_note_uuid = None

    def _schedule_recovery_snapshot(self) -> None:
        if os.name != "nt" or not getattr(self, "current_note", None):
            return
        if getattr(self, "_is_switching_note", False):
            return
        self._setup_recovery_snapshot_timer()
        self._recovery_snapshot_note_uuid = self.current_note.uuid
        self._recovery_snapshot_timer.start(150)

    def _write_recovery_snapshot(self) -> None:
        note = getattr(self, "current_note", None)
        if not note or getattr(self, "_is_switching_note", False):
            return
        if note.uuid != getattr(self, "_recovery_snapshot_note_uuid", None):
            return
        try:
            save_draft(RECOVERY_DIR, note.uuid, self.text_edit.toHtml())
        except Exception:
            # Never log HTML, private contents or password fields.
            logging.exception("Could not store protected recovery draft")

    def _clear_recovery_snapshot(self, note_uuid: str | None) -> None:
        if os.name != "nt" or not note_uuid:
            return
        if (getattr(self, "_recovery_snapshot_note_uuid", None) == note_uuid
                and getattr(self, "_recovery_snapshot_timer", None) is not None):
            self._recovery_snapshot_timer.stop()
        try:
            clear_draft(RECOVERY_DIR, note_uuid)
        except Exception:
            logging.exception("Unable to clear recovery draft")

    def _offer_recovery_snapshots(self) -> None:
        """Ask before applying old unsaved HTML. Rejecting removes only the draft."""
        if os.name != "nt" or not getattr(self, "notes", None):
            return
        if getattr(self, "_recovery_offered_once", False):
            return
        self._recovery_offered_once = True
        lookup = {note.uuid: note for note in self.notes}
        try:
            candidates = list_drafts(RECOVERY_DIR)
        except Exception:
            logging.exception("Could not enumerate encrypted recovery drafts")
            return
        for note_uuid in candidates[:20]:
            note = lookup.get(note_uuid)
            if note is None:
                # May belong to a note moved to Trash; never delete blindly.
                continue
            try:
                record = read_draft(RECOVERY_DIR, note_uuid)
            except Exception:
                logging.exception("Unable to decrypt or inspect recovery draft")
                continue
            if record is None:
                continue
            draft_html = record["html"]
            if draft_html == (note.content or ""):
                self._clear_recovery_snapshot(note_uuid)
                continue
            if (getattr(self, "current_note", None) is note
                    and self.isWindowModified()):
                # Do not overwrite typing performed since startup.
                continue
            saved_is_newer = False
            try:
                note_path = self._note_folder_path(note, NOTES_DIR) / "note.json"
                draft_timestamp = int(record.get("timestamp_ns") or 0)
                saved_is_newer = bool(
                    draft_timestamp and note_path.is_file()
                    and note_path.stat().st_mtime_ns > draft_timestamp
                )
            except (OSError, AttributeError, ValueError, TypeError):
                pass
            warning = (
                "\n\nВНИМАНИЕ: сохранённая версия новее черновика. "
                "Восстановление заменит текущий текст."
                if saved_is_newer else ""
            )
            answer = QMessageBox.question(
                self,
                "Найдены несохранённые правки",
                "Для заметки «" + str(note.title or "Без названия") +
                "» найден зашифрованный черновик предыдущего запуска.\n\n"
                "Восстановить черновик? «Нет» удалит его, «Отмена» оставит "
                "для следующего запуска." + warning,
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if answer == QMessageBox.Cancel:
                continue
            if answer == QMessageBox.No:
                self._clear_recovery_snapshot(note_uuid)
                continue
            try:
                # Find the existing row rather than fabricating a Note or UUID.
                for index in range(self.notes_list.count()):
                    item = self.notes_list.item(index)
                    item_note = item.data(Qt.UserRole)
                    if item_note and item_note.uuid == note_uuid:
                        self.notes_list.setCurrentItem(item)
                        self.load_note(item)
                        break
                else:
                    continue
                self.text_edit.setHtml(draft_html)
                self._set_unsaved(True)
                # Explicitly accepted changes become a regular atomic note save.
                self.save_note_quiet(force=True)
                self._clear_recovery_snapshot(note_uuid)
            except Exception:
                logging.exception("Could not apply recovered draft")
                self._set_unsaved(True)
                QMessageBox.warning(
                    self,
                    "Ошибка восстановления",
                    "Не удалось сохранить восстановленный черновик. "
                    "Его зашифрованная копия оставлена для повторной попытки.",
                )
