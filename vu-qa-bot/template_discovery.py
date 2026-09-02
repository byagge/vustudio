#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Авто-обнаружение текстовых слоёв PSB/PSD для templates/*.json."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from psd_tools import PSDImage

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")


def _collect_text_layers(psd: PSDImage) -> list[tuple[str, str, bool]]:
    out: list[tuple[str, str, bool]] = []

    def walk(layer, prefix: str = "") -> None:
        path = f"{prefix}/{layer.name}" if prefix else layer.name
        kind = getattr(layer, "kind", "")
        if kind == "type":
            t = layer.text
            val = t if isinstance(t, str) else str(t)
            out.append((path, val, bool(getattr(layer, "visible", True))))
        if kind == "group" and hasattr(layer, "__iter__"):
            for ch in layer:
                walk(ch, path)

    for ch in psd:
        walk(ch)
    return out


def _guess_field(name: str, value: str) -> str | None:
    v = value.strip()
    n = name.strip()
    if DATE_RE.match(v):
        if "Text/" in name:
            return None
        return "issue_date" if n.count(".") else None
    if re.fullmatch(r"\d{2}", v):
        return "series_part1"
    if re.fullmatch(r"\d{2}", v) and "series_part2" not in v:
        return "series_part2"
    if re.fullmatch(r"\d{6}", v):
        return "number"
    if re.fullmatch(r"[a-z]", v.lower()) and len(v) <= 2:
        return f"cat_{v.lower()}"
    if re.fullmatch(r"[A-Z]{3,}", v) and " " not in v:
        return "surname_lat"
    if "G." in v or "G " in v:
        return "birth_place_lat"
    if v.lower().startswith("gibdd") or v.lower().startswith("гибдд"):
        return "authority_lat" if "gib" in v.lower() and v.isascii() else "authority_ru"
    if "СТАЖ" in v.upper():
        return "special_marks"
    if re.fullmatch(r"\d{4}", v):
        return "special_year"
    if " " in v and re.search(r"\d{2} \d{2} \d+", v):
        return "full_number"
    if re.search(r"[А-Я]", v) and " " in v and len(v) > 10:
        return "given_ru"
    if re.search(r"[А-Я]", v) and len(v) <= 20:
        return "surname_ru"
    return None


def discover_field_layers(psb_path: Path) -> dict[str, str]:
    """Имя слоя (как в PSD) для каждого семантического поля."""
    psd = PSDImage.open(psb_path)
    layers = _collect_text_layers(psd)
    mapping: dict[str, str] = {}
    series_parts: list[str] = []

    for path, value, _vis in layers:
        if "/Text/" in path:
            continue
        name = path.split("/")[-1]
        if re.fullmatch(r"\d{2}", value):
            series_parts.append(name)
            continue
        field = _guess_field(path, value)
        if field and field not in mapping:
            mapping[field] = name

    if series_parts:
        mapping.setdefault("series_part1", series_parts[0])
        if len(series_parts) > 1:
            mapping.setdefault("series_part2", series_parts[1])
    return mapping


def discover_text_group_layout(psb_path: Path) -> list[dict[str, Any]]:
    psd = PSDImage.open(psb_path)
    for layer in psd.descendants():
        if layer.name != "Text" or getattr(layer, "kind", "") != "group":
            continue
        slots = []
        for ch in layer:
            if getattr(ch, "kind", "") != "type":
                continue
            t = ch.text
            val = t if isinstance(t, str) else str(t)
            if DATE_RE.match(val):
                slots.append("open" if slots.count("open") <= slots.count("expiry") else "expiry")
            elif val.upper() in {"AS", "AT", "MS"}:
                slots.append({"field": "restriction", "visible": bool(ch.visible)})
            elif "СТАЖ" in val.upper():
                slots.append({"field": "special_marks"})
            elif re.fullmatch(r"\d{4}", val):
                slots.append({"field": "special_year"})
        layout: list[dict[str, Any]] = []
        buf: list[str] = []
        for s in slots:
            if isinstance(s, dict):
                if buf:
                    layout.append({"cat": "B", "fields": buf[:]})
                    buf = []
                layout.append(s)
            else:
                buf.append(s)
        if buf:
            layout.append({"cat": "B", "fields": buf})
        return layout
    return []


def write_template_from_psb(
    psb_path: Path,
    name: str,
    *,
    description: str = "",
    scene: dict | None = None,
) -> Path:
    field_layers = discover_field_layers(psb_path)
    layout = discover_text_group_layout(psb_path)
    tpl = {
        "name": name,
        "description": description or psb_path.name,
        "field_layers": field_layers,
        "field_formats": {
            "surname_ru": "upper",
            "given_ru": "upper",
            "birth_place_ru": "upper",
            "residence_ru": "upper",
            "authority_ru": "upper",
            "authority_lat": "authority_lat",
            "surname_lat": "upper",
            "given_lat": "upper",
            "birth_place_lat": "upper",
            "residence_lat": "upper",
            "special_marks_text_group": "special_line14",
        },
        "default_restriction": "—",
        "back_table_layout": layout or [
            {"cat": "B", "fields": ["open", "open", "expiry", "expiry", "open", "expiry"]},
            {"cat": "B1", "fields": ["open", "expiry"]},
            {"cat": "M", "fields": ["open", "expiry"]},
            {"field": "restriction", "visible": False},
            {"field": "special_marks"},
        ],
        "scene": scene or {},
    }
    out = TEMPLATES_DIR / f"{name}.json"
    out.write_text(json.dumps(tpl, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
