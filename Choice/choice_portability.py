from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from portable_paths import convert_settings_paths

SAFE_IMAGES = {".ico", ".png", ".jpg", ".jpeg", ".webp"}


def _internal_image(value: str, root: Path) -> Path | None:
    try:
        path = Path(value).resolve(strict=True)
        relative = path.relative_to(root.resolve(strict=True))
        if path.is_symlink() or path.suffix.casefold() not in SAFE_IMAGES:
            return None
        return relative
    except (OSError, ValueError):
        return None


def portability_report(data: dict, root: Path) -> dict:
    encoded = convert_settings_paths(data, root, encode=True)
    internal, missing, external = [], [], []
    for field in ("python_executable", "scripts_folder", "last_script_path", "last_workdir"):
        value = str(data.get(field) or "")
        if not value:
            continue
        converted = str(encoded.get(field) or "")
        if converted.startswith("$LAUNCHER"):
            internal.append(field)
            if not Path(value).exists():
                missing.append(value)
        elif Path(value).is_absolute():
            external.append(value)
    icons = data.get("per_script_icon") or {}
    if isinstance(icons, dict):
        for icon in icons.values():
            if isinstance(icon, str) and icon:
                if not Path(icon).is_file():
                    missing.append(icon)
                elif _internal_image(icon, root) is None:
                    external.append(icon)
    return {"portable_fields": internal, "missing": list(dict.fromkeys(missing)),
            "external": list(dict.fromkeys(external))}


def export_bundle(root: Path, settings_path: Path, output: Path) -> int:
    root, settings_path, output = Path(root), Path(settings_path), Path(output)
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Некорректные настройки Choice")
    encoded = convert_settings_paths(data, root, encode=True)
    images = []
    icon_paths = data.get("per_script_icon") or {}
    if isinstance(icon_paths, dict):
        for value in icon_paths.values():
            if not isinstance(value, str):
                continue
            relative = _internal_image(value, root)
            if relative is not None:
                images.append(relative)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".zip", delete=False) as tmp:
        temporary = Path(tmp.name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("launcher_config.json", json.dumps(encoded, ensure_ascii=False, indent=2))
            for relative in sorted(set(images)):
                archive.write(root / relative, "assets/" + relative.as_posix())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return len(set(images))


def import_bundle(root: Path, settings_path: Path, source: Path) -> int:
    root, settings_path, source = Path(root), Path(settings_path), Path(source)
    with zipfile.ZipFile(source, "r") as archive:
        members = archive.infolist()
        if len(members) > 200 or sum(x.file_size for x in members) > 30_000_000:
            raise ValueError("Архив слишком большой")
        if "launcher_config.json" not in archive.namelist():
            raise ValueError("В архиве нет настроек Choice")
        config_bytes = archive.read("launcher_config.json")
        if len(config_bytes) > 2_000_000:
            raise ValueError("Некорректный размер настроек")
        data = json.loads(config_bytes.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Некорректные настройки")
        assets = []
        for item in members:
            if item.filename == "launcher_config.json":
                continue
            if item.is_dir():
                continue
            name = item.filename
            if not name.startswith("assets/"):
                raise ValueError("Посторонние файлы в архиве")
            rel = Path(name[len("assets/"):])
            if (rel.is_absolute() or not rel.parts or ".." in rel.parts
                    or rel.suffix.casefold() not in SAFE_IMAGES
                    or item.external_attr >> 16 & 0o170000 == 0o120000):
                raise ValueError("Недопустимый путь файла в архиве")
            dest = root / rel
            if not dest.resolve(strict=False).is_relative_to(root.resolve(strict=False)):
                raise ValueError("Выход за пределы Launcher")
            assets.append((item, dest))
        for info, dest in assets:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.is_symlink():
                raise ValueError("Нельзя перезаписывать символическую ссылку")
            with archive.open(info) as inp, tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as out:
                temporary_asset = Path(out.name)
                shutil.copyfileobj(inp, out)
            try:
                os.replace(temporary_asset, dest)
            finally:
                temporary_asset.unlink(missing_ok=True)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    decoded = convert_settings_paths(data, root, encode=False)
    temporary = settings_path.with_suffix(settings_path.suffix + ".importing")
    backup = settings_path.with_suffix(settings_path.suffix + ".before_import")
    if settings_path.exists():
        shutil.copy2(settings_path, backup)
    try:
        temporary.write_text(json.dumps(decoded, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, settings_path)
    finally:
        temporary.unlink(missing_ok=True)
    return len(assets)
