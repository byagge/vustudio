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


def _flatten_cutout(im: Image.Image, paper_gray: tuple[int, int, int] = (228, 228, 228)) -> Image.Image:
    """RGBA/P с прозрачностью → серый фон бланка, иначе RGB."""
    has_alpha = im.mode in {"RGBA", "LA"} or (im.mode == "P" and "transparency" in im.info)
    if has_alpha:
        rgba = im.convert("RGBA")
        bg = Image.new("RGB", rgba.size, paper_gray)
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    if im.mode == "L":
        return im.convert("RGB")
    if im.mode != "RGB":
        return im.convert("RGB")
    return im


def _cover_crop(
    im: Image.Image,
    target_w: int,
    target_h: int,
    *,
    document: bool = False,
    zoom: float | None = None,
) -> Image.Image:
    """Cover-crop в 3×4.

    document=True — кадр как на бланке ВУ: ИИ отдаёт квадрат с лицом в центре,
    поэтому увеличиваем и срезаем серый «потолок», чтобы макушка была у верха.
    zoom=1.0 — без дополнительного увеличения, только подгонка сторон.
    """
    src_w, src_h = im.size
    if src_w <= 0 or src_h <= 0:
        raise ValueError("Пустое изображение")
    src_aspect = src_w / src_h
    if zoom is None:
        zoom = 1.10 if document else 1.06
    scale = max(target_w / src_w, target_h / src_h) * zoom
    new_w = max(1, int(src_w * scale))
    new_h = max(1, int(src_h * scale))
    im = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = max(0, (new_w - target_w) // 2)
    extra_h = max(0, new_h - target_h)
    if document and src_aspect >= 0.82:
        top = int(extra_h * 0.42)
    elif document:
        top = int(extra_h * 0.16)
    else:
        top = int(extra_h * 0.06)
    if top + target_h > new_h:
        top = max(0, new_h - target_h)
    if left + target_w > new_w:
        left = max(0, new_w - target_w)
    return im.crop((left, top, left + target_w, top + target_h))


PAPER_GRAY = (228, 228, 228)


def _document_window(im: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Бланк ВУ: голова и оба плеча, поле над макушкой, не крупный план лица."""
    canvas = Image.new("RGB", (target_w, target_h), PAPER_GRAY)
    inner_w = max(1, int(target_w * 0.56))
    inner_h = max(1, int(target_h * 0.62))
    fitted = _cover_crop(im, inner_w, inner_h, document=False, zoom=1.0)
    x = (target_w - inner_w) // 2
    top_gap = int(target_h * 0.14)
    bottom_keep = int(target_h * 0.16)
    y = top_gap
    if y + inner_h > target_h - bottom_keep:
        y = max(0, target_h - inner_h - bottom_keep)
    canvas.paste(fitted, (x, y))
    return canvas


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


def _document_print_grain(im: Image.Image, amount: float = 0.07) -> Image.Image:
    """Слабая зернистость, как у фото на пластике, а не у студийного рендера."""
    try:
        noise = Image.effect_noise(im.size, 18).convert("RGB")
    except Exception:
        return im
    return Image.blend(im, noise, max(0.02, min(amount, 0.14)))


def prepare_portrait_file(
    source: Path | bytes,
    destination: Path,
    *,
    settings: PortraitSettings | None = None,
    face_focus: bool = True,
) -> Path:
    """
    Нормализация под бланк ВУ:
    - EXIF orientation
    - sRGB / вырезанный фон на серую бумагу
    - лёгкая коррекция контраста/резкости
    - crop 3×4 (390×507 по умолчанию)
    - face_focus: для селфи обрезает верх кадра; для ИИ-ID фото — False
    """
    cfg = settings or PortraitSettings.from_env()
    destination.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(source, bytes):
        im = Image.open(io.BytesIO(source))
    else:
        im = Image.open(source)
    with im:
        im = ImageOps.exif_transpose(im)
        im = _flatten_cutout(im)

        w, h = im.size
        if face_focus:
            # Лицевая зона — верхние ~72% кадра (типичное кадрирование селфи)
            im = im.crop((0, 0, w, max(1, int(h * 0.72))))
            focus = _cover_crop(im, cfg.width, cfg.height, document=False)
        else:
            focus = _document_window(im, cfg.width, cfg.height)

        focus = _match_document_background(focus)
        if face_focus:
            focus = ImageEnhance.Contrast(focus).enhance(1.06)
            focus = ImageEnhance.Brightness(focus).enhance(1.02)
            focus = ImageEnhance.Sharpness(focus).enhance(1.15)
        else:
            # ИИ-кадр: лёгкая зернистость печати, без «бьюти»-сглаживания
            focus = _document_print_grain(focus)
            focus = ImageEnhance.Color(focus).enhance(0.96)
            focus = ImageEnhance.Contrast(focus).enhance(1.04)
            focus = ImageEnhance.Sharpness(focus).enhance(0.88)

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
        "fit": "id-shoulders",
        "aspect": "3:4",
    }
