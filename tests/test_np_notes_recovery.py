"""Recovery draft encryption tests. Never opens real user files."""
import ast
from pathlib import Path
import importlib.util
import os
import tempfile
import unittest
from uuid import uuid4

FILE = Path(__file__).resolve().parents[1] / "Other_dev" / "noteapp" / "recovery.py"
SPEC = importlib.util.spec_from_file_location("npcore_note_recovery", FILE)
REC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REC)


class DraftSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.note_uuid = str(uuid4())

    def test_reject_unsafe_id_without_creating_directories(self):
        for bad in ("../Data", "/tmp/x", "not-a-uuid", ""):
            with self.assertRaises(ValueError):
                REC.draft_path(self.folder, bad)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_successful_save_clears_draft_only_after_commit(self):
        persistence = FILE.parent / "app" / "persistence.py"
        tree = ast.parse(persistence.read_text(encoding="utf-8"))
        cls = next(node for node in tree.body
                   if isinstance(node, ast.ClassDef) and node.name == "NotePersistenceMixin")
        method = next(node for node in cls.body
                      if isinstance(node, ast.FunctionDef) and node.name == "save_note_to_file")
        module = ast.Module(body=[method], type_ignores=[])
        ast.fix_missing_locations(module)
        namespace = {"NOTES_DIR": object(), "Note": object}
        exec(compile(module, "<persistence-clear-draft>", "exec"), namespace)
        class Note:
            uuid = "test"
        class Owner:
            called = False
            cleared = False
            def save_note_to_specific_folder(self, note, folder):
                self.called = True
                if getattr(self, "fail", False):
                    raise OSError("disk full")
            def _clear_recovery_snapshot(self, uuid):
                self.cleared = True
        owner = Owner()
        owner.fail = True
        with self.assertRaises(OSError):
            namespace["save_note_to_file"](owner, Note())
        self.assertFalse(owner.cleared)
        owner.fail = False
        namespace["save_note_to_file"](owner, Note())
        self.assertTrue(owner.called)
        self.assertTrue(owner.cleared)

    def test_snapshot_refuses_mismatched_note_uuid(self):
        file = FILE.parent / "app" / "recovery.py"
        tree = ast.parse(file.read_text(encoding="utf-8"))
        cls = next(node for node in tree.body
                   if isinstance(node, ast.ClassDef) and node.name == "RecoveryMixin")
        method = next(node for node in cls.body
                      if isinstance(node, ast.FunctionDef) and node.name == "_write_recovery_snapshot")
        module = ast.Module(body=[method], type_ignores=[])
        ast.fix_missing_locations(module)
        called = []
        namespace = {"save_draft": lambda *args: called.append(args),
                     "RECOVERY_DIR": self.folder,
                     "logging": __import__("logging")}
        exec(compile(module, "<recovery-write>", "exec"), namespace)
        class Note:
            uuid = "current"
        class Fake:
            current_note = Note()
            _recovery_snapshot_note_uuid = "previous"
            text_edit = None
        namespace["_write_recovery_snapshot"](Fake())
        self.assertEqual(called, [])

    @unittest.skipUnless(os.name == "nt", "Recovery prompt runs on Windows")
    def test_recovery_decline_discards_only_the_test_draft(self):
        import logging
        from types import SimpleNamespace
        source = FILE.parent / "app" / "recovery.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        cls = next(node for node in tree.body
                   if isinstance(node, ast.ClassDef) and node.name == "RecoveryMixin")
        method = next(node for node in cls.body
                      if isinstance(node, ast.FunctionDef) and node.name == "_offer_recovery_snapshots")
        module = ast.Module(body=[method], type_ignores=[])
        ast.fix_missing_locations(module)
        note = SimpleNamespace(uuid=self.note_uuid, title="Example", content="Saved")
        deleted = []
        class MessageBox:
            Yes, No, Cancel = 1, 2, 4
            @classmethod
            def question(cls, *args):
                return cls.No
        ns = {
            "os": os, "logging": logging, "RECOVERY_DIR": self.folder,
            "list_drafts": lambda directory: [self.note_uuid],
            "read_draft": lambda directory, uuid: {"html": "Unsaved"},
            "clear_draft": lambda directory, uuid: deleted.append(uuid),
            "QMessageBox": MessageBox,
        }
        exec(compile(module, "<recovery-dialog>", "exec"), ns)
        class Fake:
            notes = [note]
            current_note = None
            def isWindowModified(self):
                return False
            def _clear_recovery_snapshot(self, uuid):
                deleted.append(uuid)
        ns["_offer_recovery_snapshots"](Fake())
        self.assertEqual(deleted, [self.note_uuid])
        self.assertEqual(note.content, "Saved")

    @unittest.skipUnless(os.name == "nt", "Recovery prompt runs on Windows")
    def test_recovery_acceptance_saves_only_selected_existing_note(self):
        import logging
        from types import SimpleNamespace
        source = FILE.parent / "app" / "recovery.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        cls = next(node for node in tree.body
                   if isinstance(node, ast.ClassDef) and node.name == "RecoveryMixin")
        method = next(node for node in cls.body
                      if isinstance(node, ast.FunctionDef) and node.name == "_offer_recovery_snapshots")
        module = ast.Module(body=[method], type_ignores=[])
        ast.fix_missing_locations(module)
        note = SimpleNamespace(uuid=self.note_uuid, title="Example", content="Saved")
        removed = []
        class MessageBox:
            Yes, No, Cancel = 1, 2, 4
            @classmethod
            def question(cls, *args):
                return cls.Yes
            @classmethod
            def warning(cls, *args):
                raise AssertionError("Unexpected recovery warning")
        class Item:
            def data(self, role):
                return note
        class List:
            def count(self):
                return 1
            def item(self, index):
                return Item()
            def setCurrentItem(self, item):
                pass
        class Edit:
            html = None
            def setHtml(self, html):
                self.html = html
        ns = {
            "os": os, "logging": logging, "RECOVERY_DIR": self.folder,
            "list_drafts": lambda directory: [self.note_uuid],
            "read_draft": lambda directory, uuid: {"html": "Unsaved"},
            "QMessageBox": MessageBox,
            "Qt": SimpleNamespace(UserRole=32),
        }
        exec(compile(module, "<recovery-dialog-accept>", "exec"), ns)
        class Fake:
            notes = [note]
            current_note = None
            notes_list = List()
            text_edit = Edit()
            def isWindowModified(self):
                return False
            def _set_unsaved(self, dirty):
                self.dirty = dirty
            def load_note(self, item):
                self.current_note = note
            def save_note_quiet(self, *, force):
                if not force:
                    raise AssertionError("Recovery save must be explicit")
                note.content = self.text_edit.html
            def _clear_recovery_snapshot(self, uuid):
                removed.append(uuid)
        fake = Fake()
        ns["_offer_recovery_snapshots"](fake)
        self.assertEqual(note.content, "Unsaved")
        self.assertTrue(fake.dirty)
        self.assertEqual(removed, [self.note_uuid])

    def test_missing_draft_returns_none(self):
        self.assertIsNone(REC.read_draft(self.folder, self.note_uuid))
        self.assertEqual(REC.list_drafts(self.folder), [])

    @unittest.skipUnless(os.name == "nt", "DPAPI is Windows-only")
    def test_dpapi_round_trip_and_no_plaintext_on_disk(self):
        secret = "Text that must not appear in the DPAPI draft 🌲"
        path = REC.save_draft(self.folder, self.note_uuid, secret)
        self.assertNotIn(secret.encode("utf-8"), path.read_bytes())
        result = REC.read_draft(self.folder, self.note_uuid)
        self.assertEqual(result["uuid"], self.note_uuid)
        self.assertEqual(result["html"], secret)
        self.assertEqual(REC.list_drafts(self.folder), [self.note_uuid])
        REC.clear_draft(self.folder, self.note_uuid)
        self.assertIsNone(REC.read_draft(self.folder, self.note_uuid))

    @unittest.skipUnless(os.name == "nt", "DPAPI is Windows-only")
    def test_invalid_ciphertext_is_not_treated_as_plaintext(self):
        path = REC.draft_path(self.folder, self.note_uuid)
        path.write_bytes(b"not-a-valid-DPAPI-blob")
        with self.assertRaises(REC.DraftUnavailable):
            REC.read_draft(self.folder, self.note_uuid)
        self.assertEqual(path.read_bytes(), b"not-a-valid-DPAPI-blob")

    @unittest.skipIf(os.name == "nt", "Fallback is tested on other platforms")
    def test_non_windows_never_writes_plaintext(self):
        with self.assertRaises(REC.DraftUnavailable):
            REC.save_draft(self.folder, self.note_uuid, "private")
        self.assertEqual(list(self.folder.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
