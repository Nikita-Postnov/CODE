"""Synthetic, network-free tests: never access real NP Notes Data."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "Other_dev" / "noteapp" / "offline_sync.py"
spec = importlib.util.spec_from_file_location("np_notes_offline_sync", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class OfflineSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="np-notes-fake-")
        self.addCleanup(self.temp.cleanup)
        self.queue = module.OfflineSyncQueue(Path(self.temp.name) / "sync_state")

    def test_stays_local_when_offline(self):
        self.queue.mark_changed("fake-1")
        sent = []
        worker = module.OfflineSyncWorker(self.queue, lambda: False, lambda x: sent.append(x))
        self.assertFalse(worker.sync_once())
        self.assertEqual(worker.state, "waiting_for_network")
        self.assertEqual(sent, [])
        self.assertEqual(self.queue.count(), 1)

    def test_restarts_with_pending_edits(self):
        self.queue.mark_changed("fake-1")
        reopened = module.OfflineSyncQueue(Path(self.temp.name) / "sync_state")
        self.assertEqual(reopened.pending(), [("fake-1", 1)])

    def test_recovers_after_network_return(self):
        self.queue.mark_changed("fake-1")
        network = [False]
        sent = []
        worker = module.OfflineSyncWorker(
            self.queue, lambda: network[0], lambda x: sent.append(x) or True
        )
        self.assertFalse(worker.sync_once())
        network[0] = True
        self.assertTrue(worker.sync_once())
        self.assertEqual(sent, ["fake-1"])
        self.assertEqual(self.queue.count(), 0)

    def test_failed_remote_confirmation_preserves_queue(self):
        self.queue.mark_changed("fake-1")
        worker = module.OfflineSyncWorker(self.queue, lambda: True, lambda _: False)
        self.assertFalse(worker.sync_once())
        self.assertEqual(self.queue.count(), 1)

    def test_exception_preserves_queue(self):
        self.queue.mark_changed("fake-1")
        def fail(_):
            raise OSError("simulated GitHub failure")
        worker = module.OfflineSyncWorker(self.queue, lambda: True, fail)
        self.assertFalse(worker.sync_once())
        self.assertEqual(self.queue.count(), 1)

    def test_new_edit_during_upload_not_acknowledged(self):
        self.queue.mark_changed("fake-1")
        def simultaneous_edit(_):
            self.queue.mark_changed("fake-1")
            return True
        worker = module.OfflineSyncWorker(self.queue, lambda: True, simultaneous_edit)
        self.assertTrue(worker.sync_once())
        self.assertEqual(self.queue.pending(), [("fake-1", 2)])

    def test_coalesces_multiple_offline_edits(self):
        for _ in range(5):
            self.queue.mark_changed("fake-1")
        self.assertEqual(self.queue.pending(), [("fake-1", 5)])

    def test_conflict_does_not_block_other_notes_or_receives(self):
        self.queue.mark_changed("conflicted")
        self.queue.mark_changed("healthy")
        sent = []
        received = []
        def sender(note_id):
            sent.append(note_id)
            if note_id == "conflicted":
                raise RuntimeError("simulated concurrent edit")
            return True
        worker = module.OfflineSyncWorker(
            self.queue, lambda: True, sender,
            receive_encrypted=lambda: received.append(True) or True,
        )
        self.assertFalse(worker.sync_once())
        self.assertEqual(self.queue.pending(), [("conflicted", 1)])
        self.assertIn("healthy", sent)
        self.assertEqual(received, [True])

    def test_invalid_identifiers(self):
        for item in ("", "../etc", "folder/name", "folder\\name", ".", ".."):
            with self.subTest(item=item), self.assertRaises(ValueError):
                self.queue.mark_changed(item)

    def test_sender_requires_explicit_confirmation(self):
        self.queue.mark_changed("fake-1")
        worker = module.OfflineSyncWorker(self.queue, lambda: True, lambda _: None)
        self.assertFalse(worker.sync_once())
        self.assertEqual(self.queue.count(), 1)


if __name__ == "__main__":
    unittest.main()
