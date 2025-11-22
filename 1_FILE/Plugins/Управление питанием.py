import platform
import subprocess
import traceback
import shutil

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMessageBox, QMenu

_action_group = []
_installed = False
_submenu = None


def _run_cmd(parent, args):
    try:
        res = subprocess.run(args, check=True, capture_output=True, text=True)
        return True, res.stdout.strip()
    except Exception as e:
        return False, f"{e}"


def _confirm(parent, title, text) -> bool:
    return QMessageBox.question(
        parent, title, text, QMessageBox.Yes | QMessageBox.No
    ) == QMessageBox.Yes


def _lock_pc(parent):
    osname = platform.system()
    if osname == "Windows":
        ok, msg = _run_cmd(parent, ["rundll32.exe", "user32.dll,LockWorkStation"])
    elif osname == "Linux":
        if shutil.which("loginctl"):
            ok, msg = _run_cmd(parent, ["loginctl", "lock-session"])
        elif shutil.which("gnome-screensaver-command"):
            ok, msg = _run_cmd(parent, ["gnome-screensaver-command", "-l"])
        elif shutil.which("xdg-screensaver"):
            ok, msg = _run_cmd(parent, ["xdg-screensaver", "lock"])
        elif shutil.which("dm-tool"):
            ok, msg = _run_cmd(parent, ["dm-tool", "lock"])
        else:
            ok, msg = (False,
                       "Не найден инструмент блокировки (loginctl/gnome-screensaver/xdg-screensaver/dm-tool). "
                       "Установите/включите один из них.")
    elif osname == "Darwin":
        ok, msg = _run_cmd(
            parent,
            ["/System/Library/CoreServices/Menu Extras/User.menu/Contents/Resources/CGSession", "-suspend"]
        )
    else:
        ok, msg = False, f"Неподдерживаемая ОС: {osname}"

    if not ok:
        QMessageBox.critical(parent, "Ошибка блокировки", msg)


def _shutdown_now(parent):
    osname = platform.system()
    if not _confirm(parent, "Выключение", "Выключить ПК сейчас?"):
        return
    if osname == "Windows":
        ok, msg = _run_cmd(parent, ["shutdown", "/s", "/t", "0"])
    elif osname == "Linux":
        ok, msg = _run_cmd(parent, ["shutdown", "-h", "now"])
    elif osname == "Darwin":
        ok, msg = _run_cmd(parent, ["osascript", "-e", 'tell app "System Events" to shut down'])
    else:
        ok, msg = False, f"Неподдерживаемая ОС: {osname}"
    if not ok:
        QMessageBox.critical(parent, "Ошибка выключения", msg)


def _restart_now(parent):
    osname = platform.system()
    if not _confirm(parent, "Перезагрузка", "Перезагрузить ПК сейчас?"):
        return
    if osname == "Windows":
        ok, msg = _run_cmd(parent, ["shutdown", "/r", "/t", "0"])
    elif osname == "Linux":
        ok, msg = _run_cmd(parent, ["shutdown", "-r", "now"])
    elif osname == "Darwin":
        ok, msg = _run_cmd(parent, ["osascript", "-e", 'tell app "System Events" to restart'])
    else:
        ok, msg = False, f"Неподдерживаемая ОС: {osname}"
    if not ok:
        QMessageBox.critical(parent, "Ошибка перезагрузки", msg)


def _schedule_shutdown(parent, minutes: int):
    osname = platform.system()
    secs = max(0, int(minutes) * 60)
    if osname == "Windows":
        ok, msg = _run_cmd(parent, ["shutdown", "/s", "/t", str(secs)])
        if ok:
            QMessageBox.information(parent, "Запланировано",
                                    f"Выключение запланировано через {minutes} мин.\n"
                                    f"Чтобы отменить: Плагины → Питание ПК → Отменить отложенное")
        else:
            QMessageBox.critical(parent, "Ошибка планирования", msg)
    elif osname == "Linux":
        ok, msg = _run_cmd(parent, ["shutdown", "-h", f"+{minutes}"])
        if ok:
            QMessageBox.information(parent, "Запланировано",
                                    f"Выключение запланировано через {minutes} мин.\n"
                                    f"Отмена: `shutdown -c` (или пункт «Отменить отложенное»)")
        else:
            QMessageBox.critical(parent, "Ошибка планирования", msg)
    elif osname == "Darwin":
        ok, msg = _run_cmd(parent, ["sudo", "shutdown", "-h", f"+{minutes}"])
        if ok:
            QMessageBox.information(parent, "Запланировано",
                                    f"Выключение запланировано через {minutes} мин.")
        else:
            QMessageBox.critical(parent, "Ошибка планирования",
                                 f"{msg}\nВозможно, потребуется ввести пароль администратора в консоли.")
    else:
        QMessageBox.critical(parent, "Ошибка", f"Неподдерживаемая ОС: {osname}")


def _abort_scheduled(parent):
    osname = platform.system()
    if osname == "Windows":
        ok, msg = _run_cmd(parent, ["shutdown", "/a"])
    elif osname == "Linux":
        ok, msg = _run_cmd(parent, ["shutdown", "-c"])
    elif osname == "Darwin":
        ok, msg = _run_cmd(parent, ["sudo", "killall", "shutdown"])
    else:
        ok, msg = False, f"Неподдерживаемая ОС: {osname}"
    if ok:
        QMessageBox.information(parent, "Отложенное выключение", "Отменено.")
    else:
        QMessageBox.critical(parent, "Ошибка отмены", msg)


def on_enable(parent):
    global _installed, _submenu, _action_group
    if _installed:
        return
    try:
        mbar = parent.menuBar()
        plugins_menu = None
        for menu in mbar.children():
            try:
                if menu.title() == "Плагины":
                    plugins_menu = menu
                    break
            except Exception:
                continue
        if plugins_menu is None:
            plugins_menu = mbar.addMenu("Плагины")

        _submenu = QMenu("Питание ПК", parent)

        act_lock = QAction("Заблокировать экран", parent)
        act_lock.triggered.connect(lambda: _lock_pc(parent))
        _submenu.addAction(act_lock)
        _submenu.addSeparator()

        act_shutdown = QAction("Выключить", parent)
        act_restart = QAction("Перезагрузка", parent)
        _submenu.addAction(act_shutdown)
        _submenu.addAction(act_restart)
        _submenu.addSeparator()

        delay_menu = _submenu.addMenu("Отложить выключение")
        for mins in (5, 15, 30, 60):
            a = QAction(f"Через {mins} мин", parent)
            a.triggered.connect(lambda _, m=mins: _schedule_shutdown(parent, m))
            delay_menu.addAction(a)

        _submenu.addSeparator()
        act_abort = QAction("Отменить отложенное", parent)

        act_shutdown.triggered.connect(lambda: _shutdown_now(parent))
        act_restart.triggered.connect(lambda: _restart_now(parent))
        act_abort.triggered.connect(lambda: _abort_scheduled(parent))

        _submenu.addAction(act_abort)
        plugins_menu.addMenu(_submenu)

        _action_group = [act_lock, act_shutdown, act_restart, act_abort]
        _installed = True
    except Exception as e:
        print("Ошибка включения плагина power_control:", e)
        traceback.print_exc()


def on_disable(parent):
    global _installed, _submenu, _action_group
    try:
        if _submenu is not None:
            for menu in parent.menuBar().children():
                try:
                    if getattr(menu, "title", None) and menu.title() == "Плагины":
                        try:
                            menu.removeAction(_submenu.menuAction())
                        except Exception:
                            pass
                        break
                except Exception:
                    continue
            _submenu.deleteLater()
            _submenu = None

        for a in _action_group:
            try:
                a.deleteLater()
            except Exception:
                pass
        _action_group = []
    except Exception:
        pass
    _installed = False
