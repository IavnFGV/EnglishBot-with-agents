import sqlite3

from .db import (
    get_connection,
    get_default_content_workspace_id,
    utc_now,
)
from .vocabulary import get_learning_item
from .workspaces import ensure_teacher_can_edit_workspace_content


class TopicWorkspaceMismatchError(Exception):
    pass


def create_topic(
    name: str,
    title: str,
    workspace_id: int | None = None,
    source_topic_id: int | None = None,
    workbook_key: str | None = None,
) -> int:
    timestamp = utc_now()
    stored_workspace_id = (
        get_default_content_workspace_id() if workspace_id is None else int(workspace_id)
    )
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO topics (
                workspace_id,
                workbook_key,
                source_topic_id,
                name,
                title,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stored_workspace_id,
                workbook_key,
                source_topic_id,
                name,
                title,
                timestamp,
                timestamp,
            ),
        )
    return int(cursor.lastrowid)


def create_topic_for_teacher_workspace(
    teacher_user_id: int,
    workspace_id: int,
    name: str,
    title: str,
) -> int:
    ensure_teacher_can_edit_workspace_content(workspace_id, teacher_user_id)
    return create_topic(name, title, workspace_id=workspace_id)


def get_topic(topic_id: int, include_archived: bool = False) -> sqlite3.Row | None:
    query = """
        SELECT
            id,
            workspace_id,
            family_id,
            workbook_key,
            source_topic_id,
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


def get_topic_by_name(
    name: str,
    workspace_id: int | None = None,
    include_archived: bool = False,
) -> sqlite3.Row | None:
    stored_workspace_id = (
        get_default_content_workspace_id() if workspace_id is None else int(workspace_id)
    )
    query = """
        SELECT
            id,
            workspace_id,
            family_id,
            workbook_key,
            source_topic_id,
            name,
            title,
            is_archived,
            created_at,
            updated_at
        FROM topics
        WHERE workspace_id = ? AND name = ?
    """
    if not include_archived:
        query = f"{query}\nAND is_archived = 0"
    with get_connection() as connection:
        return connection.execute(query, (stored_workspace_id, name.strip())).fetchone()


def find_topic_by_name_for_teacher_workspace(
    teacher_user_id: int,
    workspace_id: int,
    topic_name: str,
) -> sqlite3.Row | None:
    ensure_teacher_can_edit_workspace_content(workspace_id, teacher_user_id)
    return get_topic_by_name(topic_name, workspace_id=workspace_id)


def list_topics(
    workspace_id: int | None = None,
    include_archived: bool = False,
) -> list[sqlite3.Row]:
    stored_workspace_id = (
        get_default_content_workspace_id() if workspace_id is None else int(workspace_id)
    )
    query = """
        SELECT
            topics.id,
            topics.workspace_id,
            topics.family_id,
            topics.workbook_key,
            topics.source_topic_id,
            topics.name,
            topics.title,
            topics.is_archived,
            topics.created_at,
            topics.updated_at,
            COUNT(learning_items.id) AS item_count
        FROM topics
        LEFT JOIN topic_learning_items
          ON topic_learning_items.topic_id = topics.id
        LEFT JOIN learning_items
          ON learning_items.id = topic_learning_items.learning_item_id
         AND learning_items.is_archived = 0
        WHERE topics.workspace_id = ?
    """
    if not include_archived:
        query = f"{query}\nAND topics.is_archived = 0"
    query = f"{query}\nGROUP BY topics.id\nORDER BY topics.id"
    with get_connection() as connection:
        return connection.execute(query, (stored_workspace_id,)).fetchall()


def link_learning_item_to_topic(topic_id: int, learning_item_id: int) -> None:
    with get_connection() as connection:
        topic = connection.execute(
            """
            SELECT workspace_id
            FROM topics
            WHERE id = ?
            """,
            (topic_id,),
        ).fetchone()
        learning_item = connection.execute(
            """
            SELECT workspace_id
            FROM learning_items
            WHERE id = ?
            """,
            (learning_item_id,),
        ).fetchone()
        if (
            topic is not None
            and learning_item is not None
            and int(topic["workspace_id"]) != int(learning_item["workspace_id"])
        ):
            raise TopicWorkspaceMismatchError
        connection.execute(
            """
            INSERT OR IGNORE INTO topic_learning_items (topic_id, learning_item_id)
            VALUES (?, ?)
            """,
            (topic_id, learning_item_id),
        )


def replace_topic_learning_items(
    teacher_user_id: int,
    topic_id: int,
    learning_item_ids: list[int],
) -> None:
    topic = get_topic(topic_id, include_archived=True)
    if topic is None:
        return
    workspace_id = int(topic["workspace_id"])
    ensure_teacher_can_edit_workspace_content(workspace_id, teacher_user_id)
    with get_connection() as connection:
        for learning_item_id in learning_item_ids:
            learning_item = connection.execute(
                """
                SELECT workspace_id
                FROM learning_items
                WHERE id = ?
                """,
                (learning_item_id,),
            ).fetchone()
            if learning_item is None or int(learning_item["workspace_id"]) != workspace_id:
                raise TopicWorkspaceMismatchError
        connection.execute(
            """
            DELETE FROM topic_learning_items
            WHERE topic_id = ?
            """,
            (topic_id,),
        )
        connection.executemany(
            """
            INSERT INTO topic_learning_items (topic_id, learning_item_id)
            VALUES (?, ?)
            """,
            [(topic_id, learning_item_id) for learning_item_id in learning_item_ids],
        )
        connection.execute(
            """
            UPDATE topics
            SET updated_at = ?, is_archived = 0
            WHERE id = ?
            """,
            (utc_now(), topic_id),
        )


def rename_topic(
    teacher_user_id: int,
    topic_id: int,
    *,
    name: str | None = None,
    title: str | None = None,
) -> None:
    topic = get_topic(topic_id, include_archived=True)
    if topic is None:
        return
    ensure_teacher_can_edit_workspace_content(int(topic["workspace_id"]), teacher_user_id)
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE topics
            SET name = COALESCE(?, name),
                title = COALESCE(?, title),
                is_archived = 0,
                updated_at = ?
            WHERE id = ?
            """,
            (name, title, utc_now(), topic_id),
        )


def archive_topic(
    teacher_user_id: int,
    topic_id: int,
) -> None:
    topic = get_topic(topic_id, include_archived=True)
    if topic is None:
        return
    ensure_teacher_can_edit_workspace_content(int(topic["workspace_id"]), teacher_user_id)
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE topics
            SET is_archived = 1, updated_at = ?
            WHERE id = ?
            """,
            (utc_now(), topic_id),
        )


def get_topic_learning_item_ids(
    topic_id: int,
    include_archived: bool = False,
) -> list[int]:
    query = """
        SELECT topic_learning_items.learning_item_id
        FROM topic_learning_items
        JOIN learning_items
          ON learning_items.id = topic_learning_items.learning_item_id
        WHERE topic_learning_items.topic_id = ?
    """
    if not include_archived:
        query = f"{query}\nAND learning_items.is_archived = 0"
    query = f"{query}\nORDER BY topic_learning_items.id"
    with get_connection() as connection:
        rows = connection.execute(query, (topic_id,)).fetchall()
    return [int(row["learning_item_id"]) for row in rows]


def get_learning_items_for_topic(
    topic_id: int,
    include_archived: bool = False,
) -> list[dict[str, object]]:
    query = """
        SELECT
            learning_items.id
        FROM topic_learning_items
        JOIN learning_items
          ON learning_items.id = topic_learning_items.learning_item_id
        WHERE topic_learning_items.topic_id = ?
    """
    if not include_archived:
        query = f"{query}\nAND learning_items.is_archived = 0"
    query = f"{query}\nORDER BY topic_learning_items.id"
    with get_connection() as connection:
        rows = connection.execute(query, (topic_id,)).fetchall()
    learning_items: list[dict[str, object]] = []
    for row in rows:
        learning_item = get_learning_item(int(row["id"]))
        if learning_item is not None:
            learning_items.append(learning_item)
    return learning_items

