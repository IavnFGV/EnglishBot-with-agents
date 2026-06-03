from __future__ import annotations

from io import BytesIO
from pathlib import Path

from aiogram import F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .bulk_edit import (
    BULK_EDIT_CALLBACK_PREFIX,
    BULK_EDIT_COMMAND_TOKEN,
    BulkEditSessionAlreadyActiveError,
    cancel_bulk_edit_session,
    complete_bulk_edit_session,
    create_bulk_edit_session,
    ensure_bulk_edit_session_ready_for_apply,
    ensure_bulk_edit_session_ready_for_upload,
    extend_bulk_edit_session,
    fail_bulk_edit_session,
    get_active_bulk_edit_session,
    get_bulk_edit_control_message_target,
    get_bulk_edit_session,
    get_bulk_edit_upload_dir,
    mark_bulk_edit_applying,
    mark_bulk_edit_uploaded,
    require_bulk_edit_initiator,
    restore_bulk_edit_uploaded,
    set_bulk_edit_control_message,
    set_bulk_edit_backup_path,
    update_bulk_edit_export_path,
)
from .command_registry import BULK_EDIT_COMMAND
from .db import save_user
from .families import get_user_family
from .i18n import translate_for_user
from .runtime import router
from .workbook_export import export_family_workbook
from .workbook_import import WorkbookImportValidationError, apply_family_workbook_import


@router.message(Command(BULK_EDIT_COMMAND.name))
async def start_bulk_edit(message: Message) -> None:
    await start_bulk_edit_flow(message)


async def start_bulk_edit_flow(message: Message) -> None:
    if message.from_user is None:
        return
    save_user(message.from_user)
    family = get_user_family(message.from_user.id)
    if family is None:
        await message.answer(
            translate_for_user(
                message.from_user.id,
                "family.command_family_only",
                command=BULK_EDIT_COMMAND.token,
            )
        )
        return

    active_session = get_active_bulk_edit_session()
    if active_session is not None:
        if int(active_session["started_by_user_id"]) != message.from_user.id:
            await message.answer(
                translate_for_user(
                    message.from_user.id,
                    "bulk_edit.gate.active_other",
                    command=BULK_EDIT_COMMAND_TOKEN,
                    remaining_time="",
                )
            )
            return
        await message.answer(
            translate_for_user(
                message.from_user.id,
                "bulk_edit.session.already_active",
            ),
            reply_markup=_build_controls_markup(active_session),
        )
        return

    try:
        session = create_bulk_edit_session(int(family["id"]), message.from_user.id)
    except BulkEditSessionAlreadyActiveError:
        await message.answer(
            translate_for_user(
                message.from_user.id,
                "bulk_edit.gate.active_other",
                command=BULK_EDIT_COMMAND_TOKEN,
                remaining_time="",
            )
        )
        return

    try:
        export_result = export_family_workbook(int(family["id"]))
        session = update_bulk_edit_export_path(int(session["id"]), str(export_result.file_path))
    except Exception:
        cancel_bulk_edit_session(int(session["id"]))
        raise

    await message.answer(
        translate_for_user(
            message.from_user.id,
            "bulk_edit.session.started",
        )
    )
    await message.answer_document(
        document=FSInputFile(export_result.file_path),
        caption=translate_for_user(
            message.from_user.id,
            "bulk_edit.export.ready",
            learning_item_count=export_result.learning_item_count,
            topic_count=export_result.topic_count,
        ),
    )
    await _upsert_control_message(
        message,
        session,
        "bulk_edit.session.await_upload",
    )


@router.message(F.document)
async def upload_bulk_edit_workbook(message: Message) -> None:
    if message.from_user is None or message.document is None:
        return
    session = get_active_bulk_edit_session()
    if session is None:
        return
    require_bulk_edit_initiator(session, message.from_user.id)
    ensure_bulk_edit_session_ready_for_upload(session)

    filename = (message.document.file_name or "").lower()
    if not filename.endswith(".xlsx"):
        await message.answer(
            translate_for_user(
                message.from_user.id,
                "bulk_edit.upload.xlsx_only",
            )
        )
        return

    buffer = BytesIO()
    await message.bot.download(message.document, destination=buffer)
    upload_path = get_bulk_edit_upload_dir() / f"bulk-edit-session-{int(session['id'])}.xlsx"
    upload_path.write_bytes(buffer.getvalue())
    session = mark_bulk_edit_uploaded(int(session["id"]), str(upload_path))
    await _upsert_control_message(
        message,
        session,
        "bulk_edit.upload.received",
    )


@router.callback_query(F.data.startswith(BULK_EDIT_CALLBACK_PREFIX))
async def handle_bulk_edit_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    session = get_active_bulk_edit_session()
    if session is None:
        await callback.answer(
            translate_for_user(callback.from_user.id, "bulk_edit.session.not_active"),
            show_alert=True,
        )
        return
    require_bulk_edit_initiator(session, callback.from_user.id)
    action = (callback.data or "").replace(BULK_EDIT_CALLBACK_PREFIX, "", 1)

    if action == "extend":
        session = extend_bulk_edit_session(int(session["id"]))
        await _upsert_control_message(callback.message, session, "bulk_edit.session.extended")
        await callback.answer()
        return

    if action == "cancel":
        session = cancel_bulk_edit_session(int(session["id"]))
        await _upsert_control_message(
            callback.message,
            session,
            "bulk_edit.session.cancelled",
            include_controls=False,
        )
        await callback.answer()
        return

    if action != "apply":
        await callback.answer()
        return

    ensure_bulk_edit_session_ready_for_apply(session)
    mark_bulk_edit_applying(int(session["id"]))
    try:
        summary = apply_family_workbook_import(
            Path(str(session["uploaded_file_path"])),
            int(session["family_id"]),
            int(session["started_by_user_id"]),
        )
    except WorkbookImportValidationError as exc:
        session = restore_bulk_edit_uploaded(int(session["id"]))
        await _upsert_control_message(
            callback.message,
            session,
            "bulk_edit.apply.validation_failed",
            error_lines="\n".join(exc.errors),
        )
        await callback.answer()
        return
    except Exception:
        session = fail_bulk_edit_session(int(session["id"]))
        await _upsert_control_message(
            callback.message,
            session,
            "bulk_edit.apply.failed",
            include_controls=False,
        )
        await callback.answer()
        raise

    set_bulk_edit_backup_path(int(session["id"]), str(summary.backup_file_path))
    session = complete_bulk_edit_session(int(session["id"]), str(summary.backup_file_path))
    await _upsert_control_message(
        callback.message,
        session,
        "bulk_edit.apply.completed",
        include_controls=False,
        created=summary.created,
        updated=summary.updated,
        archived=summary.archived,
        unchanged=summary.unchanged,
    )
    await callback.answer()


def _build_controls_markup(session) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if str(session["status"]) == "uploaded":
        rows.append(
            [
                InlineKeyboardButton(
                    text="Apply",
                    callback_data=f"{BULK_EDIT_CALLBACK_PREFIX}apply",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Extend 30m",
                callback_data=f"{BULK_EDIT_CALLBACK_PREFIX}extend",
            ),
            InlineKeyboardButton(
                text="Cancel",
                callback_data=f"{BULK_EDIT_CALLBACK_PREFIX}cancel",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _upsert_control_message(
    source_message: Message | None,
    session,
    text_key: str,
    *,
    include_controls: bool = True,
    **params: object,
) -> None:
    if source_message is None or source_message.from_user is None:
        return
    text = translate_for_user(source_message.from_user.id, text_key, **params)
    reply_markup = _build_controls_markup(session) if include_controls else None
    chat_id, message_id = get_bulk_edit_control_message_target(session)
    if (
        source_message.bot is not None
        and chat_id is not None
        and message_id is not None
    ):
        await source_message.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
        )
        return
    sent_message = await source_message.answer(text, reply_markup=reply_markup)
    target_chat = getattr(sent_message, "chat", None)
    target_message_id = getattr(sent_message, "message_id", None)
    if target_chat is None or getattr(target_chat, "id", None) is None or target_message_id is None:
        return
    set_bulk_edit_control_message(
        int(session["id"]),
        chat_id=int(target_chat.id),
        message_id=int(target_message_id),
    )
