#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Модели задач рендера (JSON между парсером и worker)."""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from text_parser import VuTextBlock, parse_client_block


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class MockupKind(str, Enum):
    BLANK = "blank"
    HAND = "hand"
    ORIGINAL = "original"


@dataclass
class RenderOptions:
    mockup: str = MockupKind.HAND.value
    background: int = 1
    portrait_path: str | None = None
    generate_portrait: bool = False

    def normalized(self) -> RenderOptions:
        mockup = self.mockup if self.mockup in {m.value for m in MockupKind} else MockupKind.HAND.value
        bg = max(1, min(10, int(self.background or 1)))
        return RenderOptions(
            mockup=mockup,
            background=bg,
            portrait_path=self.portrait_path,
            generate_portrait=self.generate_portrait,
        )


@dataclass
class RenderTask:
    job_id: str
    text_block: str
    fields: dict[str, Any]
    options: RenderOptions
    status: str = JobStatus.PENDING.value
    created_at: str = ""
    updated_at: str = ""
    psd_path: str | None = None
    jpg_path: str | None = None
    error: str | None = None
    chat_id: int | None = None
    user_id: int | None = None

    @classmethod
    def create(
        cls,
        text_block: str,
        *,
        options: RenderOptions | None = None,
        chat_id: int | None = None,
        user_id: int | None = None,
    ) -> RenderTask:
        block = parse_client_block(text_block)
        now = _now()
        return cls(
            job_id=uuid.uuid4().hex[:12],
            text_block=text_block,
            fields=block_to_dict(block),
            options=(options or RenderOptions()).normalized(),
            created_at=now,
            updated_at=now,
            chat_id=chat_id,
            user_id=user_id,
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["options"] = asdict(self.options.normalized())
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RenderTask:
        opts = data.get("options") or {}
        return cls(
            job_id=data["job_id"],
            text_block=data["text_block"],
            fields=data.get("fields") or {},
            options=RenderOptions(
                mockup=opts.get("mockup", MockupKind.HAND.value),
                background=int(opts.get("background", 1)),
                portrait_path=opts.get("portrait_path"),
                generate_portrait=bool(opts.get("generate_portrait")),
            ).normalized(),
            status=data.get("status", JobStatus.PENDING.value),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            psd_path=data.get("psd_path"),
            jpg_path=data.get("jpg_path"),
            error=data.get("error"),
            chat_id=data.get("chat_id"),
            user_id=data.get("user_id"),
        )


def block_to_dict(block: VuTextBlock) -> dict[str, Any]:
    from portrait_prompt import estimate_gender

    return {
        "surname_ru": block.surname_ru,
        "surname_lat": block.surname_lat,
        "given_ru": block.given_ru,
        "given_lat": block.given_lat,
        "birth_date": block.birth_date,
        "birth_place_ru": block.birth_place_ru,
        "birth_place_lat": block.birth_place_lat,
        "issue_date": block.issue_date,
        "expiry_date": block.expiry_date,
        "authority": block.authority,
        "series": block.series,
        "number": block.number,
        "residence_ru": block.residence_ru,
        "residence_lat": block.residence_lat,
        "gender": estimate_gender(
            {
                "given_ru": block.given_ru,
                "surname_ru": block.surname_ru,
            }
        ),
        "categories": list(block.categories),
        "special_marks": block.special_marks,
        "back_number": block.back_number,
        "back_table": {
            cat: {
                "open": row.open_date,
                "expiry": row.expiry_date,
                "restriction": row.restriction,
            }
            for cat, row in block.back_table.items()
        },
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
