import sqlite3
import sys
from pathlib import Path

import pytest
from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.teacher_student import create_invite, join_with_invite
from englishbot.topic_access import (
    StudentWorkspaceMembershipRequiredError,
    TopicAccessDeniedError,
    grant_topic_access,
    list_accessible_topics,
    start_topic_training_session,
    student_has_topic_access,
)
from englishbot.topics import (
    create_topic_for_teacher_workspace,
    rename_topic,
    replace_topic_learning_items,
)
from englishbot.training import get_active_training_session
from englishbot.user_profiles import set_user_role
from englishbot.vocabulary import create_learning_item_for_teacher_workspace, create_learning_item_translation, create_lexeme
from englishbot.workspaces import (
    WORKSPACE_KIND_STUDENT,
    add_workspace_member,
    create_workspace,
    find_shared_workspace_for_teacher_and_student,
)


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "topic_access.sqlite3"
    db.init_db()


def seed_linked_teacher_and_student() -> tuple[User, User]:
    teacher = make_user(701, "Teacher")
    student = make_user(702, "Student")
    db.save_user(teacher)
    db.save_user(student)
    set_user_role(teacher.id, "teacher")
    invite_code = create_invite(teacher.id)
    join_with_invite(student.id, invite_code)
    return teacher, student


def seed_teacher_topic(teacher_user_id: int) -> int:
    workspace_id = db.get_default_content_workspace_id()
    add_workspace_member(workspace_id, teacher_user_id, "teacher")
    topic_id = create_topic_for_teacher_workspace(teacher_user_id, workspace_id, "weekdays", "Дни недели")
    learning_item_ids: list[int] = []
    for index, lemma in enumerate(["monday", "tuesday"], start=1):
        lexeme_id = create_lexeme(lemma)
        learning_item_id = create_learning_item_for_teacher_workspace(
            teacher_user_id,
            workspace_id,
            lexeme_id,
            lemma,
        )
        create_learning_item_translation(learning_item_id, "ru", f"день-{index}")
        learning_item_ids.append(learning_item_id)
    replace_topic_learning_items(teacher_user_id, topic_id, learning_item_ids)
    return topic_id


def test_init_db_creates_student_topic_access_table(tmp_path: Path) -> None:
    setup_db(tmp_path)

    with sqlite3.connect(db.DB_PATH) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        student_topic_access_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(student_topic_access)")
        }

    assert "student_topic_access" in table_names
    assert "workspace_id" in student_topic_access_columns


def test_grant_topic_access_publishes_topic_into_student_workspace(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    seed_teacher_topic(teacher.id)
    student_workspace = find_shared_workspace_for_teacher_and_student(
        teacher.id,
        student.id,
        kind=WORKSPACE_KIND_STUDENT,
    )

    result = grant_topic_access(
        teacher.id,
        student.id,
        db.get_default_content_workspace_id(),
        "weekdays",
    )

    assert result["granted"] is True
    assert result["topic_name"] == "weekdays"
    assert result["topic_title"] == "Дни недели"
    assert student_workspace is not None
    assert list_accessible_topics(student.id)[0]["workspace_id"] == student_workspace["id"]


def test_list_accessible_topics_returns_granted_topics(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    seed_teacher_topic(teacher.id)
    grant_topic_access(teacher.id, student.id, db.get_default_content_workspace_id(), "weekdays")

    topics = list_accessible_topics(student.id)

    assert [topic["name"] for topic in topics] == ["weekdays"]
    assert [topic["title"] for topic in topics] == ["Дни недели"]
    assert [topic["item_count"] for topic in topics] == [2]


def test_grant_topic_access_rejects_student_without_shared_workspace(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(703, "Teacher")
    student = make_user(704, "Student")
    db.save_user(teacher)
    db.save_user(student)
    set_user_role(teacher.id, "teacher")
    seed_teacher_topic(teacher.id)

    with pytest.raises(StudentWorkspaceMembershipRequiredError):
        grant_topic_access(teacher.id, student.id, db.get_default_content_workspace_id(), "weekdays")


def test_student_has_topic_access_checks_granted_permissions(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    seed_teacher_topic(teacher.id)
    grant_topic_access(teacher.id, student.id, db.get_default_content_workspace_id(), "weekdays")
    accessible_topic = list_accessible_topics(student.id)[0]

    assert student_has_topic_access(student.id, int(accessible_topic["id"])) is True
    assert student_has_topic_access(student.id, 999) is False


def test_start_topic_training_session_uses_published_topic_items(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    seed_teacher_topic(teacher.id)
    grant_topic_access(teacher.id, student.id, db.get_default_content_workspace_id(), "weekdays")
    topic = list_accessible_topics(student.id)[0]

    result = start_topic_training_session(student.id, int(topic["id"]))
    question = result["question"]
    active_session = get_active_training_session(student.id)

    assert question is not None
    assert result["topic_title"] == "Дни недели"
    assert question["prompt"] == "день-1"
    assert active_session is not None
    assert active_session["assignment_id"] is None


def test_active_topic_session_stays_stable_after_source_topic_change(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    source_topic_id = seed_teacher_topic(teacher.id)
    grant_topic_access(teacher.id, student.id, db.get_default_content_workspace_id(), "weekdays")
    topic = list_accessible_topics(student.id)[0]

    result = start_topic_training_session(student.id, int(topic["id"]))
    rename_topic(teacher.id, source_topic_id, title="Новые будни")

    assert result["question"] is not None
    with db.get_connection() as connection:
        stored_rows = connection.execute(
            """
            SELECT learning_item_id
            FROM training_session_items
            WHERE session_id = ?
            ORDER BY item_order
            """,
            (int(result["session_id"]),),
        ).fetchall()

    assert len(stored_rows) == 2


def test_start_topic_training_session_rejects_inaccessible_topic(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    seed_teacher_topic(teacher.id)
    topic_id = create_topic_for_teacher_workspace(teacher.id, db.get_default_content_workspace_id(), "secret", "Секрет")

    with pytest.raises(TopicAccessDeniedError):
        start_topic_training_session(student.id, topic_id)


def test_grant_topic_access_uses_explicit_teacher_workspace(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    first_workspace_id = db.get_default_content_workspace_id()
    second_workspace = create_workspace("Second Authoring", kind="teacher")
    add_workspace_member(second_workspace["workspace_id"], teacher.id, "teacher")

    first_topic_id = create_topic_for_teacher_workspace(
        teacher.id,
        first_workspace_id,
        "shared",
        "Первая тема",
    )
    first_lexeme_id = create_lexeme("first-shared")
    first_learning_item_id = create_learning_item_for_teacher_workspace(
        teacher.id,
        first_workspace_id,
        first_lexeme_id,
        "first-shared",
    )
    create_learning_item_translation(first_learning_item_id, "ru", "первая")
    replace_topic_learning_items(teacher.id, first_topic_id, [first_learning_item_id])

    second_topic_id = create_topic_for_teacher_workspace(
        teacher.id,
        second_workspace["workspace_id"],
        "shared",
        "Вторая тема",
    )
    second_lexeme_id = create_lexeme("second-shared")
    second_learning_item_id = create_learning_item_for_teacher_workspace(
        teacher.id,
        second_workspace["workspace_id"],
        second_lexeme_id,
        "second-shared",
    )
    create_learning_item_translation(second_learning_item_id, "ru", "вторая")
    replace_topic_learning_items(teacher.id, second_topic_id, [second_learning_item_id])

    result = grant_topic_access(
        teacher.id,
        student.id,
        second_workspace["workspace_id"],
        "shared",
    )

    assert result["topic_title"] == "Вторая тема"


def test_grant_topic_access_rejects_ambiguous_student_workspace(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    seed_teacher_topic(teacher.id)
    extra_student_workspace = create_workspace("Extra Student", kind="student")
    add_workspace_member(extra_student_workspace["workspace_id"], teacher.id, "teacher")
    add_workspace_member(extra_student_workspace["workspace_id"], student.id, "student")

    with pytest.raises(StudentWorkspaceMembershipRequiredError):
        grant_topic_access(
            teacher.id,
            student.id,
            db.get_default_content_workspace_id(),
            "weekdays",
        )
