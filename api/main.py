#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FastAPI: REST API для генератора и валидатора ВУ."""
from __future__ import annotations

import sys
from pathlib import Path

# vu-qa-bot на PYTHONPATH
ROOT = Path(__file__).resolve().parent.parent / "vu-qa-bot"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.app import create_app  # noqa: E402

app = create_app()
