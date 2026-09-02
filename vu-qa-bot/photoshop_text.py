#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Подстановка текста в Photoshop — единая функция.

Пайплайн:
  текстовый блок → парсер → JSON полей → job → JSX/COM → PSB/PSD + JPG

Пример:
    from photoshop_text import substitute_text

    result = substitute_text(open("block.txt").read(), mockup="blank")
    if result.ok:
        print(result.psd_path, result.jpg_path)
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from layer_values import build_photoshop_job, build_render_payload, field_values, load_template
from mockup_registry import MOCKUPS, get_mockup
from photoshop_renderer import PhotoshopRenderer, RenderSettings
from photoshop_server import ensure_server_ready, get_server_status, is_server_mode
from render_models import RenderOptions, RenderTask, block_to_dict
from render_queue import RenderQueue
from text_parser import TextParseError, VuTextBlock, parse_client_block
from text_realism import ensure_back_table, validate_block

log = logging.getLogger("photoshop_text")

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class SubstituteResult:
    ok: bool
    message: str
    job_id: str = ""
    status: str = ""
    psd_path: Path | None = None
    jpg_path: Path | None = None
    job_json_path: Path | None = None
    fields: dict[str, Any] = field(default_factory=dict)
    layers_by_field: dict[str, str] = field(default_factory=dict)
    layers_by_name: dict[str, str] = field(default_factory=dict)

    @property
    def output_paths(self) -> list[Path]:
        return [p for p in (self.psd_path, self.jpg_path) if p]


def _queue_dir() -> Path:
    p = Path(os.getenv("RENDER_QUEUE_DIR", str(ROOT / "queue")))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _output_dir(custom: Path | None = None) -> Path:
    p = custom or Path(os.getenv("RENDER_OUTPUT_DIR", str(ROOT / "output")))
    p.mkdir(parents=True, exist_ok=True)
    return p


def parse_text_block(text_block: str) -> VuTextBlock:
    """Разбор блока полей с автодополнением таблицы категорий."""
    block = parse_client_block(text_block)
    ensure_back_table(block)
    return block


def validate_text_block(text_block: str) -> list[str]:
    try:
        block = parse_text_block(text_block)
    except TextParseError as e:
        return [str(e)]
    return validate_block(block)


def prepare_substitute_job(
    text_block: str,
    *,
    mockup: str = "blank",
    background: int = 1,
    portrait_path: str | None = None,
    generate_portrait: bool = False,
    output_dir: Path | None = None,
    job_id: str | None = None,
) -> tuple[dict[str, Any], Path]:
    """
    Собрать JSON-задание для JSX без запуска Photoshop.
    Возвращает (job_dict, path_to_job_file).
    """
    errors = validate_text_block(text_block)
    if errors:
        raise ValueError("; ".join(errors))

    opts = RenderOptions(
        mockup=mockup,
        background=background,
        portrait_path=portrait_path,
        generate_portrait=generate_portrait,
    ).normalized()

    task = RenderTask.create(text_block, options=opts)
    if job_id:
        task.job_id = job_id

    out = _output_dir(output_dir)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mockup_path = get_mockup(opts.mockup).resolve_path()
    ext = mockup_path.suffix.lower() or ".psd"
    base = out / f"vu_{stamp}_{task.job_id}"
    job_path = base.with_suffix(".job.json")

    job = build_photoshop_job(
        task,
        output_psd=base.with_suffix(ext),
        output_jpg=base.with_suffix(".jpg"),
    )
    job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    return job, job_path


def substitute_text(
    text_block: str,
    *,
    mockup: str = "blank",
    background: int = 1,
    portrait_path: str | None = None,
    generate_portrait: bool = False,
    output_dir: Path | None = None,
    dry_run: bool = False,
) -> SubstituteResult:
    """
    Полная подстановка текста в Photoshop-мокап.

    :param text_block: блок полей ВУ (формат заказчика)
    :param mockup: blank | hand | original
    :param background: 1–10 (для hand/original)
    :param portrait_path: путь к JPG для smart object Photo
    :param generate_portrait: запросить ИИ-портрет (PORTRAIT_API_URL)
    :param output_dir: каталог для PSB/PSD и JPG
    :param dry_run: только собрать job JSON, без Photoshop
    """
    try:
        block = parse_text_block(text_block)
    except TextParseError as e:
        return SubstituteResult(ok=False, message=str(e))

    errors = validate_block(block)
    if errors:
        return SubstituteResult(ok=False, message="; ".join(errors))

    mockup_spec = get_mockup(mockup)
    if not mockup_spec.resolve_path().is_file():
        return SubstituteResult(
            ok=False,
            message=f"Файл мокапа не найден: {mockup_spec.resolve_path()}",
        )

    opts = RenderOptions(
        mockup=mockup,
        background=background,
        portrait_path=portrait_path,
        generate_portrait=generate_portrait,
    ).normalized()

    task = RenderTask.create(text_block, options=opts)
    tpl = load_template(mockup_spec.template)
    payload = build_render_payload(block, tpl, options=opts, portrait_path=portrait_path)

    if dry_run:
        job, job_path = prepare_substitute_job(
            text_block,
            mockup=mockup,
            background=background,
            portrait_path=portrait_path,
            generate_portrait=generate_portrait,
            output_dir=output_dir,
            job_id=task.job_id,
        )
        return SubstituteResult(
            ok=True,
            message="Job подготовлен (dry_run)",
            job_id=task.job_id,
            job_json_path=job_path,
            fields=block_to_dict(block),
            layers_by_field=payload.get("layers_by_field", {}),
            layers_by_name=payload.get("layers_by_name", {}),
            psd_path=Path(job["output_psd"]),
            jpg_path=Path(job["output_jpg"]),
        )

    if is_server_mode():
        return SubstituteResult(
            ok=False,
            message=(
                "RENDER_MODE=server: Photoshop запускается только через render_worker. "
                "Используйте substitute_text_queued() или render_cli.py --queue --wait."
            ),
            job_id=task.job_id,
            fields=block_to_dict(block),
        )

    render_result = PhotoshopRenderer(RenderSettings.from_env()).render_task(task)
    if render_result.status != "ok":
        return SubstituteResult(
            ok=False,
            message=render_result.message,
            job_id=task.job_id,
            fields=block_to_dict(block),
            layers_by_field=payload.get("layers_by_field", {}),
            layers_by_name=payload.get("layers_by_name", {}),
        )

    psd = jpg = job_path = None
    out = _output_dir(output_dir)
    jobs = sorted(out.glob(f"*_{task.job_id}.job.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if jobs:
        job_path = jobs[0]

    for p in render_result.output_paths:
        if p.suffix.lower() in {".psd", ".psb"}:
            psd = p
        elif p.suffix.lower() in {".jpg", ".jpeg"}:
            jpg = p

    return SubstituteResult(
        ok=True,
        message="Готово",
        job_id=task.job_id,
        psd_path=psd,
        jpg_path=jpg,
        job_json_path=job_path,
        fields=block_to_dict(block),
        layers_by_field=payload.get("layers_by_field", {}),
        layers_by_name=payload.get("layers_by_name", {}),
    )


def substitute_text_queued(
    text_block: str,
    *,
    mockup: str = "blank",
    background: int = 1,
    portrait_path: str | None = None,
    generate_portrait: bool = False,
    chat_id: int | None = None,
    user_id: int | None = None,
) -> SubstituteResult:
    """Поставить задачу в очередь render-worker. Возвращает job_id."""
    errors = validate_text_block(text_block)
    if errors:
        return SubstituteResult(ok=False, message="; ".join(errors))

    server_err = ensure_server_ready()
    if server_err:
        return SubstituteResult(ok=False, message=server_err)

    opts = RenderOptions(
        mockup=mockup,
        background=background,
        portrait_path=portrait_path,
        generate_portrait=generate_portrait,
    ).normalized()
    from mockup_scene import validate_scene_options

    scene_errors = validate_scene_options(opts)
    if scene_errors:
        return SubstituteResult(ok=False, message="; ".join(scene_errors))

    task = RenderTask.create(
        text_block,
        options=opts,
        chat_id=chat_id,
        user_id=user_id,
    )
    RenderQueue(_queue_dir()).enqueue(task)
    return SubstituteResult(
        ok=True,
        message="В очереди",
        status="pending",
        job_id=task.job_id,
        fields=task.fields,
    )


def wait_substitute(job_id: str, timeout: float = 900, poll: float = 2.0) -> SubstituteResult:
    """Дождаться результата задачи из очереди."""
    task = RenderQueue(_queue_dir()).wait_done(job_id, timeout=timeout, poll=poll)
    if not task:
        return SubstituteResult(ok=False, message="Таймаут или задача не найдена", job_id=job_id)
    if task.status == "failed":
        return SubstituteResult(
            ok=False,
            message=task.error or "Ошибка рендера",
            job_id=job_id,
            status=task.status,
        )
    return SubstituteResult(
        ok=True,
        message="Готово",
        job_id=job_id,
        status=task.status,
        psd_path=Path(task.psd_path) if task.psd_path else None,
        jpg_path=Path(task.jpg_path) if task.jpg_path else None,
        fields=task.fields,
    )


def get_substitute_status(job_id: str) -> SubstituteResult | None:
    """Статус задачи в очереди (pending / processing / done / failed)."""
    task = RenderQueue(_queue_dir()).get(job_id)
    if not task:
        return None
    ok = task.status == "done"
    return SubstituteResult(
        ok=ok,
        message=task.error or task.status,
        job_id=job_id,
        status=task.status,
        psd_path=Path(task.psd_path) if task.psd_path else None,
        jpg_path=Path(task.jpg_path) if task.jpg_path else None,
        fields=task.fields,
    )


def verify_template(template_name: str = "mockup_blank") -> dict:
    """Сверка templates/*.json с PSB (task2 §8-9)."""
    from psb_utils import verify_template_against_psb

    return verify_template_against_psb(template_name)


def generate_portrait(
    text_block: str | None = None,
    *,
    fields: dict | None = None,
    job_id: str | None = None,
) -> "PortraitResult":
    """Сгенерировать ИИ-портрет по блоку или JSON полей."""
    from portrait_service import PortraitResult, generate_ai_portrait
    from render_models import block_to_dict

    if fields is None:
        if not text_block:
            return PortraitResult(ok=False, message="Нужен text_block или fields")
        block = parse_text_block(text_block)
        fields = block_to_dict(block)
    return generate_ai_portrait(fields, job_id=job_id)


def list_mockups() -> dict[str, str]:
    return {k: v.title for k, v in MOCKUPS.items()}


def get_render_server_status() -> dict:
    """Статус серверной обработки (очередь + worker heartbeat)."""
    return get_server_status().to_dict()
