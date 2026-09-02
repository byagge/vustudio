#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import unittest

from admin_tools import admin_dashboard, format_status_text


class TestAdminTools(unittest.TestCase):
    def test_dashboard_structure(self):
        d = admin_dashboard()
        self.assertIn("server", d)
        self.assertIn("queue", d)
        self.assertIn("scene_verify", d)

    def test_status_text(self):
        t = format_status_text()
        self.assertIn("Режим:", t)
        self.assertIn("Worker:", t)


if __name__ == "__main__":
    unittest.main()
