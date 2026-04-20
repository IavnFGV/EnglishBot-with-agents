from io import BytesIO

from openpyxl import load_workbook

from .db import get_connection, utc_now
from .workbook_export import (
    LEARNING_ITEMS_COLUMNS,
    LEARNING_ITEMS_SHEET_NAME,
    TOPIC_ITEMS_COLUMNS,
    TOPIC_ITEMS_SHEET_NAME,
    TOPICS_COLUMNS,
    TOPICS_SHEET_NAME,
)
from .workspaces import ensure_teacher_can_edit_workspace_content


TRANSLATION_COLUMNS = {
    "ru": "translation_ru",
    "uk": "translation_uk",
    "bg": "translation_bg",
}


class WorkbookImportError(Exception):
    pass


def import_teacher_workspace_workbook(
    teacher_user_id: int,
    workspace_id: int,
    workbook_bytes: bytes,
) -> dict[str, int]:
    ensure_teacher_can_edit_workspace_content(workspace_id, teacher_user_id)
    parsed = _parse_workbook(workbook_bytes)

    with get_connection() as connection:
        existing_topics = _load_existing_topics(connection, workspace_id)
        existing_learning_items = _load_existing_learning_items(connection, workspace_id)
        _validate_db_consistency(parsed, existing_topics, existing_learning_items)

        learning_item_ids_by_key, learning_item_stats = _upsert_learning_items(
            connection,
            workspace_id,
            parsed["learning_items"],
            existing_learning_items,
        )
        topic_ids_by_key, topic_stats = _upsert_topics(
            connection,
            workspace_id,
            parsed["topics"],
            existing_topics,
        )
        added_links = _add_topic_links(
            connection,
            parsed["topic_items"],
            topic_ids_by_key,
            learning_item_ids_by_key,
        )

    return {
        "created_topics": topic_stats["created"],
        "updated_topics": topic_stats["updated"],
        "created_learning_items": learning_item_stats["created"],
        "updated_learning_items": learning_item_stats["updated"],
        "added_topic_links": added_links,
    }


def _parse_workbook(workbook_bytes: bytes) -> dict[str, list[dict[str, object]]]:
    try:
        workbook = load_workbook(filename=BytesIO(workbook_bytes))
    except Exception as exc:  # pragma: no cover - library-specific surface
        raise WorkbookImportError("Workbook could not be opened.") from exc

    expected_sheet_names = [
        TOPICS_SHEET_NAME,
        TOPIC_ITEMS_SHEET_NAME,
        LEARNING_ITEMS_SHEET_NAME,
    ]
    if workbook.sheetnames != expected_sheet_names:
        raise WorkbookImportError(
            "Workbook must contain exactly topics, topic_items, and learning_items sheets."
        )

    topics = _parse_topics_sheet(workbook[TOPICS_SHEET_NAME])
    learning_items = _parse_learning_items_sheet(workbook[LEARNING_ITEMS_SHEET_NAME])
    topic_items = _parse_topic_items_sheet(workbook[TOPIC_ITEMS_SHEET_NAME])
    _validate_topic_item_references(topics, learning_items, topic_items)
    return {
        "topics": topics,
        "learning_items": learning_items,
        "topic_items": topic_items,
    }


def _parse_topics_sheet(sheet) -> list[dict[str, object]]:
    rows = _read_sheet_rows(sheet, TOPICS_COLUMNS)
    seen_keys: set[str] = set()
    parsed_rows: list[dict[str, object]] = []
    for row_index, row in rows:
        workbook_key = _parse_required_text(row, "topic_workbook_key", sheet.title, row_index)
        _ensure_unique_workbook_key(workbook_key, seen_keys, sheet.title)
        parsed_rows.append(
            {
                "workbook_key": workbook_key,
                "name": _parse_required_text(row, "topic_name", sheet.title, row_index),
                "title": _parse_required_text(row, "topic_title", sheet.title, row_index),
                "is_archived": _parse_archive_value(row["is_archived"], sheet.title, row_index),
                "db_id": _parse_optional_int(row["topic_db_id"], sheet.title, row_index, "topic_db_id"),
            }
        )
    return parsed_rows


def _parse_learning_items_sheet(sheet) -> list[dict[str, object]]:
    rows = _read_sheet_rows(sheet, LEARNING_ITEMS_COLUMNS)
    seen_keys: set[str] = set()
    parsed_rows: list[dict[str, object]] = []
    for row_index, row in rows:
        workbook_key = _parse_required_text(
            row,
            "learning_item_workbook_key",
            sheet.title,
            row_index,
        )
        _ensure_unique_workbook_key(workbook_key, seen_keys, sheet.title)
        parsed_rows.append(
            {
                "workbook_key": workbook_key,
                "text": _parse_required_text(row, "text", sheet.title, row_index),
                "lexeme_headword": _parse_required_text(
                    row,
                    "lexeme_headword",
                    sheet.title,
                    row_index,
                ),
                "translation_ru": _parse_optional_text(row["translation_ru"]),
                "translation_uk": _parse_optional_text(row["translation_uk"]),
                "translation_bg": _parse_optional_text(row["translation_bg"]),
                "image_ref": _parse_optional_text(row["image_ref"]),
                "audio_ref": _parse_optional_text(row["audio_ref"]),
                "is_archived": _parse_archive_value(row["is_archived"], sheet.title, row_index),
                "db_id": _parse_optional_int(
                    row["learning_item_db_id"],
                    sheet.title,
                    row_index,
                    "learning_item_db_id",
                ),
            }
        )
    return parsed_rows


def _parse_topic_items_sheet(sheet) -> list[dict[str, str]]:
    rows = _read_sheet_rows(sheet, TOPIC_ITEMS_COLUMNS)
    parsed_rows: list[dict[str, str]] = []
    for row_index, row in rows:
        parsed_rows.append(
            {
                "topic_workbook_key": _parse_required_text(
                    row,
                    "topic_workbook_key",
                    sheet.title,
                    row_index,
                ),
                "learning_item_workbook_key": _parse_required_text(
                    row,
                    "learning_item_workbook_key",
                    sheet.title,
                    row_index,
                ),
            }
        )
    return parsed_rows


def _read_sheet_rows(sheet, required_columns: list[str]) -> list[tuple[int, dict[str, object]]]:
    values = list(sheet.iter_rows(values_only=True))
    if not values:
        raise WorkbookImportError(f"Sheet '{sheet.title}' must include a header row.")

    header = [str(value).strip() if value is not None else "" for value in values[0]]
    missing_columns = [column for column in required_columns if column not in header]
    if missing_columns:
        raise WorkbookImportError(
            f"Sheet '{sheet.title}' is missing required columns: {', '.join(missing_columns)}."
        )

    parsed_rows: list[tuple[int, dict[str, object]]] = []
    for row_offset, raw_row in enumerate(values[1:], start=2):
        if all(cell is None for cell in raw_row):
            continue
        row = {
            column_name: raw_row[index] if index < len(raw_row) else None
            for index, column_name in enumerate(header)
        }
        parsed_rows.append((row_offset, row))
    return parsed_rows


def _validate_topic_item_references(
    topics: list[dict[str, object]],
    learning_items: list[dict[str, object]],
    topic_items: list[dict[str, str]],
) -> None:
    topic_keys = {str(row["workbook_key"]) for row in topics}
    learning_item_keys = {str(row["workbook_key"]) for row in learning_items}
    for row in topic_items:
        topic_key = row["topic_workbook_key"]
        learning_item_key = row["learning_item_workbook_key"]
        if topic_key not in topic_keys:
            raise WorkbookImportError(f"topic_items references missing topic workbook_key '{topic_key}'.")
        if learning_item_key not in learning_item_keys:
            raise WorkbookImportError(
                "topic_items references missing learning_item workbook_key "
                f"'{learning_item_key}'."
            )


def _ensure_unique_workbook_key(workbook_key: str, seen_keys: set[str], sheet_name: str) -> None:
    if workbook_key in seen_keys:
        raise WorkbookImportError(
            f"Sheet '{sheet_name}' contains duplicate workbook_key '{workbook_key}'."
        )
    seen_keys.add(workbook_key)


def _parse_required_text(
    row: dict[str, object],
    column_name: str,
    sheet_name: str,
    row_index: int,
) -> str:
    value = _parse_optional_text(row.get(column_name))
    if value is None:
        raise WorkbookImportError(
            f"Sheet '{sheet_name}' row {row_index} requires non-empty '{column_name}'."
        )
    return value


def _parse_optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    return normalized


def _parse_optional_int(
    value: object,
    sheet_name: str,
    row_index: int,
    column_name: str,
) -> int | None:
    normalized = _parse_optional_text(value)
    if normalized is None:
        return None
    try:
        return int(normalized)
    except ValueError as exc:
        raise WorkbookImportError(
            f"Sheet '{sheet_name}' row {row_index} has invalid '{column_name}'."
        ) from exc


def _parse_archive_value(value: object, sheet_name: str, row_index: int) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        if value in (0, 1):
            return value
    normalized = _parse_optional_text(value)
    if normalized in {"0", "1"}:
        return int(normalized)
    raise WorkbookImportError(
        f"Sheet '{sheet_name}' row {row_index} has invalid archive value '{value}'."
    )


def _load_existing_topics(connection, workspace_id: int) -> dict[str, dict[str, object]]:
    rows = connection.execute(
        """
        SELECT id, workbook_key
        FROM topics
        WHERE workspace_id = ?
        """,
        (workspace_id,),
    ).fetchall()
    return {
        str(row["workbook_key"]): {
            "id": int(row["id"]),
        }
        for row in rows
    }


def _load_existing_learning_items(connection, workspace_id: int) -> dict[str, dict[str, object]]:
    rows = connection.execute(
        """
        SELECT id, workbook_key
        FROM learning_items
        WHERE workspace_id = ?
        """,
        (workspace_id,),
    ).fetchall()
    return {
        str(row["workbook_key"]): {
            "id": int(row["id"]),
        }
        for row in rows
    }


def _validate_db_consistency(
    parsed: dict[str, list[dict[str, object]]],
    existing_topics: dict[str, dict[str, object]],
    existing_learning_items: dict[str, dict[str, object]],
) -> None:
    for row in parsed["topics"]:
        existing = existing_topics.get(str(row["workbook_key"]))
        if existing is None or row["db_id"] is None:
            continue
        if int(row["db_id"]) != int(existing["id"]):
            raise WorkbookImportError(
                f"Topic workbook_key '{row['workbook_key']}' does not match topic_db_id."
            )

    for row in parsed["learning_items"]:
        existing = existing_learning_items.get(str(row["workbook_key"]))
        if existing is None or row["db_id"] is None:
            continue
        if int(row["db_id"]) != int(existing["id"]):
            raise WorkbookImportError(
                "Learning item workbook_key "
                f"'{row['workbook_key']}' does not match learning_item_db_id."
            )


def _upsert_learning_items(
    connection,
    workspace_id: int,
    rows: list[dict[str, object]],
    existing_learning_items: dict[str, dict[str, object]],
) -> tuple[dict[str, int], dict[str, int]]:
    ids_by_key: dict[str, int] = {}
    created = 0
    updated = 0
    for row in rows:
        workbook_key = str(row["workbook_key"])
        lexeme_id = _resolve_lexeme_id(connection, str(row["lexeme_headword"]))
        existing = existing_learning_items.get(workbook_key)
        timestamp = utc_now()
        if existing is None:
            cursor = connection.execute(
                """
                INSERT INTO learning_items (
                    workspace_id,
                    workbook_key,
                    lexeme_id,
                    text,
                    image_ref,
                    audio_ref,
                    is_archived,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace_id,
                    workbook_key,
                    lexeme_id,
                    str(row["text"]),
                    row["image_ref"],
                    row["audio_ref"],
                    int(row["is_archived"]),
                    timestamp,
                    timestamp,
                ),
            )
            learning_item_id = int(cursor.lastrowid)
            created += 1
        else:
            learning_item_id = int(existing["id"])
            connection.execute(
                """
                UPDATE learning_items
                SET lexeme_id = ?,
                    text = ?,
                    image_ref = ?,
                    audio_ref = ?,
                    is_archived = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    lexeme_id,
                    str(row["text"]),
                    row["image_ref"],
                    row["audio_ref"],
                    int(row["is_archived"]),
                    timestamp,
                    learning_item_id,
                ),
            )
            updated += 1
        _upsert_wide_translations(connection, learning_item_id, row)
        ids_by_key[workbook_key] = learning_item_id
    return ids_by_key, {"created": created, "updated": updated}


def _resolve_lexeme_id(connection, lemma: str) -> int:
    existing = connection.execute(
        """
        SELECT id
        FROM lexemes
        WHERE lemma = ?
        ORDER BY id
        LIMIT 1
        """,
        (lemma,),
    ).fetchone()
    if existing is not None:
        return int(existing["id"])

    timestamp = utc_now()
    cursor = connection.execute(
        """
        INSERT INTO lexemes (lemma, created_at, updated_at)
        VALUES (?, ?, ?)
        """,
        (lemma, timestamp, timestamp),
    )
    return int(cursor.lastrowid)


def _upsert_wide_translations(
    connection,
    learning_item_id: int,
    row: dict[str, object],
) -> None:
    for language_code, column_name in TRANSLATION_COLUMNS.items():
        translation_text = row[column_name]
        if translation_text is None:
            continue
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
        timestamp = utc_now()
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
            continue
        connection.execute(
            """
            UPDATE learning_item_translations
            SET translation_text = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                translation_text,
                timestamp,
                int(existing["id"]),
            ),
        )


def _upsert_topics(
    connection,
    workspace_id: int,
    rows: list[dict[str, object]],
    existing_topics: dict[str, dict[str, object]],
) -> tuple[dict[str, int], dict[str, int]]:
    ids_by_key: dict[str, int] = {}
    created = 0
    updated = 0
    for row in rows:
        workbook_key = str(row["workbook_key"])
        existing = existing_topics.get(workbook_key)
        timestamp = utc_now()
        if existing is None:
            cursor = connection.execute(
                """
                INSERT INTO topics (
                    workspace_id,
                    workbook_key,
                    name,
                    title,
                    is_archived,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace_id,
                    workbook_key,
                    str(row["name"]),
                    str(row["title"]),
                    int(row["is_archived"]),
                    timestamp,
                    timestamp,
                ),
            )
            topic_id = int(cursor.lastrowid)
            created += 1
        else:
            topic_id = int(existing["id"])
            connection.execute(
                """
                UPDATE topics
                SET name = ?,
                    title = ?,
                    is_archived = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    str(row["name"]),
                    str(row["title"]),
                    int(row["is_archived"]),
                    timestamp,
                    topic_id,
                ),
            )
            updated += 1
        ids_by_key[workbook_key] = topic_id
    return ids_by_key, {"created": created, "updated": updated}


def _add_topic_links(
    connection,
    rows: list[dict[str, str]],
    topic_ids_by_key: dict[str, int],
    learning_item_ids_by_key: dict[str, int],
) -> int:
    added_links = 0
    for row in rows:
        topic_id = topic_ids_by_key[row["topic_workbook_key"]]
        learning_item_id = learning_item_ids_by_key[row["learning_item_workbook_key"]]
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO topic_learning_items (topic_id, learning_item_id)
            VALUES (?, ?)
            """,
            (topic_id, learning_item_id),
        )
        added_links += int(cursor.rowcount > 0)
    return added_links
