"""Безопасное копирование вложений в переносимые папки заметок."""

import os
import shutil
from pathlib import Path


def copy_attachment_without_overwrite(
    source: str | Path,
    destination_folder: str | Path,
) -> Path:
    """Копирует файл, не перезаписывая прежнее вложение с тем же названием."""
    original = Path(source)
    if not original.is_file():
        raise FileNotFoundError(original)

    folder = Path(destination_folder)
    folder.mkdir(parents=True, exist_ok=True)

    for index in range(10000):
        filename = (
            original.name if index == 0
            else f"{original.stem} ({index}){original.suffix}"
        )
        destination = folder / filename
        try:
            with destination.open("xb") as target:
                try:
                    with original.open("rb") as incoming:
                        shutil.copyfileobj(incoming, target, length=1024 * 1024)
                    target.flush()
                    os.fsync(target.fileno())
                except BaseException:
                    target.close()
                    destination.unlink(missing_ok=True)
                    raise
            return destination
        except FileExistsError:
            continue

    raise FileExistsError(
        f"Слишком много вложений с названием {original.name!r}"
    )
