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
from portrait_prompt import build_portrait_prompt

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


class OpenAIGenerator(PortraitGenerator):
    def __init__(self, settings: PortraitSettings):
        self.settings = settings

    def generate(self, fields: dict[str, Any], out_path: Path) -> GenerationResult:
        key = self.settings.openai_api_key
        if not key:
            return GenerationResult(ok=False, provider="openai", message="OPENAI_API_KEY не задан")

        prompt = build_portrait_prompt(fields)
        model = self.settings.openai_model
        body: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "size": self.settings.openai_size,
            "response_format": "b64_json",
        }
        if model.startswith("dall-e-3"):
            body["quality"] = "hd"
            body["style"] = "natural"

        url = "https://api.openai.com/v1/images/generations"
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
            data = payload["data"][0]["b64_json"]
            out_path.write_bytes(base64.b64decode(data))
            return GenerationResult(ok=True, raw_path=out_path, provider="openai")
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")[:500]
            log.error("OpenAI HTTP %s: %s", e.code, err)
            return GenerationResult(ok=False, provider="openai", message=f"OpenAI: {e.code} {err[:120]}")
        except Exception as e:
            log.exception("OpenAI portrait failed")
            return GenerationResult(ok=False, provider="openai", message=str(e))


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


def build_generators(settings: PortraitSettings) -> list[PortraitGenerator]:
    provider = settings.resolved_provider()
    gens: list[PortraitGenerator] = []
    if provider == "openai":
        gens.append(OpenAIGenerator(settings))
    elif provider == "http":
        gens.append(HttpApiGenerator(settings))
    elif provider == "fallback":
        gens.append(FallbackGenerator(settings))
    elif provider == "none":
        return []
    else:
        if settings.openai_api_key:
            gens.append(OpenAIGenerator(settings))
        if settings.api_url:
            gens.append(HttpApiGenerator(settings))
        if settings.fallback_enabled:
            gens.append(FallbackGenerator(settings))
    return gens


def generate_raw_portrait(
    fields: dict[str, Any],
    raw_path: Path,
    *,
    settings: PortraitSettings | None = None,
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
        last = gen.generate(fields, raw_path)
        if last.ok:
            return last
        log.warning("Portrait provider %s failed: %s", last.provider, last.message)
    return last
