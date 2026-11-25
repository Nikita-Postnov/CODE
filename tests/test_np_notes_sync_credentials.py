"""No secrets, network or real Notes folder: credential loader fails closed."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Other_dev"))
from noteapp.sync_credentials import load_dpapi_credentials
from noteapp.sync_service import configure_from_environment


class EncryptedCredentialsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="fake-np-dpapi-")
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def test_no_credentials_no_automatic_activation(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(load_dpapi_credentials(self.folder))
            self.assertIsNone(
                configure_from_environment(self.folder, self.folder / "Notes")
            )

    def test_credentials_do_not_implicitly_activate_real_sync(self):
        # Even if credentials exist, an explicit deployment gate is required.
        with patch.dict("os.environ", {"NP_NOTES_SYNC_OWNER": "fake",
                                      "NP_NOTES_SYNC_REPOSITORY": "fake",
                                      "NP_NOTES_SYNC_TOKEN": "fake",
                                      "NP_NOTES_SYNC_PASSPHRASE": "syntheticlongsecret"}, clear=True):
            with patch("noteapp.sync_credentials.load_dpapi_credentials",
                       side_effect=AssertionError("must not read credentials")):
                self.assertIsNone(
                    configure_from_environment(self.folder, self.folder / "Notes")
                )

    def test_activation_marker_requires_exact_opt_in(self):
        marker = self.folder / "sync_enabled.json"
        fake = {"owner": "fake", "repository": "fake", "token": "fake",
                "passphrase": "synthetic long secret"}
        with patch.dict("os.environ", {}, clear=True):
            for payload in ('{"enabled":true}', '{"version":1,"enabled":false}',
                            'not valid JSON'):
                marker.write_text(payload, encoding="utf-8")
                with patch("noteapp.sync_credentials.load_dpapi_credentials",
                           side_effect=AssertionError("unexpected secret read")):
                    self.assertIsNone(
                        configure_from_environment(self.folder, self.folder / "Notes")
                    )
            marker.write_text('{"version":1,"enabled":true}', encoding="utf-8")
            with patch("noteapp.sync_credentials.load_dpapi_credentials",
                       return_value=fake), patch(
                       "noteapp.sync_service.EncryptedOutboundService"
                       ) as factory:
                result = configure_from_environment(
                    self.folder, self.folder / "Notes"
                )
                self.assertIs(result, factory.return_value)
                self.assertEqual(factory.call_count, 1)

    def test_loader_never_assumes_plaintext(self):
        (self.folder / "credentials.dpapi").write_text(
            json.dumps({"owner": "fake", "repository": "fake",
                        "token": "not-really-a-token",
                        "passphrase": "synthetic long passphrase"}),
            encoding="utf-8",
        )
        # On non-Windows, DPAPI should reject. On Windows, protected data
        # cannot be decrypted from JSON plaintext either.
        with self.assertRaises(Exception):
            load_dpapi_credentials(self.folder)


if __name__ == "__main__":
    unittest.main()
