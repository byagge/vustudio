#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Даты 10/11 на обороте JPG: только рисование в ячейках, без замазывания бланка.

Важно:
- НЕ стираем пиксели на карте (гильош / иконки / буквы категорий).
- НЕ рисуем вне бланка.
- Сценовый оверлей в JSX отключён — даты только здесь.
- Карта и строки таблицы ищутся по текстуре / линиям сетки.
- Колонки 10/11 — НЕ 12 (частая ошибка сдвига вправо).
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

# Графы 10/11: сразу после иконок. 10≈0.37–0.50, 11≈0.52–0.65 (не 12).
DEFAULT_GEOM = {
    "col10": 0.435,
    "col11": 0.585,
    "col10_left": 0.370,
    "col10_right": 0.500,
    "col11_left": 0.520,
    "col11_right": 0.650,
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
    """Узкий sans как на бланке ВУ (Arial Narrow → Arial)."""
    size = max(7, int(size))
    candidates: list[Path] = []
    # Сначала шрифты проекта (если когда-нибудь положим отдельный для дат).
    root = Path(__file__).resolve().parent.parent / "assets" / "fonts"
    for name in ("Z_NOMER0.TTF", "Z_NOMER.TTF"):
        candidates.append(root / name)
    for name in (
        "C:/Windows/Fonts/ARIALNB.TTF",
        "C:/Windows/Fonts/ARIALN.TTF",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
        "C:/Windows/Fonts/calibri.ttf",
        "C:/Windows/Fonts/tahoma.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        candidates.append(Path(name))
    for path in candidates:
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

    x = _refine_left_edge(gray, (x, y, x + w, y + h))
    right = x0 * scale + (x1 - x0) * scale
    w = max(80, right - x)
    ideal_h = int(round(w / ID1_ASPECT))
    if abs(h - ideal_h) > max(8, int(h * 0.08)):
        h = min(ideal_h, src_h - y)
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


def detect_column_bounds(im: Image.Image, card: CardRect) -> dict[str, float] | None:
    """Вертикали сетки: левый край 10, 10|11, 11|12."""
    gray = im.convert("L")
    gp = gray.load()
    x0 = card.x + int(card.w * 0.28)
    x1 = card.x + int(card.w * 0.95)
    y0 = card.y + int(card.h * 0.16)
    y1 = card.y + int(card.h * 0.82)
    if x1 - x0 < 30 or y1 - y0 < 40:
        return None

    scores: list[tuple[int, int]] = []
    for x in range(x0, x1):
        acc = 0
        for y in range(y0, y1):
            acc += abs(gp[x, y] - gp[max(x0, x - 1), y])
        scores.append((acc, x))

    scores.sort(reverse=True)
    peaks: list[int] = []
    min_gap = max(8, int(card.w * 0.06))
    floor = scores[0][0] * 0.28 if scores else 0
    for sc, x in scores:
        if sc < floor:
            break
        if all(abs(x - px) >= min_gap for px in peaks):
            peaks.append(x)
        if len(peaks) >= 7:
            break
    peaks.sort()
    fracs = [(x - card.x) / max(card.w, 1) for x in peaks]
    inner = [f for f in fracs if 0.32 <= f <= 0.78]
    if len(inner) < 3:
        return None

    best: tuple[float, tuple[float, float, float]] | None = None
    for i in range(len(inner) - 2):
        a, b, c = inner[i], inner[i + 1], inner[i + 2]
        g1, g2 = b - a, c - b
        if g1 < 0.08 or g2 < 0.08 or g1 > 0.22 or g2 > 0.22:
            continue
        if a > 0.48 or c > 0.78:
            continue
        pen = abs(g1 - g2) * 40 + abs(((g1 + g2) / 2) - 0.145) * 20
        if best is None or pen < best[0]:
            best = (pen, (a, b, c))
    if best is None:
        targets = (0.36, 0.51, 0.66)
        picked: list[float] = []
        used: set[int] = set()
        for t in targets:
            cand = [k for k in range(len(inner)) if k not in used]
            if not cand:
                return None
            j = min(cand, key=lambda k: abs(inner[k] - t))
            used.add(j)
            picked.append(inner[j])
        a, b, c = picked[0], picked[1], picked[2]
    else:
        a, b, c = best[1]

    pad = 0.012
    out = {
        "col10_left": round(a + pad, 4),
        "col10_right": round(b - pad, 4),
        "col11_left": round(b + pad, 4),
        "col11_right": round(c - pad, 4),
        "col10": round((a + b) / 2, 4),
        "col11": round((b + c) / 2, 4),
    }
    if out["col10_right"] - out["col10_left"] < 0.08:
        return None
    if out["col11_right"] - out["col11_left"] < 0.08:
        return None
    log.info(
        "back cols detected 10=[%.3f,%.3f] 11=[%.3f,%.3f]",
        out["col10_left"],
        out["col10_right"],
        out["col11_left"],
        out["col11_right"],
    )
    return out


def detect_table_geometry(
    im: Image.Image,
    card: CardRect,
) -> tuple[dict[str, float], dict[str, float]] | None:
    """Строки по буквам категорий; колонки 10/11 — детект вертикалей / fallback."""
    gray = im.convert("L")
    gp = gray.load()

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

    def _fill_to_16(ys: list[int]) -> list[int]:
        out = list(ys)
        if len(out) < 2:
            return out
        step = max(6, int(round((out[-1] - out[0]) / max(1, len(out) - 1))))
        while len(out) < 16:
            out.append(min(card.y + card.h - 2, out[-1] + step))
        return out[:16]

    # Якорь: пик буквы B. На этом JPG B ≈ frac 0.43 (не A1 ~0.38).
    b_idx = None
    b_best = None
    for i, (sc, y) in enumerate(peaks):
        frac = (y - card.y) / max(card.h, 1)
        if i < 2 or len(peaks) - i < 12:
            continue
        if not (0.40 <= frac <= 0.48):
            continue
        pen = abs(frac - 0.430) * 90.0 - float(sc) * 0.2
        if b_best is None or pen < b_best:
            b_best = pen
            b_idx = i
    if b_idx is None:
        start = 0
        while start < 3 and len(peaks) - start >= 15:
            probe = [peaks[start + j][1] for j in range(min(8, len(peaks) - start))]
            gaps0 = [probe[j + 1] - probe[j] for j in range(len(probe) - 1)]
            body = sum(gaps0[1:]) / max(1, len(gaps0) - 1)
            if gaps0 and gaps0[0] > body * 1.75:
                start += 1
                continue
            break
    else:
        start = max(0, b_idx - 2)

    raw = [peaks[start + i][1] for i in range(min(16, len(peaks) - start))]
    row_ys = _fill_to_16(raw)

    gaps_f = [row_ys[i + 1] - row_ys[i] for i in range(15)]
    body_gaps = gaps_f[1:] if gaps_f[0] > (sum(gaps_f[1:]) / 14) * 1.6 else gaps_f
    mean_gap = max(6, int(round(sum(body_gaps) / len(body_gaps))))
    # Пики у верхней границы → лёгкий сдвиг в центр ячейки (не на строку ниже).
    nudge = max(1, int(round(mean_gap * 0.28)))
    row_ys = [min(card.y + card.h - 4, y + nudge) for y in row_ys]

    row_frac = {
        name: round((row_ys[i] - card.y) / max(card.h, 1), 4)
        for i, name in enumerate(DEFAULT_ROWS)
        if i < len(row_ys)
    }
    if len(row_frac) < 14:
        return None

    # Колонки: автодетект, если графа 10 сразу после иконок (~0.36); иначе фикс.
    auto = detect_column_bounds(im, card)
    if auto is not None and 0.33 <= float(auto.get("col10_left", 0)) <= 0.42:
        cols = {
            "col10": float(auto["col10"]),
            "col11": float(auto["col11"]),
            "col10_left": float(auto["col10_left"]),
            "col10_right": float(auto["col10_right"]),
            "col11_left": float(auto["col11_left"]),
            "col11_right": float(auto["col11_right"]),
        }
    else:
        cols = {
            "col10": DEFAULT_GEOM["col10"],
            "col11": DEFAULT_GEOM["col11"],
            "col10_left": DEFAULT_GEOM["col10_left"],
            "col10_right": DEFAULT_GEOM["col10_right"],
            "col11_left": DEFAULT_GEOM["col11_left"],
            "col11_right": DEFAULT_GEOM["col11_right"],
        }
    g = {
        **cols,
        "top": 0.115,
        "bottom": 0.850,
        "row_step_px": float(mean_gap),
        # Высота глифа ≤ ~70% шага строки, иначе даты слипаются между рядами.
        "font_h_px": float(max(8, min(int(round(mean_gap * 0.72)), int(card.h * 0.045)))),
    }
    log.info(
        "back table start=%s b_idx=%s B=%.3f B1=%.3f M=%.3f gap=%s font_h=%s nudge=%s",
        start,
        b_idx,
        row_frac.get("B", 0),
        row_frac.get("B1", 0),
        row_frac.get("M", 0),
        mean_gap,
        g["font_h_px"],
        nudge,
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
        left = float(g.get("col10_left", DEFAULT_GEOM["col10_left"]))
        right = float(g.get("col10_right", DEFAULT_GEOM["col10_right"]))
    else:
        left = float(g.get("col11_left", DEFAULT_GEOM["col11_left"]))
        right = float(g.get("col11_right", DEFAULT_GEOM["col11_right"]))

    step_px = float(g.get("row_step_px") or 0)
    keys = list(DEFAULT_ROWS)
    if key in ROW_INDEX and ROW_INDEX[key] + 1 < len(keys):
        nxt = keys[ROW_INDEX[key] + 1]
        if nxt in row_frac:
            step_px = max(step_px, abs(float(row_frac[nxt]) - float(frac)) * card.h)
    if step_px < 6:
        step_px = max(8.0, card.h * 0.045)

    # ячейка под реальный font_h, иначе target_h клипается до ~8px
    font_h = float(g.get("font_h_px") or max(12.0, step_px * 1.3))
    half = max(7, int(round(max(step_px * 0.55, font_h * 0.58))))
    cy = card.y + card.h * float(frac)
    y0 = int(round(cy - half))
    y1 = int(round(cy + half))
    x0 = card.x + int(card.w * left)
    x1 = card.x + int(card.w * right)
    pad = max(1, int(card.h * 0.004))
    y0 = max(card.y + pad, y0)
    y1 = min(card.y + card.h - pad, y1)
    x0 = max(card.x + pad, x0)
    x1 = min(card.x + card.w - pad, x1)
    if x1 - x0 < 10 or y1 - y0 < 8:
        return None
    return CellBox(x0, y0, x1, y1)


def _harden_alpha(im: Image.Image, *, cut: int = 100) -> Image.Image:
    """Оставить только тёмные чернила; серый антиалиас/белый ореол убрать."""
    pix = im.load()
    for yy in range(im.size[1]):
        for xx in range(im.size[0]):
            r, g, b, a = pix[xx, yy]
            if a < cut or (r + g + b) > 220:
                pix[xx, yy] = (0, 0, 0, 0)
            else:
                pix[xx, yy] = (min(r, 24), min(g, 24), min(b, 28), 255)
    return im


def _scrub_cell_ink(im: Image.Image, cell: CellBox) -> None:
    """Убрать чернила старых дат (включая серые/полупрозрачные дубли). Гильош не трогаем."""
    if cell.w < 6 or cell.h < 4:
        return
    crop = im.crop((cell.x0, cell.y0, cell.x1, cell.y1)).convert("RGB")
    gray = crop.convert("L")
    gp = gray.load()
    cp = crop.load()
    samples: list[tuple[int, int, int]] = []
    for yy in range(crop.size[1]):
        for xx in range(crop.size[0]):
            # бумага/гильош — средние тона; не брать почти белое и почти чёрное
            if 140 <= gp[xx, yy] <= 215:
                samples.append(cp[xx, yy])
    if len(samples) < 8:
        return
    samples.sort(key=lambda t: sum(t))
    paper = samples[len(samples) // 2]
    for yy in range(crop.size[1]):
        for xx in range(crop.size[0]):
            # до ~120: чёрные даты + серые «призраки» / outline из PSD
            if gp[xx, yy] < 120:
                cp[xx, yy] = paper
    im.paste(crop, (cell.x0, cell.y0))


def _ghost_scrub_boxes(
    card: CardRect,
    g: dict[str, float],
    row_frac: dict[str, float],
    cat: str,
) -> list[CellBox]:
    """Только целевые 10/11 + типичный сдвиг в графу 12."""
    boxes: list[CellBox] = []
    for which in ("10", "11"):
        cell = _cell_box(card, g, row_frac, cat, which)
        if cell is not None:
            boxes.append(cell)
    shift = int(card.w * 0.13)
    extra: list[CellBox] = []
    for cell in boxes:
        extra.append(
            CellBox(
                min(card.x + card.w - 4, cell.x0 + shift),
                cell.y0,
                min(card.x + card.w - 2, cell.x1 + shift),
                cell.y1,
            )
        )
    boxes.extend(extra)
    return boxes


def _draw_date_in_cell(im: Image.Image, text: str, cell: CellBox, *, font_h: float | None = None) -> None:
    """Печать даты: высота как у букв категорий; ширина сжимается, если не влезает."""
    text = text.strip()
    if not text or cell.w < 8 or cell.h < 6:
        return

    target_h = max(8, int(round(font_h or (cell.h * 0.88))))
    target_h = min(target_h, cell.h)
    scale = 4
    big = _load_font(target_h * scale)

    probe = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    pb = ImageDraw.Draw(probe).textbbox((0, 0), text, font=big)
    tw, th = pb[2] - pb[0], pb[3] - pb[1]
    if tw < 1 or th < 1:
        return

    glyph = Image.new("RGBA", (tw + 8, th + 8), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glyph)
    # Один проход — без «жирного» сдвига, иначе на уже чистой ячейке появляется двоение.
    ox, oy = 4 - pb[0], 4 - pb[1]
    gd.text((ox, oy), text, fill=(4, 4, 6, 255), font=big)

    # обрезать пустые поля глифа — иначе «чернила» сидят у верхнего края бокса
    gp = glyph.load()
    gw, gh = glyph.size
    top_c = 0
    bot_c = gh - 1
    while top_c < gh and all(gp[x, top_c][3] < 20 for x in range(gw)):
        top_c += 1
    while bot_c > top_c and all(gp[x, bot_c][3] < 20 for x in range(gw)):
        bot_c -= 1
    if bot_c > top_c:
        glyph = glyph.crop((0, top_c, gw, bot_c + 1))
        tw, th = glyph.size

    out_h = min(cell.h - 1, max(target_h, int(round(th / scale))))
    out_h = max(8, min(cell.h - 1, out_h))
    nat_w = max(1, int(round(tw / scale * (out_h / max(1.0, th / scale)))))
    out_w = min(cell.w - 2, nat_w)
    out_w = max(6, out_w)

    scaled = glyph.resize((out_w, out_h), Image.Resampling.LANCZOS)
    _harden_alpha(scaled, cut=100)

    px = cell.x0 + (cell.w - out_w) // 2
    py = cell.y0 + max(0, (cell.h - out_h) // 2)
    if py + out_h > cell.y1:
        py = max(cell.y0, cell.y1 - out_h)
    base = im.crop((px, py, px + out_w, py + out_h)).convert("RGBA")
    im.paste(Image.alpha_composite(base, scaled).convert("RGB"), (px, py))


def _scrub_date_columns(im: Image.Image, card: CardRect, g: dict[str, float]) -> None:
    """Стереть старые даты во всех строках граф 10–12 (только почти чёрные пиксели)."""
    left = float(g.get("col10_left", DEFAULT_GEOM["col10_left"])) - 0.02
    right = float(g.get("col11_right", DEFAULT_GEOM["col11_right"])) + 0.14
    left = max(0.30, left)
    right = min(0.92, right)
    top = float(g.get("top", 0.115)) + 0.02
    bottom = float(g.get("bottom", 0.85))
    box = CellBox(
        card.x + int(card.w * left),
        card.y + int(card.h * top),
        card.x + int(card.w * right),
        card.y + int(card.h * bottom),
    )
    _scrub_cell_ink(im, box)


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
        # Не стираем графы 10/11 «в пустоту» — иначе пропадает то, что уже
        # написал Photoshop во вложенном Text SO. Просто оставляем JPG как есть.
        log.info("back jpg: skip stamp/scrub (draw_dates=false) on %s", src.name)
        return True

    if card is None:
        card = fallback_card_rect(im)

    detected = detect_table_geometry(im, card)
    if detected:
        det_g, det_rows = detected
        g = {**g, **det_g}
        b_frac = float(det_rows.get("B") or 0)
        b1_frac = float(det_rows.get("B1") or 0)
        m_frac = float(det_rows.get("M") or 0)
        if 0.25 <= b_frac <= 0.55:
            step = b1_frac - b_frac if 0.02 <= (b1_frac - b_frac) <= 0.08 else float(
                det_g.get("row_step_px") or 0
            ) / max(card.h, 1)
            if step < 0.02 or step > 0.08:
                step = 0.04
            # B / B1 с детектора; M / остальные активные — шагом от B (16 строк бланка).
            row_frac = dict(row_frac)
            row_frac["B"] = round(b_frac, 4)
            row_frac["B1"] = round(b_frac + step, 4)
            row_frac["M"] = round(b_frac + (ROW_INDEX["M"] - ROW_INDEX["B"]) * step, 4)
            if not (0.55 <= float(row_frac["M"]) <= 0.86):
                # fallback: M ≈ 0.74 бланка, если шаг увёл вниз
                row_frac["M"] = float(row_frac.get("M") or 0.74)
                if row_frac["M"] > 0.86 or row_frac["M"] < 0.55:
                    row_frac["M"] = 0.74
            log.info(
                "back jpg rows from B-anchor B=%.3f B1=%.3f M=%.3f step=%.3f (autoM=%.3f)",
                row_frac["B"],
                row_frac["B1"],
                row_frac["M"],
                step,
                m_frac,
            )
        else:
            log.info(
                "back jpg: keep template rows (auto B=%.3f unreliable)",
                b_frac,
            )
        log.info(
            "back jpg auto-geom col10=%.3f col11=%.3f",
            float(g.get("col10", 0)),
            float(g.get("col11", 0)),
        )

    if not table:
        log.warning("back jpg: empty table for %s", src.name)
        return False

    _scrub_date_columns(im, card, g)

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
        step_px = float(g.get("row_step_px") or (card.h * 0.04))
        font_h = float(g.get("font_h_px") or max(8, min(step_px * 0.72, card.h * 0.045)))
        font_h = min(font_h, max(8.0, cell10.h * 0.85))
        _draw_date_in_cell(im, str(data["open"]).strip(), cell10, font_h=font_h)
        expiry = str(data.get("expiry") or "").strip()
        if expiry:
            cell11 = _cell_box(card, g, row_frac, key, "11")
            if cell11 is not None:
                _draw_date_in_cell(im, expiry, cell11, font_h=font_h)
        placed += 1
        log.info(
            "back date %s @ y_frac=%.3f cell=%sx%s font_h=%.1f",
            key,
            row_frac.get(key, 0),
            cell10.w,
            cell10.h,
            font_h,
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
    # Hand/original: всегда рисуем даты 10/11 — клиентский оборот не может быть пустым.
    # Blank-карточки без сцены тоже ок с True (если table пуст — fallback на text_block).
    if use_draw is False and (use_table or text_block):
        log.warning("back jpg: forcing draw_dates=True (was false) for %s", src.name)
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
