import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.basic_topics_seed import seed_basic_topics
from englishbot.teacher_handlers import (
    TEACHER_CONTENT_TOPIC_PREFIX,
    TEACHER_CONTENT_WORKSPACE_PREFIX,
    assign,
    build_teacher_topics_keyboard,
    build_teacher_workspaces_keyboard,
    invite,
    join,
    open_teacher_topic_preview,
    open_teacher_workspace,
    teacher_content,
)
from englishbot.teacher_student import get_invite, get_teacher_link
from englishbot.user_profiles import get_user_role, set_user_role
from englishbot.vocabulary import (
    create_learning_item,
    create_learning_item_for_teacher_workspace,
    create_learning_item_translation,
    create_lexeme,
)
from englishbot.workspaces import add_workspace_member, create_workspace
from englishbot.topics import create_topic_for_teacher_workspace, link_learning_item_to_topic


class FakeMessage:
    def __init__(self, user: User) -> None:
        self.from_user = user
        self.answers: list[str] = []
        self.answer_kwargs: list[dict[str, object]] = []
        self.bot = FakeBot()

    async def answer(self, text: str, **kwargs: object) -> None:
        self.answers.append(text)
        self.answer_kwargs.append(kwargs)


class FakeBot:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, object]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs: object) -> None:
        self.sent_messages.append(
            {"chat_id": chat_id, "text": text, "kwargs": kwargs}
        )


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
    db.DB_PATH = tmp_path / "teacher_handlers.sqlite3"
    db.init_db()


def seed_learning_item() -> int:
    lexeme_id = create_lexeme("apple")
    learning_item_id = create_learning_item(lexeme_id, "apple")
    create_learning_item_translation(learning_item_id, "ru", "яблоко")
    return learning_item_id


def seed_teacher_topic(
    teacher_user_id: int,
    workspace_id: int,
    *,
    topic_name: str = "fruits",
    topic_title: str = "Fruits",
) -> int:
    lexeme_id = create_lexeme("apple")
    learning_item_id = create_learning_item_for_teacher_workspace(
        teacher_user_id,
        workspace_id,
        lexeme_id,
        "apple",
        image_ref="img://apple",
        audio_ref="audio://apple",
    )
    create_learning_item_translation(learning_item_id, "ru", "яблоко")
    create_learning_item_translation(learning_item_id, "uk", "яблуко")
    topic_id = create_topic_for_teacher_workspace(
        teacher_user_id,
        workspace_id,
        topic_name,
        topic_title,
    )
    link_learning_item_to_topic(topic_id, learning_item_id)
    return topic_id


def test_invite_handler_rejects_non_teacher(tmp_path: Path) -> None:
    setup_db(tmp_path)
    message = FakeMessage(make_user(201, "Student"))

    asyncio.run(invite(message))

    assert message.answers == ["Command /invite is available only to users with the teacher role."]


def test_invite_handler_returns_code_for_teacher(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(202, "Teacher")
    db.save_user(user)
    set_user_role(user.id, "teacher")
    message = FakeMessage(user)

    asyncio.run(invite(message))

    assert len(message.answers) == 1
    assert message.answers[0].startswith("Invite code: ")
    code = message.answers[0].split(": ", 1)[1]
    invite_row = get_invite(code)
    assert invite_row is not None
    assert invite_row["teacher_user_id"] == user.id


def test_join_handler_requires_code(tmp_path: Path) -> None:
    setup_db(tmp_path)
    message = FakeMessage(make_user(203, "Student"))

    asyncio.run(join(message, SimpleNamespace(args=None)))

    assert message.answers == ["Usage: /join <code>"]


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

    assert student_message.answers == [f"Join completed. teacher_user_id: {teacher.id}"]
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
    assert missing_message.answers == ["Invite not found."]

    first_join_message = FakeMessage(first_student)
    asyncio.run(join(first_join_message, SimpleNamespace(args=code)))
    assert first_join_message.answers == [f"Join completed. teacher_user_id: {teacher.id}"]

    second_join_message = FakeMessage(second_student)
    asyncio.run(join(second_join_message, SimpleNamespace(args=code)))
    assert second_join_message.answers == ["This invite has already been used."]


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
        f"Join completed. teacher_user_id: {first_teacher.id}"
    ]

    second_join_message = FakeMessage(student)
    asyncio.run(join(second_join_message, SimpleNamespace(args=second_code)))
    assert second_join_message.answers == ["This student is already linked to a teacher."]


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
    assert join_message.answers == [f"Join completed. teacher_user_id: {teacher.id}"]
    assert link is not None
    assert link["teacher_user_id"] == teacher.id
    assert link["student_user_id"] == teacher.id
    assert teacher_role == "teacher"


def test_assign_handler_creates_assignment_and_notifies_student(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(213, "Teacher")
    student = make_user(214, "Student")
    db.save_user(teacher)
    db.save_user(student)
    set_user_role(teacher.id, "teacher")
    seed_basic_topics()

    invite_message = FakeMessage(teacher)
    asyncio.run(invite(invite_message))
    code = invite_message.answers[0].split(": ", 1)[1]
    asyncio.run(join(FakeMessage(student), SimpleNamespace(args=code)))

    assign_message = FakeMessage(teacher)
    workspace_id = db.get_default_content_workspace_id()
    asyncio.run(assign(assign_message, SimpleNamespace(args=f"{student.id} {workspace_id} weekdays")))

    assert assign_message.answers == ["Assignment created. assignment_id: 1. Title: Дни недели"]
    assert assign_message.bot.sent_messages[0]["chat_id"] == student.id
    assert assign_message.bot.sent_messages[0]["text"] == "You have a new assignment: Дни недели"
    reply_markup = assign_message.bot.sent_messages[0]["kwargs"]["reply_markup"]
    assert reply_markup.inline_keyboard[0][0].text == "Homework"


def test_assign_handler_keeps_legacy_learning_item_id_support(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(217, "Teacher")
    student = make_user(218, "Student")
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

    assert assign_message.answers == ["Assignment created. assignment_id: 1. Title: Homework"]
    assert assign_message.bot.sent_messages[0]["text"] == "You have a new assignment: Homework"


def test_assign_handler_rejects_unlinked_student(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(215, "Teacher")
    student = make_user(216, "Student")
    learning_item_id = seed_learning_item()
    db.save_user(teacher)
    db.save_user(student)
    set_user_role(teacher.id, "teacher")
    add_workspace_member(db.get_default_content_workspace_id(), teacher.id, "teacher")
    message = FakeMessage(teacher)

    asyncio.run(assign(message, SimpleNamespace(args=f"{student.id} {learning_item_id}")))

    assert message.answers == ["This student does not share a workspace with you."]


def test_assign_handler_requires_explicit_workspace_id_for_topic_flow(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(219, "Teacher")
    student = make_user(220, "Student")
    db.save_user(teacher)
    db.save_user(student)
    set_user_role(teacher.id, "teacher")
    seed_basic_topics()

    invite_message = FakeMessage(teacher)
    asyncio.run(invite(invite_message))
    code = invite_message.answers[0].split(": ", 1)[1]
    asyncio.run(join(FakeMessage(student), SimpleNamespace(args=code)))

    message = FakeMessage(teacher)
    asyncio.run(assign(message, SimpleNamespace(args=f"{student.id} weekdays")))

    assert message.answers == [
        "Usage: /assign <student_user_id> <teacher_workspace_id> <topic_name>\n"
        "Or: /assign <student_user_id> <learning_item_id,learning_item_id,...>"
    ]


def test_teacher_content_handler_lists_teacher_workspaces(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(221, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    teacher_workspace = create_workspace("Authoring", kind="teacher")
    student_workspace = create_workspace("Runtime", kind="student")
    add_workspace_member(teacher_workspace["workspace_id"], teacher.id, "teacher")
    add_workspace_member(student_workspace["workspace_id"], teacher.id, "teacher")
    message = FakeMessage(teacher)

    asyncio.run(teacher_content(message))

    assert message.answers == ["Your teacher spaces:"]
    reply_markup = message.answer_kwargs[0]["reply_markup"]
    assert reply_markup.inline_keyboard[0][0].text == "Authoring"
    assert reply_markup.inline_keyboard[0][0].callback_data == (
        f"{TEACHER_CONTENT_WORKSPACE_PREFIX}{teacher_workspace['workspace_id']}"
    )


def test_teacher_content_handler_rejects_non_teacher(tmp_path: Path) -> None:
    setup_db(tmp_path)
    message = FakeMessage(make_user(226, "Student"))

    asyncio.run(teacher_content(message))

    assert message.answers == [
        "Command /teacher_content is available only to users with the teacher role."
    ]


def test_open_teacher_workspace_handler_lists_topics_for_authorized_teacher(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(222, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    workspace = create_workspace("Authoring", kind="teacher")
    add_workspace_member(workspace["workspace_id"], teacher.id, "teacher")
    topic_id = seed_teacher_topic(teacher.id, workspace["workspace_id"], topic_title="Fruits")
    callback_message = FakeMessage(teacher)
    callback = FakeCallback(
        teacher,
        f"{TEACHER_CONTENT_WORKSPACE_PREFIX}{workspace['workspace_id']}",
        callback_message,
    )

    asyncio.run(open_teacher_workspace(callback))

    assert callback.answered is True
    assert callback_message.answers == ["Topics in Authoring:"]
    reply_markup = callback_message.answer_kwargs[0]["reply_markup"]
    assert reply_markup.inline_keyboard[0][0].text == "Fruits (1)"
    assert reply_markup.inline_keyboard[0][0].callback_data == (
        f"{TEACHER_CONTENT_TOPIC_PREFIX}{workspace['workspace_id']}:{topic_id}"
    )


def test_open_teacher_workspace_handler_rejects_unrelated_workspace(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(223, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    workspace = create_workspace("Authoring", kind="teacher")
    callback_message = FakeMessage(teacher)
    callback = FakeCallback(
        teacher,
        f"{TEACHER_CONTENT_WORKSPACE_PREFIX}{workspace['workspace_id']}",
        callback_message,
    )

    asyncio.run(open_teacher_workspace(callback))

    assert callback.answered is True
    assert callback_message.answers == ["This teacher content is not available to you."]


def test_open_teacher_topic_preview_handler_renders_compact_preview(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(224, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    workspace = create_workspace("Authoring", kind="teacher")
    add_workspace_member(workspace["workspace_id"], teacher.id, "teacher")
    topic_id = seed_teacher_topic(teacher.id, workspace["workspace_id"])
    callback_message = FakeMessage(teacher)
    callback = FakeCallback(
        teacher,
        f"{TEACHER_CONTENT_TOPIC_PREFIX}{workspace['workspace_id']}:{topic_id}",
        callback_message,
    )

    asyncio.run(open_teacher_topic_preview(callback))

    assert callback.answered is True
    assert callback_message.answers == [
        "Fruits\n"
        "apple | translations: яблоко, яблуко | image: img://apple | audio: audio://apple"
    ]


def test_open_teacher_topic_preview_handler_rejects_unrelated_topic(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(225, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    first_workspace = create_workspace("Authoring A", kind="teacher")
    second_workspace = create_workspace("Authoring B", kind="teacher")
    add_workspace_member(first_workspace["workspace_id"], teacher.id, "teacher")
    add_workspace_member(second_workspace["workspace_id"], teacher.id, "teacher")
    topic_id = seed_teacher_topic(teacher.id, second_workspace["workspace_id"])
    callback_message = FakeMessage(teacher)
    callback = FakeCallback(
        teacher,
        f"{TEACHER_CONTENT_TOPIC_PREFIX}{first_workspace['workspace_id']}:{topic_id}",
        callback_message,
    )

    asyncio.run(open_teacher_topic_preview(callback))

    assert callback.answered is True
    assert callback_message.answers == ["This teacher content is not available to you."]


def test_teacher_content_keyboards_use_centralized_callback_prefixes() -> None:
    workspace_keyboard = build_teacher_workspaces_keyboard([{"id": 7, "name": "Authoring"}])
    topic_keyboard = build_teacher_topics_keyboard(
        7,
        [{"id": 9, "title": "Fruits", "item_count": 1}],
    )

    assert workspace_keyboard.inline_keyboard[0][0].callback_data == (
        f"{TEACHER_CONTENT_WORKSPACE_PREFIX}7"
    )
    assert topic_keyboard.inline_keyboard[0][0].callback_data == (
        f"{TEACHER_CONTENT_TOPIC_PREFIX}7:9"
    )
