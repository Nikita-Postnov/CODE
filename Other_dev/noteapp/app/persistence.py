"""NotePersistenceMixin: файловый слой заметок.

Атомарная запись, сериализация/десериализация заметки, бэкапы и ротация,
порядок заметок (notes_order), чтение с диска и снапшот. Вырезано из NotesApp
(step 4.2). Апстрим-методы (_as_path, _note_folder_path, deduplicate_notes,
ensure_notes_directory) остаются в NotesApp и доступны через self в рантайме.
"""

import json
import logging
import os
import shutil
import time
import uuid
from pathlib import Path

from PySide6.QtGui import QTextDocument

from ..config import DATA_DIR, NOTES_DIR, NOTES_ORDER_PATH, qt_path
from ..models import Note


class NotePersistenceMixin:
    @staticmethod
    def _load_note_from_path(file_path: str) -> Note:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        try:
            current_mtime = os.path.getmtime(file_path)
        except Exception:
            current_mtime = None

        cache_path = os.path.join(os.path.dirname(file_path), "note_cache.json")
        if current_mtime is not None and os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as cf:
                    cache_data = json.load(cf)
                cached_mtime = cache_data.get("_note_mtime")
                if (
                    cached_mtime is not None
                    and float(cached_mtime) == float(current_mtime)
                    and isinstance(cache_data.get("note"), dict)
                ):
                    note_dict = cache_data.get("note")
                    note = Note.from_dict(note_dict)
                    note.content_txt = note_dict.get("content_txt", "") or ""
                    return note
            except Exception:
                pass

        note = Note.from_dict(data)
        note.content_txt = data.get("content_txt", "") or ""
        return note

    @staticmethod
    def read_notes_snapshot() -> list[Note]:
        if not os.path.exists(NOTES_DIR):
            os.makedirs(NOTES_DIR, exist_ok=True)
        notes_by_id: dict[str, Note] = {}
        for entry in os.scandir(NOTES_DIR):
            if not entry.is_dir():
                continue
            file_path = os.path.join(entry.path, "note.json")
            if not os.path.exists(file_path):
                continue
            try:
                note = NotePersistenceMixin._load_note_from_path(file_path)
            except Exception:
                continue
            notes_by_id[note.uuid] = note
        return list(notes_by_id.values())

    def save_note_to_specific_folder(self, note: "Note", folder: Path) -> None:
        note_folder = self._note_folder_path(note, folder)
        payload = self._note_to_payload(note)
        self._save_payload_to_folder(note_folder, payload, keep_backups=10)

    def _atomic_write_bytes(self, path: Path | str, data: bytes) -> None:
        path = self._as_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")

        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

        last_exc: Exception | None = None
        for _ in range(15):
            try:
                os.replace(tmp, path)
                return
            except PermissionError as exc:
                last_exc = exc
                time.sleep(0.05)

        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass

        if last_exc is not None:
            raise last_exc

    def _atomic_write_json(self, path: Path | str, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=4).encode("utf-8")
        self._atomic_write_bytes(path, data)

    def _rotate_backups(self, folder: Path | str, keep: int = 10) -> None:
        folder = self._as_path(folder)
        try:
            files: list[tuple[float, Path]] = []
            for p in folder.glob("note_backup_*.json"):
                try:
                    if p.is_file():
                        files.append((p.stat().st_mtime, p))
                except Exception:
                    continue
            files.sort(key=lambda t: t[0], reverse=True)
            for _, p in files[keep:]:
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception:
            pass

    def _load_note_json_with_recovery(self, note_folder: Path | str) -> dict | None:
        folder = self._as_path(note_folder)
        note_path = folder / "note.json"
        cache_path = folder / "note_cache.json"

        def _read_json(path: Path) -> dict:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)

        try:
            note_mtime = note_path.stat().st_mtime
        except Exception:
            note_mtime = None

        if note_mtime is not None and cache_path.exists():
            try:
                cached = _read_json(cache_path)
                if cached.get("_note_mtime") == note_mtime and isinstance(cached.get("note"), dict):
                    return cached.get("note")
            except Exception:
                pass

        try:
            data = _read_json(note_path)
            if note_mtime is not None:
                try:
                    self._atomic_write_json(cache_path, {"_note_mtime": note_mtime, "note": data})
                except Exception:
                    pass
            return data
        except Exception:
            pass

        backups: list[tuple[float, Path]] = []
        try:
            for p in folder.glob("note_backup_*.json"):
                try:
                    if p.is_file():
                        backups.append((p.stat().st_mtime, p))
                except Exception:
                    continue
            backups.sort(key=lambda t: t[0], reverse=True)
        except Exception:
            backups = []

        for _, p in backups[:5]:
            try:
                return _read_json(p)
            except Exception:
                continue

        tmp = folder / "note.json.tmp"
        if tmp.exists():
            try:
                return _read_json(tmp)
            except Exception:
                pass

        return None

    def load_notes_from_disk(self) -> None:
        self.notes = []
        notes_root = Path(self.notes_folder)
        notes_root.mkdir(parents=True, exist_ok=True)

        for note_folder in sorted((p for p in notes_root.iterdir() if p.is_dir()), key=lambda p: p.name):
            data = self._load_note_json_with_recovery(note_folder)
            if not isinstance(data, dict):
                continue
            try:
                note = Note.from_dict(data)
            except Exception:
                continue
            note.content_txt = data.get("content_txt", "")
            if note.uuid is None:
                note.uuid = str(uuid.uuid4())
            self.notes.append(note)

        self.deduplicate_notes()

    def _note_to_payload(self, note: "Note") -> dict:
        if self.current_note and note.uuid == self.current_note.uuid:
            note.content = self.text_edit.toHtml()

        payload = note.to_dict()
        if not note.reminder:
            payload.pop("reminder", None)

        try:
            doc = QTextDocument()
            if self.current_note and note.uuid == getattr(self, "current_note", None).uuid:
                doc.setHtml(self.text_edit.toHtml())
            else:
                doc.setHtml(note.content or "")
            payload["content_txt"] = doc.toPlainText()
        except Exception:
            payload["content_txt"] = payload.get("content_txt", "")

        return payload

    def _make_backup_if_exists(self, note_path: Path, keep: int = 10) -> None:
        if not note_path.exists():
            return
        try:
            folder = note_path.parent
            backup_name = f"note_backup_{int(time.time())}.json"
            backup_path = folder / backup_name
            shutil.copy2(note_path, backup_path)
            self._rotate_backups(folder, keep=keep)
        except Exception:
            logging.exception("Failed to create backup for %s", qt_path(note_path))

    def _write_note_cache_from_payload(self, note_path: Path, payload: dict) -> None:
        try:
            mtime = note_path.stat().st_mtime
        except Exception:
            mtime = None
        cache_path = note_path.parent / "note_cache.json"
        try:
            self._atomic_write_json(cache_path, {"_note_mtime": mtime, "note": payload})
        except Exception:
            pass

    def _save_payload_to_folder(self, note_folder: Path, payload: dict, keep_backups: int = 10) -> Path:
        note_folder.mkdir(parents=True, exist_ok=True)
        note_path = note_folder / "note.json"
        self._make_backup_if_exists(note_path, keep=keep_backups)
        self._atomic_write_json(note_path, payload)
        self._write_note_cache_from_payload(note_path, payload)
        return note_path

    def save_note_to_file(self, note: Note) -> None:
        self.save_note_to_specific_folder(note, NOTES_DIR)

    def save_all_notes_to_disk(self) -> None:
        self.ensure_notes_directory()
        unique_notes = {}
        for note in self.notes:
            unique_notes[note.uuid] = note
        self.notes = list(unique_notes.values())
        for note in self.notes:
            self.save_note_to_file(note)
        self.deduplicate_notes()

    def _load_notes_order(self) -> dict:
        path = str(NOTES_ORDER_PATH)
        try:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
                pinned = data.get("pinned") or []
                unpinned = data.get("unpinned") or []
                if isinstance(pinned, list) and isinstance(unpinned, list):
                    return {
                        "pinned": [str(x) for x in pinned],
                        "unpinned": [str(x) for x in unpinned],
                    }
        except Exception:
            pass
        return {"pinned": [], "unpinned": []}

    def _save_notes_order(self, pinned: list[str], unpinned: list[str]) -> None:
        try:
            os.makedirs(str(DATA_DIR), exist_ok=True)
            payload = {"pinned": list(pinned), "unpinned": list(unpinned)}
            # Атомарно, как и сами заметки: при сбое во время записи порядок
            # закреплённых заметок не обнулится.
            self._atomic_write_json(NOTES_ORDER_PATH, payload)
        except Exception:
            pass

    def _remove_uuid_from_notes_order(self, note_uuid: str) -> None:
        if not note_uuid:
            return
        order = self._load_notes_order()
        pinned = [u for u in (order.get("pinned") or []) if u != note_uuid]
        unpinned = [u for u in (order.get("unpinned") or []) if u != note_uuid]
        self._save_notes_order(pinned, unpinned)

