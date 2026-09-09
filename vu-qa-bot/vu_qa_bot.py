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
from aiogram.types import ErrorEvent
from aiogram.filters import Command, CommandObject
from pathlib import Path

from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    ErrorEvent,
    FSInputFile,
    InlineKeyboardMarkup,
    MenuButtonDefault,
    MenuButtonWebApp,
    Message,
)

from config import Settings
from formatter import BANNER, format_client_block, format_debug_block, record_to_json, render_html
from mockup_registry import MOCKUPS, coerce_panel_mockup
from mockup_scene import normalize_options_for_mockup, scene_summary
from portrait_service import generate_ai_portrait, portrait_status_label, prepare_upload
from photoshop_text import substitute_text_queued, wait_substitute
from render_models import RenderOptions
from text_parser import TextParseError, parse_client_block
from text_realism import validate_block
import tg_ui
from vu_testdata import (
    BIRTH_PLACES,
    MOCKUP_CATEGORIES,
    REGIONS,
    IdentityError,
    LicenceRecord,
    make_valid,
    new_rng,
    parse_me,
    random_identity,
)

ME_HINT = tg_ui.generate_hint_text()

log = logging.getLogger("vu_qa_bot")
_last_record: dict[int, LicenceRecord] = {}
_awaiting_photo: set[int] = set()
_awaiting_render: set[int] = set()
_awaiting_identity: set[int] = set()
JOBS_PER_PAGE = 8
TG_FILE_MAX = 49 * 1024 * 1024
_DEFAULT_PORTRAIT_FIELDS = {
    "surname_ru": "ИВАНОВ",
    "given_ru": "ИВАН ИВАНОВИЧ",
    "birth_date": "15.06.1992",
    "gender": "M",
}


@dataclass
class RenderDraft:
    text_block: str
    options: RenderOptions = field(default_factory=RenderOptions)


_drafts: dict[int, RenderDraft] = {}


def _queue_snapshot() -> tuple[dict, bool]:
    from photoshop_server import get_server_status

    try:
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
    except Exception:
        log.exception("не удалось прочитать очередь")
        return ({"pending": 0, "processing": 0, "done": 0, "failed": 0}, False)


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


async def _generate_portrait_preview(msg: Message, draft: RenderDraft | None, uid: int) -> bool:
    fields = dict(_DEFAULT_PORTRAIT_FIELDS)
    if draft and (draft.text_block or "").strip():
        try:
            block = parse_client_block(draft.text_block)
            errors = validate_block(block)
            if not errors:
                from render_models import block_to_dict

                fields = block_to_dict(block)
        except TextParseError:
            pass

    await _send_html(msg, f"{tg_ui.ce('clock')} Генерирую ИИ-портрет по промпту… (10–60 сек)")
    result = await asyncio.to_thread(
        generate_ai_portrait,
        fields,
        force=True,
    )
    if not result.ok or not result.path:
        await _send_html(
            msg,
            f"{tg_ui.ce('stop')} {html.escape(result.message)}",
            reply_markup=tg_ui.back_only_kb(),
        )
        return False

    draft = draft or _drafts.get(uid) or RenderDraft(text_block="")
    draft.options.portrait_path = str(result.path)
    draft.options.generate_portrait = False
    _drafts[uid] = draft
    await _send_photo(
        msg,
        FSInputFile(str(result.path)),
        f"{tg_ui.ce('ok')} {html.escape(result.message)} ({html.escape(str(result.source or ''))})",
    )
    if (draft.text_block or "").strip():
        await _send_html(
            msg,
            tg_ui.render_prompt_text(scene_summary(draft.options), draft.options.background),
            reply_markup=render_options_kb(draft.options),
        )
    else:
        await _send_html(
            msg,
            f"{tg_ui.ce('ok')} Портрет готов. Можно вставить в отрисовку.",
            reply_markup=tg_ui.back_only_kb(),
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
        f"ДР {html.escape(ident.birth_date)} · пол {'жен' if ident.gender == 'F' else 'муж'}\n"
        f"Место рожд.: {html.escape(profile.birth_place or 'любое (случайно)')}\n"
        f"Подразделение: {html.escape(region_txt)}"
    )


def generate_record(region_code: str | None, profile=None) -> LicenceRecord:
    ident = profile.ident if profile else random_identity(new_rng())
    place = profile.birth_place if profile else None
    code = region_code if region_code and region_code != "any" else (profile.region if profile else None)
    if code == "any":
        code = None
    return make_valid(
        new_rng(),
        identity=ident,
        region_code=code,
        birth_place=place,
        valid_now=True,
        allowed_categories=MOCKUP_CATEGORIES,
    )


def region_label(code: str | None) -> str:
    if not code or code == "any":
        return "любое подразделение"
    return f"{code} {REGIONS.get(code, '')}"


def _looks_like_vu_block(text: str | None) -> bool:
    if not text:
        return False
    return text.lstrip().lower().startswith("1  фамилия")


def _set_draft(uid: int, text_block: str) -> RenderDraft:
    draft = _drafts.get(uid) or RenderDraft(text_block=text_block)
    draft.text_block = text_block
    _drafts[uid] = draft
    return draft


async def show_main_menu(msg: Message, settings: Settings, *, edit: bool = False) -> None:
    q, alive = _queue_snapshot()
    text = _html(tg_ui.main_menu_text(q, alive))
    kb = tg_ui.main_menu_kb(settings.web_base_url, settings.support_url)
    if edit:
        try:
            await msg.edit_text(text, reply_markup=kb)
            return
        except Exception:
            pass
    try:
        await msg.answer(text, reply_markup=kb)
        return
    except Exception as e:
        log.warning("меню с Mini App не ушло (%s)", e)
    try:
        await msg.answer(text, reply_markup=tg_ui.main_menu_kb("", settings.support_url))
        return
    except Exception as e:
        log.warning("меню с emoji не ушло (%s)", e)
    await msg.answer(
        tg_ui.strip_ce(text),
        reply_markup=tg_ui.main_menu_kb("", settings.support_url),
    )


def _html(text: str) -> str:
    return tg_ui.assert_telegram_html(text)


async def _send_html(msg: Message, text: str, **kwargs) -> None:
    payload = _html(text)
    try:
        await msg.answer(payload, **kwargs)
        return
    except Exception as e:
        log.warning("HTML send failed (%s), unicode fallback", e)
        await msg.answer(tg_ui.strip_ce(payload), **kwargs)


async def _send_photo(msg: Message, file: FSInputFile, caption: str, **kwargs) -> None:
    cap = _html(caption) if caption else None
    try:
        await msg.answer_photo(file, caption=cap, **kwargs)
        return
    except Exception as e:
        log.warning("photo caption html failed (%s), unicode fallback", e)
        await msg.answer_photo(file, caption=tg_ui.strip_ce(cap) if cap else None, **kwargs)


async def _edit_or_send(msg: Message, text: str, reply_markup=None) -> None:
    text = _html(text)
    try:
        await msg.edit_text(text, reply_markup=reply_markup)
        return
    except Exception:
        pass
    try:
        await msg.answer(text, reply_markup=reply_markup)
        return
    except Exception as e:
        log.warning("send failed (%s), retry without custom emoji html", e)
        await msg.answer(tg_ui.strip_ce(text), reply_markup=reply_markup)


def _job_task(job_id: str):
    from photoshop_server import queue_dir
    from render_queue import RenderQueue

    return RenderQueue(queue_dir()).get(job_id)


async def _show_jobs(msg: Message, uid: int, page: int = 0) -> None:
    from photoshop_server import queue_jobs

    rows = queue_jobs(limit=200)
    mine = [j for j in rows if not j.get("user_id") or j.get("user_id") == uid]
    pages = max(1, (len(mine) + JOBS_PER_PAGE - 1) // JOBS_PER_PAGE)
    page = max(0, min(int(page), pages - 1))
    chunk = mine[page * JOBS_PER_PAGE : (page + 1) * JOBS_PER_PAGE]
    text = tg_ui.jobs_screen_text(len(mine), page, pages)
    kb = tg_ui.jobs_list_kb(chunk, page=page, pages=pages) if mine else tg_ui.jobs_kb()
    await _edit_or_send(msg, text, kb)


async def _show_job(msg: Message, job_id: str) -> None:
    task = _job_task(job_id)
    if not task:
        await _edit_or_send(
            msg,
            f"{tg_ui.ce('stop')} Задача не найдена.",
            tg_ui.jobs_kb(),
        )
        return
    fields = task.fields or {}
    title = " ".join(
        str(x) for x in (fields.get("surname_ru"), fields.get("given_ru")) if x
    )
    jpg_ok = bool(task.jpg_path and Path(task.jpg_path).is_file())
    jpg_back_ok = bool(getattr(task, "jpg_back_path", None) and Path(task.jpg_back_path).is_file())
    psd_ok = bool(task.psd_path and Path(task.psd_path).is_file())
    text = tg_ui.job_detail_text(
        job_id=task.job_id,
        status=task.status,
        title=title,
        mockup=str(task.options.mockup),
        background=task.options.background,
        error=task.error,
        fields=fields,
    )
    await _edit_or_send(msg, text, tg_ui.job_detail_kb(
        task.job_id, has_jpg=jpg_ok, has_jpg_back=jpg_back_ok, has_psd=psd_ok
    ))


def _file_too_big(path: Path) -> bool:
    try:
        return path.stat().st_size > TG_FILE_MAX
    except OSError:
        return True


def _file_size_mb(path: Path) -> float:
    try:
        return path.stat().st_size / (1024 * 1024)
    except OSError:
        return 0.0


async def _send_output_document(msg: Message, path: Path, caption: str, *, web_base: str = "") -> bool:
    if not path.is_file():
        return False
    if _file_too_big(path):
        await _send_html(
            msg,
            f"{tg_ui.ce('warning')} <code>{html.escape(path.name)}</code> слишком большой "
            f"для Telegram ({_file_size_mb(path):.0f} МБ). Скачайте в панели.",
            reply_markup=tg_ui.after_render_kb(web_base),
        )
        return False
    cap = _html(caption)
    try:
        await msg.answer_document(FSInputFile(str(path)), caption=cap)
        return True
    except Exception as e:
        log.warning("document send failed (%s) file=%s size=%.1fMB", e, path.name, _file_size_mb(path))
        await _send_html(
            msg,
            f"{tg_ui.ce('warning')} Не удалось отправить <code>{html.escape(path.name)}</code> "
            f"в Telegram. Скачайте в панели.",
            reply_markup=tg_ui.after_render_kb(web_base),
        )
        return False


async def _send_job_file(msg: Message, job_id: str, kind: str, *, web_base: str = "") -> None:
    task = _job_task(job_id)
    raw = None
    if task:
        if kind == "jpg":
            raw = task.jpg_path
        elif kind == "jpg_back":
            raw = getattr(task, "jpg_back_path", None)
        else:
            raw = task.psd_path
    path = Path(raw) if raw else None
    if not path or not path.is_file():
        await _send_html(
            msg,
            f"{tg_ui.ce('stop')} Файл ещё не готов.",
            reply_markup=tg_ui.job_detail_kb(job_id, has_jpg=False, has_psd=False),
        )
        return
    caption = f"{tg_ui.ce('folder')} {html.escape(path.name)}"
    if kind in {"jpg", "jpg_back"} and not _file_too_big(path):
        await _send_photo(msg, FSInputFile(str(path)), caption)
        return
    await _send_output_document(msg, path, caption, web_base=web_base)


async def _prompt_render_options(msg: Message, text_block: str, uid: int) -> None:
    draft = _set_draft(uid, text_block)
    draft.options.mockup = coerce_panel_mockup(draft.options.mockup)
    summary = scene_summary(draft.options)
    await _send_html(
        msg,
        tg_ui.render_prompt_text(summary, draft.options.background),
        reply_markup=render_options_kb(draft.options),
    )


async def _enqueue_and_wait(
    msg: Message,
    draft: RenderDraft,
    *,
    chat_id: int,
    user_id: int,
    web_base: str = "",
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
        await _send_html(
            msg,
            f"{tg_ui.ce('stop')} {html.escape(queued.message)}",
            reply_markup=tg_ui.back_only_kb(),
        )
        return

    summary = scene_summary(draft.options)
    portrait_line = ""
    if draft.options.portrait_path or draft.options.generate_portrait:
        portrait_line = f"\nПортрет: {html.escape(portrait_status_label(draft.options))}"
    await _send_html(
        msg,
        f"{tg_ui.ce('clock')} Генерирую… (job <code>{html.escape(str(queued.job_id))}</code>)\n"
        f"{html.escape(summary)}"
        f"{portrait_line}\n"
        f"Обычно 5–60 сек.",
    )

    done = await asyncio.to_thread(wait_substitute, queued.job_id, 900, 2.0)
    if not done.ok:
        await _send_html(
            msg,
            f"{tg_ui.ce('stop')} {html.escape(done.message)}",
            reply_markup=tg_ui.back_only_kb(),
        )
        return

    jpg = done.jpg_path
    psd = done.psd_path

    if jpg and jpg.is_file():
        await _send_photo(msg, FSInputFile(str(jpg)), f"{tg_ui.ce('ok')} JPG лицевая")
    jpg_back = getattr(done, "jpg_back_path", None)
    if jpg_back and jpg_back.is_file():
        await _send_photo(msg, FSInputFile(str(jpg_back)), f"{tg_ui.ce('ok')} JPG оборот")
    if psd and psd.is_file():
        await _send_output_document(
            msg,
            psd,
            f"{tg_ui.ce('folder')} PSD (редактируемый)",
            web_base=web_base,
        )
    await _send_html(msg, f"{tg_ui.ce('ok')} Готово", reply_markup=tg_ui.after_render_kb(web_base))


async def deliver_record(msg: Message, rec: LicenceRecord, where: str, user_id: int) -> None:
    _last_record[user_id] = rec
    client_text = format_client_block(rec)
    debug_text = format_debug_block(rec)
    await _send_html(
        msg,
        f"{tg_ui.ce('ok')} Подразделение: <b>{html.escape(where)}</b>\n\n"
        f"{render_html(rec, debug=True)}",
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
    await _send_html(
        msg,
        f"{tg_ui.ce('ok')} Запись готова. Можно отрисовать мокап.",
        reply_markup=tg_ui.after_generate_kb(),
    )


class AllowedUsers(BaseMiddleware):
    def __init__(self, allowed: frozenset[int]):
        self.allowed = allowed

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        uid = getattr(user, "id", None)
        if user is None or uid not in self.allowed:
            log.warning("ignore user_id=%s (нет в ALLOWED_USERS)", uid)
            return None
        log.info("update user_id=%s", uid)
        return await handler(event, data)


def create_dispatcher(settings: Settings) -> Dispatcher:
    from profiles import ProfileStore

    store = ProfileStore(settings.profiles_path)
    dp = Dispatcher()

    @dp.error()
    async def on_error(event: ErrorEvent) -> bool:
        log.exception("handler failed: %s", event.exception)
        upd = event.update
        msg = upd.message or (upd.callback_query.message if upd.callback_query else None)
        if msg is not None:
            try:
                await msg.answer("Не удалось ответить. Смотрите лог бота.")
            except Exception:
                pass
        return True

    async def _start_generate(msg: Message, uid: int) -> None:
        _awaiting_identity.add(uid)
        await _send_html(msg, tg_ui.generate_hint_text(), reply_markup=tg_ui.back_only_kb())

    @dp.message(Command("start", "help", "menu"))
    async def cmd_start(msg: Message) -> None:
        log.info("/start chat=%s", msg.chat.id)
        if msg.from_user:
            store.touch(
                msg.from_user.id,
                username=msg.from_user.username,
                first_name=msg.from_user.first_name,
            )
        await show_main_menu(msg, settings)

    @dp.callback_query(F.data == "m:home")
    async def cb_home(cq: CallbackQuery) -> None:
        uid = cq.from_user.id
        _awaiting_identity.discard(uid)
        _awaiting_render.discard(uid)
        _awaiting_photo.discard(uid)
        await cq.answer()
        await show_main_menu(cq.message, settings, edit=True)

    @dp.callback_query(F.data == "m:gen")
    async def cb_gen(cq: CallbackQuery) -> None:
        await cq.answer()
        await _start_generate(cq.message, cq.from_user.id)

    @dp.callback_query(F.data == "m:ren")
    async def cb_ren(cq: CallbackQuery) -> None:
        uid = cq.from_user.id
        _awaiting_render.add(uid)
        text_block = ""
        rec = _last_record.get(uid)
        if rec:
            text_block = format_client_block(rec)
        elif uid in _drafts:
            text_block = _drafts[uid].text_block
        if text_block.strip():
            await cq.answer()
            await _prompt_render_options(cq.message, text_block, uid)
            await _send_html(
                cq.message,
                f"{tg_ui.ce('info')} Можно прислать другой текстовый блок — он заменит текущий.",
                reply_markup=tg_ui.back_only_kb(),
            )
            return
        await cq.answer()
        await _send_html(
            cq.message,
            f"{tg_ui.ce('layers')} <b>Отрисовка</b>\n"
            "Пришлите сгенерированный текстовый блок полей (сообщением или файлом .txt).",
            reply_markup=tg_ui.back_only_kb(),
        )

    @dp.callback_query(F.data == "m:jobs")
    async def cb_jobs(cq: CallbackQuery) -> None:
        await cq.answer()
        await _show_jobs(cq.message, cq.from_user.id, 0)

    @dp.callback_query(F.data.startswith("jl:"))
    async def cb_jobs_page(cq: CallbackQuery) -> None:
        arg = cq.data.split(":", 1)[1]
        await cq.answer()
        if arg == "noop":
            return
        await _show_jobs(cq.message, cq.from_user.id, int(arg))

    @dp.callback_query(F.data.startswith("jo:"))
    async def cb_job_open(cq: CallbackQuery) -> None:
        await cq.answer()
        await _show_job(cq.message, cq.data.split(":", 1)[1])

    @dp.callback_query(F.data.startswith("jj:"))
    async def cb_job_jpg(cq: CallbackQuery) -> None:
        await cq.answer("JPG")
        await _send_job_file(
            cq.message, cq.data.split(":", 1)[1], "jpg", web_base=settings.web_base_url
        )

    @dp.callback_query(F.data.startswith("jb:"))
    async def cb_job_jpg_back(cq: CallbackQuery) -> None:
        await cq.answer("Оборот")
        await _send_job_file(
            cq.message, cq.data.split(":", 1)[1], "jpg_back", web_base=settings.web_base_url
        )

    @dp.callback_query(F.data.startswith("jp:"))
    async def cb_job_psd(cq: CallbackQuery) -> None:
        await cq.answer("PSD")
        await _send_job_file(
            cq.message, cq.data.split(":", 1)[1], "psd", web_base=settings.web_base_url
        )

    @dp.callback_query(F.data == "m:port")
    async def cb_port(cq: CallbackQuery) -> None:
        _awaiting_photo.add(cq.from_user.id)
        await cq.answer()
        await _send_html(
            cq.message,
            f"{tg_ui.ce('user')} <b>Портрет</b>\n"
            "Сгенерирую фото на документ по промпту, либо пришлите своё — ИИ вырежет фон.",
            reply_markup=tg_ui.portrait_kb(),
        )

    @dp.callback_query(F.data == "m:prof")
    async def cb_prof(cq: CallbackQuery) -> None:
        uid = cq.from_user.id
        store.touch(
            uid,
            username=cq.from_user.username,
            first_name=cq.from_user.first_name,
        )
        st = store.stats(uid)
        from photoshop_server import queue_jobs

        jobs = [j for j in queue_jobs(limit=200) if j.get("user_id") == uid]
        await cq.answer()
        await _send_html(
            cq.message,
            tg_ui.profile_screen(
                user_id=uid,
                username=st["username"] or (cq.from_user.username or ""),
                first_name=st["first_name"] or (cq.from_user.first_name or ""),
                generations=st["generations"],
                renders=st["renders"],
                jobs_done=sum(1 for j in jobs if j.get("status") == "done"),
                jobs_failed=sum(1 for j in jobs if j.get("status") == "failed"),
                jobs_pending=sum(1 for j in jobs if j.get("status") in {"pending", "processing"}),
            ),
            reply_markup=tg_ui.profile_kb(),
        )

    @dp.callback_query(F.data == "m:forget")
    async def cb_forget(cq: CallbackQuery) -> None:
        uid = cq.from_user.id
        store.delete(uid)
        _last_record.pop(uid, None)
        _drafts.pop(uid, None)
        await cq.answer("Профиль удалён")
        await _send_html(
            cq.message,
            f"{tg_ui.ce('ok')} Профиль сброшен.",
            reply_markup=tg_ui.back_only_kb(),
        )

    @dp.callback_query(F.data == "m:stat")
    async def cb_stat(cq: CallbackQuery) -> None:
        from admin_tools import format_status_html

        await cq.answer()
        await _send_html(
            cq.message,
            format_status_html(settings.web_base_url),
            reply_markup=tg_ui.status_kb(admin=settings.is_admin(cq.from_user.id)),
        )

    @dp.message(Command("forget", "clear"))
    async def cmd_forget(msg: Message) -> None:
        uid = msg.from_user.id
        if store.delete(uid):
            _last_record.pop(uid, None)
            _drafts.pop(uid, None)
            await _send_html(msg, f"{tg_ui.ce('ok')} Профиль удалён.", reply_markup=tg_ui.back_only_kb())
        else:
            await msg.answer("Профиль не был сохранён.", reply_markup=tg_ui.back_only_kb())

    @dp.message(Command("me"))
    async def cmd_me(msg: Message, command: CommandObject) -> None:
        uid = msg.from_user.id
        if not command.args:
            profile = store.load(uid)
            if profile:
                await _send_html(
                    msg,
                    f"{tg_ui.ce('bookmark')} Сохранено:\n{profile_summary(profile)}",
                    reply_markup=region_kb(0),
                )
            else:
                await _send_html(msg, ME_HINT, reply_markup=tg_ui.back_only_kb())
            return
        try:
            ident, place = parse_me(command.args)
        except IdentityError as e:
            await _send_html(
                msg,
                f"{tg_ui.ce('stop')} {html.escape(str(e))}\n\n{ME_HINT}",
                reply_markup=tg_ui.back_only_kb(),
            )
            return
        store.save_identity(uid, ident, place)
        await _send_html(
            msg,
            f"{tg_ui.ce('ok')} <code>{html.escape(ident.surname)} {html.escape(ident.given)}</code>\n"
            f"ДР {html.escape(ident.birth_date)}",
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
                await _send_html(
                    msg,
                    f"{tg_ui.ce('warning')} Нет данных для отрисовки.",
                    reply_markup=tg_ui.back_only_kb(),
                )
                return
        try:
            parse_client_block(text_block)
        except TextParseError as e:
            await _send_html(
                msg,
                f"{tg_ui.ce('stop')} {html.escape(str(e))}",
                reply_markup=tg_ui.back_only_kb(),
            )
            return
        await _prompt_render_options(msg, text_block, uid)

    @dp.message(Command("portrait"))
    async def cmd_portrait(msg: Message, command: CommandObject) -> None:
        uid = msg.from_user.id
        arg = (command.args or "").strip().lower()

        if arg == "generate":
            await _generate_portrait_preview(msg, _drafts.get(uid), uid)
            return

        await _send_html(
            msg,
            f"{tg_ui.ce('user')} Отправьте фото — ИИ сделает портрет на документ и вырежет фон.",
            reply_markup=tg_ui.portrait_kb(),
        )

    @dp.message(F.photo)
    async def on_photo(msg: Message) -> None:
        if not msg.photo:
            return
        uid = msg.from_user.id
        _awaiting_photo.discard(uid)
        photo = msg.photo[-1]
        file = await msg.bot.get_file(photo.file_id)
        from io import BytesIO

        buf = BytesIO()
        await msg.bot.download_file(file.file_path, buf)
        await _send_html(msg, f"{tg_ui.ce('clock')} Прогоняю фото через ИИ (вырезаю фон)…")
        draft = _drafts.get(uid)
        fields = dict(_DEFAULT_PORTRAIT_FIELDS)
        if draft and (draft.text_block or "").strip():
            try:
                block = parse_client_block(draft.text_block)
                if not validate_block(block):
                    from render_models import block_to_dict

                    # validate_block возвращает список ошибок: пустой = блок валиден
                    fields = block_to_dict(block)
            except TextParseError:
                pass
        result = await asyncio.to_thread(
            prepare_upload,
            buf.getvalue(),
            msg.from_user.id,
            fields=fields,
        )
        if not result.ok or not result.path:
            await _send_html(
                msg,
                f"{tg_ui.ce('stop')} {html.escape(result.message or 'Ошибка загрузки')}",
                reply_markup=tg_ui.back_only_kb(),
            )
            return
        draft = _drafts.get(msg.from_user.id) or RenderDraft(text_block="")
        draft.options.portrait_path = str(result.path)
        draft.options.generate_portrait = False
        _drafts[msg.from_user.id] = draft
        await _send_photo(
            msg,
            FSInputFile(str(result.path)),
            f"{tg_ui.ce('ok')} {html.escape(result.message or 'Портрет готов')}",
        )
        if draft.text_block.strip():
            await _send_html(
                msg,
                tg_ui.render_prompt_text(scene_summary(draft.options), draft.options.background),
                reply_markup=render_options_kb(draft.options),
            )

    @dp.message(F.text.func(_looks_like_vu_block))
    async def on_vu_text_block(msg: Message) -> None:
        try:
            parse_client_block(msg.text or "")
        except TextParseError as e:
            await _send_html(
                msg,
                f"{tg_ui.ce('stop')} {html.escape(str(e))}",
                reply_markup=tg_ui.back_only_kb(),
            )
            return
        await _prompt_render_options(msg, msg.text or "", msg.from_user.id)
        _awaiting_render.discard(msg.from_user.id)

    @dp.message(F.document)
    async def on_document_block(msg: Message) -> None:
        doc = msg.document
        if not doc or not (doc.file_name or "").lower().endswith(".txt"):
            return
        file = await msg.bot.get_file(doc.file_id)
        from io import BytesIO

        buf = BytesIO()
        await msg.bot.download_file(file.file_path, buf)
        text = buf.getvalue().decode("utf-8", errors="replace")
        if not _looks_like_vu_block(text):
            if msg.from_user.id in _awaiting_render:
                await _send_html(
                    msg,
                    f"{tg_ui.ce('stop')} В файле нет блока полей.",
                    reply_markup=tg_ui.back_only_kb(),
                )
            return
        try:
            parse_client_block(text)
        except TextParseError as e:
            await _send_html(
                msg,
                f"{tg_ui.ce('stop')} {html.escape(str(e))}",
                reply_markup=tg_ui.back_only_kb(),
            )
            return
        _awaiting_render.discard(msg.from_user.id)
        await _prompt_render_options(msg, text, msg.from_user.id)

    @dp.message(F.text)
    async def on_plain_text(msg: Message) -> None:
        uid = msg.from_user.id
        text = (msg.text or "").strip()
        if not text or text.startswith("/"):
            return
        if uid in _awaiting_identity:
            try:
                ident, place = parse_me(text)
            except IdentityError as e:
                await _send_html(
                    msg,
                    f"{tg_ui.ce('stop')} {html.escape(str(e))}\n\n{tg_ui.generate_hint_text()}",
                    reply_markup=tg_ui.back_only_kb(),
                )
                return
            store.save_identity(uid, ident, place)
            _awaiting_identity.discard(uid)
            extra = f"\n{html.escape(place)}" if place else ""
            await _send_html(
                msg,
                f"{tg_ui.ce('ok')} {html.escape(ident.surname)} {html.escape(ident.given)}\n"
                f"ДР {html.escape(ident.birth_date)}{extra}",
            )
            if not place:
                await msg.answer("Место рождения:", reply_markup=birthplace_kb(0))
            else:
                await msg.answer("Выберите подразделение:", reply_markup=region_kb(0))
            return
        if uid in _awaiting_render:
            try:
                parse_client_block(text)
            except TextParseError as e:
                await _send_html(
                    msg,
                    f"{tg_ui.ce('stop')} {html.escape(str(e))}\nПришлите блок полей.",
                    reply_markup=tg_ui.back_only_kb(),
                )
                return
            _awaiting_render.discard(uid)
            await _prompt_render_options(msg, text, uid)

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
        summary = scene_summary(draft.options)
        await _edit_or_send(
            cq.message,
            tg_ui.render_prompt_text(summary, draft.options.background),
            render_options_kb(draft.options),
        )

    @dp.callback_query(F.data == "rp:ai")
    async def cb_portrait_ai(cq: CallbackQuery) -> None:
        uid = cq.from_user.id
        draft = _drafts.get(uid)
        if draft:
            draft.options.mockup = coerce_panel_mockup(draft.options.mockup)
            draft.options.generate_portrait = True
            draft.options.portrait_path = None
        await cq.answer("Генерирую портрет…")
        ok = await _generate_portrait_preview(cq.message, draft, uid)
        if not ok:
            await _send_html(
                cq.message,
                f"{tg_ui.ce('warning')} Провайдер не ответил. Проверьте OPENAI_API_KEY.",
                reply_markup=tg_ui.portrait_kb(),
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
        store.bump(uid, "renders")
        await _enqueue_and_wait(
            cq.message,
            draft,
            chat_id=cq.message.chat.id,
            user_id=uid,
            web_base=settings.web_base_url,
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
        code = cq.data.split(":", 1)[1]
        if code != "any" and code not in REGIONS:
            await cq.answer("Неизвестный код", show_alert=True)
            return
        profile = store.load(uid)
        if not profile:
            _awaiting_identity.add(uid)
            await cq.answer("Сначала ФИО, дата и место", show_alert=True)
            await _send_html(cq.message, tg_ui.generate_hint_text(), reply_markup=tg_ui.back_only_kb())
            return
        await cq.answer("Генерирую…")
        rec = generate_record(None if code == "any" else code, profile)
        store.bump(uid, "generations")
        try:
            await cq.message.edit_text(
                _html(f"{tg_ui.ce('ok')} Подразделение: <b>{html.escape(region_label(code))}</b>")
            )
        except Exception:
            pass
        await deliver_record(cq.message, rec, region_label(code), uid)

    @dp.message(Command("status"))
    async def cmd_status(msg: Message) -> None:
        from admin_tools import format_status_html

        await _send_html(
            msg,
            format_status_html(settings.web_base_url),
            reply_markup=tg_ui.status_kb(admin=settings.is_admin(msg.from_user.id)),
        )

    @dp.message(Command("admin"))
    async def cmd_admin(msg: Message) -> None:
        if not settings.is_admin(msg.from_user.id):
            await msg.answer("Нет доступа.")
            return
        from admin_tools import format_status_html

        await _send_html(
            msg,
            format_status_html(settings.web_base_url),
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
    await bot.delete_my_commands()
    app = tg_ui.panel_webapp(settings.web_base_url)
    if app:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Панель", web_app=app)
        )
        log.info("Mini App «Панель»: %s", settings.web_base_url)
    else:
        await bot.set_chat_menu_button(menu_button=MenuButtonDefault())
        log.warning(
            "WEB_BASE_URL=%s — Mini App «Панель» не ставится (нужен живой https://домен). "
            "Polling бота от этого не зависит.",
            settings.web_base_url,
        )


async def run() -> None:
    print("VU bot starting...", flush=True)
    settings = Settings.load()
    settings.require_bot()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
        force=True,
    )
    print(
        f"allowed={sorted(settings.allowed_users)} web={settings.web_base_url}",
        flush=True,
    )
    dp = create_dispatcher(settings)
    guard = AllowedUsers(settings.allowed_users)
    dp.message.middleware(guard)
    dp.callback_query.middleware(guard)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    print("Telegram getMe...", flush=True)
    me = await bot.get_me()
    log.info("бот @%s, queue=%s", me.username, settings.render_queue_dir)
    try:
        await configure_bot_chrome(bot, settings)
    except Exception:
        log.exception("меню Telegram не настроено — polling всё равно стартует")
    info = await bot.get_webhook_info()
    if info.url:
        log.warning("снял webhook %s (иначе getUpdates пустой)", info.url)
    await bot.delete_webhook(drop_pending_updates=True)
    print(f"polling @{me.username} — жду сообщения", flush=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
