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

    def test_mockup_path_env_fallback(self):
        custom = Path(self._tmpdir.name) / "shared.psb"
        custom.write_bytes(b"x")
        old_hand = os.environ.pop("MOCKUP_HAND_PATH", None)
        old_orig = os.environ.pop("MOCKUP_ORIGINAL_PATH", None)
        old_shared = os.environ.get("MOCKUP_PATH")
        os.environ["MOCKUP_PATH"] = str(custom)
        try:
            self.assertEqual(MOCKUPS["hand"].resolve_path(), custom)
            self.assertEqual(MOCKUPS["original"].resolve_path(), custom)
        finally:
            if old_hand is None:
                os.environ.pop("MOCKUP_HAND_PATH", None)
            else:
                os.environ["MOCKUP_HAND_PATH"] = old_hand
            if old_orig is None:
                os.environ.pop("MOCKUP_ORIGINAL_PATH", None)
            else:
                os.environ["MOCKUP_ORIGINAL_PATH"] = old_orig
            if old_shared is None:
                os.environ.pop("MOCKUP_PATH", None)
            else:
                os.environ["MOCKUP_PATH"] = old_shared

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
        self.assertIn("Front", job["scene"]["card_smart_objects"])
        self.assertIn("Слой 0 копия", job["scene"]["card_wrappers"])
        self.assertIn("fonts", job)
        self.assertIn("blank_template", job)
        self.assertIn("УИК", job["layers_by_name"])
        self.assertIn("АБСАЛЯМОВ", job["layers_by_name"])
        self.assertEqual(job["layers_by_name"]["УИК"], "АБСАЛЯМОВ")
        self.assertEqual(job["layers_by_name"]["АБСАЛЯМОВ"], "АБСАЛЯМОВ")
        self.assertEqual(job["blank_layers_by_name"]["АБСАЛЯМОВ"], "АБСАЛЯМОВ")
        self.assertTrue(
            any(
                row["name"] == "13.01.2025" and row["value"] == "27.02.2009"
                for row in job["blank_text_replacements"]
            )
        )
        self.assertTrue(
            any(
                row["name"] == "04 76 656492" and "0476" in row["value"]
                for row in job["blank_text_replacements"]
            )
        )

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

    def test_jsx_closes_by_name_not_stale_handle(self):
        jsx = (Path(__file__).resolve().parent.parent / "photoshop" / "render.jsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("OTRIS_JSX_VERSION", jsx)
        self.assertIn("2026-09-05.12", jsx)
        self.assertIn("textStyleRange", jsx)
        self.assertIn("applyPortraitIfNeeded", jsx)
        self.assertIn("edit card SO in place", jsx)
        self.assertIn("card_wrappers", jsx)
        self.assertIn("renderBlankCard", jsx)
        self.assertIn("replaceCardSmartObjects", jsx)
        self.assertIn("openFileResilient", jsx)
        self.assertIn("closeCachedTemplate", jsx)
        self.assertIn("fillCardSmartObjectsInPlace", jsx)
        self.assertIn("isWrapperSmartObject", jsx)
        self.assertIn("setTextViaAM", jsx)
        self.assertIn("applyTextMapsDeep", jsx)
        self.assertIn("lookupReplacement", jsx)
        self.assertIn("card layers", jsx)
        self.assertIn("blank_template=", jsx)
        self.assertIn("smartObjectOpened", jsx)
        self.assertIn("closeOrphans", jsx)
        self.assertIn("isOrig || isHand", jsx)
        self.assertIn("editSmartObjectViaExport", jsx)
        self.assertIn("placedLayerReplaceContents", jsx)
        self.assertIn("function closeByName", jsx)
        self.assertIn('stringIDToTypeID("close")', jsx)
        self.assertNotIn("closeJobDocument(doc,", jsx)
        self.assertIn("outputsExist(psdFile, jpgFile)", jsx)
        self.assertIn("writeLog(jobPath, \"ok\")", jsx)
        self.assertIn("duplicate(dupName, true)", jsx)
        self.assertIn("SaveOptions.SAVECHANGES", jsx)
        self.assertIn("closeActive(true)", jsx)

    def test_wrapper_jsx_swallows_photoshop_errors(self):
        from photoshop_renderer import PhotoshopRenderer, RenderSettings

        jsx = Path(__file__).resolve().parent.parent / "photoshop" / "render.jsx"
        out = Path(self._tmpdir.name) / "ps-out"
        out.mkdir(parents=True, exist_ok=True)
        renderer = PhotoshopRenderer(RenderSettings(jsx_path=jsx, output_dir=out))
        job = out / "sample.job.json"
        job.write_text("{}", encoding="utf-8")
        wrapper = renderer._wrapper_jsx(job)
        text = wrapper.read_text(encoding="utf-8")
        self.assertIn("try {", text)
        self.assertIn("wrapper catch:", text)
        self.assertIn("$.evalFile(", text)

    def test_resolve_jsx_existing(self):
        from photoshop_renderer import _resolve_jsx

        p = _resolve_jsx()
        self.assertTrue(p.is_file(), p)

    def test_outputs_ready_and_jsx_ok_log(self):
        from photoshop_renderer import _jsx_reported_ok, _outputs_ready

        d = Path(self._tmpdir.name)
        psd = d / "a.psb"
        jpg = d / "a.jpg"
        self.assertFalse(_outputs_ready(psd, jpg))
        psd.write_bytes(b"x")
        jpg.write_bytes(b"y")
        self.assertTrue(_outputs_ready(psd, jpg))
        job = d / "a.job.json"
        job.write_text("{}", encoding="utf-8")
        (d / "a.job.json.log").write_text("close warn: x\nok\n", encoding="utf-8")
        self.assertTrue(_jsx_reported_ok(job))

    def test_wait_outputs_stable_size(self):
        from photoshop_renderer import _wait_outputs

        d = Path(self._tmpdir.name)
        psd = d / "w.psb"
        jpg = d / "w.jpg"
        self.assertFalse(_wait_outputs(psd, jpg, timeout=0.5))
        psd.write_bytes(b"x")
        jpg.write_bytes(b"y")
        self.assertTrue(_wait_outputs(psd, jpg, timeout=2))

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
