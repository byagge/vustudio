#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Интеграция с portrait_api (task3 §6)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VU = ROOT / "vu-qa-bot"
for p in (str(VU), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from portrait_api.app import _generate_jpeg
from render_models import block_to_dict
from test_text_parser import SAMPLE
from text_parser import parse_client_block


class TestPortraitApi(unittest.TestCase):
    def test_render_jpeg_bytes(self):
        fields = block_to_dict(parse_client_block(SAMPLE))
        data, provider = _generate_jpeg(fields)
        self.assertGreater(len(data), 500)
        self.assertEqual(data[:2], b"\xff\xd8")
        self.assertTrue(provider)

    def test_fields_include_gender(self):
        fields = block_to_dict(parse_client_block(SAMPLE))
        self.assertIn("gender", fields)


if __name__ == "__main__":
    unittest.main()
