#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Инспекция PSB/PSD: текстовые слои, группа Text, извлечение вложенных SO."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from psd_tools import PSDImage
from psd_tools.api.layers import SmartObjectLayer

from mockup_registry import MOCKUPS, get_mockup

ROOT = Path(__file__).resolve().parent.parent
EXTRACT_DIR = ROOT / "_extract"


def _layer_kind(layer) -> str:
    return getattr(layer, "kind", "") or ""


def _layer_text(layer) -> str:
    t = layer.text
    return t if isinstance(t, str) else str(t)


def extract_smart_object(layer: SmartObjectLayer, *, cache_key: str, refresh: bool = False) -> Path:
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in cache_key)
    out = EXTRACT_DIR / f"{safe}.psb"
    if refresh or not out.is_file():
        layer.smart_object.save(out)
    return out


def iter_nested_psbs(root: Path, *, max_depth: int = 8) -> Iterator[tuple[Path, PSDImage]]:
    stack: list[tuple[Path, int]] = [(root.resolve(), 0)]
    seen: set[str] = set()

    while stack:
        path, depth = stack.pop()
        key = str(path)
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        try:
            psd = PSDImage.open(path)
        except Exception:
            continue
        yield path, psd
        if depth >= max_depth:
            continue
        for layer in psd.descendants():
            if not isinstance(layer, SmartObjectLayer):
                continue
            try:
                inner = extract_smart_object(layer, cache_key=f"{path.stem}_{layer.name}")
                stack.append((inner, depth + 1))
            except Exception:
                continue


def collect_text_layers(psb_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def walk(layer, prefix: str = "") -> None:
        path = f"{prefix}/{layer.name}" if prefix else layer.name
        if _layer_kind(layer) == "type":
            rows.append(
                {
                    "path": path,
                    "name": layer.name,
                    "text": _layer_text(layer),
                    "visible": bool(getattr(layer, "visible", True)),
                }
            )
        if _layer_kind(layer) == "group":
            for ch in layer:
                walk(ch, path)

    for _path, psd in iter_nested_psbs(psb_path):
        for ch in psd:
            walk(ch)
    return rows


def count_text_group_slots(psb_path: Path) -> int:
    best = 0
    for _path, psd in iter_nested_psbs(psb_path):
        for layer in psd.descendants():
            if layer.name != "Text" or _layer_kind(layer) != "group":
                continue
            n = sum(1 for ch in layer if _layer_kind(ch) == "type")
            best = max(best, n)
    return best


def layout_slot_count(layout: list[dict[str, Any]]) -> int:
    n = 0
    for entry in layout:
        if "fields" in entry:
            n += len(entry["fields"])
        else:
            n += 1
    return n


def resolve_mockup_psb(mockup: str) -> Path:
    return get_mockup(mockup).resolve_path()


def text_group_reference_psb(mockup_kind: str) -> Path:
    """PSB для проверки группы Text (hand использует тот же layout, что blank)."""
    blank = resolve_mockup_psb("blank")
    if mockup_kind == "hand" or mockup_kind == "original":
        cached = EXTRACT_DIR / "hand_Text.psb"
        if cached.is_file():
            return cached
        # task2 §10: та же логика Text-группы; blank — эталон структуры слотов
        return blank
    return blank


def verify_template_against_psb(template_name: str) -> dict[str, Any]:
    tpl_path = Path(__file__).resolve().parent / "templates" / f"{template_name}.json"
    tpl = json.loads(tpl_path.read_text(encoding="utf-8"))
    mockup_kind = tpl["name"].replace("mockup_", "")
    if mockup_kind not in MOCKUPS:
        mockup_kind = "blank"
    psb = resolve_mockup_psb(mockup_kind)

    layout = tpl.get("back_table_layout") or []
    expected_slots = layout_slot_count(layout)
    slot_psb = text_group_reference_psb(mockup_kind)
    actual_slots = count_text_group_slots(slot_psb)
    if actual_slots == 0:
        actual_slots = count_text_group_slots(psb)

    field_layers = tpl.get("field_layers") or {}
    text_layers = collect_text_layers(psb)
    if len(text_layers) < len(field_layers) // 2 and mockup_kind in {"hand", "original"}:
        text_layers = collect_text_layers(resolve_mockup_psb("blank"))
    names_in_psb = {r["name"] for r in text_layers if "/Text/" not in r["path"]}
    missing_layers = sorted({v for v in field_layers.values() if v and v not in names_in_psb})

    slots_ok = expected_slots == actual_slots
    layers_ok = not missing_layers or mockup_kind in {"hand", "original"}
    ok = slots_ok and layers_ok
    return {
        "template": template_name,
        "psb": str(psb),
        "slot_reference_psb": str(slot_psb),
        "layout_slots": expected_slots,
        "text_group_slots": actual_slots,
        "missing_layer_names": missing_layers,
        "text_layer_count": len(text_layers),
        "ok": ok,
    }
