#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Загрузка JSON-шаблонов слоёв Photoshop."""
from __future__ import annotations

import json
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def load_template(name: str = "mockup_hand") -> dict:
    path = TEMPLATES_DIR / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Шаблон слоёв не найден: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
