#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Конфигурация из переменных окружения."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent

import load_env  # noqa: F401, E402


@dataclass(frozen=True)
class Settings:
    bot_token: str
    allowed_users: frozenset[int]
    profiles_path: Path
    api_key: str | None
    log_level: str
    mockup_path: Path
    render_output_dir: Path
    render_queue_dir: Path
    photoshop_exe: Path | None
    admin_users: frozenset[int]
    web_base_url: str

    @classmethod
    def load(cls) -> Settings:
        token = os.getenv("BOT_TOKEN", "").strip()
        raw_users = os.getenv("ALLOWED_USERS", "").strip()
        api_key = os.getenv("API_KEY", "").strip() or None
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        profiles = Path(os.getenv("PROFILES_PATH", str(ROOT / "profiles.json")))
        project_root = ROOT.parent
        mockup = Path(
            os.getenv(
                "MOCKUP_PATH",
                str(project_root / "Мокап (рука+фоны).psb"),
            )
        )
        render_out = Path(os.getenv("RENDER_OUTPUT_DIR", str(project_root / "output")))
        queue_dir = Path(os.getenv("RENDER_QUEUE_DIR", str(project_root / "queue")))
        ps_exe = os.getenv("PHOTOSHOP_EXE", "").strip()
        photoshop_exe = Path(ps_exe) if ps_exe else None
        render_out.mkdir(parents=True, exist_ok=True)
        queue_dir.mkdir(parents=True, exist_ok=True)

        allowed: set[int] = set()
        if raw_users:
            allowed = {
                int(p)
                for p in (t.strip() for t in raw_users.split(","))
                if p.lstrip("-").isdigit()
            }

        raw_admin = os.getenv("ADMIN_USERS", "").strip()
        admin: set[int] = set()
        if raw_admin:
            admin = {
                int(p)
                for p in (t.strip() for t in raw_admin.split(","))
                if p.lstrip("-").isdigit()
            }
        else:
            admin = set(allowed)

        web_base = os.getenv("WEB_BASE_URL", "http://localhost:8080").strip().rstrip("/")

        return cls(
            bot_token=token,
            allowed_users=frozenset(allowed),
            admin_users=frozenset(admin),
            profiles_path=profiles,
            api_key=api_key,
            log_level=log_level,
            mockup_path=mockup,
            render_output_dir=render_out,
            render_queue_dir=queue_dir,
            photoshop_exe=photoshop_exe,
            web_base_url=web_base,
        )

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_users

    def require_bot(self) -> None:
        if not self.bot_token:
            print("BOT_TOKEN не задан.", file=sys.stderr)
            raise SystemExit(2)
        if not self.allowed_users:
            print(
                "ALLOWED_USERS не задана — бот не стартует.\n"
                "Укажите user_id через запятую, например:\n"
                "  ALLOWED_USERS=681094413",
                file=sys.stderr,
            )
            raise SystemExit(2)
