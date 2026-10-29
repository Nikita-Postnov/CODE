"""Тонкий лаунчер приложения «Мои Заметки».

Вся логика — в пакете noteapp.app. Файл оставлен как точка запуска
(python notes_app.py) и совместимости с лаунчером Choice.exe.
"""

import subprocess
import sys
from pathlib import Path

# ============================================================
# ОТДЕЛЬНЫЙ ЗНАЧОК В ТРЕЕ
# ============================================================
# Windows различает значки трея по exe. Если скрипт запущен общим
# python.exe/pythonw.exe (например, из Choice), перезапускаем его под своей
# копией NP_Notes.exe (их делает make_portable.py в папке Runtime). Нет копии — работаем как есть.

def _relaunch_under_own_exe(exe_name: str = "NP_Notes") -> None:
    if sys.platform != "win32" or getattr(sys, "frozen", False):
        return
    current = Path(sys.executable)
    if current.stem.lower() == exe_name.lower():
        return
    target = current.parent / f"{exe_name}.exe"
    if not target.exists():
        return
    cmd = [str(target), str(Path(__file__).resolve()), *sys.argv[1:]]
    try:
        # Выходим из Job Object лаунчера, чтобы он не закрыл нас вместе с собой.
        subprocess.Popen(cmd, cwd=str(Path.cwd()), close_fds=True, creationflags=0x01000000)
    except OSError:
        try:
            subprocess.Popen(cmd, cwd=str(Path.cwd()), close_fds=True)
        except OSError:
            return  # не вышло — работаем под текущим интерпретатором
    raise SystemExit(0)


if __name__ == "__main__":
    _relaunch_under_own_exe()
    from noteapp.app import main

    raise SystemExit(main())
