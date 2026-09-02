#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

from render_models import RenderOptions, RenderTask
from render_queue import RenderQueue


class TestRenderQueue(unittest.TestCase):
    def test_enqueue_and_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = RenderQueue(Path(tmp))
            task = RenderTask.create(
                "1  Фамилия      TEST / TEST\n5  Номер        0101 123456",
                options=RenderOptions(mockup="blank"),
            )
            q.enqueue(task)
            claimed = q.claim("t")
            self.assertIsNotNone(claimed)
            self.assertEqual(claimed.job_id, task.job_id)
            claimed.psd_path = "/tmp/a.psd"
            claimed.jpg_path = "/tmp/a.jpg"
            q.complete(claimed)
            done = q.get(task.job_id)
            self.assertEqual(done.status, "done")
            self.assertIn("surname_ru", done.fields)


if __name__ == "__main__":
    unittest.main()
