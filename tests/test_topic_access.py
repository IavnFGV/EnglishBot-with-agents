import sqlite3
import sys
from pathlib import Path

import pytest
from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.basic_topics_seed import seed_basic_topics
from englishbot.teacher_student import create_invite, join_with_invite
from englishbot.topic_access import (
    TopicAccessDeniedError,
    grant_topic_access,
    list_accessible_topics,
    start_topic_training_session,
    student_has_topic_access,
)
from englishbot.training import get_active_training_session
from englishbot.user_profiles import set_user_role


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


def test_init_db_creates_student_topic_access_table(tmp_path: Path) -> None:
    setup_db(tmp_path)

    with sqlite3.connect(db.DB_PATH) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert "student_topic_access" in table_names


def test_grant_topic_access_persists_access_row(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    seed_basic_topics()

    result = grant_topic_access(teacher.id, student.id, "weekdays")

    with db.get_connection() as connection:
        row = connection.execute(
            """
            SELECT student_user_id, topic_id, granted_by_teacher_user_id
            FROM student_topic_access
            WHERE student_user_id = ?
            """,
            (student.id,),
        ).fetchone()

    assert result["granted"] is True
    assert result["topic_name"] == "weekdays"
    assert result["topic_title"] == "Дни недели"
    assert row is not None
    assert row["student_user_id"] == student.id
    assert row["granted_by_teacher_user_id"] == teacher.id


def test_list_accessible_topics_returns_granted_topics(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    seed_basic_topics()
    grant_topic_access(teacher.id, student.id, "months")
    grant_topic_access(teacher.id, student.id, "colors")

    topics = list_accessible_topics(student.id)

    assert [topic["name"] for topic in topics] == ["months", "colors"]
    assert [topic["title"] for topic in topics] == ["Месяцы", "Цвета"]
    assert [topic["item_count"] for topic in topics] == [6, 6]


def test_student_has_topic_access_checks_granted_permissions(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    seed_basic_topics()
    grant_topic_access(teacher.id, student.id, "weekdays")
    accessible_topic = list_accessible_topics(student.id)[0]

    assert student_has_topic_access(student.id, int(accessible_topic["id"])) is True
    assert student_has_topic_access(student.id, 999) is False


def test_start_topic_training_session_uses_accessible_topic_items(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    seed_basic_topics()
    grant_topic_access(teacher.id, student.id, "weekdays")
    topic = list_accessible_topics(student.id)[0]

    result = start_topic_training_session(student.id, int(topic["id"]))
    question = result["question"]
    active_session = get_active_training_session(student.id)

    assert question is not None
    assert result["topic_title"] == "Дни недели"
    assert question["prompt"] == "понедельник"
    assert active_session is not None
    assert active_session["assignment_id"] is None
    with db.get_connection() as connection:
        stored_items = connection.execute(
            """
            SELECT learning_item_id
            FROM training_session_items
            WHERE session_id = ?
            ORDER BY item_order
            """,
            (active_session["id"],),
        ).fetchall()

    assert len(stored_items) == 7


def test_start_topic_training_session_rejects_inaccessible_topic(tmp_path: Path) -> None:
    setup_db(tmp_path)
    seed_linked_teacher_and_student()
    seed_basic_topics()

    with pytest.raises(TopicAccessDeniedError):
        start_topic_training_session(702, 1)
