#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Извлечь имена текстовых слоёв из мокапа для templates/*.json (task2 §8-9).

Примеры:
  python scripts/discover_layers.py --mockup blank --json
  python scripts/discover_layers.py --mockup hand --write-template
  python scripts/discover_layers.py --mockup blank --verify
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

VU = Path(__file__).resolve().parent.parent / "vu-qa-bot"
if str(VU) not in sys.path:
    sys.path.insert(0, str(VU))

from mockup_registry import MOCKUPS, get_mockup  # noqa: E402
from psb_utils import collect_text_layers, verify_template_against_psb  # noqa: E402
from template_discovery import write_template_from_psb  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Дискавери текстовых слоёв PSB")
    p.add_argument("--mockup", choices=list(MOCKUPS.keys()), default="blank")
    p.add_argument("--json", action="store_true", help="Вывести список text layers")
    p.add_argument("--write-template", action="store_true", help="Записать templates/mockup_*.json")
    p.add_argument("--verify", action="store_true", help="Сверить шаблон с PSB")
    args = p.parse_args()

    spec = get_mockup(args.mockup)
    psb = spec.resolve_path()
    if not psb.is_file():
        print(f"PSB не найден: {psb}", file=sys.stderr)
        return 1

    if args.write_template:
        scene = {}
        tpl_path = Path(VU / "templates" / f"{spec.template}.json")
        if tpl_path.is_file():
            scene = json.loads(tpl_path.read_text(encoding="utf-8")).get("scene") or {}
        out = write_template_from_psb(
            psb,
            spec.template,
            description=spec.title,
            scene=scene,
        )
        print(f"written: {out}")
        return 0

    if args.verify:
        report = verify_template_against_psb(spec.template)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 2

    layers = collect_text_layers(psb)
    if args.json:
        print(json.dumps(layers, ensure_ascii=False, indent=2))
    else:
        for row in layers:
            vis = "V" if row["visible"] else "H"
            print(f"[{vis}] {row['path']!r} = {row['text']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
