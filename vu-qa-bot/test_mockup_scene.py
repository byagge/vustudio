#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import unittest

from layer_values import build_render_payload, load_template
from mockup_scene import (
    build_scene_job_fields,
    list_backgrounds,
    list_mockups_info,
    normalize_options_for_mockup,
    scene_summary,
    validate_scene_options,
)
from render_models import MockupKind, RenderOptions
from test_text_parser import SAMPLE
from text_parser import parse_client_block


class TestMockupScene(unittest.TestCase):
    def test_blank_no_scene(self):
        opts = RenderOptions(mockup="blank", background=5)
        fields = build_scene_job_fields(opts, load_template("mockup_blank"))
        self.assertIsNone(fields["background"])
        self.assertEqual(fields["scene"], {})

    def test_hand_scene(self):
        opts = RenderOptions(mockup="hand", background=3)
        fields = build_scene_job_fields(opts, load_template("mockup_hand"))
        self.assertEqual(fields["background"], 3)
        self.assertEqual(fields["mockup_variant"], "hand")
        self.assertEqual(fields["scene"]["photo_smart_object"], "Photo")

    def test_original_variant(self):
        opts = RenderOptions(mockup="original", background=7)
        fields = build_scene_job_fields(opts)
        self.assertEqual(fields["mockup_variant"], "original")
        self.assertEqual(fields["background"], 7)

    def test_ten_backgrounds(self):
        bgs = list_backgrounds("mockup_hand")
        self.assertEqual(len(bgs), 10)
        self.assertEqual(bgs[0].layer_name, "Вариант 1")
        self.assertEqual(bgs[9].layer_name, "Вариант 10")

    def test_validate_bad_background(self):
        opts = RenderOptions(mockup="hand", background=99)
        errors = validate_scene_options(opts)
        self.assertTrue(any("1 до 10" in e for e in errors))

    def test_payload_includes_scene(self):
        block = parse_client_block(SAMPLE)
        payload = build_render_payload(
            block,
            load_template("mockup_hand"),
            options=RenderOptions(mockup="hand", background=2),
        )
        self.assertEqual(payload["background"], 2)
        self.assertIn("Меняющийся фон", payload["scene"]["background_smart_object"])

    def test_normalize_clears_portrait_on_blank(self):
        opts = RenderOptions(
            mockup="blank",
            generate_portrait=True,
            portrait_path="/tmp/x.jpg",
        )
        n = normalize_options_for_mockup(opts)
        self.assertFalse(n.generate_portrait)
        self.assertIsNone(n.portrait_path)

    def test_scene_summary(self):
        s = scene_summary(RenderOptions(mockup="hand", background=4))
        self.assertIn("Вариант 4", s)
        self.assertIn("рука", s)

    def test_list_mockups(self):
        infos = list_mockups_info()
        kinds = {m.kind for m in infos}
        self.assertEqual(kinds, {MockupKind.BLANK.value, MockupKind.HAND.value, MockupKind.ORIGINAL.value})


if __name__ == "__main__":
    unittest.main()
