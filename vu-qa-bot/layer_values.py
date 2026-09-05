#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сборка job для Photoshop."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from font_registry import build_font_job_fields
from mockup_registry import ROOT, get_mockup
from mockup_scene import build_scene_job_fields, validate_scene_options
from portrait_service import portrait_job_payload
from render_models import RenderOptions, RenderTask, block_to_dict
from template_loader import load_template
from text_parser import VuTextBlock, parse_client_block
from text_realism import (
    build_layer_values,
    build_text_group,
    category_visibility,
    validate_block,
)

# Алиас из task2.md §3 (layer_values.field_values)
field_values = build_layer_values


def layers_by_name_for_template(block: VuTextBlock, tpl: dict) -> dict[str, str]:
    values = build_layer_values(block, tpl)
    layers_map = tpl.get("field_layers") or {}
    return {layers_map[key]: values[key] for key in layers_map if key in values}


def resolve_blank_template_path() -> Path:
    spec = get_mockup("blank")
    path = spec.resolve_path()
    if path.is_file():
        return path
    fallback = ROOT / spec.psb_name
    if fallback.is_file():
        return fallback
    return path


def load_template(name: str = "mockup_hand") -> dict:
    """Re-export для обратной совместимости."""
    from template_loader import load_template as _load

    return _load(name)


def build_render_payload(
    block: VuTextBlock,
    template: dict | None = None,
    *,
    options: RenderOptions | None = None,
    portrait_path: str | None = None,
) -> dict[str, Any]:
    tpl = template or load_template()
    layers_map = tpl["field_layers"]
    values = build_layer_values(block, tpl)

    layers_by_name = {layers_map[key]: values[key] for key in layers_map if key in values}
    layers_by_field = {key: values[key] for key in values}

    text_values, text_visibility = build_text_group(block, tpl)
    opts = (options or RenderOptions()).normalized()
    mockup = get_mockup(opts.mockup)
    scene_fields = build_scene_job_fields(opts, tpl)
    font_fields = build_font_job_fields(tpl)

    return {
        "layers_by_name": layers_by_name,
        "layers_by_field": layers_by_field,
        "text_group_values": text_values,
        "text_group_visibility": text_visibility,
        "category_visibility": category_visibility(block, tpl),
        "template_name": tpl.get("name", "mockup_hand"),
        **scene_fields,
        "fonts": font_fields,
        "portrait_path": portrait_path if mockup.supports_portrait else None,
        "portrait": portrait_job_payload(portrait_path if mockup.supports_portrait else None),
    }


def build_photoshop_job(task: RenderTask, *, output_psd: Path, output_jpg: Path) -> dict[str, Any]:
    block = parse_client_block(task.text_block)
    errors = validate_block(block)
    if errors:
        raise ValueError("; ".join(errors))

    scene_errors = validate_scene_options(task.options)
    if scene_errors:
        raise ValueError("; ".join(scene_errors))

    mockup = get_mockup(task.options.mockup)
    template = load_template(mockup.template)
    template_path = mockup.resolve_path()
    blank_tpl = load_template("mockup_blank")
    blank_path = resolve_blank_template_path()
    blank_map = layers_by_name_for_template(block, blank_tpl)
    blank_tg, blank_tg_vis = build_text_group(block, blank_tpl)

    payload = build_render_payload(
        block,
        template,
        options=task.options,
        portrait_path=task.options.portrait_path,
    )
    # Hand SO uses «УИК», blank uses «АБСАЛЯМОВ» — keep both maps so either document updates.
    merged = dict(blank_map)
    merged.update(payload.get("layers_by_name") or {})
    payload["layers_by_name"] = merged
    payload["blank_template"] = str(blank_path.resolve()) if blank_path.is_file() else ""
    payload["blank_layers_by_name"] = blank_map
    payload["blank_text_group_values"] = blank_tg
    payload["blank_text_group_visibility"] = blank_tg_vis

    return {
        "job_id": task.job_id,
        "template": str(template_path.resolve()),
        "output_psd": str(output_psd.resolve()),
        "output_jpg": str(output_jpg.resolve()),
        "output_is_psb": template_path.suffix.lower() == ".psb",
        "fields": block_to_dict(block),
        **payload,
    }
