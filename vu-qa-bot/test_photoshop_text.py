#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

from photoshop_text import (
    prepare_substitute_job,
    substitute_text_queued,
    validate_text_block,
    wait_substitute,
)
from render_queue import RenderQueue
from test_text_parser import SAMPLE


class TestPhotoshopText(unittest.TestCase):
    def test_validate_sample(self):
        self.assertEqual(validate_text_block(SAMPLE), [])

    def test_prepare_job_blank(self):
        with tempfile.TemporaryDirectory() as tmp:
            job, path = prepare_substitute_job(
                SAMPLE,
                mockup="blank",
                output_dir=Path(tmp),
            )
            self.assertTrue(path.is_file())
            self.assertIn("surname_ru", job["fields"])
            self.assertIn("АБСАЛЯМОВ", job["layers_by_name"].values())
            self.assertEqual(len(job["text_group_values"]), 12)

    def test_prepare_job_hand(self):
        with tempfile.TemporaryDirectory() as tmp:
            job, _ = prepare_substitute_job(SAMPLE, mockup="hand", output_dir=Path(tmp))
            self.assertEqual(job["mockup_variant"], "hand")
            self.assertEqual(job["background"], 1)
            self.assertEqual(job["text_group_values"][-1], "2009")

    def test_layers_by_field_semantic(self):
        with tempfile.TemporaryDirectory() as tmp:
            job, _ = prepare_substitute_job(SAMPLE, mockup="blank", output_dir=Path(tmp))
            by_field = job["layers_by_field"]
            self.assertEqual(by_field["surname_ru"], "АБСАЛЯМОВ")
            self.assertEqual(by_field["authority_ru"], "ГИБДД 0469")
            self.assertEqual(by_field["series_part1"], "04")

    def test_queue_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            import os

            os.environ["RENDER_QUEUE_DIR"] = tmp
            q = RenderQueue(Path(tmp))
            r = substitute_text_queued(SAMPLE, mockup="blank")
            self.assertTrue(r.ok)
            task = q.get(r.job_id)
            self.assertIsNotNone(task)
            task.psd_path = str(Path(tmp) / "out.psb")
            task.jpg_path = str(Path(tmp) / "out.jpg")
            q.complete(task)
            done = wait_substitute(r.job_id, timeout=1)
            self.assertTrue(done.ok)


if __name__ == "__main__":
    unittest.main()
