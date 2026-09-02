#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сверка шаблонов с реальной структурой Text-слоёв в PSB (task2 §8-9)."""
from __future__ import annotations

import sys
from pathlib import Path

VU = Path(__file__).resolve().parent.parent / "vu-qa-bot"
if str(VU) not in sys.path:
    sys.path.insert(0, str(VU))

from psb_utils import verify_template_against_psb  # noqa: E402


def main() -> int:
    ok = True
    tpl_dir = VU / "templates"
    for tpl_path in sorted(tpl_dir.glob("mockup_*.json")):
        name = tpl_path.stem
        report = verify_template_against_psb(name)
        status = "OK" if report["ok"] else "MISMATCH"
        if not report["ok"]:
            ok = False
        print(
            f"{name}: layout={report['layout_slots']} "
            f"Text={report['text_group_slots']} "
            f"missing={len(report['missing_layer_names'])} [{status}]"
        )
        if report["missing_layer_names"]:
            for m in report["missing_layer_names"][:10]:
                print(f"  - layer not in PSB: {m}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
