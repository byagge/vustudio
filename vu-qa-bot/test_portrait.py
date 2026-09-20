#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from portrait_ai import (
    FallbackGenerator,
    OpenAIGenerator,
    _image_bytes_for_edit,
    is_gpt_image_model,
    openai_image_body,
    resolve_openai_image_model,
)
from portrait_config import PortraitSettings
from portrait_preprocess import prepare_portrait_file, validate_image_bytes
from portrait_prompt import build_portrait_edit_prompt, build_portrait_prompt, estimate_age, estimate_gender
from portrait_service import (
    _already_enhanced,
    generate_ai_portrait,
    prepare_upload,
    resolve_portrait,
    save_upload,
)
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
        self.assertIn("driving-licence", p.lower())
        self.assertIn("document booth", p.lower())
        self.assertIn("icao", p.lower())
        self.assertIn("not a model", p.lower())
        self.assertIn("light-gray", p.lower())
        self.assertIn("shoulders", p.lower())
        self.assertIn("collar", p.lower())
        self.assertNotIn("face centered", p.lower())

    def test_edit_prompt_selfie_gray_bg(self):
        p = build_portrait_edit_prompt({"birth_date": "08.09.1983", "given_ru": "ИВАН ИВАНОВИЧ"})
        self.assertIn("4:3", p)
        self.assertIn("сером", p.lower())
        self.assertIn("gray", p.lower())
        self.assertIn("preserve", p.lower())
        self.assertNotIn("ИВАН", p)

    def test_gender_female(self):
        fields = {"given_ru": "МАРИЯ ПЕТРОВНА", "surname_ru": "СИДОРОВА"}
        self.assertEqual(estimate_gender(fields), "F")

    def test_age(self):
        self.assertGreaterEqual(estimate_age("08.09.1983"), 18)

    def test_unique_faces_same_year(self):
        from portrait_prompt import build_portrait_prompt as build

        a = build({"surname_ru": "ИВАНОВ", "given_ru": "ИВАН ИВАНОВИЧ", "birth_date": "01.01.1990"})
        b = build({"surname_ru": "ПЕТРОВ", "given_ru": "ПЁТР ПЕТРОВИЧ", "birth_date": "31.12.1990"})
        self.assertNotEqual(a, b)
        self.assertIn("unique identity", a)
        self.assertIn("unique identity", b)


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
            openrouter_api_key=None,
            openrouter_model="google/gemini-3.1-flash-lite-image",
            openrouter_base="https://openrouter.ai/api/v1",
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

    def test_flatten_cutout_on_gray(self):
        from portrait_preprocess import _flatten_cutout

        im = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
        im.putpixel((10, 10), (40, 50, 60, 255))
        flat = _flatten_cutout(im)
        self.assertEqual(flat.mode, "RGB")
        self.assertEqual(flat.getpixel((0, 0)), (228, 228, 228))

    def test_document_window_fills_frame(self):
        """ИИ-портрет закрывает всё окошко — без серых/белых полей по краям."""
        from portrait_preprocess import _document_window

        im = Image.new("RGB", (400, 400), (20, 20, 20))
        out = _document_window(im, 390, 507)
        self.assertEqual(out.size, (390, 507))
        # углы и края — не серая бумага
        for xy in ((8, 8), (8, 250), (380, 250), (195, 40), (195, 500)):
            self.assertLess(out.getpixel(xy)[0], 80, msg=f"empty margin at {xy}")

    def test_document_crop_lifts_centered_square(self):
        """Квадрат ИИ с лицом в центре → в 3×4 голова выше, без серого потолка."""
        from portrait_preprocess import _cover_crop

        im = Image.new("RGB", (400, 400), (210, 210, 210))
        for y in range(150, 240):
            for x in range(140, 260):
                im.putpixel((x, y), (20, 20, 20))
        out = _cover_crop(im, 390, 507, document=True)
        self.assertEqual(out.size, (390, 507))
        found_y = None
        for y in range(out.size[1]):
            if out.getpixel((195, y))[0] < 80:
                found_y = y
                break
        self.assertIsNotNone(found_y)
        self.assertGreater(found_y, 10)
        self.assertLess(found_y, 240)

    def test_document_crop_keeps_head_high(self):
        """После подготовки ИИ-кадра тёмное лицо оказывается в верхней половине."""
        im = Image.new("RGB", (400, 400), (210, 210, 210))
        for y in range(150, 240):
            for x in range(140, 260):
                im.putpixel((x, y), (20, 20, 20))
        cfg = PortraitSettings(
            openai_api_key=None,
            openai_model="gpt-image-1",
            openai_size="1024x1024",
            openrouter_api_key=None,
            openrouter_model="google/gemini-3.1-flash-lite-image",
            openrouter_base="https://openrouter.ai/api/v1",
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
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "id.jpg"
            dst_ai = Path(tmp) / "ai.jpg"
            im.save(src, format="JPEG")
            prepare_portrait_file(src, dst_ai, settings=cfg, face_focus=False)
            with Image.open(dst_ai) as a:
                self.assertEqual(a.size, (390, 507))
                found_y = None
                for y in range(a.size[1]):
                    if a.getpixel((195, y))[0] < 80:
                        found_y = y
                        break
                self.assertIsNotNone(found_y)
                self.assertLess(found_y, 260)


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
        os.environ["PORTRAIT_PROVIDER"] = "fallback"
        os.environ["PORTRAIT_FALLBACK"] = "1"
        os.environ["PORTRAIT_CACHE"] = "0"
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["RENDER_OUTPUT_DIR"] = tmp
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

    def test_resolve_skips_text_gen_without_selfie(self):
        os.environ["PORTRAIT_PROVIDER"] = "openai"
        os.environ["PORTRAIT_FALLBACK"] = "0"
        tmp = tempfile.mkdtemp()
        os.environ["RENDER_OUTPUT_DIR"] = tmp
        task = RenderTask.create(
            SAMPLE,
            options=RenderOptions(mockup="hand", generate_portrait=True, portrait_path=None),
        )
        path = resolve_portrait(task)
        self.assertIsNone(path)

    def test_src_upload_not_treated_as_enhanced(self):
        self.assertFalse(_already_enhanced(Path("user_1_src.png")))
        self.assertFalse(_already_enhanced(Path("user_1_src.jpg")))
        self.assertFalse(_already_enhanced(Path("edit_job_raw.png")))
        self.assertTrue(_already_enhanced(Path("user_1.jpg")))
        self.assertTrue(_already_enhanced(Path("gen_ab12.jpg")))
        self.assertTrue(_already_enhanced(Path("prep_ab12.jpg")))


class TestPortraitForceSkipsCache(unittest.TestCase):
    def test_force_regenerates(self):
        os.environ["PORTRAIT_PROVIDER"] = "fallback"
        os.environ["PORTRAIT_FALLBACK"] = "1"
        os.environ["PORTRAIT_CACHE"] = "1"
        fields = {
            "surname_ru": "КЭШ",
            "given_ru": "КЭШ КЭШЕВИЧ",
            "birth_date": "02.02.1992",
            "gender": "M",
        }
        tmp = tempfile.mkdtemp()
        os.environ["RENDER_OUTPUT_DIR"] = tmp
        first = generate_ai_portrait(fields, job_id="forcecache1")
        self.assertTrue(first.ok, first.message)
        with patch("portrait_service.generate_raw_portrait") as gen:
            from portrait_ai import GenerationResult

            gen.return_value = GenerationResult(ok=False, message="should not run")
            cached = generate_ai_portrait(fields, job_id="forcecache2")
            self.assertTrue(cached.ok)
            self.assertEqual(cached.source, "cache")
            gen.assert_not_called()
        with patch("portrait_service.generate_raw_portrait") as gen:
            from portrait_ai import GenerationResult

            raw = Path(tempfile.gettempdir()) / "otris_force_raw.jpg"
            Image.new("RGB", (100, 120), (10, 20, 30)).save(raw, format="JPEG")
            gen.return_value = GenerationResult(ok=True, raw_path=raw, provider="fallback")
            forced = generate_ai_portrait(fields, job_id="forcecache3", force=True)
            self.assertTrue(forced.ok, forced.message)
            gen.assert_called()


class TestPortraitAutoProvider(unittest.TestCase):
    def test_auto_prefers_openrouter_then_openai(self):
        cfg = PortraitSettings(
            openai_api_key="sk-test",
            openai_model="dall-e-3",
            openai_size="1024x1024",
            openrouter_api_key="or-test",
            openrouter_model="google/gemini-3.1-flash-lite-image",
            openrouter_base="https://openrouter.ai/api/v1",
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
        self.assertEqual(cfg.resolved_provider(), "openrouter")
        from portrait_ai import OpenAIGenerator, OpenRouterGenerator, build_generators

        gens = build_generators(cfg)
        self.assertIsInstance(gens[0], OpenRouterGenerator)
        self.assertIsInstance(gens[1], OpenAIGenerator)

    def test_auto_without_openrouter_uses_openai(self):
        cfg = PortraitSettings(
            openai_api_key="sk-test",
            openai_model="dall-e-3",
            openai_size="1024x1024",
            openrouter_api_key=None,
            openrouter_model="google/gemini-3.1-flash-lite-image",
            openrouter_base="https://openrouter.ai/api/v1",
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


class TestOpenAIImageApi(unittest.TestCase):
    def test_remap_retired_dalle(self):
        self.assertEqual(resolve_openai_image_model("dall-e-3"), "gpt-image-1")
        self.assertEqual(resolve_openai_image_model("dall-e-2"), "gpt-image-1")
        self.assertEqual(resolve_openai_image_model("gpt-image-1-mini"), "gpt-image-1-mini")
        self.assertTrue(is_gpt_image_model("gpt-image-1"))

    def test_gpt_image_body_has_no_response_format(self):
        cfg = PortraitSettings(
            openai_api_key="sk-test",
            openai_model="dall-e-3",
            openai_size="1024x1024",
            openrouter_api_key=None,
            openrouter_model="google/gemini-3.1-flash-lite-image",
            openrouter_base="https://openrouter.ai/api/v1",
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
        body = openai_image_body(cfg, "passport photo")
        self.assertEqual(body["model"], "gpt-image-1")
        self.assertNotIn("response_format", body)
        self.assertNotIn("style", body)
        self.assertEqual(body["output_format"], "jpeg")
        self.assertEqual(body["size"], "1024x1536")


class TestOpenAIGeneratorMock(unittest.TestCase):
    def test_openai_generate_requires_selfie(self):
        cfg = PortraitSettings(
            openai_api_key="sk-test",
            openai_model="dall-e-3",
            openai_size="1024x1024",
            openrouter_api_key=None,
            openrouter_model="google/gemini-3.1-flash-lite-image",
            openrouter_base="https://openrouter.ai/api/v1",
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
            gen = OpenAIGenerator(cfg)
            r = gen.generate({"birth_date": "01.01.1990", "given_ru": "A B"}, out)
            self.assertFalse(r.ok)
            self.assertIn("селфи", r.message.lower())

    def test_openrouter_edit_posts_images_api(self):
        import base64
        import json

        from portrait_ai import OpenRouterGenerator

        # Valid-looking JPEG payload (>= 100 bytes after decode)
        tiny_img = Image.new("RGB", (32, 32), (90, 80, 70))
        import io

        buf = io.BytesIO()
        tiny_img.save(buf, format="JPEG", quality=90)
        raw_jpeg = buf.getvalue()
        self.assertGreaterEqual(len(raw_jpeg), 100)
        tiny = base64.b64encode(raw_jpeg).decode()
        payload = json.dumps({"data": [{"b64_json": tiny, "media_type": "image/jpeg"}]}).encode()
        captured: dict = {}

        class FakeResp:
            def read(self):
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        def fake_urlopen(req, timeout=0):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResp()

        cfg = PortraitSettings(
            openai_api_key=None,
            openai_model="gpt-image-1",
            openai_size="1024x1024",
            openrouter_api_key="or-test",
            openrouter_model="google/gemini-3.1-flash-lite-image",
            openrouter_base="https://openrouter.ai/api/v1",
            api_url=None,
            api_key=None,
            width=390,
            height=507,
            jpeg_quality=90,
            provider="openrouter",
            fallback_enabled=False,
            cache_enabled=False,
            timeout_sec=30,
        )
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "face.jpg"
            Image.new("RGB", (80, 100), (90, 80, 70)).save(src, format="JPEG")
            out = Path(tmp) / "edited.jpg"
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                gen = OpenRouterGenerator(cfg)
                r = gen.edit(src, {"birth_date": "01.01.1990"}, out)
            self.assertTrue(r.ok, r.message)
            self.assertTrue(captured["url"].endswith("/images"))
            self.assertEqual(captured["body"]["model"], "google/gemini-3.1-flash-lite-image")
            self.assertIn("input_references", captured["body"])
            self.assertEqual(captured["body"]["aspect_ratio"], "4:3")
            ref = captured["body"]["input_references"][0]["image_url"]["url"]
            self.assertTrue(ref.startswith("data:image/jpeg;base64,"))
            self.assertTrue(out.is_file())
            self.assertGreaterEqual(out.stat().st_size, 100)

    def test_openai_edit_posts_multipart(self):
        import base64
        import json

        tiny = base64.b64encode(b"fake-edit").decode()
        payload = json.dumps({"data": [{"b64_json": tiny}]}).encode()
        captured: dict = {}

        class FakeResp:
            def read(self):
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        def fake_urlopen(req, timeout=0):
            captured["url"] = req.full_url
            captured["ctype"] = req.headers.get("Content-type") or req.headers.get("Content-Type")
            captured["body"] = req.data
            return FakeResp()

        cfg = PortraitSettings(
            openai_api_key="sk-test",
            openai_model="gpt-image-1",
            openai_size="1024x1024",
            openrouter_api_key=None,
            openrouter_model="google/gemini-3.1-flash-lite-image",
            openrouter_base="https://openrouter.ai/api/v1",
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
            src = Path(tmp) / "face.jpg"
            Image.new("RGB", (80, 100), (90, 80, 70)).save(src, format="JPEG")
            out = Path(tmp) / "edited.png"
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                gen = OpenAIGenerator(cfg)
                r = gen.edit(src, {"birth_date": "01.01.1990"}, out)
            self.assertTrue(r.ok, r.message)
            self.assertIn("/v1/images/edits", captured["url"])
            self.assertIn("multipart/form-data", captured["ctype"])
            self.assertIn(b"background", captured["body"])
            self.assertIn(b"photo.png", captured["body"])

    def test_edit_source_is_png_and_resized(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "huge.jpg"
            Image.new("RGB", (4000, 3000), (40, 50, 60)).save(src, format="JPEG")
            data, name, ctype = _image_bytes_for_edit(src)
            self.assertEqual(name, "photo.png")
            self.assertEqual(ctype, "image/png")
            with Image.open(io.BytesIO(data)) as im:
                self.assertEqual(im.format, "PNG")
                self.assertLessEqual(max(im.size), 1536)


if __name__ == "__main__":
    unittest.main()
