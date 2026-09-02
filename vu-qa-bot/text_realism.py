#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Форматирование полей под конкретный мокап — реалистичный вид бланка."""
from __future__ import annotations

import re
from typing import Any

from text_parser import BackTableRow, VuTextBlock

DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
_CAT_FIELDS = {"cat_b": "B", "cat_b1": "B1", "cat_m": "M"}


def _authority_lat(authority: str) -> str:
    return (
        authority.upper()
        .replace("ГИБДД", "gibdd")
        .replace("ГИБ", "gib")
        .lower()
    )


def ensure_back_table(block: VuTextBlock) -> None:
    if block.back_table:
        return
    cats = block.categories or ["B"]
    for cat in cats:
        block.back_table[cat.upper()] = BackTableRow(
            cat.upper(),
            block.issue_date,
            block.expiry_date,
            "—",
        )


def validate_block(block: VuTextBlock) -> list[str]:
    errors: list[str] = []
    if not block.surname_ru.strip():
        errors.append("Не указана фамилия")
    if not block.series.strip():
        errors.append("Не указана серия")
    if not block.number.strip():
        errors.append("Не указан номер")
    for label, val in (
        ("Дата выдачи", block.issue_date),
        ("Действ. до", block.expiry_date),
        ("Дата рожд.", block.birth_date),
    ):
        if val and not DATE_RE.match(val):
            errors.append(f"{label}: ожидается ДД.ММ.ГГГГ, получено {val!r}")
    return errors


def format_field_value(field: str, raw: str, tpl: dict[str, Any]) -> str:
    rules = tpl.get("field_formats") or {}
    rule = rules.get(field, "strip")
    val = raw.strip()
    if rule == "upper":
        return val.upper()
    if rule == "lower":
        return val.lower()
    if rule == "authority_lat":
        return _authority_lat(val)
    if rule == "special_line14":
        body = val[3:].strip() if val.startswith("14 ") else val
        return f"14 {body}"
    if rule == "special_year":
        m = re.search(r"\d{4}", val)
        return m.group(0) if m else val
    return val


def active_categories(block: VuTextBlock) -> set[str]:
    ensure_back_table(block)
    cats = {c.upper() for c in block.categories}
    cats.update(block.back_table.keys())
    return cats or {"B"}


def build_text_group(block: VuTextBlock, tpl: dict[str, Any]) -> tuple[list[str], list[bool]]:
    ensure_back_table(block)
    cats = active_categories(block)
    values: list[str] = []
    visibility: list[bool] = []
    formats = tpl.get("field_formats") or {}

    for entry in tpl.get("back_table_layout") or []:
        if "field" in entry:
            field_name = entry["field"]
            slot_visible = bool(entry.get("visible", True))
            if field_name == "restriction":
                restr = tpl.get("default_restriction", "—")
                for row in block.back_table.values():
                    if row.restriction and row.restriction != "—":
                        restr = row.restriction
                        break
                has_restr = any(
                    row.restriction and row.restriction != "—" for row in block.back_table.values()
                )
                values.append(restr)
                visibility.append(slot_visible and has_restr)
            elif field_name == "special_marks":
                rule = formats.get("special_marks_text_group", "special_line14")
                values.append(format_field_value("x", block.special_marks, {"field_formats": {"x": rule}}))
                visibility.append(True)
            elif field_name == "special_year":
                values.append(format_field_value("x", block.special_marks, {"field_formats": {"x": "special_year"}}))
                visibility.append(True)
            continue

        cat = entry["cat"].upper()
        row = block.back_table.get(cat)
        cat_active = cat in cats
        for slot in entry["fields"]:
            if not cat_active or not row:
                values.append("")
                visibility.append(False)
            elif slot == "open":
                values.append(row.open_date)
                visibility.append(True)
            elif slot == "expiry":
                values.append(row.expiry_date)
                visibility.append(True)
            else:
                values.append("")
                visibility.append(False)

    return values, visibility


def category_visibility(block: VuTextBlock, tpl: dict[str, Any]) -> dict[str, bool]:
    """Имя слоя категории (b/b1/m) → показывать ли."""
    cats = active_categories(block)
    layers_map = tpl.get("field_layers") or {}
    out: dict[str, bool] = {}
    for field_key, cat_code in _CAT_FIELDS.items():
        layer_name = layers_map.get(field_key)
        if layer_name:
            out[layer_name] = cat_code in cats
    return out


def build_layer_values(block: VuTextBlock, tpl: dict[str, Any]) -> dict[str, str]:
    ensure_back_table(block)
    series = block.series.replace(" ", "")
    part1 = series[:2] if len(series) >= 2 else series
    part2 = series[2:4] if len(series) >= 4 else ""
    full_number = f"{block.series} {block.number}".strip()
    cats = active_categories(block)

    raw = {
        "series_part1": part1,
        "series_part2": part2,
        "number": block.number.replace(" ", ""),
        "surname_ru": block.surname_ru,
        "given_ru": block.given_ru,
        "birth_place_ru": block.birth_place_ru,
        "birth_date": block.birth_date,
        "issue_date": block.issue_date,
        "expiry_date": block.expiry_date,
        "authority_ru": block.authority,
        "residence_ru": block.residence_ru,
        "full_number": full_number,
        "surname_lat": block.surname_lat,
        "given_lat": block.given_lat,
        "birth_place_lat": block.birth_place_lat,
        "authority_lat": block.authority,
        "residence_lat": block.residence_lat,
        "cat_b": "b" if "B" in cats else "",
        "cat_b1": "b1" if "B1" in cats else "",
        "cat_m": "m" if "M" in cats else "",
    }

    formatted: dict[str, str] = {}
    for key, val in raw.items():
        if key.startswith("cat_"):
            formatted[key] = val
        else:
            formatted[key] = format_field_value(key, val, tpl)
    return formatted
