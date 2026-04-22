import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.homework import (
    AssignmentNotFoundError,
    LearningItemNotFoundError,
    MixedWorkspaceAssignmentError,
    StudentWorkspaceMembershipRequiredError,
    TeacherWorkspaceMembershipRequiredError,
    create_assignment,
    create_assignment_from_group,
    get_assignment,
    get_assignment_learning_item_ids,
    get_assignment_progress_snapshot,
    list_active_assignments,
    start_assignment_training_session,
    student_has_active_homework,
)
from englishbot.homework_progress_image import (
    build_assignment_progress_image_snapshot,
    render_homework_progress_image,
)
from englishbot.teacher_student import create_invite, join_with_invite
from englishbot.topics import (
    archive_topic,
    create_topic_for_teacher_workspace,
    rename_topic,
    replace_topic_learning_items,
)
from englishbot.training import (
    create_training_session,
    get_active_training_session,
    get_current_question,
    skip_optional_hard,
    submit_training_answer,
)
from englishbot.user_profiles import set_user_role
from englishbot.vocabulary import (
    archive_learning_item,
    create_learning_item,
    create_learning_item_for_teacher_workspace,
    create_learning_item_translation,
    create_lexeme,
)
from englishbot.workspaces import WORKSPACE_KIND_STUDENT, add_workspace_member, create_workspace, find_shared_workspace_for_teacher_and_student


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


def seed_teacher_learning_items(teacher_user_id: int, count: int) -> list[int]:
    workspace_id = db.get_default_content_workspace_id()
    add_workspace_member(workspace_id, teacher_user_id, "teacher")
    learning_item_ids: list[int] = []
    for index in range(count):
        lexeme_id = create_lexeme(f"lesson-{index + 1}")
        learning_item_id = create_learning_item_for_teacher_workspace(
            teacher_user_id,
            workspace_id,
            lexeme_id,
            f"text-{index + 1}",
        )
        create_learning_item_translation(learning_item_id, "ru", f"слово-{index + 1}")
        learning_item_ids.append(learning_item_id)
    return learning_item_ids


def get_session_item_state(session_id: int, item_order: int) -> sqlite3.Row:
    with db.get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                learning_item_id,
                prompt_text,
                expected_answer,
                item_order,
                current_stage,
                easy_correct_count,
                medium_correct_count,
                correct_streak,
                hard_unlocked,
                hard_completed,
                answer_state,
                is_completed
            FROM training_session_items
            WHERE session_id = ? AND item_order = ?
            """,
            (session_id, item_order),
        ).fetchone()
    assert row is not None
    return row


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
        assignment_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(assignments)")
        }

    assert "assignments" in table_names
    assert "assignment_items" in table_names
    assert "assignment_id" in training_session_columns
    assert "workspace_id" in assignment_columns
    assert "assignment_kind" in assignment_columns
    assert "assignment_mode" in assignment_columns


def test_create_assignment_publishes_teacher_items_into_student_workspace(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    source_learning_item_ids = seed_teacher_learning_items(teacher.id, 2)
    student_workspace = find_shared_workspace_for_teacher_and_student(
        teacher.id,
        student.id,
        kind=WORKSPACE_KIND_STUDENT,
    )

    result = create_assignment(teacher.id, student.id, source_learning_item_ids)
    stored_assignment = get_assignment(int(result["assignment_id"]))

    assert stored_assignment is not None
    assert stored_assignment["workspace_id"] == student_workspace["id"]
    assert result["title"] is None
    assert stored_assignment["title"] is None
    assert stored_assignment["assignment_kind"] == "homework"
    assert stored_assignment["assignment_mode"] == "staged_default"
    assert result["learning_item_ids"] != source_learning_item_ids
    assert len(get_assignment_learning_item_ids(int(result["assignment_id"]))) == 2


def test_init_db_backfills_invalid_assignment_kind_and_mode_to_homework_defaults(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    learning_item_id = seed_teacher_learning_items(teacher.id, 1)[0]
    result = create_assignment(teacher.id, student.id, [learning_item_id])

    with db.get_connection() as connection:
        connection.execute(
            """
            UPDATE assignments
            SET assignment_kind = ?, assignment_mode = ?
            WHERE id = ?
            """,
            ("future_kind", "", int(result["assignment_id"])),
        )

    db.init_db()
    assignment = get_assignment(int(result["assignment_id"]))

    assert assignment is not None
    assert assignment["assignment_kind"] == "homework"
    assert assignment["assignment_mode"] == "staged_default"


def test_create_assignment_rejects_student_without_shared_student_workspace(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(503, "Teacher")
    student = make_user(504, "Student")
    db.save_user(teacher)
    db.save_user(student)
    set_user_role(teacher.id, "teacher")
    source_learning_item_ids = seed_teacher_learning_items(teacher.id, 1)

    with pytest.raises(StudentWorkspaceMembershipRequiredError):
        create_assignment(teacher.id, student.id, source_learning_item_ids)


def test_create_assignment_rejects_teacher_without_source_workspace_membership(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    other_teacher_workspace = create_workspace("Private", kind="teacher")
    lexeme_id = create_lexeme("private-item")
    learning_item_id = create_learning_item(
        lexeme_id,
        "private-item",
        workspace_id=other_teacher_workspace["workspace_id"],
    )
    create_learning_item_translation(learning_item_id, "ru", "частный")

    with pytest.raises(TeacherWorkspaceMembershipRequiredError):
        create_assignment(teacher.id, student.id, [learning_item_id])


def test_create_assignment_rejects_mixed_workspace_items(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    first_item_id = seed_teacher_learning_items(teacher.id, 1)[0]
    second_workspace = create_workspace("Second", kind="teacher")
    add_workspace_member(second_workspace["workspace_id"], teacher.id, "teacher")
    lexeme_id = create_lexeme("second-item")
    second_item_id = create_learning_item_for_teacher_workspace(
        teacher.id,
        second_workspace["workspace_id"],
        lexeme_id,
        "second-item",
    )

    with pytest.raises(MixedWorkspaceAssignmentError):
        create_assignment(teacher.id, student.id, [first_item_id, second_item_id])


def test_student_has_active_homework_tracks_active_assignments(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    learning_item_ids = seed_teacher_learning_items(teacher.id, 1)

    assert student_has_active_homework(student.id) is False

    create_assignment(teacher.id, student.id, learning_item_ids)

    assert student_has_active_homework(student.id) is True


def test_create_assignment_from_group_publishes_topic_and_keeps_snapshot_title(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    teacher_workspace_id = db.get_default_content_workspace_id()
    topic_id = create_topic_for_teacher_workspace(teacher.id, teacher_workspace_id, "weekdays", "Дни недели")
    learning_item_ids = seed_teacher_learning_items(teacher.id, 2)
    replace_topic_learning_items(teacher.id, topic_id, learning_item_ids)

    result = create_assignment_from_group(
        teacher.id,
        student.id,
        teacher_workspace_id,
        "weekdays",
    )
    assignment_id = int(result["assignment_id"])
    rename_topic(teacher.id, topic_id, title="Будни")
    replace_topic_learning_items(teacher.id, topic_id, [learning_item_ids[0]])
    assignment = get_assignment(assignment_id)

    assert assignment is not None
    assert assignment["title"] == "Дни недели"
    assert get_assignment_learning_item_ids(assignment_id) == result["learning_item_ids"]
    assert len(result["learning_item_ids"]) == 2


def test_archived_source_content_cannot_be_assigned_but_existing_assignment_survives(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    source_learning_item_id = seed_teacher_learning_items(teacher.id, 1)[0]
    result = create_assignment(teacher.id, student.id, [source_learning_item_id])
    archive_learning_item(teacher.id, source_learning_item_id)

    assert get_assignment_learning_item_ids(int(result["assignment_id"])) == result["learning_item_ids"]
    with pytest.raises(LearningItemNotFoundError):
        create_assignment(teacher.id, student.id, [source_learning_item_id])


def test_start_assignment_training_session_uses_snapshot_item_ids(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    teacher_workspace_id = db.get_default_content_workspace_id()
    topic_id = create_topic_for_teacher_workspace(teacher.id, teacher_workspace_id, "colors", "Цвета")
    source_learning_item_ids = seed_teacher_learning_items(teacher.id, 2)
    replace_topic_learning_items(teacher.id, topic_id, source_learning_item_ids)
    result = create_assignment_from_group(
        teacher.id,
        student.id,
        teacher_workspace_id,
        "colors",
    )

    training_result = start_assignment_training_session(student.id, int(result["assignment_id"]))
    first_question = training_result["question"]
    active_session = get_active_training_session(student.id)
    replace_topic_learning_items(teacher.id, topic_id, [source_learning_item_ids[0]])
    rename_topic(teacher.id, topic_id, title="Новые цвета")

    assert first_question is not None
    assert training_result["assignment_title"] == "Цвета"
    assert active_session is not None
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

    assert [row["learning_item_id"] for row in stored_items] == result["learning_item_ids"]


def test_start_assignment_training_session_rejects_wrong_student(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    learning_item_ids = seed_teacher_learning_items(teacher.id, 1)
    result = create_assignment(teacher.id, student.id, learning_item_ids)

    with pytest.raises(AssignmentNotFoundError):
        start_assignment_training_session(student.id + 100, int(result["assignment_id"]))


def test_assignment_completion_marks_homework_done(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    learning_item_ids = seed_teacher_learning_items(teacher.id, 1)
    result = create_assignment(teacher.id, student.id, learning_item_ids)

    start_assignment_training_session(student.id, int(result["assignment_id"]))
    for _ in range(4):
        answer_result = submit_training_answer(student.id, "lesson-1")
    answer_result = submit_training_answer(student.id, "lesson-1")

    assert answer_result is not None
    assert answer_result["status"] == "completed"
    assert list_active_assignments(student.id) == []


def test_start_assignment_training_session_resumes_existing_active_session(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    learning_item_ids = seed_teacher_learning_items(teacher.id, 1)
    result = create_assignment(teacher.id, student.id, learning_item_ids, title="Resume me")

    started = start_assignment_training_session(student.id, int(result["assignment_id"]))
    first_session_id = int(started["session_id"])
    first_answer = submit_training_answer(student.id, "lesson-1")
    resumed = start_assignment_training_session(student.id, int(result["assignment_id"]))

    assert first_answer is not None
    assert resumed["resumed"] is True
    assert int(resumed["session_id"]) == first_session_id
    assert resumed["question"] is not None


def test_start_assignment_training_session_resumes_persisted_state_after_switching_flows(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    learning_item_ids = seed_teacher_learning_items(teacher.id, 1)
    result = create_assignment(teacher.id, student.id, learning_item_ids, title="Resume later")

    started = start_assignment_training_session(student.id, int(result["assignment_id"]))
    first_session_id = int(started["session_id"])
    answer_result = submit_training_answer(student.id, "lesson-1")
    create_training_session(student.id, limit=1)

    resumed = start_assignment_training_session(student.id, int(result["assignment_id"]))

    assert answer_result is not None
    assert resumed["resumed"] is True
    assert int(resumed["session_id"]) == first_session_id
    assert resumed["question"] is not None
    assert resumed["question"]["current_stage"] == "easy"
    assert resumed["question"]["easy_correct_count"] == 1


def test_assignment_progress_snapshot_reports_compact_item_statuses(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    learning_item_ids = seed_teacher_learning_items(teacher.id, 2)
    result = create_assignment(teacher.id, student.id, learning_item_ids, title="Status test")

    training_result = start_assignment_training_session(student.id, int(result["assignment_id"]))
    first_session_id = int(training_result["session_id"])
    for _ in range(4):
        current_question = get_current_question(student.id)
        assert current_question is not None
        answer_result = submit_training_answer(student.id, str(current_question["expected_answer"]))
    answer_result = skip_optional_hard(student.id)

    snapshot = get_assignment_progress_snapshot(int(result["assignment_id"]), first_session_id)

    assert answer_result is not None
    assert snapshot["assignment_title"] == "Status test"
    assert snapshot["completed_items"] == 0
    assert snapshot["total_items"] == 2
    assert snapshot["current_item_position"] == 2
    assert snapshot["current_stage"] == "medium"
    assert snapshot["item_statuses"] == ["warm_up", "almost"]


def test_homework_uses_fifth_question_as_hard_after_four_consecutive_correct_answers(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    learning_item_ids = seed_teacher_learning_items(teacher.id, 2)
    result = create_assignment(teacher.id, student.id, learning_item_ids, title="Hard streak")

    start_assignment_training_session(student.id, int(result["assignment_id"]))
    for _ in range(4):
        current_question = get_current_question(student.id)
        assert current_question is not None
        answer_result = submit_training_answer(student.id, str(current_question["expected_answer"]))
        assert answer_result is not None

    hard_question = get_current_question(student.id)

    assert hard_question is not None
    assert hard_question["current_stage"] == "hard"
    assert hard_question["can_skip_hard"] is True


def test_homework_skip_hard_resets_global_streak_and_returns_to_normal_order(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    learning_item_ids = seed_teacher_learning_items(teacher.id, 2)
    result = create_assignment(teacher.id, student.id, learning_item_ids, title="Hard streak")

    started = start_assignment_training_session(student.id, int(result["assignment_id"]))
    session_id = int(started["session_id"])
    for _ in range(4):
        current_question = get_current_question(student.id)
        assert current_question is not None
        answer_result = submit_training_answer(student.id, str(current_question["expected_answer"]))
        assert answer_result is not None

    skip_result = skip_optional_hard(student.id)
    next_question = get_current_question(student.id)
    first_item = get_session_item_state(session_id, 0)

    assert skip_result is not None
    assert first_item["is_completed"] == 0
    assert next_question is not None
    assert next_question["current_stage"] == "medium"
    active_session = get_active_training_session(student.id)
    assert active_session is not None
    assert active_session["homework_correct_streak"] == 0
    assert active_session["homework_hard_mode"] == 0


def test_homework_hard_mode_persists_across_next_words_until_stop_condition(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    learning_item_ids = seed_teacher_learning_items(teacher.id, 3)
    result = create_assignment(teacher.id, student.id, learning_item_ids, title="Hard streak")

    start_assignment_training_session(student.id, int(result["assignment_id"]))
    for _ in range(4):
        current_question = get_current_question(student.id)
        assert current_question is not None
        answer_result = submit_training_answer(student.id, str(current_question["expected_answer"]))
        assert answer_result is not None

    first_hard_question = get_current_question(student.id)
    assert first_hard_question is not None
    assert first_hard_question["current_stage"] == "hard"

    hard_result = submit_training_answer(student.id, str(first_hard_question["expected_answer"]))
    assert hard_result is not None
    assert hard_result["is_correct"] is True

    next_question = get_current_question(student.id)
    active_session = get_active_training_session(student.id)

    assert next_question is not None
    assert next_question["current_stage"] == "hard"
    assert next_question["can_skip_hard"] is True
    assert active_session is not None
    assert active_session["homework_hard_mode"] == 1
    assert active_session["homework_correct_streak"] == 4


def test_homework_resumes_stuck_legacy_hard_item_as_medium_when_hard_mode_is_off(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    learning_item_ids = seed_teacher_learning_items(teacher.id, 1)
    result = create_assignment(teacher.id, student.id, learning_item_ids, title="Legacy hard")
    started = start_assignment_training_session(student.id, int(result["assignment_id"]))
    session_id = int(started["session_id"])

    with db.get_connection() as connection:
        connection.execute(
            """
            UPDATE training_sessions
            SET homework_hard_mode = 0,
                homework_correct_streak = 0
            WHERE id = ?
            """,
            (session_id,),
        )
        connection.execute(
            """
            UPDATE training_session_items
            SET current_stage = 'hard',
                easy_correct_count = 2,
                medium_correct_count = 2,
                hard_completed = 0,
                is_completed = 0
            WHERE session_id = ? AND item_order = 0
            """,
            (session_id,),
        )

    resumed = get_current_question(student.id)
    snapshot = get_assignment_progress_snapshot(int(result["assignment_id"]), session_id)

    assert resumed is not None
    assert resumed["current_stage"] == "medium"
    assert snapshot["current_stage"] == "medium"
    assert snapshot["items"][0]["current_stage"] == "medium"


def test_create_assignment_from_group_uses_explicit_teacher_workspace(tmp_path: Path) -> None:
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
    first_learning_item_ids = seed_teacher_learning_items(teacher.id, 2)
    replace_topic_learning_items(teacher.id, first_topic_id, first_learning_item_ids)

    second_topic_id = create_topic_for_teacher_workspace(
        teacher.id,
        second_workspace["workspace_id"],
        "shared",
        "Вторая тема",
    )
    second_lexeme_id = create_lexeme("workspace-two")
    second_learning_item_id = create_learning_item_for_teacher_workspace(
        teacher.id,
        second_workspace["workspace_id"],
        second_lexeme_id,
        "workspace-two",
    )
    create_learning_item_translation(second_learning_item_id, "ru", "вторая тема")
    replace_topic_learning_items(teacher.id, second_topic_id, [second_learning_item_id])

    result = create_assignment_from_group(
        teacher.id,
        student.id,
        second_workspace["workspace_id"],
        "shared",
    )

    assert result["title"] == "Вторая тема"
    assert len(result["learning_item_ids"]) == 1


def test_create_assignment_from_group_rejects_ambiguous_student_workspace(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    teacher_workspace_id = db.get_default_content_workspace_id()
    topic_id = create_topic_for_teacher_workspace(teacher.id, teacher_workspace_id, "weekdays", "Дни недели")
    learning_item_ids = seed_teacher_learning_items(teacher.id, 1)
    replace_topic_learning_items(teacher.id, topic_id, learning_item_ids)
    extra_student_workspace = create_workspace("Extra Student", kind="student")
    add_workspace_member(extra_student_workspace["workspace_id"], teacher.id, "teacher")
    add_workspace_member(extra_student_workspace["workspace_id"], student.id, "student")

    with pytest.raises(StudentWorkspaceMembershipRequiredError):
        create_assignment_from_group(
            teacher.id,
            student.id,
            teacher_workspace_id,
            "weekdays",
        )


def test_assignment_progress_snapshot_exposes_item_state_for_image_adapter(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    learning_item_ids = seed_teacher_learning_items(teacher.id, 2)
    result = create_assignment(teacher.id, student.id, learning_item_ids, title="Image homework")
    training_result = start_assignment_training_session(student.id, int(result["assignment_id"]))

    for _ in range(4):
        current_question = get_current_question(student.id)
        assert current_question is not None
        answer_result = submit_training_answer(student.id, str(current_question["expected_answer"]))
        assert answer_result is not None

    snapshot = get_assignment_progress_snapshot(
        int(result["assignment_id"]),
        int(training_result["session_id"]),
    )

    assert snapshot["items"][0] == {
        "item_order": 0,
        "learning_item_id": snapshot["items"][0]["learning_item_id"],
        "current_stage": "hard",
        "easy_correct_count": 2,
        "medium_correct_count": 0,
        "correct_streak": 2,
        "hard_unlocked": True,
        "hard_completed": False,
        "is_completed": False,
    }


def test_homework_progress_image_builder_maps_staged_state_into_generator_snapshot(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    learning_item_ids = seed_teacher_learning_items(teacher.id, 1)
    result = create_assignment(teacher.id, student.id, learning_item_ids, title="Image homework")
    training_result = start_assignment_training_session(student.id, int(result["assignment_id"]))

    for _ in range(4):
        current_question = get_current_question(student.id)
        assert current_question is not None
        answer_result = submit_training_answer(student.id, str(current_question["expected_answer"]))
        assert answer_result is not None

    snapshot = build_assignment_progress_image_snapshot(
        student.id,
        int(result["assignment_id"]),
        int(training_result["session_id"]),
    )

    assert snapshot.completed_word_count == 0
    assert snapshot.total_word_count == 1
    assert snapshot.legend_labels == ("start", "warm-up", "almost", "done")
    assert snapshot.hard_legend_label == "hard clear"
    assert snapshot.combo_charge_streak == 4
    assert snapshot.combo_hard_active is True
    assert snapshot.segments[0].word_id == str(training_result["question"]["learning_item_id"])
    assert snapshot.segments[0].progress_value == 1.0
    assert snapshot.segments[0].hard_clear is False


def test_homework_progress_image_combo_uses_session_streak_not_item_totals(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    learning_item_ids = seed_teacher_learning_items(teacher.id, 1)
    result = create_assignment(teacher.id, student.id, learning_item_ids, title="Image homework")
    training_result = start_assignment_training_session(student.id, int(result["assignment_id"]))
    session_id = int(training_result["session_id"])

    with db.get_connection() as connection:
        connection.execute(
            """
            UPDATE training_sessions
            SET homework_correct_streak = 3,
                homework_hard_mode = 0
            WHERE id = ?
            """,
            (session_id,),
        )
        connection.execute(
            """
            UPDATE training_session_items
            SET current_stage = 'medium',
                easy_correct_count = 2,
                medium_correct_count = 5,
                hard_unlocked = 0,
                hard_completed = 0,
                is_completed = 0
            WHERE session_id = ? AND item_order = 0
            """,
            (session_id,),
        )

    snapshot = build_assignment_progress_image_snapshot(
        student.id,
        int(result["assignment_id"]),
        session_id,
    )

    assert snapshot.combo_charge_streak == 3
    assert snapshot.combo_hard_active is False


def test_homework_progress_image_renderer_is_called_with_built_snapshot(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    learning_item_ids = seed_teacher_learning_items(teacher.id, 1)
    result = create_assignment(teacher.id, student.id, learning_item_ids, title="Image homework")
    training_result = start_assignment_training_session(student.id, int(result["assignment_id"]))

    with patch("englishbot.homework_progress_image.render_assignment_progress_image") as render_mock:
        render_mock.return_value = tmp_path / "progress.png"
        output_path = render_homework_progress_image(
            student.id,
            int(result["assignment_id"]),
            int(training_result["session_id"]),
        )

    assert output_path == tmp_path / "progress.png"
    assert render_mock.call_count == 1
    render_snapshot = render_mock.call_args.args[0]
    assert render_snapshot.total_word_count == 1
    assert render_snapshot.segments[0].word_id == str(training_result["question"]["learning_item_id"])
