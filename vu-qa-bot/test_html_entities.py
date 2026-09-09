#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Каждый текст бота — валидный Telegram HTML (без ENTITY_TEXT_INVALID)."""
from __future__ import annotations

import unittest

import tg_ui
from admin_tools import format_status_html
from formatter import BANNER, render_html
from vu_testdata import make_valid, new_rng, random_identity


class TestTelegramHtml(unittest.TestCase):
    def _ok(self, text: str, name: str) -> None:
        try:
            tg_ui.assert_telegram_html(text)
        except ValueError as e:
            self.fail(f"{name}: {e}\n---\n{text}\n---")

    def test_ce_is_tg_emoji(self):
        html = tg_ui.ce("chart")
        self.assertIn("tg-emoji", html)
        self.assertIn("5278778882848220741", html)
        self._ok(html, "ce_chart")

    def test_main_menu_text(self):
        self._ok(tg_ui.main_menu_text({"pending": 1, "processing": 0, "done": 3, "failed": 0}, True), "main_menu_text")
        self._ok(tg_ui.main_menu_text({"pending": 0, "processing": 0, "done": 0, "failed": 0}, False), "main_menu_offline")

    def test_status_screen(self):
        self._ok(
            tg_ui.status_screen(
                mode="server",
                worker_alive=True,
                pending=1,
                processing=2,
                done=3,
                failed=4,
                photoshop_ok=True,
                message="Worker online",
                current_job="abc",
                last_error="",
            ),
            "status_online",
        )
        self._ok(
            tg_ui.status_screen(
                mode="server",
                worker_alive=False,
                pending=0,
                processing=0,
                done=25,
                failed=0,
                photoshop_ok=False,
            ),
            "status_offline",
        )

    def test_format_status_html(self):
        from unittest.mock import patch
        from photoshop_server import RenderServerStatus, QueueStats

        fake = RenderServerStatus(
            mode="server",
            worker_alive=False,
            worker=None,
            queue=QueueStats(pending=0, processing=0, done=1, failed=0),
            photoshop_configured=True,
            photoshop_available=False,
            output_dir=".",
            queue_dir=".",
            message="Worker offline — a & b",
        )
        with patch("admin_tools.get_server_status", return_value=fake):
            self._ok(format_status_html(), "format_status_html")

    def test_profile_screen(self):
        self._ok(
            tg_ui.profile_screen(
                user_id=2042724515,
                username="user_name",
                first_name="Name <test>",
                generations=3,
                renders=2,
                jobs_done=1,
                jobs_failed=0,
                jobs_pending=1,
            ),
            "profile_screen",
        )
        self._ok(tg_ui.profile_screen(user_id=1), "profile_empty")

    def test_jobs_and_detail(self):
        self._ok(tg_ui.jobs_screen_text(0), "jobs_empty")
        self._ok(tg_ui.jobs_screen_text(20, 1, 3), "jobs_page")
        self._ok(
            tg_ui.job_detail_text(
                job_id="abc123def456",
                status="done",
                title="ИВАНОВ",
                mockup="hand",
                background=3,
                error=None,
                fields={"surname_ru": "ИВАНОВ", "number": "123456"},
            ),
            "job_detail",
        )
        self._ok(
            tg_ui.job_detail_text(
                job_id="x",
                status="failed",
                title="",
                mockup="hand",
                background=1,
                error="fail & <err>",
                fields={},
            ),
            "job_failed",
        )

    def test_render_prompt_and_hint(self):
        self._ok(tg_ui.render_prompt_text("рука, фон 5", 5), "render_prompt")
        self._ok(tg_ui.render_prompt_text("x & y", 10), "render_prompt_10")
        self._ok(tg_ui.generate_hint_text(), "generate_hint")

    def test_formatter_html(self):
        rec = make_valid(new_rng(), identity=random_identity(new_rng()), valid_now=True)
        self._ok(render_html(rec, debug=True), "render_html_debug")
        self._ok(render_html(rec, debug=False), "render_html_client")
        self._ok(BANNER, "banner")

    def test_digits_and_all_ce(self):
        for name in tg_ui.EMOJI:
            html = tg_ui.ce(name)
            self.assertIn("tg-emoji", html)
            self._ok(html, f"ce:{name}")
        for n in range(10):
            html = tg_ui.ce_digit(n)
            self.assertIn("tg-emoji", html)
            self._ok(html, f"digit:{n}")

    def test_status_screen_escapes_errors(self):
        self._ok(
            tg_ui.status_screen(
                mode="server",
                worker_alive=False,
                pending=0,
                processing=0,
                done=0,
                failed=1,
                photoshop_ok=False,
                message="Worker offline; a & b",
                last_error="fail & <err>",
                current_job="job_1 & x",
            ),
            "status_special_chars",
        )

    def test_assert_rejects_invalid(self):
        self._ok(tg_ui.ce("user"), "ce_user")
        with self.assertRaises(ValueError):
            tg_ui.assert_telegram_html("A & B")
        with self.assertRaises(ValueError):
            tg_ui.assert_telegram_html("Name <test>")


if __name__ == "__main__":
    unittest.main()
