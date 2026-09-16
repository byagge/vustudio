#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Загрузка пользовательского фона для мокапа «рука+фоны»."""
from __future__ import annotations

import io
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

log = logging.getLogger("background_service")

MIN_BYTES = 1024
MAX_BYTES = 15 * 1024 * 1024
MIN_SIDE = 320
MAX_SIDE = 8000


@dataclass
class BackgroundResult:
    ok: bool
    path: Path | None = None
    message: str = ""

    @property
    def path_str(self) -> str | None:
        return str(self.path.resolve()) if self.path else None


def backgrounds_dir() -> Path:
    root = Path(os.getenv("RENDER_OUTPUT_DIR", Path(__file__).resolve().parent.parent / "output"))
    p = root / "backgrounds"
    p.mkdir(parents=True, exist_ok=True)
    return p


def validate_background_bytes(data: bytes) -> None:
    if len(data) < MIN_BYTES:
        raise ValueError("Файл слишком маленький для фона")
    if len(data) > MAX_BYTES:
        raise ValueError("Файл больше 15 МБ")
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
    except Exception as e:
        raise ValueError("Не удалось прочитать изображение") from e


def _prepare_image(data: bytes, dest: Path) -> Path:
    with Image.open(io.BytesIO(data)) as im:
        im = im.convert("RGB")
        w, h = im.size
        if w < MIN_SIDE or h < MIN_SIDE:
            raise ValueError(f"Минимальный размер фона {MIN_SIDE}px по стороне")
        if max(w, h) > MAX_SIDE:
            scale = MAX_SIDE / max(w, h)
            im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
        im.save(dest, format="JPEG", quality=92, optimize=True)
    return dest


def save_upload(data: bytes, user_id: int | str, *, suffix: str = ".jpg") -> Path:
    validate_background_bytes(data)
    path = backgrounds_dir() / f"bg_{user_id}{suffix if suffix.startswith('.') else '.jpg'}"
    return _prepare_image(data, path)


def prepare_upload(data: bytes, user_id: int | str) -> BackgroundResult:
    try:
        path = save_upload(data, user_id)
        return BackgroundResult(ok=True, path=path, message="Фон сохранён")
    except ValueError as e:
        return BackgroundResult(ok=False, message=str(e))
    except Exception as e:
        log.exception("background upload failed")
        return BackgroundResult(ok=False, message=str(e))


def background_status_label(opts) -> str:
    path = getattr(opts, "custom_background_path", None)
    if path and Path(path).is_file():
        return "свой фон"
    bg = int(getattr(opts, "background", 1) or 1)
    return f"пресет #{bg}"
