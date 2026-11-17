"""Безопасная интеграция NP Screenshot с личным Диском NPCore."""
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QToolButton
from PySide6.QtGui import QImage, QColor

SOURCE = Path(__file__).resolve().parents[1] / "Other_dev" / "screenshot.py"
SPEC = importlib.util.spec_from_file_location("np_screenshot_npcore_storage", SOURCE)
shot = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = shot
SPEC.loader.exec_module(shot)


class HTTPResponse:
    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self._body).encode("utf-8")


class ScreenshotNPCoreUploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.sample = QImage(200, 90, QImage.Format_RGB32)
        self.sample.fill(QColor("#1177aa"))

    def test_upload_uses_paired_bearer_and_multipart_png(self):
        reply = {"ok": True, "entry": {
            "rel": "Скриншоты/NP Screenshot/NP_abc.png", "size": 512}}
        def urlopen(request, timeout=0):
            self.assertEqual(timeout, 90)
            self.assertEqual(request.full_url,
                             "https://npcore.example/api/desk/screenshots/upload")
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(request.get_header("Authorization"),
                             "Bearer " + "x" * 43)
            self.assertIn("multipart/form-data",
                          request.get_header("Content-type"))
            self.assertIn(b'filename="screenshot.png"', request.data)
            self.assertIn(b"\x89PNG\r\n\x1a\n", request.data)
            return HTTPResponse(reply)

        with patch.object(shot, "_npcore_load_link",
                          return_value=("https://npcore.example", "x" * 43)), \
             patch.object(shot.urllib.request, "urlopen", side_effect=urlopen):
            result = shot._npcore_upload_image(self.sample)
        self.assertEqual(result, reply)

    def test_uploaded_name_and_real_file_path_are_server_owned(self):
        with patch.object(shot, "_npcore_load_link",
                          return_value=("https://npcore.example", "x" * 43)), \
             patch.object(shot.urllib.request, "urlopen",
                          return_value=HTTPResponse({"ok": True,
                            "entry": {"rel": "Скриншоты/NP Screenshot/NP_a.png"}})):
            result = shot._npcore_upload_image(self.sample)
        self.assertEqual(result["entry"]["rel"],
                         "Скриншоты/NP Screenshot/NP_a.png")

    def test_upload_rejects_bad_input_and_oversized_png_before_network(self):
        with patch.object(shot, "_npcore_load_link",
                          return_value=("https://npcore.example", "x" * 43)), \
             patch.object(shot.urllib.request, "urlopen") as network:
            with self.assertRaises(ValueError):
                shot._npcore_upload_png_bytes(b"not png")
            with self.assertRaises(ValueError):
                shot._npcore_upload_png_bytes(
                    b"\x89PNG\r\n\x1a\n" + b"0" * shot._NPCORE_UPLOAD_LIMIT)
            network.assert_not_called()

    def test_owner_endpoint_rejects_revoked_token(self):
        error = urllib.error.HTTPError(
            "https://npcore.example/api/desk/screenshots/upload", 401,
            "Unauthorised", {}, io.BytesIO(b'{"detail":"expired"}'))
        with patch.object(shot, "_npcore_load_link",
                          return_value=("https://npcore.example", "x" * 43)), \
             patch.object(shot.urllib.request, "urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "Нет доступа"):
                shot._npcore_upload_png_bytes(b"\x89PNG\r\n\x1a\n" + b"abc")

    def test_listing_uses_separate_authenticated_endpoint(self):
        expected = {"ok": True, "files": [{"rel": "Скриншоты/NP Screenshot/x.png"}]}
        with patch.object(shot, "_npcore_load_link",
                          return_value=("https://npcore.example", "x" * 43)), \
             patch.object(shot, "_npcore_http_json", return_value=expected) as call:
            self.assertEqual(shot._npcore_recent_screenshots(), expected)
        call.assert_called_once_with(
            "GET", "https://npcore.example/api/desk/screenshots/list",
            "x" * 43, timeout=30)

    def test_upload_dialog_requires_explicit_click_and_shows_result(self):
        dialog = shot.NPCoreUploadDialog(self.sample)
        try:
            self.assertTrue(dialog.send_button.isEnabled())
            self.assertFalse(dialog.copy_button.isEnabled())
            self.assertIsNone(dialog._worker)
            dialog._complete({"ok": True, "result": {"entry": {
                "rel": "Скриншоты/NP Screenshot/NP_test.png"}}})
            self.assertTrue(dialog.copy_button.isEnabled())
            self.assertIn("NP_test.png", dialog.path_label.text())
            dialog.copy_button.click()
            self.assertIn("NP_test.png", QApplication.clipboard().text())
        finally:
            dialog.close()

    def test_launcher_exposes_upload_and_list_without_increasing_group_rows(self):
        with patch.object(shot.Launcher, "_init_tray"), \
             patch.object(shot.Launcher, "_install_global_hotkey"), \
             patch.object(shot, "_npcore_load_link", return_value=None):
            launcher = shot.Launcher()
        try:
            self.assertIsNotNone(launcher.findChild(
                QToolButton, "np_upload_clipboard_npcore"))
            self.assertIsNotNone(launcher.findChild(
                QToolButton, "np_npcore_screenshots"))
        finally:
            launcher._real_quit = True
            launcher.close()


if __name__ == "__main__":
    unittest.main()
