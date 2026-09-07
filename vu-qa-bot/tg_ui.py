#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UI Telegram-бота: custom emoji (Translucent Pack) + сетка кнопок как у референса.

В сообщениях — <tg-emoji>. В кнопках HTML не парсится, там unicode-фолбэк.
Mini App «Панель» работает только с https:// в WEB_BASE_URL.
"""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

# document_id из _tmp_emoji_id/1.png–3.png (Translucent Pack / blue squares)
EMOJI: dict[str, tuple[str, str]] = {
    "heart": ("5278611606756942667", "❤️"),
    "folder": ("5278227821364275264", "📁"),
    "bookmark": ("5276111746812112286", "🔖"),
    "lock": ("5278602437001767574", "🔒"),
    "shield": ("5276262671962892944", "🛡️"),
    "warning": ("5276240711795107620", "⚠️"),
    "stop": ("5278578973595427038", "🚫"),
    "monitor": ("5278647306525108244", "🖥️"),
    "info": ("5278753302023004775", "ℹ️"),
    "megaphone": ("5278528159837348960", "📣"),
    "check": ("5278411813468269386", "✔️"),
    "cart": ("5278613311858959074", "🛒"),
    "bags": ("5276384644739129761", "🛍️"),
    "clock": ("5276412364458059956", "🕒"),
    "briefcase": ("5276037216244624892", "💼"),
    "search": ("5276395476646653290", "🔍"),
    "broom": ("5276442772826515132", "🧹"),
    "user": ("5275979556308674886", "👤"),
    "users": ("5298668674532538341", "👥"),
    "terminal": ("5276381204470329471", ">_"),
    "wallet": ("5276398496008663230", "👛"),
    "at": ("5278589204207528856", "@"),
    "crown": ("5276229330131772747", "👑"),
    "cube": ("5278540791336165644", "🧊"),
    "link": ("5278305362703835500", "🔗"),
    "hammer": ("5276314275994954605", "🔨"),
    "gift": ("5276422526350681413", "🎁"),
    "game": ("5278304890257436355", "🎮"),
    "chart": ("5278778882848220741", "📈"),
    "house": ("527841385357734640", "🏠"),
    "robot": ("5276127848644503161", "🤖"),
    "inbox": ("5276220667182736079", "📥"),
    "star": ("5206476089127372379", "⭐"),
    "layers": ("5206626000665868017", "🥞"),
    "arrow": ("5206401524200145033", "↗️"),
    "arrow_down": ("5206510891247371052", "↘️"),
    "box": ("5206702193385700709", "📦"),
    "bell": ("5206222720416643915", "🔔"),
    "ok": ("5194996633682600894", "✅"),
    "ten": ("5194955350456953187", "10"),
}

# синие квадраты 0–9 из 3.png
DIGIT: dict[int, tuple[str, str]] = {
    0: ("5242380641332393116", "0"),
    1: ("5244961448525848230", "1"),
    2: ("5242293676834579345", "2"),
    3: ("5242652525647127686", "3"),
    4: ("5242287453426969423", "4"),
    5: ("5242407832770340528", "5"),
    6: ("5242669447818277073", "6"),
    7: ("5242663134216350272", "7"),
    8: ("5242497782270418294", "8"),
    9: ("5242286371095211663", "9"),
}


def ce(name: str) -> str:
    eid, fb = EMOJI[name]
    return f'<tg-emoji emoji-id="{eid}">{fb}</tg-emoji>'


def ce_digit(n: int) -> str:
    eid, fb = DIGIT[n]
    return f'<tg-emoji emoji-id="{eid}">{fb}</tg-emoji>'


def ico(name: str) -> str:
    return EMOJI[name][1]


def is_https_url(url: str) -> bool:
    return str(url or "").lower().startswith("https://")


def panel_url(web_base: str) -> str:
    return str(web_base or "").rstrip("/")


def panel_webapp(web_base: str) -> WebAppInfo | None:
    url = panel_url(web_base)
    if is_https_url(url):
        return WebAppInfo(url=url)
    return None


def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def panel_btn(web_base: str) -> InlineKeyboardButton:
    app = panel_webapp(web_base)
    if app:
        return InlineKeyboardButton(text="Открыть панель", web_app=app)
    url = panel_url(web_base) or "http://localhost:8080"
    return InlineKeyboardButton(text="Открыть панель", url=url)


def support_btn(url: str) -> InlineKeyboardButton:
    href = url or "https://t.me/arxixx"
    return InlineKeyboardButton(text=f"{ico('megaphone')} Поддержка", url=href)


def back_menu_btn() -> InlineKeyboardButton:
    return btn(f"{ico('house')} В меню", "m:home")


def main_menu_kb(web_base: str, support_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(f"{ico('star')} Сгенерировать", "m:gen"),
                btn(f"{ico('layers')} Отрисовать", "m:ren"),
            ],
            [btn(f"{ico('briefcase')} Мои задачи", "m:jobs")],
            [
                btn(f"{ico('user')} Портрет", "m:port"),
                btn(f"{ico('bookmark')} Профиль", "m:prof"),
            ],
            [btn(f"{ico('monitor')} Статус", "m:stat")],
            [panel_btn(web_base)],
            [support_btn(support_url)],
        ]
    )


def back_only_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[back_menu_btn()]])


def render_options_kb(bg: int, portrait_on: bool) -> InlineKeyboardMarkup:
    row1 = [
        btn(("✓ " if bg == i else "") + str(i), f"rb:{i}") for i in range(1, 6)
    ]
    row2 = [
        btn(("✓ " if bg == i else "") + str(i), f"rb:{i}") for i in range(6, 11)
    ]
    port = ("✓ " if portrait_on else "") + f"{ico('user')} Портрет (ИИ)"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            row1,
            row2,
            [
                btn(port, "rp:ai"),
                btn(f"{ico('check')} Отрисовать", "rq:go"),
            ],
            [back_menu_btn()],
        ]
    )


def portrait_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn(f"{ico('star')} Сгенерировать ИИ", "rp:ai")],
            [back_menu_btn()],
        ]
    )


def profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn(f"{ico('broom')} Сбросить профиль", "m:forget")],
            [back_menu_btn()],
        ]
    )


def jobs_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[back_menu_btn()]])


def status_kb(*, admin: bool) -> InlineKeyboardMarkup:
    rows = []
    if admin:
        rows.append([btn(f"{ico('broom')} Восстановить зависшие", "adm:recover")])
    rows.append([back_menu_btn()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def region_kb(page: int, codes: list[str], names: dict[str, str], *, per_page: int = 24) -> InlineKeyboardMarkup:
    pages = max(1, (len(codes) + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))
    chunk = codes[page * per_page : (page + 1) * per_page]
    rows = [
        [
            btn(f"{c} {names[c][:18]}", f"rg:{c}")
            for c in chunk[i : i + 2]
        ]
        for i in range(0, len(chunk), 2)
    ]
    nav = []
    if page > 0:
        nav.append(btn("◀", f"rgp:{page - 1}"))
    nav.append(btn(f"{page + 1}/{pages}", "rgp:noop"))
    if page < pages - 1:
        nav.append(btn("▶", f"rgp:{page + 1}"))
    rows.append(nav)
    rows.append([btn(f"{ico('game')} Любое подразделение", "rg:any")])
    rows.append([back_menu_btn()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def birthplace_kb(page: int, places: list[str], *, per_page: int = 8) -> InlineKeyboardMarkup:
    pages = max(1, (len(places) + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))
    chunk = places[page * per_page : (page + 1) * per_page]
    rows = [
        [btn(p[:28], f"bp:{i + page * per_page}")]
        for i, p in enumerate(chunk)
    ]
    nav = []
    if page > 0:
        nav.append(btn("◀", f"bpp:{page - 1}"))
    nav.append(btn(f"{page + 1}/{pages}", "bpp:noop"))
    if page < pages - 1:
        nav.append(btn("▶", f"bpp:{page + 1}"))
    rows.append(nav)
    rows.append([btn(f"{ico('game')} Любое место", "bp:any")])
    rows.append([back_menu_btn()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_menu_text(queue: dict, worker_alive: bool) -> str:
    pending = queue.get("pending", 0)
    processing = queue.get("processing", 0)
    done = queue.get("done", 0)
    worker = "online" if worker_alive else "offline"
    return (
        f"{ce('chart')} <b>Очередь отрисовки</b>\n"
        f"В очереди: {pending} | В работе: {processing} | Готово: {done}\n"
        f"Worker: {worker}\n\n"
        f"{ce('folder')} <b>Модуль VU Studio</b>\n"
        f"Выберите действие:"
    )


def render_prompt_text(summary: str, bg: int) -> str:
    nums = " ".join(ce_digit(i) if i < 10 else ce("ten") for i in range(1, 11))
    return (
        f"{ce('layers')} <b>Отрисовка мокапа</b>\n"
        f"Сейчас: <b>{summary}</b>\n"
        f"Фон: {ce_digit(bg) if bg < 10 else ce('ten')}\n\n"
        f"{nums}\n"
        f"Выберите фон 1–10 и запустите отрисовку."
    )
