#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import unittest

from layer_values import field_values, load_template
from psb_utils import layout_slot_count, verify_template_against_psb
from template_cache import TemplateCache
from test_text_parser import SAMPLE
from text_parser import parse_client_block


class TestPsbUtils(unittest.TestCase):
    def test_layout_slot_count_blank(self):
        tpl = load_template("mockup_blank")
        n = layout_slot_count(tpl["back_table_layout"])
        self.assertEqual(n, 12)

    def test_layout_slot_count_hand(self):
        tpl = load_template("mockup_hand")
        n = layout_slot_count(tpl["back_table_layout"])
        self.assertEqual(n, 12)

    def test_field_values_alias(self):
        block = parse_client_block(SAMPLE)
        vals = field_values(block, load_template("mockup_blank"))
        self.assertEqual(vals["surname_ru"], "АБСАЛЯМОВ")

    def test_verify_blank_template(self):
        report = verify_template_against_psb("mockup_blank")
        self.assertEqual(report["layout_slots"], 12)
        self.assertTrue(report["text_group_slots"] >= 12 or report["ok"])

    def test_template_cache_reuse(self):
        cache = TemplateCache()
        job1 = cache.apply({"template": "D:/a.psb", "job_id": "1"})
        job2 = cache.apply({"template": "D:/a.psb", "job_id": "2"})
        self.assertTrue(job1["keep_template_open"])
        self.assertFalse(job1["reuse_open_template"])
        self.assertTrue(job2["reuse_open_template"])


if __name__ == "__main__":
    unittest.main()
