#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Настройки модуля ИИ-портрета."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PortraitSettings:
    """Параметры из .env — см. .env.example."""

    openai_api_key: str | None
    openai_model: str
    openai_size: str
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
        api_url = os.getenv("PORTRAIT_API_URL", "").strip() or None
        provider = os.getenv("PORTRAIT_PROVIDER", "auto").strip().lower()
        return cls(
            openai_api_key=key,
            openai_model=os.getenv("PORTRAIT_OPENAI_MODEL", "dall-e-3").strip(),
            openai_size=os.getenv("PORTRAIT_OPENAI_SIZE", "1024x1024").strip(),
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
            timeout_sec=int(os.getenv("PORTRAIT_TIMEOUT", "120")),
        )

    def resolved_provider(self) -> str:
        if self.provider != "auto":
            return self.provider
        if self.api_url:
            return "http"
        if self.openai_api_key:
            return "openai"
        if self.fallback_enabled:
            return "fallback"
        return "none"
