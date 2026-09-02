#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Точка расширения для внешнего рендера (Photoshop и т.п.).

Этот модуль НЕ выполняет отрисовку документов.
Он описывает контракт, к которому можно подключить легальный
внешний пайплайн (ручной или лицензированный).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from formatter import format_client_block
from vu_testdata import LicenceRecord


@dataclass
class RenderJob:
    record: LicenceRecord | None
    text_block: str
    template_path: Path | None = None
    mockup: str = "hand"
    background: int = 1
    portrait_path: str | None = None
    generate_portrait: bool = False


@dataclass
class RenderResult:
    job: RenderJob
    output_paths: list[Path]
    status: str
    message: str


class DocumentRenderer(Protocol):
    def render(self, job: RenderJob) -> RenderResult: ...


class StubRenderer:
    """Заглушка: возвращает только текстовый блок без файлов изображений."""

    def render(self, job: RenderJob) -> RenderResult:
        return RenderResult(
            job=job,
            output_paths=[],
            status="skipped",
            message=(
                "Рендер изображений не подключён. "
                "Используйте text_block или подключите DocumentRenderer."
            ),
        )


def build_job(rec: LicenceRecord, template: Path | None = None) -> RenderJob:
    return RenderJob(
        record=rec,
        text_block=format_client_block(rec),
        template_path=template,
    )
