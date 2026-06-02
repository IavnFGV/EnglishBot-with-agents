import sqlite3

from .db import get_connection
from .families import get_user_family
from .topics import get_topic
from .training import create_training_session_for_learning_items


class TopicAccessError(Exception):
    pass


class TopicNotFoundError(TopicAccessError):
    pass


class TopicAccessDeniedError(TopicAccessError):
    pass


class EmptyTopicError(TopicAccessError):
    pass


def list_accessible_topics(student_user_id: int) -> list[sqlite3.Row]:
    family = get_user_family(student_user_id)
    if family is None:
        return []
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                topics.id,
                topics.name,
                topics.title,
                topics.created_at,
                COUNT(learning_items.id) AS item_count
            FROM topics
            LEFT JOIN topic_items
              ON topic_items.topic_id = topics.id
            LEFT JOIN learning_items
              ON learning_items.id = topic_items.learning_item_id
             AND learning_items.is_archived = 0
            WHERE topics.family_id = ?
              AND topics.is_archived = 0
            GROUP BY topics.id
            ORDER BY topics.id
            """,
            (int(family["id"]),),
        ).fetchall()


def student_has_topic_access(student_user_id: int, topic_id: int) -> bool:
    topic = get_topic(topic_id)
    family = get_user_family(student_user_id)
    return bool(
        topic is not None
        and family is not None
        and topic["family_id"] is not None
        and int(topic["family_id"]) == int(family["id"])
    )


def start_topic_training_session(
    student_user_id: int,
    topic_id: int,
) -> dict[str, object]:
    topic = get_topic(topic_id)
    if topic is None:
        raise TopicNotFoundError
    if not student_has_topic_access(student_user_id, topic_id):
        raise TopicAccessDeniedError
    learning_item_ids = _get_family_topic_learning_item_ids(topic_id)
    if not learning_item_ids:
        raise EmptyTopicError

    result = create_training_session_for_learning_items(student_user_id, learning_item_ids)
    result["topic_title"] = str(topic["title"])
    result["topic_name"] = str(topic["name"])
    return result


def _get_family_topic_learning_item_ids(topic_id: int) -> list[int]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT topic_items.learning_item_id
            FROM topic_items
            JOIN learning_items
              ON learning_items.id = topic_items.learning_item_id
            WHERE topic_items.topic_id = ?
              AND learning_items.is_archived = 0
            ORDER BY topic_items.id
            """,
            (topic_id,),
        ).fetchall()
    return [int(row["learning_item_id"]) for row in rows]
