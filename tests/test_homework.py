import sqlite3
import sys
from pathlib import Path

import pytest
from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.basic_topics_seed import seed_basic_topics
from englishbot.homework import (
    StudentLinkRequiredError,
    create_assignment,
    create_assignment_from_group,
    get_assignment_learning_item_ids,
    list_active_assignments,
    start_assignment_training_session,
    student_has_active_homework,
)
from englishbot.teacher_student import join_with_invite, create_invite
from englishbot.training import get_active_training_session, submit_training_answer
from englishbot.user_profiles import set_user_role
from englishbot.vocabulary import (
    create_learning_item,
    create_learning_item_translation,
    create_lexeme,
)


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "homework.sqlite3"
    db.init_db()


def seed_linked_teacher_and_student() -> tuple[User, User]:
    teacher = make_user(501, "Teacher")
    student = make_user(502, "Student")
    db.save_user(teacher)
    db.save_user(student)
    set_user_role(teacher.id, "teacher")
    invite_code = create_invite(teacher.id)
    join_with_invite(student.id, invite_code)
    return teacher, student


def seed_learning_items() -> list[int]:
    learning_item_ids: list[int] = []
    for index in range(3):
        lexeme_id = create_lexeme(f"lesson-{index + 1}")
        learning_item_id = create_learning_item(lexeme_id, f"text-{index + 1}")
        create_learning_item_translation(learning_item_id, "ru", f"слово-{index + 1}")
        learning_item_ids.append(learning_item_id)
    return learning_item_ids


def test_init_db_creates_assignment_tables_and_training_assignment_column(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)

    with sqlite3.connect(db.DB_PATH) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        training_session_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(training_sessions)")
        }

    assert "assignments" in table_names
    assert "assignment_items" in table_names
    assert "assignment_id" in training_session_columns


def test_create_assignment_persists_header_and_item_order(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    learning_item_ids = seed_learning_items()

    result = create_assignment(teacher.id, student.id, [learning_item_ids[1], learning_item_ids[0]])

    assignments = list_active_assignments(student.id)
    assert result["assignment_id"] == assignments[0]["id"]
    assert assignments[0]["title"] == "Домашка"
    assert assignments[0]["item_count"] == 2
    assert get_assignment_learning_item_ids(result["assignment_id"]) == [
        learning_item_ids[1],
        learning_item_ids[0],
    ]
    assert result["title"] == "Домашка"
    assert result["notification"] == {
        "student_user_id": student.id,
        "text": "Вам назначено новое задание: Домашка",
    }


def test_create_assignment_rejects_unlinked_student(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(503, "Teacher")
    student = make_user(504, "Student")
    db.save_user(teacher)
    db.save_user(student)
    set_user_role(teacher.id, "teacher")
    learning_item_ids = seed_learning_items()

    with pytest.raises(StudentLinkRequiredError):
        create_assignment(teacher.id, student.id, learning_item_ids[:1])


def test_student_has_active_homework_tracks_active_assignments(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    learning_item_ids = seed_learning_items()

    assert student_has_active_homework(student.id) is False

    create_assignment(teacher.id, student.id, learning_item_ids[:1])

    assert student_has_active_homework(student.id) is True


def test_create_assignment_from_group_uses_named_seeded_pack(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    seed_basic_topics()

    result = create_assignment_from_group(teacher.id, student.id, "weekdays")

    assignments = list_active_assignments(student.id)
    assert result["title"] == "Дни недели"
    assert assignments[0]["title"] == "Дни недели"
    assert assignments[0]["item_count"] == 7
    assert len(get_assignment_learning_item_ids(int(result["assignment_id"]))) == 7
    assert result["notification"]["text"] == "Вам назначено новое задание: Дни недели"


def test_start_assignment_training_session_uses_assigned_items_and_completes_assignment(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    learning_item_ids = seed_learning_items()
    result = create_assignment(teacher.id, student.id, [learning_item_ids[2], learning_item_ids[0]])

    session_result = start_assignment_training_session(student.id, int(result["assignment_id"]))
    first_question = session_result["question"]
    active_session = get_active_training_session(student.id)

    assert first_question is not None
    assert first_question["learning_item_id"] == learning_item_ids[2]
    assert first_question["prompt"] == "слово-3"
    assert active_session is not None
    assert active_session["assignment_id"] == result["assignment_id"]

    submit_training_answer(student.id, "lesson-3")
    completion = submit_training_answer(student.id, "lesson-1")
    assert completion is not None
    assert completion["status"] == "completed"
    assert student_has_active_homework(student.id) is False
