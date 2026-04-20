import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.basic_topics_seed import seed_basic_topics
from englishbot.teacher_handlers import grant_topic
from englishbot.teacher_student import create_invite, join_with_invite
from englishbot.topic_access import grant_topic_access, list_accessible_topics
from englishbot.topic_access_handlers import (
    TOPICS_START_PREFIX,
    build_accessible_topics_keyboard,
    start_topic_training,
    topics,
)
from englishbot.user_profiles import set_user_role


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


def seed_linked_teacher_and_student() -> tuple[User, User]:
    teacher = make_user(801, "Teacher")
    student = make_user(802, "Student")
    db.save_user(teacher)
    db.save_user(student)
    set_user_role(teacher.id, "teacher")
    invite_code = create_invite(teacher.id)
    join_with_invite(student.id, invite_code)
    return teacher, student


def test_grant_topic_handler_grants_named_topic_to_linked_student(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    seed_basic_topics()
    message = FakeMessage(teacher)
    workspace_id = db.get_default_content_workspace_id()

    asyncio.run(grant_topic(message, SimpleNamespace(args=f"{student.id} {workspace_id} weekdays")))

    assert message.answers == [
        {"text": "Topic access granted: Дни недели (weekdays).", "kwargs": {}}
    ]


def test_topics_handler_lists_accessible_topics(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    seed_basic_topics()
    grant_topic_access(teacher.id, student.id, db.get_default_content_workspace_id(), "months")
    message = FakeMessage(student)

    asyncio.run(topics(message))

    assert message.answers[0]["text"] == "Available topics:"
    keyboard = message.answers[0]["kwargs"]["reply_markup"]
    accessible_topic = list_accessible_topics(student.id)[0]
    assert keyboard.inline_keyboard[0][0].text == "Месяцы"
    assert keyboard.inline_keyboard[0][0].callback_data == (
        f"{TOPICS_START_PREFIX}{accessible_topic['id']}"
    )


def test_start_topic_training_handler_uses_accessible_topic(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    seed_basic_topics()
    grant_topic_access(teacher.id, student.id, db.get_default_content_workspace_id(), "colors")
    callback_message = FakeMessage(student)
    accessible_topic = list_accessible_topics(student.id)[0]
    callback = FakeCallback(
        student,
        f"{TOPICS_START_PREFIX}{accessible_topic['id']}",
        callback_message,
    )

    asyncio.run(start_topic_training(callback))

    assert callback.answered is True
    assert callback_message.answers[0] == {
        "text": "Item 1/6\nDone 0/6\nStage: easy",
        "kwargs": {},
    }
    assert callback_message.answers[1]["text"] == "красный"
    keyboard = callback_message.answers[1]["kwargs"]["reply_markup"]
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 3


def test_start_topic_training_handler_rejects_inaccessible_topic(tmp_path: Path) -> None:
    setup_db(tmp_path)
    _, student = seed_linked_teacher_and_student()
    seed_basic_topics()
    callback_message = FakeMessage(student)
    callback = FakeCallback(student, f"{TOPICS_START_PREFIX}1", callback_message)

    asyncio.run(start_topic_training(callback))

    assert callback.answered is True
    assert callback_message.answers == [
        {"text": "This topic is not available to you yet.", "kwargs": {}}
    ]


def test_build_accessible_topics_keyboard_uses_topic_start_callback() -> None:
    keyboard = build_accessible_topics_keyboard([{"id": 9, "title": "Фрукты"}])

    assert keyboard.inline_keyboard[0][0].text == "Фрукты"
    assert keyboard.inline_keyboard[0][0].callback_data == f"{TOPICS_START_PREFIX}9"


def test_grant_topic_handler_requires_explicit_workspace_id(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    seed_basic_topics()
    message = FakeMessage(teacher)

    asyncio.run(grant_topic(message, SimpleNamespace(args=f"{student.id} weekdays")))

    assert message.answers == [
        {
            "text": "Usage: /granttopic <student_user_id> <teacher_workspace_id> <topic_name>",
            "kwargs": {},
        }
    ]
