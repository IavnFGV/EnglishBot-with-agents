import sqlite3
import sys
from pathlib import Path

import pytest
from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.families import create_family, create_family_learning_item
from englishbot.training import (
    NoLearningItemsError,
    create_training_session_for_learning_items,
    get_session_outcome,
    resume_training_session,
    get_item_progress_status,
    create_training_session,
    get_active_training_session,
    get_current_question,
    skip_optional_hard,
    submit_training_answer,
)
from englishbot.user_profiles import set_user_hint_language
from englishbot.vocabulary import (
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
    family = create_family("Home", user.id)
    for index in range(item_count):
        lexeme_id = create_lexeme(f"word-{index + 1}")
        learning_item_id = create_family_learning_item(
            int(family["id"]),
            lexeme_id,
            f"text-{index + 1}",
        )
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


def answer_current_question(user_id: int) -> dict[str, object]:
    question = get_current_question(user_id)
    assert question is not None
    result = submit_training_answer(user_id, str(question["expected_answer"]))
    assert result is not None
    return result


def start_fixed(user_id: int, mode: str = "easy", count: int = 3):
    return create_training_session_for_learning_items(user_id, list(range(1, count + 1)), training_mode=mode)


@pytest.mark.parametrize("mode,type_name", [("easy", "multiple_choice"), ("medium", "jumbled_letters"), ("hard", "typed_answer")])
def test_selected_mode_needs_one_correct_answer_per_word(tmp_path, mode, type_name):
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(3)
    result = start_fixed(user_id, mode)
    for item_id in range(1, 4):
        question = get_current_question(user_id)
        assert question["learning_item_id"] == item_id
        assert question["exercise_type"] == type_name
        answer_current_question(user_id)
    assert get_current_question(user_id) is None
    assert get_session_outcome(result["session_id"]) == {"completed": 3, "deferred": 0, "assisted": 0}


def test_wrong_word_returns_after_other_words(tmp_path):
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(3)
    start_fixed(user_id)
    submit_training_answer(user_id, "wrong")
    assert get_current_question(user_id)["learning_item_id"] == 2
    answer_current_question(user_id)
    answer_current_question(user_id)
    assert get_current_question(user_id)["learning_item_id"] == 1
    answer_current_question(user_id)
    assert get_current_question(user_id) is None


def test_three_failures_end_round_without_marking_word_learned(tmp_path):
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(3)
    result = start_fixed(user_id, count=1)
    for _ in range(3):
        answer = submit_training_answer(user_id, "wrong")
    assert answer["status"] == "completed"
    assert answer["deferred"] is True
    assert get_session_outcome(result["session_id"])["completed"] == 0
    assert get_session_outcome(result["session_id"])["deferred"] == 1
    from englishbot.families import get_user_progress
    assert get_user_progress(user_id, 1)["status"] == "needs_review"


def test_help_keeps_same_word_and_requires_correct_medium_answer(tmp_path):
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(3)
    result = start_fixed(user_id, "hard")
    before = get_current_question(user_id)
    helped = skip_optional_hard(user_id)["next_question"]
    assert helped["learning_item_id"] == before["learning_item_id"]
    assert helped["current_stage"] == "medium"
    assert helped["used_help"] is True
    assert helped["question_version"] > before["question_version"]
    assert get_session_outcome(result["session_id"])["completed"] == 0
    answer_current_question(user_id)
    assert get_current_question(user_id)["current_stage"] == "hard"
    assert get_session_outcome(result["session_id"])["assisted"] == 1


def test_mode_help_and_pending_letters_survive_restart(tmp_path):
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(3)
    result = start_fixed(user_id, "hard")
    skip_optional_hard(user_id)
    from englishbot.training import append_medium_answer_letter, get_training_session
    append_medium_answer_letter(user_id, 0)
    before = get_current_question(user_id)
    db.init_db()
    assert get_training_session(result["session_id"])["training_mode"] == "hard"
    assert get_current_question(user_id) == before


def test_selection_prioritizes_errors_then_new_words_then_oldest_review(tmp_path):
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(8)
    from englishbot.families import upsert_user_progress
    for item_id in range(1, 7):
        upsert_user_progress(user_id, item_id, status="done")
    with db.get_connection() as connection:
        for item_id in range(1, 7):
            connection.execute("UPDATE user_progress SET last_answered_at = ? WHERE learning_item_id = ?", (f"2026-01-0{item_id}", item_id))
    upsert_user_progress(user_id, 5, status="needs_review")
    result = create_training_session(user_id)
    with db.get_connection() as connection:
        selected = [row[0] for row in connection.execute("SELECT learning_item_id FROM training_session_items WHERE session_id = ? ORDER BY item_order", (result["session_id"],))]
    assert selected[0] == 5
    assert set(selected[1:3]) == {7, 8}
    assert selected[3:] == [1, 2]
    for _ in selected:
        answer_current_question(user_id)
    next_result = create_training_session(user_id)
    assert next_result["question"]["learning_item_id"] == 3


def test_no_items_without_family_and_invalid_mode(tmp_path):
    setup_db(tmp_path)
    with pytest.raises(NoLearningItemsError):
        create_training_session(123)
    user_id = seed_user_with_learning_items(3)
    with pytest.raises(ValueError):
        create_training_session(user_id, training_mode="unknown")
    with pytest.raises(ValueError):
        create_training_session(user_id, limit=0)


def test_session_keeps_snapshotted_prompt_after_edit(tmp_path):
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(3)
    result = start_fixed(user_id)
    with db.get_connection() as connection:
        connection.execute("UPDATE training_session_items SET prompt_text = 'saved prompt' WHERE session_id = ? AND item_order = 0", (result["session_id"],))
    assert get_current_question(user_id)["prompt"] == "saved prompt"


def test_hint_language_applies_to_mode_and_help(tmp_path):
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(3)
    create_learning_item_translation(1, "bg", "дума")
    set_user_hint_language(user_id, "bg")
    start_fixed(user_id, "hard")
    assert get_current_question(user_id)["hint_text"] == "дума"
    skip_optional_hard(user_id)
    assert get_current_question(user_id)["hint_text"] == "дума"


def test_schema_upgrade_preserves_unfinished_cards_and_normalizes_boost(tmp_path):
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(3)
    result = start_fixed(user_id, "hard")
    with db.get_connection() as connection:
        connection.execute("ALTER TABLE training_sessions DROP COLUMN training_mode")
        for column in ("failed_attempts", "used_help", "is_deferred"):
            connection.execute(f"ALTER TABLE training_session_items DROP COLUMN {column}")
        connection.execute("ALTER TABLE homework_assignments DROP COLUMN training_mode")
        connection.execute("UPDATE training_sessions SET homework_hard_mode = 1, homework_correct_streak = 4")
    db.init_db()
    assert get_current_question(user_id)["current_stage"] == "hard"
    assert get_session_outcome(result["session_id"])["completed"] == 0
    answer_current_question(user_id)
    assert get_session_outcome(result["session_id"])["completed"] == 1
    db.init_db()
    assert get_session_outcome(result["session_id"])["completed"] == 1


def test_help_and_medium_letters_use_original_word_after_live_edit(tmp_path):
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(3)
    start_fixed(user_id, "hard")
    with db.get_connection() as connection:
        connection.execute("UPDATE lexemes SET lemma = 'changed' WHERE id = 1")
    skip_optional_hard(user_id)
    question = get_current_question(user_id)
    assert question["expected_answer"] == "word-1"
    assert sorted(question["jumbled_letters"]) == sorted("word-1")
    assert question["hint_text"] == "слово-1"


def test_correct_answer_after_mistake_is_still_prioritized_for_review(tmp_path):
    setup_db(tmp_path)
    user_id = seed_user_with_learning_items(3)
    start_fixed(user_id, count=1)
    submit_training_answer(user_id, "wrong")
    answer_current_question(user_id)
    from englishbot.families import get_user_progress
    assert get_user_progress(user_id, 1)["status"] == "needs_review"
    start_fixed(user_id, count=1)
    answer_current_question(user_id)
    assert get_user_progress(user_id, 1)["status"] == "done"
