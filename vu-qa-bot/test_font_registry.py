#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import unittest

from font_registry import build_font_job_fields, fonts_status, list_font_specs, verify_font_files
from template_loader import load_template


class TestFontRegistry(unittest.TestCase):
    def test_font_files_exist(self):
        self.assertEqual(verify_font_files(), [])

    def test_specs(self):
        specs = list_font_specs()
        ids = {s.id for s in specs}
        self.assertEqual(ids, {"nomer", "nomer0"})

    def test_postscript_names(self):
        specs = {s.id: s for s in list_font_specs()}
        self.assertEqual(specs["nomer0"].postscript, "z_nomer0")
        self.assertIn("znomer", specs["nomer"].postscript_candidates())

    def test_job_fields_blank(self):
        tpl = load_template("mockup_blank")
        fonts = build_font_job_fields(tpl)
        by_name = fonts["by_layer_name"]
        self.assertEqual(by_name["04"], "z_nomer0")
        self.assertEqual(by_name["656492"], "z_nomer0")
        self.assertEqual(by_name["04 76 656492"], "znomer")
        self.assertIn("nomer0", fonts["catalog"])

    def test_status(self):
        st = fonts_status()
        self.assertFalse(st["errors"])
        self.assertEqual(len(st["fonts"]), 2)


if __name__ == "__main__":
    unittest.main()
