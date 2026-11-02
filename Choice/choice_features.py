from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QProcess, QTimer
from PySide6.QtWidgets import QFileDialog, QMessageBox

from choice_integration import (atomic_json, control_dir, heartbeat_file, health_status,
                                receive_requests, resolve_script, supported_probe)
from choice_portability import export_bundle, import_bundle, portability_report


class ChoiceFeatures:
    def _start_choice_control(self):
        self._choice_health_failures = {}
        self._choice_health_restarts = {}
        self._choice_health_last = {}
        self._choice_control_timer = QTimer(self)
        self._choice_control_timer.timeout.connect(self._choice_service_tick)
        self._choice_control_timer.start(1800)

    def _choice_entries(self):
        known = {}
        for card in self.settings.home_cards or []:
            if isinstance(card, dict):
                path = str(card.get("path") or "")
                if path:
                    known[path] = str(card.get("name") or Path(path).stem)
        for path in [*(self.settings.autostart_scripts or []), *(self.settings.favorites or [])]:
            if isinstance(path, str) and path:
                known.setdefault(path, Path(path).stem)
        for path in self.all_scripts:
            known.setdefault(str(path), path.stem)
        result = []
        for path, name in known.items():
            active = [(rid, proc) for rid, proc in self.processes.items()
                      if proc is not None and proc.state() != QProcess.NotRunning
                      and self.proc_info.get(rid, {}).get("script") == path]
            state, detail = "остановлен", "Процесс не запущен"
            if active:
                state, detail = "запущен", "Функциональность не проверялась"
                if supported_probe(path):
                    rid, _ = active[-1]
                    key = str(self.proc_info.get(rid, {}).get("health_key") or "")
                    if key:
                        from choice_dev import app_folder
                        state, detail = health_status(
                            heartbeat_file(app_folder(), path), key=key,
                            started=self.proc_start_time.get(rid, time.time()))
            result.append({"path": path, "name": name, "running": bool(active),
                           "state": state, "detail": detail})
        return result

    def _choice_stop(self, path):
        ids = [rid for rid, proc in self.processes.items()
               if proc is not None and proc.state() != QProcess.NotRunning
               and self.proc_info.get(rid, {}).get("script") == path]
        for rid in ids:
            self.processes[rid].terminate()
        if ids:
            QTimer.singleShot(2500, lambda ids=tuple(ids): self._kill_still_running(list(ids)))
        return bool(ids)

    def _choice_restart(self, path):
        self._choice_stop(path)
        QTimer.singleShot(3100, lambda path=path: self._start_script_direct(path, clear_output=False))

    def _choice_handle_request(self, action, target):
        entries = self._choice_entries()
        if action == "status" and not target.strip():
            running = [f"{x['name']}: {x['state']}" for x in entries if x["running"]]
            errors = [f"{x['name']}: {x['detail']}" for x in entries if x["state"] == "ошибка"]
            message = "Работают: " + (", ".join(running[:12]) or "нет")
            if errors:
                message += "; проблемы: " + "; ".join(errors[:6])
            return {"ok": True, "message": message}
        path, error = resolve_script(target, entries)
        if not path:
            return {"ok": False, "message": error}
        entry = next(item for item in entries if item["path"] == path)
        if action == "status":
            return {"ok": True, "message": f"{entry['name']}: {entry['state']}. {entry['detail']}"}
        if not Path(path).is_file():
            return {"ok": False, "message": "Файл приложения отсутствует"}
        if action == "start":
            if entry["running"]:
                return {"ok": True, "message": f"{entry['name']} уже запущен"}
            self._start_script_direct(path, clear_output=False)
            return {"ok": True, "message": f"Запуск {entry['name']} запрошен"}
        if action == "stop":
            if not self._choice_stop(path):
                return {"ok": True, "message": f"{entry['name']} не запущен через Choice"}
            return {"ok": True, "message": f"Остановка {entry['name']} запрошена"}
        if action == "restart":
            if entry["running"]:
                self._choice_restart(path)
            else:
                self._start_script_direct(path, clear_output=False)
            return {"ok": True, "message": f"Перезапуск {entry['name']} запланирован"}
        return {"ok": False, "message": "Недопустимая команда"}

    def _choice_service_tick(self):
        try:
            from choice_dev import app_folder
            entries = self._choice_entries()
            for entry in entries:
                path = entry["path"]
                if not entry["running"] or not supported_probe(path):
                    self._choice_health_failures.pop(path, None)
                    self._choice_health_last.pop(path, None)
                    continue
                state = entry["state"]
                if state == "ошибка" and self._choice_health_last.get(path) != state:
                    self._append_error(f"Диагностика {entry['name']}: {entry['detail']}")
                self._choice_health_last[path] = state
                if state != "ошибка":
                    self._choice_health_failures[path] = 0
                    continue
                failures = self._choice_health_failures.get(path, 0) + 1
                self._choice_health_failures[path] = failures
                history = [t for t in self._choice_health_restarts.get(path, [])
                           if time.time() - t < 600]
                self._choice_health_restarts[path] = history
                if failures >= 3 and len(history) < 2:
                    self._choice_health_restarts[path].append(time.time())
                    self._choice_health_failures[path] = 0
                    self._append_error(f"Автовосстановление {entry['name']}: перезапуск")
                    self._choice_restart(path)
            atomic_json(control_dir(app_folder()) / "status.json", {
                "ts": time.time(), "apps": entries, "choice_pid": os.getpid(),
            })
            receive_requests(app_folder(), self._choice_handle_request)
        except Exception as exc:
            self._append_error("Choice Control: " + str(exc)[:200])

    def _show_choice_health(self):
        from choice_dev import app_folder
        entries = self._choice_entries()
        lines = [f"{x['name']}: {x['state']} — {x['detail']}"
                 for x in entries if x["running"]]
        report = portability_report(self.settings.__dict__, app_folder())
        lines += ["", f"Отсутствующих файлов: {len(report['missing'])}",
                  f"Внешних путей: {len(report['external'])}"]
        lines.extend(report["missing"][:10])
        QMessageBox.information(self, "Состояние Choice",
                                "\n".join(lines) if lines else "Нет запущенных приложений")

    def _export_choice_settings(self):
        from choice_dev import app_folder, config_file
        self._save_settings()
        target, _ = QFileDialog.getSaveFileName(
            self, "Экспорт настроек Choice", str(app_folder() / "Choice_backup.zip"),
            "Архив ZIP (*.zip)")
        if not target:
            return
        try:
            images = export_bundle(app_folder(), config_file(), Path(target))
            QMessageBox.information(self, "Экспорт выполнен",
                                    f"Настройки и {images} файлов иконок сохранены.\n{target}")
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Ошибка экспорта", str(exc))

    def _import_choice_settings(self):
        from choice_dev import app_folder, config_file, Settings, detect_system_python
        if any(p.state() != QProcess.NotRunning for p in self.processes.values()):
            QMessageBox.warning(self, "Импорт настроек",
                                "Перед импортом останови приложения, которыми управляет Choice.")
            return
        source, _ = QFileDialog.getOpenFileName(
            self, "Импорт настроек Choice", str(app_folder()), "Архив ZIP (*.zip)")
        if not source:
            return
        if QMessageBox.question(
            self, "Импорт настроек", "Заменить настройки Choice из архива?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        try:
            images = import_bundle(app_folder(), config_file(), Path(source))
            self.settings = Settings.load(config_file())
            self.python_field.setText(self.settings.python_executable or detect_system_python())
            self.folder_field.setText(self.settings.scripts_folder or str(app_folder()))
            self.scan_checkbox.setChecked(bool(self.settings.scan_subfolders))
            self._refresh_script_list(save=False)
            self._refresh_home_cards()
            self._refresh_recent_list()
            self._apply_filters()
            QMessageBox.information(self, "Импорт выполнен",
                                    f"Восстановлено иконок: {images}.\n"
                                    "Чтобы применить все параметры, перезапусти Choice.")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.warning(self, "Ошибка импорта", str(exc))
