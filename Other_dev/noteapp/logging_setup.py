"""Настройка логирования сбоев и перехват необработанных исключений.

Сюда же вынесен фильтр Qt-сообщений (гасит болтливое
``QFileSystemWatcher::addPaths: list is empty`` и переводит остальное в лог).
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
import threading
import traceback

import faulthandler

try:
    from PySide6.QtCore import qInstallMessageHandler, QtMsgType
except Exception:
    qInstallMessageHandler = None
    QtMsgType = None


def _qt_message_handler(mode, context, message):
    try:
        if isinstance(message, str) and "QFileSystemWatcher::addPaths: list is empty" in message:
            return

        ctx = ""
        try:
            ctx = f"{getattr(context, 'file', '')}:{getattr(context, 'line', '')} {getattr(context, 'function', '')}"
        except Exception:
            ctx = ""
        msg = f"Qt[{int(mode)}] {ctx} | {message}"
        if QtMsgType is not None and mode == QtMsgType.QtFatalMsg:
            logging.critical(msg)
        else:
            logging.warning(msg)
    except Exception:
        pass


def install_qt_message_handler() -> None:
    if qInstallMessageHandler is None:
        return
    try:
        qInstallMessageHandler(_qt_message_handler)
    except Exception:
        pass


_fault_log_file = None


def _setup_crash_logging(log_path) -> None:
    """Лог с ротацией (2 МБ × 3) + отдельный файл для faulthandler.

    Раньше crash.log рос без ограничений, faulthandler писал в тот же файл
    (с ротацией на Windows так нельзя — открытый файл не переименовать),
    а StreamHandler(sys.stdout) под pythonw получал None.
    """
    global _fault_log_file
    log_path = Path(log_path)
    handlers: list[logging.Handler] = []
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(
            str(log_path), maxBytes=2_000_000, backupCount=3, encoding="utf-8",
        ))
    except Exception:
        pass
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    if handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            handlers=handlers,
        )
    try:
        fault_path = log_path.with_name(log_path.stem + "_fault" + log_path.suffix)
        _fault_log_file = open(str(fault_path), "a", encoding="utf-8")
        faulthandler.enable(_fault_log_file, all_threads=True)
    except Exception:
        pass


def handle_exception(exc_type, exc_value, exc_traceback, exc, tb):
    traceback.print_exception(exc_type, exc_value, exc_traceback)


def _global_excepthook(t, v, tb):
    try:
        logging.exception("Uncaught exception", exc_info=(t, v, tb))
    except Exception:
        pass


def _threading_excepthook(args):
    try:
        logging.exception(
            "Thread exception",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
    except Exception:
        pass


def install_exception_hooks() -> None:
    try:
        sys.excepthook = _global_excepthook
    except Exception:
        pass

    try:
        threading.excepthook = _threading_excepthook
    except Exception:
        pass
