import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.learner_homework import (
    HOMEWORK_ACTION_CONTINUE,
    HOMEWORK_ACTION_START,
    get_learner_homework_overview,
    list_learner_homework,
)
from englishbot.teacher_student import create_invite, join_with_invite
from englishbot.training import create_training_session, submit_training_answer
from englishbot.homework import create_assignment
from englishbot.user_profiles import set_user_role
from englishbot.vocabulary import (
    create_learning_item_for_teacher_workspace,
    create_learning_item_translation,
    create_lexeme,
)
from englishbot.workspaces import add_workspace_member
from aiogram.types import User


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "learner_homework.sqlite3"
    db.init_db()


def seed_linked_teacher_and_student() -> tuple[User, User]:
    teacher = make_user(901, "Teacher")
    student = make_user(902, "Student")
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


def test_list_learner_homework_reports_compact_progress_for_new_and_resumable_assignments(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    first_assignment = create_assignment(
        teacher.id,
        student.id,
        seed_teacher_learning_items(teacher.id, 2, prefix="fresh-homework"),
        title="Fresh homework",
    )
    second_assignment = create_assignment(
        teacher.id,
        student.id,
        seed_teacher_learning_items(teacher.id, 1, prefix="resume-homework"),
        title="Resume homework",
    )

    from englishbot.homework import start_assignment_training_session

    start_assignment_training_session(student.id, int(second_assignment["assignment_id"]))
    submit_training_answer(student.id, "resume-homework-1")
    snapshots = list_learner_homework(student.id)

    assert [snapshot["assignment_id"] for snapshot in snapshots] == [
        int(first_assignment["assignment_id"]),
        int(second_assignment["assignment_id"]),
    ]
    assert snapshots[0]["action_key"] == HOMEWORK_ACTION_START
    assert snapshots[0]["completed_items"] == 0
    assert snapshots[0]["total_items"] == 2
    assert snapshots[1]["action_key"] == HOMEWORK_ACTION_CONTINUE
    assert snapshots[1]["completed_items"] == 0
    assert snapshots[1]["total_items"] == 1
    assert snapshots[1]["current_item_position"] == 1
    assert snapshots[1]["current_stage"] == "easy"


def test_get_learner_homework_overview_reuses_unfinished_assignment_session_after_switching_flows(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    assignment = create_assignment(
        teacher.id,
        student.id,
        seed_teacher_learning_items(teacher.id, 1, prefix="resume-later"),
        title="Resume later",
    )

    from englishbot.homework import start_assignment_training_session

    start_assignment_training_session(student.id, int(assignment["assignment_id"]))
    submit_training_answer(student.id, "resume-later-1")
    create_training_session(student.id, limit=1)

    overview = get_learner_homework_overview(student.id, int(assignment["assignment_id"]))

    assert overview["action_key"] == HOMEWORK_ACTION_CONTINUE
    assert overview["completed_items"] == 0
    assert overview["current_item_position"] == 1
    assert overview["current_stage"] == "easy"
