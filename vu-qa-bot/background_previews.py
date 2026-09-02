#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Превью фонов «Вариант N» для панели.

Превью — обычные JPEG в assets/backgrounds/. Их можно положить руками или
извлечь из PSB: python scripts/extract_backgrounds.py
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from mockup_registry import get_mockup
from mockup_scene import background_layer_name, background_count, scene_from_template
from template_loader import load_template

ROOT = Path(__file__).resolve().parent
PREVIEW_DIR = Path(
    __import__("os").getenv("BACKGROUND_PREVIEW_DIR", str(ROOT.parent / "assets" / "backgrounds"))
)
SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")
THUMB_MAX_SIDE = 360

_extract_lock = threading.Lock()
_extract_state: dict[str, Any] = {"running": False, "done": 0, "total": 0, "message": ""}


def preview_file(bg_id: int) -> Path | None:
    for suffix in SUFFIXES:
        candidate = PREVIEW_DIR / f"{bg_id}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def list_previews(template_name: str = "mockup_hand") -> list[dict[str, Any]]:
    scene = scene_from_template(load_template(template_name))
    out: list[dict[str, Any]] = []
    for bg_id in range(1, background_count(scene) + 1):
        path = preview_file(bg_id)
        out.append(
            {
                "id": bg_id,
                "layer_name": background_layer_name(scene, bg_id),
                "has_preview": path is not None,
            }
        )
    return out


def extract_state() -> dict[str, Any]:
    with _extract_lock:
        return dict(_extract_state)


def _save_thumb(image, dest: Path) -> None:
    from PIL import Image

    img = image.convert("RGB") if image.mode != "RGB" else image
    img.thumbnail((THUMB_MAX_SIDE, THUMB_MAX_SIDE), Image.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "JPEG", quality=86, optimize=True)


def extract_previews(mockup: str = "hand", overwrite: bool = False) -> dict[str, Any]:
    """Достать слои «Вариант N» из PSB и сохранить как JPEG-превью."""
    try:
        import psd_tools  # noqa: F401
    except ImportError:
        return {"ok": False, "saved": 0, "message": "psd_tools не установлен"}

    from psb_utils import iter_nested_psbs

    spec = get_mockup(mockup)
    psb = spec.resolve_path()
    if not psb.is_file():
        return {"ok": False, "saved": 0, "message": f"PSB не найден: {psb}"}

    scene = scene_from_template(load_template(spec.template))
    total = background_count(scene)
    wanted = {background_layer_name(scene, i): i for i in range(1, total + 1)}

    with _extract_lock:
        _extract_state.update(running=True, done=0, total=total, message="Открываем PSB…")

    saved = 0
    errors: list[str] = []
    try:
        for _path, psd in iter_nested_psbs(psb):
            for layer in psd.descendants():
                bg_id = wanted.get(layer.name)
                if bg_id is None:
                    continue
                dest = PREVIEW_DIR / f"{bg_id}.jpg"
                if dest.is_file() and not overwrite:
                    continue
                try:
                    image = layer.composite()
                    if image is None:
                        continue
                    _save_thumb(image, dest)
                    saved += 1
                except Exception as exc:  # noqa: BLE001 — один слой не должен ронять всё
                    errors.append(f"{layer.name}: {exc}")
                with _extract_lock:
                    _extract_state.update(done=saved, message=f"Сохранён фон {bg_id}")
    finally:
        with _extract_lock:
            _extract_state.update(running=False, message="Готово")

    return {
        "ok": saved > 0,
        "saved": saved,
        "total": total,
        "dir": str(PREVIEW_DIR),
        "errors": errors[:10],
        "message": f"Сохранено превью: {saved}" if saved else "Слои «Вариант N» не найдены",
    }


def extract_previews_async(mockup: str = "hand", overwrite: bool = False) -> dict[str, Any]:
    with _extract_lock:
        if _extract_state["running"]:
            return {"started": False, "message": "Извлечение уже идёт"}
        _extract_state.update(running=True, done=0, total=0, message="Запуск…")

    def run() -> None:
        try:
            extract_previews(mockup=mockup, overwrite=overwrite)
        finally:
            with _extract_lock:
                _extract_state["running"] = False

    threading.Thread(target=run, daemon=True).start()
    time.sleep(0.05)
    return {"started": True, "message": "Извлечение запущено"}
