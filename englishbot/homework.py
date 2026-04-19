import sqlite3

from .db import get_connection, utc_now
from .teacher_student import ROLE_TEACHER
from .topics import get_topic_by_name, get_topic_learning_item_ids, list_topics
from .training import create_training_session_for_learning_items
from .user_profiles import get_user_role
from .vocabulary import get_learning_item
from .workspaces import find_shared_workspace_for_teacher_and_student, user_is_workspace_member


ACTIVE_STATUS = "active"
COMPLETED_STATUS = "completed"
DEFAULT_ASSIGNMENT_TITLE = "Домашка"


class HomeworkError(Exception):
    pass


class TeacherRoleRequiredError(HomeworkError):
    pass


class TeacherWorkspaceMembershipRequiredError(HomeworkError):
    pass


class StudentWorkspaceMembershipRequiredError(HomeworkError):
    pass


class EmptyAssignmentError(HomeworkError):
    pass


class LearningItemNotFoundError(HomeworkError):
    pass


class AssignmentGroupNotFoundError(HomeworkError):
    pass


class AssignmentNotFoundError(HomeworkError):
    pass


class MixedWorkspaceAssignmentError(HomeworkError):
    pass


def create_assignment(
    teacher_user_id: int,
    student_user_id: int,
    learning_item_ids: list[int],
    title: str | None = None,
) -> dict[str, object]:
    if get_user_role(teacher_user_id) != ROLE_TEACHER:
        raise TeacherRoleRequiredError

    normalized_learning_item_ids = [int(learning_item_id) for learning_item_id in learning_item_ids]
    if not normalized_learning_item_ids:
        raise EmptyAssignmentError
    stored_title = title.strip() if title is not None and title.strip() else DEFAULT_ASSIGNMENT_TITLE

    workspace_id: int | None = None
    for learning_item_id in normalized_learning_item_ids:
        learning_item = get_learning_item(learning_item_id)
        if learning_item is None:
            raise LearningItemNotFoundError
        item_workspace_id = int(learning_item["workspace_id"])
        if workspace_id is None:
            workspace_id = item_workspace_id
            continue
        if item_workspace_id != workspace_id:
            raise MixedWorkspaceAssignmentError

    if workspace_id is None:
        raise EmptyAssignmentError
    if not user_is_workspace_member(workspace_id, teacher_user_id, ROLE_TEACHER):
        raise TeacherWorkspaceMembershipRequiredError
    if not user_is_workspace_member(workspace_id, student_user_id):
        raise StudentWorkspaceMembershipRequiredError

    timestamp = utc_now()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO assignments (
                workspace_id,
                teacher_user_id,
                student_user_id,
                title,
                status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workspace_id,
                teacher_user_id,
                student_user_id,
                stored_title,
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
        "title": stored_title,
        "learning_item_ids": normalized_learning_item_ids,
        "notification": {
            "student_user_id": student_user_id,
            "text": f"Вам назначено новое задание: {stored_title}",
        },
    }


def list_assignable_groups() -> list[dict[str, object]]:
    return [
        {
            "workspace_id": int(topic["workspace_id"]),
            "name": str(topic["name"]),
            "title": str(topic["title"]),
            "item_count": int(topic["item_count"]),
        }
        for topic in list_topics()
    ]


def create_assignment_from_group(
    teacher_user_id: int,
    student_user_id: int,
    group_name: str,
) -> dict[str, object]:
    workspace = find_shared_workspace_for_teacher_and_student(teacher_user_id, student_user_id)
    if workspace is None:
        raise StudentWorkspaceMembershipRequiredError

    topic = get_topic_by_name(group_name.strip(), workspace_id=int(workspace["id"]))
    if topic is None:
        raise AssignmentGroupNotFoundError

    learning_item_ids = get_topic_learning_item_ids(int(topic["id"]))
    if not learning_item_ids:
        raise AssignmentGroupNotFoundError

    return create_assignment(
        teacher_user_id,
        student_user_id,
        learning_item_ids,
        title=str(topic["title"]),
    )


def list_active_assignments(student_user_id: int) -> list[sqlite3.Row]:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                assignments.id,
                assignments.workspace_id,
                assignments.teacher_user_id,
                assignments.student_user_id,
                assignments.title,
                assignments.status,
                assignments.created_at,
                assignments.updated_at,
                assignments.completed_at,
                COUNT(assignment_items.id) AS item_count
            FROM assignments
            LEFT JOIN assignment_items
                ON assignment_items.assignment_id = assignments.id
            JOIN workspace_members
              ON workspace_members.workspace_id = assignments.workspace_id
             AND workspace_members.telegram_user_id = assignments.student_user_id
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
                workspace_id,
                teacher_user_id,
                student_user_id,
                title,
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
    if not user_is_workspace_member(int(assignment["workspace_id"]), student_user_id):
        raise AssignmentNotFoundError

    learning_item_ids = get_assignment_learning_item_ids(assignment_id)
    if not learning_item_ids:
        raise EmptyAssignmentError

    result = create_training_session_for_learning_items(
        student_user_id,
        learning_item_ids,
        assignment_id=assignment_id,
    )
    result["assignment_title"] = assignment["title"]
    return result


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
