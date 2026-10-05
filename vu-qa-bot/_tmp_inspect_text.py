#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
from mockup_registry import get_mockup
from psb_utils import iter_nested_psbs, count_text_group_slots


def dump_text_groups(label: str, psb: Path) -> None:
    print(f"=== {label} {psb} exists={psb.is_file()} slots={count_text_group_slots(psb)} ===")
    if not psb.is_file():
        return
    for path, psd in iter_nested_psbs(psb):
        for layer in psd.descendants():
            if layer.name != "Text" or getattr(layer, "kind", "") != "group":
                continue
            print(f"--- Text @ {path} ---")
            for i, ch in enumerate(layer):
                kind = getattr(ch, "kind", "")
                if kind != "type":
                    print(f"{i:02d} [{kind}] name={ch.name!r} vis={getattr(ch, 'visible', None)}")
                    continue
                t = ch.text
                val = t if isinstance(t, str) else str(t)
                bbox = getattr(ch, "bbox", None)
                y = bbox[1] if bbox else "?"
                x = bbox[0] if bbox else "?"
                print(
                    f"{i:02d} name={ch.name!r} val={val!r} x={x} y={y} vis={ch.visible}"
                )


def dump_series_layers(label: str, psb: Path) -> None:
    print(f"=== series-like in {label} ===")
    if not psb.is_file():
        return
    keys = {"04", "76", "656492", "04 76 656492", "77", "35", "739911", "77 35 739911"}
    for path, psd in iter_nested_psbs(psb):
        for layer in psd.descendants():
            if getattr(layer, "kind", "") != "type":
                continue
            if layer.name in keys or (isinstance(layer.text, str) and layer.text in keys):
                eng = getattr(layer, "engine_dict", None) or {}
                font = None
                try:
                    style = eng.get("StyleRun", {}).get("RunArray", [{}])[0].get("StyleSheet", {})
                    font = style.get("StyleSheetData", {}).get("Font")
                except Exception:
                    pass
                print(f"{path} name={layer.name!r} text={layer.text!r} font={font}")


blank = get_mockup("blank").resolve_path()
hand = get_mockup("hand").resolve_path()
dump_text_groups("blank", blank)
dump_text_groups("hand", hand)
extract = Path(__file__).resolve().parent.parent / "_extract" / "hand_Text.psb"
dump_text_groups("hand_Text", extract)
dump_series_layers("blank", blank)
dump_series_layers("hand", hand)
