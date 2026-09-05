#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from portrait_ai import FallbackGenerator, OpenAIGenerator
from portrait_config import PortraitSettings
from portrait_preprocess import prepare_portrait_file, validate_image_bytes
from portrait_prompt import build_portrait_prompt, estimate_age, estimate_gender
from portrait_service import generate_ai_portrait, prepare_upload, resolve_portrait, save_upload
from render_models import RenderOptions, RenderTask
from test_text_parser import SAMPLE
from text_parser import parse_client_block


class TestPortraitPrompt(unittest.TestCase):
    def test_prompt_no_pii(self):
        fields = {
            "surname_ru": "ИВАНОВ",
            "given_ru": "ИВАН ИВАНОВИЧ",
            "birth_date": "08.09.1983",
        }
        p = build_portrait_prompt(fields)
        self.assertNotIn("ИВАНОВ", p)
        self.assertIn("man", p.lower())

    def test_gender_female(self):
        fields = {"given_ru": "МАРИЯ ПЕТРОВНА", "surname_ru": "СИДОРОВА"}
        self.assertEqual(estimate_gender(fields), "F")

    def test_age(self):
        self.assertGreaterEqual(estimate_age("08.09.1983"), 18)


class TestPortraitPreprocess(unittest.TestCase):
    def test_prepare_resize(self):
        buf = io.BytesIO()
        Image.new("RGB", (800, 600), (200, 180, 170)).save(buf, format="JPEG")
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.jpg"
            dst = Path(tmp) / "out.jpg"
            src.write_bytes(buf.getvalue())
            cfg = PortraitSettings(
                openai_api_key=None,
                openai_model="dall-e-3",
                openai_size="1024x1024",
                api_url=None,
                api_key=None,
                width=390,
                height=507,
                jpeg_quality=90,
                provider="fallback",
                fallback_enabled=True,
                cache_enabled=False,
                timeout_sec=30,
            )
            prepare_portrait_file(src, dst, settings=cfg)
            with Image.open(dst) as im:
                self.assertEqual(im.size, (390, 507))

    def test_block_to_dict_has_gender(self):
        from render_models import block_to_dict

        fields = block_to_dict(parse_client_block(SAMPLE))
        self.assertIn("gender", fields)
        self.assertIn(fields["gender"], {"M", "F"})

    def test_validate_rejects_tiny(self):
        with self.assertRaises(ValueError):
            validate_image_bytes(b"x" * 10)


class TestPortraitService(unittest.TestCase):
    def test_fallback_generate(self):
        os.environ["PORTRAIT_PROVIDER"] = "fallback"
        os.environ["PORTRAIT_FALLBACK"] = "1"
        os.environ["PORTRAIT_CACHE"] = "0"
        fields = {
            "surname_ru": "ТЕСТ",
            "given_ru": "ТЕСТ ТЕСТОВИЧ",
            "birth_date": "01.01.1990",
            "gender": "M",
        }
        result = generate_ai_portrait(fields, job_id="testjob")
        self.assertTrue(result.ok, result.message)
        self.assertTrue(result.path and result.path.is_file())
        self.assertEqual(result.path.name, "gen_testjob.jpg")

    def test_upload_save_path(self):
        buf = io.BytesIO()
        Image.new("RGB", (400, 500), (180, 170, 160)).save(buf, format="JPEG")
        path = save_upload(buf.getvalue(), user_id=99999)
        self.assertEqual(path.name, "user_99999.jpg")
        self.assertTrue(path.parent.name == "portraits")

    def test_resolve_upload_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "p.jpg"
            Image.new("RGB", (400, 500), (150, 140, 130)).save(src, format="JPEG")
            task = RenderTask.create(
                SAMPLE,
                options=RenderOptions(
                    mockup="hand",
                    portrait_path=str(src),
                    generate_portrait=True,
                ),
            )
            path = resolve_portrait(task)
            self.assertIsNotNone(path)
            self.assertTrue(Path(path).is_file())


class TestPortraitAutoProvider(unittest.TestCase):
    def test_auto_prefers_openai_over_localhost_http(self):
        cfg = PortraitSettings(
            openai_api_key="sk-test",
            openai_model="dall-e-3",
            openai_size="1024x1024",
            api_url="http://127.0.0.1:8090/generate",
            api_key=None,
            width=390,
            height=507,
            jpeg_quality=90,
            provider="auto",
            fallback_enabled=True,
            cache_enabled=False,
            timeout_sec=30,
        )
        self.assertEqual(cfg.resolved_provider(), "openai")
        from portrait_ai import OpenAIGenerator, build_generators

        gens = build_generators(cfg)
        self.assertIsInstance(gens[0], OpenAIGenerator)


class TestOpenAIGeneratorMock(unittest.TestCase):
    def test_openai_parses_b64(self):
        import base64
        import json

        tiny = base64.b64encode(b"fake").decode()
        payload = json.dumps({"data": [{"b64_json": tiny}]}).encode()

        class FakeResp:
            def read(self):
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        cfg = PortraitSettings(
            openai_api_key="sk-test",
            openai_model="dall-e-3",
            openai_size="1024x1024",
            api_url=None,
            api_key=None,
            width=390,
            height=507,
            jpeg_quality=90,
            provider="openai",
            fallback_enabled=False,
            cache_enabled=False,
            timeout_sec=30,
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "raw.jpg"
            with patch("urllib.request.urlopen", return_value=FakeResp()):
                gen = OpenAIGenerator(cfg)
                r = gen.generate({"birth_date": "01.01.1990", "given_ru": "A B"}, out)
            self.assertTrue(r.ok)
            self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main()
