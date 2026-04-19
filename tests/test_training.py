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


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "training.sqlite3"
    db.init_db()


def seed_user_with_learning_items(item_count: int) -> int:
    user = make_user(301, "Learner")
    db.save_user(user)
    for index in range(item_count):
        lexeme_id = create_lexeme(f"word-{index + 1}")
        learning_item_id = create_learning_item(lexeme_id, f"text-{index + 1}")
        if index == 0:
            create_learning_item_translation(learning_item_id, "uk", "слово-uk")
            create_learning_item_translation(learning_item_id, "ru", "слово-ru")
        elif index == 1:
            create_learning_item_translation(learning_item_id, "uk", "друге")
    return user.id


def test_init_db_creates_training_tables(tmp_path: Path) -> None:
    setup_db(tmp_path)

    with sqlite3.connect(db.DB_PATH) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert "training_sessions" in table_names
    assert "training_session_items" in table_names


def test_create_training_session_persists_active_session_and_item_order(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(6)

    result = create_training_session(user_id)

    session = get_active_training_session(user_id)
    assert session is not None
    assert result["session_id"] == session["id"]
    assert session["current_index"] == 0
    assert session["correct_answers"] == 0
    assert session["total_questions"] == 5
    assert session["status"] == "active"

    with db.get_connection() as connection:
        stored_items = connection.execute(
            """
            SELECT learning_item_id, item_order
            FROM training_session_items
            WHERE session_id = ?
            ORDER BY item_order
            """,
            (session["id"],),
        ).fetchall()

    assert [row["item_order"] for row in stored_items] == [0, 1, 2, 3, 4]
    assert [row["learning_item_id"] for row in stored_items] == [1, 2, 3, 4, 5]


def test_get_current_question_prefers_translation_and_falls_back_to_lexeme(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(3)
    create_training_session(user_id)

    first_question = get_current_question(user_id)
    assert first_question is not None
    assert first_question["prompt"] == "слово-ru"
    assert first_question["expected_answer"] == "word-1"

    submit_training_answer(user_id, "word-1")
    second_question = get_current_question(user_id)
    assert second_question is not None
    assert second_question["prompt"] == "друге"
    assert second_question["expected_answer"] == "word-2"

    submit_training_answer(user_id, "word-2")
    third_question = get_current_question(user_id)
    assert third_question is not None
    assert third_question["prompt"] == "word-3"
    assert third_question["expected_answer"] == "word-3"


def test_submit_training_answer_marks_correct_and_advances_session(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(2)
    create_training_session(user_id)

    result = submit_training_answer(user_id, "  WORD-1  ")
    session = get_active_training_session(user_id)

    assert result is not None
    assert result["is_correct"] is True
    assert result["status"] == "active"
    assert result["correct_answers"] == 1
    assert result["expected_answer"] == "word-1"
    assert result["next_question"]["expected_answer"] == "word-2"
    assert session is not None
    assert session["current_index"] == 1
    assert session["correct_answers"] == 1


def test_submit_training_answer_marks_incorrect_and_still_advances_session(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(2)
    create_training_session(user_id)

    result = submit_training_answer(user_id, "wrong")
    session = get_active_training_session(user_id)

    assert result is not None
    assert result["is_correct"] is False
    assert result["status"] == "active"
    assert result["correct_answers"] == 0
    assert result["expected_answer"] == "word-1"
    assert result["next_question"]["expected_answer"] == "word-2"
    assert session is not None
    assert session["current_index"] == 1
    assert session["correct_answers"] == 0


def test_submit_training_answer_completes_session_and_returns_summary(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(2)
    create_training_session(user_id)

    submit_training_answer(user_id, "word-1")
    result = submit_training_answer(user_id, "wrong")

    assert result is not None
    assert result["is_correct"] is False
    assert result["status"] == "completed"
    assert result["summary"] == {"total_questions": 2, "correct_answers": 1}
    assert get_active_training_session(user_id) is None
    assert get_current_question(user_id) is None

    with db.get_connection() as connection:
        completed_session = connection.execute(
            """
            SELECT status, current_index, correct_answers, total_questions
            FROM training_sessions
            WHERE telegram_user_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()

    assert completed_session["status"] == "completed"
    assert completed_session["current_index"] == 2
    assert completed_session["correct_answers"] == 1
    assert completed_session["total_questions"] == 2


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
