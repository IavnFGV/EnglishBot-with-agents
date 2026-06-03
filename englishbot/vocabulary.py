import sqlite3

from .assets import (
    ASSET_TYPE_AUDIO,
    ASSET_TYPE_IMAGE,
    PRIMARY_AUDIO_ROLE,
    PRIMARY_IMAGE_ROLE,
    list_learning_item_assets,
    replace_learning_item_assets_for_role,
    resolve_asset_ref_for_role,
    store_remote_asset,
)
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
    *,
    family_id: int | None = None,
    image_ref: str | None = None,
    audio_ref: str | None = None,
) -> int:
    timestamp = utc_now()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO learning_items (
                family_id,
                lexeme_id,
                text,
                is_archived,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, 0, ?, ?)
            """,
            (family_id, lexeme_id, text, timestamp, timestamp),
        )
    learning_item_id = int(cursor.lastrowid)
    _replace_media_assets(learning_item_id, image_ref=image_ref, audio_ref=audio_ref)
    return learning_item_id


def get_learning_item(learning_item_id: int) -> dict[str, object] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                id,
                family_id,
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
    *,
    family_id: int | None = None,
    include_archived: bool = False,
) -> list[dict[str, object]]:
    query = """
        SELECT
            id,
            family_id,
            lexeme_id,
            text,
            is_archived,
            created_at,
            updated_at
        FROM learning_items
    """
    parameters: list[object] = []
    clauses: list[str] = []
    if family_id is not None:
        clauses.append("family_id = ?")
        parameters.append(family_id)
    if not include_archived:
        clauses.append("is_archived = 0")
    if clauses:
        query = f"{query}\nWHERE " + " AND ".join(clauses)
    query = f"{query}\nORDER BY id"
    if limit is not None:
        query = f"{query}\nLIMIT ?"
        parameters.append(limit)
    with get_connection() as connection:
        rows = connection.execute(query, tuple(parameters)).fetchall()
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
            (learning_item_id, language_code, translation_text, timestamp, timestamp),
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


def get_learning_item_with_translations(learning_item_id: int) -> dict[str, object] | None:
    learning_item = get_learning_item(learning_item_id)
    if learning_item is None:
        return None
    return {
        "learning_item": learning_item,
        "translations": list_learning_item_translations(learning_item_id),
    }


def archive_learning_item(learning_item_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE learning_items
            SET is_archived = 1, updated_at = ?
            WHERE id = ?
            """,
            (utc_now(), learning_item_id),
        )


def _serialize_learning_item_row(
    row: sqlite3.Row,
    connection: sqlite3.Connection,
) -> dict[str, object]:
    return {
        "id": int(row["id"]),
        "family_id": int(row["family_id"]) if row["family_id"] is not None else None,
        "lexeme_id": int(row["lexeme_id"]),
        "text": str(row["text"]),
        "image_ref": resolve_asset_ref_for_role(int(row["id"]), PRIMARY_IMAGE_ROLE),
        "audio_ref": resolve_asset_ref_for_role(int(row["id"]), PRIMARY_AUDIO_ROLE),
        "is_archived": int(row["is_archived"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "assets": [
            dict(asset_row)
            for asset_row in list_learning_item_assets(int(row["id"]), connection=connection)
        ],
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
            assets=[] if not image_ref else [{
                "asset_type": ASSET_TYPE_IMAGE,
                "source_url": source_url,
                "local_path": image_ref,
            }],
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
            assets=[] if not audio_ref else [{
                "asset_type": ASSET_TYPE_AUDIO,
                "source_url": source_url,
                "local_path": audio_ref,
            }],
        )
