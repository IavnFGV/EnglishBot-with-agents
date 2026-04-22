import sqlite3

from .db import get_connection, utc_now
from .teacher_student import ROLE_TEACHER
from .topics import find_topic_by_name_for_teacher_workspace, publish_topic_to_workspace
from .training import (
    create_training_session_for_learning_items,
    find_latest_incomplete_assignment_training_session,
    get_current_question,
    resume_training_session,
)
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
ITEM_STATUS_NOT_STARTED = "not_started"
ITEM_STATUS_IN_PROGRESS = "in_progress"
ITEM_STATUS_COMPLETED = "completed"
ASSIGNMENT_KIND_HOMEWORK = "homework"
ASSIGNMENT_MODE_STAGED_DEFAULT = "staged_default"
SUPPORTED_ASSIGNMENT_KINDS = {ASSIGNMENT_KIND_HOMEWORK}
SUPPORTED_ASSIGNMENT_MODES = {ASSIGNMENT_MODE_STAGED_DEFAULT}


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
    assignment_kind: str = ASSIGNMENT_KIND_HOMEWORK,
    assignment_mode: str = ASSIGNMENT_MODE_STAGED_DEFAULT,
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
        assignment_kind=assignment_kind,
        assignment_mode=assignment_mode,
    )


def create_assignment_from_group(
    teacher_user_id: int,
    student_user_id: int,
    teacher_workspace_id: int,
    group_name: str,
    assignment_kind: str = ASSIGNMENT_KIND_HOMEWORK,
    assignment_mode: str = ASSIGNMENT_MODE_STAGED_DEFAULT,
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
        assignment_kind=assignment_kind,
        assignment_mode=assignment_mode,
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
                assignments.assignment_kind,
                assignments.assignment_mode,
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
                assignment_kind,
                assignment_mode,
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

    active_session = find_latest_incomplete_assignment_training_session(
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
        }

    result = create_training_session_for_learning_items(
        student_user_id,
        learning_item_ids,
        assignment_id=assignment_id,
    )
    result["assignment_title"] = assignment["title"]
    result["resumed"] = False
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


def get_active_assignment_training_session(
    student_user_id: int,
    assignment_id: int,
) -> sqlite3.Row | None:
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
            WHERE telegram_user_id = ?
              AND assignment_id = ?
              AND status = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (student_user_id, assignment_id, ACTIVE_STATUS),
        ).fetchone()


def get_assignment_progress_snapshot(
    assignment_id: int,
    session_id: int,
) -> dict[str, object]:
    assignment = get_assignment(assignment_id)
    if assignment is None:
        raise AssignmentNotFoundError

    with get_connection() as connection:
        session = connection.execute(
            """
            SELECT id, current_index, total_questions, status
            FROM training_sessions
            WHERE id = ? AND assignment_id = ?
            """,
            (session_id, assignment_id),
        ).fetchone()
        item_rows = connection.execute(
            """
            SELECT item_order, current_stage, is_completed
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
    next_incomplete_row = next(
        (row for row in item_rows if int(row["is_completed"]) == 0),
        None,
    )
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
            current_stage = str(current_row["current_stage"])

    item_statuses: list[str] = []
    current_item_order = None if next_incomplete_row is None else int(next_incomplete_row["item_order"])
    for row in item_rows:
        item_order = int(row["item_order"])
        if int(row["is_completed"]) == 1:
            item_statuses.append(ITEM_STATUS_COMPLETED)
        elif (
            (not is_session_completed and item_order == current_index)
            or (is_session_completed and item_order == current_item_order)
        ):
            item_statuses.append(ITEM_STATUS_IN_PROGRESS)
        else:
            item_statuses.append(ITEM_STATUS_NOT_STARTED)

    return {
        "assignment_id": int(assignment["id"]),
        "assignment_title": assignment["title"],
        "assignment_kind": normalize_assignment_kind(assignment["assignment_kind"]),
        "assignment_mode": normalize_assignment_mode(assignment["assignment_mode"]),
        "completed_items": completed_items,
        "total_items": total_items,
        "current_item_position": current_item_position,
        "current_stage": current_stage,
        "item_statuses": item_statuses,
    }


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
    *,
    assignment_kind: str = ASSIGNMENT_KIND_HOMEWORK,
    assignment_mode: str = ASSIGNMENT_MODE_STAGED_DEFAULT,
) -> dict[str, object]:
    timestamp = utc_now()
    normalized_kind = normalize_assignment_kind(assignment_kind)
    normalized_mode = normalize_assignment_mode(assignment_mode)
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO assignments (
                workspace_id,
                teacher_user_id,
                student_user_id,
                title,
                assignment_kind,
                assignment_mode,
                status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workspace_id,
                teacher_user_id,
                student_user_id,
                title,
                normalized_kind,
                normalized_mode,
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
        "assignment_kind": normalized_kind,
        "assignment_mode": normalized_mode,
        "learning_item_ids": learning_item_ids,
    }


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
