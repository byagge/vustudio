#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Кэш открытого шаблона Photoshop между задачами (task2 §8)."""
from __future__ import annotations

import os
from pathlib import Path


class TemplateCache:
    """Worker держит последний template path — JSX дублирует открытый документ."""

    def __init__(self) -> None:
        self._last_template: str | None = None

    @staticmethod
    def enabled() -> bool:
        return os.getenv("PHOTOSHOP_CACHE_TEMPLATE", "1").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    def apply(self, job: dict) -> dict:
        template = str(job.get("template", ""))
        reuse = self.enabled() and self._last_template == template and bool(template)
        job["keep_template_open"] = self.enabled()
        job["reuse_open_template"] = reuse
        if template:
            self._last_template = template
        return job

    def reset(self) -> None:
        self._last_template = None


# один инстанс на процесс worker
WORKER_TEMPLATE_CACHE = TemplateCache()
