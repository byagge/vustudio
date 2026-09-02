#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Извлечь превью фонов «Вариант N» из PSB в assets/backgrounds/."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

VU = Path(__file__).resolve().parent.parent / "vu-qa-bot"
if str(VU) not in sys.path:
    sys.path.insert(0, str(VU))

from background_previews import extract_previews  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mockup", default="hand", help="hand | original")
    ap.add_argument("--overwrite", action="store_true", help="перезаписать существующие превью")
    args = ap.parse_args()

    report = extract_previews(mockup=args.mockup, overwrite=args.overwrite)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
