import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from aiogram_dialog import ShowMode
from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.homework import create_assignment, start_assignment_training_session
from englishbot.homework_dialog import (
    HomeworkDialogSG,
    get_assignments_window_data,
    get_overview_window_data,
    launch_selected_homework,
    select_assignment,
)
from englishbot.teacher_student import create_invite, join_with_invite
from englishbot.training import get_active_training_session, submit_training_answer
from englishbot.user_profiles import set_user_role
from englishbot.vocabulary import (
    create_learning_item_for_teacher_workspace,
    create_learning_item_translation,
    create_lexeme,
)
from englishbot.workspaces import add_workspace_member


class FakeDialogManager:
    def __init__(self, user: User) -> None:
        self.event = SimpleNamespace(from_user=user, chat=SimpleNamespace(id=user.id))
        self.dialog_data: dict[str, object] = {}
        self.switch_calls: list[dict[str, object]] = []
        self.done_calls: list[dict[str, object]] = []

    async def switch_to(self, state, show_mode=None) -> None:
        self.switch_calls.append({"state": state, "show_mode": show_mode})

    async def done(self, result=None, show_mode=None) -> None:
        self.done_calls.append({"result": result, "show_mode": show_mode})

    async def update(self, data=None, **kwargs) -> None:
        if data:
            self.dialog_data.update(data)


class FakeMessage:
    def __init__(self, user: User) -> None:
        self.from_user = user
        self.chat = SimpleNamespace(id=user.id)
        self.answers: list[dict[str, object]] = []
        self.deleted = False
        self._next_message_id = 1
        self.bot = SimpleNamespace()

    async def answer(self, text: str, **kwargs: object) -> SimpleNamespace:
        self.answers.append({"text": text, "kwargs": kwargs})
        message = SimpleNamespace(message_id=self._next_message_id)
        self._next_message_id += 1
        return message

    async def delete(self) -> None:
        self.deleted = True


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "homework_dialog.sqlite3"
    db.init_db()


def seed_linked_teacher_and_student() -> tuple[User, User]:
    teacher = make_user(1001, "Teacher")
    student = make_user(1002, "Student")
    db.save_user(teacher)
    db.save_user(student)
    set_user_role(teacher.id, "teacher")
    invite_code = create_invite(teacher.id)
    join_with_invite(student.id, invite_code)
    return teacher, student


def seed_teacher_learning_items(teacher_user_id: int, count: int, *, prefix: str) -> list[int]:
    workspace_id = db.get_default_content_workspace_id()
    add_workspace_member(workspace_id, teacher_user_id, "teacher")
    learning_item_ids: list[int] = []
    for index in range(count):
        lexeme_id = create_lexeme(f"{prefix}-{index + 1}")
        learning_item_id = create_learning_item_for_teacher_workspace(
            teacher_user_id,
            workspace_id,
            lexeme_id,
            f"text-{index + 1}",
        )
        create_learning_item_translation(learning_item_id, "ru", f"слово-{index + 1}")
        learning_item_ids.append(learning_item_id)
    return learning_item_ids


def test_assignments_window_renders_titles_progress_and_selection_indexes(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    create_assignment(
        teacher.id,
        student.id,
        seed_teacher_learning_items(teacher.id, 2, prefix="dialog-fresh"),
        title="Fresh",
    )
    resumable = create_assignment(
        teacher.id,
        student.id,
        seed_teacher_learning_items(teacher.id, 1, prefix="dialog-resume"),
        title="Resume me",
    )
    start_assignment_training_session(student.id, int(resumable["assignment_id"]))
    submit_training_answer(student.id, "dialog-resume-1")
    manager = FakeDialogManager(student)

    view = asyncio.run(get_assignments_window_data(manager))

    assert "Homework" in view["screen_text"]
    assert "1. Fresh • 0/2 • Start" in view["screen_text"]
    assert "2. Resume me • 0/1 • Continue" in view["screen_text"]
    assert [item["index_label"] for item in view["assignment_items"]] == ["1", "2"]


def test_selecting_assignment_opens_overview_with_continue_state(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    assignment = create_assignment(
        teacher.id,
        student.id,
        seed_teacher_learning_items(teacher.id, 1, prefix="dialog-overview"),
        title="Overview",
    )
    start_assignment_training_session(student.id, int(assignment["assignment_id"]))
    submit_training_answer(student.id, "dialog-overview-1")
    manager = FakeDialogManager(student)

    asyncio.run(select_assignment(None, None, manager, str(assignment["assignment_id"])))
    view = asyncio.run(get_overview_window_data(manager))

    assert manager.switch_calls == [
        {"state": HomeworkDialogSG.overview, "show_mode": None}
    ]
    assert "Title: Overview" in view["screen_text"]
    assert "Items: 1" in view["screen_text"]
    assert "Progress: 0/1" in view["screen_text"]
    assert "Action: Continue" in view["screen_text"]
    assert "Current item: 1/1" in view["screen_text"]
    assert view["action_label"] == "Continue"


def test_launch_selected_homework_reuses_existing_session(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    assignment = create_assignment(
        teacher.id,
        student.id,
        seed_teacher_learning_items(teacher.id, 1, prefix="dialog-reuse"),
        title="Reuse session",
    )
    started = start_assignment_training_session(student.id, int(assignment["assignment_id"]))
    submit_training_answer(student.id, "dialog-reuse-1")
    first_session = get_active_training_session(student.id)
    manager = FakeDialogManager(student)
    manager.dialog_data["assignment_id"] = int(assignment["assignment_id"])
    message = FakeMessage(student)
    callback = SimpleNamespace(from_user=student, message=message)

    asyncio.run(launch_selected_homework(callback, None, manager))

    active_session = get_active_training_session(student.id)
    assert started["resumed"] is False
    assert first_session is not None
    assert active_session is not None
    assert int(active_session["id"]) == int(first_session["id"])
    assert message.deleted is True
    assert manager.done_calls == [{"result": None, "show_mode": ShowMode.NO_UPDATE}]
    assert message.answers == [
        {
            "text": "Homework: Reuse session\nDone 0/1\nCurrent item 1/1\nStage: easy\nItems: 1 warm-up",
            "kwargs": {},
        },
        {
            "text": "Hint: слово-1\nFirst letter: d",
            "kwargs": {"reply_markup": None},
        },
    ]
