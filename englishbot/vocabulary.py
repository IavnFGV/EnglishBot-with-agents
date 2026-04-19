import sqlite3

from .db import get_connection, utc_now


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
    image_ref: str | None = None,
    audio_ref: str | None = None,
) -> int:
    timestamp = utc_now()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO learning_items (
                lexeme_id,
                text,
                image_ref,
                audio_ref,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (lexeme_id, text, image_ref, audio_ref, timestamp, timestamp),
        )
    return int(cursor.lastrowid)


def get_learning_item(learning_item_id: int) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, lexeme_id, text, image_ref, audio_ref, created_at, updated_at
            FROM learning_items
            WHERE id = ?
            """,
            (learning_item_id,),
        ).fetchone()


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
