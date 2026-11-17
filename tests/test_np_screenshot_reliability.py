"""Проверки сохранности снимков, записей и отложенного захвата NP_Screenshot."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication

SCRIPT = Path(__file__).resolve().parents[1] / "Other_dev" / "screenshot.py"
SPEC = importlib.util.spec_from_file_location("np_screenshot_under_test", SCRIPT)
shot = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = shot
SPEC.loader.exec_module(shot)


class FakeImage:
    def __init__(self, succeed=True):
        self.succeed = succeed
        self.saves = []

    def save(self, path, fmt, quality):
        self.saves.append((path, fmt, quality))
        Path(path).write_bytes(b"partial" if not self.succeed else b"new-image")
        return self.succeed


class ScreenshotReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def test_new_image_is_written_and_temp_is_removed(self):
        out = self.folder / "capture.png"
        self.assertTrue(shot.save_image_atomically(FakeImage(), out, "PNG"))
        self.assertEqual(out.read_bytes(), b"new-image")
        self.assertEqual(list(self.folder.glob("*.tmp")), [])

    def test_failed_encoder_never_replaces_existing_screenshot(self):
        out = self.folder / "important.png"
        out.write_bytes(b"original")
        self.assertFalse(shot.save_image_atomically(FakeImage(False), out, "PNG"))
        self.assertEqual(out.read_bytes(), b"original")
        self.assertEqual(list(self.folder.glob("*.tmp")), [])

    def test_failed_replace_keeps_existing_image_and_removes_temp(self):
        out = self.folder / "important.png"
        out.write_bytes(b"original")
        with patch.object(shot.os, "replace", side_effect=OSError("locked")):
            self.assertFalse(shot.save_image_atomically(FakeImage(), out, "PNG"))
        self.assertEqual(out.read_bytes(), b"original")
        self.assertEqual(list(self.folder.glob("*.tmp")), [])

    def test_actual_qimage_round_trip(self):
        out = self.folder / "real.png"
        image = QImage(4, 3, QImage.Format_ARGB32)
        image.fill(QColor("#bb0000"))
        self.assertTrue(shot.save_image_atomically(image, out, "PNG"))
        loaded = QImage(str(out))
        self.assertFalse(loaded.isNull())
        self.assertEqual((loaded.width(), loaded.height()), (4, 3))
        self.assertEqual(loaded.pixelColor(1, 1).name(), "#bb0000")

    def test_old_recordings_survive_temp_cleanup(self):
        tmp = self.folder / "Data" / "_rec_tmp"
        tmp.mkdir(parents=True)
        old_video = tmp / "rec_2026-01-01_10-00-00.mp4"
        old_temp = tmp / "frame_cache.png"
        for entry in (old_video, old_temp):
            entry.write_bytes(b"file")
            ago = time.time() - 30 * 86400
            os.utime(entry, (ago, ago))
        with patch.object(shot, "DATA_DIR", self.folder / "Data"):
            shot._cleanup_rec_tmp()
        self.assertTrue(old_video.exists())
        self.assertFalse(old_temp.exists())

    def test_permanent_recording_directory_is_independent_of_temp(self):
        with patch.object(shot, "DATA_DIR", self.folder / "Data"):
            permanent = shot._recordings_dir()
            permanent_video = permanent / "rec_2026-01-01_10-00-00.mp4"
            permanent_video.write_bytes(b"recording")
            ago = time.time() - 30 * 86400
            os.utime(permanent_video, (ago, ago))
            shot._cleanup_rec_tmp()
        self.assertEqual(permanent.name, "Recordings")
        self.assertEqual(permanent_video.read_bytes(), b"recording")


class OCRTableLayoutTests(unittest.TestCase):
    """Проверяем скриншот веб-таблицы с двумя отдельно распознанными колонками."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _ocr_line(text, x, y, width=130, height=14):
        return {"text": text, "x": x, "y": y,
                "width": width, "height": height, "words": [
                    {"text": text, "x": x, "y": y,
                     "width": width, "height": height}]}

    def _portfolio_payload(self):
        headers = ("Возможность", "Как теперь работает")
        left = [
            "Многострочный текст", "Выбор шрифта", "Размер текста",
            "Начертание", "Выравнивание", "Автоматический размер",
            "Ручное изменение размера", "Редактирование",
            "Отмена изменений", "Сохранение проектов",
        ]
        right = [
            "Можно вводить абзацы и переносить строки клавишей Enter",
            "В окне редактирования доступен список установленных шрифтов",
            "Настраивается от 5 до 300 pt", "Полужирный и курсив",
            "Слева, по центру или справа",
            "Рамка текста подстраивается под содержимое",
            "Можно изменять рамку маркерами",
            "Двойной щелчок по тексту открывает окно редактирования",
            "Работают Ctrl+Z и Ctrl+Y",
            "Все параметры текста сохраняются в .npshot",
        ]
        lines = [self._ocr_line(headers[0], 627, 248),
                 self._ocr_line(headers[1], 805, 248)]
        for index, (label, explanation) in enumerate(zip(left, right)):
            y = 278 + 35 * index
            lines.append(self._ocr_line(label, 627, y))
            lines.append(self._ocr_line(explanation, 805, y + (index % 2)))
            if index in (0, 6):
                lines.append(self._ocr_line(
                    "Дополнительная часть описания", 805, y + 16))
        # OCR часто возвращает сперва всю левую колонку, затем правую;
        # постороннее меню и заголовок страницы не должны создавать столбцы.
        lines.extend(self._ocr_line("Пункт меню " + str(i), 17, 170 + i * 22)
                     for i in range(6))
        lines.extend((
            self._ocr_line("Готово!", 627, 108),
            self._ocr_line("Проверки", 627, 706),
            self._ocr_line("Выполнено", 627, 730),
        ))
        lines.sort(key=lambda row: (row["x"], row["y"]))
        return {"lines": lines}

    def test_detects_two_column_table_from_separate_ocr_lines(self):
        rows = shot.ocr_layout_to_table_cells(self._portfolio_payload())
        self.assertEqual(len(rows), 11)
        self.assertEqual(rows[0], ["Возможность", "Как теперь работает"])
        self.assertEqual(rows[1][0], "Многострочный текст")
        self.assertIn("Дополнительная часть описания", rows[1][1])
        self.assertEqual(rows[-1][0], "Сохранение проектов")
        self.assertNotIn("Пункт меню", str(rows))
        markdown = shot.ocr_layout_to_markdown_table(self._portfolio_payload())
        self.assertIn("| Возможность | Как теперь работает |", markdown)
        self.assertIn("| --- | --- |", markdown)

    def test_multi_column_line_split_into_separate_cells(self):
        lines = []
        for index, (left, right) in enumerate((
                ("Название", "Описание"), ("Этап 1", "Подготовка"),
                ("Этап 2", "Выполнение"), ("Этап 3", "Проверка"))):
            y = 100 + 30 * index
            lines.append({"text": left + " " + right,
                          "x": 40, "y": y, "height": 14,
                          "words": [
                              {"text": left, "x": 40, "y": y,
                               "width": 60, "height": 14},
                              {"text": right, "x": 250, "y": y,
                               "width": 110, "height": 14},
                          ]})
        rows = shot.ocr_layout_to_table_cells({"lines": lines})
        self.assertEqual(rows[0], ["Название", "Описание"])
        self.assertEqual(rows[-1], ["Этап 3", "Проверка"])

    def test_random_prose_is_not_fabricated_as_table(self):
        payload = {"lines": [
            self._ocr_line("Заголовок", 100, 35),
            self._ocr_line("Обычный текст абзаца", 100, 64),
            self._ocr_line("Продолжение текста", 100, 93),
            self._ocr_line("Окончание", 100, 122),
        ]}
        self.assertEqual(shot.ocr_layout_to_table_cells(payload), [])
        self.assertEqual(shot.ocr_layout_to_markdown_table(payload), "")

    def test_table_dialog_previews_columns_and_copies_excel(self):
        rows = shot.ocr_layout_to_table_cells(self._portfolio_payload())
        dialog = shot.OCRTableDialog(rows)
        try:
            self.assertEqual(dialog.table.columnCount(), 2)
            self.assertEqual(dialog.table.rowCount(), 10)
            self.assertEqual(dialog.table.horizontalHeaderItem(0).text(),
                             "Возможность")
            dialog.table.item(0, 1).setText("Текст изменён")
            dialog.copy_tsv()
            copied = QApplication.clipboard().text()
            self.assertIn("Возможность\tКак теперь работает", copied)
            self.assertIn("Многострочный текст\tТекст изменён", copied)
            dialog.copy_markdown()
            markdown = QApplication.clipboard().text()
            self.assertIn("| Многострочный текст | Текст изменён |",
                          markdown)
        finally:
            dialog.close()


class QuickCaptureTests(unittest.TestCase):
    """Повторный захват, сохранение и устойчивость сохранённой области."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        settings = self.folder / "prefs.json"
        self.path_patch = patch.object(shot, "SCREENSHOT_HISTORY_SETTINGS", settings)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.region_patch = patch.object(
            shot, "SCREENSHOT_QUICK_REGION_SETTINGS",
            self.folder / "quick_region.json")
        self.region_patch.start()
        self.addCleanup(self.region_patch.stop)
        with patch.object(shot.Launcher, "_init_tray"), \
             patch.object(shot.Launcher, "_install_global_hotkey"):
            self.launcher = shot.Launcher()
        self.addCleanup(self.close_launcher)

    def close_launcher(self):
        self.launcher._real_quit = True
        self.launcher.close()

    def _rect(self):
        screen = QApplication.primaryScreen().geometry()
        return shot.QRect(screen.x() + 10, screen.y() + 10, 85, 65)

    def _sample_image(self):
        image = QImage(85, 65, QImage.Format_ARGB32)
        image.fill(QColor("#2488bb"))
        return image

    def test_region_settings_survive_restart_and_manual_checkboxes(self):
        rect = self._rect()
        self.assertTrue(self.launcher.remember_last_region(rect))
        stored = shot.load_quick_region()
        self.assertEqual(stored["last_region"], list(rect.getRect()))
        self.assertEqual(stored["last_screens"], shot._quick_screen_layout())
        self.launcher._set_capture_preference("edit_after_capture", False)
        self.assertEqual(shot.load_quick_region()["last_region"],
                         list(rect.getRect()))
        self.assertFalse(shot.load_capture_preferences()["edit_after_capture"])
        self.assertEqual(self.launcher._last_valid_quick_region(), rect)

    def test_quick_repeat_copies_without_area_selection_or_editor(self):
        rect = self._rect()
        self.assertTrue(self.launcher.remember_last_region(rect))
        image = self._sample_image()
        with patch.object(shot, "grab_region_highdpi", return_value=image) as capture, \
             patch.object(shot.QTimer, "singleShot") as timer, \
             patch.object(self.launcher, "_open_editor_image") as open_editor:
            self.launcher.quick_repeat("copy")
            timer.assert_called_once()
            self.assertTrue(self.launcher._quick_capture_pending)
            timer.call_args.args[1]()
            capture.assert_called_once_with(rect)
            open_editor.assert_not_called()
        copied = QApplication.clipboard().image()
        self.assertEqual(copied.pixelColor(1, 1).name(), "#2488bb")
        self.assertFalse(self.launcher._quick_capture_pending)

    def test_quick_repeat_saves_png_without_dialog(self):
        self.assertTrue(self.launcher.remember_last_region(self._rect()))
        with patch.object(shot, "grab_region_highdpi",
                          return_value=self._sample_image()), \
             patch.object(shot.QStandardPaths, "writableLocation",
                          return_value=str(self.folder)), \
             patch.object(shot.QTimer, "singleShot") as timer, \
             patch.object(shot.QFileDialog, "getSaveFileName") as save_dialog:
            self.launcher.quick_repeat("save")
            timer.call_args.args[1]()
            save_dialog.assert_not_called()
        files = list((self.folder / "NP Screenshot").glob("Screenshot_*.png"))
        self.assertEqual(len(files), 1)
        self.assertEqual(QImage(str(files[0])).pixelColor(1, 1).name(),
                         "#2488bb")

    def test_new_area_sets_last_region_then_performs_selected_action(self):
        rect = self._rect()
        def select(on_selected=None):
            self.assertIsNotNone(on_selected)
            on_selected(rect)
            return self._sample_image()
        with patch.object(shot, "capture_region_interactive",
                          side_effect=select) as capture:
            self.launcher._quick_select_area("copy")
            capture.assert_called_once()
        self.assertEqual(self.launcher._last_valid_quick_region(), rect)
        self.assertEqual(QApplication.clipboard().image().width(), 85)

    def test_changing_monitors_disables_stale_region_safely(self):
        self.assertTrue(self.launcher.remember_last_region(self._rect()))
        with patch.object(shot, "_quick_screen_layout",
                          return_value=[[50_000, 50_000, 120, 100]]), \
             patch.object(shot.QMessageBox, "information") as inform, \
             patch.object(shot, "grab_region_highdpi") as capture:
            self.launcher.quick_repeat("copy")
            self.assertIsNone(self.launcher._last_valid_quick_region())
        inform.assert_called_once()
        capture.assert_not_called()

    def test_invalid_preferences_cannot_force_offscreen_capture(self):
        region_path = shot.SCREENSHOT_QUICK_REGION_SETTINGS
        region_path.write_text(
            '{"last_region":[1,2,-99999,20],"last_screens":[[0,0,1280,800]]}',
            encoding="utf-8")
        self.assertIsNone(shot.load_quick_region()["last_region"])
        self.assertIsNone(shot._quick_region_data([1, True, 60, 70]))
        self.assertFalse(shot._quick_region_is_visible(
            shot.QRect(50000, 50000, 30, 30)))

    def test_rapid_duplicate_requests_do_not_capture_twice(self):
        self.assertTrue(self.launcher.remember_last_region(self._rect()))
        with patch.object(shot.QTimer, "singleShot") as timer:
            self.launcher.quick_repeat("copy")
            self.launcher.quick_repeat("save")
            timer.assert_called_once()
            self.launcher._quick_capture_pending = False

class DelayedCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.launcher = shot.Launcher()
        self.addCleanup(self.close_launcher)

    def close_launcher(self):
        self.launcher.cancel_delayed_capture()
        self.launcher._real_quit = True
        self.launcher.close()

    def test_delay_triggers_capture_only_after_countdown(self):
        with patch.object(self.launcher, "_capture") as capture:
            self.launcher.capture_delayed(3)
            self.assertTrue(self.launcher._delayed_capture_timer.isActive())
            self.assertEqual(self.launcher._delayed_capture_timer.remainingTime() > 0, True)
            capture.assert_not_called()
            self.launcher._delayed_capture_timer.stop()
            self.launcher._finish_delayed_capture()
            capture.assert_called_once_with(shot.SelectionOverlay.MODE_SHOT)

    def test_cancel_prevents_delayed_capture(self):
        with patch.object(self.launcher, "_capture") as capture:
            self.launcher.capture_delayed(5)
            self.launcher.cancel_delayed_capture()
            self.assertFalse(self.launcher._delayed_capture_timer.isActive())
            capture.assert_not_called()

    def test_delay_values_are_restricted(self):
        with self.assertRaises(ValueError):
            self.launcher.capture_delayed(-1)
        with self.assertRaises(ValueError):
            self.launcher.capture_delayed(120)


class StartupNotificationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _invoke_hotkey_setup(self, registered):
        tray = SimpleNamespace(setToolTip=Mock(), showMessage=Mock())
        fake = SimpleNamespace(
            tray=tray, act_tray_shot=SimpleNamespace(setText=Mock()),
            act_tray_ocr=SimpleNamespace(setText=Mock()),
            hotkey_capture=Mock(),
        )
        hotkey = SimpleNamespace(
            registered=registered, main_key="PrintScreen",
            ocr_key="Shift+PrintScreen", description="PrintScreen",
            report=["ok"],
        )
        with patch.object(shot.sys, "platform", "win32"), \
             patch.object(shot, "_WinHotkey", return_value=hotkey):
            shot.Launcher._install_global_hotkey(fake)
        return tray, fake

    def test_successful_startup_does_not_generate_windows_notification(self):
        tray, fake = self._invoke_hotkey_setup(True)
        tray.showMessage.assert_not_called()
        tray.setToolTip.assert_called_once()
        fake.act_tray_shot.setText.assert_called_once()
        fake.act_tray_ocr.setText.assert_called_once()

    def test_hotkey_registration_failure_still_warns_user(self):
        tray, _fake = self._invoke_hotkey_setup(False)
        tray.showMessage.assert_called_once()
        self.assertIn("PrintScreen занят", tray.showMessage.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
