import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.families import (
    add_family_member,
    create_family,
    create_family_learning_item,
    create_homework_assignment,
)
from englishbot.homework import (
    get_active_assignment_training_session,
    get_assignment,
    get_assignment_progress_snapshot,
    list_active_assignments,
    start_assignment_training_session,
)
from englishbot.homework_progress_image import (
    build_assignment_progress_image_snapshot,
    render_homework_progress_image,
)
from englishbot.training import get_current_question, submit_training_answer, skip_optional_hard
import pytest
from englishbot.vocabulary import create_learning_item_translation, create_lexeme


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "homework.sqlite3"
    db.init_db()


def seed_family_parent_and_child() -> tuple[sqlite3.Row, User, User]:
    parent = make_user(501, "Parent")
    child = make_user(502, "Child")
    db.save_user(parent)
    db.save_user(child)
    family = create_family("Home", parent.id)
    add_family_member(int(family["id"]), child.id)
    return family, parent, child


def seed_family_learning_items(family_id: int, count: int, *, prefix: str) -> list[int]:
    learning_item_ids: list[int] = []
    for index in range(count):
        lexeme_id = create_lexeme(f"{prefix}-{index + 1}")
        learning_item_id = create_family_learning_item(family_id, lexeme_id, f"{prefix}-{index + 1}")
        create_learning_item_translation(learning_item_id, "ru", f"слово-{index + 1}")
        learning_item_ids.append(learning_item_id)
    return learning_item_ids


def test_init_db_creates_family_homework_tables_and_training_column(tmp_path: Path) -> None:
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

    assert "homework_assignments" in table_names
    assert "homework_assignment_items" in table_names
    assert "assignments" not in table_names
    assert "assignment_items" not in table_names
    assert "student_topic_access" not in table_names
    assert "assignment_id" not in training_session_columns
    assert "family_homework_assignment_id" in training_session_columns


def test_list_active_assignments_returns_family_homework(tmp_path: Path) -> None:
    setup_db(tmp_path)
    family, parent, child = seed_family_parent_and_child()
    item_id = seed_family_learning_items(int(family["id"]), 1, prefix="fruit")[0]
    create_homework_assignment(
        int(family["id"]),
        parent.id,
        child.id,
        [item_id],
        title="Family fruit",
    )

    assignments = list_active_assignments(child.id)

    assert len(assignments) == 1
    assert assignments[0]["assignment_source"] == "family"
    assert assignments[0]["title"] == "Family fruit"
    assert int(assignments[0]["item_count"]) == 1


@pytest.mark.parametrize("mode", ["easy", "medium", "hard"])
def test_homework_uses_selected_mode_and_one_answer_per_word(tmp_path, mode):
    setup_db(tmp_path)
    family, parent, child = seed_family_parent_and_child()
    ids = seed_family_learning_items(int(family["id"]), 3, prefix="mode")
    assignment_id = create_homework_assignment(int(family["id"]), parent.id, child.id, ids, training_mode=mode)
    first = start_assignment_training_session(child.id, assignment_id)
    for index in range(3):
        question = get_current_question(child.id)
        assert question["current_stage"] == mode
        submit_training_answer(child.id, str(question["expected_answer"]))
        snapshot = get_assignment_progress_snapshot(assignment_id, first["session_id"])
        assert snapshot["completed_items"] == index + 1
        assert not snapshot["homework_hard_mode"]
    assert get_assignment(assignment_id)["status"] == "completed"


def test_deferred_homework_can_resume_without_repeating_completed_words(tmp_path):
    setup_db(tmp_path)
    family, parent, child = seed_family_parent_and_child()
    ids = seed_family_learning_items(int(family["id"]), 3, prefix="resume")
    assignment_id = create_homework_assignment(int(family["id"]), parent.id, child.id, ids)
    first = start_assignment_training_session(child.id, assignment_id)
    submit_training_answer(child.id, "wrong")
    for _ in range(2):
        submit_training_answer(child.id, str(get_current_question(child.id)["expected_answer"]))
    submit_training_answer(child.id, "wrong")
    submit_training_answer(child.id, "wrong")
    assert get_current_question(child.id) is None
    assert get_assignment(assignment_id)["status"] == "active"
    second = start_assignment_training_session(child.id, assignment_id)
    assert second["session_id"] == first["session_id"]
    assert second["resumed"] is True
    assert second["question"]["learning_item_id"] == ids[0]
    submit_training_answer(child.id, str(second["question"]["expected_answer"]))
    assert get_assignment(assignment_id)["status"] == "completed"


def test_homework_help_persists_and_progress_counts_completed_words(tmp_path):
    setup_db(tmp_path)
    family, parent, child = seed_family_parent_and_child()
    ids = seed_family_learning_items(int(family["id"]), 3, prefix="help")
    assignment_id = create_homework_assignment(int(family["id"]), parent.id, child.id, ids, training_mode="hard")
    first = start_assignment_training_session(child.id, assignment_id)
    skip_optional_hard(child.id)
    second = start_assignment_training_session(child.id, assignment_id)
    assert second["question"]["current_stage"] == "medium"
    initial = build_assignment_progress_image_snapshot(child.id, assignment_id, first["session_id"])
    assert initial.segments[0].progress_value == 0
    submit_training_answer(child.id, str(second["question"]["expected_answer"]))
    image = build_assignment_progress_image_snapshot(child.id, assignment_id, first["session_id"])
    assert image.segments[0].progress_value == 1
    assert image.segments[0].hard_clear is False
    snapshot = get_assignment_progress_snapshot(assignment_id, first["session_id"])
    assert snapshot["items"][0]["used_help"] is True
    assert snapshot["items"][1]["current_stage"] == "hard"


def test_render_homework_progress_image_passes_built_snapshot(tmp_path: Path) -> None:
    setup_db(tmp_path)
    family, parent, child = seed_family_parent_and_child()
    item_id = seed_family_learning_items(int(family["id"]), 1, prefix="render")[0]
    assignment_id = create_homework_assignment(
        int(family["id"]),
        parent.id,
        child.id,
        [item_id],
        title="Render homework",
    )
    result = start_assignment_training_session(child.id, assignment_id)

    with patch("englishbot.homework_progress_image.render_assignment_progress_image") as render_mock:
        render_mock.return_value = Path("/tmp/family-progress.png")
        output_path = render_homework_progress_image(
            child.id,
            assignment_id,
            int(result["session_id"]),
        )

    assert output_path == Path("/tmp/family-progress.png")
    render_mock.assert_called_once()
