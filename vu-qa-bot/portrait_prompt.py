#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Промпт и демография для ИИ-портрета (официальное фото на документ)."""
from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Any

from vu_testdata import gender_from

_PROMPT_VERSION = "vu-id-booth-v15-selfie-or"

# BBC / client: selfie → gray-bg document portrait via OpenRouter NB 2 Lite.
# Russian primary (as used by client in NB), English reinforce for model fidelity.
SELFIE_EDIT_PROMPT = (
    "Сделай из этого фото портретное фото 4:3 на однотонном сером фоне. "
    "Максимально сохрани пропорции и внешний вид лица из исходного фото. "
    "Make a 4:3 portrait photo on a plain solid gray background from this photo. "
    "Preserve face proportions and appearance as much as possible. "
    "Keep the same person: face, hair, skin tone, age. "
    "Neutral expression, mouth closed, eyes open looking at the camera. "
    "Shoulders and upper chest visible. No scenery, no objects, no text, no watermark. "
    "Photorealistic document-booth photo."
)

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
    digest = _variation_key(fields)
    idx = int(digest[:8], 16)
    return {
        "token": digest[:12],
        "hair": _HAIR[idx % len(_HAIR)],
        "face": _FACE[(idx // len(_HAIR)) % len(_FACE)],
    }


def build_portrait_prompt(fields: dict[str, Any]) -> str:
    """Text-to-image prompt (dev/fallback only — product path is selfie edit)."""
    age = estimate_age(str(fields.get("birth_date") or ""))
    gender = estimate_gender(fields)
    who = gender_label(gender)
    var = portrait_variation(fields)
    return (
        f"Photorealistic ICAO-style driving-licence portrait of a {age}-year-old {who}. "
        f"unique identity token {var['token']}. "
        f"Hair: {var['hair']}. Face: {var['face']}. "
        "Document booth, light-gray seamless backdrop, soft even frontal light, "
        "neutral expression, mouth closed, eyes open looking at camera, "
        "shoulders and upper chest with a simple dark collar, "
        "no jewelry, no glasses glare, not a model, not a celebrity. "
        "Photorealistic passport-booth JPEG, slight print softness."
    )


def build_portrait_edit_prompt(fields: dict[str, Any] | None = None) -> str:
    """Промпт img2img по селфи (OpenRouter / NB 2 Lite). fields зарезервированы."""
    _ = fields
    return SELFIE_EDIT_PROMPT


def portrait_cache_key(fields: dict[str, Any]) -> str:
    import json

    payload = {
        "v": _PROMPT_VERSION,
        "crop": "v10-shoulders-chest",
        "birth_date": fields.get("birth_date"),
        "given_ru": fields.get("given_ru"),
        "surname_ru": fields.get("surname_ru"),
        "gender": estimate_gender(fields),
        # Identity cache only — job_id must not bust cache across same person.
        "token": portrait_variation({k: v for k, v in fields.items() if k not in {"_seed", "job_id"}})[
            "token"
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
