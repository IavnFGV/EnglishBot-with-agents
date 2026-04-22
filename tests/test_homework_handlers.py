import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from aiogram_dialog import StartMode
from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.basic_topics_seed import (
    resolve_basic_topic_learning_item_ids,
    seed_basic_topics,
)
from englishbot.homework_dialog import HomeworkDialogSG
from englishbot.homework import create_assignment
from englishbot.homework_handlers import (
    HOMEWORK_OPEN_CALLBACK,
    build_homework_button,
    open_homework,
    start,
    start_homework,
)
from englishbot.teacher_student import create_invite, join_with_invite
from englishbot.user_profiles import set_user_role
from englishbot.vocabulary import (
    create_learning_item,
    create_learning_item_translation,
    create_lexeme,
)


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


class FakeDialogManager:
    def __init__(self) -> None:
        self.start_calls: list[dict[str, object]] = []

    async def start(self, state, mode=None, data=None, **kwargs) -> None:
        self.start_calls.append({"state": state, "mode": mode, "data": data, "kwargs": kwargs})


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "homework_handlers.sqlite3"
    db.init_db()


def seed_linked_teacher_and_student() -> tuple[User, User]:
    teacher = make_user(601, "Teacher")
    student = make_user(602, "Student")
    db.save_user(teacher)
    db.save_user(student)
    set_user_role(teacher.id, "teacher")
    invite_code = create_invite(teacher.id)
    join_with_invite(student.id, invite_code)
    return teacher, student


def seed_learning_item() -> int:
    lexeme_id = create_lexeme("apple")
    learning_item_id = create_learning_item(lexeme_id, "apple")
    create_learning_item_translation(learning_item_id, "ru", "яблоко")
    return learning_item_id


def test_start_shows_homework_button_when_active_assignment_exists(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    learning_item_id = seed_learning_item()
    create_assignment(teacher.id, student.id, [learning_item_id])
    message = FakeMessage(student)

    asyncio.run(start(message))

    assert len(message.answers) == 1
    assert message.answers[0]["text"] == "You have assigned homework."
    assert (
        message.answers[0]["kwargs"]["reply_markup"].inline_keyboard[0][0].text
        == "Homework"
    )


def test_start_shows_no_homework_message_without_assignments(tmp_path: Path) -> None:
    setup_db(tmp_path)
    student = make_user(603, "Student")
    message = FakeMessage(student)

    asyncio.run(start(message))

    assert message.answers == [
        {
            "text": "No homework yet. You can use /learn for training.",
            "kwargs": {},
        }
    ]


def test_open_homework_starts_dialog_flow(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    learning_item_id = seed_learning_item()
    create_assignment(teacher.id, student.id, [learning_item_id], title="Фрукты")
    callback_message = FakeMessage(student)
    callback = FakeCallback(student, HOMEWORK_OPEN_CALLBACK, callback_message)
    manager = FakeDialogManager()

    asyncio.run(open_homework(callback, manager))

    assert callback.answered is True
    assert callback_message.answers == []
    assert manager.start_calls == [
        {
            "state": HomeworkDialogSG.assignments,
            "mode": StartMode.RESET_STACK,
            "data": None,
            "kwargs": {},
        }
    ]


def test_start_homework_uses_assigned_content(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    seed_basic_topics()
    learning_item_id = resolve_basic_topic_learning_item_ids("weekdays")[0]
    assignment = create_assignment(
        teacher.id,
        student.id,
        [learning_item_id],
        title="Тестовая домашка",
    )
    callback_message = FakeMessage(student)
    callback = FakeCallback(
        student,
        f"homework:start:{assignment['assignment_id']}",
        callback_message,
    )

    asyncio.run(start_homework(callback))

    assert callback.answered is True
    assert callback_message.answers == [
        {
            "text": (
                "Homework: Тестовая домашка\n"
                "Done 0/1\n"
                "Current item 1/1\n"
                "Stage: easy\n"
                "Items: 1 in progress"
            ),
            "kwargs": {},
        },
        {
            "text": "Hint: понедельник\nFirst letter: m",
            "kwargs": {"reply_markup": None},
        }
    ]


def test_start_homework_progress_shows_item_statuses_for_multiple_items(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    seed_basic_topics()
    learning_item_ids = resolve_basic_topic_learning_item_ids("weekdays")[:2]
    assignment = create_assignment(
        teacher.id,
        student.id,
        learning_item_ids,
        title="Два слова",
    )
    callback_message = FakeMessage(student)
    callback = FakeCallback(
        student,
        f"homework:start:{assignment['assignment_id']}",
        callback_message,
    )

    asyncio.run(start_homework(callback))

    assert "Homework: Два слова" in callback_message.answers[0]["text"]
    assert "Items: 1 in progress | 2 not started" in callback_message.answers[0]["text"]


def test_build_homework_button_uses_homework_open_callback() -> None:
    keyboard = build_homework_button(1)

    assert keyboard.inline_keyboard[0][0].text == "Homework"
    assert keyboard.inline_keyboard[0][0].callback_data == HOMEWORK_OPEN_CALLBACK
