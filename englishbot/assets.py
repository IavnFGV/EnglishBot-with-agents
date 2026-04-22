from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from . import db

TEACHER_CONTENT_IMAGE_DIR = Path("assets/images/teacher-content")
WORKBOOK_IMPORT_ASSET_DIR = Path("assets/workbook-import")
ASSET_TYPE_IMAGE = "image"
ASSET_TYPE_AUDIO = "audio"
ASSET_TYPE_VOICE = "voice"
ASSET_TYPE_VIDEO = "video"
PRIMARY_IMAGE_ROLE = "primary_image"
PRIMARY_AUDIO_ROLE = "primary_audio"
IMAGE_PREVIEW_ROLE = "image_preview"
AUDIO_VOICE_ROLE = "audio_voice"
SUPPORTED_ASSET_TYPES = {
    ASSET_TYPE_IMAGE,
    ASSET_TYPE_AUDIO,
    ASSET_TYPE_VOICE,
    ASSET_TYPE_VIDEO,
}


def create_asset(
    asset_type: str,
    *,
    source_url: str | None = None,
    local_path: str | None = None,
    workbook_key: str | None = None,
) -> int:
    if asset_type not in SUPPORTED_ASSET_TYPES:
        raise ValueError("unsupported asset_type")
    if source_url is None and local_path is None:
        raise ValueError("source_url or local_path is required")

    with db.get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO assets (
                workbook_key,
                asset_type,
                source_url,
                local_path,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (workbook_key, asset_type, source_url, local_path, db.utc_now()),
        )
    return int(cursor.lastrowid)


def link_asset_to_learning_item(
    learning_item_id: int,
    asset_id: int,
    role: str,
    *,
    sort_order: int = 0,
) -> int:
    with db.get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO learning_item_assets (
                learning_item_id,
                asset_id,
                role,
                sort_order
            )
            VALUES (?, ?, ?, ?)
            """,
            (learning_item_id, asset_id, role, sort_order),
        )
    return int(cursor.lastrowid)


def list_learning_item_assets(learning_item_id: int, *, connection=None) -> list:
    owns_connection = connection is None
    if connection is None:
        connection = db.get_connection()
    try:
        return connection.execute(
            """
            SELECT
                learning_item_assets.id,
                learning_item_assets.learning_item_id,
                learning_item_assets.asset_id,
                learning_item_assets.role,
                learning_item_assets.sort_order,
                assets.workbook_key,
                assets.asset_type,
                assets.source_url,
                assets.local_path,
                assets.created_at
            FROM learning_item_assets
            JOIN assets
              ON assets.id = learning_item_assets.asset_id
            WHERE learning_item_assets.learning_item_id = ?
            ORDER BY learning_item_assets.sort_order, learning_item_assets.id
            """,
            (learning_item_id,),
        ).fetchall()
    finally:
        if owns_connection:
            connection.close()


def get_learning_item_asset(
    learning_item_id: int,
    *,
    role: str | None = None,
    asset_type: str | None = None,
    connection=None,
):
    query = """
        SELECT
            learning_item_assets.id,
            learning_item_assets.learning_item_id,
            learning_item_assets.asset_id,
            learning_item_assets.role,
            learning_item_assets.sort_order,
            assets.workbook_key,
            assets.asset_type,
            assets.source_url,
            assets.local_path,
            assets.created_at
        FROM learning_item_assets
        JOIN assets
          ON assets.id = learning_item_assets.asset_id
        WHERE learning_item_assets.learning_item_id = ?
    """
    parameters: list[object] = [learning_item_id]
    if role is not None:
        query += "\nAND learning_item_assets.role = ?"
        parameters.append(role)
    if asset_type is not None:
        query += "\nAND assets.asset_type = ?"
        parameters.append(asset_type)
    query += "\nORDER BY learning_item_assets.sort_order, learning_item_assets.id\nLIMIT 1"
    owns_connection = connection is None
    if connection is None:
        connection = db.get_connection()
    try:
        return connection.execute(query, tuple(parameters)).fetchone()
    finally:
        if owns_connection:
            connection.close()


def resolve_asset_ref(asset_row) -> str | None:
    if asset_row is None:
        return None
    if asset_row["local_path"] is not None:
        return str(asset_row["local_path"])
    if asset_row["source_url"] is not None:
        return str(asset_row["source_url"])
    return None


def resolve_asset_ref_for_role(
    learning_item_id: int,
    role: str,
    *,
    asset_type: str | None = None,
) -> str | None:
    return resolve_asset_ref(
        get_learning_item_asset(
            learning_item_id,
            role=role,
            asset_type=asset_type,
        )
    )


def replace_learning_item_assets(
    learning_item_id: int,
    links: list[dict[str, object]],
    *,
    connection=None,
) -> None:
    if connection is None:
        with db.get_connection() as owned_connection:
            replace_learning_item_assets(
                learning_item_id,
                links,
                connection=owned_connection,
            )
        return
    existing_asset_ids = [
        int(row["asset_id"])
        for row in connection.execute(
            """
            SELECT asset_id
            FROM learning_item_assets
            WHERE learning_item_id = ?
            """,
            (learning_item_id,),
        ).fetchall()
    ]
    connection.execute(
        """
        DELETE FROM learning_item_assets
        WHERE learning_item_id = ?
        """,
        (learning_item_id,),
    )
    for index, link in enumerate(links):
        asset_id = link.get("asset_id")
        if asset_id is None:
            cursor = connection.execute(
                """
                INSERT INTO assets (
                    workbook_key,
                    asset_type,
                    source_url,
                    local_path,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    link.get("workbook_key"),
                    str(link["asset_type"]),
                    link.get("source_url"),
                    link.get("local_path"),
                    db.utc_now(),
                ),
            )
            asset_id = int(cursor.lastrowid)
        connection.execute(
            """
            INSERT INTO learning_item_assets (
                learning_item_id,
                asset_id,
                role,
                sort_order
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                learning_item_id,
                int(asset_id),
                str(link["role"]),
                int(link.get("sort_order", index)),
            ),
        )
    _delete_orphaned_assets(connection, existing_asset_ids)


def replace_learning_item_assets_for_role(
    learning_item_id: int,
    role: str,
    *,
    assets: list[dict[str, object]],
    connection=None,
) -> None:
    existing_assets = [
        link
        for link in (
            list_learning_item_assets(learning_item_id)
            if connection is None
            else connection.execute(
                """
                SELECT
                    learning_item_assets.id,
                    learning_item_assets.learning_item_id,
                    learning_item_assets.asset_id,
                    learning_item_assets.role,
                    learning_item_assets.sort_order,
                    assets.workbook_key,
                    assets.asset_type,
                    assets.source_url,
                    assets.local_path,
                    assets.created_at
                FROM learning_item_assets
                JOIN assets
                  ON assets.id = learning_item_assets.asset_id
                WHERE learning_item_assets.learning_item_id = ?
                ORDER BY learning_item_assets.sort_order, learning_item_assets.id
                """,
                (learning_item_id,),
            ).fetchall()
        )
        if str(link["role"]) != role
    ]
    replacement_links = [
        {
            "asset_id": int(link["asset_id"]),
            "role": str(link["role"]),
            "sort_order": int(link["sort_order"]),
        }
        for link in existing_assets
    ]
    replacement_links.extend(
        [
            {
                "asset_type": str(asset["asset_type"]),
                "source_url": asset.get("source_url"),
                "local_path": asset.get("local_path"),
                "workbook_key": asset.get("workbook_key"),
                "role": role,
                "sort_order": index,
            }
            for index, asset in enumerate(assets)
        ]
    )
    replace_learning_item_assets(learning_item_id, replacement_links, connection=connection)


def clone_learning_item_assets(
    source_learning_item_id: int,
    target_learning_item_id: int,
    *,
    connection=None,
) -> None:
    cloned_links = [
        {
            "asset_type": str(asset["asset_type"]),
            "source_url": asset["source_url"],
            "local_path": asset["local_path"],
            "role": str(asset["role"]),
            "sort_order": int(asset["sort_order"]),
        }
        for asset in (
            list_learning_item_assets(source_learning_item_id)
            if connection is None
            else connection.execute(
                """
                SELECT
                    learning_item_assets.id,
                    learning_item_assets.learning_item_id,
                    learning_item_assets.asset_id,
                    learning_item_assets.role,
                    learning_item_assets.sort_order,
                    assets.workbook_key,
                    assets.asset_type,
                    assets.source_url,
                    assets.local_path,
                    assets.created_at
                FROM learning_item_assets
                JOIN assets
                  ON assets.id = learning_item_assets.asset_id
                WHERE learning_item_assets.learning_item_id = ?
                ORDER BY learning_item_assets.sort_order, learning_item_assets.id
                """,
                (source_learning_item_id,),
            ).fetchall()
        )
    ]
    replace_learning_item_assets(target_learning_item_id, cloned_links, connection=connection)


def store_teacher_content_image(
    learning_item_id: int,
    content: bytes,
    *,
    extension: str = ".jpg",
) -> str:
    if not content:
        raise ValueError("image content is required")

    normalized_extension = extension if extension.startswith(".") else f".{extension}"
    asset_dir = Path(db.DB_PATH).resolve().parent / TEACHER_CONTENT_IMAGE_DIR
    asset_dir.mkdir(parents=True, exist_ok=True)
    filename = f"learning-item-{int(learning_item_id)}-{uuid4().hex}{normalized_extension}"
    output_path = asset_dir / filename
    output_path.write_bytes(content)
    return str((TEACHER_CONTENT_IMAGE_DIR / filename).as_posix())


def store_workbook_import_asset(
    asset_type: str,
    content: bytes,
    *,
    source_url: str,
) -> str:
    if asset_type not in SUPPORTED_ASSET_TYPES:
        raise ValueError("unsupported asset_type")
    if not content:
        raise ValueError("asset content is required")

    suffix = Path(urlparse(source_url).path).suffix.lower()
    if not suffix:
        if asset_type == ASSET_TYPE_IMAGE:
            suffix = ".bin"
        elif asset_type == ASSET_TYPE_AUDIO:
            suffix = ".bin"
        else:
            suffix = ".txt"
    asset_dir = Path(db.DB_PATH).resolve().parent / WORKBOOK_IMPORT_ASSET_DIR / asset_type
    asset_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{asset_type}-{uuid4().hex}{suffix}"
    output_path = asset_dir / filename
    output_path.write_bytes(content)
    return str((WORKBOOK_IMPORT_ASSET_DIR / asset_type / filename).as_posix())


def _delete_orphaned_assets(connection, asset_ids: list[int]) -> None:
    for asset_id in asset_ids:
        linked = connection.execute(
            """
            SELECT 1
            FROM learning_item_assets
            WHERE asset_id = ?
            LIMIT 1
            """,
            (asset_id,),
        ).fetchone()
        if linked is not None:
            continue
        connection.execute(
            """
            DELETE FROM assets
            WHERE id = ?
            """,
            (asset_id,),
        )
