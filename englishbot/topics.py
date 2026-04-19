import sqlite3

from .db import get_connection, utc_now


def create_topic(name: str, title: str) -> int:
    timestamp = utc_now()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO topics (name, title, created_at)
            VALUES (?, ?, ?)
            """,
            (name, title, timestamp),
        )
    return int(cursor.lastrowid)


def get_topic(topic_id: int) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, name, title, created_at
            FROM topics
            WHERE id = ?
            """,
            (topic_id,),
        ).fetchone()


def get_topic_by_name(name: str) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, name, title, created_at
            FROM topics
            WHERE name = ?
            """,
            (name.strip(),),
        ).fetchone()


def list_topics() -> list[sqlite3.Row]:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                topics.id,
                topics.name,
                topics.title,
                topics.created_at,
                COUNT(topic_learning_items.id) AS item_count
            FROM topics
            LEFT JOIN topic_learning_items
              ON topic_learning_items.topic_id = topics.id
            GROUP BY topics.id
            ORDER BY topics.id
            """
        ).fetchall()


def link_learning_item_to_topic(topic_id: int, learning_item_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO topic_learning_items (topic_id, learning_item_id)
            VALUES (?, ?)
            """,
            (topic_id, learning_item_id),
        )


def get_topic_learning_item_ids(topic_id: int) -> list[int]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT learning_item_id
            FROM topic_learning_items
            WHERE topic_id = ?
            ORDER BY id
            """,
            (topic_id,),
        ).fetchall()
    return [int(row["learning_item_id"]) for row in rows]


def get_learning_items_for_topic(topic_id: int) -> list[sqlite3.Row]:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                learning_items.id,
                learning_items.lexeme_id,
                learning_items.text,
                learning_items.image_ref,
                learning_items.audio_ref,
                learning_items.created_at,
                learning_items.updated_at
            FROM topic_learning_items
            JOIN learning_items
              ON learning_items.id = topic_learning_items.learning_item_id
            WHERE topic_learning_items.topic_id = ?
            ORDER BY topic_learning_items.id
            """,
            (topic_id,),
        ).fetchall()
