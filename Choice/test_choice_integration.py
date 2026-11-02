import ast
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from choice_integration import (atomic_json, control_dir, heartbeat_file, health_status,
                                receive_requests, resolve_script, send_request, read_reply)
from choice_portability import export_bundle, import_bundle, portability_report


class ChoiceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "Launcher"
        self.root.mkdir()
        self.script = self.root / "Other_dev" / "punto_like_work_safe.py"
        self.script.parent.mkdir(parents=True)
        self.script.write_text("print('punto')", encoding="utf-8")

    def test_health_requires_correct_process_key(self):
        path = heartbeat_file(self.root, str(self.script))
        now = time.time()
        atomic_json(path, {"key": "old", "ts": now, "ok": True})
        self.assertEqual(health_status(path, key="current", started=now-2, now=now)[0], "ожидание")
        atomic_json(path, {"key": "current", "ts": now, "ok": True})
        self.assertEqual(health_status(path, key="current", started=now-2, now=now)[0], "исправен")
        self.assertEqual(health_status(path, key="current", started=now-2, now=now+11)[0], "ошибка")

    def test_voice_request_is_allowlisted_and_returns_reply(self):
        ident = send_request(self.root, "restart", "пунто")
        seen = []
        count = receive_requests(self.root, lambda a,t: seen.append((a,t)) or {"ok":True,"message":"done"})
        self.assertEqual(count, 1)
        self.assertEqual(seen, [("restart", "пунто")])
        self.assertEqual(read_reply(self.root, ident)["message"], "done")
        self.assertIsNone(read_reply(self.root, ident))

    def test_stale_command_is_not_executed(self):
        ident = send_request(self.root, "stop", "пунто")
        path = control_dir(self.root) / "inbox" / (ident + ".json")
        atomic_json(path, {"id": ident, "action": "stop", "target": "пунто", "ts": time.time()-120})
        calls = []
        receive_requests(self.root, lambda action,target: calls.append(action))
        self.assertEqual(calls, [])
        self.assertFalse(read_reply(self.root, ident)["ok"])

    def test_ambiguous_commands_are_rejected(self):
        entries = [{"path": "C:/A/punto_like_work_safe.py", "name": "Punto"},
                   {"path": "C:/B/punto_like_work_safe.py", "name": "Punto duplicate"}]
        self.assertEqual(resolve_script("пунто", entries)[0], None)
        self.assertEqual(resolve_script("anything;shutdown", entries)[0], None)


class ChoicePortabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)/"Launcher"
        self.root.mkdir()
        self.icon = self.root/"Icons"/"test.ico"
        self.icon.parent.mkdir()
        self.icon.write_bytes(b"ICON")
        self.script = self.root/"Other_dev"/"my_script.py"
        self.script.parent.mkdir()
        self.script.write_text("pass", encoding="utf-8")
        self.config = self.root/"launcher_config.json"
        self.config.write_text(__import__("json").dumps({
            "home_cards": [{"path": str(self.script), "name": "Demo"}],
            "per_script_icon": {str(self.script):str(self.icon)},
            "favorites": [str(self.script)]}), encoding="utf-8")

    def test_backup_restores_internal_paths_and_images_after_move(self):
        import json
        archive = self.root.parent/"choice.zip"
        self.assertEqual(export_bundle(self.root, self.config, archive), 1)
        with zipfile.ZipFile(archive) as z:
            saved=json.loads(z.read("launcher_config.json"))
            self.assertIn("$LAUNCHER/Other_dev/my_script.py", saved["favorites"])
        other=self.root.parent/"moved"/"Launcher"
        other.mkdir(parents=True)
        new_config=other/"launcher_config.json"
        self.assertEqual(import_bundle(other,new_config,archive),1)
        restored=json.loads(new_config.read_text(encoding="utf-8"))
        self.assertEqual(restored["favorites"], [str(other/"Other_dev"/"my_script.py")])
        self.assertEqual((other/"Icons"/"test.ico").read_bytes(),b"ICON")

    def test_archive_traversal_is_rejected(self):
        archive=self.root.parent/"bad.zip"
        with zipfile.ZipFile(archive,"w") as z:
            z.writestr("launcher_config.json","{}")
            z.writestr("assets/../evil.ico","EVIL")
        with self.assertRaises(ValueError):
            import_bundle(self.root,self.config,archive)
        self.assertFalse((self.root.parent/"evil.ico").exists())


if __name__ == "__main__":
    unittest.main()
