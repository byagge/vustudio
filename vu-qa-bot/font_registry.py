#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Шрифты мокапа ВУ (Z_NOMER / Z_NOMER0).

Хранятся в assets/fonts/, подгружаются render_worker на Windows
перед запуском Photoshop (AddFontResourceEx, session-private).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger("font_registry")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FONTS_DIR = ROOT / "assets" / "fonts"
MANIFEST_NAME = "manifest.json"

_installed: set[str] = set()


@dataclass(frozen=True)
class FontSpec:
    id: str
    path: Path
    family: str
    postscript: str
    aliases: tuple[str, ...]

    def postscript_candidates(self) -> tuple[str, ...]:
        seen: list[str] = []
        for name in (self.postscript, *self.aliases):
            if name and name not in seen:
                seen.append(name)
        return tuple(seen)


def fonts_dir() -> Path:
    raw = os.getenv("FONTS_DIR", "").strip()
    return Path(raw) if raw else DEFAULT_FONTS_DIR


def manifest_path() -> Path:
    return fonts_dir() / MANIFEST_NAME


@lru_cache(maxsize=1)
def load_manifest() -> dict[str, Any]:
    path = manifest_path()
    if not path.is_file():
        raise FileNotFoundError(f"Font manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_font_specs() -> list[FontSpec]:
    data = load_manifest()
    out: list[FontSpec] = []
    for font_id, meta in (data.get("fonts") or {}).items():
        file_path = fonts_dir() / meta["file"]
        out.append(
            FontSpec(
                id=font_id,
                path=file_path,
                family=meta.get("family") or font_id,
                postscript=meta.get("postscript") or font_id,
                aliases=tuple(meta.get("aliases") or ()),
            )
        )
    return out


def get_font(font_id: str) -> FontSpec:
    for spec in list_font_specs():
        if spec.id == font_id:
            return spec
    raise KeyError(f"Unknown font id: {font_id}")


def verify_font_files() -> list[str]:
    """Проверка наличия TTF на диске."""
    errors: list[str] = []
    for spec in list_font_specs():
        if not spec.path.is_file():
            errors.append(f"Font file missing: {spec.path}")
    return errors


def _install_font_windows(path: Path) -> bool:
    import ctypes

    gdi32 = ctypes.windll.gdi32
    user32 = ctypes.windll.user32
    FR_PRIVATE = 0x10
    added = gdi32.AddFontResourceExW(str(path.resolve()), FR_PRIVATE, 0)
    if added <= 0:
        return False
    user32.SendMessageW(0xFFFF, 0x001D, 0, 0)  # WM_FONTCHANGE
    return True


def install_font(spec: FontSpec) -> bool:
    key = str(spec.path.resolve()).lower()
    if key in _installed:
        return True
    if not spec.path.is_file():
        log.error("font file not found: %s", spec.path)
        return False
    if sys.platform != "win32":
        log.debug("skip font install (not Windows): %s", spec.path.name)
        _installed.add(key)
        return True
    try:
        ok = _install_font_windows(spec.path)
    except Exception:
        log.exception("failed to install font %s", spec.path)
        return False
    if ok:
        _installed.add(key)
        log.info("font loaded: %s (%s)", spec.path.name, spec.postscript)
    else:
        log.error("AddFontResourceEx failed: %s", spec.path)
    return ok


def ensure_fonts_installed() -> list[str]:
    """
    Установить все шрифты из manifest в текущую сессию Windows.
    Возвращает список ошибок (пустой = OK).
    """
    errors = verify_font_files()
    if errors:
        return errors
    for spec in list_font_specs():
        if not install_font(spec):
            errors.append(f"Could not load font: {spec.path.name}")
    return errors


def build_font_job_fields(template: dict | None = None) -> dict[str, Any]:
    """
    Поля job JSON для render.jsx: by_layer_name, catalog, files.
    """
    tpl = template or {}
    manifest = load_manifest()
    layer_fields: dict[str, str] = dict(manifest.get("layer_fields") or {})
    layer_fields.update(tpl.get("fonts", {}).get("layer_fields") or tpl.get("layer_fields") or {})

    field_layers = tpl.get("field_layers") or {}
    by_layer_name: dict[str, str] = {}
    catalog: dict[str, dict[str, Any]] = {}
    files: dict[str, str] = {}

    for spec in list_font_specs():
        catalog[spec.id] = {
            "postscript": spec.postscript,
            "family": spec.family,
            "aliases": list(spec.aliases),
            "file": spec.path.name,
        }
        files[spec.id] = str(spec.path.resolve())

    for field, font_id in layer_fields.items():
        layer_name = field_layers.get(field)
        if not layer_name:
            continue
        spec = get_font(font_id)
        by_layer_name[layer_name] = spec.postscript

    payload: dict[str, Any] = {
        "by_layer_name": by_layer_name,
        "catalog": catalog,
        "files": files,
    }

    text_group_font = (tpl.get("fonts") or {}).get("text_group") or manifest.get("text_group")
    if text_group_font:
        payload["text_group_postscript"] = get_font(text_group_font).postscript

    alias_map: dict[str, list[str]] = {}
    for spec in list_font_specs():
        alias_map[spec.postscript] = list(spec.aliases)
    payload["aliases"] = alias_map

    return payload


def fonts_status() -> dict[str, Any]:
    specs = list_font_specs()
    return {
        "fonts_dir": str(fonts_dir()),
        "manifest": str(manifest_path()),
        "fonts": [
            {
                "id": s.id,
                "file": str(s.path),
                "exists": s.path.is_file(),
                "postscript": s.postscript,
                "installed": str(s.path.resolve()).lower() in _installed,
            }
            for s in specs
        ],
        "errors": verify_font_files(),
    }
