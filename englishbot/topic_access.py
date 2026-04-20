import sqlite3

from .db import get_connection, utc_now
from .teacher_student import ROLE_TEACHER
from .topics import (
    find_topic_by_name_for_teacher,
    get_topic,
    get_topic_learning_item_ids,
    publish_topic_to_workspace,
)
from .training import create_training_session_for_learning_items
from .user_profiles import get_user_role
from .workspaces import WORKSPACE_KIND_STUDENT, find_shared_workspace_for_teacher_and_student, user_is_workspace_member


class TopicAccessError(Exception):
    pass


class TeacherRoleRequiredError(TopicAccessError):
    pass


class TeacherWorkspaceMembershipRequiredError(TopicAccessError):
    pass


class StudentWorkspaceMembershipRequiredError(TopicAccessError):
    pass


class TopicNotFoundError(TopicAccessError):
    pass


class TopicAccessDeniedError(TopicAccessError):
    pass


class EmptyTopicError(TopicAccessError):
    pass


def grant_topic_access(
    teacher_user_id: int,
    student_user_id: int,
    topic_name: str,
) -> dict[str, object]:
    if get_user_role(teacher_user_id) != ROLE_TEACHER:
        raise TeacherRoleRequiredError

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

    source_topic = find_topic_by_name_for_teacher(teacher_user_id, topic_name)
    if source_topic is None:
        raise TopicNotFoundError
    topic = publish_topic_to_workspace(int(source_topic["id"]), workspace_id)

    timestamp = utc_now()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO student_topic_access (
                workspace_id,
                student_user_id,
                topic_id,
                granted_by_teacher_user_id,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                workspace_id,
                student_user_id,
                int(topic["topic_id"]),
                teacher_user_id,
                timestamp,
            ),
        )

    access_row = get_student_topic_access(student_user_id, int(topic["topic_id"]))
    return {
        "granted": cursor.rowcount > 0,
        "student_user_id": student_user_id,
        "topic_id": int(topic["topic_id"]),
        "topic_name": str(topic["name"]),
        "topic_title": str(topic["title"]),
        "access_id": None if access_row is None else int(access_row["id"]),
    }


def get_student_topic_access(
    student_user_id: int,
    topic_id: int,
) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                id,
                workspace_id,
                student_user_id,
                topic_id,
                granted_by_teacher_user_id,
                created_at
            FROM student_topic_access
            WHERE student_user_id = ? AND topic_id = ?
            """,
            (student_user_id, topic_id),
        ).fetchone()


def list_accessible_topics(student_user_id: int) -> list[sqlite3.Row]:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                topics.id,
                student_topic_access.workspace_id,
                topics.name,
                topics.title,
                topics.created_at,
                student_topic_access.granted_by_teacher_user_id,
                student_topic_access.created_at AS access_created_at,
                COUNT(learning_items.id) AS item_count
            FROM student_topic_access
            JOIN topics
              ON topics.id = student_topic_access.topic_id
            LEFT JOIN topic_learning_items
              ON topic_learning_items.topic_id = topics.id
            LEFT JOIN learning_items
              ON learning_items.id = topic_learning_items.learning_item_id
             AND learning_items.is_archived = 0
            JOIN workspace_members
              ON workspace_members.workspace_id = student_topic_access.workspace_id
             AND workspace_members.telegram_user_id = student_topic_access.student_user_id
            JOIN workspaces
              ON workspaces.id = student_topic_access.workspace_id
            WHERE student_topic_access.student_user_id = ?
              AND topics.is_archived = 0
              AND workspaces.kind = 'student'
            GROUP BY topics.id, student_topic_access.id
            ORDER BY topics.id
            """,
            (student_user_id,),
        ).fetchall()


def student_has_topic_access(student_user_id: int, topic_id: int) -> bool:
    return get_student_topic_access(student_user_id, topic_id) is not None


def start_topic_training_session(
    student_user_id: int,
    topic_id: int,
) -> dict[str, object]:
    topic = get_topic(topic_id)
    if topic is None:
        raise TopicNotFoundError
    if not student_has_topic_access(student_user_id, topic_id):
        raise TopicAccessDeniedError
    if not user_is_workspace_member(int(topic["workspace_id"]), student_user_id):
        raise TopicAccessDeniedError

    learning_item_ids = get_topic_learning_item_ids(topic_id)
    if not learning_item_ids:
        raise EmptyTopicError

    result = create_training_session_for_learning_items(student_user_id, learning_item_ids)
    result["topic_title"] = str(topic["title"])
    result["topic_name"] = str(topic["name"])
    return result
