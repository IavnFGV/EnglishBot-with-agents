import asyncio
import sys
from pathlib import Path

from aiogram import Bot
from aiogram.types import User
from aiogram.types import Chat, Message, Update

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.bot import BOT_COMMANDS, configure_bot_commands, dispatcher, me
from englishbot.command_registry import CANCEL_COMMAND, ME_COMMAND, SETTINGS_COMMAND
from englishbot.training import create_training_session, get_active_training_session
from englishbot.vocabulary import create_learning_item, create_learning_item_translation, create_lexeme


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


def test_configure_bot_commands_registers_expected_commands() -> None:
    bot = FakeBot()

    asyncio.run(configure_bot_commands(bot))

    assert bot.commands == BOT_COMMANDS
    assert [command.command for command in bot.commands] == [
        "start",
        "learn",
        ME_COMMAND.name,
        SETTINGS_COMMAND.name,
        CANCEL_COMMAND.name,
    ]


def test_me_command_is_not_swallowed_by_active_training_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    setup_db(tmp_path)
    user = make_user(902, "Nika")
    db.save_user(user)
    lexeme_id = create_lexeme("apple")
    learning_item_id = create_learning_item(lexeme_id, "apple")
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
    lexeme_id = create_lexeme("apple")
    learning_item_id = create_learning_item(lexeme_id, "apple")
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
