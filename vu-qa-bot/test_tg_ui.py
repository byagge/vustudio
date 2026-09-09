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

    def test_buttons_use_premium_icon(self):
        kb = tg_ui.main_menu_kb("https://photoshop.arix.vu", "https://t.me/arxixx")
        gen = kb.inline_keyboard[0][0]
        self.assertEqual(gen.text, "Сгенерировать")
        self.assertEqual(gen.icon_custom_emoji_id, tg_ui.eid("star"))
        self.assertEqual(kb.inline_keyboard[5][0].icon_custom_emoji_id, tg_ui.eid("megaphone"))

    def test_main_menu_layout(self):
        kb = tg_ui.main_menu_kb("https://photoshop.arix.vu", "https://t.me/arxixx")
        rows = kb.inline_keyboard
        self.assertEqual(len(rows), 6)
        self.assertEqual(len(rows[0]), 2)
        self.assertEqual(len(rows[1]), 1)
        self.assertEqual(len(rows[2]), 2)
        self.assertTrue(rows[4][0].web_app)
        self.assertEqual(rows[4][0].web_app.url, "https://photoshop.arix.vu")
        self.assertTrue(rows[5][0].url)

    def test_placeholder_https_is_not_miniapp(self):
        kb = tg_ui.main_menu_kb("https://panel.example.com", "https://t.me/arxixx")
        panel = kb.inline_keyboard[4][0]
        self.assertIsNone(panel.web_app)
        self.assertEqual(panel.url, "https://panel.example.com")

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

    def test_jobs_are_buttons(self):
        kb = tg_ui.jobs_list_kb(
            [{"job_id": "abc123def456", "status": "done", "title": "ИВАНОВ"}]
        )
        first = kb.inline_keyboard[0][0]
        self.assertEqual(first.callback_data, "jo:abc123def456")
        self.assertEqual(first.icon_custom_emoji_id, tg_ui.eid("ok"))
        self.assertNotIn("•", first.text)

    def test_jobs_pagination(self):
        kb = tg_ui.jobs_list_kb(
            [{"job_id": "abc123def456", "status": "pending", "title": "ПЕТРОВ"}],
            page=1,
            pages=3,
        )
        nav = kb.inline_keyboard[1]
        self.assertEqual(nav[0].callback_data, "jl:0")
        self.assertEqual(nav[1].callback_data, "jl:noop")
        self.assertEqual(nav[2].callback_data, "jl:2")

    def test_profile_is_stats(self):
        text = tg_ui.profile_screen(user_id=2042724515, username="user", generations=3, renders=2)
        self.assertIn("2042724515", text)
        self.assertIn("Генераций", text)
        self.assertIn("user", text)
        self.assertNotIn("@user", text)
        self.assertNotIn("ОТЧЕСТВО", text)

    def test_menu_text_has_module(self):
        text = tg_ui.main_menu_text({"pending": 1, "processing": 0, "done": 3}, True)
        self.assertIn("VU Studio", text)
        self.assertIn("Выберите действие", text)

    def test_status_screen_not_pre(self):
        text = tg_ui.status_screen(
            mode="server",
            worker_alive=False,
            pending=0,
            processing=0,
            done=25,
            failed=0,
            photoshop_ok=False,
        )
        self.assertIn("Worker offline", text)
        self.assertIn("tg-emoji", text)
        self.assertNotIn("<pre>", text)
        self.assertNotIn("Панель:", text)


if __name__ == "__main__":
    unittest.main()
