"""Ensure GitHub visibility guard rejects public repositories using fake HTTP."""
import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Other_dev"))
from noteapp.encrypted_sync import GitHubTransport, SyncSecurityError


class JsonResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class PrivateRepositoryTests(unittest.TestCase):
    def test_public_repository_is_rejected(self):
        calls = []
        def respond(request, timeout):
            calls.append(request.full_url)
            return JsonResponse(json.dumps({"private": False}).encode())
        transport = GitHubTransport("fake", "fake", "fake-token", opener=respond)
        with self.assertRaises(SyncSecurityError):
            transport.assert_private()
        self.assertEqual(len(calls), 1)
        self.assertNotIn("fake-token", calls[0])

    def test_private_repository_is_allowed(self):
        def respond(request, timeout):
            return JsonResponse(json.dumps({"private": True}).encode())
        transport = GitHubTransport("fake", "fake", "fake-token", opener=respond)
        self.assertTrue(transport.assert_private())

    def test_missing_visibility_fails_closed(self):
        def respond(request, timeout):
            return JsonResponse(b"{}")
        transport = GitHubTransport("fake", "fake", "fake-token", opener=respond)
        with self.assertRaises(SyncSecurityError):
            transport.assert_private()


if __name__ == "__main__":
    unittest.main()
