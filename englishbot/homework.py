import sqlite3

from .db import get_connection, utc_now
from .families import get_user_family
from .training import (
    HARD_STAGE,
    EASY_STAGE,
    MEDIUM_STAGE,
    HOMEWORK_EASY_CORRECT_REQUIRED,
    HOMEWORK_MEDIUM_CORRECT_REQUIRED,
    create_training_session_for_learning_items,
    find_latest_incomplete_family_homework_training_session,
    get_current_question,
    get_item_progress_status,
    resume_training_session,
)


ACTIVE_STATUS = "active"
COMPLETED_STATUS = "completed"
ASSIGNMENT_SOURCE_FAMILY = "family"
ASSIGNMENT_KIND_HOMEWORK = "homework"
ASSIGNMENT_MODE_STAGED_DEFAULT = "staged_default"
SUPPORTED_ASSIGNMENT_KINDS = {ASSIGNMENT_KIND_HOMEWORK}
SUPPORTED_ASSIGNMENT_MODES = {ASSIGNMENT_MODE_STAGED_DEFAULT}


class HomeworkError(Exception):
    pass


class EmptyAssignmentError(HomeworkError):
    pass


class AssignmentNotFoundError(HomeworkError):
    pass


def list_active_assignments(student_user_id: int) -> list[sqlite3.Row]:
    family = get_user_family(student_user_id)
    if family is None:
        return []
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                homework_assignments.id,
                'family' AS assignment_source,
                NULL AS workspace_id,
                homework_assignments.family_id,
                homework_assignments.assigned_by_user_id AS teacher_user_id,
                homework_assignments.assigned_to_user_id AS student_user_id,
                homework_assignments.title,
                'homework' AS assignment_kind,
                'staged_default' AS assignment_mode,
                homework_assignments.status,
                homework_assignments.created_at,
                homework_assignments.updated_at,
                homework_assignments.completed_at,
                COUNT(homework_assignment_items.id) AS item_count
            FROM homework_assignments
            LEFT JOIN homework_assignment_items
              ON homework_assignment_items.homework_assignment_id = homework_assignments.id
            WHERE homework_assignments.family_id = ?
              AND homework_assignments.assigned_to_user_id = ?
              AND homework_assignments.status = ?
            GROUP BY homework_assignments.id
            ORDER BY homework_assignments.id
            """,
            (int(family["id"]), student_user_id, ACTIVE_STATUS),
        ).fetchall()


def build_assignment_key(source: str, assignment_id: int) -> str:
    if source != ASSIGNMENT_SOURCE_FAMILY:
        raise AssignmentNotFoundError
    return f"{source}:{assignment_id}"


def parse_assignment_ref(assignment_ref: int | str) -> tuple[str, int]:
    if isinstance(assignment_ref, int):
        return ASSIGNMENT_SOURCE_FAMILY, assignment_ref
    value = str(assignment_ref).strip()
    if not value:
        raise AssignmentNotFoundError
    if ":" not in value:
        if not value.isdigit():
            raise AssignmentNotFoundError
        return ASSIGNMENT_SOURCE_FAMILY, int(value)
    source, raw_id = value.split(":", 1)
    if source.strip().lower() != ASSIGNMENT_SOURCE_FAMILY or not raw_id.strip().isdigit():
        raise AssignmentNotFoundError
    return ASSIGNMENT_SOURCE_FAMILY, int(raw_id.strip())


def get_assignment(assignment_ref: int | str) -> sqlite3.Row | None:
    _, assignment_id = parse_assignment_ref(assignment_ref)
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                id,
                'family' AS assignment_source,
                NULL AS workspace_id,
                family_id,
                assigned_by_user_id AS teacher_user_id,
                assigned_to_user_id AS student_user_id,
                title,
                'homework' AS assignment_kind,
                'staged_default' AS assignment_mode,
                status,
                created_at,
                updated_at,
                completed_at
            FROM homework_assignments
            WHERE id = ?
            """,
            (assignment_id,),
        ).fetchone()


def get_assignment_learning_item_ids(assignment_ref: int | str) -> list[int]:
    _, assignment_id = parse_assignment_ref(assignment_ref)
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT learning_item_id
            FROM homework_assignment_items
            WHERE homework_assignment_id = ?
            ORDER BY item_order
            """,
            (assignment_id,),
        ).fetchall()
    return [int(row["learning_item_id"]) for row in rows]


def student_has_active_homework(student_user_id: int) -> bool:
    return bool(list_active_assignments(student_user_id))


def start_assignment_training_session(
    student_user_id: int,
    assignment_ref: int | str,
) -> dict[str, object]:
    _, assignment_id = parse_assignment_ref(assignment_ref)
    assignment_key = build_assignment_key(ASSIGNMENT_SOURCE_FAMILY, assignment_id)
    assignment = get_assignment(assignment_key)
    if assignment is None:
        raise AssignmentNotFoundError
    family = get_user_family(student_user_id)
    if (
        int(assignment["student_user_id"]) != student_user_id
        or str(assignment["status"]) != ACTIVE_STATUS
        or family is None
        or int(assignment["family_id"]) != int(family["id"])
    ):
        raise AssignmentNotFoundError

    learning_item_ids = get_assignment_learning_item_ids(assignment_key)
    if not learning_item_ids:
        raise EmptyAssignmentError

    active_session = find_latest_incomplete_family_homework_training_session(
        student_user_id,
        assignment_id,
    )
    if active_session is not None:
        resumed_session = resume_training_session(int(active_session["id"]))
        if resumed_session is None:
            raise AssignmentNotFoundError
        return {
            "session_id": int(resumed_session["id"]),
            "total_questions": int(resumed_session["total_questions"]),
            "question": get_current_question(student_user_id),
            "assignment_title": assignment["title"],
            "resumed": True,
            "assignment_ref": assignment_key,
        }

    result = create_training_session_for_learning_items(
        student_user_id,
        learning_item_ids,
        family_homework_assignment_id=assignment_id,
    )
    result["assignment_title"] = assignment["title"]
    result["resumed"] = False
    result["assignment_ref"] = assignment_key
    return result


def mark_assignment_completed(assignment_ref: int | str) -> None:
    _, assignment_id = parse_assignment_ref(assignment_ref)
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE homework_assignments
            SET status = ?, updated_at = ?, completed_at = ?
            WHERE id = ?
            """,
            (
                COMPLETED_STATUS,
                utc_now(),
                utc_now(),
                assignment_id,
            ),
        )


def get_active_assignment_training_session(
    student_user_id: int,
    assignment_ref: int | str,
) -> sqlite3.Row | None:
    _, assignment_id = parse_assignment_ref(assignment_ref)
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                id,
                telegram_user_id,
                family_homework_assignment_id,
                current_index,
                correct_answers,
                total_questions,
                progress_message_id,
                current_question_message_id,
                status,
                created_at,
                updated_at
            FROM training_sessions
            WHERE telegram_user_id = ?
              AND family_homework_assignment_id = ?
              AND status = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (student_user_id, assignment_id, ACTIVE_STATUS),
        ).fetchone()


def get_assignment_progress_snapshot(
    assignment_ref: int | str,
    session_id: int,
) -> dict[str, object]:
    _, assignment_id = parse_assignment_ref(assignment_ref)
    assignment_key = build_assignment_key(ASSIGNMENT_SOURCE_FAMILY, assignment_id)
    assignment = get_assignment(assignment_key)
    if assignment is None:
        raise AssignmentNotFoundError

    with get_connection() as connection:
        session = connection.execute(
            """
            SELECT
                id,
                family_homework_assignment_id,
                current_index,
                total_questions,
                status,
                homework_correct_streak,
                homework_hard_mode
            FROM training_sessions
            WHERE id = ? AND family_homework_assignment_id = ?
            """,
            (session_id, assignment_id),
        ).fetchone()
        item_rows = connection.execute(
            """
            SELECT
                item_order,
                learning_item_id,
                current_stage,
                easy_correct_count,
                medium_correct_count,
                correct_streak,
                hard_unlocked,
                hard_completed,
                is_completed
            FROM training_session_items
            WHERE session_id = ?
            ORDER BY item_order
            """,
            (session_id,),
        ).fetchall()

    if session is None:
        raise AssignmentNotFoundError

    total_items = len(item_rows)
    completed_items = sum(1 for row in item_rows if int(row["is_completed"]) == 1)
    current_index = int(session["current_index"])
    is_session_completed = str(session["status"]) == COMPLETED_STATUS
    homework_correct_streak = int(session["homework_correct_streak"])
    homework_hard_mode = bool(session["homework_hard_mode"])
    next_incomplete_row = next((row for row in item_rows if int(row["is_completed"]) == 0), None)
    if total_items == 0:
        current_item_position = 0
        current_stage = COMPLETED_STATUS if is_session_completed else ACTIVE_STATUS
    else:
        current_item_position = total_items if is_session_completed else min(current_index + 1, total_items)
        current_stage = COMPLETED_STATUS
        if is_session_completed and next_incomplete_row is not None:
            current_item_position = int(next_incomplete_row["item_order"]) + 1
            current_stage = str(next_incomplete_row["current_stage"])
        elif not is_session_completed:
            current_row = item_rows[min(current_index, total_items - 1)]
            current_stage = (
                HARD_STAGE if homework_hard_mode else _normalize_assignment_snapshot_stage(current_row)
            )

    item_statuses = [get_item_progress_status(row) for row in item_rows]
    return {
        "assignment_id": int(assignment["id"]),
        "assignment_ref": assignment_key,
        "assignment_source": ASSIGNMENT_SOURCE_FAMILY,
        "assignment_title": assignment["title"],
        "assignment_kind": normalize_assignment_kind(assignment["assignment_kind"]),
        "assignment_mode": normalize_assignment_mode(assignment["assignment_mode"]),
        "completed_items": completed_items,
        "total_items": total_items,
        "current_item_position": current_item_position,
        "current_stage": current_stage,
        "homework_correct_streak": homework_correct_streak,
        "homework_hard_mode": homework_hard_mode,
        "item_statuses": item_statuses,
        "items": [
            {
                "item_order": int(row["item_order"]),
                "learning_item_id": int(row["learning_item_id"]),
                "current_stage": (
                    HARD_STAGE
                    if homework_hard_mode and int(row["item_order"]) == min(current_index, total_items - 1)
                    else _normalize_assignment_snapshot_stage(row)
                ),
                "easy_correct_count": int(row["easy_correct_count"]),
                "medium_correct_count": int(row["medium_correct_count"]),
                "correct_streak": int(row["correct_streak"]),
                "hard_unlocked": bool(row["hard_unlocked"])
                or (homework_hard_mode and int(row["item_order"]) == min(current_index, total_items - 1)),
                "hard_completed": bool(row["hard_completed"]),
                "is_completed": bool(row["is_completed"]),
            }
            for row in item_rows
        ],
    }


def _normalize_assignment_snapshot_stage(row: sqlite3.Row) -> str:
    if bool(row["is_completed"]):
        if bool(row["hard_completed"]):
            return HARD_STAGE
        return MEDIUM_STAGE
    if int(row["easy_correct_count"]) < HOMEWORK_EASY_CORRECT_REQUIRED:
        return EASY_STAGE
    if int(row["medium_correct_count"]) < HOMEWORK_MEDIUM_CORRECT_REQUIRED:
        return MEDIUM_STAGE
    return MEDIUM_STAGE


def normalize_assignment_kind(value: object) -> str:
    if not isinstance(value, str):
        return ASSIGNMENT_KIND_HOMEWORK
    normalized_value = value.strip().lower()
    if normalized_value not in SUPPORTED_ASSIGNMENT_KINDS:
        return ASSIGNMENT_KIND_HOMEWORK
    return normalized_value


def normalize_assignment_mode(value: object) -> str:
    if not isinstance(value, str):
        return ASSIGNMENT_MODE_STAGED_DEFAULT
    normalized_value = value.strip().lower()
    if normalized_value not in SUPPORTED_ASSIGNMENT_MODES:
        return ASSIGNMENT_MODE_STAGED_DEFAULT
    return normalized_value
