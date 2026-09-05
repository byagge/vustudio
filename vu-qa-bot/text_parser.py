#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Парсинг клиентского текстового блока ВУ (обратный formatter.format_client_block)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from formatter import SEP

_LINE_RE = re.compile(
    r"^(?:(\d+[a-z]?)\s+)?(.+?)\s{2,}(.+)$",
    re.UNICODE,
)
_DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
_TABLE_HEADER = "кат   открыто     до          огр."
_BACK_NUMBER_RE = re.compile(r"^номер\s*\(оборот\)\s+(.+)$", re.IGNORECASE)
_SPECIAL_RE = re.compile(r"^14\s+(.+)$")


class TextParseError(ValueError):
    pass


@dataclass
class BackTableRow:
    category: str
    open_date: str
    expiry_date: str
    restriction: str = "—"


@dataclass
class VuTextBlock:
    surname_ru: str = ""
    surname_lat: str = ""
    given_ru: str = ""
    given_lat: str = ""
    birth_date: str = ""
    birth_place_ru: str = ""
    birth_place_lat: str = ""
    issue_date: str = ""
    expiry_date: str = ""
    authority: str = ""
    series: str = ""
    number: str = ""
    residence_ru: str = ""
    residence_lat: str = ""
    categories: list[str] = field(default_factory=list)
    back_table: dict[str, BackTableRow] = field(default_factory=dict)
    special_marks: str = ""
    back_number: str = ""


def _split_ru_lat(value: str) -> tuple[str, str]:
    if " / " in value:
        ru, lat = value.split(" / ", 1)
        return ru.strip(), lat.strip()
    return value.strip(), ""


def _parse_table_row(line: str) -> BackTableRow | None:
    parts = line.split()
    if len(parts) < 4:
        return None
    cat, opened, expiry, restriction = parts[0], parts[1], parts[2], parts[3]
    if not _DATE_RE.match(opened) or not _DATE_RE.match(expiry):
        return None
    return BackTableRow(cat, opened, expiry, restriction)


def parse_client_block(text: str) -> VuTextBlock:
    """Разбор блока полей из бота / генератора."""
    block = VuTextBlock()
    in_table = False

    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line or line == SEP:
            in_table = False
            continue

        if line.startswith("кат ") and "открыто" in line:
            in_table = True
            continue

        if in_table:
            row = _parse_table_row(line)
            if row:
                block.back_table[row.category.upper()] = row
            continue

        m = _BACK_NUMBER_RE.match(line)
        if m:
            block.back_number = m.group(1).strip()
            continue

        m = _SPECIAL_RE.match(line)
        if m:
            block.special_marks = m.group(1).strip()
            continue

        if line.startswith("Место рожд.") or raw.startswith("   Место рожд."):
            payload = line.split("Место рожд.", 1)[1].strip()
            ru, lat = _split_ru_lat(payload)
            block.birth_place_ru, block.birth_place_lat = ru, lat
            continue

        m = _LINE_RE.match(line)
        if not m:
            continue

        key, _label, value = m.group(1), m.group(2).strip(), m.group(3).strip()
        if not key:
            continue

        if key == "1":
            block.surname_ru, block.surname_lat = _split_ru_lat(value)
        elif key == "2":
            block.given_ru, block.given_lat = _split_ru_lat(value)
        elif key == "3":
            block.birth_date = value
        elif key == "4a":
            block.issue_date = value
        elif key == "4b":
            block.expiry_date = value
        elif key == "4c":
            block.authority = value
        elif key == "5":
            parts = value.split()
            if len(parts) >= 2:
                block.series = parts[0]
                block.number = " ".join(parts[1:])
            else:
                block.number = value
        elif key == "8":
            block.residence_ru, block.residence_lat = _split_ru_lat(value)
        elif key == "9":
            block.categories = [c.strip().upper() for c in value.split(",") if c.strip()]

    if not block.back_number and block.series and block.number:
        block.back_number = f"{block.series} {block.number}"

    if not block.surname_ru and not block.series:
        raise TextParseError("Не удалось распознать блок данных ВУ")

    return block
