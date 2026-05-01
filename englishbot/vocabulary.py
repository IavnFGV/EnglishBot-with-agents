import sqlite3

from .assets import (
    ASSET_TYPE_AUDIO,
    ASSET_TYPE_IMAGE,
    PRIMARY_AUDIO_ROLE,
    PRIMARY_IMAGE_ROLE,
    clone_learning_item_assets,
    list_learning_item_assets,
    replace_learning_item_assets_for_role,
    resolve_asset_ref_for_role,
    store_remote_asset,
)
from .db import (
    get_connection,
    get_default_content_workspace_id,
    utc_now,
)
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
    workbook_key: str | None = None,
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
                workbook_key,
                source_learning_item_id,
                lexeme_id,
                text,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stored_workspace_id,
                workbook_key,
                source_learning_item_id,
                lexeme_id,
                text,
                timestamp,
                timestamp,
            ),
        )
    learning_item_id = int(cursor.lastrowid)
    _replace_media_assets(learning_item_id, image_ref=image_ref, audio_ref=audio_ref)
    return learning_item_id


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


def get_learning_item(learning_item_id: int) -> dict[str, object] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                id,
                workspace_id,
                workbook_key,
                source_learning_item_id,
                lexeme_id,
                text,
                is_archived,
                created_at,
                updated_at
            FROM learning_items
            WHERE id = ?
            """,
            (learning_item_id,),
        ).fetchone()
        return _serialize_learning_item_row(row, connection) if row is not None else None


def list_learning_items(
    limit: int | None = None,
    workspace_id: int | None = None,
    include_archived: bool = False,
) -> list[dict[str, object]]:
    stored_workspace_id = (
        get_default_content_workspace_id() if workspace_id is None else int(workspace_id)
    )
    query = """
        SELECT
            learning_items.id,
            learning_items.workspace_id,
            learning_items.workbook_key,
            learning_items.source_learning_item_id,
            learning_items.lexeme_id,
            learning_items.text,
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
        rows = connection.execute(query, parameters).fetchall()
        return [_serialize_learning_item_row(row, connection) for row in rows]


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
) -> dict[str, object] | None:
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
                is_archived = 0,
                updated_at = ?
            WHERE id = ?
            """,
            (text, utc_now(), learning_item_id),
        )
    _replace_media_assets(learning_item_id, image_ref=image_ref, audio_ref=audio_ref)


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
                source_learning_item_id=learning_item_id,
            )
        else:
            published_learning_item_id = int(existing["id"])
            connection.execute(
                """
                UPDATE learning_items
                SET lexeme_id = ?,
                    text = ?,
                    is_archived = 0,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    int(learning_item["lexeme_id"]),
                    str(learning_item["text"]),
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
    clone_learning_item_assets(learning_item_id, published_learning_item_id)
    return published_learning_item_id


def _serialize_learning_item_row(
    row: sqlite3.Row,
    connection: sqlite3.Connection,
) -> dict[str, object]:
    return {
        "id": int(row["id"]),
        "workspace_id": int(row["workspace_id"]),
        "workbook_key": str(row["workbook_key"]) if row["workbook_key"] is not None else None,
        "source_learning_item_id": (
            int(row["source_learning_item_id"])
            if row["source_learning_item_id"] is not None
            else None
        ),
        "lexeme_id": int(row["lexeme_id"]),
        "text": str(row["text"]),
        "image_ref": resolve_asset_ref_for_role(int(row["id"]), PRIMARY_IMAGE_ROLE),
        "audio_ref": resolve_asset_ref_for_role(int(row["id"]), PRIMARY_AUDIO_ROLE),
        "is_archived": int(row["is_archived"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "assets": [dict(asset_row) for asset_row in list_learning_item_assets(int(row["id"]), connection=connection)],
    }


def _replace_media_assets(
    learning_item_id: int,
    *,
    image_ref: str | None = None,
    audio_ref: str | None = None,
) -> None:
    if image_ref is not None:
        source_url = None
        if image_ref.startswith(("http://", "https://")):
            source_url = image_ref
            image_ref = store_remote_asset(
                ASSET_TYPE_IMAGE,
                image_ref,
                filename_prefix=f"learning-item-{learning_item_id}",
                default_extension=".jpg",
            )
        replace_learning_item_assets_for_role(
            learning_item_id,
            PRIMARY_IMAGE_ROLE,
            assets=[
                {
                    "asset_type": ASSET_TYPE_IMAGE,
                    "source_url": source_url,
                    "local_path": image_ref,
                }
            ] if image_ref else [],
        )
    if audio_ref is not None:
        source_url = None
        if audio_ref.startswith(("http://", "https://")):
            source_url = audio_ref
            audio_ref = store_remote_asset(
                ASSET_TYPE_AUDIO,
                audio_ref,
                filename_prefix=f"learning-item-{learning_item_id}",
                default_extension=".bin",
            )
        replace_learning_item_assets_for_role(
            learning_item_id,
            PRIMARY_AUDIO_ROLE,
            assets=[
                {
                    "asset_type": ASSET_TYPE_AUDIO,
                    "source_url": source_url,
                    "local_path": audio_ref,
                }
            ] if audio_ref else [],
        )
