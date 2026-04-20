import sqlite3

from .db import get_connection, utc_now
from .vocabulary import (
    get_learning_item_with_translations,
    get_lexeme,
    list_learning_items,
)


ACTIVE_STATUS = "active"
COMPLETED_STATUS = "completed"
DEFAULT_SESSION_SIZE = 5


class NoLearningItemsError(Exception):
    pass


def create_training_session(
    telegram_user_id: int,
    limit: int = DEFAULT_SESSION_SIZE,
) -> dict[str, object]:
    learning_item_ids = [row["id"] for row in list_learning_items(limit)]
    if not learning_item_ids:
        raise NoLearningItemsError

    return create_training_session_for_learning_items(telegram_user_id, learning_item_ids)


def create_training_session_for_learning_items(
    telegram_user_id: int,
    learning_item_ids: list[int],
    assignment_id: int | None = None,
) -> dict[str, object]:
    if not learning_item_ids:
        raise NoLearningItemsError

    item_snapshots = [_build_item_snapshot(int(learning_item_id)) for learning_item_id in learning_item_ids]
    timestamp = utc_now()
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE training_sessions
            SET status = ?, current_index = total_questions, updated_at = ?
            WHERE telegram_user_id = ? AND status = ?
            """,
            (COMPLETED_STATUS, timestamp, telegram_user_id, ACTIVE_STATUS),
        )
        cursor = connection.execute(
            """
            INSERT INTO training_sessions (
                telegram_user_id,
                assignment_id,
                current_index,
                correct_answers,
                total_questions,
                status,
                created_at,
                updated_at
            )
            VALUES (?, ?, 0, 0, ?, ?, ?, ?)
            """,
            (
                telegram_user_id,
                assignment_id,
                len(item_snapshots),
                ACTIVE_STATUS,
                timestamp,
                timestamp,
            ),
        )
        session_id = int(cursor.lastrowid)
        connection.executemany(
            """
            INSERT INTO training_session_items (
                session_id,
                learning_item_id,
                prompt_text,
                expected_answer,
                item_order
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    session_id,
                    int(snapshot["learning_item_id"]),
                    str(snapshot["prompt"]),
                    str(snapshot["expected_answer"]),
                    item_order,
                )
                for item_order, snapshot in enumerate(item_snapshots)
            ],
        )

    question = get_current_question(telegram_user_id)
    return {
        "session_id": session_id,
        "total_questions": len(item_snapshots),
        "question": question,
    }


def get_active_training_session(telegram_user_id: int) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                id,
                telegram_user_id,
                assignment_id,
                current_index,
                correct_answers,
                total_questions,
                status,
                created_at,
                updated_at
            FROM training_sessions
            WHERE telegram_user_id = ? AND status = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (telegram_user_id, ACTIVE_STATUS),
        ).fetchone()


def get_current_question(telegram_user_id: int) -> dict[str, object] | None:
    session = get_active_training_session(telegram_user_id)
    if session is None:
        return None

    item_snapshot = _get_session_learning_item(session["id"], session["current_index"])
    if item_snapshot is None:
        return None

    return {
        "session_id": session["id"],
        "learning_item_id": int(item_snapshot["learning_item_id"]),
        "current_index": session["current_index"],
        "question_number": session["current_index"] + 1,
        "total_questions": session["total_questions"],
        "prompt": str(item_snapshot["prompt_text"]),
        "expected_answer": str(item_snapshot["expected_answer"]),
    }


def submit_training_answer(
    telegram_user_id: int,
    answer_text: str,
) -> dict[str, object] | None:
    session = get_active_training_session(telegram_user_id)
    question = get_current_question(telegram_user_id)
    if session is None or question is None:
        return None

    is_correct = _normalize_answer(answer_text) == _normalize_answer(
        str(question["expected_answer"])
    )
    updated_correct_answers = session["correct_answers"] + (1 if is_correct else 0)
    updated_index = session["current_index"] + 1
    is_completed = updated_index >= session["total_questions"]
    new_status = COMPLETED_STATUS if is_completed else ACTIVE_STATUS

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE training_sessions
            SET current_index = ?,
                correct_answers = ?,
                status = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                updated_index,
                updated_correct_answers,
                new_status,
                utc_now(),
                session["id"],
            ),
        )

    result: dict[str, object] = {
        "is_correct": is_correct,
        "expected_answer": question["expected_answer"],
        "status": "completed" if is_completed else "active",
        "correct_answers": updated_correct_answers,
        "total_questions": session["total_questions"],
    }
    if is_completed:
        if session["assignment_id"] is not None:
            from .homework import mark_assignment_completed

            mark_assignment_completed(int(session["assignment_id"]))
        result["summary"] = {
            "total_questions": session["total_questions"],
            "correct_answers": updated_correct_answers,
        }
    else:
        result["next_question"] = get_current_question(telegram_user_id)
    return result


def _get_session_learning_item(session_id: int, item_order: int) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT learning_item_id, prompt_text, expected_answer, item_order
            FROM training_session_items
            WHERE session_id = ? AND item_order = ?
            """,
            (session_id, item_order),
        ).fetchone()


def _build_item_snapshot(learning_item_id: int) -> dict[str, object]:
    content = get_learning_item_with_translations(learning_item_id)
    if content is None:
        raise NoLearningItemsError
    learning_item = content["learning_item"]
    translations = content["translations"]
    lexeme = get_lexeme(int(learning_item["lexeme_id"]))
    if lexeme is None:
        raise NoLearningItemsError
    return {
        "learning_item_id": learning_item_id,
        "prompt": _select_prompt(translations, str(lexeme["lemma"])),
        "expected_answer": str(lexeme["lemma"]),
    }


def _select_prompt(translations: list[sqlite3.Row], fallback_text: str) -> str:
    translations_by_language = {
        translation["language_code"]: translation["translation_text"]
        for translation in translations
    }
    for language_code in ("ru", "uk"):
        prompt = translations_by_language.get(language_code)
        if prompt:
            return str(prompt)
    if translations:
        return str(translations[0]["translation_text"])
    return fallback_text


def _normalize_answer(answer_text: str) -> str:
    return answer_text.strip().casefold()
