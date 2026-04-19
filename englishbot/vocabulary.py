import sqlite3

from .db import get_connection, get_default_content_workspace_id, utc_now


def create_lexeme(lemma: str) -> int:
    timestamp = utc_now()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO lexemes (lemma, created_at, updated_at)
            VALUES (?, ?, ?)
            """,
            (lemma, timestamp, timestamp),
        )
    return int(cursor.lastrowid)


def get_lexeme(lexeme_id: int) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, lemma, created_at, updated_at
            FROM lexemes
            WHERE id = ?
            """,
            (lexeme_id,),
        ).fetchone()


def create_learning_item(
    lexeme_id: int,
    text: str,
    workspace_id: int | None = None,
    image_ref: str | None = None,
    audio_ref: str | None = None,
) -> int:
    timestamp = utc_now()
    stored_workspace_id = (
        get_default_content_workspace_id() if workspace_id is None else int(workspace_id)
    )
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO learning_items (
                workspace_id,
                lexeme_id,
                text,
                image_ref,
                audio_ref,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stored_workspace_id,
                lexeme_id,
                text,
                image_ref,
                audio_ref,
                timestamp,
                timestamp,
            ),
        )
    return int(cursor.lastrowid)


def get_learning_item(learning_item_id: int) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                id,
                workspace_id,
                lexeme_id,
                text,
                image_ref,
                audio_ref,
                created_at,
                updated_at
            FROM learning_items
            WHERE id = ?
            """,
            (learning_item_id,),
        ).fetchone()


def list_learning_items(
    limit: int | None = None,
    workspace_id: int | None = None,
) -> list[sqlite3.Row]:
    stored_workspace_id = (
        get_default_content_workspace_id() if workspace_id is None else int(workspace_id)
    )
    query = """
        SELECT
            learning_items.id,
            learning_items.workspace_id,
            learning_items.lexeme_id,
            learning_items.text,
            learning_items.image_ref,
            learning_items.audio_ref,
            learning_items.created_at,
            learning_items.updated_at
        FROM learning_items
        WHERE learning_items.workspace_id = ?
        ORDER BY learning_items.id
    """
    parameters: tuple[int, ...] | tuple[int, int] = (stored_workspace_id,)
    if limit is not None:
        query = f"{query}\nLIMIT ?"
        parameters = (stored_workspace_id, limit)

    with get_connection() as connection:
        return connection.execute(query, parameters).fetchall()


def create_learning_item_translation(
    learning_item_id: int,
    language_code: str,
    translation_text: str,
) -> int:
    timestamp = utc_now()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO learning_item_translations (
                learning_item_id,
                language_code,
                translation_text,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                learning_item_id,
                language_code,
                translation_text,
                timestamp,
                timestamp,
            ),
        )
    return int(cursor.lastrowid)


def list_learning_item_translations(learning_item_id: int) -> list[sqlite3.Row]:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, learning_item_id, language_code, translation_text, created_at, updated_at
            FROM learning_item_translations
            WHERE learning_item_id = ?
            ORDER BY language_code, id
            """,
            (learning_item_id,),
        ).fetchall()


def get_learning_item_with_translations(
    learning_item_id: int,
) -> dict[str, sqlite3.Row | list[sqlite3.Row]] | None:
    learning_item = get_learning_item(learning_item_id)
    if learning_item is None:
        return None
    return {
        "learning_item": learning_item,
        "translations": list_learning_item_translations(learning_item_id),
    }
