#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка scene мокапа против PSB (task4 §12)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

VU = Path(__file__).resolve().parent.parent / "vu-qa-bot"
if str(VU) not in sys.path:
    sys.path.insert(0, str(VU))

from mockup_scene import verify_all_scenes  # noqa: E402


def main() -> int:
    report = verify_all_scenes()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    for name, tpl in report["templates"].items():
        status = "OK" if tpl["ok"] else "FAIL"
        bg = len(tpl["found_backgrounds"])
        print(
            f"\n{name} [{status}] PSB={'yes' if tpl['psb_exists'] else 'NO'} "
            f"backgrounds={bg}/10 layers={tpl['layer_count']}"
        )
        if tpl.get("missing_backgrounds"):
            print("  missing backgrounds:", ", ".join(tpl["missing_backgrounds"]))
        if tpl.get("missing_layers"):
            print("  missing layers:", ", ".join(tpl["missing_layers"]))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
