import asyncio
import sys
from pathlib import Path

from aiogram import Bot
from aiogram.types import User
from aiogram.types import Chat, Message, Update

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.bot import BOT_COMMANDS, configure_bot_commands, dispatcher, help_command, me, start_command
from englishbot.command_registry import get_registered_commands
from englishbot.families import create_family, create_family_learning_item, get_user_family
from englishbot.training import create_training_session, get_active_training_session
from englishbot.vocabulary import create_learning_item_translation, create_lexeme


class FakeMessage:
    def __init__(self, user: User) -> None:
        self.from_user = user
        self.answers: list[str] = []

    async def answer(self, text: str, **_: object) -> None:
        self.answers.append(text)


class FakeBot:
    def __init__(self) -> None:
        self.commands = None

    async def set_my_commands(self, commands) -> None:
        self.commands = commands


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "bot.sqlite3"
    db.init_db()


def test_me_handler_shows_profile_role_and_text_count(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(901, "Mira")
    db.save_user(user)
    db.save_interaction(user.id, "in", "text", "hello")
    db.save_interaction(user.id, "in", "text", "world")
    db.save_interaction(user.id, "in", "command", "/me")
    message = FakeMessage(user)

    asyncio.run(me(message))

    assert message.answers == [
        "Mira\ntelegram_user_id: 901\nrole: student\nsaved_text_messages: 2"
    ]


def test_start_handler_bootstraps_family_for_new_user_when_owner_is_not_configured(tmp_path: Path, monkeypatch) -> None:
    setup_db(tmp_path)
    monkeypatch.delenv("ENGLISHBOT_OWNER_TELEGRAM_USER_ID", raising=False)
    user = make_user(905, "Nora")
    message = FakeMessage(user)

    asyncio.run(start_command(message))

    family = get_user_family(user.id)
    assert family is not None
    assert message.answers == [
        "Main menu\n"
        "Family: Home\n\n"
        "Family setup created for you.\n\n"
        "Next steps:\n"
        "/teacher_content - add words and topics\n"
        "/create_assignment - assign homework\n"
        "/topics - open family topics\n"
        "/learn - start training"
    ]


def test_start_handler_reuses_existing_family(tmp_path: Path, monkeypatch) -> None:
    setup_db(tmp_path)
    monkeypatch.setenv("ENGLISHBOT_OWNER_TELEGRAM_USER_ID", "906")
    user = make_user(906, "Mila")
    db.save_user(user)
    create_family("Home", user.id)
    message = FakeMessage(user)

    asyncio.run(start_command(message))

    assert message.answers == [
        "Main menu\n"
        "Family: Home\n\n"
        "Next steps:\n"
        "/teacher_content - add words and topics\n"
        "/create_assignment - assign homework\n"
        "/topics - open family topics\n"
        "/learn - start training"
    ]


def test_start_command_via_dispatcher_bootstraps_family_in_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    setup_db(tmp_path)
    monkeypatch.delenv("ENGLISHBOT_OWNER_TELEGRAM_USER_ID", raising=False)
    user = make_user(907, "Roma")
    answers: list[str] = []

    async def fake_answer(self: Message, text: str, **_: object) -> None:
        answers.append(text)

    monkeypatch.setattr(Message, "answer", fake_answer)

    async def run() -> None:
        chat = Chat(id=user.id, type="private")
        message = Message(message_id=1, date=0, chat=chat, from_user=user, text="/start")
        update = Update(update_id=1, message=message)
        bot = Bot("123456:TESTTOKEN")
        try:
            await dispatcher.feed_update(bot, update)
        finally:
            await bot.session.close()

    asyncio.run(run())

    family = get_user_family(user.id)
    assert family is not None
    assert answers == [
        "Main menu\n"
        "Family: Home\n\n"
        "Family setup created for you.\n\n"
        "Next steps:\n"
        "/teacher_content - add words and topics\n"
        "/create_assignment - assign homework\n"
        "/topics - open family topics\n"
        "/learn - start training"
    ]


def test_start_handler_registers_non_owner_without_bootstrapping_family_when_owner_is_configured(
    tmp_path: Path,
    monkeypatch,
) -> None:
    setup_db(tmp_path)
    monkeypatch.setenv("ENGLISHBOT_OWNER_TELEGRAM_USER_ID", "999")
    user = make_user(908, "Guest")
    message = FakeMessage(user)

    asyncio.run(start_command(message))

    assert get_user_family(user.id) is None
    assert message.answers == [
        "You are registered.\n"
        "telegram_user_id: 908\n"
        "Ask the owner to add you to the family."
    ]


def test_help_handler_shows_family_first_command_list(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(904, "Nora")
    db.save_user(user)
    message = FakeMessage(user)

    asyncio.run(help_command(message))

    assert message.answers == [
        "Available commands:\n"
        "/start - open the main menu\n"
        "/help - show this help\n"
        "/learn - start training\n"
        "/topics - open family topics\n"
        "/me - show your profile\n"
        "/settings - open settings\n"
        "/cancel - stop the current flow\n"
        "/teacher_content - edit family content\n"
        "/create_assignment - assign homework inside the family"
    ]


def test_add_family_command_adds_registered_user_to_owner_family_via_dispatcher(
    tmp_path: Path,
    monkeypatch,
) -> None:
    setup_db(tmp_path)
    monkeypatch.setenv("ENGLISHBOT_OWNER_TELEGRAM_USER_ID", "910")
    owner = make_user(910, "Owner")
    guest = make_user(911, "Guest")
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

    asyncio.run(feed_text(guest, "/start", 1))
    asyncio.run(feed_text(owner, "/add_family 911", 2))

    family = get_user_family(guest.id)
    assert family is not None
    assert answers == [
        "You are registered.\n"
        "telegram_user_id: 911\n"
        "Ask the owner to add you to the family.",
        "User added to family Home.\n"
        "telegram_user_id: 911",
    ]


def test_add_family_command_rejects_non_owner_user(tmp_path: Path, monkeypatch) -> None:
    setup_db(tmp_path)
    monkeypatch.setenv("ENGLISHBOT_OWNER_TELEGRAM_USER_ID", "910")
    guest = make_user(912, "Guest")
    answers: list[str] = []

    async def fake_answer(self: Message, text: str, **_: object) -> None:
        answers.append(text)

    monkeypatch.setattr(Message, "answer", fake_answer)

    async def run() -> None:
        chat = Chat(id=guest.id, type="private")
        message = Message(message_id=1, date=0, chat=chat, from_user=guest, text="/add_family 999")
        update = Update(update_id=1, message=message)
        bot = Bot("123456:TESTTOKEN")
        try:
            await dispatcher.feed_update(bot, update)
        finally:
            await bot.session.close()

    asyncio.run(run())

    assert answers == ["Command /add_family is available only to the configured owner user."]


def test_configure_bot_commands_registers_expected_commands() -> None:
    bot = FakeBot()

    asyncio.run(configure_bot_commands(bot))

    assert bot.commands == BOT_COMMANDS
    assert [command.command for command in bot.commands] == [
        command.name for command in get_registered_commands()
    ]


def test_me_command_is_not_swallowed_by_active_training_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    setup_db(tmp_path)
    user = make_user(902, "Nika")
    db.save_user(user)
    family = create_family("Home", user.id)
    lexeme_id = create_lexeme("apple")
    learning_item_id = create_family_learning_item(int(family["id"]), lexeme_id, "apple")
    create_learning_item_translation(learning_item_id, "ru", "яблоко")
    create_training_session(user.id)
    answers: list[str] = []

    async def fake_answer(self: Message, text: str, **_: object) -> None:
        answers.append(text)

    monkeypatch.setattr(Message, "answer", fake_answer)

    async def run() -> None:
        chat = Chat(id=user.id, type="private")
        message = Message(message_id=1, date=0, chat=chat, from_user=user, text="/me")
        update = Update(update_id=1, message=message)
        bot = Bot("123456:TESTTOKEN")
        try:
            await dispatcher.feed_update(bot, update)
        finally:
            await bot.session.close()

    asyncio.run(run())

    assert answers == [
        "Nika\ntelegram_user_id: 902\nrole: student\nsaved_text_messages: 0"
    ]


def test_cancel_command_stops_active_training_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    setup_db(tmp_path)
    user = make_user(903, "Lina")
    db.save_user(user)
    family = create_family("Home", user.id)
    lexeme_id = create_lexeme("apple")
    learning_item_id = create_family_learning_item(int(family["id"]), lexeme_id, "apple")
    create_learning_item_translation(learning_item_id, "ru", "яблоко")
    create_training_session(user.id)
    answers: list[str] = []

    async def fake_answer(self: Message, text: str, **_: object) -> None:
        answers.append(text)

    monkeypatch.setattr(Message, "answer", fake_answer)

    async def run() -> None:
        chat = Chat(id=user.id, type="private")
        message = Message(message_id=1, date=0, chat=chat, from_user=user, text="/cancel")
        update = Update(update_id=1, message=message)
        bot = Bot("123456:TESTTOKEN")
        try:
            await dispatcher.feed_update(bot, update)
        finally:
            await bot.session.close()

    asyncio.run(run())

    assert answers == ["Current flow stopped."]
    assert get_active_training_session(user.id) is None
