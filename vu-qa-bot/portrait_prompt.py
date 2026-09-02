#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Промпт и демография для ИИ-портрета (официальное фото на документ)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from vu_testdata import gender_from

_PROMPT_VERSION = "vu-passport-v2"


def estimate_age(birth_date: str, *, today: date | None = None) -> int:
    if not birth_date:
        return 35
    try:
        born = datetime.strptime(birth_date.strip(), "%d.%m.%Y").date()
    except ValueError:
        return 35
    ref = today or date.today()
    years = ref.year - born.year
    if (ref.month, ref.day) < (born.month, born.day):
        years -= 1
    return max(18, min(years, 85))


def estimate_gender(fields: dict[str, Any]) -> str:
    if fields.get("gender") in {"M", "F"}:
        return fields["gender"]
    given = (fields.get("given_ru") or "").strip()
    parts = given.split()
    patronymic = parts[-1] if len(parts) >= 2 else ""
    surname = (fields.get("surname_ru") or "").strip()
    return gender_from(patronymic, surname)


def gender_label(gender: str) -> str:
    return "woman" if gender == "F" else "man"


def build_portrait_prompt(fields: dict[str, Any]) -> str:
    """
    Промпт для генерации реалистичного фото на документ.
    ФИО в промпт не включаем — только демография (privacy + меньше артефактов).
    """
    age = estimate_age(fields.get("birth_date") or "")
    gender = gender_label(estimate_gender(fields))
    return (
        f"Professional passport-style ID photograph of a {age}-year-old Russian {gender}, "
        "front-facing, neutral expression, mouth closed, eyes open and looking at camera, "
        "even soft studio lighting, plain light gray background, shoulders and upper chest visible, "
        "sharp focus on face, realistic skin texture and pores, no makeup exaggeration, "
        "no hat, no glasses glare, no smile, photorealistic, high detail, "
        "official government ID photo quality, 35mm lens look"
    )


def portrait_cache_key(fields: dict[str, Any]) -> str:
    import hashlib
    import json

    payload = {
        "v": _PROMPT_VERSION,
        "birth_date": fields.get("birth_date"),
        "given_ru": fields.get("given_ru"),
        "surname_ru": fields.get("surname_ru"),
        "gender": estimate_gender(fields),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
