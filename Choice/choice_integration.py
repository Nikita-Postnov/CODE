from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path


def control_dir(root: Path) -> Path:
    return Path(root) / "Data" / "Choice" / "control"


def heartbeat_file(root: Path, script: str) -> Path:
    identity = os.path.normcase(os.path.abspath(script)).encode("utf-8", errors="surrogatepass")
    return control_dir(root) / "health" / (hashlib.sha256(identity).hexdigest()[:24] + ".json")


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def health_status(path: Path, *, key: str, started: float, now: float | None = None) -> tuple[str, str]:
    now = time.time() if now is None else now
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return ("ожидание", "От приложения пока нет диагностического сигнала") if now - started < 15 else ("ошибка", "Диагностический сигнал не поступает")
    if not isinstance(data, dict) or data.get("key") != key:
        return ("ожидание", "Ожидание сигнала от текущего экземпляра") if now - started < 15 else ("ошибка", "Нет сигнала текущего экземпляра")
    timestamp = data.get("ts")
    if not isinstance(timestamp, (int, float)) or timestamp > now + 3 or timestamp < started - 3:
        return ("ошибка", "Некорректное время диагностического сигнала")
    if now - timestamp > 9:
        return ("ошибка", "Диагностический сигнал устарел")
    if data.get("ok") is not True:
        return ("ошибка", str(data.get("detail") or "Основные компоненты не отвечают")[:200])
    return "исправен", str(data.get("detail") or "Основные компоненты отвечают")[:200]


def supported_probe(script: str) -> bool:
    return Path(script).stem.casefold().startswith("punto_like_work_safe")


def app_aliases(name: str) -> set[str]:
    name = Path(name).stem.casefold().replace("_", " ").replace("-", " ").strip()
    result = {name, re.sub(r"\s+", " ", name)}
    if "punto" in name:
        result.update(("punto", "пунто", "punto like", "пунто лайк"))
    if "nicholas" in name or "никол" in name:
        result.update(("nicholas", "николас", "ник"))
    return result


def resolve_script(target: str, entries: list[dict]) -> tuple[str | None, str]:
    target = re.sub(r"\s+", " ", str(target or "").casefold().strip(" .!?")).strip()
    if not target:
        return None, "Название приложения не указано"
    matches = []
    for entry in entries:
        path = str(entry.get("path") or "")
        name = str(entry.get("name") or Path(path).stem)
        aliases = app_aliases(name) | app_aliases(path)
        if target in aliases or target == name.casefold() or target == Path(path).name.casefold():
            if path not in matches:
                matches.append(path)
    if len(matches) == 1:
        return matches[0], ""
    if not matches:
        return None, "Приложение не найдено в Choice. Уточни название."
    return None, "Найдено несколько приложений с таким названием. Уточни название."


def send_request(root: Path, action: str, target: str = "") -> str:
    if action not in ("status", "start", "stop", "restart"):
        raise ValueError("Недопустимая команда")
    request_id = uuid.uuid4().hex
    atomic_json(control_dir(root) / "inbox" / (request_id + ".json"), {
        "id": request_id, "ts": time.time(), "action": action, "target": target[:180],
    })
    return request_id


def read_reply(root: Path, request_id: str, *, remove: bool = True) -> dict | None:
    if not re.fullmatch(r"[a-f0-9]{32}", request_id):
        return None
    path = control_dir(root) / "outbox" / (request_id + ".json")
    try:
        answer = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    if remove:
        path.unlink(missing_ok=True)
    return answer if isinstance(answer, dict) else None


def receive_requests(root: Path, handler, *, limit: int = 12) -> int:
    base = control_dir(root)
    inbox = base / "inbox"
    if not inbox.is_dir():
        return 0
    handled = 0
    for path in sorted(inbox.glob("*.json"))[:limit]:
        if not re.fullmatch(r"[a-f0-9]{32}\.json", path.name):
            continue
        try:
            if path.stat().st_size > 8192:
                path.unlink(missing_ok=True)
                continue
            request = json.loads(path.read_text(encoding="utf-8"))
            path.unlink(missing_ok=True)
            if not isinstance(request, dict) or request.get("id") != path.stem:
                continue
            if request.get("action") not in ("status", "start", "stop", "restart"):
                response = {"ok": False, "message": "Недопустимая команда"}
            elif not isinstance(request.get("ts"), (int, float)) or abs(time.time() - request["ts"]) > 60:
                response = {"ok": False, "message": "Команда устарела"}
            elif not isinstance(request.get("target", ""), str) or len(request.get("target", "")) > 180:
                response = {"ok": False, "message": "Недопустимое название"}
            else:
                try:
                    response = handler(request["action"], request.get("target", ""))
                except Exception:
                    response = {"ok": False, "message": "Ошибка обработки команды Choice"}
            atomic_json(base / "outbox" / path.name, response)
            handled += 1
        except (OSError, ValueError, UnicodeError):
            path.unlink(missing_ok=True)
            continue
    for folder in (base / "outbox",):
        if folder.is_dir():
            now = time.time()
            for old in list(folder.glob("*.json"))[:80]:
                try:
                    if now - old.stat().st_mtime > 3600:
                        old.unlink(missing_ok=True)
                except OSError:
                    pass
    return handled
