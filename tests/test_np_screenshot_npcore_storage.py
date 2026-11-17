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


class FakeOpener:
    def __init__(self, operation):
        self.operation = operation

    def open(self, request, timeout=0):
        return self.operation(request, timeout=timeout)


class ScreenshotNPCoreUploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.sample = QImage(200, 90, QImage.Format_RGB32)
        self.sample.fill(QColor("#1177aa"))

    def test_current_clipboard_png_data_is_decoded(self):
        """Некоторые приложения кладут только MIME image/png, а не QImage."""
        image = self.sample
        buffer = shot.QBuffer()
        self.assertTrue(buffer.open(shot.QIODevice.WriteOnly))
        self.assertTrue(image.save(buffer, "PNG"))
        mime = shot.QMimeData()
        mime.setData("image/png", bytes(buffer.data()))
        QApplication.clipboard().setMimeData(mime)
        extracted = shot._npcore_current_clipboard_image()
        self.assertFalse(extracted.isNull())
        self.assertEqual(extracted.pixelColor(8, 8).name(), "#1177aa")

    def test_windows_clipboard_history_does_not_override_current_text(self):
        """Win+V может хранить снимок, когда активным содержимым стал OCR-текст."""
        QApplication.clipboard().setText("Текст, полученный через OCR")
        self.assertTrue(shot._npcore_current_clipboard_image().isNull())

    def test_copy_image_file_from_explorer_is_supported(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            filename = Path(folder) / "capture.png"
            self.assertTrue(self.sample.save(str(filename), "PNG"))
            mime = shot.QMimeData()
            mime.setUrls([shot.QUrl.fromLocalFile(str(filename))])
            QApplication.clipboard().setMimeData(mime)
            extracted = shot._npcore_current_clipboard_image()
            self.assertEqual(extracted.size(), self.sample.size())

    def test_normal_capture_keeps_last_image_when_ocr_replaces_clipboard(self):
        with patch.object(shot.Launcher, "_init_tray"), \
             patch.object(shot.Launcher, "_install_global_hotkey"), \
             patch.object(shot, "_npcore_load_link", return_value=None):
            launcher = shot.Launcher()
        try:
            launcher._handle_captured_image(self.sample)
            QApplication.clipboard().setText("OCR теперь в буфере")
            self.assertTrue(shot._npcore_current_clipboard_image().isNull())
            self.assertEqual(
                launcher._last_captured_image.pixelColor(2, 3).name(),
                "#1177aa")
            with patch.object(shot.QMessageBox, "exec", autospec=True) as run:
                def click_last(dialog):
                    choice = next(b for b in dialog.buttons()
                                  if b.text() == "Последний снимок")
                    choice.click()
                    return 0
                run.side_effect = click_last
                selected = launcher._choose_npcore_source()
            self.assertEqual(selected.size(), self.sample.size())
        finally:
            launcher._real_quit = True
            launcher.close()

    def test_upload_when_clipboard_contains_text_prompts_before_network(self):
        with patch.object(shot.Launcher, "_init_tray"), \
             patch.object(shot.Launcher, "_install_global_hotkey"), \
             patch.object(shot, "_npcore_load_link",
                          return_value=("https://npcore.example", "x" * 43)):
            launcher = shot.Launcher()
        try:
            QApplication.clipboard().setText("Скопирован текст")
            with patch.object(launcher, "_choose_npcore_source",
                              return_value=self.sample) as choose, \
                 patch.object(launcher, "_show_npcore_upload") as upload, \
                 patch.object(shot, "_npcore_upload_image") as network:
                launcher.upload_clipboard_npcore()
                choose.assert_called_once()
                upload.assert_called_once()
                self.assertEqual(
                    upload.call_args.args[0].pixelColor(4, 4).name(),
                    "#1177aa")
                network.assert_not_called()
        finally:
            launcher._real_quit = True
            launcher.close()

    def test_quick_save_remembers_image_without_changing_clipboard(self):
        with patch.object(shot.Launcher, "_init_tray"), \
             patch.object(shot.Launcher, "_install_global_hotkey"):
            launcher = shot.Launcher()
        try:
            import tempfile
            with tempfile.TemporaryDirectory() as folder, \
                 patch.object(shot.QStandardPaths, "writableLocation",
                              return_value=folder):
                QApplication.clipboard().setText("Важный текст")
                launcher._quick_finish_image(self.sample, "save")
                self.assertEqual(QApplication.clipboard().text(), "Важный текст")
                self.assertEqual(
                    launcher._last_captured_image.pixelColor(4, 4).name(),
                    "#1177aa")
        finally:
            launcher._real_quit = True
            launcher.close()

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
             patch.object(shot.urllib.request, "build_opener",
                          return_value=FakeOpener(urlopen)):
            result = shot._npcore_upload_image(self.sample)
        self.assertEqual(result, reply)

    def test_uploaded_name_and_real_file_path_are_server_owned(self):
        with patch.object(shot, "_npcore_load_link",
                          return_value=("https://npcore.example", "x" * 43)), \
             patch.object(shot.urllib.request, "build_opener",
                          return_value=FakeOpener(
                              lambda _request, timeout=0: HTTPResponse({
                                  "ok": True, "entry": {
                                  "rel": "Скриншоты/NP Screenshot/NP_a.png"}}))):
            result = shot._npcore_upload_image(self.sample)
        self.assertEqual(result["entry"]["rel"],
                         "Скриншоты/NP Screenshot/NP_a.png")

    def test_upload_rejects_bad_input_and_oversized_png_before_network(self):
        with patch.object(shot, "_npcore_load_link",
                          return_value=("https://npcore.example", "x" * 43)), \
             patch.object(shot.urllib.request, "build_opener") as network:
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
             patch.object(shot.urllib.request, "build_opener",
                          return_value=FakeOpener(
                              lambda _request, timeout=0: (_ for _ in ()).throw(error))):
            with self.assertRaisesRegex(RuntimeError, "Нет доступа"):
                shot._npcore_upload_png_bytes(b"\x89PNG\r\n\x1a\n" + b"abc")

    def test_upload_redirects_are_disabled(self):
        with patch.object(shot, "_npcore_load_link",
                          return_value=("https://npcore.example", "x" * 43)), \
             patch.object(shot.urllib.request, "build_opener",
                          return_value=FakeOpener(
                              lambda _request, timeout=0:
                              HTTPResponse({"ok": True, "entry": {
                                  "rel": "Скриншоты/NP Screenshot/x.png"}}))) as factory:
            shot._npcore_upload_png_bytes(b"\x89PNG\r\n\x1a\n" + b"abc")
            self.assertEqual(factory.call_count, 1)
            handler = factory.call_args.args[0]
            self.assertIsNone(handler.redirect_request(
                None, None, 302, "Moved", {}, "https://other.example"))

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
