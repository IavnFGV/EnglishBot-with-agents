import asyncio
import sys
from pathlib import Path

from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.settings_handlers import (
    SETTINGS_BOT_LANGUAGE_CALLBACK,
    SETTINGS_HINT_LANGUAGE_CALLBACK,
    SETTINGS_SET_BOT_LANGUAGE_PREFIX,
    SETTINGS_SET_HINT_LANGUAGE_PREFIX,
    open_bot_language_settings,
    open_hint_language_settings,
    set_bot_language,
    set_hint_language,
    settings,
)
from englishbot.user_profiles import get_user_hint_language, get_user_language


class FakeMessage:
    def __init__(self, user: User) -> None:
        self.from_user = user
        self.answers: list[dict[str, object]] = []

    async def answer(self, text: str, **kwargs: object) -> None:
        self.answers.append({"text": text, "kwargs": kwargs})


class FakeCallback:
    def __init__(self, user: User, data: str, message: FakeMessage) -> None:
        self.from_user = user
        self.data = data
        self.message = message
        self.answered = False

    async def answer(self) -> None:
        self.answered = True


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "settings_handlers.sqlite3"
    db.init_db()


def test_settings_handler_shows_bot_and_hint_language_entries(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(1101, "Learner")
    message = FakeMessage(user)

    asyncio.run(settings(message))

    assert message.answers == [
        {
            "text": "Settings",
            "kwargs": {
                "reply_markup": message.answers[0]["kwargs"]["reply_markup"],
            },
        }
    ]
    keyboard = message.answers[0]["kwargs"]["reply_markup"]
    assert keyboard.inline_keyboard[0][0].text == "Bot language: English"
    assert keyboard.inline_keyboard[1][0].text == "Hint language: English"


def test_open_bot_language_settings_shows_supported_language_options(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(1102, "Learner")
    callback_message = FakeMessage(user)
    callback = FakeCallback(user, SETTINGS_BOT_LANGUAGE_CALLBACK, callback_message)

    asyncio.run(open_bot_language_settings(callback))

    assert callback.answered is True
    assert callback_message.answers[0]["text"] == "Choose bot language:"
    keyboard = callback_message.answers[0]["kwargs"]["reply_markup"]
    assert [row[0].text for row in keyboard.inline_keyboard] == [
        "English",
        "Русский",
        "Українська",
        "Български",
    ]


def test_open_hint_language_settings_shows_supported_language_options(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(1103, "Learner")
    callback_message = FakeMessage(user)
    callback = FakeCallback(user, SETTINGS_HINT_LANGUAGE_CALLBACK, callback_message)

    asyncio.run(open_hint_language_settings(callback))

    assert callback.answered is True
    assert callback_message.answers[0]["text"] == "Choose hint language:"
    keyboard = callback_message.answers[0]["kwargs"]["reply_markup"]
    assert [row[0].text for row in keyboard.inline_keyboard] == [
        "English",
        "Русский",
        "Українська",
        "Български",
    ]


def test_set_bot_language_persists_choice_and_replies_in_new_language(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(1104, "Learner")
    db.save_user(user)
    callback_message = FakeMessage(user)
    callback = FakeCallback(
        user,
        f"{SETTINGS_SET_BOT_LANGUAGE_PREFIX}uk",
        callback_message,
    )

    asyncio.run(set_bot_language(callback))

    assert callback.answered is True
    assert get_user_language(user.id) == "uk"
    assert get_user_hint_language(user.id) == "en"
    assert callback_message.answers[0]["text"] == "Мову бота змінено на Українська."
    keyboard = callback_message.answers[0]["kwargs"]["reply_markup"]
    assert keyboard.inline_keyboard[0][0].text == "Мова бота: Українська"
    assert keyboard.inline_keyboard[1][0].text == "Мова підказок: English"


def test_set_hint_language_persists_choice_without_changing_bot_language(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(1105, "Learner")
    db.save_user(user)
    callback_message = FakeMessage(user)
    callback = FakeCallback(
        user,
        f"{SETTINGS_SET_HINT_LANGUAGE_PREFIX}bg",
        callback_message,
    )

    asyncio.run(set_hint_language(callback))

    assert callback.answered is True
    assert get_user_language(user.id) == "en"
    assert get_user_hint_language(user.id) == "bg"
    assert callback_message.answers[0]["text"] == "Hint language set to Български."
    keyboard = callback_message.answers[0]["kwargs"]["reply_markup"]
    assert keyboard.inline_keyboard[0][0].text == "Bot language: English"
    assert keyboard.inline_keyboard[1][0].text == "Hint language: Български"
