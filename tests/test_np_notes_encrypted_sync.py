"""No network or user notes: synthetic tests for encrypted NP Notes transport."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

MODULE = Path(__file__).resolve().parents[1] / "Other_dev/noteapp/encrypted_sync.py"
spec = importlib.util.spec_from_file_location("np_encrypted_sync", MODULE)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class CryptographicTests(unittest.TestCase):
    def setUp(self):
        try:
            sync._aes()
        except sync.SyncSecurityError:
            self.skipTest("cryptography dependency not installed")
        self.note_id = str(uuid4())
        self.other_id = str(uuid4())
        self.passphrase = "synthetic test passphrase only"

    def test_round_trip(self):
        sample = b"fake note + fake image bytes\x00\xff"
        encrypted = sync.seal(sample, self.passphrase, self.note_id)
        self.assertNotIn(sample, encrypted)
        self.assertEqual(sync.unseal(encrypted, self.passphrase, self.note_id), sample)

    def test_unique_ciphertext(self):
        one = sync.seal(b"same", self.passphrase, self.note_id)
        two = sync.seal(b"same", self.passphrase, self.note_id)
        self.assertNotEqual(one, two)

    def test_wrong_password_fails(self):
        encrypted = sync.seal(b"fake", self.passphrase, self.note_id)
        with self.assertRaises(sync.SyncSecurityError):
            sync.unseal(encrypted, "different password", self.note_id)

    def test_cross_note_replay_fails(self):
        encrypted = sync.seal(b"fake", self.passphrase, self.note_id)
        with self.assertRaises(sync.SyncSecurityError):
            sync.unseal(encrypted, self.passphrase, self.other_id)

    def test_corruption_fails(self):
        encrypted = sync.seal(b"fake", self.passphrase, self.note_id)
        with self.assertRaises(sync.SyncSecurityError):
            sync.unseal(encrypted[:-5] + b"xxxxx", self.passphrase, self.note_id)

    def test_short_secret_rejected(self):
        with self.assertRaises(sync.SyncSecurityError):
            sync.seal(b"fake", "short", self.note_id)

    def test_invalid_note_id_rejected(self):
        with self.assertRaises(sync.SyncSecurityError):
            sync.seal(b"fake", self.passphrase, "../example")


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        def offline_opener(request, timeout):
            self.calls.append(request)
            raise OSError("Synthetic offline failure")
        self.transport = sync.GitHubTransport(
            "fake-owner", "fake-private-repo", "fake-token",
            opener=offline_opener,
        )

    def test_offline_does_not_mark_sent(self):
        with self.assertRaises(OSError):
            self.transport.write(str(uuid4()), b"fake-ciphertext")
        self.assertEqual(len(self.calls), 1)

    def test_only_encrypted_path(self):
        with self.assertRaises(sync.SyncSecurityError):
            self.transport.write("../../etc", b"fake")
        self.assertEqual(self.calls, [])

    def test_invalid_revision_rejected(self):
        with self.assertRaises(sync.SyncSecurityError):
            self.transport.write(str(uuid4()), b"fake", expected_sha="invalid")
        self.assertEqual(self.calls, [])

    def test_no_plaintext_note_in_url(self):
        with self.assertRaises(OSError):
            self.transport.write(str(uuid4()), b"fake")
        self.assertNotIn("fake-ciphertext", self.calls[0].full_url)

    def test_delete_requires_exact_git_blob_sha(self):
        identifier = str(uuid4())
        with self.assertRaises(sync.SyncSecurityError):
            self.transport.delete_note(identifier, "not-a-sha")
        self.assertEqual(self.calls, [])
        with self.assertRaises(OSError):
            self.transport.delete_note(identifier, "a" * 40)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0].get_method(), "DELETE")
        self.assertTrue(self.calls[0].full_url.endswith(
            "/encrypted/" + identifier + ".json"
        ))
        self.assertIn(b'"sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"',
                      self.calls[0].data)

    def test_encrypted_deletion_marker_uses_separate_directory(self):
        identifier = str(uuid4())
        payload = sync.seal(
            b'{"v":1,"uuid":"' + identifier.encode() + b'"}',
            "synthetic password for tests",
            identifier
        )
        with self.assertRaises(OSError):
            self.transport.write_tombstone(identifier, payload)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.calls[0].full_url.endswith(
            "/tombstones/" + identifier + ".json"
        ))
        self.assertNotIn(identifier.encode() + b'"}', self.calls[0].data)



if __name__ == "__main__":
    unittest.main()
