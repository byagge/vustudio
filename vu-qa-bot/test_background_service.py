#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import tempfile
import unittest
from io import BytesIO

from PIL import Image

from background_service import prepare_upload, validate_background_bytes
from mockup_scene import build_scene_job_fields, scene_summary
from render_models import RenderOptions


class TestBackgroundService(unittest.TestCase):
    def _jpg_bytes(self, w: int = 800, h: int = 600) -> bytes:
        buf = BytesIO()
        Image.new("RGB", (w, h), (120, 80, 40)).save(buf, format="JPEG")
        return buf.getvalue()

    def test_validate_and_save(self):
        data = self._jpg_bytes()
        validate_background_bytes(data)
        with tempfile.TemporaryDirectory() as tmp:
            import os

            os.environ["RENDER_OUTPUT_DIR"] = tmp
            result = prepare_upload(data, 42)
            self.assertTrue(result.ok)
            self.assertTrue(result.path.is_file())

    def test_render_options_custom_bg_in_job(self):
        opts = RenderOptions(background=3, custom_background_path="/tmp/bg.jpg").normalized()
        self.assertIsNone(opts.custom_background_path)
        fields = build_scene_job_fields(opts)
        self.assertIsNone(fields.get("custom_background_path"))
        opts2 = RenderOptions(background=3)
        summary = scene_summary(opts2)
        self.assertIn("фон #3", summary)


if __name__ == "__main__":
    unittest.main()
