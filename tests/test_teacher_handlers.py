import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.teacher_handlers import assign, invite, join
from englishbot.teacher_student import get_invite, get_teacher_link
from englishbot.user_profiles import get_user_role, set_user_role
from englishbot.vocabulary import create_learning_item, create_learning_item_translation, create_lexeme


class FakeMessage:
    def __init__(self, user: User) -> None:
        self.from_user = user
        self.answers: list[str] = []
        self.bot = FakeBot()

    async def answer(self, text: str, **_: object) -> None:
        self.answers.append(text)


class FakeBot:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, object]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs: object) -> None:
        self.sent_messages.append(
            {"chat_id": chat_id, "text": text, "kwargs": kwargs}
        )


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "teacher_handlers.sqlite3"
    db.init_db()


def seed_learning_item() -> int:
    lexeme_id = create_lexeme("apple")
    learning_item_id = create_learning_item(lexeme_id, "apple")
    create_learning_item_translation(learning_item_id, "ru", "яблоко")
    return learning_item_id


def test_invite_handler_rejects_non_teacher(tmp_path: Path) -> None:
    setup_db(tmp_path)
    message = FakeMessage(make_user(201, "Student"))

    asyncio.run(invite(message))

    assert message.answers == ["Команда /invite доступна только пользователю с ролью teacher."]


def test_invite_handler_returns_code_for_teacher(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(202, "Teacher")
    db.save_user(user)
    set_user_role(user.id, "teacher")
    message = FakeMessage(user)

    asyncio.run(invite(message))

    assert len(message.answers) == 1
    assert message.answers[0].startswith("Код приглашения: ")
    code = message.answers[0].split(": ", 1)[1]
    invite_row = get_invite(code)
    assert invite_row is not None
    assert invite_row["teacher_user_id"] == user.id


def test_join_handler_requires_code(tmp_path: Path) -> None:
    setup_db(tmp_path)
    message = FakeMessage(make_user(203, "Student"))

    asyncio.run(join(message, SimpleNamespace(args=None)))

    assert message.answers == ["Использование: /join <code>"]


def test_join_handler_joins_student_to_teacher(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(204, "Teacher")
    student = make_user(205, "Student")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    teacher_message = FakeMessage(teacher)
    asyncio.run(invite(teacher_message))
    code = teacher_message.answers[0].split(": ", 1)[1]
    student_message = FakeMessage(student)

    asyncio.run(join(student_message, SimpleNamespace(args=code)))

    assert student_message.answers == [f"Присоединение выполнено. teacher_user_id: {teacher.id}"]
    link = get_teacher_link(student.id)
    assert link is not None
    assert link["teacher_user_id"] == teacher.id


def test_join_handler_rejects_used_or_invalid_invites(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(206, "Teacher")
    first_student = make_user(207, "First")
    second_student = make_user(208, "Second")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    teacher_message = FakeMessage(teacher)
    asyncio.run(invite(teacher_message))
    code = teacher_message.answers[0].split(": ", 1)[1]

    missing_message = FakeMessage(first_student)
    asyncio.run(join(missing_message, SimpleNamespace(args="missing")))
    assert missing_message.answers == ["Приглашение не найдено."]

    first_join_message = FakeMessage(first_student)
    asyncio.run(join(first_join_message, SimpleNamespace(args=code)))
    assert first_join_message.answers == [f"Присоединение выполнено. teacher_user_id: {teacher.id}"]

    second_join_message = FakeMessage(second_student)
    asyncio.run(join(second_join_message, SimpleNamespace(args=code)))
    assert second_join_message.answers == ["Это приглашение уже использовано."]


def test_join_handler_rejects_already_linked_student(tmp_path: Path) -> None:
    setup_db(tmp_path)
    first_teacher = make_user(209, "TeacherA")
    second_teacher = make_user(210, "TeacherB")
    student = make_user(211, "Student")
    db.save_user(first_teacher)
    db.save_user(second_teacher)
    set_user_role(first_teacher.id, "teacher")
    set_user_role(second_teacher.id, "teacher")

    first_teacher_message = FakeMessage(first_teacher)
    asyncio.run(invite(first_teacher_message))
    first_code = first_teacher_message.answers[0].split(": ", 1)[1]

    second_teacher_message = FakeMessage(second_teacher)
    asyncio.run(invite(second_teacher_message))
    second_code = second_teacher_message.answers[0].split(": ", 1)[1]

    first_join_message = FakeMessage(student)
    asyncio.run(join(first_join_message, SimpleNamespace(args=first_code)))
    assert first_join_message.answers == [
        f"Присоединение выполнено. teacher_user_id: {first_teacher.id}"
    ]

    second_join_message = FakeMessage(student)
    asyncio.run(join(second_join_message, SimpleNamespace(args=second_code)))
    assert second_join_message.answers == ["Ученик уже привязан к учителю."]


def test_join_handler_allows_teacher_to_join_own_invite_for_testing(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(212, "TeacherSelf")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")

    invite_message = FakeMessage(teacher)
    asyncio.run(invite(invite_message))
    code = invite_message.answers[0].split(": ", 1)[1]

    join_message = FakeMessage(teacher)
    asyncio.run(join(join_message, SimpleNamespace(args=code)))

    teacher_role = get_user_role(teacher.id)
    link = get_teacher_link(teacher.id)
    assert join_message.answers == [f"Присоединение выполнено. teacher_user_id: {teacher.id}"]
    assert link is not None
    assert link["teacher_user_id"] == teacher.id
    assert link["student_user_id"] == teacher.id
    assert teacher_role == "teacher"


def test_assign_handler_creates_assignment_and_notifies_student(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(213, "Teacher")
    student = make_user(214, "Student")
    learning_item_id = seed_learning_item()
    db.save_user(teacher)
    db.save_user(student)
    set_user_role(teacher.id, "teacher")

    invite_message = FakeMessage(teacher)
    asyncio.run(invite(invite_message))
    code = invite_message.answers[0].split(": ", 1)[1]
    asyncio.run(join(FakeMessage(student), SimpleNamespace(args=code)))

    assign_message = FakeMessage(teacher)
    asyncio.run(assign(assign_message, SimpleNamespace(args=f"{student.id} {learning_item_id}")))

    assert assign_message.answers == ["Задание создано. assignment_id: 1"]
    assert assign_message.bot.sent_messages[0]["chat_id"] == student.id
    assert assign_message.bot.sent_messages[0]["text"] == "Вам назначено новое задание"
    reply_markup = assign_message.bot.sent_messages[0]["kwargs"]["reply_markup"]
    assert reply_markup.inline_keyboard[0][0].text == "Домашка"


def test_assign_handler_rejects_unlinked_student(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(215, "Teacher")
    student = make_user(216, "Student")
    learning_item_id = seed_learning_item()
    db.save_user(teacher)
    db.save_user(student)
    set_user_role(teacher.id, "teacher")
    message = FakeMessage(teacher)

    asyncio.run(assign(message, SimpleNamespace(args=f"{student.id} {learning_item_id}")))

    assert message.answers == ["Этот ученик не привязан к вашему teacher-профилю."]
