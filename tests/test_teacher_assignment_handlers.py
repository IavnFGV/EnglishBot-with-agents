import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from aiogram_dialog import ShowMode, StartMode
from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.teacher_assignment_dialog import (
    TeacherAssignmentDialogSG,
    confirm_assignment,
    get_confirm_window_data,
    get_recipients_window_data,
    get_words_window_data,
    go_to_confirm,
    next_word,
    on_topic_selected,
    on_workspace_selected,
    toggle_current_word,
    toggle_recipient,
)
from englishbot.teacher_assignment_handlers import create_assignment_flow
from englishbot.teacher_student import create_invite, join_with_invite
from englishbot.topics import create_topic_for_teacher_workspace, replace_topic_learning_items
from englishbot.user_profiles import set_user_role
from englishbot.vocabulary import (
    create_learning_item_for_teacher_workspace,
    create_learning_item_translation,
    create_lexeme,
)
from englishbot.workspaces import add_workspace_member, create_workspace


class FakeDialogManager:
    def __init__(self, user: User) -> None:
        self.event = SimpleNamespace(from_user=user, chat=SimpleNamespace(id=user.id))
        self.dialog_data: dict[str, object] = {}
        self.start_calls: list[dict[str, object]] = []
        self.switch_calls: list[dict[str, object]] = []
        self.update_calls: list[dict[str, object] | None] = []
        self.done_calls: list[dict[str, object]] = []

    async def start(self, state, mode=None, data=None, **kwargs) -> None:
        self.start_calls.append({"state": state, "mode": mode, "data": data, "kwargs": kwargs})

    async def switch_to(self, state, show_mode=None) -> None:
        self.switch_calls.append({"state": state, "show_mode": show_mode})

    async def update(self, data=None, **kwargs) -> None:
        if data:
            self.dialog_data.update(data)
        self.update_calls.append({"data": data, "kwargs": kwargs})

    async def done(self, result=None, show_mode=None) -> None:
        self.done_calls.append({"result": result, "show_mode": show_mode})


class FakeBot:
    def __init__(self) -> None:
        self.edit_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []
        self.sent_messages: list[dict[str, object]] = []

    async def edit_message_text(self, *, text: str, chat_id: int, message_id: int, parse_mode=None, reply_markup=None):
        self.edit_calls.append(
            {
                "text": text,
                "chat_id": chat_id,
                "message_id": message_id,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
            }
        )

    async def delete_message(self, *, chat_id: int, message_id: int):
        self.delete_calls.append({"chat_id": chat_id, "message_id": message_id})

    async def send_message(self, chat_id: int, text: str, **kwargs: object) -> None:
        self.sent_messages.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})


class FakeMessage:
    def __init__(self, user: User, bot: FakeBot | None = None, message_id: int = 1) -> None:
        self.from_user = user
        self.bot = bot or FakeBot()
        self.chat = SimpleNamespace(id=user.id)
        self.message_id = message_id
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs: object) -> None:
        self.answers.append(text)


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "teacher_assignment.sqlite3"
    db.init_db()


def seed_teacher_with_students(teacher: User, *students: User) -> None:
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    for student in students:
        db.save_user(student)
        invite_code = create_invite(teacher.id)
        join_with_invite(student.id, invite_code)


def seed_teacher_workspace_items(teacher_user_id: int, *, count: int = 3) -> tuple[int, list[int]]:
    workspace = create_workspace("Assignments", kind="teacher")
    workspace_id = int(workspace["workspace_id"])
    add_workspace_member(workspace_id, teacher_user_id, "teacher")
    learning_item_ids: list[int] = []
    for index in range(count):
        lexeme_id = create_lexeme(f"assign-{index + 1}")
        learning_item_id = create_learning_item_for_teacher_workspace(
            teacher_user_id,
            workspace_id,
            lexeme_id,
            f"assign-{index + 1}",
        )
        create_learning_item_translation(learning_item_id, "ru", f"слово-{index + 1}")
        learning_item_ids.append(learning_item_id)
    return workspace_id, learning_item_ids


def seed_teacher_topic(teacher_user_id: int) -> tuple[int, int]:
    workspace_id, learning_item_ids = seed_teacher_workspace_items(teacher_user_id, count=2)
    topic_id = create_topic_for_teacher_workspace(
        teacher_user_id,
        workspace_id,
        "assignment-topic",
        "Assignment Topic",
    )
    replace_topic_learning_items(teacher_user_id, topic_id, learning_item_ids)
    return workspace_id, topic_id


def count_assignments() -> int:
    with db.get_connection() as connection:
        row = connection.execute("SELECT COUNT(*) AS count FROM assignments").fetchone()
    return int(row["count"])


def test_create_assignment_command_starts_dialog_for_teacher(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(801, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    manager = FakeDialogManager(teacher)
    message = FakeMessage(teacher)

    asyncio.run(create_assignment_flow(message, manager))

    assert message.answers == []
    assert manager.start_calls == [
        {
            "state": TeacherAssignmentDialogSG.source_mode,
            "mode": StartMode.RESET_STACK,
            "data": None,
            "kwargs": {},
        }
    ]


def test_create_assignment_command_rejects_non_teacher(tmp_path: Path) -> None:
    setup_db(tmp_path)
    student = make_user(802, "Student")
    db.save_user(student)
    manager = FakeDialogManager(student)
    message = FakeMessage(student)

    asyncio.run(create_assignment_flow(message, manager))

    assert manager.start_calls == []
    assert message.answers == [
        "Command /create_assignment is available only to users with the teacher role."
    ]


def test_topic_path_shows_summary_then_confirm_without_persisting_before_confirm(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(803, "Teacher")
    student = make_user(804, "Student")
    seed_teacher_with_students(teacher, student)
    workspace_id, topic_id = seed_teacher_topic(teacher.id)
    manager = FakeDialogManager(teacher)
    manager.dialog_data["source_mode"] = "topic"
    bot = FakeBot()
    message = FakeMessage(teacher, bot=bot, message_id=55)

    asyncio.run(on_workspace_selected(SimpleNamespace(message=message), None, manager, str(workspace_id)))
    asyncio.run(on_topic_selected(SimpleNamespace(message=message), None, manager, str(topic_id)))
    confirm_view = asyncio.run(get_confirm_window_data(manager))

    assert manager.switch_calls == [
        {"state": TeacherAssignmentDialogSG.topic, "show_mode": None},
        {"state": TeacherAssignmentDialogSG.recipients, "show_mode": ShowMode.SEND},
    ]
    assert "Assignment draft" in bot.edit_calls[0]["text"]
    assert "Topic: Assignment Topic" in bot.edit_calls[0]["text"]
    assert "not selected yet" in confirm_view["screen_text"]
    assert confirm_view["can_confirm"] is False
    assert count_assignments() == 0


def test_words_path_uses_summary_and_current_item_browser(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(805, "Teacher")
    student = make_user(806, "Student")
    seed_teacher_with_students(teacher, student)
    workspace_id, _ = seed_teacher_workspace_items(teacher.id, count=3)
    manager = FakeDialogManager(teacher)
    manager.dialog_data["source_mode"] = "words"
    bot = FakeBot()
    message = FakeMessage(teacher, bot=bot, message_id=77)

    asyncio.run(on_workspace_selected(SimpleNamespace(message=message), None, manager, str(workspace_id)))
    first_view = asyncio.run(get_words_window_data(manager))
    asyncio.run(toggle_current_word(SimpleNamespace(message=message), None, manager))
    asyncio.run(next_word(SimpleNamespace(message=message), None, manager))
    second_view = asyncio.run(get_words_window_data(manager))

    assert manager.switch_calls == [
        {"state": TeacherAssignmentDialogSG.words, "show_mode": ShowMode.SEND},
    ]
    assert "Selected: no" in first_view["screen_text"]
    assert "Selected: no" in second_view["screen_text"]
    assert "Selected: 1" in bot.edit_calls[-1]["text"]
    assert count_assignments() == 0


def test_recipient_skip_keeps_confirm_non_persistent_until_recipient_selected(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(807, "Teacher")
    student = make_user(808, "Student")
    seed_teacher_with_students(teacher, student)
    workspace_id, _ = seed_teacher_workspace_items(teacher.id, count=2)
    manager = FakeDialogManager(teacher)
    manager.dialog_data.update(
        {
            "source_mode": "words",
            "workspace_id": workspace_id,
            "selected_learning_item_ids": [],
        }
    )
    message = FakeMessage(teacher, bot=FakeBot(), message_id=88)

    asyncio.run(toggle_current_word(SimpleNamespace(message=message), None, manager))
    asyncio.run(go_to_confirm(SimpleNamespace(message=message), None, manager))
    confirm_view = asyncio.run(get_confirm_window_data(manager))

    assert confirm_view["can_confirm"] is False
    assert "Choose recipients before final confirm." in confirm_view["screen_text"]
    assert count_assignments() == 0


def test_confirm_creates_expected_assignments_after_recipient_selection(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(809, "Teacher")
    first_student = make_user(810, "First")
    second_student = make_user(811, "Second")
    seed_teacher_with_students(teacher, first_student, second_student)
    workspace_id, _ = seed_teacher_workspace_items(teacher.id, count=2)
    manager = FakeDialogManager(teacher)
    manager.dialog_data.update(
        {
            "source_mode": "words",
            "workspace_id": workspace_id,
            "selected_learning_item_ids": [],
        }
    )
    bot = FakeBot()
    message = FakeMessage(teacher, bot=bot, message_id=99)

    asyncio.run(toggle_current_word(SimpleNamespace(message=message), None, manager))
    recipients_view = asyncio.run(get_recipients_window_data(manager))
    first_recipient_id = recipients_view["recipient_items"][0]["student_user_id"]
    second_recipient_id = recipients_view["recipient_items"][1]["student_user_id"]
    asyncio.run(toggle_recipient(SimpleNamespace(message=message), None, manager, str(first_recipient_id)))
    asyncio.run(toggle_recipient(SimpleNamespace(message=message), None, manager, str(second_recipient_id)))
    asyncio.run(confirm_assignment(SimpleNamespace(message=message), None, manager))

    assert count_assignments() == 2
    assert manager.done_calls == [{"result": {"assignment_count": 2}, "show_mode": ShowMode.SEND}]
    assert len(bot.sent_messages) == 2
    assert message.answers == ["Assignments created: 2."]
