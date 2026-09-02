#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка шрифтов мокапа (assets/fonts)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VU = ROOT / "vu-qa-bot"
if str(VU) not in sys.path:
    sys.path.insert(0, str(VU))

from font_registry import build_font_job_fields, ensure_fonts_installed, fonts_status, verify_font_files  # noqa: E402
from template_loader import load_template  # noqa: E402


def main() -> int:
    ok = True
    errors = verify_font_files()
    if errors:
        ok = False
        for e in errors:
            print(f"ERROR: {e}")

    status = fonts_status()
    print(json.dumps(status, ensure_ascii=False, indent=2))

    fonts = build_font_job_fields(load_template("mockup_blank"))
    print("\nLayer -> PostScript:")
    for layer, ps in sorted(fonts["by_layer_name"].items()):
        print(f"  {layer} -> {ps}")

    if sys.platform == "win32":
        load_err = ensure_fonts_installed()
        if load_err:
            ok = False
            print("Load errors:", load_err)
        else:
            print("\nWindows: fonts loaded into session OK")
    else:
        print("\nSkip Windows font load (not win32)")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
