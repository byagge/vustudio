#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Реестр мокапов: blank / hand / original."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from render_models import MockupKind

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class MockupSpec:
    kind: str
    title: str
    psb_name: str
    template: str
    mockup_variant: str | None = None
    supports_background: bool = False
    supports_portrait: bool = False

    def resolve_path(self) -> Path:
        env_key = f"MOCKUP_{self.kind.upper()}_PATH"
        override = os.getenv(env_key, "").strip()
        if override:
            return Path(override)
        if self.kind in {"hand", "original"}:
            shared = os.getenv("MOCKUP_PATH", "").strip()
            if shared:
                return Path(shared)
        return ROOT / self.psb_name


MOCKUPS: dict[str, MockupSpec] = {
    MockupKind.BLANK.value: MockupSpec(
        kind=MockupKind.BLANK.value,
        title="Бланк ВУ",
        psb_name="Прямоугольник 2 копия.psb",
        template="mockup_blank",
        supports_portrait=False,
        supports_background=False,
    ),
    MockupKind.HAND.value: MockupSpec(
        kind=MockupKind.HAND.value,
        title="Рука + фон",
        psb_name="Мокап (рука+фоны).psb",
        template="mockup_hand",
        mockup_variant="hand",
        supports_background=True,
        supports_portrait=True,
    ),
    MockupKind.ORIGINAL.value: MockupSpec(
        kind=MockupKind.ORIGINAL.value,
        title="Оригинал (без руки)",
        psb_name="Мокап (рука+фоны).psb",
        template="mockup_hand",
        mockup_variant="original",
        supports_background=True,
        supports_portrait=True,
    ),
}


def get_mockup(kind: str) -> MockupSpec:
    return MOCKUPS.get(kind, MOCKUPS[MockupKind.HAND.value])
