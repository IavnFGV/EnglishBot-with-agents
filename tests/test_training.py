import sqlite3
import sys
from pathlib import Path

from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.training import (
    NoLearningItemsError,
    create_training_session,
    get_active_training_session,
    get_current_question,
    submit_training_answer,
)
from englishbot.vocabulary import (
    create_learning_item,
    create_learning_item_translation,
    create_lexeme,
)
from englishbot.workspaces import add_workspace_member


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "training.sqlite3"
    db.init_db()


def seed_user_with_learning_items(item_count: int) -> int:
    user = make_user(301, "Learner")
    db.save_user(user)
    add_workspace_member(db.get_default_content_workspace_id(), user.id, "teacher")
    for index in range(item_count):
        lexeme_id = create_lexeme(f"word-{index + 1}")
        learning_item_id = create_learning_item(lexeme_id, f"text-{index + 1}")
        create_learning_item_translation(learning_item_id, "ru", f"слово-{index + 1}")
    return user.id


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
                is_completed
            FROM training_session_items
            WHERE session_id = ? AND item_order = ?
            """,
            (session_id, item_order),
        ).fetchone()
    assert row is not None
    return row


def answer_current_question(user_id: int) -> dict[str, object]:
    question = get_current_question(user_id)
    assert question is not None
    result = submit_training_answer(user_id, str(question["expected_answer"]))
    assert result is not None
    return result


def test_init_db_creates_training_tables_with_staged_columns(tmp_path: Path) -> None:
    setup_db(tmp_path)

    with sqlite3.connect(db.DB_PATH) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        training_item_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(training_session_items)")
        }
        training_session_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(training_sessions)")
        }

    assert "training_sessions" in table_names
    assert "training_session_items" in table_names
    assert {
        "progress_message_id",
        "current_question_message_id",
    }.issubset(training_session_columns)
    assert {
        "prompt_text",
        "expected_answer",
        "current_stage",
        "easy_correct_count",
        "medium_correct_count",
        "correct_streak",
        "hard_unlocked",
        "is_completed",
    }.issubset(training_item_columns)


def test_new_sessions_initialize_easy_stage_and_zero_counters(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(3)

    result = create_training_session(user_id)
    session_id = int(result["session_id"])
    first_item = get_session_item_state(session_id, 0)

    assert first_item["current_stage"] == "easy"
    assert first_item["easy_correct_count"] == 0
    assert first_item["medium_correct_count"] == 0
    assert first_item["correct_streak"] == 0
    assert first_item["hard_unlocked"] == 0
    assert first_item["is_completed"] == 0
    assert first_item["prompt_text"] == "слово-1"
    assert first_item["expected_answer"] == "word-1"


def test_easy_transitions_to_medium_after_two_correct_answers(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(3)
    session_id = int(create_training_session(user_id)["session_id"])

    answer_current_question(user_id)
    answer_current_question(user_id)
    first_item = get_session_item_state(session_id, 0)

    assert first_item["current_stage"] == "medium"
    assert first_item["easy_correct_count"] == 2
    assert first_item["is_completed"] == 0


def test_medium_stage_completes_item_after_two_more_correct_answers(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(3)
    session_id = int(create_training_session(user_id)["session_id"])

    for _ in range(4):
        answer_current_question(user_id)
    first_item = get_session_item_state(session_id, 0)

    assert first_item["current_stage"] == "medium"
    assert first_item["medium_correct_count"] == 2
    assert first_item["is_completed"] == 1


def test_correct_streak_increments_on_correct_answers(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(3)
    session_id = int(create_training_session(user_id)["session_id"])

    answer_current_question(user_id)
    answer_current_question(user_id)
    streak_state = get_session_item_state(session_id, 0)

    assert streak_state["correct_streak"] == 2


def test_correct_streak_resets_on_wrong_answer(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(3)
    session_id = int(create_training_session(user_id)["session_id"])

    answer_current_question(user_id)
    wrong_result = submit_training_answer(user_id, "wrong")
    first_item = get_session_item_state(session_id, 0)

    assert wrong_result is not None
    assert wrong_result["is_correct"] is False
    assert first_item["correct_streak"] == 0
    assert first_item["current_stage"] == "easy"


def test_hard_unlocks_after_four_correct_answers_in_a_row(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(3)
    session_id = int(create_training_session(user_id)["session_id"])

    for _ in range(4):
        answer_current_question(user_id)
    first_item = get_session_item_state(session_id, 0)

    assert first_item["hard_unlocked"] == 1
    assert first_item["correct_streak"] == 4


def test_completed_items_are_skipped_and_session_advances(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(3)
    create_training_session(user_id)

    for _ in range(4):
        answer_current_question(user_id)
    next_question = get_current_question(user_id)
    active_session = get_active_training_session(user_id)

    assert next_question is not None
    assert next_question["learning_item_id"] == 2
    assert next_question["question_number"] == 2
    assert next_question["current_stage"] == "easy"
    assert active_session is not None
    assert active_session["current_index"] == 1


def test_full_session_completes_when_all_items_are_completed(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(2)
    create_training_session(user_id)

    for _ in range(8):
        result = answer_current_question(user_id)

    assert result["status"] == "completed"
    assert result["summary"] == {"total_questions": 2, "correct_answers": 8}
    assert get_active_training_session(user_id) is None
    assert get_current_question(user_id) is None


def test_persisted_state_can_be_reread_after_updates(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(3)
    session_id = int(create_training_session(user_id)["session_id"])

    answer_current_question(user_id)
    answer_current_question(user_id)
    persisted_question = get_current_question(user_id)
    first_item = get_session_item_state(session_id, 0)

    assert persisted_question is not None
    assert persisted_question["learning_item_id"] == 1
    assert persisted_question["current_stage"] == "medium"
    assert persisted_question["easy_correct_count"] == 2
    assert persisted_question["medium_correct_count"] == 0
    assert persisted_question["correct_streak"] == 2
    assert persisted_question["hard_unlocked"] is False
    assert first_item["current_stage"] == "medium"


def test_active_session_uses_snapshotted_prompt_text_for_compatibility(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(3)
    create_training_session(user_id)

    with db.get_connection() as connection:
        connection.execute(
            """
            UPDATE learning_item_translations
            SET translation_text = ?
            WHERE learning_item_id = ? AND language_code = ?
            """,
            ("новый перевод", 1, "ru"),
        )

    question = get_current_question(user_id)

    assert question is not None
    assert question["prompt"] == "слово-1"


def test_create_training_session_rejects_empty_vocabulary(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(302, "Empty")
    db.save_user(user)

    try:
        create_training_session(user.id)
    except NoLearningItemsError:
        pass
    else:
        raise AssertionError("Expected NoLearningItemsError for empty vocabulary")
