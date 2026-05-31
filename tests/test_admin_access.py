import asyncio
import sys
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText
from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.admin_access import (
    AdminAccessDeniedError,
    add_user_to_student_workspace,
    ensure_admin_access,
    ensure_default_spaces_for_user,
    ensure_shared_family_workspace,
    grant_teacher_role,
)
from englishbot.admin_handlers import open_admin
from englishbot.homework import create_assignment
from englishbot.topic_access import grant_topic_access, list_accessible_topics
from englishbot.topics import create_topic_for_teacher_workspace, replace_topic_learning_items
from englishbot.user_profiles import get_user_role
from englishbot.vocabulary import (
    create_learning_item_for_teacher_workspace,
    create_learning_item_translation,
    create_lexeme,
)
from englishbot.workspaces import (
    find_shared_workspace_for_teacher_and_student,
    get_workspace_member,
)


class FakeMessage:
    def __init__(self, user: User) -> None:
        self.from_user = user
        self.answers: list[str] = []
        self.answer_kwargs: list[dict[str, object]] = []

    async def answer(self, text: str, **kwargs: object) -> None:
        self.answers.append(text)
        self.answer_kwargs.append(kwargs)


class FakeEditableMessage:
    async def edit_text(self, text: str, **kwargs: object) -> None:
        raise TelegramBadRequest(
            method=EditMessageText(text=text, chat_id=1, message_id=1, reply_markup=kwargs.get("reply_markup")),
            message="Bad Request: message is not modified: specified new message content and reply markup are exactly the same as a current content and reply markup of the message",
        )


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "admin_access.sqlite3"
    db.init_db()


def test_admin_access_only_allows_configured_admin(tmp_path: Path, monkeypatch) -> None:
    setup_db(tmp_path)
    monkeypatch.setenv("ENGLISHBOT_ADMIN_TELEGRAM_USER_ID", "9001")

    assert ensure_admin_access(9001) == 9001

    try:
        ensure_admin_access(9002)
    except AdminAccessDeniedError:
        pass
    else:
        raise AssertionError("Expected AdminAccessDeniedError for non-admin user")


def test_open_admin_handler_rejects_non_admin(tmp_path: Path, monkeypatch) -> None:
    setup_db(tmp_path)
    monkeypatch.setenv("ENGLISHBOT_ADMIN_TELEGRAM_USER_ID", "9101")
    message = FakeMessage(make_user(9102, "Outsider"))

    asyncio.run(open_admin(message))

    assert message.answers == [
        "Command /admin is available only to the configured admin user."
    ]


def test_open_admin_handler_shows_registered_users_for_admin(
    tmp_path: Path,
    monkeypatch,
) -> None:
    setup_db(tmp_path)
    monkeypatch.setenv("ENGLISHBOT_ADMIN_TELEGRAM_USER_ID", "9201")
    admin_user = make_user(9201, "Admin")
    learner = make_user(9202, "Learner")
    db.save_user(admin_user)
    db.save_user(learner)
    message = FakeMessage(admin_user)

    asyncio.run(open_admin(message))

    assert len(message.answers) == 1
    assert "Admin access" in message.answers[0]
    assert "Admin" in message.answers[0]
    assert "Learner" in message.answers[0]
    assert "reply_markup" in message.answer_kwargs[0]


def test_ensure_default_spaces_for_user_is_idempotent(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(9301, "Parent")
    db.save_user(user)

    first_result = ensure_default_spaces_for_user(user.id)
    second_result = ensure_default_spaces_for_user(user.id)

    assert first_result == second_result
    assert get_workspace_member(first_result["teacher_workspace_id"], user.id)["role"] == "teacher"
    assert get_workspace_member(first_result["student_workspace_id"], user.id)["role"] == "student"


def test_grant_teacher_role_keeps_student_workspace_membership(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(9401, "TeacherLater")
    db.save_user(user)
    workspace_ids = ensure_default_spaces_for_user(user.id)

    grant_teacher_role(user.id)

    assert get_user_role(user.id) == "teacher"
    assert (
        get_workspace_member(workspace_ids["student_workspace_id"], user.id)["role"]
        == "student"
    )


def test_admin_bootstrap_supports_assign_and_grant_without_invite_join(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(9501, "Parent")
    student = make_user(9502, "Child")
    db.save_user(teacher)
    db.save_user(student)

    teacher_workspace_ids = ensure_default_spaces_for_user(teacher.id)
    ensure_default_spaces_for_user(student.id)
    grant_teacher_role(teacher.id)

    family_workspace = ensure_shared_family_workspace()
    add_user_to_student_workspace(family_workspace["workspace_id"], teacher.id, "teacher")
    add_user_to_student_workspace(family_workspace["workspace_id"], student.id, "student")

    teacher_workspace_id = teacher_workspace_ids["teacher_workspace_id"]
    lexeme_id = create_lexeme("apple")
    learning_item_id = create_learning_item_for_teacher_workspace(
        teacher.id,
        teacher_workspace_id,
        lexeme_id,
        "apple",
    )
    create_learning_item_translation(learning_item_id, "ru", "яблоко")
    topic_id = create_topic_for_teacher_workspace(
        teacher.id,
        teacher_workspace_id,
        "family-pack",
        "Family Pack",
    )
    replace_topic_learning_items(teacher.id, topic_id, [learning_item_id])

    assignment = create_assignment(
        teacher.id,
        student.id,
        [learning_item_id],
        title="Family Homework",
    )
    topic_access = grant_topic_access(
        teacher.id,
        student.id,
        teacher_workspace_id,
        "family-pack",
    )
    shared_workspace = find_shared_workspace_for_teacher_and_student(
        teacher.id,
        student.id,
        kind="student",
    )

    assert assignment["assignment_id"] == 1
    assert topic_access["granted"] is True
    assert topic_access["topic_name"] == "family-pack"
    assert shared_workspace is not None
    assert shared_workspace["id"] == family_workspace["workspace_id"]
    assert [topic["name"] for topic in list_accessible_topics(student.id)] == ["family-pack"]


def test_admin_screen_edit_ignores_message_not_modified() -> None:
    from englishbot.admin_handlers import _edit_admin_screen

    class FakeCallback:
        def __init__(self) -> None:
            self.message = FakeEditableMessage()

    asyncio.run(
        _edit_admin_screen(
            FakeCallback(),
            "same text",
            reply_markup=None,
        )
    )
