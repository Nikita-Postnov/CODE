"""RemindersMixin: напоминания заметок — диалоги, таймер, проверка и попапы.

Вырезано из NotesApp (step 4.4). Апстрим-методы (refresh_notes_list,
select_note, show_toast) остаются в NotesApp и доступны через self.
"""

from PySide6.QtCore import QDateTime, QTimer, Qt
from datetime import datetime, timedelta
from calendar import monthrange
from PySide6.QtWidgets import (
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
)



REPEAT_CODES = {
    "": "", "once": "", "однократно": "",
    "daily": "daily", "каждый день": "daily",
    "workdays": "workdays", "по будням": "workdays",
    "weekends": "weekends", "по выходным": "weekends",
    "weekly": "weekly", "каждую неделю": "weekly",
    "monthly": "monthly", "каждый месяц": "monthly",
    "minutely": "minutely", "hourly": "hourly",
}


def normalize_reminder_repeat(value: str | None) -> str:
    return REPEAT_CODES.get(str(value or "").strip().casefold(), "")


def parse_reminder_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def next_reminder_datetime(due: datetime, now: datetime, repeat: str) -> datetime | None:
    repeat = normalize_reminder_repeat(repeat)
    if not repeat:
        return None
    if repeat in ("daily", "weekly", "hourly", "minutely"):
        seconds = {"daily": 86400, "weekly": 604800, "hourly": 3600, "minutely": 60}[repeat]
        jump = (now - due).total_seconds()
        return due + timedelta(seconds=seconds * (max(0, int(jump // seconds)) + 1))
    if repeat in ("workdays", "weekends"):
        due += timedelta(days=max(1, (now.date() - due.date()).days))
        while due <= now or ((due.weekday() < 5) != (repeat == "workdays")):
            due += timedelta(days=1)
        return due
    if repeat == "monthly":
        candidate = due
        original_day = due.day
        while candidate <= now:
            year, month = candidate.year, candidate.month + 1
            if month > 12:
                year += 1
                month = 1
            candidate = candidate.replace(year=year, month=month, day=min(original_day, monthrange(year, month)[1]))
        return candidate
    return None


class RemindersMixin:
    def open_mass_reminders_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        dialog.setWindowTitle("Массовое управление напоминаниями")
        layout = QVBoxLayout(dialog)
        list_widget = QListWidget()
        notes_with_reminder = [n for n in self.notes if n.reminder]
        for note in notes_with_reminder:
            item = QListWidgetItem(f"{note.title} [{note.reminder}]")
            item.setData(Qt.UserRole, note)
            item.setCheckState(Qt.Unchecked)
            list_widget.addItem(item)
        layout.addWidget(list_widget)
        btn_remove = QPushButton("Удалить напоминание у выбранных")
        btn_remove.clicked.connect(
            lambda _=False, lw=list_widget, dlg=dialog: self.mass_remove_reminders(
                lw, dlg
            )
        )
        layout.addWidget(btn_remove)
        dialog.setLayout(layout)
        dialog.exec()

    def mass_remove_reminders(self, list_widget, dialog):
        changed = False
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            note = item.data(Qt.UserRole)
            if item.checkState() == Qt.Checked:
                note.reminder = None
                note.reminder_repeat = None
                self.save_note_to_file(note)
                changed = True
        if changed:
            self.refresh_notes_list()
            dialog.accept()

    def show_reminder_dialog(self, note):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("Напоминание")
        note_time = note.reminder or ""
        when = QDateTime.fromString(note_time, Qt.ISODate)
        when_text = when.toString("dd.MM.yyyy HH:mm") if when.isValid() else note_time
        msg.setText(f"Напоминание по заметке:\n\n{note.title}\n\n{when_text}")

        open_btn = msg.addButton("Открыть заметку", QMessageBox.AcceptRole)
        snooze5_btn = msg.addButton("Отложить 5 мин", QMessageBox.ActionRole)
        snooze15_btn = msg.addButton("Отложить 15 мин", QMessageBox.ActionRole)
        snooze60_btn = msg.addButton("Отложить 1 час", QMessageBox.ActionRole)
        msg.addButton("ОК", QMessageBox.RejectRole)

        msg.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        msg.exec()
        clicked = msg.clickedButton()

        def _snooze(mins: int):
            dt = QDateTime.currentDateTime().addSecs(mins * 60)
            note.reminder = dt.toString(Qt.ISODate)
            note.reminder_shown = False

        if clicked == open_btn:
            try:
                self.select_note(note)
            except Exception:
                pass
        elif clicked == snooze5_btn:
            _snooze(5)
            return True
        elif clicked == snooze15_btn:
            _snooze(15)
            return True
        elif clicked == snooze60_btn:
            _snooze(60)
            return True
        return False

    def check_reminders(self):
        now = datetime.now()
        changed = False
        for note in list(self.notes):
            due = parse_reminder_datetime(note.reminder)
            if due is None or due.tzinfo is not None or due > now:
                continue
            if self.show_reminder_dialog(note):
                self.save_note_to_file(note)
                changed = True
                continue
            following = next_reminder_datetime(due, datetime.now(), note.reminder_repeat)
            note.reminder = following.isoformat(timespec="seconds") if following else None
            note.reminder_repeat = normalize_reminder_repeat(note.reminder_repeat) if following else None
            note.reminder_shown = False
            self.save_note_to_file(note)
            changed = True
        if changed:
            self.refresh_notes_list()

    def set_reminder_for_note(self):
        if not self.current_note:
            return
        dialog = QDialog(self)
        dialog.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        dialog.setWindowTitle("Установить напоминание")
        layout = QFormLayout(dialog)
        datetime_edit = QDateTimeEdit(QDateTime.currentDateTime())
        datetime_edit.setCalendarPopup(True)
        layout.addRow("Напоминание:", datetime_edit)
        repeat_combo = QComboBox()
        repeat_combo.addItems(
            ["Однократно", "По будням", "Каждый день", "Каждую неделю", "Каждый месяц"]
        )
        layout.addRow("Повторять:", repeat_combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            dt = datetime_edit.dateTime()
            self.current_note.reminder = dt.toString(Qt.ISODate)
            repeat_option = repeat_combo.currentText()
            if repeat_option == "Однократно":
                self.current_note.reminder_repeat = None
            else:
                self.current_note.reminder_repeat = normalize_reminder_repeat(repeat_option)
            self.save_note_to_file(self.current_note)
            self.refresh_notes_list()
            self.show_toast(f"Напоминание: {self.current_note.reminder}")

    def edit_reminder_for_note(self):
        if not self.current_note:
            QMessageBox.warning(self, "Нет заметки", "Сначала выберите заметку.")
            return
        dialog = QDialog(self)
        dialog.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        dialog.setWindowTitle("Изменить напоминание")
        layout = QFormLayout(dialog)
        if self.current_note.reminder:
            dt = QDateTime.fromString(self.current_note.reminder, "yyyy-MM-dd HH:mm")
            if not dt.isValid():
                dt = QDateTime.fromString(self.current_note.reminder, Qt.ISODate)
            if not dt.isValid():
                dt = QDateTime.currentDateTime()
        else:
            dt = QDateTime.currentDateTime()
        datetime_edit = QDateTimeEdit(dt)
        datetime_edit.setCalendarPopup(True)
        layout.addRow("Напоминание:", datetime_edit)
        repeat_combo = QComboBox()
        options = [
            "Однократно",
            "По будням",
            "Каждый день",
            "Каждую неделю",
            "Каждый месяц",
        ]
        repeat_combo.addItems(options)
        if getattr(self.current_note, "reminder_repeat", None) in options:
            repeat_combo.setCurrentText(
                self.current_note.reminder_repeat or "Однократно"
            )
        else:
            repeat_combo.setCurrentIndex(0)
        layout.addRow("Повторять:", repeat_combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.Accepted:
            dt = datetime_edit.dateTime()
            self.current_note.reminder = dt.toString(Qt.ISODate)
            selected = repeat_combo.currentText()
            self.current_note.reminder_repeat = (
                normalize_reminder_repeat(selected) or None
            )
            self.save_note_to_file(self.current_note)
            self.refresh_notes_list()
            self.show_toast("Напоминание обновлено")

    def remove_reminder_from_note(self):
        if self.current_note:
            self.current_note.reminder = None
            self.current_note.reminder_repeat = None
            self.save_note_to_file(self.current_note)
            self.refresh_notes_list()
            self.show_toast("Напоминание удалено")

    def check_upcoming_reminders(self):
        self.check_reminders()

    def show_reminder_popup(self, note):
        dlg = QDialog(self, Qt.WindowStaysOnTopHint)
        dlg.setWindowTitle("Напоминание")
        dlg.setWindowModality(Qt.NonModal)
        dlg.setMinimumWidth(300)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(f"Напоминание по заметке: <b>{note.title}</b>"))
        layout.addWidget(QLabel(f"Время: {note.reminder}"))
        btn = QPushButton("ОК")
        btn.clicked.connect(dlg.accept)
        layout.addWidget(btn)
        dlg.show()

    def setup_reminder_timer(self):
        self.reminder_timer = QTimer(self)
        self.reminder_timer.timeout.connect(self.check_reminders)
        self.reminder_timer.start(60000)
