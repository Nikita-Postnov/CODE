"""AutosaveMixin: планировщик автосохранения (дебаунс, таймер, автосейв).

Вырезано из NotesApp (step 4.6). Save-методы берёт из NotePersistenceMixin,
апстрим-методы (_set_unsaved, update_history_list, update_history_list_selection,
update_current_note_custom_fields, _persist_dropdown_values_in_html) остаются
в NotesApp — всё доступно через self.
"""

import logging
import traceback

from PySide6.QtCore import QTimer

from ..constants import MAX_HISTORY


class AutosaveMixin:
    def _schedule_autosave(self):
        if not getattr(self, "current_note", None):
            return
        if not getattr(self, "autosave_enabled", True):
            return
        if getattr(self, "_is_switching_note", False):
            return
        if getattr(self, "_autosave_in_progress", False):
            return

        try:
            self.autosave_timer.start(0)
        except Exception:
            pass

    def _get_autosave_debounce_ms(self) -> int:
        try:
            ms = int(self.settings.value("autosave/debounce_ms", 350))
        except Exception:
            ms = 350
        if ms < 150:
            ms = 150
        if ms > 5000:
            ms = 5000
        return ms

    def autosave(self) -> None:
        if self.current_note and not self.text_edit.isReadOnly():
            current_html = self.text_edit.toHtml()
            last_html = (
                self.current_note.history[-1] if self.current_note.history else ""
            )
            if current_html != last_html:
                if len(self.current_note.history) >= MAX_HISTORY:
                    self.current_note.history.pop(0)
                self.current_note.history.append(current_html)
                self.current_note.history_index = len(self.current_note.history) - 1
                self.update_history_list()
                self.update_history_list_selection()
            self.current_note.content = current_html
            self.current_note.password_manager = self.password_manager_field.text()
            self.save_note_to_file(self.current_note)

    def autosave_current_note(self):
        if not getattr(self, "autosave_enabled", True):
            return
        if not getattr(self, "current_note", None):
            return
        if (
            getattr(self, "_edit_session_note_uuid", None)
            and self.current_note
            and self.current_note.uuid != self._edit_session_note_uuid
        ):
            return
        self.current_note.content = self.text_edit.toHtml()
        self.current_note.password_manager = self.password_manager_field.text()
        self.update_current_note_custom_fields()
        self.save_note_to_file(self.current_note)
        self._set_unsaved(False)

    def _ensure_autosave_timer(self) -> None:
        if hasattr(self, "_autosave_timer") and isinstance(getattr(self, "_autosave_timer"), QTimer):
            return
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._perform_autosave)

        self._autosave_interval_ms = 0

        if not hasattr(self, "_autosave_in_progress"):
            self._autosave_in_progress = False

    def toggle_autosave(self, state: int):
        self.autosave_enabled = bool(state)
        self._ensure_autosave_timer()

        try:
            self.text_edit.textChanged.disconnect(self.on_text_changed_autosave)
        except Exception:
            pass

        if self.autosave_enabled:
            try:
                self.text_edit.textChanged.connect(self.on_text_changed_autosave)
            except Exception:
                pass
        else:
            try:
                self._autosave_timer.stop()
            except Exception:
                pass

    def on_text_changed_autosave(self):
        if not getattr(self, "autosave_enabled", False):
            return
        if not getattr(self, "current_note", None):
            return
        if getattr(self, "_is_switching_note", False):
            return
        if getattr(self, "_autosave_in_progress", False):
            return
        if (
            getattr(self, "_edit_session_note_uuid", None)
            and self.current_note
            and self.current_note.uuid != self._edit_session_note_uuid
        ):
            return
        self._ensure_autosave_timer()
        try:
            ms = self._get_autosave_debounce_ms()
            self._autosave_timer.start(ms)
        except Exception:
            logging.exception("Failed to start autosave timer")

    def _perform_autosave(self) -> None:
        if not getattr(self, "autosave_enabled", False):
            return
        if not getattr(self, "current_note", None):
            return
        if getattr(self, "_is_switching_note", False):
            return
        if getattr(self, "_autosave_in_progress", False):
            return
        if (
            getattr(self, "_edit_session_note_uuid", None)
            and self.current_note
            and self.current_note.uuid != self._edit_session_note_uuid
        ):
            return
        self._autosave_in_progress = True
        try:
            if hasattr(self, "autosave_current_note"):
                self.autosave_current_note()
            else:
                html = self.text_edit.toHtml()
                html = self._persist_dropdown_values_in_html(html)
                self.current_note.content = html
                self.save_note_to_file(self.current_note)
        except Exception:
            traceback.print_exc()
        finally:
            self._autosave_in_progress = False
