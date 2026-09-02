#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Форматирование записи ВУ (§7.4 ТЗ)."""
from __future__ import annotations

import html
import json
from typing import TYPE_CHECKING

from vu_testdata import ALL_CATEGORIES, effective_expiry, is_synthetic, parse_date

if TYPE_CHECKING:
    from vu_testdata import LicenceRecord

BANNER = "СИНТЕТИЧЕСКАЯ ЗАПИСЬ — ТЕСТОВЫЙ ДАТАСЕТ, НЕ ДОКУМЕНТ"
SEP = "─" * 44


def format_client_block(rec: LicenceRecord, *, include_banner: bool = False) -> str:
    """Блок полей бланка без служебных метаданных."""
    lines: list[str] = []
    if include_banner:
        lines += [BANNER, ""]
    lines += [
        f"1  Фамилия      {rec.surname_ru} / {rec.surname_lat}",
        f"2  Имя, отч.    {rec.given_ru} / {rec.given_lat}",
        f"3  Дата рожд.   {rec.birth_date}",
        f"   Место рожд.  {rec.birth_place_ru} / {rec.birth_place_lat}",
        f"4a Выдано       {rec.issue_date}",
        f"4b Действ. до   {rec.expiry_date}",
        f"4c Кем выдано   {rec.authority}",
        f"5  Номер        {rec.series} {rec.number}",
        f"8  Регион       {rec.residence_ru} / {rec.residence_lat}",
        f"9  Категории    {', '.join(rec.categories) or '—'}",
        SEP,
        "кат   открыто     до          огр.",
    ]
    order = {c: i for i, c in enumerate(ALL_CATEGORIES)}
    for cat in sorted(rec.back_table, key=lambda c: (order.get(c, 999), c)):
        row = rec.back_table[cat]
        lines.append(
            f"{cat:<5} {row['open']:<11} {row['expiry']:<11} {row['restriction'] or '—'}"
        )
    lines += [
        SEP,
        f"14 {rec.special_marks}",
        f"номер (оборот) {rec.back_number}",
    ]
    return "\n".join(lines)


def format_debug_block(rec: LicenceRecord) -> str:
    """§7.4: баннер + поля + служебный блок QA."""
    exp = parse_date(rec.expiry_date)
    eff = effective_expiry(exp)
    lines = [BANNER, "", format_client_block(rec), SEP]
    lines += [
        f"synthetic: {str(rec.synthetic).lower()} | is_synthetic(): {str(is_synthetic(rec)).lower()}",
        f"identity_source: {rec.identity_source}",
        f"expected_valid: {str(rec.expected_valid).lower()} | broken_rule: {rec.broken_rule or '—'}",
    ]
    if eff != exp:
        lines.append(f"effective_expiry: {eff.strftime('%d.%m.%Y')}  (автопродление 2022–2025)")
    return "\n".join(lines)


def format_jsonl_line(rec: LicenceRecord) -> str:
    return json.dumps(rec.to_dict(), ensure_ascii=False)


def dataset_filename(valid: int, mutated: int) -> str:
    return f"dataset_{valid}_{mutated}.jsonl"


def render_html(rec: LicenceRecord, *, debug: bool = True) -> str:
    text = format_debug_block(rec) if debug else format_client_block(rec)
    if not debug:
        text = f"{BANNER}\n\n{text}"
    return "<pre>" + html.escape(text) + "</pre>"


def record_to_json(rec: LicenceRecord, *, indent: int | None = 2) -> str:
    return json.dumps(rec.to_dict(), ensure_ascii=False, indent=indent)
