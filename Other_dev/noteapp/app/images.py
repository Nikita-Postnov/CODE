"""ImagesMixin: изображения и вложения — панель вложений, прикрепление файлов,
вставка картинок (файл/буфер/рисование), слежение за буфером обмена.

Вырезано из NotesApp (step 4.11). safe_folder_name — свободная функция из utils
Апстрим-методы (save_note, save_note_quiet,
record_state_for_undo, _safe_restore_cursor, _ensure_typing_defaults,
_apply_dynamic_tokens, update_note_layout_counter) остаются в NotesApp.
"""

import base64
import os
import re
import shutil
import uuid
from urllib.parse import quote

from PySide6.QtCore import (
    QBuffer,
    QDateTime,
    QFileSystemWatcher,
    QIODevice,
    QTimer,
    QUrl,
    Qt,
)
from PySide6.QtGui import (
    QCursor,
    QFont,
    QImage,
    QPixmap,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStyle,
    QToolTip,
    QWidget,
)

from ..config import FILE_ICON_PATH, NOTES_DIR, qt_path
from ..constants import ATTACH_FILE_FILTER, IMAGE_EXTENSIONS
from ..models import Note
from ..utils import safe_folder_name
from ..widgets.drawing import DrawingDialog


class ImagesMixin:
    def _init_clipboard_watch(self) -> None:
        if getattr(self, "_clipboard_connected", False):
            return
        if not getattr(self, "_clipboard_watch_enabled", True):
            return

        try:
            cb = QApplication.clipboard()
            cb.dataChanged.connect(self._on_clipboard_changed)
            self._clipboard_connected = True
        except Exception:
            self._clipboard_connected = False

    def copy_password_manager_to_clipboard(self) -> None:
        text = self.password_manager_field.text().strip()
        if not text:
            QToolTip.showText(QCursor.pos(), "Поле пустое")
            return
        QApplication.clipboard().setText(text)
        self.show_toast(
            "Скопировано",
            boundary_widget=self.dock_editor.widget(),
            anchor_widget=self.password_manager_copy_btn,
        )

    def copy_custom_field_to_clipboard(self, edit: QLineEdit, btn: QPushButton) -> None:
        text = edit.text().strip()
        if not text:
            QToolTip.showText(QCursor.pos(), "Поле пустое")
            return
        QApplication.clipboard().setText(text)
        self.show_toast(
            "Скопировано",
            boundary_widget=self.dock_editor.widget(),
            anchor_widget=btn,
        )

    def _detach_attachments_watcher(self, extra_paths: list[str] | None = None) -> None:
        try:
            if not hasattr(self, "attachments_watcher") or not self.attachments_watcher:
                return
            files = list(self.attachments_watcher.files() or [])
            dirs = list(self.attachments_watcher.directories() or [])
            to_remove = files + dirs
            if extra_paths:
                to_remove.extend(extra_paths)

            to_remove = [p for p in to_remove if p]

            if to_remove:
                self.attachments_watcher.removePaths(list(set(to_remove)))
        except Exception:
            pass

    def _list_attachment_files(self, note: Note | None) -> list[tuple[str, str]]:
        if not note:
            return []
        note_dir = os.path.join(
            NOTES_DIR, safe_folder_name(note.title, note.uuid, note.timestamp)
        )
        if not os.path.isdir(note_dir):
            return []
        ignored_files = {
            "note.json",
            "note_cache.json",
            "note_backup.json",
            ".DS_Store",
            "Thumbs.db",
            "desktop.ini",
        }
        ignored_prefixes = ("~$", ".~")
        ignored_suffixes = ("~", ".tmp", ".temp", ".bak")
        attachments: list[tuple[str, str]] = []
        for filename in os.listdir(note_dir):
            if (
                filename in ignored_files
                or filename.startswith(ignored_prefixes)
                or filename.endswith(ignored_suffixes)
                or filename.startswith("note_backup_")
                or (filename.startswith("backup(") and filename.endswith(".json"))
            ):
                continue
            attachments.append((filename, os.path.join(note_dir, filename)))
        return attachments

    def show_note_with_attachments(self, note: "Note | None") -> None:
        self.current_note = note
        self._attachments_render_token = getattr(self, "_attachments_render_token", 0) + 1
        token = self._attachments_render_token
        if not note:
            if hasattr(self, "attachments_scroll") and self.attachments_scroll:
                self.attachments_scroll.setVisible(False)
            if hasattr(self, "add_field_btn"):
                self.add_field_btn.setEnabled(False)
                self.add_field_btn.setVisible(False)
            self.text_edit.blockSignals(True)
            self.text_edit.clear()
            self.text_edit.blockSignals(False)
            self.update_note_layout_counter()
            if hasattr(self, "attachments_layout"):
                for i in reversed(range(self.attachments_layout.count())):
                    w = self.attachments_layout.itemAt(i).widget()
                    if w:
                        w.setParent(None)
                        w.deleteLater()
            if hasattr(self, "tags_label"):
                self.tags_label.setText("Теги: нет")
            return
        if hasattr(self, "add_field_btn"):
            self.add_field_btn.setVisible(True)
            self.add_field_btn.setEnabled(True)
        self.settings.setValue("lastNoteUuid", note.uuid)
        cursor_pos = None
        anchor_pos = None
        try:
            cursor = self.text_edit.textCursor()
            cursor_pos = cursor.position()
            anchor_pos = cursor.anchor()
        except Exception:
            pass
        raw_html = (
            note.content_html
            if hasattr(note, "content_html") and note.content_html
            else note.content
        )
        self.settings.setValue("ui/lastOpenedNote", getattr(self, "current_note_path", ""))
        rendered = self._apply_dynamic_tokens(raw_html)
        self.text_edit.blockSignals(True)
        self.text_edit.setHtml(rendered)
        self.text_edit.document().setDefaultFont(QFont("Times New Roman", 14))
        self.text_edit.blockSignals(False)

        self.update_note_layout_counter()
        if cursor_pos is not None and anchor_pos is not None:
            self._safe_restore_cursor(anchor_pos, cursor_pos)
        self._ensure_typing_defaults()
        if hasattr(self, "_dropdown_tokens"):
            self._dropdown_tokens.clear()
        attachments = self._list_attachment_files(note)
        self._attachments_snapshot[note.uuid] = {name for name, _ in attachments}
        if hasattr(self, "attachments_layout"):
            for i in reversed(range(self.attachments_layout.count())):
                w = self.attachments_layout.itemAt(i).widget()
                if w:
                    w.setParent(None)
                    w.deleteLater()
            if not attachments:
                if hasattr(self, "attachments_scroll") and self.attachments_scroll:
                    self.attachments_scroll.setVisible(False)
            else:
                loading_lbl = QLabel("Вложения загружаются…")
                loading_lbl.setObjectName("_attachments_loading_label")
                self.attachments_layout.addWidget(loading_lbl)
                note_dir_path = NOTES_DIR / safe_folder_name(note.title, note.uuid, note.timestamp)
                note_dir = qt_path(note_dir_path)
                try:
                    if self.attachments_watcher is None:
                        self.attachments_watcher = QFileSystemWatcher(self)
                        self.attachments_watcher.directoryChanged.connect(self._refresh_attachments)
                        self.attachments_watcher.fileChanged.connect(self._refresh_attachments)

                    if note_dir and note_dir_path.is_dir() and note_dir not in self.attachments_watcher.directories():
                        self.attachments_watcher.addPath(note_dir)
                except Exception:
                    pass
                if hasattr(self, "attachments_scroll") and self.attachments_scroll:
                    self.attachments_scroll.setVisible(True)
                state = {"i": 0}
                def _render_batch() -> None:
                    if getattr(self, "_attachments_render_token", None) != token:
                        return
                    if not getattr(self, "current_note", None) or self.current_note.uuid != note.uuid:
                        return
                    if not hasattr(self, "attachments_layout") or not self.attachments_layout:
                        return
                    if state["i"] == 0:
                        for j in reversed(range(self.attachments_layout.count())):
                            w = self.attachments_layout.itemAt(j).widget()
                            if isinstance(w, QLabel) and w.objectName() == "_attachments_loading_label":
                                w.setParent(None)
                                w.deleteLater()
                    batch = 5
                    added = 0
                    while state["i"] < len(attachments) and added < batch:
                        filename, file_path = attachments[state["i"]]
                        state["i"] += 1
                        added += 1
                        item_widget = QWidget()
                        layout = QHBoxLayout(item_widget)
                        layout.setContentsMargins(0, 0, 0, 0)
                        layout.setSpacing(6)
                        item_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                        if filename.lower().endswith(tuple(IMAGE_EXTENSIONS)):
                            pixmap = QPixmap(file_path)
                            icon_label = QLabel()
                            if not pixmap.isNull():
                                icon_label.setPixmap(
                                    pixmap.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                                )
                            else:
                                icon_label.setPixmap(self.style().standardIcon(QStyle.SP_FileIcon).pixmap(32, 32))
                            layout.addWidget(icon_label)
                        else:
                            icon_label = QLabel()
                            if FILE_ICON_PATH.exists():
                                icon_label.setPixmap(
                                    QPixmap(qt_path(FILE_ICON_PATH)).scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                                )
                            else:
                                icon_label.setPixmap(self.style().standardIcon(QStyle.SP_FileIcon).pixmap(32, 32))
                            layout.addWidget(icon_label)
                        label = QLabel(filename)
                        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                        label.setWordWrap(False)
                        label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
                        label.setMinimumWidth(label.sizeHint().width())
                        layout.addWidget(label)
                        open_btn = QPushButton("Открыть")
                        open_btn.setToolTip("Открыть вложение")
                        open_btn.setFixedSize(60, 24)
                        open_btn.clicked.connect(lambda _, path=file_path: self.text_edit._open_any_link(path))
                        layout.addWidget(open_btn)
                        del_btn = QPushButton("❌")
                        del_btn.setToolTip("Удалить вложение")
                        del_btn.setFixedSize(28, 24)
                        del_btn.clicked.connect(lambda _, path=file_path: self.delete_attachment_from_panel(path))
                        layout.addWidget(del_btn)
                        item_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                        if self.attachments_layout.count() > 0:
                            sep_lbl = QLabel(" - ")
                            sep_lbl.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                            self.attachments_layout.addWidget(sep_lbl)
                        self.attachments_layout.addWidget(item_widget)
                    if state["i"] < len(attachments):
                        QTimer.singleShot(0, _render_batch)
                QTimer.singleShot(0, _render_batch)
        if hasattr(self, "tags_label"):
            self.tags_label.setText(f"Теги: {', '.join(note.tags) if note.tags else 'нет'}")

    def _refresh_attachments(self, *args) -> None:
        if not self.current_note:
            return
        if args:
            changed_path = (args[0] or "").lower()
            ignored_files = {
                "note.json",
                "note_cache.json",
                "note_backup.json",
                "desktop.ini",
                "thumbs.db",
            }
            ignored_prefixes = ("~$", ".~")
            ignored_suffixes = ("~", ".tmp", ".temp", ".bak")
            basename = os.path.basename(changed_path)
            if (
                basename in ignored_files
                or basename.startswith("note_cache_")
                or basename.startswith("note_backup_")
                or (basename.startswith("backup(") and basename.endswith(".json"))
                or basename.startswith(ignored_prefixes)
                or basename.endswith(ignored_suffixes)
            ):
                return
        attachments = self._list_attachment_files(self.current_note)
        filenames = {name for name, _ in attachments}
        if filenames == self._attachments_snapshot.get(self.current_note.uuid, set()):
            return
        self._rebuild_attachments_panel(self.current_note, attachments)

    def delete_attachment_from_panel(self, file_path: str) -> None:
        reply = QMessageBox.question(
            self,
            "Удалить вложение",
            f"Удалить вложение '{os.path.basename(file_path)}'?\nФайл будет удалён безвозвратно.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            b64_data = None
            if file_path.lower().endswith(tuple(IMAGE_EXTENSIONS)):
                try:
                    pixmap = QPixmap(file_path)
                    if not pixmap.isNull():
                        buffer = QBuffer()
                        buffer.open(QIODevice.WriteOnly)
                        pixmap.save(buffer, "PNG")
                        b64_data = base64.b64encode(buffer.data()).decode("utf-8")
                except Exception:
                    b64_data = None
            try:
                os.remove(file_path)
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", f"Не удалось удалить файл:\n{e}")
            if self.current_note:
                file_path_abs = os.path.abspath(file_path)
                urls = {
                    QUrl.fromLocalFile(file_path_abs).toString(),
                    "file:///" + quote(file_path_abs.replace(os.sep, "/")),
                }
                html = self.text_edit.toHtml()
                for url in urls:
                    esc = re.escape(url)
                    html = re.sub(
                        rf"(<br>\s*)*(?:📄\s*)?<a[^>]+href=\"{esc}\"[^>]*>.*?</a>(<br>\s*)*",
                        "",
                        html,
                        flags=re.IGNORECASE,
                    )
                    html = re.sub(
                        rf"(<br>\s*)*<img[^>]+src=\"{esc}\"[^>]*>(<br>\s*)*",
                        "",
                        html,
                        flags=re.IGNORECASE,
                    )
                if b64_data:
                    esc_b64 = re.escape(b64_data)
                    html = re.sub(
                        rf"(<br>\s*)*<img[^>]+src=\"data:image/[^;]+;base64,{esc_b64}\"[^>]*>(<br>\s*)*",
                        "",
                        html,
                        flags=re.IGNORECASE,
                    )
                self.text_edit.blockSignals(True)
                self.text_edit.setHtml(html)
                self.text_edit.blockSignals(False)
                self.save_note_quiet(force=True)
                self._rebuild_attachments_panel(self.current_note)

    def attach_file_to_note(self) -> None:
        if not self.current_note:
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Прикрепить файл",
            "",
            ATTACH_FILE_FILTER,
        )
        if not file_path:
            return
        note_dir = os.path.join(
            NOTES_DIR,
            safe_folder_name(
                self.current_note.title,
                self.current_note.uuid,
                self.current_note.timestamp,
            ),
        )
        os.makedirs(note_dir, exist_ok=True)
        filename = os.path.basename(file_path)
        dest = os.path.join(note_dir, filename)
        try:
            shutil.copy(file_path, dest)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось скопировать файл: {e}")
            return
        is_image = filename.lower().endswith(tuple(IMAGE_EXTENSIONS))
        cursor = self.text_edit.textCursor()
        self.text_edit.setTextCursor(cursor)
        if is_image:
            pixmap = QPixmap(dest)
            if not pixmap.isNull():
                buffer = QBuffer()
                buffer.open(QIODevice.WriteOnly)
                pixmap.save(buffer, "PNG")
                base64_data = base64.b64encode(buffer.data()).decode("utf-8")
                html_img = (
                    f'<img src="Data:image/png;base64,{base64_data}" width="200"><br>'
                )
                self.text_edit.insertHtml(html_img)
                self.record_state_for_undo()
            else:
                QMessageBox.warning(
                    self, "Ошибка", f"Не удалось открыть изображение: {filename}"
                )
        else:
            file_url = QUrl.fromLocalFile(os.path.abspath(dest)).toString()
            self.text_edit.insertHtml(f'📄 <a href="{file_url}">{filename}</a>')
        self.show_toast("Файл прикреплён к заметке.")
        self.save_note_quiet(force=True)
        self._rebuild_attachments_panel(self.current_note)

    def attach_file_to_note_external(self, file_path: str) -> None:
        if not self.current_note:
            return
        note_dir = os.path.join(
            NOTES_DIR,
            safe_folder_name(
                self.current_note.title,
                self.current_note.uuid,
                self.current_note.timestamp,
            ),
        )
        os.makedirs(note_dir, exist_ok=True)
        filename = os.path.basename(file_path)
        dest = os.path.join(note_dir, filename)
        try:
            shutil.copy(file_path, dest)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось скопировать файл: {e}")
            return
        is_image = filename.lower().endswith(tuple(IMAGE_EXTENSIONS))
        cursor = self.text_edit.textCursor()
        self.text_edit.setTextCursor(cursor)
        if is_image:
            pixmap = QPixmap(dest)
            if not pixmap.isNull():
                buffer = QBuffer()
                buffer.open(QIODevice.WriteOnly)
                pixmap.save(buffer, "PNG")
                base64_data = base64.b64encode(buffer.data()).decode("utf-8")
                html_img = (
                    f'<img src="Data:image/png;base64,{base64_data}" width="200"><br>'
                )
                self.text_edit.insertHtml(html_img)
                self.record_state_for_undo()
            else:
                QMessageBox.warning(
                    self, "Ошибка", f"Не удалось открыть изображение: {filename}"
                )
        else:
            file_url = QUrl.fromLocalFile(os.path.abspath(dest)).toString()
            self.text_edit.insertHtml(f'📄 <a href="{file_url}">{filename}</a>')
        self.show_toast("Файл прикреплён к заметке.")
        self.save_note_quiet(force=True)
        self._rebuild_attachments_panel(self.current_note)

    def _toggle_clipboard_layout_watch(self, enabled: bool) -> None:
        self._clipboard_watch_enabled = bool(enabled)
        self.settings.setValue(
            "layout/clipboard_auto_convert", self._clipboard_watch_enabled
        )
        if not self._clipboard_watch_enabled:
            self._last_clipboard_text = ""

    def _on_clipboard_changed(self) -> None:
        return

    def insert_image_html(
        self, html_img: str, replace_current: bool = False, orig_path: str | None = None
    ) -> None:
        doc = self.text_edit.document()
        cursor = QTextCursor(doc)
        replaced = False
        while not cursor.isNull() and not cursor.atEnd():
            if cursor.charFormat().isImageFormat():
                img_format = cursor.charFormat().toImageFormat()
                if orig_path and (
                    img_format.name() == orig_path
                    or (
                        img_format.name().startswith("Data:image")
                        and orig_path.startswith("Data:image")
                    )
                ):
                    cursor.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, 1)
                    cursor.insertHtml(html_img)
                    replaced = True
                    break
            cursor.movePosition(QTextCursor.NextCharacter)
        if not replaced:
            insert_cursor = self.text_edit.textCursor()
            insert_cursor.movePosition(QTextCursor.End)
            self.text_edit.setTextCursor(insert_cursor)
            self.text_edit.insertHtml(html_img)
            self.record_state_for_undo()

    def insert_image_into_note(self, image_path: str) -> None:
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            pixmap.save(buffer, "PNG")
            base64_data = base64.b64encode(buffer.data()).decode("utf-8")
            html_img = (
                f'<img src="Data:image/png;base64,{base64_data}" width="300"><br>'
            )
            cursor = self.text_edit.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.text_edit.setTextCursor(cursor)
            self.text_edit.insertHtml(html_img)
            self.record_state_for_undo()

    def _insert_image_at_cursor(self, image_path: str, width: int = 400) -> None:
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            QMessageBox.warning(self, "Ошибка", "Не удалось загрузить изображение.")
            return
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        pixmap.save(buffer, "PNG")
        base64_data = base64.b64encode(buffer.data()).decode("utf-8")
        html_img = (
            f'<img src="Data:image/png;base64,{base64_data}" width="{width}"><br>'
        )
        cursor = self.text_edit.textCursor()
        self.text_edit.setTextCursor(cursor)
        self.text_edit.insertHtml(html_img)
        self.record_state_for_undo()

    def open_drawing_dialog(self) -> None:
        if not self.current_note:
            QMessageBox.warning(
                self, "Нет заметки", "Пожалуйста, выбери или создай заметку."
            )
            return

        dlg = DrawingDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            img = dlg.get_image()

            note_dir = os.path.join(
                NOTES_DIR,
                safe_folder_name(
                    self.current_note.title,
                    self.current_note.uuid,
                    self.current_note.timestamp,
                ),
            )
            os.makedirs(note_dir, exist_ok=True)

            default_base = (
                f"рисунок_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}"
            )
            name, ok = QInputDialog.getText(
                self,
                "Имя рисунка",
                "Имя файла (без расширения):",
                QLineEdit.EchoMode.Normal,
                default_base,
            )
            if not ok:
                return
            base = (name or "").strip()
            if not base:
                base = default_base
            base = re.sub(r"[^a-zA-Zа-яА-Я0-9 _\-\.\(\)]", "_", base).strip(" ._")
            if not base:
                base = default_base
            filename = base if base.lower().endswith(".png") else base + ".png"
            filepath = os.path.join(note_dir, filename)
            if os.path.exists(filepath):
                stem, ext = os.path.splitext(filename)
                i = 1
                while os.path.exists(os.path.join(note_dir, f"{stem}_{i}{ext}")):
                    i += 1
                filepath = os.path.join(note_dir, f"{stem}_{i}{ext}")
            try:
                img.save(filepath, "PNG")
            except Exception as e:
                QMessageBox.critical(
                    self, "Ошибка", f"Не удалось сохранить рисунок:\n{e}"
                )
                return
            self._insert_image_at_cursor(filepath, width=400)
            self.save_note()
            self._rebuild_attachments_panel(self.current_note)

    def insert_image_from_clipboard(self, image: QImage) -> None:
        if not self.current_note:
            QMessageBox.warning(
                self, "Нет заметки", "Пожалуйста, выберите или создайте заметку."
            )
            return
        note_dir = os.path.join(
            NOTES_DIR,
            safe_folder_name(
                self.current_note.title,
                self.current_note.uuid,
                self.current_note.timestamp,
            ),
        )
        os.makedirs(note_dir, exist_ok=True)
        filename = f"clipboard_{uuid.uuid4().hex}.png"
        filepath = os.path.join(note_dir, filename)
        try:
            if not image.save(filepath):
                raise RuntimeError("QImage.save вернул False")
        except Exception as e:
            QMessageBox.critical(
                self, "Ошибка", f"Не удалось сохранить изображение: {e}"
            )
            return
        self._insert_image_at_cursor(filepath, width=200)
        self.save_note()

    def _rebuild_attachments_panel(
        self,
        note: Note | None,
        attachments: list[tuple[str, str]] | None = None,
    ) -> None:
        if hasattr(self, "attachments_layout"):
            for i in reversed(range(self.attachments_layout.count())):
                w = self.attachments_layout.itemAt(i).widget()
                if w:
                    w.setParent(None)
                    w.deleteLater()
        if not note:
            if hasattr(self, "attachments_scroll") and self.attachments_scroll:
                self.attachments_scroll.setVisible(False)
            return
        attachments = attachments or self._list_attachment_files(note)
        self._attachments_snapshot[note.uuid] = {name for name, _ in attachments}
        attachments_found = False
        for filename, file_path in attachments:
            attachments_found = True
            item_widget = QWidget()
            layout = QHBoxLayout(item_widget)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(6)
            item_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            icon_label = QLabel()
            if filename.lower().endswith(tuple(IMAGE_EXTENSIONS)):
                pixmap = QPixmap(file_path)
                icon_label.setPixmap(
                    pixmap.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
            else:
                if FILE_ICON_PATH.exists():
                    icon_label.setPixmap(
                        QPixmap(qt_path(FILE_ICON_PATH)).scaled(
                            48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation
                        )
                    )
                else:
                    icon_label.setPixmap(
                        self.style().standardIcon(QStyle.SP_FileIcon).pixmap(32, 32)
                    )
            layout.addWidget(icon_label)
            label = QLabel(filename)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setWordWrap(False)
            label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            label.setMinimumWidth(label.sizeHint().width())
            layout.addWidget(label)
            open_btn = QPushButton("Открыть")
            open_btn.setToolTip("Открыть вложение")
            open_btn.setFixedSize(60, 24)
            open_btn.clicked.connect(
                lambda _, path=file_path: self.text_edit._open_any_link(path)
            )
            layout.addWidget(open_btn)
            del_btn = QPushButton("❌")
            del_btn.setToolTip("Удалить вложение")
            del_btn.setFixedSize(28, 24)
            del_btn.clicked.connect(
                lambda _, path=file_path: self.delete_attachment_from_panel(path)
            )
            layout.addWidget(del_btn)
            self.attachments_layout.addWidget(item_widget)
        if hasattr(self, "attachments_scroll") and self.attachments_scroll:
            self.attachments_scroll.setVisible(attachments_found)

    def attach_docks(self, dock1, dock2):
        area = self.dockWidgetArea(dock1)
        self.addDockWidget(area, dock2)
        self.tabifyDockWidget(dock1, dock2)
        dock2.show()
        dock1.raise_()

    def list_attachments_for_current_note(self):
        if not self.current_note:
            return
        if hasattr(self, "_rebuild_attachments_panel"):
            self._rebuild_attachments_panel(self.current_note)
