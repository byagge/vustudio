#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram-бот: генерация записей ВУ + очередь отрисовки PSD/JPG.

Архитектура task1.md:
  бот → парсер → JSON → очередь → render-worker → Photoshop → JPG + PSD
"""
from __future__ import annotations

import asyncio
import html
import logging
from dataclasses import dataclass, field
from pathlib import Path

from aiogram import Bot, Dispatcher, BaseMiddleware, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import Settings
from formatter import BANNER, format_client_block, format_debug_block, record_to_json, render_html
from mockup_registry import MOCKUPS, MockupKind
from mockup_scene import normalize_options_for_mockup, scene_summary, validate_scene_options
from portrait_service import generate_ai_portrait, portrait_status_label, prepare_upload, save_upload
from photoshop_text import substitute_text_queued, wait_substitute
from render_models import RenderOptions
from text_parser import TextParseError, parse_client_block
from text_realism import validate_block
from vu_testdata import (
    BIRTH_PLACES,
    REGIONS,
    IdentityError,
    LicenceRecord,
    make_valid,
    new_rng,
    parse_me,
)

PAGE = 24
BP_PAGE = 8
USAGE = (
    "<b>Формат:</b>\n"
    "<code>/me ФАМИЛИЯ ИМЯ ОТЧЕСТВО ДД.ММ.ГГГГ МЕСТО РОЖДЕНИЯ</code>\n\n"
    "<b>Отрисовка:</b> вставьте блок полей → выберите мокап/фон → «Отрисовать».\n"
    "Фото для портрета — отправьте изображение с подписью <code>/portrait</code>."
)

log = logging.getLogger("vu_qa_bot")
_last_record: dict[int, LicenceRecord] = {}


@dataclass
class RenderDraft:
    text_block: str
    options: RenderOptions = field(default_factory=RenderOptions)


_drafts: dict[int, RenderDraft] = {}


def region_kb(page: int = 0) -> InlineKeyboardMarkup:
    codes = sorted(REGIONS)
    pages = max(1, (len(codes) + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    chunk = codes[page * PAGE : (page + 1) * PAGE]
    rows = [
        [
            InlineKeyboardButton(text=f"{c} {REGIONS[c][:18]}", callback_data=f"rg:{c}")
            for c in chunk[i : i + 2]
        ]
        for i in range(0, len(chunk), 2)
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"rgp:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="rgp:noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"rgp:{page + 1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="🎲 Любое подразделение", callback_data="rg:any")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def birthplace_kb(page: int = 0) -> InlineKeyboardMarkup:
    places = BIRTH_PLACES
    pages = max(1, (len(places) + BP_PAGE - 1) // BP_PAGE)
    page = max(0, min(page, pages - 1))
    chunk = places[page * BP_PAGE : (page + 1) * BP_PAGE]
    rows = [
        [InlineKeyboardButton(text=p[:28], callback_data=f"bp:{i + page * BP_PAGE}")]
        for i, p in enumerate(chunk)
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"bpp:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="bpp:noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"bpp:{page + 1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="🎲 Любое место", callback_data="bp:any")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def render_options_kb(opts: RenderOptions) -> InlineKeyboardMarkup:
    mockup = opts.mockup
    bg = opts.background
    rows = [
        [
            InlineKeyboardButton(
                text=("✓ " if mockup == MockupKind.BLANK.value else "") + "📄 Бланк",
                callback_data="rm:blank",
            ),
            InlineKeyboardButton(
                text=("✓ " if mockup == MockupKind.HAND.value else "") + "🤚 Рука+фон",
                callback_data="rm:hand",
            ),
            InlineKeyboardButton(
                text=("✓ " if mockup == MockupKind.ORIGINAL.value else "") + "🖼 Оригинал",
                callback_data="rm:original",
            ),
        ],
    ]
    if mockup != MockupKind.BLANK.value:
        bg_row = []
        for i in range(1, 6):
            bg_row.append(
                InlineKeyboardButton(
                    text=f"{'✓' if bg == i else ''}{i}",
                    callback_data=f"rb:{i}",
                )
            )
        rows.append(bg_row)
        bg_row2 = []
        for i in range(6, 11):
            bg_row2.append(
                InlineKeyboardButton(
                    text=f"{'✓' if bg == i else ''}{i}",
                    callback_data=f"rb:{i}",
                )
            )
        rows.append(bg_row2)
        rows.append(
            [
                InlineKeyboardButton(
                    text=("✓ " if opts.generate_portrait else "") + "🧑 Портрет (ИИ)",
                    callback_data="rp:ai",
                ),
                InlineKeyboardButton(text="▶️ Отрисовать", callback_data="rq:go"),
            ]
        )
    else:
        rows.append([InlineKeyboardButton(text="▶️ Отрисовать", callback_data="rq:go")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _portrait_caption(opts: RenderOptions) -> str:
    st = portrait_status_label(opts)
    mockup_title = MOCKUPS[opts.mockup].title
    return f"Мокап: <b>{html.escape(mockup_title)}</b>, фон #{opts.background}\nПортрет: {html.escape(st)}"


async def _generate_portrait_preview(msg: Message, draft: RenderDraft) -> bool:
    """Сгенерировать ИИ-портрет и показать превью. Возвращает успех."""
    if not draft.text_block.strip():
        await msg.answer("❌ Сначала отправьте блок полей ВУ.")
        return False
    try:
        block = parse_client_block(draft.text_block)
        errors = validate_block(block)
        if errors:
            await msg.answer("❌ " + html.escape("; ".join(errors)))
            return False
    except TextParseError as e:
        await msg.answer(f"❌ {html.escape(str(e))}")
        return False

    from render_models import block_to_dict

    await msg.answer("🧑 Генерирую ИИ-портрет… (10–60 сек)")
    result = await asyncio.to_thread(generate_ai_portrait, block_to_dict(block))
    if not result.ok or not result.path:
        await msg.answer(f"❌ {html.escape(result.message)}")
        return False

    draft.options.portrait_path = str(result.path)
    draft.options.generate_portrait = False
    await msg.answer_photo(
        FSInputFile(str(result.path)),
        caption=f"✅ {html.escape(result.message)} ({result.source})",
    )
    await msg.answer("Настройки отрисовки:", reply_markup=render_options_kb(draft.options))
    return True


def profile_summary(profile) -> str:
    ident = profile.ident
    region = profile.region
    if region and region in REGIONS:
        region_txt = f"{region} {REGIONS[region]}"
    elif region:
        region_txt = region
    else:
        region_txt = "любое подразделение"
    return (
        f"<code>{html.escape(ident.surname)} {html.escape(ident.given)}</code>\n"
        f"ДР {ident.birth_date} · пол {'жен' if ident.gender == 'F' else 'муж'}\n"
        f"Место рожд.: {html.escape(profile.birth_place or 'любое (случайно)')}\n"
        f"Подразделение: {html.escape(region_txt)}"
    )


def generate_record(profile, region_code: str | None) -> LicenceRecord:
    code = region_code if region_code and region_code != "any" else profile.region
    if code == "any":
        code = None
    return make_valid(
        new_rng(),
        identity=profile.ident,
        region_code=code,
        birth_place=profile.birth_place,
        valid_now=True,
    )


def region_label(code: str | None) -> str:
    if not code or code == "any":
        return "любое подразделение"
    return f"{code} {REGIONS.get(code, '')}"


def _looks_like_vu_block(text: str) -> bool:
    t = text.lstrip().lower()
    return t.startswith("1  фамилия")


def _set_draft(uid: int, text_block: str) -> RenderDraft:
    draft = _drafts.get(uid) or RenderDraft(text_block=text_block)
    draft.text_block = text_block
    _drafts[uid] = draft
    return draft


async def _prompt_render_options(msg: Message, text_block: str) -> None:
    draft = _set_draft(msg.from_user.id, text_block)
    summary = scene_summary(draft.options)
    await msg.answer(
        f"Выберите мокап и фон.\n"
        f"Сейчас: <b>{html.escape(summary)}</b>",
        reply_markup=render_options_kb(draft.options),
    )


async def _enqueue_and_wait(
    msg: Message,
    draft: RenderDraft,
    *,
    chat_id: int,
    user_id: int,
) -> None:
    queued = substitute_text_queued(
        draft.text_block,
        mockup=draft.options.mockup,
        background=draft.options.background,
        portrait_path=draft.options.portrait_path,
        generate_portrait=draft.options.generate_portrait,
        chat_id=chat_id,
        user_id=user_id,
    )
    if not queued.ok:
        await msg.answer(f"❌ {html.escape(queued.message)}")
        return

    summary = scene_summary(draft.options)
    portrait_line = ""
    if draft.options.portrait_path or draft.options.generate_portrait:
        portrait_line = f"\nПортрет: {html.escape(portrait_status_label(draft.options))}"
    await msg.answer(
        f"⏳ Генерирую… (job <code>{queued.job_id}</code>)\n"
        f"{html.escape(summary)}"
        f"{portrait_line}\n"
        f"Обычно 5–60 сек."
    )

    done = await asyncio.to_thread(wait_substitute, queued.job_id, 900, 2.0)
    if not done.ok:
        await msg.answer(f"❌ {html.escape(done.message)}")
        return

    jpg = done.jpg_path
    psd = done.psd_path

    if jpg and jpg.is_file():
        await msg.answer_photo(FSInputFile(str(jpg)), caption="JPG превью")
    if psd and psd.is_file():
        await msg.answer_document(FSInputFile(str(psd)), caption="PSD (редактируемый)")
    await msg.answer("✅ Готово")


async def deliver_record(msg: Message, rec: LicenceRecord, where: str, user_id: int) -> None:
    _last_record[user_id] = rec
    client_text = format_client_block(rec)
    debug_text = format_debug_block(rec)
    await msg.answer(f"Подразделение: <b>{html.escape(where)}</b>")
    await msg.answer(render_html(rec, debug=True))
    await msg.answer_document(
        BufferedInputFile(client_text.encode("utf-8"), filename="vu_block.txt"),
        caption="Текстовый блок",
    )
    await msg.answer_document(
        BufferedInputFile(debug_text.encode("utf-8"), filename="vu_record_debug.txt"),
        caption=BANNER,
    )
    await msg.answer_document(
        BufferedInputFile(record_to_json(rec).encode("utf-8"), filename="vu_record.json"),
        caption="JSON записи",
    )
    draft = _set_draft(user_id, client_text)
    await msg.answer(
        "Настройте отрисовку:",
        reply_markup=render_options_kb(draft.options),
    )


class AllowedUsers(BaseMiddleware):
    def __init__(self, allowed: frozenset[int]):
        self.allowed = allowed

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user is None or user.id not in self.allowed:
            return None
        return await handler(event, data)


def create_dispatcher(settings: Settings) -> Dispatcher:
    from profiles import ProfileStore

    store = ProfileStore(settings.profiles_path)
    dp = Dispatcher()

    @dp.message(Command("start", "help"))
    async def cmd_start(msg: Message) -> None:
        profile = store.load(msg.from_user.id)
        cur = f"\n{profile_summary(profile)}\n" if profile else ""
        await msg.answer(
            f"<b>{BANNER}</b>\n\n"
            "Генератор и отрисовка ВУ.\n"
            f"{cur}\n{USAGE}\n\n"
            "<b>Команды:</b> /me · /render · /portrait · /status · /admin · /forget"
        )

    @dp.message(Command("forget", "clear"))
    async def cmd_forget(msg: Message) -> None:
        uid = msg.from_user.id
        if store.delete(uid):
            _last_record.pop(uid, None)
            _drafts.pop(uid, None)
            await msg.answer("Профиль удалён.")
        else:
            await msg.answer("Профиль не был сохранён.")

    @dp.message(Command("me"))
    async def cmd_me(msg: Message, command: CommandObject) -> None:
        uid = msg.from_user.id
        if not command.args:
            profile = store.load(uid)
            if profile:
                await msg.answer(
                    f"Сохранено:\n{profile_summary(profile)}",
                    reply_markup=region_kb(0),
                )
            else:
                await msg.answer(USAGE)
            return
        try:
            ident, place = parse_me(command.args)
        except IdentityError as e:
            await msg.answer(f"❌ {html.escape(str(e))}\n\n{USAGE}")
            return
        store.save_identity(uid, ident, place)
        await msg.answer(
            f"✅ <code>{html.escape(ident.surname)} {html.escape(ident.given)}</code>\n"
            f"ДР {ident.birth_date}"
        )
        if place:
            await msg.answer("Выберите подразделение:", reply_markup=region_kb(0))
        else:
            await msg.answer("Место рождения:", reply_markup=birthplace_kb(0))

    @dp.message(Command("render"))
    async def cmd_render(msg: Message, command: CommandObject) -> None:
        uid = msg.from_user.id
        text_block = (command.args or "").strip()
        if not text_block:
            rec = _last_record.get(uid)
            if rec:
                text_block = format_client_block(rec)
            elif uid in _drafts:
                text_block = _drafts[uid].text_block
            else:
                await msg.answer("Нет данных для отрисовки.")
                return
        try:
            parse_client_block(text_block)
        except TextParseError as e:
            await msg.answer(f"❌ {html.escape(str(e))}")
            return
        await _prompt_render_options(msg, text_block)

    @dp.message(Command("portrait"))
    async def cmd_portrait(msg: Message, command: CommandObject) -> None:
        uid = msg.from_user.id
        arg = (command.args or "").strip().lower()

        if arg == "generate":
            draft = _drafts.get(uid)
            if not draft:
                await msg.answer("Сначала отправьте блок полей ВУ.")
                return
            await _generate_portrait_preview(msg, draft)
            return

        await msg.answer("Отправьте фото ответом на это сообщение или с подписью <code>/portrait</code>.")

    @dp.message(F.photo)
    async def on_photo(msg: Message) -> None:
        if not msg.photo:
            return
        caption = (msg.caption or "").lower()
        if "/portrait" not in caption and "portrait" not in caption:
            return
        photo = msg.photo[-1]
        file = await msg.bot.get_file(photo.file_id)
        from io import BytesIO

        buf = BytesIO()
        await msg.bot.download_file(file.file_path, buf)
        result = prepare_upload(buf.getvalue(), msg.from_user.id)
        if not result.ok or not result.path:
            await msg.answer(f"❌ {html.escape(result.message or 'Ошибка загрузки')}")
            return
        draft = _drafts.get(msg.from_user.id) or RenderDraft(text_block="")
        draft.options.portrait_path = str(result.path)
        draft.options.generate_portrait = False
        _drafts[msg.from_user.id] = draft
        await msg.answer_photo(
            FSInputFile(str(result.path)),
            caption=f"✅ Портрет: <code>{result.path.name}</code>",
        )
        if draft.text_block.strip():
            await msg.answer(
                "Настройки отрисовки:",
                reply_markup=render_options_kb(draft.options),
            )

    @dp.message(F.text.func(_looks_like_vu_block))
    async def on_vu_text_block(msg: Message) -> None:
        try:
            parse_client_block(msg.text or "")
        except TextParseError as e:
            await msg.answer(f"❌ {html.escape(str(e))}")
            return
        await _prompt_render_options(msg, msg.text or "")

    @dp.callback_query(F.data.startswith("rm:"))
    async def cb_mockup(cq: CallbackQuery) -> None:
        uid = cq.from_user.id
        draft = _drafts.get(uid)
        if not draft:
            await cq.answer("Сначала отправьте блок полей", show_alert=True)
            return
        draft.options.mockup = cq.data.split(":", 1)[1]
        draft.options = normalize_options_for_mockup(draft.options)
        await cq.answer(MOCKUPS[draft.options.mockup].title)
        await cq.message.edit_reply_markup(reply_markup=render_options_kb(draft.options))
        await cq.message.edit_text(
            f"Сейчас: <b>{html.escape(scene_summary(draft.options))}</b>",
            reply_markup=render_options_kb(draft.options),
        )

    @dp.callback_query(F.data.startswith("rb:"))
    async def cb_background(cq: CallbackQuery) -> None:
        uid = cq.from_user.id
        draft = _drafts.get(uid)
        if not draft:
            await cq.answer("Нет черновика", show_alert=True)
            return
        if draft.options.mockup == MockupKind.BLANK.value:
            await cq.answer("Фон доступен для «Рука+фон» / «Оригинал»", show_alert=True)
            return
        draft.options.background = int(cq.data.split(":", 1)[1])
        await cq.answer(f"Фон #{draft.options.background}")
        await cq.message.edit_reply_markup(reply_markup=render_options_kb(draft.options))
        await cq.message.edit_text(
            f"Выберите мокап и фон.\n"
            f"Сейчас: <b>{html.escape(scene_summary(draft.options))}</b>",
            reply_markup=render_options_kb(draft.options),
        )

    @dp.callback_query(F.data == "rp:ai")
    async def cb_portrait_ai(cq: CallbackQuery) -> None:
        uid = cq.from_user.id
        draft = _drafts.get(uid)
        if not draft:
            await cq.answer("Нет черновика", show_alert=True)
            return
        if draft.options.mockup == MockupKind.BLANK.value:
            await cq.answer("Портрет только для «Рука+фон» / «Оригинал»", show_alert=True)
            return
        draft.options.generate_portrait = True
        draft.options.portrait_path = None
        await cq.answer("ИИ-портрет будет запрошен при отрисовке")
        await cq.message.edit_reply_markup(reply_markup=render_options_kb(draft.options))

    @dp.callback_query(F.data == "rq:go")
    async def cb_render_go(cq: CallbackQuery) -> None:
        uid = cq.from_user.id
        draft = _drafts.get(uid)
        if not draft or not draft.text_block.strip():
            await cq.answer("Нет текста для отрисовки", show_alert=True)
            return

        from photoshop_server import get_server_status, is_server_mode

        if is_server_mode():
            st = get_server_status()
            if not st.worker_alive:
                await cq.answer(
                    "Worker offline — задача в очереди. Запустите render_worker на Windows.",
                    show_alert=True,
                )

        await cq.answer("В очередь")
        await _enqueue_and_wait(
            cq.message,
            draft,
            chat_id=cq.message.chat.id,
            user_id=uid,
        )

    @dp.callback_query(F.data.startswith("bpp:"))
    async def cb_birthplace_page(cq: CallbackQuery) -> None:
        arg = cq.data.split(":", 1)[1]
        if arg != "noop":
            await cq.message.edit_reply_markup(reply_markup=birthplace_kb(int(arg)))
        await cq.answer()

    @dp.callback_query(F.data.startswith("bp:"))
    async def cb_birthplace_pick(cq: CallbackQuery) -> None:
        uid = cq.from_user.id
        profile = store.load(uid)
        if not profile:
            await cq.answer("Сначала /me", show_alert=True)
            return
        arg = cq.data.split(":", 1)[1]
        place = None if arg == "any" else BIRTH_PLACES[int(arg)]
        store.save_birth_place(uid, place)
        await cq.answer()
        await cq.message.answer("Выберите подразделение:", reply_markup=region_kb(0))

    @dp.callback_query(F.data.startswith("rgp:"))
    async def cb_region_page(cq: CallbackQuery) -> None:
        arg = cq.data.split(":", 1)[1]
        if arg != "noop":
            await cq.message.edit_reply_markup(reply_markup=region_kb(int(arg)))
        await cq.answer()

    @dp.callback_query(F.data.startswith("rg:"))
    async def cb_region_pick(cq: CallbackQuery) -> None:
        uid = cq.from_user.id
        profile = store.load(uid)
        if not profile:
            await cq.answer("Сначала /me", show_alert=True)
            return
        code = cq.data.split(":", 1)[1]
        if code != "any" and code not in REGIONS:
            await cq.answer("Неизвестный код", show_alert=True)
            return
        store.save_region(uid, None if code == "any" else code)
        profile = store.load(uid)
        await cq.answer("Генерирую…")
        rec = generate_record(profile, None if code == "any" else code)
        await cq.message.edit_text(f"Подразделение: <b>{html.escape(region_label(code))}</b>")
        await deliver_record(cq.message, rec, region_label(code), uid)

    @dp.message(Command("status"))
    async def cmd_status(msg: Message) -> None:
        from admin_tools import format_status_text

        await msg.answer(f"<pre>{html.escape(format_status_text())}</pre>")

    @dp.message(Command("admin"))
    async def cmd_admin(msg: Message) -> None:
        if not settings.is_admin(msg.from_user.id):
            await msg.answer("Команда только для администратора.")
            return
        from admin_tools import admin_dashboard, format_status_text

        dash = admin_dashboard()
        q = dash["queue"]
        web = settings.web_base_url
        await msg.answer(
            f"<b>Админ-панель</b>\n\n"
            f"<pre>{html.escape(format_status_text())}</pre>\n\n"
            f"Очередь: done={q['done']} failed={q['failed']}\n"
            f"Scene OK: {'да' if dash['scene_verify'].get('ok') else 'нет'}\n\n"
            f"Веб: <a href=\"{html.escape(web)}\">{html.escape(web)}</a>\n"
            f"API: <a href=\"{html.escape(web)}/docs\">/docs</a>",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="♻ Восстановить зависшие", callback_data="adm:recover")],
                ]
            ),
        )

    @dp.callback_query(F.data == "adm:recover")
    async def cb_admin_recover(cq: CallbackQuery) -> None:
        if not settings.is_admin(cq.from_user.id):
            await cq.answer("Нет доступа", show_alert=True)
            return
        from admin_tools import admin_recover_stale

        raw = admin_recover_stale()
        await cq.answer(f"Восстановлено: {raw['recovered']}", show_alert=True)

    return dp


async def run() -> None:
    settings = Settings.load()
    settings.require_bot()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    dp = create_dispatcher(settings)
    guard = AllowedUsers(settings.allowed_users)
    dp.message.middleware(guard)
    dp.callback_query.middleware(guard)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    me = await bot.get_me()
    log.info("бот @%s, queue=%s", me.username, settings.render_queue_dir)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
