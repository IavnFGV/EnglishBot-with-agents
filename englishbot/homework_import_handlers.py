"""Telegram flow for importing tutor homework: forward messages, pick a kind, get a draft."""

import asyncio
import contextlib
import logging

from aiogram import F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from .ai_extraction import KIND_WORDS, AIExtractionUnavailable, ExtractionSource, extract_items, is_ai_extraction_configured
from .config import get_mini_app_url
from .families import get_user_family
from .homework_sets import (
    KIND_MANUAL,
    HomeworkSetError,
    add_source,
    begin_processing,
    cancel_set,
    mark_failed,
    set_control_message,
    store_extraction,
    store_manual_draft,
    store_source_photos,
    summarize_sources,
)
from .i18n import translate_for_user
from .runtime import router


logger = logging.getLogger(__name__)

CALLBACK_PREFIX = "hwimport:"
_user_locks: dict[int, asyncio.Lock] = {}
_background_tasks: set[asyncio.Task] = set()


def build_draft_url(base_url: str, set_id: int) -> str:
    return f"{base_url.rstrip('/')}/editor?import={set_id}"


def _kind_keyboard(user_id: int, set_id: int) -> InlineKeyboardMarkup:
    rows = []
    if is_ai_extraction_configured():
        rows.append([InlineKeyboardButton(text=translate_for_user(user_id, "homework_import.kind.words"), callback_data=f"{CALLBACK_PREFIX}{KIND_WORDS}:{set_id}")])
    rows.append([InlineKeyboardButton(text=translate_for_user(user_id, "homework_import.kind.manual"), callback_data=f"{CALLBACK_PREFIX}{KIND_MANUAL}:{set_id}")])
    rows.append([InlineKeyboardButton(text=translate_for_user(user_id, "homework_import.cancel"), callback_data=f"{CALLBACK_PREFIX}cancel:{set_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _retry_keyboard(user_id: int, set_id: int, kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=translate_for_user(user_id, "homework_import.retry"), callback_data=f"{CALLBACK_PREFIX}{kind}:{set_id}")],
        [InlineKeyboardButton(text=translate_for_user(user_id, "homework_import.kind.manual"), callback_data=f"{CALLBACK_PREFIX}{KIND_MANUAL}:{set_id}")],
        [InlineKeyboardButton(text=translate_for_user(user_id, "homework_import.cancel"), callback_data=f"{CALLBACK_PREFIX}cancel:{set_id}")],
    ])


def _draft_keyboard(user_id: int, set_id: int) -> InlineKeyboardMarkup | None:
    base_url = get_mini_app_url()
    if base_url is None:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=translate_for_user(user_id, "homework_import.open_draft"),
        web_app=WebAppInfo(url=build_draft_url(base_url, set_id)),
    )]])


def is_homework_forward(message: Message) -> bool:
    return (
        getattr(message, "forward_origin", None) is not None
        and message.from_user is not None
        and getattr(message.chat, "type", None) == "private"
        and bool(message.text or message.caption or message.photo)
        and get_mini_app_url() is not None
        and get_user_family(message.from_user.id) is not None
    )


@router.message(is_homework_forward)
async def collect_homework_forward(message: Message) -> None:
    user_id = message.from_user.id
    lock = _user_locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        try:
            row = add_source(
                user_id,
                text=message.text or message.caption,
                photo_file_id=message.photo[-1].file_id if message.photo else None,
            )
        except HomeworkSetError as exc:
            logger.warning("Homework forward rejected: user=%s code=%s", user_id, exc.code)
            return
        if row["control_message_id"]:
            with contextlib.suppress(TelegramBadRequest):
                await message.bot.delete_message(chat_id=row["control_chat_id"], message_id=row["control_message_id"])
        counts = summarize_sources(row)
        control = await message.answer(
            translate_for_user(user_id, "homework_import.received", **counts),
            reply_markup=_kind_keyboard(user_id, int(row["id"])),
        )
        set_control_message(int(row["id"]), control.chat.id, control.message_id)


def _parse_callback(data: str) -> tuple[str, int] | None:
    try:
        action, raw_id = data.removeprefix(CALLBACK_PREFIX).split(":", 1)
        return action, int(raw_id)
    except ValueError:
        return None


@router.callback_query(F.data.startswith(CALLBACK_PREFIX))
async def handle_homework_import_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    parsed = _parse_callback(callback.data or "")
    if parsed is None or callback.from_user is None or callback.message is None:
        return
    action, set_id = parsed
    user_id = callback.from_user.id
    try:
        if action == "cancel":
            cancel_set(user_id, set_id)
            await callback.message.edit_text(translate_for_user(user_id, "homework_import.cancelled"))
            return
        sources = begin_processing(user_id, set_id, action)
    except HomeworkSetError:
        await callback.message.edit_text(translate_for_user(user_id, "homework_import.stale"))
        return
    processing_key = "homework_import.preparing" if action == KIND_MANUAL else "homework_import.processing"
    await callback.message.edit_text(translate_for_user(user_id, processing_key))
    task = asyncio.create_task(_process(callback.message, user_id, set_id, action, sources))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _download_sources(bot, sources: list[dict[str, str]]) -> list[ExtractionSource]:
    prepared = []
    for source in sources:
        image = None
        if source.get("photo_file_id"):
            buffer = await bot.download(source["photo_file_id"])
            image = buffer.read() if buffer is not None else None
        prepared.append(ExtractionSource(text=source.get("text"), image=image))
    return prepared


async def _process(message: Message, user_id: int, set_id: int, kind: str, sources: list[dict[str, str]]) -> None:
    try:
        prepared = await _download_sources(message.bot, sources)
        images = [source.image for source in prepared if source.image]
        photo_ids = await asyncio.to_thread(store_source_photos, set_id, images)
        # The model numbers pictures in sending order; a skipped unreadable photo breaks that mapping.
        picture_ids = photo_ids if len(photo_ids) == len(images) else None
        if kind == KIND_MANUAL:
            await asyncio.to_thread(store_manual_draft, set_id)
            await message.edit_text(translate_for_user(user_id, "homework_import.manual_done"), reply_markup=_draft_keyboard(user_id, set_id))
            return
        result = await asyncio.to_thread(extract_items, kind, prepared)
        counts = await asyncio.to_thread(store_extraction, set_id, result, picture_ids)
    except AIExtractionUnavailable as exc:
        mark_failed(set_id, str(exc))
        await message.edit_text(
            translate_for_user(user_id, "homework_import.failed"),
            reply_markup=_retry_keyboard(user_id, set_id, kind),
        )
        return
    except Exception as exc:
        logger.exception("Homework import failed: set=%s", set_id)
        mark_failed(set_id, repr(exc))
        await message.edit_text(
            translate_for_user(user_id, "homework_import.failed"),
            reply_markup=_retry_keyboard(user_id, set_id, kind),
        )
        return
    keyboard = _draft_keyboard(user_id, set_id)
    text = translate_for_user(user_id, "homework_import.done", **counts)
    if keyboard is None:
        text = f"{text}\n{translate_for_user(user_id, 'homework_import.no_editor')}"
    await message.edit_text(text, reply_markup=keyboard)
