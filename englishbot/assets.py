from __future__ import annotations

import hashlib
from io import BytesIO
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from . import db

TEACHER_CONTENT_IMAGE_DIR = Path("assets/images/teacher-content")
NO_IMAGE_PLACEHOLDER_PATH = Path("assets/images/no-image.png")
WORKBOOK_IMPORT_STAGING_DIR = Path("assets/import-staging")
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

REMOTE_ASSET_SUBDIR_BY_TYPE = {
    ASSET_TYPE_IMAGE: Path("assets/images/remote"),
    ASSET_TYPE_AUDIO: Path("assets/audio/remote"),
    ASSET_TYPE_VOICE: Path("assets/voice/remote"),
    ASSET_TYPE_VIDEO: Path("assets/video/remote"),
}

IMPORTED_ASSET_SUBDIR_BY_TYPE = {
    ASSET_TYPE_IMAGE: Path("assets/images/imported"),
    ASSET_TYPE_AUDIO: Path("assets/audio/imported"),
    ASSET_TYPE_VOICE: Path("assets/voice/imported"),
    ASSET_TYPE_VIDEO: Path("assets/video/imported"),
}
SYNTHESIZED_VOICE_SUBDIR = Path("assets/voice/synthesized")
TELEGRAM_MEDIA_KIND_PHOTO = "photo"
TELEGRAM_MEDIA_KIND_AUDIO = "audio"
TELEGRAM_MEDIA_KIND_VOICE = "voice"
SUPPORTED_TELEGRAM_MEDIA_KINDS = {
    TELEGRAM_MEDIA_KIND_PHOTO,
    TELEGRAM_MEDIA_KIND_AUDIO,
    TELEGRAM_MEDIA_KIND_VOICE,
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


def get_asset(asset_id: int, *, connection=None):
    owns_connection = connection is None
    if connection is None:
        connection = db.get_connection()
    try:
        return connection.execute(
            """
            SELECT
                id,
                workbook_key,
                asset_type,
                source_url,
                local_path,
                created_at
            FROM assets
            WHERE id = ?
            LIMIT 1
            """,
            (asset_id,),
        ).fetchone()
    finally:
        if owns_connection:
            connection.close()


def find_asset_by_transport_source(
    *,
    asset_type: str,
    local_path: str | Path | None = None,
    source_url: str | None = None,
    connection=None,
):
    if asset_type not in SUPPORTED_ASSET_TYPES:
        raise ValueError("unsupported asset_type")
    normalized_local_path = str(local_path).strip() if local_path is not None else ""
    normalized_source_url = str(source_url or "").strip()
    if not normalized_local_path and not normalized_source_url:
        return None
    owns_connection = connection is None
    if connection is None:
        connection = db.get_connection()
    try:
        return connection.execute(
            """
            SELECT
                id,
                workbook_key,
                asset_type,
                source_url,
                local_path,
                created_at
            FROM assets
            WHERE asset_type = ?
              AND (
                    (? != '' AND local_path = ?)
                 OR (? != '' AND source_url = ?)
              )
            ORDER BY id DESC
            LIMIT 1
            """,
            (
                asset_type,
                normalized_local_path,
                normalized_local_path,
                normalized_source_url,
                normalized_source_url,
            ),
        ).fetchone()
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


def get_cached_telegram_file_id(asset_id: int, telegram_media_kind: str) -> str | None:
    _validate_telegram_media_kind(telegram_media_kind)
    with db.get_connection() as connection:
        asset_row = get_asset(asset_id, connection=connection)
        if asset_row is None:
            return None
        cache_row = connection.execute(
            """
            SELECT telegram_file_id, asset_fingerprint
            FROM telegram_asset_file_cache
            WHERE asset_id = ? AND telegram_media_kind = ?
            LIMIT 1
            """,
            (asset_id, telegram_media_kind),
        ).fetchone()
        if cache_row is None:
            return None
        current_fingerprint = _build_asset_transport_fingerprint(asset_row)
        cached_fingerprint = cache_row["asset_fingerprint"]
        if current_fingerprint != cached_fingerprint:
            connection.execute(
                """
                DELETE FROM telegram_asset_file_cache
                WHERE asset_id = ? AND telegram_media_kind = ?
                """,
                (asset_id, telegram_media_kind),
            )
            return None
        return str(cache_row["telegram_file_id"])


def cache_telegram_file_id(
    asset_id: int,
    telegram_media_kind: str,
    telegram_file_id: str,
) -> None:
    _validate_telegram_media_kind(telegram_media_kind)
    normalized_file_id = telegram_file_id.strip()
    if not normalized_file_id:
        raise ValueError("telegram_file_id is required")
    with db.get_connection() as connection:
        asset_row = get_asset(asset_id, connection=connection)
        if asset_row is None:
            raise ValueError("asset_id does not exist")
        timestamp = db.utc_now()
        connection.execute(
            """
            INSERT INTO telegram_asset_file_cache (
                asset_id,
                telegram_media_kind,
                telegram_file_id,
                asset_fingerprint,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(asset_id, telegram_media_kind) DO UPDATE SET
                telegram_file_id = excluded.telegram_file_id,
                asset_fingerprint = excluded.asset_fingerprint,
                updated_at = excluded.updated_at
            """,
            (
                asset_id,
                telegram_media_kind,
                normalized_file_id,
                _build_asset_transport_fingerprint(asset_row),
                timestamp,
                timestamp,
            ),
        )


def delete_cached_telegram_file_id(asset_id: int, telegram_media_kind: str) -> None:
    _validate_telegram_media_kind(telegram_media_kind)
    with db.get_connection() as connection:
        connection.execute(
            """
            DELETE FROM telegram_asset_file_cache
            WHERE asset_id = ? AND telegram_media_kind = ?
            """,
            (asset_id, telegram_media_kind),
        )


def get_learning_item_tts_variant(
    learning_item_id: int,
    *,
    voice_id: str,
    tts_model_key: str,
    source_text: str,
    connection=None,
):
    normalized_voice_id = str(voice_id).strip()
    normalized_model_key = str(tts_model_key).strip()
    normalized_source_text = str(source_text).strip()
    if not normalized_voice_id:
        raise ValueError("voice_id is required")
    if not normalized_model_key:
        raise ValueError("tts_model_key is required")
    if not normalized_source_text:
        raise ValueError("source_text is required")
    source_text_hash = build_tts_source_text_hash(normalized_source_text)
    owns_connection = connection is None
    if connection is None:
        connection = db.get_connection()
    try:
        variant_row = connection.execute(
            """
            SELECT
                learning_item_tts_variants.id,
                learning_item_tts_variants.learning_item_id,
                learning_item_tts_variants.asset_id,
                learning_item_tts_variants.voice_id,
                learning_item_tts_variants.tts_model_key,
                learning_item_tts_variants.source_text,
                learning_item_tts_variants.source_text_hash,
                learning_item_tts_variants.created_at,
                learning_item_tts_variants.updated_at,
                assets.asset_type,
                assets.source_url,
                assets.local_path,
                assets.workbook_key
            FROM learning_item_tts_variants
            JOIN assets
              ON assets.id = learning_item_tts_variants.asset_id
            WHERE learning_item_tts_variants.learning_item_id = ?
              AND learning_item_tts_variants.voice_id = ?
              AND learning_item_tts_variants.tts_model_key = ?
              AND learning_item_tts_variants.source_text_hash = ?
            LIMIT 1
            """,
            (
                learning_item_id,
                normalized_voice_id,
                normalized_model_key,
                source_text_hash,
            ),
        ).fetchone()
        if variant_row is None:
            return None
        local_path = str(variant_row["local_path"] or "").strip()
        if not local_path:
            _delete_learning_item_tts_variant(
                connection,
                variant_id=int(variant_row["id"]),
                asset_id=int(variant_row["asset_id"]),
            )
            return None
        resolved_path = resolve_runtime_asset_path(local_path)
        if not resolved_path.is_file():
            _delete_learning_item_tts_variant(
                connection,
                variant_id=int(variant_row["id"]),
                asset_id=int(variant_row["asset_id"]),
            )
            return None
        return variant_row
    finally:
        if owns_connection:
            connection.close()


def create_learning_item_tts_variant(
    learning_item_id: int,
    *,
    voice_id: str,
    tts_model_key: str,
    source_text: str,
    audio_bytes: bytes,
):
    normalized_voice_id = str(voice_id).strip()
    normalized_model_key = str(tts_model_key).strip()
    normalized_source_text = str(source_text).strip()
    if not normalized_voice_id:
        raise ValueError("voice_id is required")
    if not normalized_model_key:
        raise ValueError("tts_model_key is required")
    if not normalized_source_text:
        raise ValueError("source_text is required")
    if not audio_bytes:
        raise ValueError("audio_bytes is required")

    source_text_hash = build_tts_source_text_hash(normalized_source_text)
    existing_variant = get_learning_item_tts_variant(
        learning_item_id,
        voice_id=normalized_voice_id,
        tts_model_key=normalized_model_key,
        source_text=normalized_source_text,
    )
    if existing_variant is not None:
        return existing_variant

    relative_path = _build_tts_variant_relative_path(
        learning_item_id=learning_item_id,
        voice_id=normalized_voice_id,
        tts_model_key=normalized_model_key,
        source_text_hash=source_text_hash,
    )
    output_path = resolve_runtime_asset_path(relative_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio_bytes)

    asset_id: int | None = None
    try:
        asset_id = create_asset(ASSET_TYPE_VOICE, local_path=relative_path)
        timestamp = db.utc_now()
        with db.get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO learning_item_tts_variants (
                    learning_item_id,
                    asset_id,
                    voice_id,
                    tts_model_key,
                    source_text,
                    source_text_hash,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    learning_item_id,
                    asset_id,
                    normalized_voice_id,
                    normalized_model_key,
                    normalized_source_text,
                    source_text_hash,
                    timestamp,
                    timestamp,
                ),
            )
            variant_id = int(cursor.lastrowid)
        variant_row = get_learning_item_tts_variant(
            learning_item_id,
            voice_id=normalized_voice_id,
            tts_model_key=normalized_model_key,
            source_text=normalized_source_text,
        )
        if variant_row is None:
            raise ValueError("created TTS variant could not be reloaded")
        return variant_row
    except Exception:
        output_path.unlink(missing_ok=True)
        if asset_id is not None:
            with db.get_connection() as connection:
                connection.execute(
                    """
                    DELETE FROM assets
                    WHERE id = ?
                    """,
                    (asset_id,),
                )
        raise


def build_tts_source_text_hash(source_text: str) -> str:
    normalized_source_text = str(source_text).strip()
    if not normalized_source_text:
        raise ValueError("source_text is required")
    return hashlib.sha256(normalized_source_text.encode("utf-8")).hexdigest()


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
        _build_asset_replacement_link(role, asset, index)
        for index, asset in enumerate(assets)
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
    asset_dir = _get_runtime_root() / TEACHER_CONTENT_IMAGE_DIR
    asset_dir.mkdir(parents=True, exist_ok=True)
    filename = f"learning-item-{int(learning_item_id)}-{uuid4().hex}{normalized_extension}"
    output_path = asset_dir / filename
    output_path.write_bytes(content)
    return str((TEACHER_CONTENT_IMAGE_DIR / filename).as_posix())


def store_teacher_content_image_from_url(
    learning_item_id: int,
    source_url: str,
) -> str:
    return store_remote_asset(
        ASSET_TYPE_IMAGE,
        source_url,
        preferred_dir=TEACHER_CONTENT_IMAGE_DIR,
        filename_prefix=f"learning-item-{int(learning_item_id)}",
        default_extension=".jpg",
    )


def store_remote_asset(
    asset_type: str,
    source_url: str,
    *,
    preferred_dir: Path | None = None,
    filename_prefix: str | None = None,
    default_extension: str | None = None,
) -> str:
    if asset_type not in SUPPORTED_ASSET_TYPES:
        raise ValueError("unsupported asset_type")
    parsed_url = urlparse(source_url)
    if parsed_url.scheme not in {"http", "https"}:
        raise ValueError(f"{asset_type} url must be http or https")
    content = download_remote_asset_content(asset_type, source_url)

    suffix = _resolve_asset_extension(
        asset_type,
        source_url=source_url,
        content=content,
        default_extension=default_extension,
    )
    relative_dir = preferred_dir or REMOTE_ASSET_SUBDIR_BY_TYPE[asset_type]
    asset_dir = _get_runtime_root() / relative_dir
    asset_dir.mkdir(parents=True, exist_ok=True)

    base_prefix = (filename_prefix or asset_type).strip() or asset_type
    filename = f"{base_prefix}-{uuid4().hex}{suffix}"
    output_path = asset_dir / filename
    output_path.write_bytes(content)
    return str((relative_dir / filename).as_posix())


def download_remote_asset_content(
    asset_type: str,
    source_url: str,
    *,
    timeout_seconds: int = 15,
) -> bytes:
    if asset_type not in SUPPORTED_ASSET_TYPES:
        raise ValueError("unsupported asset_type")
    parsed_url = urlparse(source_url)
    if parsed_url.scheme not in {"http", "https"}:
        raise ValueError(f"{asset_type} url must be http or https")

    with urlopen(source_url, timeout=timeout_seconds) as response:
        content = response.read()
    if not content:
        raise ValueError(f"{asset_type} content is required")
    if asset_type == ASSET_TYPE_IMAGE:
        _validate_image_content(content, source_url=source_url)
    return content


def is_valid_local_image_path(image_path: str | Path) -> bool:
    candidate_path = _get_runtime_root() / Path(str(image_path))
    if not candidate_path.exists() or not candidate_path.is_file():
        return False
    try:
        with Image.open(candidate_path) as image:
            image.verify()
    except (OSError, SyntaxError, UnidentifiedImageError):
        return False
    return True


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

    suffix = _resolve_asset_extension(
        asset_type,
        source_url=source_url,
        content=content,
    )
    asset_dir = _get_runtime_root() / WORKBOOK_IMPORT_STAGING_DIR / asset_type
    asset_dir.mkdir(parents=True, exist_ok=True)
    filename = f"staged-{uuid4().hex}{suffix}"
    output_path = asset_dir / filename
    output_path.write_bytes(content)
    return str((WORKBOOK_IMPORT_STAGING_DIR / asset_type / filename).as_posix())


def finalize_workbook_import_asset(
    asset_id: int,
    asset_type: str,
    staged_local_path: str,
) -> str:
    if asset_type not in SUPPORTED_ASSET_TYPES:
        raise ValueError("unsupported asset_type")
    staged_path = resolve_runtime_asset_path(staged_local_path)
    suffix = staged_path.suffix.lower() or _default_extension_for_asset_type(asset_type)
    relative_dir = IMPORTED_ASSET_SUBDIR_BY_TYPE[asset_type]
    final_relative_path = relative_dir / f"asset-{int(asset_id)}{suffix}"
    final_path = _get_runtime_root() / final_relative_path
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if staged_path.resolve() != final_path.resolve():
        final_path.unlink(missing_ok=True)
        shutil.move(str(staged_path), str(final_path))
    return str(final_relative_path.as_posix())


def resolve_runtime_asset_path(asset_path: str | Path) -> Path:
    return _get_runtime_root() / Path(str(asset_path))


def _delete_orphaned_assets(connection, asset_ids: list[int]) -> None:
    for asset_id in asset_ids:
        tts_variant_linked = connection.execute(
            """
            SELECT 1
            FROM learning_item_tts_variants
            WHERE asset_id = ?
            LIMIT 1
            """,
            (asset_id,),
        ).fetchone()
        if tts_variant_linked is not None:
            continue
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


def _validate_image_content(content: bytes, *, source_url: str) -> None:
    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
    except (OSError, SyntaxError, UnidentifiedImageError) as exc:
        raise ValueError(f"image content from {source_url} is not a valid image") from exc


def _get_runtime_root() -> Path:
    db_parent = Path(db.DB_PATH).resolve().parent
    if db_parent.name == "data":
        return db_parent.parent
    return db_parent


def _validate_telegram_media_kind(telegram_media_kind: str) -> None:
    if telegram_media_kind not in SUPPORTED_TELEGRAM_MEDIA_KINDS:
        raise ValueError("unsupported telegram_media_kind")


def _build_asset_transport_fingerprint(asset_row) -> str:
    local_path = str(asset_row["local_path"] or "").strip()
    source_url = str(asset_row["source_url"] or "").strip()
    asset_type = str(asset_row["asset_type"] or "").strip()
    if local_path:
        resolved_path = resolve_runtime_asset_path(local_path)
        try:
            stat_result = resolved_path.stat()
        except OSError:
            return f"{asset_type}|local|{local_path}|missing"
        return (
            f"{asset_type}|local|{local_path}|"
            f"{stat_result.st_size}|{stat_result.st_mtime_ns}"
        )
    if source_url:
        return f"{asset_type}|source_url|{source_url}"
    return f"{asset_type}|asset_id|{int(asset_row['id'])}"


def _delete_learning_item_tts_variant(connection, *, variant_id: int, asset_id: int) -> None:
    connection.execute(
        """
        DELETE FROM learning_item_tts_variants
        WHERE id = ?
        """,
        (variant_id,),
    )
    _delete_orphaned_assets(connection, [asset_id])


def _build_tts_variant_relative_path(
    *,
    learning_item_id: int,
    voice_id: str,
    tts_model_key: str,
    source_text_hash: str,
) -> str:
    voice_slug = _slugify_tts_identity_part(voice_id)
    model_slug = _slugify_tts_identity_part(tts_model_key)
    hash_prefix = source_text_hash[:16]
    relative_path = (
        SYNTHESIZED_VOICE_SUBDIR
        / f"item-{int(learning_item_id)}"
        / f"item-{int(learning_item_id)}__{voice_slug}__{model_slug}__{hash_prefix}.ogg"
    )
    return str(relative_path.as_posix())


def _slugify_tts_identity_part(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")
    return normalized or "default"


def _build_asset_replacement_link(
    role: str,
    asset: dict[str, object],
    sort_order: int,
) -> dict[str, object]:
    asset_id = asset.get("asset_id")
    if asset_id is not None:
        return {
            "asset_id": int(asset_id),
            "role": role,
            "sort_order": sort_order,
        }
    return {
        "asset_type": str(asset["asset_type"]),
        "source_url": asset.get("source_url"),
        "local_path": asset.get("local_path"),
        "workbook_key": asset.get("workbook_key"),
        "role": role,
        "sort_order": sort_order,
    }


def _resolve_asset_extension(
    asset_type: str,
    *,
    source_url: str,
    content: bytes,
    default_extension: str | None = None,
) -> str:
    parsed_suffix = Path(urlparse(source_url).path).suffix.lower()
    if parsed_suffix and parsed_suffix != ".bin":
        return parsed_suffix
    sniffed_extension = _sniff_asset_extension(asset_type, content)
    if sniffed_extension:
        return sniffed_extension
    if default_extension:
        normalized = default_extension.lower()
        return normalized if normalized.startswith(".") else f".{normalized}"
    return _default_extension_for_asset_type(asset_type)


def _sniff_asset_extension(asset_type: str, content: bytes) -> str | None:
    if asset_type == ASSET_TYPE_IMAGE:
        try:
            with Image.open(BytesIO(content)) as image:
                detected = str(image.format or "").upper()
        except (OSError, SyntaxError, UnidentifiedImageError):
            return None
        image_extensions = {
            "JPEG": ".jpg",
            "PNG": ".png",
            "GIF": ".gif",
            "BMP": ".bmp",
            "WEBP": ".webp",
            "TIFF": ".tiff",
        }
        return image_extensions.get(detected)
    if asset_type in {ASSET_TYPE_AUDIO, ASSET_TYPE_VOICE}:
        if content.startswith(b"ID3") or content[:2] == b"\xff\xfb":
            return ".mp3"
        if content.startswith(b"OggS"):
            return ".ogg"
        if content.startswith(b"RIFF") and content[8:12] == b"WAVE":
            return ".wav"
        if content.startswith(b"fLaC"):
            return ".flac"
        if len(content) > 8 and content[4:8] == b"ftyp":
            return ".m4a"
        return None
    if asset_type == ASSET_TYPE_VIDEO and len(content) > 8 and content[4:8] == b"ftyp":
        return ".mp4"
    return None


def _default_extension_for_asset_type(asset_type: str) -> str:
    defaults = {
        ASSET_TYPE_IMAGE: ".jpg",
        ASSET_TYPE_AUDIO: ".mp3",
        ASSET_TYPE_VOICE: ".ogg",
        ASSET_TYPE_VIDEO: ".mp4",
    }
    return defaults.get(asset_type, ".dat")
