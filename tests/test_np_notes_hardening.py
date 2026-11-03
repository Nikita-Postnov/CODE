"""Регрессии переносимости, восстановления кэша и сохранности вложений."""
import ast
import importlib.util
import json
import logging
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
NOTES = ROOT / "Other_dev" / "noteapp"


def load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def recover_payload(folder: Path):
    source = NOTES / "app" / "persistence.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    cls = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "NotePersistenceMixin"
    )
    method = next(
        node for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "_recover_note_payload"
    )
    fake_class = types.SimpleNamespace(
        _atomic_write_json_static=lambda *args: None
    )
    namespace = {
        "Path": Path,
        "json": json,
        "logging": logging,
        "NotePersistenceMixin": fake_class,
    }
    compiled = ast.fix_missing_locations(
        ast.Module(body=[method], type_ignores=[])
    )
    exec(compile(compiled, str(source), "exec"), namespace)
    return namespace["_recover_note_payload"](folder)


class PortableChoicePathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cfg = load_module("np_note_config_safety", NOTES / "config.py")

    def test_choice_pythonw_without_exe_is_recognized(self):
        (self.root / "Choice.pyw").write_text("", encoding="utf-8")
        self.assertTrue(self.cfg._is_launcher_dir(self.root))
        (self.root / "Data").mkdir()
        with patch.dict(os.environ, {"LAUNCHER_ROOT": str(self.root / "Data")}):
            self.assertEqual(self.cfg.launcher_root(), self.root.resolve())

    def test_choice_batch_without_exe_is_recognized(self):
        (self.root / "Choice.bat").write_text("", encoding="utf-8")
        self.assertTrue(self.cfg._is_launcher_dir(self.root))

    def test_ordinary_directory_is_not_misidentified(self):
        self.assertFalse(self.cfg._is_launcher_dir(self.root))


class RecoveryCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.note_path = self.folder / "note.json"
        self.note_path.write_text("{corrupt", encoding="utf-8")

    def write_cache(self, *, mtime=None, note=None):
        payload = {
            "_note_mtime": self.note_path.stat().st_mtime if mtime is None else mtime,
            "note": {"title": "Восстановленная", "content": "Текст"} if note is None else note,
        }
        (self.folder / "note_cache.json").write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_valid_cache_envelope_recovers_when_main_json_is_corrupted(self):
        self.write_cache()
        restored = recover_payload(self.folder)
        self.assertEqual(restored["title"], "Восстановленная")
        self.assertEqual(restored["content"], "Текст")
        self.assertEqual(self.note_path.read_text(encoding="utf-8"), "{corrupt")

    def test_stale_cache_does_not_mask_valid_backup(self):
        self.write_cache(mtime=self.note_path.stat().st_mtime - 2)
        (self.folder / "note_backup_1.json").write_text(
            json.dumps({"title": "Из резервной копии"}, ensure_ascii=False),
            encoding="utf-8",
        )
        self.assertEqual(
            recover_payload(self.folder)["title"], "Из резервной копии"
        )

    def test_malformed_cache_note_does_not_hide_valid_backup(self):
        self.write_cache(note={"content": "Без заголовка"})
        (self.folder / "note_backup_2.json").write_text(
            json.dumps({"title": "Запасная копия"}, ensure_ascii=False),
            encoding="utf-8",
        )
        self.assertEqual(
            recover_payload(self.folder)["title"], "Запасная копия"
        )


class AttachmentSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.target = self.root / "notes"
        self.source.mkdir()
        self.target.mkdir()
        self.module = load_module(
            "np_note_attachment_safety", NOTES / "attachments.py"
        )

    def test_duplicate_names_preserve_every_version(self):
        original = self.source / "file.txt"
        original.write_text("first", encoding="utf-8")
        one = self.module.copy_attachment_without_overwrite(original, self.target)
        original.write_text("second", encoding="utf-8")
        two = self.module.copy_attachment_without_overwrite(original, self.target)
        original.write_text("third", encoding="utf-8")
        three = self.module.copy_attachment_without_overwrite(original, self.target)

        self.assertEqual([p.name for p in (one, two, three)],
                         ["file.txt", "file (1).txt", "file (2).txt"])
        self.assertEqual([p.read_text(encoding="utf-8") for p in (one, two, three)],
                         ["first", "second", "third"])

    def test_source_inside_same_folder_is_copied_to_new_name(self):
        original = self.target / "same.pdf"
        original.write_bytes(b"original bytes")
        copied = self.module.copy_attachment_without_overwrite(
            original, self.target
        )
        self.assertEqual(copied.name, "same (1).pdf")
        self.assertEqual(original.read_bytes(), copied.read_bytes())

    def test_failure_does_not_leave_partial_attachment(self):
        original = self.source / "copy.txt"
        original.write_text("content", encoding="utf-8")
        with patch.object(
            self.module.shutil, "copyfileobj",
            side_effect=OSError("Диск недоступен"),
        ):
            with self.assertRaises(OSError):
                self.module.copy_attachment_without_overwrite(
                    original, self.target
                )
        self.assertEqual(list(self.target.iterdir()), [])
        self.assertEqual(original.read_text(encoding="utf-8"), "content")

    def test_note_drop_handler_uses_safe_copy_and_escapes_html(self):
        code = (NOTES / "app" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("copy_attachment_without_overwrite(source, folder)", code)
        self.assertIn("safe_url = escape_html(file_url, quote=True)", code)
        self.assertIn("safe_name = escape_html(filename)", code)
        self.assertNotIn("shutil.copy(file_path, dest)", code)


if __name__ == "__main__":
    unittest.main()
