import sqlite3

from .db import get_connection, utc_now
from .teacher_student import ROLE_TEACHER
from .topics import find_topic_by_name_for_teacher_workspace, publish_topic_to_workspace
from .training import create_training_session_for_learning_items
from .user_profiles import get_user_role
from .vocabulary import get_learning_item, publish_learning_item_to_workspace
from .workspaces import (
    WORKSPACE_KIND_STUDENT,
    WORKSPACE_KIND_TEACHER,
    WorkspaceEditPermissionError,
    find_shared_workspace_for_teacher_and_student,
    get_workspace,
    user_is_workspace_member,
)


ACTIVE_STATUS = "active"
COMPLETED_STATUS = "completed"


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
    stored_title = title.strip() if title is not None and title.strip() else None

    target_workspace = _get_student_workspace(teacher_user_id, student_user_id)
    published_learning_item_ids: list[int] = []
    source_workspace_id: int | None = None
    for learning_item_id in normalized_learning_item_ids:
        learning_item = get_learning_item(learning_item_id)
        if learning_item is None or int(learning_item["is_archived"]) == 1:
            raise LearningItemNotFoundError
        item_workspace_id = int(learning_item["workspace_id"])
        if source_workspace_id is None:
            source_workspace_id = item_workspace_id
        elif source_workspace_id != item_workspace_id:
            raise MixedWorkspaceAssignmentError

        workspace = get_workspace(item_workspace_id)
        if workspace is None:
            raise LearningItemNotFoundError
        if str(workspace["kind"]) == WORKSPACE_KIND_TEACHER:
            if not user_is_workspace_member(item_workspace_id, teacher_user_id, ROLE_TEACHER):
                raise TeacherWorkspaceMembershipRequiredError
            published_learning_item_ids.append(
                publish_learning_item_to_workspace(
                    learning_item_id,
                    int(target_workspace["id"]),
                )
            )
            continue
        if (
            str(workspace["kind"]) != WORKSPACE_KIND_STUDENT
            or item_workspace_id != int(target_workspace["id"])
        ):
            raise MixedWorkspaceAssignmentError
        published_learning_item_ids.append(learning_item_id)

    return _store_assignment(
        teacher_user_id,
        student_user_id,
        int(target_workspace["id"]),
        published_learning_item_ids,
        stored_title,
    )


def create_assignment_from_group(
    teacher_user_id: int,
    student_user_id: int,
    teacher_workspace_id: int,
    group_name: str,
) -> dict[str, object]:
    target_workspace = _get_student_workspace(teacher_user_id, student_user_id)
    try:
        source_topic = find_topic_by_name_for_teacher_workspace(
            teacher_user_id,
            teacher_workspace_id,
            group_name,
        )
    except WorkspaceEditPermissionError as error:
        raise TeacherWorkspaceMembershipRequiredError from error
    if source_topic is None:
        raise AssignmentGroupNotFoundError

    published_topic = publish_topic_to_workspace(
        int(source_topic["id"]),
        int(target_workspace["id"]),
    )
    return _store_assignment(
        teacher_user_id,
        student_user_id,
        int(target_workspace["id"]),
        [int(learning_item_id) for learning_item_id in published_topic["learning_item_ids"]],
        str(published_topic["title"]),
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
            JOIN workspaces
              ON workspaces.id = assignments.workspace_id
            WHERE assignments.student_user_id = ?
              AND assignments.status = ?
              AND workspaces.kind = 'student'
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


def _get_student_workspace(
    teacher_user_id: int,
    student_user_id: int,
) -> sqlite3.Row:
    workspace = find_shared_workspace_for_teacher_and_student(
        teacher_user_id,
        student_user_id,
        kind=WORKSPACE_KIND_STUDENT,
    )
    if workspace is None:
        raise StudentWorkspaceMembershipRequiredError
    workspace_id = int(workspace["id"])
    if not user_is_workspace_member(workspace_id, teacher_user_id, ROLE_TEACHER):
        raise TeacherWorkspaceMembershipRequiredError
    if not user_is_workspace_member(workspace_id, student_user_id):
        raise StudentWorkspaceMembershipRequiredError
    return workspace


def _store_assignment(
    teacher_user_id: int,
    student_user_id: int,
    workspace_id: int,
    learning_item_ids: list[int],
    title: str | None,
) -> dict[str, object]:
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
                title,
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
                for item_order, learning_item_id in enumerate(learning_item_ids)
            ],
        )

    return {
        "assignment_id": assignment_id,
        "student_user_id": student_user_id,
        "title": title,
        "learning_item_ids": learning_item_ids,
    }
