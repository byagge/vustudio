#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Единая загрузка .env для всех entrypoint'ов vu-qa-bot."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv

    # Корневой otris/.env — главный; vu-qa-bot/.env только дополняет.
    load_dotenv(ROOT.parent / ".env")
    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass
