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


class OpenRouterGenerator(PortraitGenerator):
    """Selfie → document portrait via OpenRouter Images API (Nano Banana 2 Lite)."""

    _MIN_BYTES = 100

    def __init__(self, settings: PortraitSettings):
        self.settings = settings

    def generate(self, fields: dict[str, Any], out_path: Path) -> GenerationResult:
        return GenerationResult(
            ok=False,
            provider="openrouter",
            message="Нужно селфи: OpenRouter делает портрет только из загруженного фото",
        )

    def edit(self, source: Path, fields: dict[str, Any], out_path: Path) -> GenerationResult:
        key = self.settings.openrouter_api_key
        if not key:
            return GenerationResult(
                ok=False,
                provider="openrouter",
                message="OPENROUTER_API_KEY не задан",
            )
        if not source.is_file():
            return GenerationResult(ok=False, provider="openrouter", message="Исходное фото не найдено")

        prompt = build_portrait_edit_prompt(fields)
        try:
            data_url = _openrouter_reference_data_url(source)
        except Exception as e:
            return GenerationResult(ok=False, provider="openrouter", message=str(e))

        model = self.settings.openrouter_model or "google/gemini-3.1-flash-lite-image"
        url = f"{self.settings.openrouter_base.rstrip('/')}/images"
        body: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "aspect_ratio": "4:3",
            "resolution": "1K",
            "input_references": [
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }

        log.info(
            "OpenRouter portrait EDIT %s model=%s timeout=%ss",
            url,
            model,
            self.settings.timeout_sec,
        )
        try:
            payload = _openrouter_post(url, key, body, self.settings.timeout_sec)
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")[:500]
            log.error("OpenRouter HTTP %s: %s", e.code, err)
            # Retry once without optional fields some endpoints reject.
            if e.code == 400:
                for drop in ("aspect_ratio", "resolution"):
                    body.pop(drop, None)
                try:
                    payload = _openrouter_post(url, key, body, self.settings.timeout_sec)
                except urllib.error.HTTPError as e2:
                    err2 = e2.read().decode("utf-8", errors="replace")[:500]
                    return GenerationResult(
                        ok=False,
                        provider="openrouter",
                        message=f"OpenRouter: {e2.code} {err2[:160]}",
                    )
                except Exception as e2:
                    log.exception("OpenRouter portrait edit failed")
                    return GenerationResult(ok=False, provider="openrouter", message=str(e2))
            else:
                return GenerationResult(
                    ok=False,
                    provider="openrouter",
                    message=f"OpenRouter: {e.code} {err[:160]}",
                )
        except Exception as e:
            log.exception("OpenRouter portrait edit failed")
            return GenerationResult(ok=False, provider="openrouter", message=str(e))

        try:
            img = _decode_openrouter_image(payload)
            if not img:
                return GenerationResult(
                    ok=False,
                    provider="openrouter",
                    message="OpenRouter: пустой ответ без изображения",
                )
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(img)
            if out_path.stat().st_size < self._MIN_BYTES:
                return GenerationResult(
                    ok=False,
                    provider="openrouter",
                    message="OpenRouter: пустой файл изображения",
                )
            log.info(
                "OpenRouter portrait OK bytes=%s -> %s",
                out_path.stat().st_size,
                out_path.name,
            )
            return GenerationResult(ok=True, raw_path=out_path, provider="openrouter")
        except Exception as e:
            log.exception("OpenRouter portrait decode failed")
            return GenerationResult(ok=False, provider="openrouter", message=str(e))


def _openrouter_post(url: str, key: str, body: dict[str, Any], timeout: int) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "HTTP-Referer": "https://photoshop.arix.vu",
            "X-Title": "Otris VU Portrait",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _openrouter_reference_data_url(source: Path) -> str:
    """JPEG data-URL for OpenRouter input_references (smaller than PNG)."""
    import io

    from PIL import Image, ImageOps

    with Image.open(source) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in {"RGB", "L"}:
            im = im.convert("RGB")
        w, h = im.size
        if max(w, h) > _EDIT_MAX_SIDE:
            im.thumbnail((_EDIT_MAX_SIDE, _EDIT_MAX_SIDE), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=92)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def _b64_to_bytes(raw: str) -> bytes | None:
    if not raw:
        return None
    s = raw.strip()
    if "base64," in s:
        s = s.split("base64,", 1)[1]
    try:
        return base64.b64decode(s)
    except Exception:
        return None


def _decode_openrouter_image(payload: dict[str, Any]) -> bytes | None:
    """Decode Image API data[] or chat-style OpenRouter payloads."""
    data = payload.get("data") or []
    for item in data:
        if not isinstance(item, dict):
            continue
        img = _b64_to_bytes(item.get("b64_json") or "")
        if img:
            return img
        url = item.get("url")
        if isinstance(url, str) and url.startswith("data:") and "base64," in url:
            img = _b64_to_bytes(url)
            if img:
                return img
        if isinstance(url, str) and url.startswith("http"):
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=60) as resp:
                got = resp.read()
            if got:
                return got

    img = _extract_openrouter_image(payload)
    return img


def _extract_openrouter_image(payload: dict[str, Any]) -> bytes | None:
    """Fallback: pull first data-URL / b64 image from chat-like OpenRouter payloads."""
    choices = payload.get("choices") or []
    for ch in choices:
        msg = ch.get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            img = _b64_to_bytes(content) if ("base64," in content or len(content) > 200) else None
            if img:
                return img
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                url = (part.get("image_url") or {}).get("url") or part.get("url") or ""
                if isinstance(url, str):
                    img = _b64_to_bytes(url) if ("base64," in url or url.startswith("data:")) else None
                    if img:
                        return img
                b64 = part.get("b64_json")
                if b64:
                    img = _b64_to_bytes(b64)
                    if img:
                        return img
    return None


class OpenAIGenerator(PortraitGenerator):
    def __init__(self, settings: PortraitSettings):
        self.settings = settings

    def generate(self, fields: dict[str, Any], out_path: Path) -> GenerationResult:
        # Product path: selfie → edit (OpenRouter / OpenAI edits), not text-to-image.
        return GenerationResult(
            ok=False,
            provider="openai",
            message="Нужно селфи: портрет только из загруженного фото",
        )

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
        # Selfie edit: OpenRouter (NB 2 Lite) first, then OpenAI edits, then fallback crop.
        if settings.openrouter_api_key:
            gens.append(OpenRouterGenerator(settings))
        if settings.openai_api_key:
            gens.append(OpenAIGenerator(settings))
        if settings.api_url:
            gens.append(HttpApiGenerator(settings))
        if settings.fallback_enabled:
            gens.append(FallbackGenerator(settings))
        return gens
    resolved = settings.resolved_provider()
    if resolved == "openrouter":
        gens.append(OpenRouterGenerator(settings))
    elif resolved == "openai":
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
            message="Нет провайдера: задайте OPENROUTER_API_KEY или OPENAI_API_KEY",
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
