#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Провайдеры генерации ИИ-портрета."""
from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from portrait_config import PortraitSettings
from portrait_prompt import build_portrait_edit_prompt, build_portrait_prompt

log = logging.getLogger("portrait_ai")


@dataclass
class GenerationResult:
    ok: bool
    raw_path: Path | None = None
    provider: str = ""
    message: str = ""


class PortraitGenerator(ABC):
    @abstractmethod
    def generate(self, fields: dict[str, Any], out_path: Path) -> GenerationResult:
        pass

    def edit(self, source: Path, fields: dict[str, Any], out_path: Path) -> GenerationResult:
        """По умолчанию генерация с нуля. Провайдеры с img2img переопределяют."""
        return self.generate(fields, out_path)


_GPT_IMAGE_DEFAULT = "gpt-image-1"


def resolve_openai_image_model(model: str | None) -> str:
    """DALL·E 2/3 retired May 2026 — map to gpt-image-1."""
    raw = (model or "").strip()
    if not raw or raw.lower().startswith("dall-e"):
        return _GPT_IMAGE_DEFAULT
    return raw


def is_gpt_image_model(model: str) -> bool:
    return (model or "").lower().startswith("gpt-image")


def openai_image_body(settings: PortraitSettings, prompt: str, *, model: str | None = None) -> dict[str, Any]:
    chosen = resolve_openai_image_model(model or settings.openai_model)
    size = (settings.openai_size or "1024x1024").strip()
    if is_gpt_image_model(chosen):
        if size in {"1024x1024", "1792x1024", "1024x1792"} and settings.height > settings.width:
            size = "1024x1536"
        return {
            "model": chosen,
            "prompt": prompt,
            "n": 1,
            "size": size,
            "quality": "high",
            "output_format": "jpeg",
        }
    body: dict[str, Any] = {
        "model": chosen,
        "prompt": prompt,
        "n": 1,
        "size": size,
        "response_format": "b64_json",
    }
    if chosen.startswith("dall-e-3"):
        body["quality"] = "hd"
        body["style"] = "natural"
    return body


def _multipart_body(
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
) -> tuple[bytes, str]:
    import uuid

    boundary = "----OtrisPortrait" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")
        )
    for key, (filename, data, ctype) in files.items():
        header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n"
        ).encode("utf-8")
        chunks.append(header + data + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


_EDIT_MAX_SIDE = 1536


def _image_bytes_for_edit(source: Path) -> tuple[bytes, str, str]:
    """PNG для gpt-image-1 edits; длинная сторона ≤1536, чтобы не раздувать multipart."""
    import io

    from PIL import Image, ImageOps

    data = source.read_bytes()
    with Image.open(io.BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in {"RGB", "RGBA"}:
            im = im.convert("RGBA") if "A" in im.mode or im.mode == "P" else im.convert("RGB")
        w, h = im.size
        if max(w, h) > _EDIT_MAX_SIDE:
            im.thumbnail((_EDIT_MAX_SIDE, _EDIT_MAX_SIDE), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue(), "photo.png", "image/png"


def _write_openai_image(item: dict[str, Any], out_path: Path, timeout: int) -> None:
    b64 = item.get("b64_json")
    if b64:
        out_path.write_bytes(base64.b64decode(b64))
        return
    image_url = item.get("url")
    if image_url:
        req = urllib.request.Request(image_url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out_path.write_bytes(resp.read())
        return
    raise KeyError("OpenAI image payload has neither b64_json nor url")


class OpenAIGenerator(PortraitGenerator):
    def __init__(self, settings: PortraitSettings):
        self.settings = settings

    def generate(self, fields: dict[str, Any], out_path: Path) -> GenerationResult:
        key = self.settings.openai_api_key
        if not key:
            return GenerationResult(ok=False, provider="openai", message="OPENAI_API_KEY не задан")

        prompt = build_portrait_prompt(fields)
        requested = (self.settings.openai_model or "").strip()
        model = resolve_openai_image_model(requested)
        if model != requested:
            log.info("OpenAI model %s retired/unknown — using %s", requested or "(empty)", model)

        bodies = [
            openai_image_body(self.settings, prompt, model=model),
            {
                "model": model,
                "prompt": prompt,
                "n": 1,
                "size": "1024x1024",
            },
        ]
        url = "https://api.openai.com/v1/images/generations"
        last_err = "OpenAI: пустой ответ"
        for i, body in enumerate(bodies):
            log.info("OpenAI portrait POST %s model=%s attempt=%s", url, body.get("model"), i + 1)
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {key}",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.settings.timeout_sec) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                _write_openai_image(payload["data"][0], out_path, self.settings.timeout_sec)
                return GenerationResult(ok=True, raw_path=out_path, provider="openai")
            except urllib.error.HTTPError as e:
                err = e.read().decode("utf-8", errors="replace")[:500]
                log.error("OpenAI HTTP %s: %s", e.code, err)
                last_err = f"OpenAI: {e.code} {err[:160]}"
                if e.code != 400:
                    break
            except Exception as e:
                log.exception("OpenAI portrait failed")
                return GenerationResult(ok=False, provider="openai", message=str(e))
        return GenerationResult(ok=False, provider="openai", message=last_err)

    def edit(self, source: Path, fields: dict[str, Any], out_path: Path) -> GenerationResult:
        key = self.settings.openai_api_key
        if not key:
            return GenerationResult(ok=False, provider="openai", message="OPENAI_API_KEY не задан")
        if not source.is_file():
            return GenerationResult(ok=False, provider="openai", message="Исходное фото не найдено")

        prompt = build_portrait_edit_prompt(fields)
        requested = (self.settings.openai_model or "").strip()
        model = resolve_openai_image_model(requested)
        image_bytes, filename, ctype = _image_bytes_for_edit(source)
        size = "1024x1536" if self.settings.height > self.settings.width else "1024x1024"
        attempts: list[dict[str, str]] = [
            {
                "model": model,
                "prompt": prompt,
                "n": "1",
                "size": size,
                "quality": "medium",
                "background": "transparent",
                "output_format": "png",
            },
            {
                "model": model,
                "prompt": prompt,
                "n": "1",
                "size": size,
                "quality": "medium",
                "output_format": "jpeg",
            },
            {
                "model": model,
                "prompt": prompt,
                "n": "1",
                "size": "1024x1024",
            },
        ]
        url = "https://api.openai.com/v1/images/edits"
        last_err = "OpenAI edits: пустой ответ"
        for i, fields_body in enumerate(attempts):
            body, content_type = _multipart_body(
                fields_body,
                {"image": (filename, image_bytes, ctype)},
            )
            log.info("OpenAI portrait EDIT %s model=%s attempt=%s", url, fields_body.get("model"), i + 1)
            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": content_type,
                    "Authorization": f"Bearer {key}",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.settings.timeout_sec) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                _write_openai_image(payload["data"][0], out_path, self.settings.timeout_sec)
                return GenerationResult(ok=True, raw_path=out_path, provider="openai")
            except urllib.error.HTTPError as e:
                err = e.read().decode("utf-8", errors="replace")[:500]
                log.error("OpenAI edits HTTP %s: %s", e.code, err)
                last_err = f"OpenAI edits: {e.code} {err[:160]}"
                if e.code not in {400, 422}:
                    break
            except Exception as e:
                log.exception("OpenAI portrait edit failed")
                return GenerationResult(ok=False, provider="openai", message=str(e))
        return GenerationResult(ok=False, provider="openai", message=last_err)


class HttpApiGenerator(PortraitGenerator):
    """Внешний API: POST JSON task.fields → JPG bytes (task3 §6)."""

    def __init__(self, settings: PortraitSettings):
        self.settings = settings

    def generate(self, fields: dict[str, Any], out_path: Path) -> GenerationResult:
        url = self.settings.api_url
        if not url:
            return GenerationResult(ok=False, provider="http", message="PORTRAIT_API_URL не задан")

        headers = {"Content-Type": "application/json; charset=utf-8"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"

        req = urllib.request.Request(
            url,
            data=json.dumps(fields, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.settings.timeout_sec) as resp:
                ctype = resp.headers.get("Content-Type", "")
                data = resp.read()
            if len(data) < 100:
                return GenerationResult(ok=False, provider="http", message="API вернул пустой ответ")
            if "json" in ctype.lower():
                return GenerationResult(
                    ok=False,
                    provider="http",
                    message="API должен вернуть JPEG bytes, не JSON",
                )
            out_path.write_bytes(data)
            return GenerationResult(ok=True, raw_path=out_path, provider="http")
        except Exception as e:
            log.exception("Portrait HTTP API failed")
            return GenerationResult(ok=False, provider="http", message=str(e))

    def edit(self, source: Path, fields: dict[str, Any], out_path: Path) -> GenerationResult:
        return GenerationResult(
            ok=False,
            provider="http",
            message="HTTP API не поддерживает обработку загруженного фото",
        )


class FallbackGenerator(PortraitGenerator):
    """Офлайн-заглушка для dev/QA (PORTRAIT_FALLBACK=1). Не для продакшена."""

    def __init__(self, settings: PortraitSettings):
        self.settings = settings

    def generate(self, fields: dict[str, Any], out_path: Path) -> GenerationResult:
        from PIL import Image, ImageDraw

        w, h = self.settings.width * 2, self.settings.height * 2
        im = Image.new("RGB", (w, h), (210, 210, 215))
        draw = ImageDraw.Draw(im)
        # овал «лица»
        cx, cy = w // 2, int(h * 0.38)
        rx, ry = int(w * 0.22), int(h * 0.28)
        draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=(180, 165, 155))
        draw.rectangle((cx - rx, cy + ry // 2, cx + rx, h - 20), fill=(120, 130, 145))
        im = im.resize((self.settings.width, self.settings.height), Image.Resampling.LANCZOS)
        im.save(out_path, format="JPEG", quality=90)
        return GenerationResult(ok=True, raw_path=out_path, provider="fallback")

    def edit(self, source: Path, fields: dict[str, Any], out_path: Path) -> GenerationResult:
        """Сырой исходник без ID-кропа: финализация один раз в transform/resolve."""
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            from PIL import Image, ImageOps

            from portrait_preprocess import _flatten_cutout

            with Image.open(source) as im:
                im = ImageOps.exif_transpose(im)
                im = _flatten_cutout(im)
                im.save(out_path, format="JPEG", quality=90)
        except Exception as e:
            return GenerationResult(ok=False, provider="fallback", message=str(e))
        return GenerationResult(ok=True, raw_path=out_path, provider="fallback")


def build_generators(settings: PortraitSettings) -> list[PortraitGenerator]:
    provider = settings.provider if settings.provider else "auto"
    gens: list[PortraitGenerator] = []
    if provider == "auto":
        if settings.openai_api_key:
            gens.append(OpenAIGenerator(settings))
        if settings.api_url:
            gens.append(HttpApiGenerator(settings))
        if settings.fallback_enabled:
            gens.append(FallbackGenerator(settings))
        return gens
    resolved = settings.resolved_provider()
    if resolved == "openai":
        gens.append(OpenAIGenerator(settings))
    elif resolved == "http":
        gens.append(HttpApiGenerator(settings))
    elif resolved == "fallback":
        gens.append(FallbackGenerator(settings))
    return gens


def generate_raw_portrait(
    fields: dict[str, Any],
    raw_path: Path,
    *,
    settings: PortraitSettings | None = None,
    source_image: Path | None = None,
) -> GenerationResult:
    cfg = settings or PortraitSettings.from_env()
    generators = build_generators(cfg)
    if not generators:
        return GenerationResult(
            ok=False,
            message="Нет провайдера: задайте OPENAI_API_KEY или PORTRAIT_API_URL",
        )
    last = GenerationResult(ok=False, message="Неизвестная ошибка")
    for gen in generators:
        if source_image is not None:
            last = gen.edit(source_image, fields, raw_path)
        else:
            last = gen.generate(fields, raw_path)
        if last.ok:
            return last
        log.warning("Portrait provider %s failed: %s", last.provider, last.message)
    return last
