#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Даты 10/11 на обороте JPG: только рисование в ячейках, без замазывания бланка.

Важно:
- НЕ стираем пиксели на карте (гильош / иконки / буквы категорий).
- НЕ рисуем вне бланка.
- Сценовый оверлей в JSX отключён — даты только здесь.
- Карта и строки таблицы ищутся по текстуре / линиям сетки.
"""
from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger("back_jpg_dates")

ID1_ASPECT = 85.6 / 53.98
DEFAULT_ROWS = (
    "A", "A1", "B", "B1", "C", "C1", "D", "D1",
    "BE", "CE", "C1E", "DE", "D1E", "M", "Tm", "Tb",
)
STAMP_CATS = ("B", "B1", "M")

# Fallback-геометрия, если линии сетки не найдены.
DEFAULT_GEOM = {
    "col10": 0.545,
    "col11": 0.685,
    "col10_left": 0.48,
    "col10_right": 0.61,
    "col11_left": 0.61,
    "col11_right": 0.76,
    "top": 0.115,
    "bottom": 0.850,
}

_TABLE_TOP = 0.218
_TABLE_STEP = 0.040
DEFAULT_ROW_FRAC = {
    name: round(_TABLE_TOP + _TABLE_STEP * i, 4)
    for i, name in enumerate(DEFAULT_ROWS)
}
ROW_INDEX = {name: i for i, name in enumerate(DEFAULT_ROWS)}


@dataclass(frozen=True)
class CardRect:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class CellBox:
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def w(self) -> int:
        return max(1, self.x1 - self.x0)

    @property
    def h(self) -> int:
        return max(1, self.y1 - self.y0)


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    size = max(5, int(size))
    for name in (
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/ARIALN.TTF",
        "C:/Windows/Fonts/calibri.ttf",
        "C:/Windows/Fonts/tahoma.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        path = Path(name)
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _refine_left_edge(gray: Image.Image, box: tuple[int, int, int, int]) -> int:
    """Левый край бланка — сильный вертикальный градиент (не стена)."""
    gp = gray.load()
    x0, y0, x1, y1 = box
    w = x1 - x0
    h = y1 - y0
    if w < 40 or h < 30:
        return x0
    search_r = x0 + max(12, int(w * 0.35))
    y_a = y0 + int(h * 0.20)
    y_b = y0 + int(h * 0.75)
    best_x = x0
    best_s = -1
    for x in range(max(1, x0), min(gray.size[0] - 1, search_r)):
        s = 0
        for y in range(y_a, y_b, 2):
            s += abs(gp[x + 1, y] - gp[x - 1, y])
        if s > best_s:
            best_s = s
            best_x = x
    # не уезжать слишком вправо
    if best_x > x0 + int(w * 0.28):
        return x0 + max(2, int(w * 0.04))
    return max(x0, best_x - 2)


def find_card_rect(im: Image.Image) -> CardRect | None:
    """ID-1 бланк: текстурный силуэт (гильош/сетка), не однотонная стена."""
    rgb = im.convert("RGB")
    gray = rgb.convert("L")
    src_w, src_h = rgb.size
    scale = 2 if src_w >= 400 else 1
    small = gray.resize((max(1, src_w // scale), max(1, src_h // scale)), Image.Resampling.BILINEAR)
    sw, sh = small.size
    sp = small.load()
    win = 2
    mask = [[False] * sw for _ in range(sh)]
    for y in range(win, sh - win):
        for x in range(win, sw - win):
            if sp[x, y] < 55:
                continue
            vals = [
                sp[x + dx, y + dy]
                for dy in range(-win, win + 1)
                for dx in range(-win, win + 1)
            ]
            mean = sum(vals) / len(vals)
            var = sum((t - mean) ** 2 for t in vals) / len(vals)
            mask[y][x] = var > 35 and mean > 70

    seen = [[False] * sw for _ in range(sh)]
    candidates: list[tuple[float, int, int, int, int, int]] = []
    for y in range(sh):
        for x in range(sw):
            if not mask[y][x] or seen[y][x]:
                continue
            q: deque[tuple[int, int]] = deque([(x, y)])
            seen[y][x] = True
            xs = [x]
            ys = [y]
            while q:
                cx, cy = q.popleft()
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < sw and 0 <= ny < sh and mask[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        q.append((nx, ny))
                        xs.append(nx)
                        ys.append(ny)
            if len(xs) < 200:
                continue
            box = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)
            bw, bh = box[2] - box[0], box[3] - box[1]
            if bw < 40 or bh < 24:
                continue
            aspect = bw / bh if bh else 0
            area_frac = (bw * bh) / max(1, sw * sh)
            if area_frac > 0.72 or area_frac < 0.05:
                continue
            if aspect < 1.25 or aspect > 2.15:
                continue
            aspect_pen = 1.0 - min(1.0, abs(aspect - ID1_ASPECT) / 0.45)
            score = len(xs) * (0.30 + 0.70 * aspect_pen)
            candidates.append((score, len(xs), box[0], box[1], box[2], box[3]))

    if not candidates:
        return None
    candidates.sort(reverse=True)
    _score, _n, x0, y0, x1, y1 = candidates[0]
    x = x0 * scale
    y = y0 * scale
    w = (x1 - x0) * scale
    h = (y1 - y0) * scale

    # уточнить левый край и подогнать под ID-1 (верх бланка сохраняем — шапка 10/11)
    x = _refine_left_edge(gray, (x, y, x + w, y + h))
    right = x0 * scale + (x1 - x0) * scale
    w = max(80, right - x)
    ideal_h = int(round(w / ID1_ASPECT))
    if abs(h - ideal_h) > max(8, int(h * 0.08)):
        h = min(ideal_h, src_h - y)
    # чуть подтянуть верх к реальной кромке карты (текстура часто захватывает фон выше)
    top_nudge = max(0, int(h * 0.04))
    y += top_nudge
    h = max(50, h - top_nudge)
    inset_x = max(2, int(w * 0.012))
    inset_y = max(1, int(h * 0.012))
    x += inset_x
    y += inset_y
    w -= inset_x * 2
    h -= inset_y * 2
    if w < 80 or h < 50:
        return None
    log.info("back card %sx%s @ %s,%s aspect=%.2f", w, h, x, y, w / max(h, 1))
    return CardRect(x, y, w, h)


def fallback_card_rect(im: Image.Image) -> CardRect:
    src_w, src_h = im.size
    w = max(80, int(src_w * 0.66))
    h = max(50, int(round(w / ID1_ASPECT)))
    if h > int(src_h * 0.42):
        h = max(50, int(src_h * 0.32))
        w = max(80, int(round(h * ID1_ASPECT)))
    x = max(0, int(src_w * 0.18))
    if x + w > src_w:
        x = max(0, src_w - w)
    y = max(0, int(src_h * 0.23))
    if y + h > src_h:
        y = max(0, src_h - h)
    log.warning("back card fallback %sx%s @ %s,%s", w, h, x, y)
    return CardRect(x, y, w, h)


def _local_maxima(scores: list[tuple[int, int]], *, min_gap: int, min_score: int) -> list[int]:
    """scores: (score, coord) in coord order."""
    peaks: list[tuple[int, int]] = []
    n = len(scores)
    for i in range(2, n - 2):
        sc, coord = scores[i]
        if sc < min_score:
            continue
        if (
            sc >= scores[i - 1][0]
            and sc >= scores[i + 1][0]
            and sc >= scores[i - 2][0]
            and sc >= scores[i + 2][0]
        ):
            if not peaks or coord - peaks[-1][1] >= min_gap:
                peaks.append((sc, coord))
            elif sc > peaks[-1][0]:
                peaks[-1] = (sc, coord)
    peaks.sort(key=lambda t: t[1])
    return [c for _s, c in peaks]


def detect_table_geometry(
    im: Image.Image,
    card: CardRect,
) -> tuple[dict[str, float], dict[str, float]] | None:
    """Строки по буквам категорий слева; колонки 10/11 — фикс. доли бланка (не путать с 12)."""
    gray = im.convert("L")
    gp = gray.load()

    # --- строки: тёмные пики в колонке букв A/B/M ---
    x0 = card.x + int(card.w * 0.09)
    x1 = card.x + int(card.w * 0.24)
    y0 = max(0, card.y + int(card.h * 0.06))
    y1 = min(im.size[1], card.y + int(card.h * 0.92))
    if x1 - x0 < 8 or y1 - y0 < 40:
        return None

    series: list[tuple[float, int]] = []
    for y in range(y0, y1):
        dark = 0
        for x in range(x0, x1):
            if gp[x, y] < 115:
                dark += 1
        series.append((float(dark), y))
    # сглаживание
    smooth: list[tuple[float, int]] = []
    for i in range(len(series)):
        window = series[max(0, i - 1) : i + 2]
        smooth.append((sum(t[0] for t in window) / len(window), series[i][1]))

    peaks: list[tuple[float, int]] = []
    for i in range(2, len(smooth) - 2):
        sc, y = smooth[i]
        if sc < 2.5:
            continue
        if sc >= smooth[i - 1][0] and sc >= smooth[i + 1][0] and sc >= smooth[i - 2][0]:
            if not peaks or y - peaks[-1][1] >= 7:
                peaks.append((sc, y))
            elif sc > peaks[-1][0]:
                peaks[-1] = (sc, y)
    peaks.sort(key=lambda t: t[1])
    if len(peaks) < 14:
        return None

    def _seg_score(ys: list[int]) -> float:
        if len(ys) < 16:
            return 1e9
        gaps = [ys[i + 1] - ys[i] for i in range(15)]
        mean = sum(gaps) / 15
        var = sum((g - mean) ** 2 for g in gaps) / 15
        # первый зазор не должен быть «дырой» над таблицей
        head_pen = 0 if gaps[0] <= mean * 1.6 else (gaps[0] - mean) * 3
        b_frac = (ys[2] - card.y) / max(card.h, 1)
        b_pen = 0 if 0.24 <= b_frac <= 0.42 else abs(b_frac - 0.33) * 80
        m_frac = (ys[13] - card.y) / max(card.h, 1)
        m_pen = 0 if 0.64 <= m_frac <= 0.90 else abs(m_frac - 0.76) * 40
        step_pen = 0 if 5 <= mean <= 14 else 40
        return var + b_pen + m_pen + step_pen + head_pen

    best: tuple[float, list[int]] | None = None
    for start in range(0, max(1, len(peaks) - 15)):
        ys = [peaks[start + i][1] for i in range(min(16, len(peaks) - start))]
        if len(ys) < 16:
            continue
        score = _seg_score(ys)
        if best is None or score < best[0]:
            best = (score, ys)
    # если пиков ровно 16, но B слишком высоко — сдвиг «виртуально» на 1–2 шага вниз
    if best is not None and len(peaks) >= 16:
        base = [p[1] for p in peaks[:16]]
        step = max(5, int(round((base[-1] - base[0]) / 15)))
        for shift in (0, 1, 2):
            ys = [base[i] + shift * step for i in range(16)] if shift else list(base)
            # для shift>0 лучше взять peaks[shift:shift+16] если есть
            if shift and len(peaks) >= 16 + shift:
                ys = [peaks[shift + i][1] for i in range(16)]
            score = _seg_score(ys)
            if best is None or score < best[0]:
                best = (score, ys)
    if best is None:
        return None
    row_ys = best[1]
    # ложные пики над первой буквой A — сдвигаем, пока шаг не станет ровным
    for _ in range(3):
        gaps0 = [row_ys[i + 1] - row_ys[i] for i in range(15)]
        mean0 = sum(gaps0) / 15
        if gaps0[0] <= mean0 * 1.45:
            break
        step = max(5, int(round(sum(gaps0[1:]) / max(1, len(gaps0) - 1))))
        # сдвиг: отбросить первый Y, добавить строку снизу
        row_ys = row_ys[1:] + [row_ys[-1] + step]
        log.info("back table dropped head junk peak")

    row_frac = {
        name: round((row_ys[i] - card.y) / max(card.h, 1), 4)
        for i, name in enumerate(DEFAULT_ROWS)
        if i < len(row_ys)
    }
    if len(row_frac) < 14:
        return None

    # колонки: не автодетект (путает 11/12) — доли из бланка VU
    g = {
        "col10": 0.545,
        "col11": 0.685,
        "col10_left": 0.48,
        "col10_right": 0.61,
        "col11_left": 0.61,
        "col11_right": 0.76,
        "top": 0.115,
        "bottom": 0.850,
    }
    log.info(
        "back table rows B=%.3f B1=%.3f M=%.3f (letter peaks) cols fixed 0.48-0.76",
        row_frac.get("B", 0),
        row_frac.get("B1", 0),
        row_frac.get("M", 0),
    )
    return g, row_frac


def _sample(im: Image.Image, x: int, y: int) -> tuple[int, int, int]:
    x = max(0, min(im.size[0] - 1, x))
    y = max(0, min(im.size[1] - 1, y))
    pix = im.getpixel((x, y))
    if isinstance(pix, int):
        return (pix, pix, pix)
    return (int(pix[0]), int(pix[1]), int(pix[2]))


def _clear_ghosts_outside_card(im: Image.Image, card: CardRect) -> None:
    """Убрать только «летающие» даты ПОД картой (на стене), карту не трогаем."""
    gray = im.convert("L")
    pix = im.load()
    gp = gray.load()
    y0 = min(im.size[1] - 1, card.y + card.h + 4)
    y1 = min(im.size[1], card.y + card.h + max(28, int(card.h * 0.35)))
    x0 = max(0, card.x + int(card.w * 0.35))
    x1 = min(im.size[0], card.x + card.w + 8)
    if y1 <= y0 or x1 <= x0:
        return
    for y in range(y0, y1):
        for x in range(x0, x1):
            if gp[x, y] > 95:
                continue
            paper = _sample(im, x, min(im.size[1] - 1, y + 6))
            if sum(paper) < 200:
                paper = _sample(im, max(0, x - 12), y)
            pix[x, y] = paper


def _cell_box(
    card: CardRect,
    g: dict[str, float],
    row_frac: dict[str, float],
    cat: str,
    which: str,
) -> CellBox | None:
    key = str(cat).upper()
    frac = row_frac.get(key)
    if frac is None:
        idx = ROW_INDEX.get(key)
        if idx is None:
            return None
        frac = _TABLE_TOP + _TABLE_STEP * idx
    if which == "10":
        left = float(g.get("col10_left", 0.42))
        right = float(g.get("col10_right", 0.56))
    else:
        left = float(g.get("col11_left", 0.56))
        right = float(g.get("col11_right", 0.70))
    # высота ячейки ≈ половина шага соседних строк
    step = _TABLE_STEP
    keys = list(DEFAULT_ROWS)
    if key in ROW_INDEX and ROW_INDEX[key] + 1 < len(keys):
        nxt = keys[ROW_INDEX[key] + 1]
        if nxt in row_frac:
            step = max(0.025, abs(float(row_frac[nxt]) - float(frac)))
    half = card.h * step * 0.38
    cy = card.y + card.h * float(frac)
    y0 = int(round(cy - half))
    y1 = int(round(cy + half))
    x0 = card.x + int(card.w * left)
    x1 = card.x + int(card.w * right)
    pad = max(1, int(card.h * 0.006))
    y0 = max(card.y + pad, y0)
    y1 = min(card.y + card.h - pad, y1)
    x0 = max(card.x + pad, x0)
    x1 = min(card.x + card.w - pad, x1)
    if x1 - x0 < 8 or y1 - y0 < 4:
        return None
    return CellBox(x0, y0, x1, y1)


def _fit_font(text: str, max_w: int, max_h: int) -> ImageFont.ImageFont:
    lo, hi = 5, max(5, min(36, max_h + 2))
    best = _load_font(lo)
    probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    while lo <= hi:
        mid = (lo + hi) // 2
        font = _load_font(mid)
        bbox = probe.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if tw <= max_w and th <= max_h:
            best = font
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _draw_date_in_cell(im: Image.Image, text: str, cell: CellBox) -> None:
    """Рисуем только «чернила» даты — без засветки всего прямоугольника ячейки."""
    text = text.strip()
    if not text or cell.w < 6 or cell.h < 4:
        return
    target_h = max(6, int(round(cell.h * 0.82)))
    font = _fit_font(text, max(6, cell.w - 2), target_h)
    scale = 4
    cw, ch = cell.w * scale, cell.h * scale
    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    big = _load_font(max(5, int(getattr(font, "size", 8) * scale)))
    bbox = draw.textbbox((0, 0), text, font=big)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (cw - tw) // 2 - bbox[0]
    ty = (ch - th) // 2 - bbox[1]
    draw.text((tx, ty), text, fill=(16, 16, 20, 255), font=big)
    scaled = canvas.resize((cell.w, cell.h), Image.Resampling.LANCZOS)
    # убрать полупрозрачный ореол (он «забеливает» гильош)
    pix = scaled.load()
    for yy in range(scaled.size[1]):
        for xx in range(scaled.size[0]):
            r, g, b, a = pix[xx, yy]
            if a < 96:
                pix[xx, yy] = (0, 0, 0, 0)
            else:
                pix[xx, yy] = (r, g, b, 255)
    base = im.crop((cell.x0, cell.y0, cell.x1, cell.y1)).convert("RGBA")
    im.paste(Image.alpha_composite(base, scaled).convert("RGB"), (cell.x0, cell.y0))


def stamp_back_jpg(
    path: Path | str,
    *,
    table: dict[str, dict[str, str]],
    order: list[str] | tuple[str, ...] | None = None,
    geom: dict[str, Any] | None = None,
    draw_dates: bool = True,
) -> bool:
    src = Path(path)
    if not src.is_file():
        log.warning("back jpg missing: %s", src)
        return False
    src_geom = geom or {}
    g = {**DEFAULT_GEOM, **{k: v for k, v in src_geom.items() if k != "rows"}}
    row_frac = {**DEFAULT_ROW_FRAC, **(src_geom.get("rows") or {})}
    im = Image.open(src).convert("RGB")
    card = find_card_rect(im)
    if card is None and draw_dates:
        card = fallback_card_rect(im)
    if card is not None:
        _clear_ghosts_outside_card(im, card)
    elif not draw_dates:
        log.info("back jpg: skip ghost clear (no card) on %s", src.name)
        return True

    if not draw_dates:
        im.save(src, format="JPEG", quality=94, optimize=True)
        log.info("back jpg ghosts-only on %s", src.name)
        return True

    if card is None:
        card = fallback_card_rect(im)

    # живая геометрия сетки важнее шаблонных frac
    detected = detect_table_geometry(im, card)
    if detected:
        det_g, det_rows = detected
        g = {**g, **det_g}
        row_frac = {**row_frac, **det_rows}

    if not table:
        log.warning("back jpg: empty table for %s", src.name)
        return False

    rows = list(order or DEFAULT_ROWS)
    want = {c.upper() for c in STAMP_CATS}
    placed = 0
    for cat in rows:
        key = str(cat).upper()
        if key not in want:
            continue
        data = table.get(cat) or table.get(key)
        if not data or not str(data.get("open") or "").strip():
            continue
        cell10 = _cell_box(card, g, row_frac, key, "10")
        if cell10 is None:
            continue
        _draw_date_in_cell(im, str(data["open"]).strip(), cell10)
        expiry = str(data.get("expiry") or "").strip()
        if expiry:
            cell11 = _cell_box(card, g, row_frac, key, "11")
            if cell11 is not None:
                _draw_date_in_cell(im, expiry, cell11)
        placed += 1
        log.info(
            "back date %s @ y_frac=%.3f cell=%sx%s",
            key,
            row_frac.get(key, 0),
            cell10.w,
            cell10.h,
        )
    if placed < 1:
        log.warning("back jpg: no stampable categories on %s", src.name)
        return False
    im.save(src, format="JPEG", quality=94, optimize=True)
    log.info("back jpg stamped %s cats on %s (no card erase)", placed, src.name)
    return True


def stamp_back_from_text(
    path: Path | str,
    text_block: str,
    *,
    order: list[str] | tuple[str, ...] | None = None,
    geom: dict[str, Any] | None = None,
) -> bool:
    from text_parser import parse_client_block
    from text_realism import VU_BACK_ROWS, build_back_table_map

    block = parse_client_block(text_block)
    table = build_back_table_map(block)
    return stamp_back_jpg(
        path,
        table=table,
        order=order or VU_BACK_ROWS,
        geom=geom,
    )


def job_json_beside_back(path: Path | str) -> Path | None:
    src = Path(path)
    name = src.name
    if name.endswith("_back.jpg"):
        cand = src.with_name(name[: -len("_back.jpg")] + ".job.json")
        if cand.is_file():
            return cand
    return None


def ensure_back_jpg_stamped(
    path: Path | str,
    text_block: str | None = None,
    *,
    table: dict[str, dict[str, str]] | None = None,
    order: list[str] | tuple[str, ...] | None = None,
    geom: dict[str, Any] | None = None,
    draw_dates: bool | None = None,
) -> bool:
    src = Path(path)
    if not src.is_file():
        return False
    use_table = dict(table or {})
    use_order = order
    use_geom = geom
    use_draw = draw_dates
    job_file = job_json_beside_back(src)
    if job_file and (not use_table or use_geom is None or use_draw is None):
        try:
            data = json.loads(job_file.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            data = {}
        if not use_table:
            use_table = data.get("back_table_map") or {}
        if use_order is None:
            use_order = data.get("back_table_order")
        if use_geom is None:
            use_geom = data.get("back_table_geom")
        if use_draw is None and "back_jpg_draw_dates" in data:
            use_draw = bool(data.get("back_jpg_draw_dates"))
    if use_draw is None:
        use_draw = True
    if (use_table or not use_draw) and stamp_back_jpg(
        src,
        table=use_table,
        order=use_order,
        geom=use_geom,
        draw_dates=use_draw,
    ):
        return True
    if use_draw and text_block:
        return stamp_back_from_text(src, text_block, order=use_order, geom=use_geom)
    log.warning("back jpg stamp skipped: no table for %s", src.name)
    return False
