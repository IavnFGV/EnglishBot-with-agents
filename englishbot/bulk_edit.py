from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from .db import DB_PATH, get_connection, utc_now
from .i18n import translate_for_user


logger = logging.getLogger(__name__)

SESSION_DURATION_MINUTES = 30
REMINDER_10_MINUTES = 10
REMINDER_3_MINUTES = 3
ACTIVE_SESSION_STATUSES = ("active", "uploaded", "applying")
BULK_EDIT_CALLBACK_PREFIX = "bulk_edit:"
BULK_EDIT_COMMAND_TOKEN = "/bulk_edit"


class BulkEditError(RuntimeError):
    pass


class BulkEditSessionAlreadyActiveError(BulkEditError):
    pass


class BulkEditSessionAccessError(BulkEditError):
    pass


class BulkEditSessionStateError(BulkEditError):
    pass


@dataclass(frozen=True)
class BulkEditGateDecision:
    session: sqlite3.Row
    allowed: bool
    responder_user_id: int
    message_key: str


def get_bulk_edit_runtime_dir() -> Path:
    runtime_dir = Path(DB_PATH).resolve().parent / "bulk-edit"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir


def get_bulk_edit_export_dir() -> Path:
    export_dir = get_bulk_edit_runtime_dir() / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir


def get_bulk_edit_upload_dir() -> Path:
    upload_dir = get_bulk_edit_runtime_dir() / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def get_backup_dir() -> Path:
    raw_dir = os.getenv("ENGLISHBOT_BACKUP_DIR", "./backups").strip() or "./backups"
    backup_dir = Path(raw_dir)
    if not backup_dir.is_absolute():
        backup_dir = Path.cwd() / backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def get_active_bulk_edit_session() -> sqlite3.Row | None:
    expire_active_bulk_edit_session_if_needed()
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT *
            FROM bulk_edit_sessions
            WHERE status IN (?, ?, ?)
            ORDER BY id DESC
            LIMIT 1
            """,
            ACTIVE_SESSION_STATUSES,
        ).fetchone()


def get_bulk_edit_session(session_id: int) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT *
            FROM bulk_edit_sessions
            WHERE id = ?
            """,
            (session_id,),
        ).fetchone()


def create_bulk_edit_session(family_id: int, started_by_user_id: int) -> sqlite3.Row:
    active_session = get_active_bulk_edit_session()
    if active_session is not None:
        raise BulkEditSessionAlreadyActiveError("another bulk edit session is already active")
    now = _utcnow()
    expires_at = now + timedelta(minutes=SESSION_DURATION_MINUTES)
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO bulk_edit_sessions (
                family_id,
                started_by_user_id,
                status,
                export_file_path,
                uploaded_file_path,
                backup_file_path,
                expires_at,
                reminded_10m_at,
                reminded_3m_at,
                expired_notified_at,
                created_at,
                updated_at
            )
            VALUES (?, ?, 'active', NULL, NULL, NULL, ?, NULL, NULL, NULL, ?, ?)
            """,
            (
                family_id,
                started_by_user_id,
                _format_dt(expires_at),
                utc_now(),
                utc_now(),
            ),
        )
        session_id = int(cursor.lastrowid)
    session = get_bulk_edit_session(session_id)
    assert session is not None
    return session


def update_bulk_edit_export_path(session_id: int, export_file_path: str) -> sqlite3.Row:
    return _update_session(
        session_id,
        """
        UPDATE bulk_edit_sessions
        SET export_file_path = ?, updated_at = ?
        WHERE id = ?
        """,
        (export_file_path, utc_now(), session_id),
    )


def mark_bulk_edit_uploaded(session_id: int, uploaded_file_path: str) -> sqlite3.Row:
    return _update_session(
        session_id,
        """
        UPDATE bulk_edit_sessions
        SET status = 'uploaded',
            uploaded_file_path = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (uploaded_file_path, utc_now(), session_id),
    )


def mark_bulk_edit_applying(session_id: int) -> sqlite3.Row:
    return _update_session(
        session_id,
        """
        UPDATE bulk_edit_sessions
        SET status = 'applying',
            updated_at = ?
        WHERE id = ?
        """,
        (utc_now(), session_id),
    )


def restore_bulk_edit_uploaded(session_id: int) -> sqlite3.Row:
    return _update_session(
        session_id,
        """
        UPDATE bulk_edit_sessions
        SET status = 'uploaded',
            updated_at = ?
        WHERE id = ?
        """,
        (utc_now(), session_id),
    )


def complete_bulk_edit_session(session_id: int, backup_file_path: str | None = None) -> sqlite3.Row:
    session = _update_session(
        session_id,
        """
        UPDATE bulk_edit_sessions
        SET status = 'completed',
            backup_file_path = COALESCE(?, backup_file_path),
            expires_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            backup_file_path,
            _format_dt(_utcnow()),
            utc_now(),
            session_id,
        ),
    )
    _cleanup_session_temp_files(session)
    return session


def cancel_bulk_edit_session(session_id: int) -> sqlite3.Row:
    session = _update_session(
        session_id,
        """
        UPDATE bulk_edit_sessions
        SET status = 'cancelled',
            expires_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            _format_dt(_utcnow()),
            utc_now(),
            session_id,
        ),
    )
    _cleanup_session_temp_files(session)
    return session


def fail_bulk_edit_session(session_id: int) -> sqlite3.Row:
    session = _update_session(
        session_id,
        """
        UPDATE bulk_edit_sessions
        SET status = 'failed',
            expires_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            _format_dt(_utcnow()),
            utc_now(),
            session_id,
        ),
    )
    _cleanup_session_temp_files(session)
    return session


def extend_bulk_edit_session(session_id: int, *, minutes: int = SESSION_DURATION_MINUTES) -> sqlite3.Row:
    session = get_bulk_edit_session(session_id)
    if session is None:
        raise BulkEditSessionStateError("session not found")
    expires_at = max(_parse_dt(session["expires_at"]), _utcnow()) + timedelta(minutes=minutes)
    return _update_session(
        session_id,
        """
        UPDATE bulk_edit_sessions
        SET expires_at = ?,
            reminded_10m_at = NULL,
            reminded_3m_at = NULL,
            updated_at = ?
        WHERE id = ?
        """,
        (_format_dt(expires_at), utc_now(), session_id),
    )


def set_bulk_edit_backup_path(session_id: int, backup_file_path: str) -> sqlite3.Row:
    return _update_session(
        session_id,
        """
        UPDATE bulk_edit_sessions
        SET backup_file_path = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (backup_file_path, utc_now(), session_id),
    )


def set_bulk_edit_control_message(
    session_id: int,
    *,
    chat_id: int | None,
    message_id: int | None,
) -> sqlite3.Row:
    return _update_session(
        session_id,
        """
        UPDATE bulk_edit_sessions
        SET control_message_chat_id = ?,
            control_message_message_id = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (chat_id, message_id, utc_now(), session_id),
    )


def create_bulk_edit_backup(*, family_id: int, user_id: int) -> Path:
    timestamp = _utcnow().strftime("%Y-%m-%dT%H-%M-%S")
    backup_path = get_backup_dir() / (
        f"before-bulk-edit__family-{family_id}__user-{user_id}__{timestamp}.sqlite3"
    )
    source = sqlite3.connect(DB_PATH)
    try:
        destination = sqlite3.connect(backup_path)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
    _prune_bulk_edit_backups()
    return backup_path


def expire_active_bulk_edit_session_if_needed() -> sqlite3.Row | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM bulk_edit_sessions
            WHERE status IN (?, ?, ?)
            ORDER BY id DESC
            LIMIT 1
            """,
            ACTIVE_SESSION_STATUSES,
        ).fetchone()
        if row is None:
            return None
        if _parse_dt(row["expires_at"]) > _utcnow():
            return None
        connection.execute(
            """
            UPDATE bulk_edit_sessions
            SET status = 'expired',
                updated_at = ?
            WHERE id = ?
            """,
            (utc_now(), int(row["id"])),
        )
    expired = get_bulk_edit_session(int(row["id"]))
    if expired is not None:
        _cleanup_session_temp_files(expired)
    return expired


def build_bulk_edit_gate_decision(update: Update) -> BulkEditGateDecision | None:
    session = get_active_bulk_edit_session()
    if session is None:
        return None
    user_id = _extract_user_id(update)
    if user_id is None:
        return BulkEditGateDecision(
            session=session,
            allowed=False,
            responder_user_id=int(session["started_by_user_id"]),
            message_key="bulk_edit.gate.active_other",
        )
    is_initiator = user_id == int(session["started_by_user_id"])
    if is_initiator and _is_allowed_initiator_update(update):
        return BulkEditGateDecision(
            session=session,
            allowed=True,
            responder_user_id=user_id,
            message_key="bulk_edit.gate.active_owner",
        )
    return BulkEditGateDecision(
        session=session,
        allowed=False,
        responder_user_id=user_id,
        message_key="bulk_edit.gate.active_owner" if is_initiator else "bulk_edit.gate.active_other",
    )


class BulkEditGateMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        if not isinstance(event, Update):
            return await handler(event, data)
        decision = build_bulk_edit_gate_decision(event)
        if decision is None or decision.allowed:
            return await handler(event, data)
        await _respond_to_blocked_update(event, decision)
        return None


async def process_due_bulk_edit_notifications(bot) -> None:
    session = expire_active_bulk_edit_session_if_needed()
    if session is not None and session["expired_notified_at"] is None:
        await _notify_and_mark(
            bot,
            int(session["id"]),
            int(session["started_by_user_id"]),
            "bulk_edit.session.expired",
            reminder_field="expired_notified_at",
        )
        return

    session = get_active_bulk_edit_session()
    if session is None:
        return
    remaining = _parse_dt(session["expires_at"]) - _utcnow()
    if remaining <= timedelta(minutes=REMINDER_3_MINUTES) and session["reminded_3m_at"] is None:
        await _notify_and_mark(
            bot,
            int(session["id"]),
            int(session["started_by_user_id"]),
            "bulk_edit.session.reminder_3m",
            reminder_field="reminded_3m_at",
        )
        return
    if remaining <= timedelta(minutes=REMINDER_10_MINUTES) and session["reminded_10m_at"] is None:
        await _notify_and_mark(
            bot,
            int(session["id"]),
            int(session["started_by_user_id"]),
            "bulk_edit.session.reminder_10m",
            reminder_field="reminded_10m_at",
        )


async def run_bulk_edit_monitor(bot, *, poll_interval_seconds: int = 30) -> None:
    try:
        while True:
            await process_due_bulk_edit_notifications(bot)
            await asyncio.sleep(poll_interval_seconds)
    except asyncio.CancelledError:
        raise


def require_bulk_edit_initiator(session: sqlite3.Row, user_id: int) -> None:
    if user_id != int(session["started_by_user_id"]):
        raise BulkEditSessionAccessError("only the bulk-edit initiator may do this")


def ensure_bulk_edit_session_ready_for_upload(session: sqlite3.Row) -> None:
    if str(session["status"]) not in {"active", "uploaded"}:
        raise BulkEditSessionStateError("bulk edit session is not ready for upload")


def ensure_bulk_edit_session_ready_for_apply(session: sqlite3.Row) -> None:
    if str(session["status"]) != "uploaded":
        raise BulkEditSessionStateError("bulk edit session is not ready for apply")
    if not session["uploaded_file_path"]:
        raise BulkEditSessionStateError("uploaded workbook is missing")


def format_bulk_edit_remaining_time(session: sqlite3.Row) -> str:
    remaining = max(_parse_dt(session["expires_at"]) - _utcnow(), timedelta())
    minutes = max(int(remaining.total_seconds() // 60), 0)
    return f"{minutes}m"


def get_bulk_edit_control_message_target(session: sqlite3.Row) -> tuple[int | None, int | None]:
    chat_id = session["control_message_chat_id"]
    message_id = session["control_message_message_id"]
    return (
        int(chat_id) if chat_id is not None else None,
        int(message_id) if message_id is not None else None,
    )


def _update_session(session_id: int, query: str, parameters: tuple[object, ...]) -> sqlite3.Row:
    with get_connection() as connection:
        connection.execute(query, parameters)
    session = get_bulk_edit_session(session_id)
    assert session is not None
    return session


def _cleanup_session_temp_files(session: sqlite3.Row) -> None:
    for field_name in ("export_file_path", "uploaded_file_path"):
        file_path = session[field_name]
        if not file_path:
            continue
        path = Path(str(file_path))
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove temporary bulk-edit file %s", path)


def _prune_bulk_edit_backups() -> None:
    backup_paths = sorted(
        get_backup_dir().glob("before-bulk-edit__family-*__user-*__*.sqlite3"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for overflow_path in backup_paths[500:]:
        overflow_path.unlink(missing_ok=True)


def _parse_dt(raw_value: object) -> datetime:
    value = str(raw_value)
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(UTC)


def _format_dt(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _extract_user_id(update: Update) -> int | None:
    if update.message is not None and update.message.from_user is not None:
        return update.message.from_user.id
    if update.callback_query is not None and update.callback_query.from_user is not None:
        return update.callback_query.from_user.id
    return None


def _is_allowed_initiator_update(update: Update) -> bool:
    message = update.message
    if message is not None and message.from_user is not None:
        text = (message.text or message.caption or "").strip()
        if text.startswith(BULK_EDIT_COMMAND_TOKEN):
            return True
        if message.document is not None:
            filename = (message.document.file_name or "").lower()
            return filename.endswith(".xlsx")
        return False
    callback_query = update.callback_query
    if callback_query is not None:
        return (callback_query.data or "").startswith(BULK_EDIT_CALLBACK_PREFIX)
    return False


async def _respond_to_blocked_update(update: Update, decision: BulkEditGateDecision) -> None:
    text = translate_for_user(
        decision.responder_user_id,
        decision.message_key,
        remaining_time=format_bulk_edit_remaining_time(decision.session),
        command=BULK_EDIT_COMMAND_TOKEN,
    )
    if update.callback_query is not None:
        callback = update.callback_query
        await callback.answer(text, show_alert=True)
        return
    message = update.message
    if message is not None:
        await message.answer(text)


async def _notify_and_mark(
    bot,
    session_id: int,
    user_id: int,
    message_key: str,
    *,
    reminder_field: str,
) -> None:
    await bot.send_message(
        chat_id=user_id,
        text=translate_for_user(user_id, message_key, command=BULK_EDIT_COMMAND_TOKEN),
    )
    with get_connection() as connection:
        connection.execute(
            f"""
            UPDATE bulk_edit_sessions
            SET {reminder_field} = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (utc_now(), utc_now(), session_id),
        )
