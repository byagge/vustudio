#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Подготовка JPG под smart object Photo (3×4, cover-crop, цветокоррекция)."""
from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps

from portrait_config import PortraitSettings

log = logging.getLogger("portrait_preprocess")

MIN_BYTES = 512
MAX_BYTES = 12 * 1024 * 1024
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "JPG"}


def validate_image_bytes(data: bytes) -> None:
    if len(data) < MIN_BYTES:
        raise ValueError("Файл слишком маленький для фото")
    if len(data) > MAX_BYTES:
        raise ValueError("Файл больше 12 МБ")
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
    except Exception as e:
        raise ValueError("Не удалось прочитать изображение") from e


def _cover_crop(im: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Object-fit: cover — как в CSS, для вставки в SO Photo."""
    src_w, src_h = im.size
    if src_w <= 0 or src_h <= 0:
        raise ValueError("Пустое изображение")
    scale = max(target_w / src_w, target_h / src_h)
    new_w = max(1, int(src_w * scale))
    new_h = max(1, int(src_h * scale))
    im = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return im.crop((left, top, left + target_w, top + target_h))


def _match_document_background(im: Image.Image, target_gray: int = 228) -> Image.Image:
    """Лёгкая подгонка фона под серый тон мокапа (task3 §14 постобработка)."""
    from PIL import ImageStat

    w, h = im.size
    # нижние и боковые полосы — оценка фона
    strip = im.crop((0, int(h * 0.85), w, h))
    mean = ImageStat.Stat(strip).mean
    bg = sum(mean[:3]) / 3 if mean else target_gray
    if bg < 1:
        return im
    factor = target_gray / bg
    factor = max(0.85, min(factor, 1.15))
    return ImageEnhance.Brightness(im).enhance(factor)


def prepare_portrait_file(
    source: Path | bytes,
    destination: Path,
    *,
    settings: PortraitSettings | None = None,
) -> Path:
    """
    Нормализация под бланк ВУ:
    - EXIF orientation
    - sRGB
    - лёгкая коррекция контраста/резкости
    - crop 3×4 (390×507 по умолчанию)
    """
    cfg = settings or PortraitSettings.from_env()
    destination.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(source, bytes):
        im = Image.open(io.BytesIO(source))
    else:
        im = Image.open(source)
    with im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        elif im.mode == "L":
            im = im.convert("RGB")

        # Лицевая зона — верхние ~55% кадра (типичное кадрирование ID photo)
        w, h = im.size
        focus = im.crop((0, 0, w, int(h * 0.72)))
        focus = _cover_crop(focus, cfg.width, cfg.height)

        focus = _match_document_background(focus)
        focus = ImageEnhance.Contrast(focus).enhance(1.06)
        focus = ImageEnhance.Brightness(focus).enhance(1.02)
        focus = ImageEnhance.Sharpness(focus).enhance(1.15)

        focus.save(
            destination,
            format="JPEG",
            quality=cfg.jpeg_quality,
            optimize=True,
            subsampling=0,
        )
    log.debug("Portrait prepared %s (%dx%d)", destination, cfg.width, cfg.height)
    return destination


def portrait_meta(settings: PortraitSettings | None = None) -> dict:
    cfg = settings or PortraitSettings.from_env()
    return {
        "width": cfg.width,
        "height": cfg.height,
        "fit": "cover",
        "aspect": "3:4",
    }
