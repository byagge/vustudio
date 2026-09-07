#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram-бот VU Studio.

Сетка меню и Mini App «Панель» — как в референсе. Логика: генерация блока,
отрисовка Photoshop, портрет, профиль.
"""
from __future__ import annotations

import asyncio
import html
import logging
from dataclasses import dataclass, field

from aiogram import Bot, Dispatcher, BaseMiddleware, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    BotCommand,
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardMarkup,
    MenuButtonCommands,
    MenuButtonWebApp,
    Message,
)

from config import Settings
from formatter import BANNER, format_client_block, format_debug_block, record_to_json, render_html
from mockup_registry import MOCKUPS, coerce_panel_mockup
from mockup_scene import normalize_options_for_mockup, scene_summary
from portrait_service import generate_ai_portrait, portrait_status_label, prepare_upload, save_upload
from photoshop_text import substitute_text_queued, wait_substitute
from render_models import RenderOptions
from text_parser import TextParseError, parse_client_block
from text_realism import validate_block
import tg_ui
from vu_testdata import (
    BIRTH_PLACES,
    REGIONS,
    IdentityError,
    LicenceRecord,
    make_valid,
    new_rng,
    parse_me,
)

ME_HINT = (
    f"{tg_ui.ce('info')} <b>Формат профиля</b>\n"
    "<code>/me ФАМИЛИЯ ИМЯ ОТЧЕСТВО ДД.ММ.ГГГГ МЕСТО РОЖДЕНИЯ</code>\n\n"
    "Или вставьте готовый блок полей — откроется отрисовка."
)

log = logging.getLogger("vu_qa_bot")
_last_record: dict[int, LicenceRecord] = {}


@dataclass
class RenderDraft:
    text_block: str
    options: RenderOptions = field(default_factory=RenderOptions)


_drafts: dict[int, RenderDraft] = {}


def _queue_snapshot() -> tuple[dict, bool]:
    from photoshop_server import get_server_status

    st = get_server_status()
    return (
        {
            "pending": st.queue.pending,
            "processing": st.queue.processing,
            "done": st.queue.done,
            "failed": st.queue.failed,
        },
        st.worker_alive,
    )


def region_kb(page: int = 0) -> InlineKeyboardMarkup:
    return tg_ui.region_kb(page, sorted(REGIONS), REGIONS)


def birthplace_kb(page: int = 0) -> InlineKeyboardMarkup:
    return tg_ui.birthplace_kb(page, BIRTH_PLACES)


def render_options_kb(opts: RenderOptions) -> InlineKeyboardMarkup:
    return tg_ui.render_options_kb(
        opts.background,
        bool(opts.generate_portrait or opts.portrait_path),
    )


def _portrait_caption(opts: RenderOptions) -> str:
    st = portrait_status_label(opts)
    mockup_title = MOCKUPS[opts.mockup].title
    return f"Мокап: <b>{html.escape(mockup_title)}</b>, фон #{opts.background}\nПортрет: {html.escape(st)}"


async def _generate_portrait_preview(msg: Message, draft: RenderDraft) -> bool:
    if not draft.text_block.strip():
        await msg.answer(
            f"{tg_ui.ce('stop')} Сначала сгенерируйте или вставьте блок полей.",
            reply_markup=tg_ui.back_only_kb(),
        )
        return False
    try:
        block = parse_client_block(draft.text_block)
        errors = validate_block(block)
        if errors:
            await msg.answer(
                f"{tg_ui.ce('stop')} " + html.escape("; ".join(errors)),
                reply_markup=tg_ui.back_only_kb(),
            )
            return False
    except TextParseError as e:
        await msg.answer(
            f"{tg_ui.ce('stop')} {html.escape(str(e))}",
            reply_markup=tg_ui.back_only_kb(),
        )
        return False

    from render_models import block_to_dict

    await msg.answer(f"{tg_ui.ce('clock')} Генерирую ИИ-портрет… (10–60 сек)")
    result = await asyncio.to_thread(
        generate_ai_portrait,
        block_to_dict(block),
        force=True,
    )
    if not result.ok or not result.path:
        await msg.answer(
            f"{tg_ui.ce('stop')} {html.escape(result.message)}",
            reply_markup=tg_ui.back_only_kb(),
        )
        return False

    draft.options.portrait_path = str(result.path)
    draft.options.generate_portrait = False
    await msg.answer_photo(
        FSInputFile(str(result.path)),
        caption=f"{tg_ui.ce('ok')} {html.escape(result.message)} ({result.source})",
    )
    await msg.answer(
        tg_ui.render_prompt_text(html.escape(scene_summary(draft.options)), draft.options.background),
        reply_markup=render_options_kb(draft.options),
    )
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


async def show_main_menu(msg: Message, settings: Settings, *, edit: bool = False) -> None:
    q, alive = _queue_snapshot()
    text = tg_ui.main_menu_text(q, alive)
    kb = tg_ui.main_menu_kb(settings.web_base_url, settings.support_url)
    if edit:
        try:
            await msg.edit_text(text, reply_markup=kb)
            return
        except Exception:
            pass
    await msg.answer(text, reply_markup=kb)


async def _prompt_render_options(msg: Message, text_block: str) -> None:
    draft = _set_draft(msg.from_user.id, text_block)
    draft.options.mockup = coerce_panel_mockup(draft.options.mockup)
    summary = html.escape(scene_summary(draft.options))
    await msg.answer(
        tg_ui.render_prompt_text(summary, draft.options.background),
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
        mockup=coerce_panel_mockup(draft.options.mockup),
        background=draft.options.background,
        portrait_path=draft.options.portrait_path,
        generate_portrait=draft.options.generate_portrait,
        chat_id=chat_id,
        user_id=user_id,
    )
    if not queued.ok:
        await msg.answer(
            f"{tg_ui.ce('stop')} {html.escape(queued.message)}",
            reply_markup=tg_ui.back_only_kb(),
        )
        return

    summary = scene_summary(draft.options)
    portrait_line = ""
    if draft.options.portrait_path or draft.options.generate_portrait:
        portrait_line = f"\nПортрет: {html.escape(portrait_status_label(draft.options))}"
    await msg.answer(
        f"{tg_ui.ce('clock')} Генерирую… (job <code>{queued.job_id}</code>)\n"
        f"{html.escape(summary)}"
        f"{portrait_line}\n"
        f"Обычно 5–60 сек."
    )

    done = await asyncio.to_thread(wait_substitute, queued.job_id, 900, 2.0)
    if not done.ok:
        await msg.answer(
            f"{tg_ui.ce('stop')} {html.escape(done.message)}",
            reply_markup=tg_ui.back_only_kb(),
        )
        return

    jpg = done.jpg_path
    psd = done.psd_path

    if jpg and jpg.is_file():
        await msg.answer_photo(FSInputFile(str(jpg)), caption=f"{tg_ui.ce('ok')} JPG превью")
    if psd and psd.is_file():
        await msg.answer_document(FSInputFile(str(psd)), caption="PSD (редактируемый)")
    await msg.answer(f"{tg_ui.ce('ok')} Готово", reply_markup=tg_ui.back_only_kb())


async def deliver_record(msg: Message, rec: LicenceRecord, where: str, user_id: int) -> None:
    _last_record[user_id] = rec
    client_text = format_client_block(rec)
    debug_text = format_debug_block(rec)
    await msg.answer(
        f"{tg_ui.ce('ok')} Подразделение: <b>{html.escape(where)}</b>\n\n"
        f"{render_html(rec, debug=True)}"
    )
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
        tg_ui.render_prompt_text(html.escape(scene_summary(draft.options)), draft.options.background),
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

    async def _start_generate(msg: Message, uid: int) -> None:
        profile = store.load(uid)
        if profile:
            await msg.answer(
                f"{tg_ui.ce('star')} <b>Генерация записи</b>\n{profile_summary(profile)}\n\n"
                f"Выберите подразделение:",
                reply_markup=region_kb(0),
            )
            return
        await msg.answer(ME_HINT, reply_markup=tg_ui.back_only_kb())

    @dp.message(Command("start", "help", "menu"))
    async def cmd_start(msg: Message) -> None:
        await show_main_menu(msg, settings)

    @dp.callback_query(F.data == "m:home")
    async def cb_home(cq: CallbackQuery) -> None:
        await cq.answer()
        await show_main_menu(cq.message, settings, edit=True)

    @dp.callback_query(F.data == "m:gen")
    async def cb_gen(cq: CallbackQuery) -> None:
        await cq.answer()
        await _start_generate(cq.message, cq.from_user.id)

    @dp.callback_query(F.data == "m:ren")
    async def cb_ren(cq: CallbackQuery) -> None:
        uid = cq.from_user.id
        text_block = ""
        rec = _last_record.get(uid)
        if rec:
            text_block = format_client_block(rec)
        elif uid in _drafts:
            text_block = _drafts[uid].text_block
        if not text_block.strip():
            await cq.answer()
            await cq.message.answer(
                f"{tg_ui.ce('warning')} Нет блока для отрисовки.\n"
                f"Сначала сгенерируйте запись или вставьте блок полей.",
                reply_markup=tg_ui.back_only_kb(),
            )
            return
        await cq.answer()
        await _prompt_render_options(cq.message, text_block)

    @dp.callback_query(F.data == "m:jobs")
    async def cb_jobs(cq: CallbackQuery) -> None:
        from photoshop_server import queue_jobs

        await cq.answer()
        rows = queue_jobs(limit=8)
        if not rows:
            await cq.message.answer(
                f"{tg_ui.ce('briefcase')} <b>Мои задачи</b>\nОчередь пуста.",
                reply_markup=tg_ui.jobs_kb(),
            )
            return
        lines = [f"{tg_ui.ce('briefcase')} <b>Последние задачи</b>"]
        for j in rows:
            st = j.get("status") or "—"
            jid = j.get("job_id") or "—"
            title = j.get("title") or ""
            extra = f" · {html.escape(title)}" if title else ""
            lines.append(f"• <code>{html.escape(str(jid)[:12])}</code> — {html.escape(st)}{extra}")
        await cq.message.answer("\n".join(lines), reply_markup=tg_ui.jobs_kb())

    @dp.callback_query(F.data == "m:port")
    async def cb_port(cq: CallbackQuery) -> None:
        await cq.answer()
        await cq.message.answer(
            f"{tg_ui.ce('user')} <b>Портрет</b>\n"
            f"Сгенерировать через OpenAI или пришлите фото с подписью <code>/portrait</code>.",
            reply_markup=tg_ui.portrait_kb(),
        )

    @dp.callback_query(F.data == "m:prof")
    async def cb_prof(cq: CallbackQuery) -> None:
        await cq.answer()
        profile = store.load(cq.from_user.id)
        if profile:
            body = profile_summary(profile)
        else:
            body = "Профиль не сохранён.\n" + ME_HINT
        await cq.message.answer(
            f"{tg_ui.ce('bookmark')} <b>Профиль</b>\n{body}",
            reply_markup=tg_ui.profile_kb(),
        )

    @dp.callback_query(F.data == "m:forget")
    async def cb_forget(cq: CallbackQuery) -> None:
        uid = cq.from_user.id
        store.delete(uid)
        _last_record.pop(uid, None)
        _drafts.pop(uid, None)
        await cq.answer("Профиль удалён")
        await cq.message.answer(
            f"{tg_ui.ce('ok')} Профиль сброшен.",
            reply_markup=tg_ui.back_only_kb(),
        )

    @dp.callback_query(F.data == "m:stat")
    async def cb_stat(cq: CallbackQuery) -> None:
        from admin_tools import format_status_text

        await cq.answer()
        await cq.message.answer(
            f"{tg_ui.ce('monitor')} <b>Статус</b>\n"
            f"<pre>{html.escape(format_status_text())}</pre>",
            reply_markup=tg_ui.status_kb(admin=settings.is_admin(cq.from_user.id)),
        )

    @dp.message(Command("forget", "clear"))
    async def cmd_forget(msg: Message) -> None:
        uid = msg.from_user.id
        if store.delete(uid):
            _last_record.pop(uid, None)
            _drafts.pop(uid, None)
            await msg.answer(f"{tg_ui.ce('ok')} Профиль удалён.", reply_markup=tg_ui.back_only_kb())
        else:
            await msg.answer("Профиль не был сохранён.", reply_markup=tg_ui.back_only_kb())

    @dp.message(Command("me"))
    async def cmd_me(msg: Message, command: CommandObject) -> None:
        uid = msg.from_user.id
        if not command.args:
            profile = store.load(uid)
            if profile:
                await msg.answer(
                    f"{tg_ui.ce('bookmark')} Сохранено:\n{profile_summary(profile)}",
                    reply_markup=region_kb(0),
                )
            else:
                await msg.answer(ME_HINT, reply_markup=tg_ui.back_only_kb())
            return
        try:
            ident, place = parse_me(command.args)
        except IdentityError as e:
            await msg.answer(
                f"{tg_ui.ce('stop')} {html.escape(str(e))}\n\n{ME_HINT}",
                reply_markup=tg_ui.back_only_kb(),
            )
            return
        store.save_identity(uid, ident, place)
        await msg.answer(
            f"{tg_ui.ce('ok')} <code>{html.escape(ident.surname)} {html.escape(ident.given)}</code>\n"
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
                await msg.answer(
                    f"{tg_ui.ce('warning')} Нет данных для отрисовки.",
                    reply_markup=tg_ui.back_only_kb(),
                )
                return
        try:
            parse_client_block(text_block)
        except TextParseError as e:
            await msg.answer(
                f"{tg_ui.ce('stop')} {html.escape(str(e))}",
                reply_markup=tg_ui.back_only_kb(),
            )
            return
        await _prompt_render_options(msg, text_block)

    @dp.message(Command("portrait"))
    async def cmd_portrait(msg: Message, command: CommandObject) -> None:
        uid = msg.from_user.id
        arg = (command.args or "").strip().lower()

        if arg == "generate":
            draft = _drafts.get(uid)
            if not draft:
                await msg.answer(
                    f"{tg_ui.ce('warning')} Сначала отправьте блок полей.",
                    reply_markup=tg_ui.back_only_kb(),
                )
                return
            await _generate_portrait_preview(msg, draft)
            return

        await msg.answer(
            f"{tg_ui.ce('user')} Отправьте фото с подписью <code>/portrait</code>.",
            reply_markup=tg_ui.portrait_kb(),
        )

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
            await msg.answer(
                f"{tg_ui.ce('stop')} {html.escape(result.message or 'Ошибка загрузки')}",
                reply_markup=tg_ui.back_only_kb(),
            )
            return
        draft = _drafts.get(msg.from_user.id) or RenderDraft(text_block="")
        draft.options.portrait_path = str(result.path)
        draft.options.generate_portrait = False
        _drafts[msg.from_user.id] = draft
        await msg.answer_photo(
            FSInputFile(str(result.path)),
            caption=f"{tg_ui.ce('ok')} Портрет: <code>{result.path.name}</code>",
        )
        if draft.text_block.strip():
            await msg.answer(
                tg_ui.render_prompt_text(html.escape(scene_summary(draft.options)), draft.options.background),
                reply_markup=render_options_kb(draft.options),
            )

    @dp.message(F.text.func(_looks_like_vu_block))
    async def on_vu_text_block(msg: Message) -> None:
        try:
            parse_client_block(msg.text or "")
        except TextParseError as e:
            await msg.answer(
                f"{tg_ui.ce('stop')} {html.escape(str(e))}",
                reply_markup=tg_ui.back_only_kb(),
            )
            return
        await _prompt_render_options(msg, msg.text or "")

    @dp.callback_query(F.data.startswith("rm:"))
    async def cb_mockup(cq: CallbackQuery) -> None:
        uid = cq.from_user.id
        draft = _drafts.get(uid)
        if not draft:
            await cq.answer("Сначала отправьте блок полей", show_alert=True)
            return
        draft.options.mockup = coerce_panel_mockup(cq.data.split(":", 1)[1])
        draft.options = normalize_options_for_mockup(draft.options)
        await cq.answer("Рука + фон")
        await cq.message.edit_reply_markup(reply_markup=render_options_kb(draft.options))

    @dp.callback_query(F.data.startswith("rb:"))
    async def cb_background(cq: CallbackQuery) -> None:
        uid = cq.from_user.id
        draft = _drafts.get(uid)
        if not draft:
            await cq.answer("Нет черновика", show_alert=True)
            return
        draft.options.mockup = coerce_panel_mockup(draft.options.mockup)
        draft.options.background = int(cq.data.split(":", 1)[1])
        await cq.answer(f"Фон #{draft.options.background}")
        summary = html.escape(scene_summary(draft.options))
        await cq.message.edit_text(
            tg_ui.render_prompt_text(summary, draft.options.background),
            reply_markup=render_options_kb(draft.options),
        )

    @dp.callback_query(F.data == "rp:ai")
    async def cb_portrait_ai(cq: CallbackQuery) -> None:
        uid = cq.from_user.id
        draft = _drafts.get(uid)
        if not draft:
            await cq.answer("Нет черновика — сначала сгенерируйте запись", show_alert=True)
            return
        draft.options.mockup = coerce_panel_mockup(draft.options.mockup)
        draft.options.generate_portrait = True
        draft.options.portrait_path = None
        await cq.answer("Генерирую портрет…")
        ok = await _generate_portrait_preview(cq.message, draft)
        if not ok:
            draft.options.generate_portrait = True
            await cq.message.answer(
                f"{tg_ui.ce('warning')} Портрет не готов сейчас. Нажмите «Отрисовать» — worker запросит ещё раз.",
                reply_markup=render_options_kb(draft.options),
            )

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
            await cq.answer("Сначала задайте профиль", show_alert=True)
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
            await cq.answer("Сначала задайте профиль", show_alert=True)
            return
        code = cq.data.split(":", 1)[1]
        if code != "any" and code not in REGIONS:
            await cq.answer("Неизвестный код", show_alert=True)
            return
        store.save_region(uid, None if code == "any" else code)
        profile = store.load(uid)
        await cq.answer("Генерирую…")
        rec = generate_record(profile, None if code == "any" else code)
        await cq.message.edit_text(
            f"{tg_ui.ce('ok')} Подразделение: <b>{html.escape(region_label(code))}</b>"
        )
        await deliver_record(cq.message, rec, region_label(code), uid)

    @dp.message(Command("status"))
    async def cmd_status(msg: Message) -> None:
        from admin_tools import format_status_text

        await msg.answer(
            f"{tg_ui.ce('monitor')} <b>Статус</b>\n<pre>{html.escape(format_status_text())}</pre>",
            reply_markup=tg_ui.status_kb(admin=settings.is_admin(msg.from_user.id)),
        )

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
            f"{tg_ui.ce('crown')} <b>Админ-панель</b>\n\n"
            f"<pre>{html.escape(format_status_text())}</pre>\n\n"
            f"Очередь: done={q['done']} failed={q['failed']}\n"
            f"Scene OK: {'да' if dash['scene_verify'].get('ok') else 'нет'}\n\n"
            f"Веб: <a href=\"{html.escape(web)}\">{html.escape(web)}</a>",
            reply_markup=tg_ui.status_kb(admin=True),
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


async def configure_bot_chrome(bot: Bot, settings: Settings) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Меню"),
            BotCommand(command="me", description="Профиль ФИО"),
            BotCommand(command="render", description="Отрисовать"),
            BotCommand(command="portrait", description="Портрет"),
            BotCommand(command="status", description="Статус очереди"),
        ]
    )
    app = tg_ui.panel_webapp(settings.web_base_url)
    if app:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Панель", web_app=app)
        )
        log.info("Mini App «Панель»: %s", settings.web_base_url)
    else:
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        log.warning(
            "WEB_BASE_URL=%s — не HTTPS. Кнопка Mini App «Панель» не ставится. "
            "Повесьте домен на 443 → 8080 и задайте WEB_BASE_URL=https://ваш.домен",
            settings.web_base_url,
        )


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
    await configure_bot_chrome(bot, settings)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
