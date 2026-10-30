import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from manual_cards import ManualCardsHome, normalize_home_cards


class ManualCardsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.script = self.root / "Nicholas.py"
        self.script.write_text("print('ok')", encoding="utf-8")

    def test_no_apps_appear_automatically(self):
        home = ManualCardsHome()
        self.addCleanup(home.close)
        self.assertEqual(home._cards, [])
        self.assertEqual(len(home.content.findChildren(QPushButton)), 0)
        added = []
        home.addRequested.connect(lambda: added.append(True))
        home.add_button.click()
        self.assertEqual(added, [True])
        self.assertEqual(home._cards, [])

    def test_only_valid_manually_saved_cards_are_shown(self):
        home = ManualCardsHome()
        self.addCleanup(home.close)
        home.set_cards([
            {"path": str(self.script), "name": "Николас"},
            {"path": str(self.script), "name": "Дубликат"},
            {"path": str(self.root / "bad.exe"), "name": "EXE"},
            {},
        ])
        self.assertEqual(home._cards, [{"path": str(self.script), "name": "Николас"}])
        launch = []
        remove = []
        home.launchRequested.connect(launch.append)
        home.removeRequested.connect(remove.append)
        buttons = home.content.findChildren(QPushButton)
        self.assertEqual(len(buttons), 2)
        next(x for x in buttons if "Запустить" in x.text()).click()
        next(x for x in buttons if x.text() == "Убрать").click()
        self.assertEqual(launch, [str(self.script)])
        self.assertEqual(remove, [str(self.script)])
        self.assertTrue(self.script.exists())

    def test_running_card_cannot_spawn_a_duplicate(self):
        home = ManualCardsHome()
        self.addCleanup(home.close)
        home.set_cards([{"path": str(self.script), "name": "Nicholas"}],
                       running={str(self.script)})
        launch = next(
            x for x in home.content.findChildren(QPushButton)
            if "Запустить" in x.text()
        )
        self.assertFalse(launch.isEnabled())

    def test_missing_file_disables_launch_but_preserves_card(self):
        missing = self.root / "missing.pyw"
        home = ManualCardsHome()
        self.addCleanup(home.close)
        home.set_cards([{"path": str(missing), "name": "Отсутствует"}])
        button = next(
            x for x in home.content.findChildren(QPushButton)
            if "Запустить" in x.text()
        )
        self.assertFalse(button.isEnabled())
        self.assertEqual(home._cards[0]["path"], str(missing))

    def test_launcher_saves_only_manual_cards_and_keeps_file_on_removal(self):
        from choice_dev import FriendlyLauncher
        settings = self.root / "launcher_config.json"
        with patch("choice_dev.config_file", return_value=settings), \
             patch("choice_dev.app_folder", return_value=self.root):
            window = FriendlyLauncher()
            self.addCleanup(window.close)
            window._startup_deferred()
            self.assertEqual(window.main_pages.currentIndex(), 0)
            self.assertEqual(window.cards_home._cards, [])
            self.assertEqual(window.scripts_list.selectedItems(), [])
            window._pin_home_card(str(self.script))
            self.assertEqual(len(window.cards_home._cards), 1)
            self.assertEqual(window.main_pages.currentIndex(), 0)
            self.assertEqual(window.cards_home._cards[0]["name"], "Nicholas")
            window._pin_home_card(str(self.script))
            self.assertEqual(len(window.cards_home._cards), 1)
            self.assertTrue(settings.exists())
            window._remove_home_card(str(self.script))
            self.assertEqual(window.cards_home._cards, [])
            self.assertTrue(self.script.is_file())

    def test_card_paths_survive_portable_settings_conversion(self):
        from portable_paths import convert_settings_paths
        cards = [{"name": "Nicholas", "path": str(self.script)}]
        original = {"home_cards": cards}
        saved = convert_settings_paths(original, self.root, encode=True)
        self.assertEqual(saved["home_cards"][0]["path"], "$LAUNCHER/Nicholas.py")
        loaded = convert_settings_paths(saved, self.root, encode=False)
        self.assertEqual(loaded, original)

    def test_cards_can_reflow_when_resized(self):
        home = ManualCardsHome()
        self.addCleanup(home.close)
        for index in range(5):
            path = self.root / f"test_{index}.py"
            path.touch()
        cards = [
            {"path": str(self.root / f"test_{i}.py"), "name": f"Test {i}"}
            for i in range(5)
        ]
        home.resize(930, 650)
        home.set_cards(cards)
        home.show()
        QApplication.processEvents()
        wide = home._columns
        home.resize(420, 650)
        QApplication.processEvents()
        narrow = home._columns
        self.assertGreater(wide, narrow)
        self.assertEqual(narrow, 1)
        self.assertEqual(len(home.content.findChildren(QPushButton)), 10)


if __name__ == "__main__":
    unittest.main()
