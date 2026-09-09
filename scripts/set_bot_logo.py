#!/usr/bin/env python3
"""Set web/static/bot-logo.jpg as the Telegram bot profile photo."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vu-qa-bot"))

from dotenv import load_dotenv
from aiogram import Bot
from aiogram.types import FSInputFile, InputProfilePhotoStatic

LOGO = ROOT / "web" / "static" / "bot-logo.jpg"


async def main() -> None:
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT / "vu-qa-bot" / ".env", override=False)
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        print("BOT_TOKEN не задан.", file=sys.stderr)
        raise SystemExit(2)
    if not LOGO.exists():
        print(f"Нет файла {LOGO}. Сначала: python scripts/make_bot_logo.py", file=sys.stderr)
        raise SystemExit(1)
    bot = Bot(token)
    try:
        ok = await bot.set_my_profile_photo(
            photo=InputProfilePhotoStatic(photo=FSInputFile(LOGO))
        )
        me = await bot.get_me()
        if ok:
            print(f"Логотип VU Studio поставлен для @{me.username}")
        else:
            print("Telegram вернул False", file=sys.stderr)
            raise SystemExit(1)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
