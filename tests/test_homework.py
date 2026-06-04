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
from englishbot.training import get_current_question, submit_training_answer
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


def test_start_assignment_training_session_creates_and_reuses_family_session(tmp_path: Path) -> None:
    setup_db(tmp_path)
    family, parent, child = seed_family_parent_and_child()
    item_id = seed_family_learning_items(int(family["id"]), 1, prefix="pear")[0]
    assignment_id = create_homework_assignment(
        int(family["id"]),
        parent.id,
        child.id,
        [item_id],
        title="Family pear",
    )

    first_result = start_assignment_training_session(child.id, f"family:{assignment_id}")
    question = get_current_question(child.id)
    assert question is not None
    submit_training_answer(child.id, str(question["expected_answer"]))
    second_result = start_assignment_training_session(child.id, assignment_id)
    active_session = get_active_assignment_training_session(child.id, f"family:{assignment_id}")

    assert first_result["resumed"] is False
    assert second_result["resumed"] is True
    assert active_session is not None
    assert int(active_session["id"]) == int(first_result["session_id"])


def test_completed_family_homework_is_marked_completed(tmp_path: Path) -> None:
    setup_db(tmp_path)
    family, parent, child = seed_family_parent_and_child()
    item_id = seed_family_learning_items(int(family["id"]), 1, prefix="plum")[0]
    assignment_id = create_homework_assignment(
        int(family["id"]),
        parent.id,
        child.id,
        [item_id],
        title="Family plum",
    )

    start_assignment_training_session(child.id, assignment_id)
    for _ in range(5):
        question = get_current_question(child.id)
        assert question is not None
        submit_training_answer(child.id, str(question["expected_answer"]))

    assignment = get_assignment(assignment_id)

    assert assignment is not None
    assert assignment["status"] == "completed"


def test_assignment_progress_snapshot_tracks_family_homework_state(tmp_path: Path) -> None:
    setup_db(tmp_path)
    family, parent, child = seed_family_parent_and_child()
    learning_item_ids = seed_family_learning_items(int(family["id"]), 2, prefix="status")
    assignment_id = create_homework_assignment(
        int(family["id"]),
        parent.id,
        child.id,
        learning_item_ids,
        title="Status test",
    )

    result = start_assignment_training_session(child.id, assignment_id)
    question = get_current_question(child.id)
    assert question is not None
    submit_training_answer(child.id, str(question["expected_answer"]))
    session_id = int(result["session_id"])

    snapshot = get_assignment_progress_snapshot(assignment_id, session_id)

    assert snapshot["assignment_ref"] == f"family:{assignment_id}"
    assert snapshot["assignment_source"] == "family"
    assert snapshot["completed_items"] == 0
    assert snapshot["total_items"] == 2
    assert snapshot["current_item_position"] == 2
    assert snapshot["current_stage"] == "easy"
    assert len(snapshot["items"]) == 2


def test_homework_progress_image_builder_uses_family_snapshot(tmp_path: Path) -> None:
    setup_db(tmp_path)
    family, parent, child = seed_family_parent_and_child()
    learning_item_ids = seed_family_learning_items(int(family["id"]), 2, prefix="image")
    assignment_id = create_homework_assignment(
        int(family["id"]),
        parent.id,
        child.id,
        learning_item_ids,
        title="Image homework",
    )
    result = start_assignment_training_session(child.id, assignment_id)

    snapshot = build_assignment_progress_image_snapshot(child.id, assignment_id, int(result["session_id"]))

    assert snapshot.center_label == "Image homework"
    assert snapshot.completed_word_count == 0
    assert snapshot.total_word_count == 2
    assert len(snapshot.segments) == 2


def test_homework_progress_image_does_not_render_hard_pending_word_as_done(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    family, parent, child = seed_family_parent_and_child()
    item_id = seed_family_learning_items(int(family["id"]), 1, prefix="hard-pending")[0]
    assignment_id = create_homework_assignment(
        int(family["id"]),
        parent.id,
        child.id,
        [item_id],
        title="Hard pending homework",
    )
    result = start_assignment_training_session(child.id, assignment_id)

    for _ in range(4):
        question = get_current_question(child.id)
        assert question is not None
        submit_training_answer(child.id, str(question["expected_answer"]))

    snapshot = build_assignment_progress_image_snapshot(child.id, assignment_id, int(result["session_id"]))

    assert snapshot.completed_word_count == 0
    assert snapshot.combo_hard_active is True
    assert len(snapshot.segments) == 1
    assert snapshot.segments[0].progress_value == 0.8
    assert snapshot.segments[0].hard_clear is False


def test_homework_progress_image_uses_step_based_fill_levels(tmp_path: Path) -> None:
    setup_db(tmp_path)
    family, parent, child = seed_family_parent_and_child()
    item_id = seed_family_learning_items(int(family["id"]), 1, prefix="step-fill")[0]
    assignment_id = create_homework_assignment(
        int(family["id"]),
        parent.id,
        child.id,
        [item_id],
        title="Step fill homework",
    )
    result = start_assignment_training_session(child.id, assignment_id)

    initial_snapshot = build_assignment_progress_image_snapshot(child.id, assignment_id, int(result["session_id"]))
    assert initial_snapshot.segments[0].progress_value == 0.0

    expected_progress = [0.2, 0.4, 0.6, 0.8, 1.0]
    for progress_value in expected_progress:
        question = get_current_question(child.id)
        assert question is not None
        submit_training_answer(child.id, str(question["expected_answer"]))
        current_snapshot = build_assignment_progress_image_snapshot(
            child.id,
            assignment_id,
            int(result["session_id"]),
        )
        assert current_snapshot.segments[0].progress_value == progress_value


def test_homework_enters_global_hard_mode_after_four_total_correct_answers(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    family, parent, child = seed_family_parent_and_child()
    learning_item_ids = seed_family_learning_items(int(family["id"]), 2, prefix="no-global-hard")
    assignment_id = create_homework_assignment(
        int(family["id"]),
        parent.id,
        child.id,
        learning_item_ids,
        title="No global hard",
    )
    result = start_assignment_training_session(child.id, assignment_id)

    for _ in range(4):
        question = get_current_question(child.id)
        assert question is not None
        submit_training_answer(child.id, str(question["expected_answer"]))

    snapshot = get_assignment_progress_snapshot(assignment_id, int(result["session_id"]))

    assert snapshot["homework_hard_mode"] is True
    assert snapshot["homework_correct_streak"] == 4
    assert snapshot["current_stage"] == "hard"
    assert snapshot["items"][0]["current_stage"] == "hard"
    assert snapshot["items"][1]["current_stage"] == "easy"
    assert snapshot["items"][0]["hard_unlocked"] is True
    assert snapshot["items"][1]["hard_unlocked"] is True


def test_homework_boost_continues_across_words_after_hard_completion(tmp_path: Path) -> None:
    setup_db(tmp_path)
    family, parent, child = seed_family_parent_and_child()
    learning_item_ids = seed_family_learning_items(int(family["id"]), 5, prefix="boost-flow")
    assignment_id = create_homework_assignment(
        int(family["id"]),
        parent.id,
        child.id,
        learning_item_ids,
        title="Boost flow",
    )
    start_assignment_training_session(child.id, assignment_id)

    for _ in range(4):
        question = get_current_question(child.id)
        assert question is not None
        submit_training_answer(child.id, str(question["expected_answer"]))

    boosted_question = get_current_question(child.id)
    assert boosted_question is not None
    assert boosted_question["learning_item_id"] == learning_item_ids[4]
    assert boosted_question["current_stage"] == "hard"

    submit_training_answer(child.id, str(boosted_question["expected_answer"]))

    next_question = get_current_question(child.id)
    assert next_question is not None
    assert next_question["learning_item_id"] == learning_item_ids[0]
    assert next_question["current_stage"] == "hard"


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
