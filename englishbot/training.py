import sqlite3

from .db import DEFAULT_HINT_LANGUAGE, get_connection, utc_now
from .exercises import ExerciseBuildError, ResolvedLearningItem, TranslationEntry, build_exercise
from .user_profiles import get_user_hint_language
from .vocabulary import get_learning_item_with_translations, get_lexeme, list_learning_items


ACTIVE_STATUS = "active"
COMPLETED_STATUS = "completed"
DEFAULT_SESSION_SIZE = 5
EASY_STAGE = "easy"
MEDIUM_STAGE = "medium"
HARD_STAGE = "hard"


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

    item_snapshots = [
        _build_item_snapshot(
            int(learning_item_id),
            EASY_STAGE,
            learning_item_ids,
            get_user_hint_language(telegram_user_id),
        )
        for learning_item_id in learning_item_ids
    ]
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
                item_order,
                current_stage,
                easy_correct_count,
                medium_correct_count,
                correct_streak,
                hard_unlocked,
                is_completed
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0)
            """,
            [
                (
                    session_id,
                    int(snapshot["learning_item_id"]),
                    str(snapshot["prompt"]),
                    str(snapshot["expected_answer"]),
                    item_order,
                    EASY_STAGE,
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
                progress_message_id,
                current_question_message_id,
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


def get_training_session(session_id: int) -> sqlite3.Row | None:
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
                progress_message_id,
                current_question_message_id,
                status,
                created_at,
                updated_at
            FROM training_sessions
            WHERE id = ?
            """,
            (session_id,),
        ).fetchone()


def find_latest_incomplete_assignment_training_session(
    telegram_user_id: int,
    assignment_id: int,
) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                training_sessions.id,
                training_sessions.telegram_user_id,
                training_sessions.assignment_id,
                training_sessions.current_index,
                training_sessions.correct_answers,
                training_sessions.total_questions,
                training_sessions.progress_message_id,
                training_sessions.current_question_message_id,
                training_sessions.status,
                training_sessions.created_at,
                training_sessions.updated_at
            FROM training_sessions
            WHERE training_sessions.telegram_user_id = ?
              AND training_sessions.assignment_id = ?
              AND EXISTS (
                    SELECT 1
                    FROM training_session_items
                    WHERE training_session_items.session_id = training_sessions.id
                      AND training_session_items.is_completed = 0
                )
            ORDER BY training_sessions.id DESC
            LIMIT 1
            """,
            (telegram_user_id, assignment_id),
        ).fetchone()


def resume_training_session(session_id: int) -> sqlite3.Row | None:
    session = get_training_session(session_id)
    if session is None:
        return None

    next_item = _find_next_incomplete_item(int(session["id"]), 0)
    if next_item is None:
        _mark_session_completed(session)
        return None

    timestamp = utc_now()
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE training_sessions
            SET status = ?, current_index = total_questions, updated_at = ?
            WHERE telegram_user_id = ? AND status = ? AND id != ?
            """,
            (
                COMPLETED_STATUS,
                timestamp,
                int(session["telegram_user_id"]),
                ACTIVE_STATUS,
                int(session["id"]),
            ),
        )
        connection.execute(
            """
            UPDATE training_sessions
            SET status = ?, current_index = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                ACTIVE_STATUS,
                int(next_item["item_order"]),
                timestamp,
                int(session["id"]),
            ),
        )
    return get_training_session(session_id)


def get_current_question(telegram_user_id: int) -> dict[str, object] | None:
    session = get_active_training_session(telegram_user_id)
    if session is None:
        return None

    session = _synchronize_active_session(session)
    if session is None:
        return None

    item_snapshot = _get_session_learning_item(int(session["id"]), int(session["current_index"]))
    if item_snapshot is None:
        _mark_session_completed(session)
        return None

    exercise = _build_session_exercise(
        int(session["id"]),
        int(item_snapshot["learning_item_id"]),
        str(item_snapshot["current_stage"]),
        int(session["telegram_user_id"]),
    )
    prompt_text = str(item_snapshot["prompt_text"]).strip() or exercise.prompt_payload.prompt_text
    expected_answer = str(item_snapshot["expected_answer"]).strip() or exercise.expected_answer
    return {
        "session_id": int(session["id"]),
        "telegram_user_id": int(session["telegram_user_id"]),
        "session_item_id": int(item_snapshot["id"]),
        "learning_item_id": int(item_snapshot["learning_item_id"]),
        "current_index": int(session["current_index"]),
        "question_number": int(session["current_index"]) + 1,
        "total_questions": int(session["total_questions"]),
        "completed_items": _count_completed_session_items(int(session["id"])),
        "current_stage": str(item_snapshot["current_stage"]),
        "stage": str(item_snapshot["current_stage"]),
        "exercise_type": exercise.exercise_type,
        "options": exercise.options,
        "hint_text": exercise.hint_text,
        "image_ref": exercise.image_ref,
        "first_letter": exercise.first_letter,
        "jumbled_letters": exercise.prompt_payload.jumbled_letters,
        "correct_streak": int(item_snapshot["correct_streak"]),
        "easy_correct_count": int(item_snapshot["easy_correct_count"]),
        "medium_correct_count": int(item_snapshot["medium_correct_count"]),
        "hard_unlocked": bool(item_snapshot["hard_unlocked"]),
        "is_completed": bool(item_snapshot["is_completed"]),
        "prompt": prompt_text,
        "expected_answer": expected_answer,
    }


def submit_training_answer(
    telegram_user_id: int,
    answer_text: str,
) -> dict[str, object] | None:
    session = get_active_training_session(telegram_user_id)
    question = get_current_question(telegram_user_id)
    if session is None or question is None:
        return None

    is_correct = _normalize_answer(answer_text) == _normalize_answer(str(question["expected_answer"]))
    next_item_state = _calculate_next_item_state(question, is_correct)
    updated_correct_answers = int(session["correct_answers"]) + (1 if is_correct else 0)

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE training_session_items
            SET prompt_text = ?,
                expected_answer = ?,
                current_stage = ?,
                easy_correct_count = ?,
                medium_correct_count = ?,
                correct_streak = ?,
                hard_unlocked = ?,
                is_completed = ?
            WHERE id = ?
            """,
            (
                next_item_state["prompt_text"],
                next_item_state["expected_answer"],
                next_item_state["current_stage"],
                next_item_state["easy_correct_count"],
                next_item_state["medium_correct_count"],
                next_item_state["correct_streak"],
                1 if next_item_state["hard_unlocked"] else 0,
                1 if next_item_state["is_completed"] else 0,
                int(question["session_item_id"]),
            ),
        )

    status, next_index = _update_session_after_answer(
        session,
        updated_correct_answers,
        item_completed=bool(next_item_state["is_completed"]),
    )

    result: dict[str, object] = {
        "is_correct": is_correct,
        "expected_answer": question["expected_answer"],
        "status": status,
        "correct_answers": updated_correct_answers,
        "total_questions": int(session["total_questions"]),
    }
    if status == COMPLETED_STATUS:
        if session["assignment_id"] is not None:
            from .homework import mark_assignment_completed

            mark_assignment_completed(int(session["assignment_id"]))
        result["summary"] = {
            "total_questions": int(session["total_questions"]),
            "correct_answers": updated_correct_answers,
        }
        return result

    next_question = get_current_question(telegram_user_id)
    if next_question is None:
        result["status"] = COMPLETED_STATUS
        result["summary"] = {
            "total_questions": int(session["total_questions"]),
            "correct_answers": updated_correct_answers,
        }
    else:
        result["next_question"] = next_question
        result["current_index"] = next_index
    return result


def set_training_session_progress_message_id(session_id: int, message_id: int | None) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE training_sessions
            SET progress_message_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (message_id, utc_now(), session_id),
        )


def set_training_session_current_question_message_id(
    session_id: int,
    message_id: int | None,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE training_sessions
            SET current_question_message_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (message_id, utc_now(), session_id),
        )


def _update_session_after_answer(
    session: sqlite3.Row,
    updated_correct_answers: int,
    *,
    item_completed: bool,
) -> tuple[str, int]:
    updated_index = int(session["current_index"])
    status = ACTIVE_STATUS
    if item_completed:
        next_item = _find_next_incomplete_item(int(session["id"]), updated_index + 1)
        if next_item is None:
            status = COMPLETED_STATUS
            updated_index = int(session["total_questions"])
        else:
            updated_index = int(next_item["item_order"])

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
                status,
                utc_now(),
                int(session["id"]),
            ),
        )
    return status, updated_index


def _get_session_learning_item(session_id: int, item_order: int) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                id,
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


def _count_completed_session_items(session_id: int) -> int:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS completed_items
            FROM training_session_items
            WHERE session_id = ? AND is_completed = 1
            """,
            (session_id,),
        ).fetchone()
    return 0 if row is None else int(row["completed_items"])


def _build_item_snapshot(
    learning_item_id: int,
    stage: str,
    session_learning_item_ids: list[int],
    hint_language: str,
) -> dict[str, object]:
    exercise = _build_session_exercise_from_ids(
        learning_item_id,
        stage,
        session_learning_item_ids,
        hint_language,
    )
    return {
        "learning_item_id": learning_item_id,
        "prompt": exercise.prompt_payload.prompt_text,
        "expected_answer": exercise.expected_answer,
    }


def _calculate_next_item_state(question: dict[str, object], is_correct: bool) -> dict[str, object]:
    current_stage = str(question["current_stage"])
    easy_correct_count = int(question["easy_correct_count"])
    medium_correct_count = int(question["medium_correct_count"])
    correct_streak = int(question["correct_streak"])
    hard_unlocked = bool(question["hard_unlocked"])
    is_completed = bool(question["is_completed"])

    if is_correct:
        correct_streak += 1
        if current_stage == EASY_STAGE:
            easy_correct_count += 1
            if easy_correct_count >= 2:
                current_stage = MEDIUM_STAGE
        elif current_stage == MEDIUM_STAGE:
            medium_correct_count += 1
            if medium_correct_count >= 2:
                is_completed = True
        if correct_streak >= 4:
            hard_unlocked = True
    else:
        correct_streak = 0

    session_learning_item_ids = _list_session_learning_item_ids(int(question["session_id"]))
    snapshot = _build_item_snapshot(
        int(question["learning_item_id"]),
        current_stage,
        session_learning_item_ids,
        get_user_hint_language(int(question["telegram_user_id"])),
    )
    return {
        "prompt_text": snapshot["prompt"],
        "expected_answer": snapshot["expected_answer"],
        "current_stage": current_stage,
        "easy_correct_count": easy_correct_count,
        "medium_correct_count": medium_correct_count,
        "correct_streak": correct_streak,
        "hard_unlocked": hard_unlocked,
        "is_completed": is_completed,
    }


def _synchronize_active_session(session: sqlite3.Row) -> sqlite3.Row | None:
    current_item = _get_session_learning_item(int(session["id"]), int(session["current_index"]))
    if current_item is not None and not bool(current_item["is_completed"]):
        return session

    next_item = _find_next_incomplete_item(int(session["id"]), int(session["current_index"]))
    if next_item is None:
        _mark_session_completed(session)
        return None

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE training_sessions
            SET current_index = ?, updated_at = ?
            WHERE id = ?
            """,
            (int(next_item["item_order"]), utc_now(), int(session["id"])),
        )
    return get_active_training_session(int(session["telegram_user_id"]))


def _mark_session_completed(session: sqlite3.Row) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE training_sessions
            SET current_index = total_questions,
                current_question_message_id = NULL,
                status = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (COMPLETED_STATUS, utc_now(), int(session["id"])),
        )
    if session["assignment_id"] is not None:
        from .homework import mark_assignment_completed

        mark_assignment_completed(int(session["assignment_id"]))


def _find_next_incomplete_item(session_id: int, start_item_order: int) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, item_order, learning_item_id, is_completed
            FROM training_session_items
            WHERE session_id = ? AND item_order >= ? AND is_completed = 0
            ORDER BY item_order
            LIMIT 1
            """,
            (session_id, start_item_order),
        ).fetchone()


def _build_session_exercise(
    session_id: int,
    learning_item_id: int,
    stage: str,
    telegram_user_id: int,
):
    session_learning_item_ids = _list_session_learning_item_ids(session_id)
    return _build_session_exercise_from_ids(
        learning_item_id,
        stage,
        session_learning_item_ids,
        get_user_hint_language(telegram_user_id),
    )


def _build_session_exercise_from_ids(
    learning_item_id: int,
    stage: str,
    session_learning_item_ids: list[int],
    hint_language: str = DEFAULT_HINT_LANGUAGE,
):
    learning_item = _resolve_learning_item(learning_item_id)
    distractor_pool = _build_distractor_pool(learning_item, session_learning_item_ids)
    try:
        return build_exercise(
            learning_item=learning_item,
            stage=stage,
            hint_language=hint_language,
            distractor_pool=distractor_pool,
        )
    except ExerciseBuildError:
        if stage != EASY_STAGE:
            raise
        # Keep the session in the required easy stage, but fall back to a minimal
        # typed-answer payload when the current pool cannot support multiple choice.
        return build_exercise(
            learning_item=learning_item,
            stage=HARD_STAGE,
            hint_language=hint_language,
            distractor_pool=distractor_pool,
        )


def _list_session_learning_item_ids(session_id: int) -> list[int]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT learning_item_id
            FROM training_session_items
            WHERE session_id = ?
            ORDER BY item_order
            """,
            (session_id,),
        ).fetchall()
    return [int(row["learning_item_id"]) for row in rows]


def _build_distractor_pool(
    learning_item: ResolvedLearningItem,
    session_learning_item_ids: list[int],
) -> list[ResolvedLearningItem]:
    distractors: list[ResolvedLearningItem] = []
    seen_ids: set[int] = {learning_item.learning_item_id}

    for distractor_id in session_learning_item_ids:
        normalized_id = int(distractor_id)
        if normalized_id in seen_ids:
            continue
        distractors.append(_resolve_learning_item(normalized_id))
        seen_ids.add(normalized_id)

    content = get_learning_item_with_translations(learning_item.learning_item_id)
    if content is None:
        raise NoLearningItemsError
    workspace_id = int(content["learning_item"]["workspace_id"])
    for row in list_learning_items(workspace_id=workspace_id):
        distractor_id = int(row["id"])
        if distractor_id in seen_ids:
            continue
        distractors.append(_resolve_learning_item(distractor_id))
        seen_ids.add(distractor_id)
    return distractors


def _resolve_learning_item(learning_item_id: int) -> ResolvedLearningItem:
    content = get_learning_item_with_translations(learning_item_id)
    if content is None:
        raise NoLearningItemsError

    learning_item = content["learning_item"]
    translations = content["translations"]
    lexeme = get_lexeme(int(learning_item["lexeme_id"]))
    if lexeme is None:
        raise NoLearningItemsError

    return ResolvedLearningItem(
        learning_item_id=int(learning_item["id"]),
        headword=str(lexeme["lemma"]),
        translations=[
            TranslationEntry(
                language_code=str(translation["language_code"]),
                translation_text=str(translation["translation_text"]),
            )
            for translation in translations
        ],
        image_ref=str(learning_item["image_ref"]) if learning_item["image_ref"] else None,
    )


def _normalize_answer(answer_text: str) -> str:
    return answer_text.strip().casefold()
