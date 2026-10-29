"""RemindersMixin: напоминания заметок — диалоги, таймер, проверка и попапы.

Вырезано из NotesApp (step 4.4). Апстрим-методы (refresh_notes_list,
select_note, show_toast) остаются в NotesApp и доступны через self.
"""

from PySide6.QtCore import QDateTime, QTimer, Qt
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
            note.reminder_shown = True
        elif clicked == snooze5_btn:
            _snooze(5)
        elif clicked == snooze15_btn:
            _snooze(15)
        elif clicked == snooze60_btn:
            _snooze(60)
        else:
            note.reminder_shown = True

    def check_reminders(self):
        now = QDateTime.currentDateTime()
        changed = False
        for note in self.notes:
            if note.reminder and not getattr(note, "reminder_shown", False):
                reminder_time = QDateTime.fromString(note.reminder, Qt.ISODate)
                if not reminder_time.isValid():
                    continue
                if reminder_time <= now:
                    self.show_reminder_dialog(note)
                    changed = True
                    repeat = (note.reminder_repeat or "").lower()
                    if repeat in ("once", "", None):
                        note.reminder = None
                        note.reminder_repeat = None
                    elif repeat == "workdays":
                        next_dt = reminder_time.addDays(1)
                        while next_dt.date().dayOfWeek() > 5:
                            next_dt = next_dt.addDays(1)
                        note.reminder = next_dt.toString(Qt.ISODate)
                        note.reminder_shown = False
                    elif repeat == "weekends":
                        next_dt = reminder_time.addDays(1)
                        while next_dt.date().dayOfWeek() < 6:
                            next_dt = next_dt.addDays(1)
                        note.reminder = next_dt.toString(Qt.ISODate)
                        note.reminder_shown = False
                    elif repeat == "daily":
                        next_dt = reminder_time.addDays(1)
                        note.reminder = next_dt.toString(Qt.ISODate)
                        note.reminder_shown = False
                    elif repeat == "weekly":
                        next_dt = reminder_time.addDays(7)
                        note.reminder = next_dt.toString(Qt.ISODate)
                        note.reminder_shown = False
                    elif repeat == "minutely":
                        next_dt = reminder_time.addSecs(60)
                        note.reminder = next_dt.toString(Qt.ISODate)
                        note.reminder_shown = False
                    elif repeat == "hourly":
                        next_dt = reminder_time.addSecs(3600)
                        note.reminder = next_dt.toString(Qt.ISODate)
                        note.reminder_shown = False
                    else:
                        note.reminder = None
                        note.reminder_repeat = None

        if changed:
            self.save_all_notes_to_disk()
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
            self.current_note.reminder = dt.toString("yyyy-MM-dd HH:mm")
            repeat_option = repeat_combo.currentText()
            if repeat_option == "Однократно":
                self.current_note.reminder_repeat = None
            else:
                self.current_note.reminder_repeat = repeat_option
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
            self.current_note.reminder = dt.toString("yyyy-MM-dd HH:mm")
            selected = repeat_combo.currentText()
            self.current_note.reminder_repeat = (
                None if selected == "Однократно" else selected
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
        now = QDateTime.currentDateTime()
        for note in self.notes:
            if note.reminder:
                reminder_dt = QDateTime.fromString(note.reminder, "yyyy-MM-dd HH:mm")
                if -60 <= now.secsTo(reminder_dt) <= 60:
                    self.tray_icon.showMessage(
                        "Напоминание",
                        f"Заметка: {note.title}",
                        QSystemTrayIcon.Information,
                        10000,
                    )
                    self.show_reminder_popup(note)
                    if note.reminder_repeat == "Каждый день":
                        note.reminder = reminder_dt.addDays(1).toString(
                            "yyyy-MM-dd HH:mm"
                        )
                        self.save_note_to_file(note)
                    elif note.reminder_repeat == "По будням":
                        if reminder_dt.date().dayOfWeek() < 6:
                            note.reminder = reminder_dt.addDays(1).toString(
                                "yyyy-MM-dd HH:mm"
                            )
                        else:
                            days_to_monday = 8 - reminder_dt.date().dayOfWeek()
                            note.reminder = reminder_dt.addDays(
                                days_to_monday
                            ).toString("yyyy-MM-dd HH:mm")
                        self.save_note_to_file(note)
                    elif note.reminder_repeat == "Каждую неделю":
                        note.reminder = reminder_dt.addDays(7).toString(
                            "yyyy-MM-dd HH:mm"
                        )
                        self.save_note_to_file(note)
                    elif note.reminder_repeat == "Каждый месяц":
                        note.reminder = reminder_dt.addMonths(1).toString(
                            "yyyy-MM-dd HH:mm"
                        )
                        self.save_note_to_file(note)
                    else:
                        note.reminder = None
                        note.reminder_repeat = None
                        self.save_note_to_file(note)
                elif now > reminder_dt.addSecs(60):
                    note.reminder = None
                    self.save_note_to_file(note)
                    self.refresh_notes_list()

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
        self.reminder_timer.timeout.connect(self.check_upcoming_reminders)
        self.reminder_timer.start(60000)
