#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import unittest

from layer_values import build_render_payload, load_template
from text_parser import parse_client_block
from text_realism import build_layer_values, validate_block
from test_text_parser import SAMPLE


class TestTextRealism(unittest.TestCase):
    def test_authority_casing_blank_vs_hand(self):
        block = parse_client_block(SAMPLE)
        blank = build_layer_values(block, load_template("mockup_blank"))
        hand = build_layer_values(block, load_template("mockup_hand"))
        self.assertEqual(blank["authority_ru"], "ГИБДД 0469")
        self.assertEqual(hand["authority_ru"], "гибдд 0469")
        self.assertEqual(blank["authority_lat"], "gibdd 0469")

    def test_special_marks_line14_blank(self):
        block = parse_client_block(SAMPLE)
        payload = build_render_payload(block, load_template("mockup_blank"))
        self.assertEqual(payload["text_group_values"][-1], "14 СТАЖ С 2009")

    def test_special_year_hand(self):
        block = parse_client_block(SAMPLE)
        payload = build_render_payload(block, load_template("mockup_hand"))
        self.assertEqual(payload["text_group_values"][-1], "2009")

    def test_category_visibility(self):
        block = parse_client_block(SAMPLE)
        payload = build_render_payload(block, load_template("mockup_hand"))
        self.assertTrue(payload["category_visibility"]["b"])
        self.assertTrue(payload["category_visibility"]["b1"])
        self.assertTrue(payload["category_visibility"]["m"])

    def test_text_group_slot_count(self):
        block = parse_client_block(SAMPLE)
        blank = build_render_payload(block, load_template("mockup_blank"))
        hand = build_render_payload(block, load_template("mockup_hand"))
        self.assertEqual(len(blank["text_group_values"]), 12)
        self.assertEqual(len(hand["text_group_values"]), 12)
        self.assertEqual(len(blank["text_group_visibility"]), 12)

    def test_validate_sample(self):
        block = parse_client_block(SAMPLE)
        self.assertEqual(validate_block(block), [])


if __name__ == "__main__":
    unittest.main()
