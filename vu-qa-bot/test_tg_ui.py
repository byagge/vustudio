#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

import tg_ui


class TestTgUi(unittest.TestCase):
    def test_custom_emoji_html(self):
        html = tg_ui.ce("chart")
        self.assertIn("tg-emoji", html)
        self.assertIn("5278778882848220741", html)

    def test_main_menu_layout(self):
        kb = tg_ui.main_menu_kb("https://panel.example.com", "https://t.me/arxixx")
        rows = kb.inline_keyboard
        self.assertEqual(len(rows), 6)
        self.assertEqual(len(rows[0]), 2)
        self.assertEqual(len(rows[1]), 1)
        self.assertEqual(len(rows[2]), 2)
        self.assertTrue(rows[4][0].web_app)
        self.assertEqual(rows[4][0].web_app.url, "https://panel.example.com")
        self.assertTrue(rows[5][0].url)

    def test_panel_falls_back_to_url_without_https(self):
        kb = tg_ui.main_menu_kb("http://localhost:8080", "https://t.me/arxixx")
        panel = kb.inline_keyboard[4][0]
        self.assertIsNone(panel.web_app)
        self.assertEqual(panel.url, "http://localhost:8080")

    def test_render_kb_has_back(self):
        kb = tg_ui.render_options_kb(5, True)
        last = kb.inline_keyboard[-1][0]
        self.assertEqual(last.callback_data, "m:home")
        marks = [b.text for row in kb.inline_keyboard[:2] for b in row]
        self.assertTrue(any(t.startswith("✓") and t.endswith("5") for t in marks))

    def test_menu_text_has_module(self):
        text = tg_ui.main_menu_text({"pending": 1, "processing": 0, "done": 3}, True)
        self.assertIn("VU Studio", text)
        self.assertIn("Выберите действие", text)


if __name__ == "__main__":
    unittest.main()
