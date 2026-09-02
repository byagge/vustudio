#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ИИ-портрет для smart object Photo (task3.md).

Приоритет resolve_portrait():
  1. portrait_path (файл существует)
  2. generate_portrait → POST PORTRAIT_API_URL (JSON fields → JPEG)
  3. null — placeholder в PSB
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from portrait_ai import generate_raw_portrait
from portrait_config import PortraitSettings
from portrait_preprocess import portrait_meta, prepare_portrait_file, validate_image_bytes
from portrait_prompt import portrait_cache_key
from render_models import RenderTask

log = logging.getLogger("portrait_service")


@dataclass
class PortraitResult:
    ok: bool
    path: Path | None = None
    message: str = ""
    source: str = ""
    provider: str = ""

    @property
    def path_str(self) -> str | None:
        return str(self.path.resolve()) if self.path else None


def portraits_dir() -> Path:
    root = Path(os.getenv("RENDER_OUTPUT_DIR", Path(__file__).resolve().parent.parent / "output"))
    p = root / "portraits"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _cache_path(fields: dict[str, Any]) -> Path:
    return portraits_dir() / f"cache_{portrait_cache_key(fields)}.jpg"


def save_upload(data: bytes, user_id: int, suffix: str = ".jpg") -> Path:
    """task3 §5.1: output/portraits/user_{user_id}.jpg"""
    validate_image_bytes(data)
    cfg = PortraitSettings.from_env()
    path = portraits_dir() / f"user_{user_id}{suffix}"
    path.write_bytes(data)
    return prepare_portrait_file(path, path, settings=cfg)


def prepare_upload(data: bytes, user_id: int, *, suffix: str = ".jpg") -> PortraitResult:
    try:
        path = save_upload(data, user_id, suffix=suffix)
    except ValueError as e:
        return PortraitResult(ok=False, message=str(e))
    except Exception as e:
        log.exception("Upload portrait failed")
        return PortraitResult(ok=False, message=str(e))
    return PortraitResult(ok=True, path=path, source="upload", message="Фото сохранено")


def _http_api_generate(fields: dict[str, Any], out: Path, cfg: PortraitSettings) -> bool:
    """Прямой вызов PORTRAIT_API_URL (task3 §5.2)."""
    url = (cfg.api_url or "").strip()
    if not url:
        log.warning("PORTRAIT_API_URL не задан — пропуск генерации портрета")
        return False
    req = urllib.request.Request(
        url,
        data=json.dumps(fields, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_sec) as resp:
            data = resp.read()
        if len(data) < 100:
            log.error("Portrait API empty response")
            return False
        out.write_bytes(data)
        return True
    except urllib.error.HTTPError as e:
        log.error("Portrait API HTTP %s: %s", e.code, e.read()[:200])
        return False
    except Exception:
        log.exception("Portrait API failed")
        return False


def finalize_portrait(raw: Path, *, dest: Path, settings: PortraitSettings | None = None) -> Path:
    cfg = settings or PortraitSettings.from_env()
    return prepare_portrait_file(raw, dest, settings=cfg)


def generate_ai_portrait(
    fields: dict[str, Any],
    *,
    job_id: str | None = None,
    settings: PortraitSettings | None = None,
) -> PortraitResult:
    """ИИ-портрет → portraits/gen_{job_id}.jpg (task3 §5.2, §6)."""
    cfg = settings or PortraitSettings.from_env()
    jid = job_id or portrait_cache_key(fields)
    out = portraits_dir() / f"gen_{jid}.jpg"

    if cfg.cache_enabled:
        cached = _cache_path(fields)
        if cached.is_file():
            shutil.copy2(cached, out)
            return PortraitResult(ok=True, path=out, source="cache", provider="cache")

    raw = portraits_dir() / f"gen_{jid}_raw.jpg"
    gen = generate_raw_portrait(fields, raw, settings=cfg)
    if not gen.ok or not gen.raw_path or not gen.raw_path.is_file():
        return PortraitResult(
            ok=False,
            message=gen.message or "Генерация не удалась",
            provider=gen.provider,
        )

    try:
        finalize_portrait(gen.raw_path, dest=out, settings=cfg)
    except Exception as e:
        log.exception("Portrait finalize failed")
        return PortraitResult(ok=False, message=str(e), provider=gen.provider)

    if cfg.cache_enabled:
        shutil.copy2(out, _cache_path(fields))

    return PortraitResult(
        ok=True,
        path=out,
        source=f"ai_{gen.provider}",
        provider=gen.provider,
        message="ИИ-портрет готов",
    )


def resolve_portrait(task: RenderTask) -> str | None:
    opts = task.options
    cfg = PortraitSettings.from_env()

    if opts.portrait_path and Path(opts.portrait_path).is_file():
        src = Path(opts.portrait_path)
        if src.parent.resolve() == portraits_dir().resolve() and src.name.startswith("user_"):
            return str(src.resolve())
        out = portraits_dir() / f"prep_{task.job_id}.jpg"
        try:
            return str(finalize_portrait(src, dest=out, settings=cfg).resolve())
        except Exception:
            log.exception("Failed to prepare uploaded portrait")
            return str(src.resolve())

    if not opts.generate_portrait:
        return None

    result = generate_ai_portrait(task.fields, job_id=task.job_id, settings=cfg)
    if not result.ok:
        log.error("AI portrait failed for job %s: %s", task.job_id, result.message)
        return None
    return result.path_str


def portrait_job_payload(portrait_path: str | None) -> dict[str, Any]:
    cfg = PortraitSettings.from_env()
    meta = portrait_meta(cfg)
    if portrait_path:
        meta["path"] = portrait_path
    return meta


def portrait_status_label(opts) -> str:
    if getattr(opts, "portrait_path", None):
        return "📷 своё фото"
    if getattr(opts, "generate_portrait", False):
        return "🧑 ИИ (при отрисовке)"
    return "без портрета"
