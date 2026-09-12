#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Даты 10/11 на обороте: рисуем на готовом JPG по найденному бланку."""
from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

log = logging.getLogger("back_jpg_dates")

ID1_ASPECT = 85.6 / 53.98
DEFAULT_ROWS = (
    "A", "A1", "B", "B1", "C", "C1", "D", "D1",
    "BE", "CE", "C1E", "DE", "D1E", "M", "Tm", "Tb",
)
# Центры граф 10/11 и границы ячеек (доли ширины бланка).
DEFAULT_GEOM = {
    "col10": 0.610,
    "col11": 0.790,
    "col10_left": 0.520,
    "col10_right": 0.700,
    "col11_left": 0.700,
    "col11_right": 0.880,
    "top": 0.115,
    "bottom": 0.850,
}

# Середины строк (визуальные центры A..Tb на бланке в сцене).
_TABLE_TOP = 0.088
_TABLE_STEP = 0.0545
DEFAULT_ROW_FRAC = {
    name: round(_TABLE_TOP + _TABLE_STEP * i, 4)
    for i, name in enumerate(DEFAULT_ROWS)
}
ROW_INDEX = {name: i for i, name in enumerate(DEFAULT_ROWS)}
N_TABLE_ROWS = len(DEFAULT_ROWS)


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


def find_card_rect(im: Image.Image) -> CardRect | None:
    """Самое плотное бледное пятно ≈ пластиковая карта; пальцы сверху отрезаем."""
    rgb = im.convert("RGB")
    hsv = rgb.convert("HSV")
    src_w, src_h = rgb.size
    scale = 4 if src_w >= 600 else 2
    small = hsv.resize((max(1, src_w // scale), max(1, src_h // scale)), Image.Resampling.BILINEAR)
    sw, sh = small.size
    px = small.load()
    mask = [[False] * sw for _ in range(sh)]
    for y in range(sh):
        for x in range(sw):
            _h, sat, val = px[x, y]
            mask[y][x] = sat <= 48 and val >= 118

    seen = [[False] * sw for _ in range(sh)]
    best: tuple[int, int, int, int, int] | None = None
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
            if len(xs) < 60:
                continue
            box = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)
            bw, bh = box[2] - box[0], box[3] - box[1]
            if bw < 20 or bh < 12:
                continue
            if best is None or len(xs) > best[0]:
                best = (len(xs), box[0], box[1], box[2], box[3])

    if best is None:
        return None
    _, x0, y0, x1, y1 = best
    x = x0 * scale
    y = y0 * scale
    w = (x1 - x0) * scale
    h = (y1 - y0) * scale
    aspect = w / h if h else 0
    if aspect < 1.42:
        card_h = int(round(w / ID1_ASPECT))
        if 0 < card_h <= h:
            # пальцы перекрывают верх карты — не режем по нижнему краю впритык
            y = y + h - card_h - int(card_h * 0.12)
            h = card_h
            if y < y0 * scale:
                y = y0 * scale
    inset_x = max(2, int(w * 0.015))
    inset_y = max(2, int(h * 0.02))
    x += inset_x
    y += inset_y
    w -= inset_x * 2
    h -= inset_y * 2
    if w < 80 or h < 50:
        return None
    log.info("back card %sx%s @ %s,%s aspect=%.2f", w, h, x, y, w / h)
    return CardRect(x, y, w, h)


def fallback_card_rect(im: Image.Image) -> CardRect:
    """Если пятно не нашлось — типичный кадр «рука + карта» в центре."""
    src_w, src_h = im.size
    w = max(80, int(src_w * 0.50))
    h = max(50, int(round(w / ID1_ASPECT)))
    if h > int(src_h * 0.42):
        h = max(50, int(src_h * 0.30))
        w = max(80, int(round(h * ID1_ASPECT)))
    x = max(0, (src_w - w) // 2)
    y = max(0, int(src_h * 0.27))
    if y + h > src_h:
        y = max(0, src_h - h)
    log.warning("back card fallback %sx%s @ %s,%s", w, h, x, y)
    return CardRect(x, y, w, h)


def _sample(im: Image.Image, x: int, y: int) -> tuple[int, int, int]:
    x = max(0, min(im.size[0] - 1, x))
    y = max(0, min(im.size[1] - 1, y))
    pix = im.getpixel((x, y))
    if isinstance(pix, int):
        return (pix, pix, pix)
    return (int(pix[0]), int(pix[1]), int(pix[2]))


def _erase_old_marks(im: Image.Image, card: CardRect, geom: dict[str, float]) -> None:
    """Убрать даты, которые старый оверлей ставил под картой."""
    del geom  # API compat
    draw = ImageDraw.Draw(im)
    side_x = max(0, card.x - max(8, card.w // 20))
    below = _sample(im, side_x, min(im.size[1] - 2, card.y + card.h + max(16, card.h // 12)))
    draw.rectangle(
        [
            card.x + int(card.w * 0.16),
            card.y + card.h + 6,
            min(im.size[0] - 1, card.x + int(card.w * 0.98)),
            min(im.size[1] - 1, card.y + card.h + int(card.h * 0.95)),
        ],
        fill=below,
    )


def _cluster_ys(values: list[int], gap: int = 5) -> list[int]:
    out: list[int] = []
    for y in sorted(values):
        if not out or y - out[-1] > gap:
            out.append(y)
    return out


def find_table_row_ys(im: Image.Image, card: CardRect) -> list[int]:
    """Горизонтальные линии таблицы на бланке — якоря строк."""
    gray = im.convert("L")
    x0 = card.x + int(card.w * 0.40)
    x1 = card.x + int(card.w * 0.93)
    y0 = card.y + int(card.h * 0.10)
    y1 = card.y + int(card.h * 0.88)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return []
    raw: list[int] = []
    for y in range(y0 + 2, y1 - 2):
        acc = 0
        n = 0
        x = x0
        while x < x1:
            acc += gray.getpixel((x, y))
            n += 1
            x += 2
        mid = acc / n
        acc_a = acc_b = 0
        xa = x0
        while xa < x1:
            acc_a += gray.getpixel((xa, y - 2))
            acc_b += gray.getpixel((xa, y + 2))
            xa += 2
        if mid < min(acc_a / n, acc_b / n) - 2.5:
            raw.append(y)
    lines = _cluster_ys(raw, gap=5)
    log.info("table lines %s", lines)
    return lines


def table_row_borders(
    lines: list[int],
    card: CardRect,
    row_frac: dict[str, float],
    n_rows: int = N_TABLE_ROWS,
) -> list[int]:
    """n_rows+1 горизонтальных границ ячеек (верх A … низ Tb)."""
    need = n_rows + 1
    if lines and len(lines) >= 8:
        borders = [int(y) for y in lines]
        step = (borders[-1] - borders[0]) / max(1, len(borders) - 1)
        # линии часто без нижней границы последней строки
        while len(borders) < need:
            borders.append(int(round(borders[-1] + step)))
        if len(borders) > need:
            # если поймали лишние — равномерно ужимаем к need
            first, last = borders[0], borders[need - 1] if len(borders) >= need else borders[-1]
            if len(borders) > need:
                last = borders[-1]
            borders = [int(round(first + (last - first) * i / n_rows)) for i in range(need)]
        return borders

    tops = []
    for i, name in enumerate(DEFAULT_ROWS[:n_rows]):
        frac = float(row_frac.get(name, _TABLE_TOP + _TABLE_STEP * i))
        # row_frac — середина строки → верх = mid - step/2
        tops.append(card.y + card.h * (frac - _TABLE_STEP * 0.5))
    step = card.h * _TABLE_STEP
    borders = [int(round(tops[0]))]
    for i in range(n_rows):
        borders.append(int(round(tops[0] + step * (i + 1))))
    return borders


def _cat_border_index(cat: str, lines: list[int]) -> int | None:
    """Индекс строки в borders для категории.

    Детектор часто начинает линии с низа A / верха A1, из‑за чего
    idx из алфавита попадает на ряд ниже нужного (B→B1, M→Tm).
    При наличии линий сдвигаем на -1.
    """
    idx = ROW_INDEX.get(str(cat).upper())
    if idx is None:
        return None
    if lines and len(lines) >= 8:
        return max(0, idx - 1)
    return idx


def _cell_for_cat(
    cat: str,
    borders: list[int],
    card: CardRect,
    g: dict[str, float],
    which: str,
    *,
    lines: list[int] | None = None,
) -> CellBox | None:
    idx = _cat_border_index(cat, lines or [])
    if idx is None or idx + 1 >= len(borders):
        return None
    if which == "10":
        left = float(g.get("col10_left", 0.520))
        right = float(g.get("col10_right", 0.700))
    else:
        left = float(g.get("col11_left", 0.700))
        right = float(g.get("col11_right", 0.880))
    gap = max(1, borders[idx + 1] - borders[idx])
    pad_x = max(1, int(card.w * 0.006))
    # больше отступ сверху — иначе на фото даты липнут к верхней линии ряда
    pad_top = 2 if gap >= 7 else 1
    pad_bot = 1 if gap >= 7 else 0
    return CellBox(
        x0=card.x + int(card.w * left) + pad_x,
        y0=borders[idx] + pad_top,
        x1=card.x + int(card.w * right) - pad_x,
        y1=borders[idx + 1] - pad_bot,
    )


def _local_paper(im: Image.Image, x: int, y: int) -> tuple[int, int, int]:
    """Светлая бумага вокруг точки (медиана светлых соседей)."""
    samples: list[tuple[int, int, int]] = []
    for dy in range(-5, 6):
        for dx in range(-6, 7):
            if dx == 0 and dy == 0:
                continue
            r, g, b = _sample(im, x + dx, y + dy)
            if r + g + b >= 360:
                samples.append((r, g, b))
    if not samples:
        return _sample(im, x, y)
    samples.sort(key=lambda t: t[0] + t[1] + t[2])
    return samples[len(samples) // 2]


def _erase_date_ink(im: Image.Image, card: CardRect, g: dict[str, float]) -> None:
    """Стереть чернила дат в графах 10/11, сохранив гильош и линии сетки."""
    gray = im.convert("L")
    pix = im.load()
    gp = gray.load()
    y0 = card.y + int(card.h * 0.12)
    y1 = card.y + int(card.h * 0.88)
    max_run = max(8, int(card.w * 0.12))
    bands = (
        (float(g.get("col10_left", 0.500)), float(g.get("col10_right", 0.670))),
        (float(g.get("col11_left", 0.670)), float(g.get("col11_right", 0.860))),
    )
    # три прохода: ядро → расширение → добить полутона
    for _pass, thresh in enumerate((152, 145, 138)):
        grow = min(2, _pass)
        for left, right in bands:
            x0 = card.x + int(card.w * left)
            x1 = card.x + int(card.w * right)
            for y in range(y0, y1):
                x = x0
                while x < x1:
                    if gp[x, y] > thresh:
                        x += 1
                        continue
                    run_end = x
                    while run_end < x1 and gp[run_end, y] <= thresh:
                        run_end += 1
                    run = run_end - x
                    if run > max_run:
                        x = run_end
                        continue
                    for xx in range(max(x0, x - grow), min(x1, run_end + grow)):
                        if gp[xx, y] <= thresh + 12:
                            pix[xx, y] = _local_paper(im, xx, y)
                    x = run_end
        # обновить gray после прохода
        gray = im.convert("L")
        gp = gray.load()


def _fit_font(text: str, max_w: int, max_h: int) -> ImageFont.ImageFont:
    """Кегль, чтобы дата влезла в ячейку по ширине и высоте."""
    lo, hi = 5, max(5, min(32, max_h + 4))
    best = _load_font(lo)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    while lo <= hi:
        mid = (lo + hi) // 2
        font = _load_font(mid)
        bbox = probe.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        if tw <= max_w and th <= max_h:
            best = font
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _draw_date_in_cell(
    im: Image.Image,
    text: str,
    cell: CellBox,
    *,
    ink: tuple[int, int, int] = (22, 22, 26),
) -> None:
    """Дата строго по центру ячейки."""
    text = text.strip()
    if not text or cell.w < 4 or cell.h < 3:
        return
    target_h = max(5, int(round(cell.h * 0.62)))
    font = _fit_font(text, max(4, int(cell.w * 0.96)), target_h)
    # рендер на увеличенном холсте → даунскейл (чётче, чем прямой мелкий кегль)
    scale = 4
    cw, ch = max(8, cell.w * scale), max(8, cell.h * scale)
    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    big = _load_font(max(5, int(getattr(font, "size", 8) * scale)))
    bbox = d.textbbox((0, 0), text, font=big)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    # оптический центр заметно ниже геометрии — иначе цифры липнут к верхней линии
    tx = (cw - tw) // 2 - bbox[0]
    ty = (ch - th) // 2 - bbox[1] + max(scale + 2, th // 5)
    d.text((tx, ty), text, fill=ink + (245,), font=big)
    scaled = canvas.resize((cell.w, cell.h), Image.Resampling.LANCZOS)
    # блюр под зерно фото мокапа (рука+камера)
    blur = 0.55 if cell.h <= 12 else 0.40
    scaled = scaled.filter(ImageFilter.GaussianBlur(radius=blur))
    base = im.crop((cell.x0, cell.y0, cell.x1, cell.y1)).convert("RGBA")
    im.paste(Image.alpha_composite(base, scaled).convert("RGB"), (cell.x0, cell.y0))


def stamp_back_jpg(
    path: Path | str,
    *,
    table: dict[str, dict[str, str]],
    order: list[str] | tuple[str, ...] | None = None,
    geom: dict[str, Any] | None = None,
) -> bool:
    src = Path(path)
    if not src.is_file():
        log.warning("back jpg missing: %s", src)
        return False
    if not table:
        log.warning("back jpg: empty table for %s", src.name)
        return False
    rows = list(order or DEFAULT_ROWS)
    src_geom = geom or {}
    g = {**DEFAULT_GEOM, **{k: v for k, v in src_geom.items() if k != "rows"}}
    row_frac = {**DEFAULT_ROW_FRAC, **(src_geom.get("rows") or {})}
    im = Image.open(src).convert("RGB")
    card = find_card_rect(im) or fallback_card_rect(im)
    lines = find_table_row_ys(im, card)
    borders = table_row_borders(lines, card, row_frac)
    _erase_old_marks(im, card, g)
    _erase_date_ink(im, card, g)
    placed = 0
    for cat in rows:
        data = table.get(cat) or table.get(str(cat).upper())
        if not data or not str(data.get("open") or "").strip():
            continue
        open_s = str(data["open"]).strip()
        cell10 = _cell_for_cat(cat, borders, card, g, "10", lines=lines)
        if cell10 is None:
            continue
        _draw_date_in_cell(im, open_s, cell10)
        expiry = str(data.get("expiry") or "").strip()
        if expiry:
            cell11 = _cell_for_cat(cat, borders, card, g, "11", lines=lines)
            if cell11 is not None:
                _draw_date_in_cell(im, expiry, cell11)
        placed += 1
        log.info(
            "back date %s @ border_idx=%s cell10=%sx%s %s",
            cat,
            _cat_border_index(cat, lines),
            cell10.w,
            cell10.h,
            open_s,
        )
    if placed < 1:
        log.warning("back jpg: no open categories on %s", src.name)
        return False
    im.save(src, format="JPEG", quality=93, optimize=True)
    log.info("back jpg stamped %s cats on %s", placed, src.name)
    return True


def stamp_back_from_text(
    path: Path | str,
    text_block: str,
    *,
    order: list[str] | tuple[str, ...] | None = None,
    geom: dict[str, Any] | None = None,
) -> bool:
    """Даты 10/11 из текстового блока клиента — если job JSON потерял таблицу."""
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
) -> bool:
    """Штамп дат на оборотном JPG: таблица из аргументов, рядом лежащего job.json или текста."""
    src = Path(path)
    if not src.is_file():
        return False
    use_table = dict(table or {})
    use_order = order
    use_geom = geom
    job_file = job_json_beside_back(src)
    if job_file and (not use_table or use_geom is None):
        try:
            data = json.loads(job_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not use_table:
            use_table = data.get("back_table_map") or {}
        if use_order is None:
            use_order = data.get("back_table_order")
        if use_geom is None:
            use_geom = data.get("back_table_geom")
    if use_table and stamp_back_jpg(src, table=use_table, order=use_order, geom=use_geom):
        return True
    if text_block:
        return stamp_back_from_text(src, text_block, order=use_order, geom=use_geom)
    log.warning("back jpg stamp skipped: no table for %s", src.name)
    return False
