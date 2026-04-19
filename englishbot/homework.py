import sqlite3

from .db import get_connection, utc_now
from .teacher_student import ROLE_TEACHER, get_teacher_link
from .user_profiles import get_user_role
from .vocabulary import get_learning_item
from .training import create_training_session_for_learning_items


ACTIVE_STATUS = "active"
COMPLETED_STATUS = "completed"


class HomeworkError(Exception):
    pass


class TeacherRoleRequiredError(HomeworkError):
    pass


class StudentLinkRequiredError(HomeworkError):
    pass


class EmptyAssignmentError(HomeworkError):
    pass


class LearningItemNotFoundError(HomeworkError):
    pass


class AssignmentNotFoundError(HomeworkError):
    pass


def create_assignment(
    teacher_user_id: int,
    student_user_id: int,
    learning_item_ids: list[int],
) -> dict[str, object]:
    if get_user_role(teacher_user_id) != ROLE_TEACHER:
        raise TeacherRoleRequiredError

    teacher_link = get_teacher_link(student_user_id)
    if teacher_link is None or int(teacher_link["teacher_user_id"]) != teacher_user_id:
        raise StudentLinkRequiredError

    normalized_learning_item_ids = [int(learning_item_id) for learning_item_id in learning_item_ids]
    if not normalized_learning_item_ids:
        raise EmptyAssignmentError

    for learning_item_id in normalized_learning_item_ids:
        if get_learning_item(learning_item_id) is None:
            raise LearningItemNotFoundError

    timestamp = utc_now()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO assignments (
                teacher_user_id,
                student_user_id,
                status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                teacher_user_id,
                student_user_id,
                ACTIVE_STATUS,
                timestamp,
                timestamp,
            ),
        )
        assignment_id = int(cursor.lastrowid)
        connection.executemany(
            """
            INSERT INTO assignment_items (assignment_id, learning_item_id, item_order)
            VALUES (?, ?, ?)
            """,
            [
                (assignment_id, learning_item_id, item_order)
                for item_order, learning_item_id in enumerate(normalized_learning_item_ids)
            ],
        )

    return {
        "assignment_id": assignment_id,
        "student_user_id": student_user_id,
        "learning_item_ids": normalized_learning_item_ids,
        "notification": {
            "student_user_id": student_user_id,
            "text": "Вам назначено новое задание",
        },
    }


def list_active_assignments(student_user_id: int) -> list[sqlite3.Row]:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                assignments.id,
                assignments.teacher_user_id,
                assignments.student_user_id,
                assignments.status,
                assignments.created_at,
                assignments.updated_at,
                assignments.completed_at,
                COUNT(assignment_items.id) AS item_count
            FROM assignments
            LEFT JOIN assignment_items
                ON assignment_items.assignment_id = assignments.id
            WHERE assignments.student_user_id = ?
              AND assignments.status = ?
            GROUP BY assignments.id
            ORDER BY assignments.id
            """,
            (student_user_id, ACTIVE_STATUS),
        ).fetchall()


def get_assignment(assignment_id: int) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                id,
                teacher_user_id,
                student_user_id,
                status,
                created_at,
                updated_at,
                completed_at
            FROM assignments
            WHERE id = ?
            """,
            (assignment_id,),
        ).fetchone()


def get_assignment_learning_item_ids(assignment_id: int) -> list[int]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT learning_item_id
            FROM assignment_items
            WHERE assignment_id = ?
            ORDER BY item_order
            """,
            (assignment_id,),
        ).fetchall()
    return [int(row["learning_item_id"]) for row in rows]


def student_has_active_homework(student_user_id: int) -> bool:
    return bool(list_active_assignments(student_user_id))


def start_assignment_training_session(
    student_user_id: int,
    assignment_id: int,
) -> dict[str, object]:
    assignment = get_assignment(assignment_id)
    if assignment is None:
        raise AssignmentNotFoundError
    if int(assignment["student_user_id"]) != student_user_id:
        raise AssignmentNotFoundError
    if str(assignment["status"]) != ACTIVE_STATUS:
        raise AssignmentNotFoundError

    learning_item_ids = get_assignment_learning_item_ids(assignment_id)
    if not learning_item_ids:
        raise EmptyAssignmentError

    return create_training_session_for_learning_items(
        student_user_id,
        learning_item_ids,
        assignment_id=assignment_id,
    )


def mark_assignment_completed(assignment_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE assignments
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
