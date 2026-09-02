#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сервис ИИ-портрета (task3) — OpenAI / HTTP / fallback через portrait_ai.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

VU = Path(__file__).resolve().parent.parent / "vu-qa-bot"
if str(VU) not in sys.path:
    sys.path.insert(0, str(VU))

from portrait_config import PortraitSettings  # noqa: E402
from portrait_preprocess import prepare_portrait_file  # noqa: E402

app = FastAPI(title="VU Portrait API", version="2.0.0")


class PortraitFields(BaseModel):
    surname_ru: str | None = None
    given_ru: str | None = None
    birth_date: str | None = None
    gender: str | None = None
    birth_place_ru: str | None = None

    model_config = {"extra": "allow"}


def _generate_jpeg(fields: dict) -> tuple[bytes, str]:
    cfg = PortraitSettings.from_env()
    with tempfile.TemporaryDirectory() as td:
        raw = Path(td) / "raw.jpg"
        out = Path(td) / "out.jpg"
        from portrait_ai import FallbackGenerator, OpenAIGenerator

        gens = []
        if cfg.openai_api_key:
            gens.append(OpenAIGenerator(cfg))
        if cfg.fallback_enabled or not gens:
            gens.append(FallbackGenerator(cfg))
        gen = None
        last_msg = "Нет провайдера"
        for g in gens:
            gen = g.generate(fields, raw)
            if gen.ok:
                break
            last_msg = gen.message
        if not gen or not gen.ok:
            raise HTTPException(503, last_msg)
        prepare_portrait_file(gen.raw_path, out, settings=cfg)
        return out.read_bytes(), gen.provider


@app.get("/health")
async def health():
    cfg = PortraitSettings.from_env()
    return {
        "status": "ok",
        "service": "portrait-api",
        "provider": cfg.resolved_provider(),
        "openai_configured": bool(cfg.openai_api_key),
        "http_configured": bool(cfg.api_url),
        "fallback": cfg.fallback_enabled,
    }


@app.post("/generate")
async def generate(fields: PortraitFields):
    data = fields.model_dump(exclude_none=False)
    jpg, provider = _generate_jpeg(data)
    return Response(
        content=jpg,
        media_type="image/jpeg",
        headers={"X-Portrait-Provider": provider},
    )


@app.post("/")
async def generate_root(fields: PortraitFields):
    return await generate(fields)
