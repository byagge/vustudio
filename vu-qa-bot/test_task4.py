#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Интеграционные тесты task4: фон + мокап + серверный worker."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from layer_values import build_photoshop_job, build_render_payload, load_template
from mockup_registry import MOCKUPS
from mockup_scene import (
    build_scene_job_fields,
    list_mockups_info,
    normalize_options_for_mockup,
    verify_all_scenes,
    verify_scene_template,
)
from photoshop_server import (
    RenderMode,
    get_server_status,
    is_server_mode,
    queue_stats,
    render_mode,
)
from render_models import RenderOptions, RenderTask
from render_queue import RenderQueue
from template_cache import TemplateCache
from test_text_parser import SAMPLE
from text_parser import parse_client_block


class TestTask4Integration(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["RENDER_QUEUE_DIR"] = str(Path(self._tmpdir.name) / "queue")
        os.environ["RENDER_OUTPUT_DIR"] = str(Path(self._tmpdir.name) / "output")
        os.environ["RENDER_MODE"] = "server"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_three_mockup_modes(self):
        infos = {m.kind: m for m in list_mockups_info()}
        self.assertTrue(infos["blank"].supports_background is False)
        self.assertTrue(infos["hand"].supports_background)
        self.assertEqual(infos["hand"].mockup_variant, "hand")
        self.assertEqual(infos["original"].mockup_variant, "original")

    def test_hand_and_original_same_psb(self):
        hand = MOCKUPS["hand"].resolve_path()
        orig = MOCKUPS["original"].resolve_path()
        self.assertEqual(hand.name, orig.name)

    def test_scene_job_fields_hand(self):
        opts = RenderOptions(mockup="hand", background=5)
        fields = build_scene_job_fields(opts, load_template("mockup_hand"))
        self.assertEqual(fields["mockup_variant"], "hand")
        self.assertEqual(fields["background"], 5)
        self.assertEqual(fields["scene"]["background_count"], 10)

    def test_full_job_json_scene_block(self):
        task = RenderTask.create(
            SAMPLE,
            options=RenderOptions(mockup="original", background=7),
        )
        out = Path(self._tmpdir.name) / "output"
        out.mkdir(parents=True, exist_ok=True)
        job = build_photoshop_job(
            task,
            output_psd=out / "x.psb",
            output_jpg=out / "x.jpg",
        )
        self.assertEqual(job["mockup_variant"], "original")
        self.assertEqual(job["background"], 7)
        self.assertIn("hand_group", job["scene"])
        self.assertIn("fonts", job)

    def test_template_cache_flags(self):
        job = {"template": "/mock/hand.psb"}
        cached = TemplateCache().apply(job)
        self.assertIn("keep_template_open", cached)
        self.assertIn("reuse_open_template", cached)

    def test_server_mode_default(self):
        self.assertEqual(render_mode(), RenderMode.SERVER)
        self.assertTrue(is_server_mode())

    def test_queue_stats_empty(self):
        stats = queue_stats()
        self.assertEqual(stats.pending, 0)
        self.assertEqual(stats.total, 0)

    def test_server_status_structure(self):
        st = get_server_status()
        self.assertEqual(st.mode, "server")
        self.assertIsNotNone(st.queue)

    def test_verify_scene_template_structure(self):
        report = verify_scene_template("mockup_hand")
        for key in (
            "psb_exists",
            "psd_tools",
            "expected_backgrounds",
            "found_backgrounds",
            "missing_backgrounds",
            "missing_layers",
            "hand_group",
            "background_so",
        ):
            self.assertIn(key, report)

    def test_verify_all_scenes(self):
        raw = verify_all_scenes()
        self.assertIn("mockup_hand", raw["templates"])
        if not raw["templates"]["mockup_hand"]["psd_tools"]:
            self.skipTest("psd_tools not installed")

    def test_render_payload_blank_no_scene(self):
        block = parse_client_block(SAMPLE)
        payload = build_render_payload(
            block,
            load_template("mockup_blank"),
            options=RenderOptions(mockup="blank"),
        )
        self.assertIsNone(payload.get("background"))
        self.assertEqual(payload.get("scene"), {})

    def test_normalize_hand_to_blank(self):
        opts = RenderOptions(
            mockup="hand",
            background=8,
            generate_portrait=True,
            portrait_path="/x.jpg",
        )
        n = normalize_options_for_mockup(
            RenderOptions(mockup="blank", background=8, portrait_path="/x.jpg", generate_portrait=True)
        )
        self.assertIsNone(n.portrait_path)
        self.assertFalse(n.generate_portrait)

    def test_queue_enqueue_with_scene(self):
        q = RenderQueue(Path(os.environ["RENDER_QUEUE_DIR"]))
        task = RenderTask.create(
            SAMPLE,
            options=RenderOptions(mockup="hand", background=3),
        )
        q.enqueue(task)
        self.assertEqual(queue_stats().pending, 1)


if __name__ == "__main__":
    unittest.main()
