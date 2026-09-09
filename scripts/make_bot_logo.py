#!/usr/bin/env python3
"""Rasterize web/static/bot-logo.svg into PNG/JPEG for Telegram."""
from __future__ import annotations

import math
import os
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "web" / "static"
SVG = OUT_DIR / "bot-logo.svg"
PNG = OUT_DIR / "bot-logo.png"
JPG = OUT_DIR / "bot-logo.jpg"

ACCENT = (0x10, 0xA3, 0x7F)
ACCENT_DARK = (0x0B, 0x6F, 0x57)
SIZE = 640
OVERSAMPLE = 4
ICON_FRACTION = 0.52
STROKE_VIEW = 2.05


def _try_resvg() -> bool:
    node = shutil.which("node")
    if not node or not SVG.exists():
        return False
    candidates = [
        Path(os.environ.get("TEMP", "/tmp")) / "otris-resvg" / "node_modules",
        ROOT / "node_modules",
    ]
    node_path = os.pathsep.join(str(p) for p in candidates if p.exists())
    if not node_path:
        return False
    script = (
        "const {Resvg}=require('@resvg/resvg-js');"
        "const fs=require('fs');"
        "const svg=fs.readFileSync(process.argv[1]);"
        "const r=new Resvg(svg,{fitTo:{mode:'width',value:Number(process.argv[3])}});"
        "fs.writeFileSync(process.argv[2], r.render().asPng());"
    )
    env = os.environ.copy()
    env["NODE_PATH"] = node_path + (os.pathsep + env["NODE_PATH"] if env.get("NODE_PATH") else "")
    try:
        subprocess.run(
            [node, "-e", script, str(SVG), str(PNG), str(SIZE)],
            check=True,
            env=env,
            cwd=str(candidates[0].parent if candidates[0].exists() else ROOT),
        )
        return PNG.exists()
    except (OSError, subprocess.CalledProcessError):
        return False


def _gradient(size: int) -> Image.Image:
    src = 384
    angle = math.radians(145)
    dx, dy = math.sin(angle), -math.cos(angle)
    corners = [dx * x + dy * y for x, y in ((0, 0), (src - 1, 0), (0, src - 1), (src - 1, src - 1))]
    tmin, tmax = min(corners), max(corners)
    im = Image.new("RGB", (src, src))
    px = im.load()
    span = tmax - tmin or 1.0
    for y in range(src):
        row = dy * y
        for x in range(src):
            t = (dx * x + row - tmin) / span
            px[x, y] = tuple(int(a + (b - a) * t) for a, b in zip(ACCENT, ACCENT_DARK))
    return im.resize((size, size), Image.Resampling.BICUBIC)


def _arc_points(
    x1: float, y1: float, rx: float, ry: float, large: int, sweep: int, x2: float, y2: float, n: int = 64
) -> list[tuple[float, float]]:
    rx, ry = abs(rx), abs(ry)
    dx = (x1 - x2) / 2.0
    dy = (y1 - y2) / 2.0
    lam = (dx * dx) / (rx * rx) + (dy * dy) / (ry * ry)
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx * rx * ry * ry - rx * rx * dy * dy - ry * ry * dx * dx
    den = rx * rx * dy * dy + ry * ry * dx * dx
    coef = math.sqrt(max(0.0, num / den))
    if large == sweep:
        coef = -coef
    cxp = coef * (rx * dy) / ry
    cyp = coef * -(ry * dx) / rx
    cx = cxp + (x1 + x2) / 2.0
    cy = cyp + (y1 + y2) / 2.0

    def ang(ux: float, uy: float, vx: float, vy: float) -> float:
        dot = ux * vx + uy * vy
        nrm = math.hypot(ux, uy) * math.hypot(vx, vy)
        a = math.acos(max(-1.0, min(1.0, dot / nrm)))
        if ux * vy - uy * vx < 0:
            a = -a
        return a

    theta1 = ang(1, 0, (dx - cxp) / rx, (dy - cyp) / ry)
    dtheta = ang((dx - cxp) / rx, (dy - cyp) / ry, (-dx - cxp) / rx, (-dy - cyp) / ry)
    if not sweep and dtheta > 0:
        dtheta -= 2 * math.pi
    elif sweep and dtheta < 0:
        dtheta += 2 * math.pi
    return [
        (cx + rx * math.cos(theta1 + dtheta * i / n), cy + ry * math.sin(theta1 + dtheta * i / n))
        for i in range(n + 1)
    ]


def _stroke(draw: ImageDraw.ImageDraw, points: list[tuple[float, float]], radius: float) -> None:
    if len(points) < 2:
        return
    width = max(1, int(round(radius * 2)))
    draw.line(points, fill="white", width=width, joint="curve")
    r = radius
    for x, y in (points[0], points[-1]):
        draw.ellipse((x - r, y - r, x + r, y + r), fill="white")


def _rounded_rect_path(x: float, y: float, w: float, h: float, r: float, n: int = 16) -> list[tuple[float, float]]:
    x0, y0, x1, y1 = x, y, x + w, y + h
    pts: list[tuple[float, float]] = []
    for i in range(n + 1):
        a = math.pi + (math.pi / 2) * i / n
        pts.append((x0 + r + r * math.cos(a), y0 + r + r * math.sin(a)))
    for i in range(n + 1):
        a = -math.pi / 2 + (math.pi / 2) * i / n
        pts.append((x1 - r + r * math.cos(a), y0 + r + r * math.sin(a)))
    for i in range(n + 1):
        a = 0 + (math.pi / 2) * i / n
        pts.append((x1 - r + r * math.cos(a), y1 - r + r * math.sin(a)))
    for i in range(n + 1):
        a = math.pi / 2 + (math.pi / 2) * i / n
        pts.append((x0 + r + r * math.cos(a), y1 - r + r * math.sin(a)))
    pts.append(pts[0])
    return pts


def _render_pil(size: int = SIZE) -> Image.Image:
    canvas = size * OVERSAMPLE
    img = _gradient(canvas)
    draw = ImageDraw.Draw(img)
    origin = canvas * (1.0 - ICON_FRACTION) / 2.0
    scale = canvas * ICON_FRACTION / 24.0
    radius = STROKE_VIEW * scale / 2.0

    def m(x: float, y: float) -> tuple[float, float]:
        return origin + x * scale, origin + y * scale

    _stroke(draw, [m(x, y) for x, y in _rounded_rect_path(2, 5, 20, 14, 2)], radius)
    _stroke(draw, [m(16, 10), m(18, 10)], radius)
    _stroke(draw, [m(16, 14), m(18, 14)], radius)
    cx, cy = m(9, 11)
    rr = 2 * scale
    n = 64
    circle = [
        (cx + rr * math.cos(2 * math.pi * i / n), cy + rr * math.sin(2 * math.pi * i / n))
        for i in range(n + 1)
    ]
    _stroke(draw, circle, radius)
    _stroke(draw, [m(x, y) for x, y in _arc_points(6.17, 15, 3, 3, 0, 1, 11.83, 15)], radius)
    return img.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not _try_resvg():
        _render_pil(SIZE).save(PNG, "PNG", optimize=True)
    img = Image.open(PNG).convert("RGB")
    img.save(JPG, "JPEG", quality=95, optimize=True, subsampling=0)
    print(f"wrote {PNG} ({PNG.stat().st_size} bytes)")
    print(f"wrote {JPG} ({JPG.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
