#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Промпт и демография для ИИ-портрета (официальное фото на документ)."""
from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Any

from vu_testdata import gender_from

_PROMPT_VERSION = "vu-id-booth-v3"

_HAIR = (
    "short straight dark brown hair",
    "short wavy black hair",
    "cropped ash-brown hair",
    "neat side-parted brown hair",
    "short chestnut hair with a high forehead",
    "dense dark hair combed back",
    "light brown short hair",
    "black hair with a slight widow's peak",
)

_FACE = (
    "oval face, thin straight brows, narrow nose",
    "square jaw, close-set dark eyes",
    "round face, wide-set eyes, short nose",
    "long face, high cheekbones, thin lips",
    "soft chin, straight brows, medium nose",
    "angular cheekbones, deep-set eyes",
    "broad forehead, small mouth, brown eyes",
    "heart-shaped face, thicker brows, pale skin",
)


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


def _variation_key(fields: dict[str, Any]) -> str:
    raw = "|".join(
        [
            str(fields.get("surname_ru") or ""),
            str(fields.get("given_ru") or ""),
            str(fields.get("birth_date") or ""),
            str(fields.get("birth_place_ru") or ""),
            str(fields.get("_seed") or fields.get("job_id") or ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def portrait_variation(fields: dict[str, Any]) -> dict[str, str]:
    """Детерминированные черты лица — разные люди / задачи не копируют один типаж."""
    digest = _variation_key(fields)
    n = int(digest[:8], 16)
    return {
        "token": digest[:10],
        "hair": _HAIR[n % len(_HAIR)],
        "face": _FACE[(n // len(_HAIR)) % len(_FACE)],
    }


def build_portrait_prompt(fields: dict[str, Any]) -> str:
    """
    Промпт: фото как в окошке бланка ВУ, не студийный портрет.
    ФИО в промпт не включаем — только демография + уникальный типаж.
    """
    age = estimate_age(fields.get("birth_date") or "")
    gender = gender_label(estimate_gender(fields))
    var = portrait_variation(fields)
    return (
        f"Official Russian driving-licence ID card photograph of a {age}-year-old {gender}, "
        f"unique identity {var['token']}, {var['hair']}, {var['face']}. "
        "This is a government document booth photo printed into a plastic card window, "
        "not a studio, fashion or LinkedIn portrait. "
        "Head-and-shoulders 3:4 crop, face centered, ears visible, both shoulders in frame. "
        "Neutral expression, mouth closed, no smile, eyes open looking straight at the camera. "
        "Flat even frontal lighting, no rim light, no cinematic grade, no dramatic shadows. "
        "Matte skin, realistic pores, slight document-print softness. "
        "Plain light-gray ID-card background, no scenery, no objects, no text, no watermark. "
        "Photorealistic, ISO/IEC 19794-5 compliant passport photo look."
    )


def build_portrait_edit_prompt(fields: dict[str, Any] | None = None) -> str:
    """Промпт img2img: тот же человек, вид официального фото на документ."""
    fields = fields or {}
    age = estimate_age(fields.get("birth_date") or "")
    gender = gender_label(estimate_gender(fields))
    who = f"this {age}-year-old {gender}" if fields.get("birth_date") or fields.get("given_ru") else "this person"
    return (
        f"Edit this photo into an official Russian driving-licence ID card photograph of {who}. "
        "Keep the same identity: same face, age, gender, hair, skin tone and distinctive features. "
        "Make it look printed in the photo window of a plastic document, not a studio portrait. "
        "Front-facing head-and-shoulders 3:4 crop, neutral expression, mouth closed, eyes open. "
        "Remove the original background completely (cut-out), no scenery, no objects, no text. "
        "Flat even frontal lighting, matte skin, plain light-gray ID-card paper background."
    )


def portrait_cache_key(fields: dict[str, Any]) -> str:
    import json

    payload = {
        "v": _PROMPT_VERSION,
        "birth_date": fields.get("birth_date"),
        "given_ru": fields.get("given_ru"),
        "surname_ru": fields.get("surname_ru"),
        "gender": estimate_gender(fields),
        "seed": fields.get("_seed") or fields.get("job_id") or "",
        "token": portrait_variation(fields)["token"],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
