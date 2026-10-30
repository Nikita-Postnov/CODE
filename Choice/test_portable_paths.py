import tempfile
import unittest
from pathlib import Path

from portable_paths import (
    PORTABLE_ROOT,
    convert_settings_paths,
    decode_path,
    encode_path,
    locate_portable_python,
)


class PortablePathsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "Launcher"
        self.python = self.root / "Runtime" / "python.exe"
        self.script = self.root / "Other_dev" / "notes_app.py"
        self.icon = self.root / "Icons" / "notes.ico"
        for path in (self.python, self.script, self.icon):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()

    def test_paths_are_relative_to_launcher(self):
        self.assertEqual(
            encode_path(str(self.python), self.root),
            f"{PORTABLE_ROOT}/Runtime/python.exe",
        )
        self.assertEqual(
            decode_path(f"{PORTABLE_ROOT}/Runtime/python.exe", self.root),
            str(self.python),
        )
        self.assertEqual(encode_path(str(self.root), self.root), PORTABLE_ROOT)
        self.assertEqual(decode_path(PORTABLE_ROOT, self.root), str(self.root))

    def test_moved_launcher_restores_legacy_absolute_paths(self):
        old_script = self.base / "before_move" / "Launcher" / "Other_dev" / "notes_app.py"
        self.assertEqual(decode_path(str(old_script), self.root), str(self.script))

    def test_external_paths_remain_unchanged(self):
        external = str(self.base / "external" / "python.exe")
        self.assertEqual(encode_path(external, self.root), external)
        self.assertEqual(decode_path(external, self.root), external)

    def test_rejects_portable_directory_traversal(self):
        path = f"{PORTABLE_ROOT}/../outside.txt"
        self.assertEqual(decode_path(path, self.root), path)

    def test_locates_python_when_saved_path_no_longer_exists(self):
        stale = str(self.base / "OLD" / "Launcher" / "Runtime" / "python.exe")
        self.assertEqual(locate_portable_python(self.root, stale), str(self.python))

    def test_falls_back_to_pythonw_when_python_exe_is_missing(self):
        self.python.unlink()
        alternative = self.root / "Runtime" / "pythonw.exe"
        alternative.touch()
        self.assertEqual(locate_portable_python(self.root, str(self.python)), str(alternative))

    def test_preserves_explicit_existing_python(self):
        outside = self.base / "external_python.exe"
        outside.touch()
        self.assertEqual(locate_portable_python(self.root, str(outside)), str(outside))

    def test_reports_missing_runtime_without_inventing_an_executable(self):
        self.python.unlink()
        self.assertEqual(locate_portable_python(self.root, ""), "")

    def test_settings_round_trip(self):
        original = {
            "python_executable": str(self.python),
            "scripts_folder": str(self.root),
            "last_script_path": str(self.script),
            "favorites": [str(self.script)],
            "autostart_scripts": [str(self.script)],
            "per_script_args": {str(self.script): "--tray"},
            "per_script_workdir": {str(self.script): str(self.root)},
            "per_script_icon": {str(self.script): str(self.icon)},
            "per_script_shortcut": {str(self.script): str(self.root / "Shortcuts" / "notes.lnk")},
            "recent_runs": [{"script": str(self.script), "workdir": str(self.root), "py": str(self.python), "args": "--tray"}],
            "env_text": "LAUNCHER_FLAG=1",
        }
        encoded = convert_settings_paths(original, self.root, encode=True)
        self.assertEqual(encoded["python_executable"], "$LAUNCHER/Runtime/python.exe")
        self.assertEqual(
            encoded["per_script_args"]["$LAUNCHER/Other_dev/notes_app.py"],
            "--tray",
        )
        decoded = convert_settings_paths(encoded, self.root, encode=False)
        self.assertEqual(decoded, original)


if __name__ == "__main__":
    unittest.main()
