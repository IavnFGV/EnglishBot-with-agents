import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.families import (
    add_family_member,
    create_family,
    create_family_learning_item,
    create_family_topic,
    replace_topic_items as replace_family_topic_items,
)
from englishbot.topic_access import list_accessible_topics
from englishbot.topic_access_handlers import (
    TOPICS_START_PREFIX,
    build_accessible_topics_keyboard,
    start_topic_training,
    topics,
)
from englishbot.vocabulary import create_learning_item_translation, create_lexeme


class FakeMessage:
    def __init__(self, user: User) -> None:
        self.from_user = user
        self.answers: list[dict[str, object]] = []
        self.chat = SimpleNamespace(id=user.id)
        self.bot = SimpleNamespace()
        self._next_message_id = 1

    async def answer(self, text: str, **kwargs: object) -> SimpleNamespace:
        self.answers.append({"text": text, "kwargs": kwargs})
        message = SimpleNamespace(message_id=self._next_message_id)
        self._next_message_id += 1
        return message


    async def edit_text(self, text, **kwargs):
        return await self.answer(text, **kwargs)

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
    db.DB_PATH = tmp_path / "topic_access_handlers.sqlite3"
    db.init_db()


def seed_family_topic() -> tuple[User, User, int]:
    parent = make_user(821, "Parent")
    child = make_user(822, "Child")
    db.save_user(parent)
    db.save_user(child)
    family = create_family("Home", parent.id)
    add_family_member(int(family["id"]), child.id)
    item_id = create_family_learning_item(int(family["id"]), create_lexeme("cat-topic"), "cat")
    create_learning_item_translation(item_id, "ru", "кот")
    topic_id = create_family_topic(int(family["id"]), "pets", "Pets")
    replace_family_topic_items(topic_id, [item_id])
    return parent, child, topic_id


def test_topics_handler_lists_family_topics(tmp_path: Path) -> None:
    setup_db(tmp_path)
    _, child, topic_id = seed_family_topic()
    message = FakeMessage(child)

    asyncio.run(topics(message))

    assert message.answers[0]["text"] == "Available topics:"
    keyboard = message.answers[0]["kwargs"]["reply_markup"]
    accessible_topic = list_accessible_topics(child.id)[0]
    assert accessible_topic["id"] == topic_id
    assert keyboard.inline_keyboard[0][0].text == "Pets"
    assert keyboard.inline_keyboard[0][0].callback_data == (
        f"{TOPICS_START_PREFIX}{accessible_topic['id']}"
    )


def test_start_topic_training_handler_uses_family_topic(tmp_path: Path) -> None:
    setup_db(tmp_path)
    _, child, _ = seed_family_topic()
    callback_message = FakeMessage(child)
    accessible_topic = list_accessible_topics(child.id)[0]
    callback = FakeCallback(
        child,
        f"{TOPICS_START_PREFIX}{accessible_topic['id']}",
        callback_message,
    )

    asyncio.run(start_topic_training(callback))

    assert callback.answered is True
    assert callback_message.answers[0]["text"].startswith("Choose how to practice")
    keyboard = callback_message.answers[0]["kwargs"]["reply_markup"]
    assert len(keyboard.inline_keyboard) == 3
    from englishbot.training_handlers import choose_training_mode
    from englishbot.training import get_current_question
    asyncio.run(choose_training_mode(FakeCallback(child, keyboard.inline_keyboard[2][0].callback_data, callback_message)))
    assert get_current_question(child.id)["current_stage"] == "hard"


def test_topic_launch_offers_mini_app_when_configured(tmp_path: Path, monkeypatch) -> None:
    setup_db(tmp_path)
    _, child, topic_id = seed_family_topic()
    monkeypatch.setenv("ENGLISHBOT_MINI_APP_URL", "https://example.test/mini-app")
    message = FakeMessage(child)
    callback = FakeCallback(child, f"{TOPICS_START_PREFIX}{topic_id}", message)
    asyncio.run(start_topic_training(callback))
    assert len(message.answers) == 1
    keyboard = message.answers[0]["kwargs"]["reply_markup"]
    from englishbot.training_handlers import choose_training_mode
    asyncio.run(choose_training_mode(FakeCallback(child, keyboard.inline_keyboard[0][0].callback_data, message)))
    assert message.answers[-1]["text"] == "Choose a training mode:"
    assert message.answers[-1]["kwargs"]["reply_markup"].inline_keyboard[0][0].web_app is not None


def test_start_topic_training_handler_rejects_inaccessible_topic(tmp_path: Path) -> None:
    setup_db(tmp_path)
    _, _, topic_id = seed_family_topic()
    outsider = make_user(899, "Outsider")
    db.save_user(outsider)
    callback_message = FakeMessage(outsider)
    callback = FakeCallback(outsider, f"{TOPICS_START_PREFIX}{topic_id}", callback_message)

    asyncio.run(start_topic_training(callback))

    assert callback.answered is True
    assert callback_message.answers == [
        {"text": "This topic is not available to you yet.", "kwargs": {}}
    ]


def test_build_accessible_topics_keyboard_uses_topic_start_callback() -> None:
    keyboard = build_accessible_topics_keyboard([{"id": 9, "title": "Фрукты"}])

    assert keyboard.inline_keyboard[0][0].text == "Фрукты"
    assert keyboard.inline_keyboard[0][0].callback_data == f"{TOPICS_START_PREFIX}9"


def test_topics_handler_lists_family_topics_without_grants(tmp_path: Path) -> None:
    setup_db(tmp_path)
    _, child, topic_id = seed_family_topic()
    message = FakeMessage(child)

    asyncio.run(topics(message))

    assert message.answers[0]["text"] == "Available topics:"
    keyboard = message.answers[0]["kwargs"]["reply_markup"]
    assert keyboard.inline_keyboard[0][0].text == "Pets"
    assert keyboard.inline_keyboard[0][0].callback_data == f"{TOPICS_START_PREFIX}{topic_id}"
