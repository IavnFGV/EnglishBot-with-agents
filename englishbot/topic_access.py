import sqlite3

from .db import get_connection, utc_now
from .teacher_student import ROLE_TEACHER, get_teacher_link
from .topics import get_topic, get_topic_by_name, get_topic_learning_item_ids
from .training import create_training_session_for_learning_items
from .user_profiles import get_user_role


class TopicAccessError(Exception):
    pass


class TeacherRoleRequiredError(TopicAccessError):
    pass


class StudentLinkRequiredError(TopicAccessError):
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

    teacher_link = get_teacher_link(student_user_id)
    if teacher_link is None or int(teacher_link["teacher_user_id"]) != teacher_user_id:
        raise StudentLinkRequiredError

    topic = get_topic_by_name(topic_name.strip())
    if topic is None:
        raise TopicNotFoundError

    timestamp = utc_now()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO student_topic_access (
                student_user_id,
                topic_id,
                granted_by_teacher_user_id,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                student_user_id,
                int(topic["id"]),
                teacher_user_id,
                timestamp,
            ),
        )

    access_row = get_student_topic_access(student_user_id, int(topic["id"]))
    return {
        "granted": cursor.rowcount > 0,
        "student_user_id": student_user_id,
        "topic_id": int(topic["id"]),
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
                topics.name,
                topics.title,
                topics.created_at,
                student_topic_access.granted_by_teacher_user_id,
                student_topic_access.created_at AS access_created_at,
                COUNT(topic_learning_items.id) AS item_count
            FROM student_topic_access
            JOIN topics
              ON topics.id = student_topic_access.topic_id
            LEFT JOIN topic_learning_items
              ON topic_learning_items.topic_id = topics.id
            WHERE student_topic_access.student_user_id = ?
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

    learning_item_ids = get_topic_learning_item_ids(topic_id)
    if not learning_item_ids:
        raise EmptyTopicError

    result = create_training_session_for_learning_items(student_user_id, learning_item_ids)
    result["topic_title"] = str(topic["title"])
    result["topic_name"] = str(topic["name"])
    return result
