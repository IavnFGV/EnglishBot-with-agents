import sqlite3

from .db import get_connection, get_default_content_workspace_id, utc_now
from .workspaces import ensure_teacher_can_edit_workspace_content


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
    source_learning_item_id: int | None = None,
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
                source_learning_item_id,
                lexeme_id,
                text,
                image_ref,
                audio_ref,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stored_workspace_id,
                source_learning_item_id,
                lexeme_id,
                text,
                image_ref,
                audio_ref,
                timestamp,
                timestamp,
            ),
        )
    return int(cursor.lastrowid)


def create_learning_item_for_teacher_workspace(
    teacher_user_id: int,
    workspace_id: int,
    lexeme_id: int,
    text: str,
    image_ref: str | None = None,
    audio_ref: str | None = None,
) -> int:
    ensure_teacher_can_edit_workspace_content(workspace_id, teacher_user_id)
    return create_learning_item(
        lexeme_id,
        text,
        workspace_id=workspace_id,
        image_ref=image_ref,
        audio_ref=audio_ref,
    )


def get_learning_item(learning_item_id: int) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                id,
                workspace_id,
                source_learning_item_id,
                lexeme_id,
                text,
                image_ref,
                audio_ref,
                is_archived,
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
    include_archived: bool = False,
) -> list[sqlite3.Row]:
    stored_workspace_id = (
        get_default_content_workspace_id() if workspace_id is None else int(workspace_id)
    )
    query = """
        SELECT
            learning_items.id,
            learning_items.workspace_id,
            learning_items.source_learning_item_id,
            learning_items.lexeme_id,
            learning_items.text,
            learning_items.image_ref,
            learning_items.audio_ref,
            learning_items.is_archived,
            learning_items.created_at,
            learning_items.updated_at
        FROM learning_items
        WHERE learning_items.workspace_id = ?
    """
    parameters: tuple[int, ...] | tuple[int, int] = (stored_workspace_id,)
    if not include_archived:
        query = f"{query}\nAND learning_items.is_archived = 0"
    query = f"{query}\nORDER BY learning_items.id"
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


def update_learning_item(
    teacher_user_id: int,
    learning_item_id: int,
    *,
    text: str | None = None,
    image_ref: str | None = None,
    audio_ref: str | None = None,
) -> None:
    learning_item = get_learning_item(learning_item_id)
    if learning_item is None:
        return
    ensure_teacher_can_edit_workspace_content(int(learning_item["workspace_id"]), teacher_user_id)
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE learning_items
            SET text = COALESCE(?, text),
                image_ref = COALESCE(?, image_ref),
                audio_ref = COALESCE(?, audio_ref),
                is_archived = 0,
                updated_at = ?
            WHERE id = ?
            """,
            (text, image_ref, audio_ref, utc_now(), learning_item_id),
        )


def upsert_learning_item_translation(
    teacher_user_id: int,
    learning_item_id: int,
    language_code: str,
    translation_text: str,
) -> None:
    learning_item = get_learning_item(learning_item_id)
    if learning_item is None:
        return
    ensure_teacher_can_edit_workspace_content(int(learning_item["workspace_id"]), teacher_user_id)
    timestamp = utc_now()
    with get_connection() as connection:
        existing = connection.execute(
            """
            SELECT id
            FROM learning_item_translations
            WHERE learning_item_id = ? AND language_code = ?
            ORDER BY id
            LIMIT 1
            """,
            (learning_item_id, language_code),
        ).fetchone()
        if existing is None:
            connection.execute(
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
        else:
            connection.execute(
                """
                UPDATE learning_item_translations
                SET translation_text = ?, updated_at = ?
                WHERE id = ?
                """,
                (translation_text, timestamp, int(existing["id"])),
            )


def archive_learning_item(
    teacher_user_id: int,
    learning_item_id: int,
) -> None:
    learning_item = get_learning_item(learning_item_id)
    if learning_item is None:
        return
    ensure_teacher_can_edit_workspace_content(int(learning_item["workspace_id"]), teacher_user_id)
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE learning_items
            SET is_archived = 1, updated_at = ?
            WHERE id = ?
            """,
            (utc_now(), learning_item_id),
        )


def publish_learning_item_to_workspace(
    learning_item_id: int,
    target_workspace_id: int,
) -> int:
    content = get_learning_item_with_translations(learning_item_id)
    if content is None:
        raise sqlite3.IntegrityError("learning_item not found")

    learning_item = content["learning_item"]
    translations = content["translations"]
    with get_connection() as connection:
        existing = connection.execute(
            """
            SELECT id
            FROM learning_items
            WHERE workspace_id = ? AND source_learning_item_id = ?
            ORDER BY id
            LIMIT 1
            """,
            (target_workspace_id, learning_item_id),
        ).fetchone()
        if existing is None:
            published_learning_item_id = create_learning_item(
                int(learning_item["lexeme_id"]),
                str(learning_item["text"]),
                workspace_id=target_workspace_id,
                image_ref=learning_item["image_ref"],
                audio_ref=learning_item["audio_ref"],
                source_learning_item_id=learning_item_id,
            )
        else:
            published_learning_item_id = int(existing["id"])
            connection.execute(
                """
                UPDATE learning_items
                SET lexeme_id = ?,
                    text = ?,
                    image_ref = ?,
                    audio_ref = ?,
                    is_archived = 0,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    int(learning_item["lexeme_id"]),
                    str(learning_item["text"]),
                    learning_item["image_ref"],
                    learning_item["audio_ref"],
                    utc_now(),
                    published_learning_item_id,
                ),
            )
            connection.execute(
                """
                DELETE FROM learning_item_translations
                WHERE learning_item_id = ?
                """,
                (published_learning_item_id,),
            )
    for translation in translations:
        create_learning_item_translation(
            published_learning_item_id,
            str(translation["language_code"]),
            str(translation["translation_text"]),
        )
    return published_learning_item_id
