import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from aiogram import Bot
from aiogram.types import Chat, Message, Update, User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.bot import dispatcher
from englishbot.bulk_edit import (
    BulkEditSessionAlreadyActiveError,
    create_bulk_edit_session,
    create_bulk_edit_backup,
    get_active_bulk_edit_session,
    get_bulk_edit_session,
    process_due_bulk_edit_notifications,
    restore_database_from_bulk_edit_backup,
)
from englishbot.families import add_family_member, create_family


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path, monkeypatch) -> None:
    db.DB_PATH = tmp_path / "bulk_edit.sqlite3"
    monkeypatch.setenv("ENGLISHBOT_BACKUP_DIR", str(tmp_path / "backups"))
    db.init_db()


def seed_family(tmp_path: Path, monkeypatch) -> tuple[User, User, int]:
    setup_db(tmp_path, monkeypatch)
    owner = make_user(1201, "Owner")
    peer = make_user(1202, "Peer")
    db.save_user(owner)
    db.save_user(peer)
    family = create_family("Home", owner.id)
    add_family_member(int(family["id"]), peer.id)
    return owner, peer, int(family["id"])


def test_only_one_active_bulk_edit_session_is_allowed(tmp_path: Path, monkeypatch) -> None:
    owner, _, family_id = seed_family(tmp_path, monkeypatch)

    create_bulk_edit_session(family_id, owner.id)

    with pytest.raises(BulkEditSessionAlreadyActiveError):
        create_bulk_edit_session(family_id, owner.id)


def test_expired_session_releases_global_gate(tmp_path: Path, monkeypatch) -> None:
    owner, _, family_id = seed_family(tmp_path, monkeypatch)
    session = create_bulk_edit_session(family_id, owner.id)
    expired_at = (datetime.now(UTC) - timedelta(minutes=1)).isoformat(timespec="seconds")
    with db.get_connection() as connection:
        connection.execute(
            """
            UPDATE bulk_edit_sessions
            SET expires_at = ?
            WHERE id = ?
            """,
            (expired_at, int(session["id"])),
        )

    assert get_active_bulk_edit_session() is None
    assert get_bulk_edit_session(int(session["id"]))["status"] == "expired"


def test_bulk_edit_backup_is_created_and_pruned_to_latest_500(tmp_path: Path, monkeypatch) -> None:
    owner, _, family_id = seed_family(tmp_path, monkeypatch)
    backup_dir = Path(str(tmp_path / "backups"))
    backup_dir.mkdir(parents=True, exist_ok=True)
    for index in range(500):
        path = backup_dir / f"before-bulk-edit__family-{family_id}__user-{owner.id}__old-{index:03d}.sqlite3"
        path.write_bytes(b"old")

    backup_path = create_bulk_edit_backup(family_id=family_id, user_id=owner.id)

    backups = sorted(backup_dir.glob("before-bulk-edit__family-*__user-*__*.sqlite3"))
    assert backup_path.exists()
    assert len(backups) == 500


def test_global_gate_blocks_ordinary_flows_but_initiator_gets_specialized_response(
    tmp_path: Path,
    monkeypatch,
) -> None:
    owner, peer, family_id = seed_family(tmp_path, monkeypatch)
    create_bulk_edit_session(family_id, owner.id)
    answers: list[str] = []

    async def fake_answer(self: Message, text: str, **_: object) -> None:
        answers.append(text)

    monkeypatch.setattr(Message, "answer", fake_answer)

    async def feed_text(user: User, text: str, update_id: int) -> None:
        chat = Chat(id=user.id, type="private")
        message = Message(message_id=update_id, date=0, chat=chat, from_user=user, text=text)
        update = Update(update_id=update_id, message=message)
        bot = Bot("123456:TESTTOKEN")
        try:
            await dispatcher.feed_update(bot, update)
        finally:
            await bot.session.close()

    asyncio.run(feed_text(peer, "/help", 1))
    asyncio.run(feed_text(owner, "/help", 2))

    assert answers == [
        "Family bulk edit is in progress now. Please try again later.",
        "Bulk edit is active. Upload the .xlsx file or finish the session with /bulk_edit.",
    ]


def test_bulk_edit_monitor_sends_reminders_and_expiration_notice(tmp_path: Path, monkeypatch) -> None:
    owner, _, family_id = seed_family(tmp_path, monkeypatch)
    session = create_bulk_edit_session(family_id, owner.id)

    class FakeBot:
        def __init__(self) -> None:
            self.messages: list[str] = []

        async def send_message(self, chat_id: int, text: str) -> None:
            self.messages.append(text)

    bot = FakeBot()

    with db.get_connection() as connection:
        connection.execute(
            """
            UPDATE bulk_edit_sessions
            SET expires_at = ?, reminded_10m_at = NULL, reminded_3m_at = NULL
            WHERE id = ?
            """,
            (
                (datetime.now(UTC) + timedelta(minutes=9)).isoformat(timespec="seconds"),
                int(session["id"]),
            ),
        )
    asyncio.run(process_due_bulk_edit_notifications(bot))

    with db.get_connection() as connection:
        connection.execute(
            """
            UPDATE bulk_edit_sessions
            SET expires_at = ?, reminded_3m_at = NULL
            WHERE id = ?
            """,
            (
                (datetime.now(UTC) + timedelta(minutes=2)).isoformat(timespec="seconds"),
                int(session["id"]),
            ),
        )
    asyncio.run(process_due_bulk_edit_notifications(bot))

    with db.get_connection() as connection:
        connection.execute(
            """
            UPDATE bulk_edit_sessions
            SET expires_at = ?, expired_notified_at = NULL
            WHERE id = ?
            """,
            (
                (datetime.now(UTC) - timedelta(minutes=1)).isoformat(timespec="seconds"),
                int(session["id"]),
            ),
        )
    asyncio.run(process_due_bulk_edit_notifications(bot))

    assert bot.messages == [
        "Bulk edit reminder: 10 minutes remain before the session expires automatically.",
        "Bulk edit reminder: 3 minutes remain before the session expires automatically.",
        "Bulk edit session expired automatically. The bot is available again.",
    ]


def test_restore_database_from_bulk_edit_backup_restores_previous_sqlite_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    owner, _, family_id = seed_family(tmp_path, monkeypatch)
    backup_path = create_bulk_edit_backup(family_id=family_id, user_id=owner.id)

    extra_user = make_user(1999, "LateUser")
    db.save_user(extra_user)
    with db.get_connection() as connection:
        assert connection.execute(
            "SELECT 1 FROM users WHERE telegram_user_id = ?",
            (extra_user.id,),
        ).fetchone() is not None

    restore_database_from_bulk_edit_backup(backup_path)

    with db.get_connection() as connection:
        assert connection.execute(
            "SELECT 1 FROM users WHERE telegram_user_id = ?",
            (extra_user.id,),
        ).fetchone() is None
