"""Recovery draft encryption tests. Never opens real user files."""
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
