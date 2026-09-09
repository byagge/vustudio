#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
from pathlib import Path

from admin_tools import admin_dashboard, format_status_html, format_status_text


class TestAdminTools(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        os.environ["RENDER_QUEUE_DIR"] = str(self.tmp / "queue")
        os.environ["RENDER_OUTPUT_DIR"] = str(self.tmp / "output")
        os.environ["RENDER_MODE"] = "server"
        (self.tmp / "output").mkdir(parents=True)
        (self.tmp / "queue").mkdir(parents=True)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_dashboard_structure(self):
        d = admin_dashboard()
        self.assertIn("server", d)
        self.assertIn("queue", d)
        self.assertIn("scene_verify", d)

    def test_status_text(self):
        t = format_status_text()
        self.assertIn("Режим:", t)
        self.assertIn("Worker:", t)

    def test_status_html(self):
        t = format_status_html()
        self.assertIn("Статус", t)
        self.assertIn("Worker", t)
        self.assertNotIn("<pre>", t)


if __name__ == "__main__":
    unittest.main()
