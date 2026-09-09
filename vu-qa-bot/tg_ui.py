#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UI Telegram-бота: custom emoji (Translucent Pack) + сетка кнопок как у референса.

В тексте сообщений — <tg-emoji> (если Telegram отвергнет — бот шлёт unicode).
В inline-кнопках — icon_custom_emoji_id (Premium у владельца бота).
Mini App «Панель» — только https://.
"""
from __future__ import annotations

import html

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
    "terminal": ("5276381204470329471", "💻"),
    "wallet": ("5276398496008663230", "👛"),
    "at": ("5278589204207528856", "💠"),
    "crown": ("5276229330131772747", "👑"),
    "cube": ("5278540791336165644", "🧊"),
    "link": ("5278305362703835500", "🔗"),
    "hammer": ("5276314275994954605", "🔨"),
    "gift": ("5276422526350681413", "🎁"),
    "game": ("5278304890257436355", "🎮"),
    "chart": ("5278778882848220741", "📈"),
    "house": ("5278413853577346406", "🏠"),
    "robot": ("5276127848644503161", "🤖"),
    "inbox": ("5276220667182736079", "📥"),
    "star": ("5206476089127372379", "⭐"),
    "layers": ("5206626000665868017", "🟣"),
    "arrow": ("5206401524200145033", "↗️"),
    "arrow_down": ("5206510891247371052", "↘️"),
    "box": ("5206702193385700709", "📦"),
    "bell": ("5206222720416643915", "🔔"),
    "ok": ("5194996633682600894", "✅"),
    "ten": ("5194955350456953187", "🔟"),
}

# синие квадраты 0–9 из 3.png; fallback — keycap (иначе ENTITY_TEXT_INVALID)
DIGIT: dict[int, tuple[str, str]] = {
    0: ("5242380641332393116", "0️⃣"),
    1: ("5244961448525848230", "1️⃣"),
    2: ("5242293676834579345", "2️⃣"),
    3: ("5242652525647127686", "3️⃣"),
    4: ("5242287453426969423", "4️⃣"),
    5: ("5242407832770340528", "5️⃣"),
    6: ("5242669447818277073", "6️⃣"),
    7: ("5242663134216350272", "7️⃣"),
    8: ("5242497782270418294", "8️⃣"),
    9: ("5242286371095211663", "9️⃣"),
}


def ce(name: str) -> str:
    """Premium-пак в HTML сообщений. Если Telegram отклонит — strip_ce оставит unicode."""
    emoji_id, fallback = EMOJI[name]
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


def strip_ce(text: str) -> str:
    import re

    return re.sub(r'<tg-emoji emoji-id="[^"]*">(.*?)</tg-emoji>', r"\1", text, flags=re.S)


def ce_digit(n: int) -> str:
    emoji_id, fallback = DIGIT[n]
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


def ico(name: str) -> str:
    return EMOJI[name][1]


def eid(name: str) -> str:
    return EMOJI[name][0]


JOB_STATUS_ICON = {
    "pending": "clock",
    "processing": "hammer",
    "done": "ok",
    "failed": "stop",
}

JOB_STATUS_LABEL = {
    "pending": "В очереди",
    "processing": "В работе",
    "done": "Готово",
    "failed": "Ошибка",
}


def is_https_url(url: str) -> bool:
    return str(url or "").lower().startswith("https://")


def is_miniapp_url(url: str) -> bool:
    """Telegram Mini App: HTTPS and not a placeholder host."""
    if not is_https_url(url):
        return False
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    if not host or host in {"localhost", "127.0.0.1"}:
        return False
    if host == "example.com" or host.endswith(".example.com"):
        return False
    return True


def panel_url(web_base: str) -> str:
    return str(web_base or "").rstrip("/")


def panel_webapp(web_base: str) -> WebAppInfo | None:
    url = panel_url(web_base)
    if is_miniapp_url(url):
        return WebAppInfo(url=url)
    return None


def btn(text: str, data: str, icon: str | None = None) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text,
        callback_data=data,
        icon_custom_emoji_id=eid(icon) if icon else None,
    )


def digit_btn(n: int, data: str, *, selected: bool = False) -> InlineKeyboardButton:
    label = f"✓ {n}" if selected else str(n)
    if n >= 10:
        icon_id = eid("ten")
    else:
        icon_id = DIGIT[n][0]
    return InlineKeyboardButton(
        text=label, callback_data=data, icon_custom_emoji_id=icon_id
    )


def panel_btn(web_base: str) -> InlineKeyboardButton:
    app = panel_webapp(web_base)
    if app:
        return InlineKeyboardButton(
            text="Открыть панель", web_app=app, icon_custom_emoji_id=eid("monitor")
        )
    url = panel_url(web_base) or "http://localhost:8080"
    return InlineKeyboardButton(
        text="Открыть панель", url=url, icon_custom_emoji_id=eid("link")
    )


def support_btn(url: str) -> InlineKeyboardButton:
    href = url or "https://t.me/arxixx"
    return InlineKeyboardButton(
        text="Поддержка", url=href, icon_custom_emoji_id=eid("megaphone")
    )


def back_menu_btn() -> InlineKeyboardButton:
    return btn("В меню", "m:home", "house")


def main_menu_kb(web_base: str, support_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn("Сгенерировать", "m:gen", "star"),
                btn("Отрисовать", "m:ren", "layers"),
            ],
            [btn("Мои задачи", "m:jobs", "briefcase")],
            [
                btn("Портрет", "m:port", "user"),
                btn("Профиль", "m:prof", "bookmark"),
            ],
            [btn("Статус", "m:stat", "monitor")],
            [panel_btn(web_base)],
            [support_btn(support_url)],
        ]
    )


def back_only_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[back_menu_btn()]])


def render_options_kb(bg: int, portrait_on: bool) -> InlineKeyboardMarkup:
    row1 = [digit_btn(i, f"rb:{i}", selected=(bg == i)) for i in range(1, 6)]
    row2 = [digit_btn(i, f"rb:{i}", selected=(bg == i)) for i in range(6, 11)]
    port = ("✓ " if portrait_on else "") + "Портрет (ИИ)"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            row1,
            row2,
            [
                btn(port, "rp:ai", "user"),
                btn("Отрисовать", "rq:go", "check"),
            ],
            [back_menu_btn()],
        ]
    )


def portrait_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn("Сгенерировать ИИ", "rp:ai", "star")],
            [back_menu_btn()],
        ]
    )


def profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[back_menu_btn()]])


def after_render_kb(web_base: str = "") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [btn("Мои задачи", "m:jobs", "briefcase")],
    ]
    if panel_url(web_base):
        rows.append([panel_btn(web_base)])
    rows.append([back_menu_btn()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def after_generate_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn("Отрисовать", "m:ren", "layers")],
            [back_menu_btn()],
        ]
    )


def generate_hint_text() -> str:
    return assert_telegram_html(
        f"{ce('star')} <b>Генерация записи</b>\n"
        "Отправьте одним сообщением ФИО, дату и место рождения:\n"
        "<code>ФАМИЛИЯ ИМЯ ОТЧЕСТВО 08.09.1983 Г. ХАБАРОВСК</code>"
    )


def jobs_list_kb(
    rows: list[dict],
    *,
    page: int = 0,
    pages: int = 1,
) -> InlineKeyboardMarkup:
    keyboard: list[list[InlineKeyboardButton]] = []
    for j in rows:
        jid = str(j.get("job_id") or "")
        if not jid:
            continue
        st = str(j.get("status") or "")
        title = (j.get("title") or jid)[:28]
        label = f"{JOB_STATUS_LABEL.get(st, st)} · {title}"[:64]
        keyboard.append([btn(label, f"jo:{jid}", JOB_STATUS_ICON.get(st, "inbox"))])
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(btn("Назад", f"jl:{page - 1}", "arrow"))
        nav.append(btn(f"{page + 1}/{pages}", "jl:noop", "inbox"))
        if page < pages - 1:
            nav.append(btn("Дальше", f"jl:{page + 1}", "arrow_down"))
        keyboard.append(nav)
    keyboard.append([back_menu_btn()])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def job_detail_kb(
    job_id: str, *, has_jpg: bool, has_psd: bool, has_jpg_back: bool = False
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if has_jpg:
        rows.append([btn("Скачать JPG лицевая", f"jj:{job_id}", "folder")])
    if has_jpg_back:
        rows.append([btn("Скачать JPG оборот", f"jb:{job_id}", "folder")])
    if has_psd:
        rows.append([btn("Скачать PSD", f"jp:{job_id}", "box")])
    rows.append([btn("К задачам", "m:jobs", "briefcase")])
    rows.append([back_menu_btn()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def jobs_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[back_menu_btn()]])


def status_kb(*, admin: bool) -> InlineKeyboardMarkup:
    rows = []
    if admin:
        rows.append([btn("Восстановить зависшие", "adm:recover", "broom")])
    rows.append([back_menu_btn()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def region_kb(page: int, codes: list[str], names: dict[str, str], *, per_page: int = 24) -> InlineKeyboardMarkup:
    pages = max(1, (len(codes) + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))
    chunk = codes[page * per_page : (page + 1) * per_page]
    rows = [
        [
            btn(f"{c} {names[c][:18]}", f"rg:{c}", "cube")
            for c in chunk[i : i + 2]
        ]
        for i in range(0, len(chunk), 2)
    ]
    nav = []
    if page > 0:
        nav.append(btn("◀", f"rgp:{page - 1}", "arrow"))
    nav.append(btn(f"{page + 1}/{pages}", "rgp:noop", "inbox"))
    if page < pages - 1:
        nav.append(btn("▶", f"rgp:{page + 1}", "arrow_down"))
    rows.append(nav)
    rows.append([btn("Любое подразделение", "rg:any", "game")])
    rows.append([back_menu_btn()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def birthplace_kb(page: int, places: list[str], *, per_page: int = 8) -> InlineKeyboardMarkup:
    pages = max(1, (len(places) + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))
    chunk = places[page * per_page : (page + 1) * per_page]
    rows = [
        [btn(p[:28], f"bp:{i + page * per_page}", "bookmark")]
        for i, p in enumerate(chunk)
    ]
    nav = []
    if page > 0:
        nav.append(btn("◀", f"bpp:{page - 1}", "arrow"))
    nav.append(btn(f"{page + 1}/{pages}", "bpp:noop", "inbox"))
    if page < pages - 1:
        nav.append(btn("▶", f"bpp:{page + 1}", "arrow_down"))
    rows.append(nav)
    rows.append([btn("Любое место", "bp:any", "game")])
    rows.append([back_menu_btn()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_menu_text(queue: dict, worker_alive: bool) -> str:
    pending = queue.get("pending", 0)
    processing = queue.get("processing", 0)
    done = queue.get("done", 0)
    worker = "online" if worker_alive else "offline"
    return assert_telegram_html(
        f"{ce('chart')} <b>Очередь отрисовки</b>\n"
        f"В очереди: {pending} | В работе: {processing} | Готово: {done}\n"
        f"Worker: {worker}\n\n"
        f"{ce('folder')} <b>Модуль VU Studio</b>\n"
        f"Выберите действие:"
    )


def status_screen(
    *,
    mode: str,
    worker_alive: bool,
    pending: int,
    processing: int,
    done: int,
    failed: int,
    photoshop_ok: bool,
    message: str = "",
    current_job: str | None = None,
    last_error: str | None = None,
) -> str:
    worker_line = (
        f"{ce('ok')} <b>Worker online</b>"
        if worker_alive
        else f"{ce('stop')} <b>Worker offline</b>"
    )
    ps_line = (
        f"{ce('ok')} Photoshop готов"
        if photoshop_ok
        else f"{ce('warning')} Photoshop не подключён"
    )
    lines = [
        f"{ce('monitor')} <b>Статус VU Studio</b>",
        "",
        worker_line,
        f"{ce('cube')} Режим: <b>{html.escape(str(mode))}</b>",
        ps_line,
        "",
        f"{ce('chart')} <b>Очередь</b>",
        f"{ce('inbox')} В очереди: <b>{pending}</b>",
        f"{ce('hammer')} В работе: <b>{processing}</b>",
        f"{ce('check')} Готово: <b>{done}</b>",
        f"{ce('stop')} Ошибки: <b>{failed}</b>",
    ]
    if current_job:
        lines += ["", f"{ce('briefcase')} Текущая задача: <code>{html.escape(str(current_job))}</code>"]
    if last_error:
        lines += ["", f"{ce('warning')} {html.escape(str(last_error))}"]
    if message:
        lines += ["", f"{ce('info')} {html.escape(str(message))}"]
    return assert_telegram_html("\n".join(lines))


def jobs_screen_text(count: int, page: int = 0, pages: int = 1) -> str:
    if count <= 0:
        text = f"{ce('briefcase')} <b>Мои задачи</b>\nОчередь пуста."
    else:
        extra = f"\nСтраница {page + 1} из {pages}" if pages > 1 else ""
        text = f"{ce('briefcase')} <b>Мои задачи</b>\nВсего: {count}{extra}\nВыберите задачу:"
    return assert_telegram_html(text)


def profile_screen(
    *,
    user_id: int,
    username: str = "",
    first_name: str = "",
    generations: int = 0,
    renders: int = 0,
    jobs_done: int = 0,
    jobs_failed: int = 0,
    jobs_pending: int = 0,
) -> str:
    uname = html.escape(username) if username else "без username"
    name = html.escape(first_name) if first_name else "—"
    return assert_telegram_html(
        f"{ce('user')} <b>Профиль</b>\n"
        f"{ce('at')} {uname}\n"
        f"{ce('bookmark')} {name}\n"
        f"{ce('lock')} ID: <code>{user_id}</code>\n\n"
        f"{ce('chart')} <b>Статистика</b>\n"
        f"{ce('star')} Генераций: <b>{generations}</b>\n"
        f"{ce('layers')} Отрисовок: <b>{renders}</b>\n"
        f"{ce('check')} Задач готово: <b>{jobs_done}</b>\n"
        f"{ce('clock')} В очереди: <b>{jobs_pending}</b>\n"
        f"{ce('stop')} Ошибок: <b>{jobs_failed}</b>"
    )


def job_detail_text(
    *,
    job_id: str,
    status: str,
    title: str,
    mockup: str,
    background: int | str | None,
    error: str | None,
    fields: dict | None,
) -> str:
    st = JOB_STATUS_LABEL.get(status, status or "—")
    icon = JOB_STATUS_ICON.get(status, "inbox")
    lines = [
        f"{ce(icon)} <b>{html.escape(st)}</b>",
        f"{ce('cube')} <code>{html.escape(job_id)}</code>",
    ]
    if title:
        lines.append(f"{ce('user')} {html.escape(title)}")
    extra = []
    if mockup:
        extra.append(html.escape(str(mockup)))
    if background:
        extra.append(f"фон {html.escape(str(background))}")
    if extra:
        lines.append(f"{ce('layers')} {' · '.join(extra)}")
    if error:
        lines.append(f"{ce('warning')} {html.escape(error)}")
    data = fields or {}
    pairs = [
        ("surname_ru", "Фамилия"),
        ("given_ru", "Имя"),
        ("birth_date", "Дата рождения"),
        ("number", "Номер"),
        ("series", "Серия"),
        ("issue_date", "Выдано"),
        ("expiry_date", "Действует до"),
    ]
    shown = False
    for key, label in pairs:
        val = data.get(key)
        if val:
            if not shown:
                lines.append("")
                lines.append(f"{ce('bookmark')} <b>Данные</b>")
                shown = True
            lines.append(f"{ce('check')} {label}: <b>{html.escape(str(val))}</b>")
    return assert_telegram_html("\n".join(lines))


def render_prompt_text(summary: str, bg: int) -> str:
    nums = " ".join(ce_digit(i) if i < 10 else ce("ten") for i in range(1, 11))
    return assert_telegram_html(
        f"{ce('layers')} <b>Отрисовка мокапа</b>\n"
        f"Сейчас: <b>{html.escape(summary)}</b>\n"
        f"Фон: {ce_digit(bg) if bg < 10 else ce('ten')}\n\n"
        f"{nums}\n"
        f"Выберите фон 1–10 и запустите отрисовку."
    )


_TG_EMOJI = r'<tg-emoji emoji-id="[0-9]+">(.*?)</tg-emoji>'

_HTML_TAG = (
    r"</?(?:b|strong|i|em|u|ins|s|strike|del|code|pre|"
    r"a(?:\s[^>]*)?|tg-spoiler|blockquote)>"
)


def assert_telegram_html(text: str) -> str:
    """Telegram parse_mode=HTML: <tg-emoji> разрешён, сырые < > и голый & — нет."""
    import re

    if not text:
        return text
    stripped = re.sub(_TG_EMOJI, r"\1", text, flags=re.S)
    stripped = re.sub(_HTML_TAG, "", stripped, flags=re.I)
    if "<" in stripped or ">" in stripped:
        raise ValueError(f"unescaped angle brackets in HTML: {stripped[:200]!r}")
    leftover = re.sub(r"&(?:amp|lt|gt|quot|#\d+|#x[0-9a-fA-F]+);", "", stripped)
    if "&" in leftover:
        raise ValueError(f"unescaped ampersand in HTML: {leftover[:200]!r}")
    for tag in ("b", "code", "pre"):
        if text.count(f"<{tag}>") != text.count(f"</{tag}>"):
            raise ValueError(f"unbalanced <{tag}>")
    if text.count("<tg-emoji") != text.count("</tg-emoji>"):
        raise ValueError("unbalanced <tg-emoji>")
    return text
