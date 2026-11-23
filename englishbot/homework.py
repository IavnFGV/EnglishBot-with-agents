import sqlite3

from .db import get_connection, utc_now
from .families import get_user_family
from .training import (
    HARD_STAGE,
    EASY_STAGE,
    MEDIUM_STAGE,
    TRAINING_MODES,
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
ASSIGNMENT_MODE_STAGED_DEFAULT = "easy"
SUPPORTED_ASSIGNMENT_KINDS = {ASSIGNMENT_KIND_HOMEWORK}
SUPPORTED_ASSIGNMENT_MODES = set(TRAINING_MODES)


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
                training_mode AS assignment_mode,
                homework_assignments.status,
                homework_assignments.created_at,
                homework_assignments.updated_at,
                homework_assignments.completed_at,
                homework_assignments.words_completed_at,
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
                training_mode AS assignment_mode,
                status,
                created_at,
                updated_at,
                completed_at,
                words_completed_at
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
    # Words already drilled while paper tasks are pending: there is nothing to train again.
    if not learning_item_ids or assignment["words_completed_at"] is not None:
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
        training_mode=str(assignment["assignment_mode"]),
    )
    result["assignment_title"] = assignment["title"]
    result["resumed"] = False
    result["assignment_ref"] = assignment_key
    return result


def mark_assignment_completed(assignment_ref: int | str) -> None:
    """Called when the homework words are all drilled; paper tasks may still keep it open."""
    _, assignment_id = parse_assignment_ref(assignment_ref)
    with get_connection() as connection:
        connection.execute(
            "UPDATE homework_assignments SET words_completed_at = COALESCE(words_completed_at, ?) WHERE id = ?",
            (utc_now(), assignment_id),
        )
        _complete_if_finished(connection, assignment_id)


# Tasks of homework assigned from a homework set: words, paper work, notes


TASK_WORDS = "words"
TASK_PAPER = "paper"


def _complete_if_finished(connection, assignment_id: int) -> bool:
    """Complete active homework once its words are drilled (or it has none) and every paper task is ticked."""
    assignment = connection.execute(
        """
        SELECT status, homework_set_id, words_completed_at,
               (SELECT COUNT(*) FROM homework_assignment_items WHERE homework_assignment_id = homework_assignments.id) AS item_count
        FROM homework_assignments WHERE id = ?
        """,
        (assignment_id,),
    ).fetchone()
    if assignment is None or assignment["status"] != ACTIVE_STATUS:
        return False
    if int(assignment["item_count"]) and assignment["words_completed_at"] is None:
        return False
    if assignment["homework_set_id"] is not None:
        pending = connection.execute(
            """
            SELECT COUNT(*) FROM homework_set_tasks
            WHERE homework_set_id = ? AND task_kind = ?
              AND id NOT IN (SELECT task_id FROM homework_assignment_task_done WHERE homework_assignment_id = ?)
            """,
            (int(assignment["homework_set_id"]), TASK_PAPER, assignment_id),
        ).fetchone()[0]
        if pending:
            return False
    timestamp = utc_now()
    connection.execute(
        "UPDATE homework_assignments SET status = ?, updated_at = ?, completed_at = ? WHERE id = ?",
        (COMPLETED_STATUS, timestamp, timestamp, assignment_id),
    )
    return True


def _own_active_assignment(connection, student_user_id: int, assignment_id: int):
    assignment = connection.execute(
        "SELECT * FROM homework_assignments WHERE id = ? AND assigned_to_user_id = ? AND status = ?",
        (assignment_id, student_user_id, ACTIVE_STATUS),
    ).fetchone()
    if assignment is None:
        raise AssignmentNotFoundError
    return assignment


def list_assignment_tasks(student_user_id: int, assignment_id: int) -> list[dict[str, object]]:
    """Tasks of the learner's active homework with photo paths and done marks; empty for word-only homework."""
    from .assets import resolve_runtime_asset_path

    with get_connection() as connection:
        assignment = _own_active_assignment(connection, student_user_id, assignment_id)
        if assignment["homework_set_id"] is None:
            return []
        done = {
            int(row["task_id"])
            for row in connection.execute(
                "SELECT task_id FROM homework_assignment_task_done WHERE homework_assignment_id = ?", (assignment_id,)
            ).fetchall()
        }
        tasks = []
        for task in connection.execute(
            "SELECT * FROM homework_set_tasks WHERE homework_set_id = ? ORDER BY task_order, id",
            (int(assignment["homework_set_id"]),),
        ).fetchall():
            photos = [
                str(resolve_runtime_asset_path(str(row["local_path"])))
                for row in connection.execute(
                    """
                    SELECT assets.local_path FROM homework_set_task_assets
                    JOIN assets ON assets.id = homework_set_task_assets.asset_id
                    WHERE homework_set_task_assets.task_id = ? AND assets.local_path IS NOT NULL
                    ORDER BY homework_set_task_assets.sort_order
                    """,
                    (int(task["id"]),),
                ).fetchall()
            ]
            tasks.append({
                "id": int(task["id"]),
                "kind": str(task["task_kind"]),
                "title": str(task["title"] or ""),
                "instructions": str(task["instructions"] or ""),
                "photos": photos,
                "done": int(task["id"]) in done,
            })
    return tasks


def pending_paper_task_count(assignment_ref: int | str) -> int:
    """Paper tasks still unticked on active homework; zero for finished or word-only homework."""
    _, assignment_id = parse_assignment_ref(assignment_ref)
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) FROM homework_assignments
            JOIN homework_set_tasks ON homework_set_tasks.homework_set_id = homework_assignments.homework_set_id
            WHERE homework_assignments.id = ? AND homework_assignments.status = ? AND homework_set_tasks.task_kind = ?
              AND homework_set_tasks.id NOT IN (
                SELECT task_id FROM homework_assignment_task_done WHERE homework_assignment_id = homework_assignments.id)
            """,
            (assignment_id, ACTIVE_STATUS, TASK_PAPER),
        ).fetchone()
    return int(row[0])


def set_assignment_task_done(student_user_id: int, assignment_id: int, task_id: int, done: bool) -> bool:
    """Tick a paper task on or off; returns True when this finished the whole homework."""
    with get_connection() as connection:
        assignment = _own_active_assignment(connection, student_user_id, assignment_id)
        task = connection.execute(
            "SELECT 1 FROM homework_set_tasks WHERE id = ? AND homework_set_id = ? AND task_kind = ?",
            (task_id, assignment["homework_set_id"], TASK_PAPER),
        ).fetchone()
        if task is None:
            raise AssignmentNotFoundError
        if done:
            connection.execute(
                "INSERT OR IGNORE INTO homework_assignment_task_done (homework_assignment_id, task_id, done_at) VALUES (?, ?, ?)",
                (assignment_id, task_id, utc_now()),
            )
            return _complete_if_finished(connection, assignment_id)
        connection.execute(
            "DELETE FROM homework_assignment_task_done WHERE homework_assignment_id = ? AND task_id = ?",
            (assignment_id, task_id),
        )
        return False


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
                is_completed,
                is_deferred,
                used_help
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
    homework_correct_streak = 0
    homework_hard_mode = False
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
                "is_deferred": bool(row["is_deferred"]),
                "used_help": bool(row["used_help"]),
            }
            for row in item_rows
        ],
    }


def _normalize_assignment_snapshot_stage(row: sqlite3.Row) -> str:
    return str(row["current_stage"])


def normalize_assignment_kind(value: object) -> str:
    if not isinstance(value, str):
        return ASSIGNMENT_KIND_HOMEWORK
    normalized_value = value.strip().lower()
    if normalized_value not in SUPPORTED_ASSIGNMENT_KINDS:
        return ASSIGNMENT_KIND_HOMEWORK
    return normalized_value


def normalize_assignment_mode(value: object) -> str:
    if value == "staged_default":
        return ASSIGNMENT_MODE_STAGED_DEFAULT
    if not isinstance(value, str) or value not in SUPPORTED_ASSIGNMENT_MODES:
        raise ValueError("invalid assignment mode")
    return value
