import sqlite3

from .db import get_connection, utc_now
from .vocabulary import get_learning_item


def get_topic(topic_id: int, include_archived: bool = False) -> sqlite3.Row | None:
    query = """
        SELECT
            id,
            family_id,
            name,
            title,
            is_archived,
            created_at,
            updated_at
        FROM topics
        WHERE id = ?
    """
    if not include_archived:
        query = f"{query}\nAND is_archived = 0"
    with get_connection() as connection:
        return connection.execute(query, (topic_id,)).fetchone()


def get_topic_learning_item_ids(topic_id: int, include_archived: bool = False) -> list[int]:
    query = """
        SELECT topic_items.learning_item_id
        FROM topic_items
        JOIN learning_items
          ON learning_items.id = topic_items.learning_item_id
        WHERE topic_items.topic_id = ?
    """
    if not include_archived:
        query = f"{query}\nAND learning_items.is_archived = 0"
    query = f"{query}\nORDER BY topic_items.id"
    with get_connection() as connection:
        rows = connection.execute(query, (topic_id,)).fetchall()
    return [int(row["learning_item_id"]) for row in rows]


def get_learning_items_for_topic(
    topic_id: int,
    *,
    include_archived: bool = False,
) -> list[dict[str, object]]:
    learning_items: list[dict[str, object]] = []
    for learning_item_id in get_topic_learning_item_ids(topic_id, include_archived=include_archived):
        learning_item = get_learning_item(learning_item_id)
        if learning_item is not None:
            learning_items.append(learning_item)
    return learning_items


def archive_topic(topic_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE topics
            SET is_archived = 1, updated_at = ?
            WHERE id = ?
            """,
            (utc_now(), topic_id),
        )
