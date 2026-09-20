#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Настройки модуля ИИ-портрета."""
from __future__ import annotations

import os
from dataclasses import dataclass

import load_env  # noqa: F401


# Nano Banana 2 Lite (OpenRouter) — selfie → document portrait.
_DEFAULT_OPENROUTER_MODEL = "google/gemini-3.1-flash-lite-image"
_DEFAULT_OPENROUTER_BASE = "https://openrouter.ai/api/v1"


@dataclass(frozen=True)
class PortraitSettings:
    """Параметры из .env — см. .env.example."""

    openai_api_key: str | None
    openai_model: str
    openai_size: str
    openrouter_api_key: str | None
    openrouter_model: str
    openrouter_base: str
    api_url: str | None
    api_key: str | None
    width: int
    height: int
    jpeg_quality: int
    provider: str
    fallback_enabled: bool
    cache_enabled: bool
    timeout_sec: int

    @classmethod
    def from_env(cls) -> PortraitSettings:
        key = (
            os.getenv("PORTRAIT_OPENAI_API_KEY", "").strip()
            or os.getenv("OPENAI_API_KEY", "").strip()
            or None
        )
        or_key = (
            os.getenv("PORTRAIT_OPENROUTER_API_KEY", "").strip()
            or os.getenv("OPENROUTER_API_KEY", "").strip()
            or None
        )
        api_url = os.getenv("PORTRAIT_API_URL", "").strip() or None
        # auto: OpenRouter first (selfie edit), then OpenAI, then HTTP/fallback
        provider = os.getenv("PORTRAIT_PROVIDER", "auto").strip().lower()
        return cls(
            openai_api_key=key,
            openai_model=os.getenv("PORTRAIT_OPENAI_MODEL", "gpt-image-1").strip(),
            openai_size=os.getenv("PORTRAIT_OPENAI_SIZE", "1024x1024").strip(),
            openrouter_api_key=or_key,
            openrouter_model=os.getenv(
                "PORTRAIT_OPENROUTER_MODEL", _DEFAULT_OPENROUTER_MODEL
            ).strip()
            or _DEFAULT_OPENROUTER_MODEL,
            openrouter_base=(
                os.getenv("PORTRAIT_OPENROUTER_BASE", _DEFAULT_OPENROUTER_BASE).strip()
                or _DEFAULT_OPENROUTER_BASE
            ).rstrip("/"),
            api_url=api_url,
            api_key=os.getenv("PORTRAIT_API_KEY", "").strip() or None,
            width=int(os.getenv("PORTRAIT_WIDTH", "390")),
            height=int(os.getenv("PORTRAIT_HEIGHT", "507")),
            jpeg_quality=int(os.getenv("PORTRAIT_JPEG_QUALITY", "92")),
            provider=provider,
            fallback_enabled=os.getenv("PORTRAIT_FALLBACK", "0").strip().lower()
            in {"1", "true", "yes"},
            cache_enabled=os.getenv("PORTRAIT_CACHE", "1").strip().lower()
            not in {"0", "false", "no"},
            timeout_sec=int(os.getenv("PORTRAIT_TIMEOUT", "180")),
        )

    def resolved_provider(self) -> str:
        if self.provider != "auto":
            return self.provider
        if self.openrouter_api_key:
            return "openrouter"
        if self.openai_api_key:
            return "openai"
        if self.api_url:
            return "http"
        if self.fallback_enabled:
            return "fallback"
        return "none"
