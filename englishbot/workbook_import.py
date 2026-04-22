from __future__ import annotations

import re
from collections import OrderedDict
from io import BytesIO
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from openpyxl import load_workbook

from .assets import (
    ASSET_TYPE_AUDIO,
    ASSET_TYPE_IMAGE,
    PRIMARY_AUDIO_ROLE,
    PRIMARY_IMAGE_ROLE,
    replace_learning_item_assets,
    store_workbook_import_asset,
)
from .db import create_workbook_import_backup, get_connection, utc_now
from .workbook_export import (
    LEARNING_ITEMS_COLUMNS,
    LEARNING_ITEMS_SHEET_NAME,
    META_COLUMNS,
    META_SHEET_NAME,
    SHEET_NAMES,
    WORKBOOK_VERSION,
)
from .workspaces import ensure_teacher_can_edit_workspace_content


TRANSLATION_LINE_RE = re.compile(r"^<([a-z][a-z0-9_-]{1,15})>:\s*(.+)$")


class WorkbookImportError(Exception):
    pass


def import_teacher_workspace_workbook(
    teacher_user_id: int,
    workspace_id: int,
    workbook_bytes: bytes,
) -> dict[str, int]:
    ensure_teacher_can_edit_workspace_content(workspace_id, teacher_user_id)
    parsed = _parse_workbook(workbook_bytes)
    create_workbook_import_backup()

    with get_connection() as connection:
        plan, errors = _build_import_plan(connection, workspace_id, parsed)
    staged_media, media_errors = _stage_grouped_item_media(list(plan.get("grouped_items", [])))
    combined_errors = list(parsed.get("errors", [])) + list(errors) + media_errors
    if combined_errors:
        raise WorkbookImportError("\n".join(combined_errors))

    with get_connection() as connection:
        try:
            _begin_import_transaction(connection)
            report = _apply_import_plan(connection, workspace_id, plan, staged_media)
        except Exception:
            connection.rollback()
            raise
        connection.commit()
    return report


def _parse_workbook(workbook_bytes: bytes) -> dict[str, object]:
    try:
        workbook = load_workbook(filename=BytesIO(workbook_bytes))
    except Exception as exc:  # pragma: no cover
        raise WorkbookImportError("Workbook could not be opened.") from exc

    if workbook.sheetnames != SHEET_NAMES:
        raise WorkbookImportError(
            "Workbook must contain exactly 'meta' and 'learning_items' sheets. "
            "Legacy workbook sheets are no longer supported."
        )

    meta = _parse_meta_sheet(workbook[META_SHEET_NAME])
    learning_items, errors = _parse_learning_items_sheet(
        workbook[LEARNING_ITEMS_SHEET_NAME],
        str(meta["default_translation_language"]),
    )
    return {
        "meta": meta,
        "learning_items": learning_items,
        "errors": errors,
    }


def _parse_meta_sheet(sheet) -> dict[str, str]:
    rows = _read_sheet_rows(sheet, META_COLUMNS)
    if len(rows) != 1:
        raise WorkbookImportError("Sheet 'meta' must contain exactly one data row.")
    row_index, row = rows[0]
    version = _parse_required_text(row, "version", sheet.title, row_index)
    default_workspace = _parse_optional_text(row.get("default_workspace"))
    default_translation_language = _parse_required_text(
        row,
        "default_translation_language",
        sheet.title,
        row_index,
    ).lower()
    return {
        "version": version,
        "default_workspace": default_workspace,
        "default_translation_language": default_translation_language,
    }


def _parse_learning_items_sheet(
    sheet,
    default_translation_language: str,
) -> tuple[list[dict[str, object]], list[str]]:
    rows = _read_sheet_rows(sheet, LEARNING_ITEMS_COLUMNS)
    parsed_rows: list[dict[str, object]] = []
    errors: list[str] = []
    for row_index, row in rows:
        row_errors: list[str] = []
        text = _capture_parse_error(
            row_errors,
            lambda: _parse_required_text(row, "text", sheet.title, row_index),
        )
        translations = _capture_parse_error(
            row_errors,
            lambda: _parse_translation_cell(
                row.get("translations"),
                default_translation_language,
                sheet.title,
                row_index,
            ),
        )
        image_url = _capture_parse_error(
            row_errors,
            lambda: _parse_media_reference(
                row.get("image_url"),
                sheet.title,
                row_index,
                "image_url",
                require_url=True,
            ),
        )
        image_preview = _capture_parse_error(
            row_errors,
            lambda: _parse_media_reference(
                row.get("image_preview"),
                sheet.title,
                row_index,
                "image_preview",
                require_url=False,
            ),
        )
        audio_url = _capture_parse_error(
            row_errors,
            lambda: _parse_media_reference(
                row.get("audio_url"),
                sheet.title,
                row_index,
                "audio_url",
                require_url=True,
            ),
        )
        is_archived = _capture_parse_error(
            row_errors,
            lambda: _parse_archive_value(row.get("is_archived"), sheet.title, row_index),
        )
        if row_errors:
            errors.extend(row_errors)
            continue
        parsed_rows.append(
            {
                "row_index": row_index,
                "text": text,
                "translations": translations,
                "workspace": _parse_optional_text(row.get("workspace")),
                "topic": _parse_optional_text(row.get("topic")),
                "image_url": image_url,
                "image_preview": image_preview,
                "audio_url": audio_url,
                "audio_voice": _parse_optional_text(row.get("audio_voice")),
                "is_archived": is_archived,
            }
        )
    return parsed_rows, errors


def _capture_parse_error(errors: list[str], parser):
    try:
        return parser()
    except WorkbookImportError as exc:
        errors.append(str(exc))
        return None


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


def _parse_archive_value(value: object, sheet_name: str, row_index: int) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int) and value in (0, 1):
        return value
    normalized = _parse_optional_text(value)
    if normalized in {"0", "1"}:
        return int(normalized)
    raise WorkbookImportError(
        f"Sheet '{sheet_name}' row {row_index} has invalid archive value '{value}'."
    )


def _parse_translation_cell(
    value: object,
    default_translation_language: str,
    sheet_name: str,
    row_index: int,
) -> dict[str, str]:
    normalized = _parse_optional_text(value)
    if normalized is None:
        return {}
    translations: dict[str, str] = {}
    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = TRANSLATION_LINE_RE.match(line)
        if match is not None:
            language_code = match.group(1).lower()
            translation_text = match.group(2).strip()
        elif line.startswith("<"):
            raise WorkbookImportError(
                f"Sheet '{sheet_name}' row {row_index} has invalid translation syntax '{line}'."
            )
        else:
            language_code = default_translation_language
            translation_text = line
        if language_code in translations:
            raise WorkbookImportError(
                f"Sheet '{sheet_name}' row {row_index} has duplicate translation language '{language_code}'."
            )
        translations[language_code] = translation_text
    return translations


def _parse_media_reference(
    value: object,
    sheet_name: str,
    row_index: int,
    column_name: str,
    *,
    require_url: bool,
) -> str | None:
    normalized = _parse_optional_text(value)
    if normalized is None:
        return None
    parsed = urlparse(normalized)
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        raise WorkbookImportError(
            f"Sheet '{sheet_name}' row {row_index} has unsupported URL in '{column_name}'."
        )
    if require_url and parsed.scheme not in {"http", "https"}:
        raise WorkbookImportError(
            f"Sheet '{sheet_name}' row {row_index} requires an http(s) URL in '{column_name}'."
        )
    return normalized


def _build_import_plan(connection, workspace_id: int, parsed: dict[str, object]) -> tuple[dict[str, object], list[str]]:
    meta = parsed["meta"]
    workbook_version = str(meta["version"])
    default_workspace = (
        str(meta["default_workspace"])
        if meta["default_workspace"] is not None
        else None
    )
    default_translation_language = str(meta["default_translation_language"])
    target_workspace = connection.execute(
        """
        SELECT id, name
        FROM workspaces
        WHERE id = ?
        """,
        (workspace_id,),
    ).fetchone()
    if target_workspace is None:
        return {}, ["Workspace not found."]

    target_workspace_name = str(target_workspace["name"])
    errors: list[str] = []
    if workbook_version != WORKBOOK_VERSION:
        errors.append(
            f"Sheet 'meta' has unsupported version '{workbook_version}'. Expected '{WORKBOOK_VERSION}'."
        )
    if default_workspace is not None and default_workspace != target_workspace_name:
        errors.append(
            "Sheet 'meta' default_workspace must match the target workspace name "
            f"'{target_workspace_name}'."
        )
    if not TRANSLATION_LINE_RE.match(f"<{default_translation_language}>: ok"):
        errors.append(
            "Sheet 'meta' has invalid default_translation_language "
            f"'{default_translation_language}'."
        )

    duplicate_workspace = connection.execute(
        """
        SELECT id
        FROM workspaces
        WHERE name = ?
          AND id != ?
        ORDER BY id
        LIMIT 1
        """,
        (target_workspace_name, workspace_id),
    ).fetchone()
    if duplicate_workspace is not None:
        errors.append(
            f"Workspace name '{target_workspace_name}' is not globally unique, so workbook import is blocked."
        )

    existing_items = connection.execute(
        """
        SELECT id, text
        FROM learning_items
        WHERE workspace_id = ?
        ORDER BY id
        """,
        (workspace_id,),
    ).fetchall()
    existing_item_ids_by_text: dict[str, int] = {}
    existing_item_duplicates: set[str] = set()
    for row in existing_items:
        text = str(row["text"])
        if text in existing_item_ids_by_text:
            existing_item_duplicates.add(text)
            continue
        existing_item_ids_by_text[text] = int(row["id"])
    for duplicated_text in sorted(existing_item_duplicates):
        errors.append(
            f"Existing learning item text '{duplicated_text}' is duplicated in the target workspace."
        )

    grouped_items: OrderedDict[str, dict[str, object]] = OrderedDict()
    topic_names_in_order: OrderedDict[str, None] = OrderedDict()
    topic_titles: dict[str, str] = {}
    for row in parsed["learning_items"]:
        row_index = int(row["row_index"])
        effective_workspace = (
            str(row["workspace"])
            if row["workspace"] is not None
            else default_workspace
        )
        if effective_workspace is None:
            errors.append(
                f"Sheet '{LEARNING_ITEMS_SHEET_NAME}' row {row_index} requires 'workspace' when meta.default_workspace is empty."
            )
            continue
        if effective_workspace != target_workspace_name:
            errors.append(
                f"Sheet '{LEARNING_ITEMS_SHEET_NAME}' row {row_index} targets workspace "
                f"'{effective_workspace}', but only '{target_workspace_name}' can be imported here."
            )
        if row["audio_voice"] is not None and row["audio_url"] is None:
            errors.append(
                f"Sheet '{LEARNING_ITEMS_SHEET_NAME}' row {row_index} has 'audio_voice' without 'audio_url'."
            )

        topic_name = str(row["topic"]) if row["topic"] is not None else None
        if topic_name is not None:
            topic_names_in_order.setdefault(topic_name, None)
            previous_title = topic_titles.setdefault(topic_name, topic_name)
            if previous_title != topic_name:
                errors.append(
                    f"Sheet '{LEARNING_ITEMS_SHEET_NAME}' row {row_index} has inconsistent topic name '{topic_name}'."
                )

        item_key = str(row["text"])
        grouped_item = grouped_items.get(item_key)
        comparable_fields = {
            "translations": dict(row["translations"]),
            "image_url": row["image_url"],
            "image_preview": row["image_preview"],
            "audio_url": row["audio_url"],
            "audio_voice": row["audio_voice"],
            "is_archived": int(row["is_archived"]),
        }
        if grouped_item is None:
            grouped_items[item_key] = {
                "text": item_key,
                "translations": comparable_fields["translations"],
                "image_url": comparable_fields["image_url"],
                "image_preview": comparable_fields["image_preview"],
                "audio_url": comparable_fields["audio_url"],
                "audio_voice": comparable_fields["audio_voice"],
                "is_archived": comparable_fields["is_archived"],
                "topics": [] if topic_name is None else [topic_name],
            }
            continue

        if (
            grouped_item["translations"] != comparable_fields["translations"]
            or grouped_item["image_url"] != comparable_fields["image_url"]
            or grouped_item["image_preview"] != comparable_fields["image_preview"]
            or grouped_item["audio_url"] != comparable_fields["audio_url"]
            or grouped_item["audio_voice"] != comparable_fields["audio_voice"]
            or grouped_item["is_archived"] != comparable_fields["is_archived"]
        ):
            errors.append(
                f"Sheet '{LEARNING_ITEMS_SHEET_NAME}' row {row_index} duplicates text '{item_key}' "
                "with conflicting item data."
            )
            continue
        if topic_name is not None and topic_name not in grouped_item["topics"]:
            grouped_item["topics"].append(topic_name)

    if topic_names_in_order:
        duplicate_topic_rows = connection.execute(
            """
            SELECT topics.name, workspaces.name AS workspace_name
            FROM topics
            JOIN workspaces
              ON workspaces.id = topics.workspace_id
            WHERE topics.name IN ({placeholders})
              AND topics.workspace_id != ?
            ORDER BY topics.name, topics.id
            """.format(
                placeholders=", ".join("?" for _ in topic_names_in_order)
            ),
            tuple(topic_names_in_order.keys()) + (workspace_id,),
        ).fetchall()
        for row in duplicate_topic_rows:
            errors.append(
                f"Topic name '{row['name']}' already exists in workspace '{row['workspace_name']}', "
                "so topic names are treated as globally unique for this import."
            )

    existing_topics = connection.execute(
        """
        SELECT id, name
        FROM topics
        WHERE workspace_id = ?
        ORDER BY id
        """,
        (workspace_id,),
    ).fetchall()
    existing_topic_ids_by_name = {str(row["name"]): int(row["id"]) for row in existing_topics}

    return {
        "default_translation_language": default_translation_language,
        "grouped_items": list(grouped_items.values()),
        "topic_names": list(topic_names_in_order.keys()),
        "existing_topic_ids_by_name": existing_topic_ids_by_name,
        "existing_item_ids_by_text": existing_item_ids_by_text,
    }, errors


def _begin_import_transaction(connection) -> None:
    connection.execute("BEGIN IMMEDIATE")


def _stage_grouped_item_media(
    grouped_items: list[dict[str, object]],
) -> tuple[dict[str, dict[str, str]], list[str]]:
    staged_media: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    for grouped_item in grouped_items:
        text = str(grouped_item["text"])
        if grouped_item["image_url"] is not None:
            try:
                staged_media.setdefault(text, {})["image_local_path"] = _download_media_asset(
                    str(grouped_item["image_url"]),
                    ASSET_TYPE_IMAGE,
                )
            except WorkbookImportError as exc:
                errors.append(str(exc))
        if grouped_item["audio_url"] is not None:
            try:
                staged_media.setdefault(text, {})["audio_local_path"] = _download_media_asset(
                    str(grouped_item["audio_url"]),
                    ASSET_TYPE_AUDIO,
                )
            except WorkbookImportError as exc:
                errors.append(str(exc))
    return staged_media, errors


def _download_media_asset(reference: str, asset_type: str) -> str:
    try:
        with urlopen(reference, timeout=10) as response:
            content = response.read()
    except (OSError, URLError) as exc:
        raise WorkbookImportError(
            f"Workbook media download failed for '{reference}': {exc}"
        ) from exc
    if not content:
        raise WorkbookImportError(f"Workbook media download failed for '{reference}': empty response.")
    return store_workbook_import_asset(asset_type, content, source_url=reference)


def _apply_import_plan(
    connection,
    workspace_id: int,
    plan: dict[str, object],
    staged_media: dict[str, dict[str, str]],
) -> dict[str, int]:
    topic_ids_by_name, topic_stats = _upsert_topics(
        connection,
        workspace_id,
        list(plan["topic_names"]),
        dict(plan["existing_topic_ids_by_name"]),
    )
    learning_item_ids_by_text, learning_item_stats = _upsert_learning_items(
        connection,
        workspace_id,
        list(plan["grouped_items"]),
        dict(plan["existing_item_ids_by_text"]),
        staged_media,
    )
    added_topic_links = _replace_topic_links(
        connection,
        list(plan["grouped_items"]),
        topic_ids_by_name,
        learning_item_ids_by_text,
    )
    _archive_unmatched_topics(connection, workspace_id, topic_ids_by_name)
    _archive_unmatched_learning_items(connection, workspace_id, learning_item_ids_by_text)
    return {
        "created_topics": topic_stats["created"],
        "updated_topics": topic_stats["updated"],
        "created_learning_items": learning_item_stats["created"],
        "updated_learning_items": learning_item_stats["updated"],
        "added_topic_links": added_topic_links,
    }


def _upsert_topics(
    connection,
    workspace_id: int,
    topic_names: list[str],
    existing_topic_ids_by_name: dict[str, int],
) -> tuple[dict[str, int], dict[str, int]]:
    topic_ids_by_name: dict[str, int] = {}
    created = 0
    updated = 0
    for topic_name in topic_names:
        topic_id = existing_topic_ids_by_name.get(topic_name)
        timestamp = utc_now()
        if topic_id is None:
            cursor = connection.execute(
                """
                INSERT INTO topics (
                    workspace_id,
                    name,
                    title,
                    is_archived,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, 0, ?, ?)
                """,
                (workspace_id, topic_name, topic_name, timestamp, timestamp),
            )
            topic_id = int(cursor.lastrowid)
            created += 1
        else:
            connection.execute(
                """
                UPDATE topics
                SET title = ?, is_archived = 0, updated_at = ?
                WHERE id = ?
                """,
                (topic_name, timestamp, topic_id),
            )
            updated += 1
        topic_ids_by_name[topic_name] = topic_id
    return topic_ids_by_name, {"created": created, "updated": updated}


def _upsert_learning_items(
    connection,
    workspace_id: int,
    grouped_items: list[dict[str, object]],
    existing_item_ids_by_text: dict[str, int],
    staged_media: dict[str, dict[str, str]],
) -> tuple[dict[str, int], dict[str, int]]:
    item_ids_by_text: dict[str, int] = {}
    created = 0
    updated = 0
    for grouped_item in grouped_items:
        text = str(grouped_item["text"])
        lexeme_id = _resolve_lexeme_id(connection, text)
        learning_item_id = existing_item_ids_by_text.get(text)
        timestamp = utc_now()
        if learning_item_id is None:
            cursor = connection.execute(
                """
                INSERT INTO learning_items (
                    workspace_id,
                    lexeme_id,
                    text,
                    is_archived,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace_id,
                    lexeme_id,
                    text,
                    int(grouped_item["is_archived"]),
                    timestamp,
                    timestamp,
                ),
            )
            learning_item_id = int(cursor.lastrowid)
            created += 1
        else:
            connection.execute(
                """
                UPDATE learning_items
                SET lexeme_id = ?, is_archived = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    lexeme_id,
                    int(grouped_item["is_archived"]),
                    timestamp,
                    learning_item_id,
                ),
            )
            updated += 1
        _replace_translations(connection, learning_item_id, dict(grouped_item["translations"]))
        _replace_workbook_assets(
            connection,
            learning_item_id,
            grouped_item,
            staged_media.get(text, {}),
        )
        item_ids_by_text[text] = learning_item_id
    return item_ids_by_text, {"created": created, "updated": updated}


def _resolve_lexeme_id(connection, lemma: str) -> int:
    existing = connection.execute(
        "SELECT id FROM lexemes WHERE lemma = ? ORDER BY id LIMIT 1",
        (lemma,),
    ).fetchone()
    if existing is not None:
        return int(existing["id"])
    timestamp = utc_now()
    cursor = connection.execute(
        "INSERT INTO lexemes (lemma, created_at, updated_at) VALUES (?, ?, ?)",
        (lemma, timestamp, timestamp),
    )
    return int(cursor.lastrowid)


def _replace_translations(connection, learning_item_id: int, translations: dict[str, str]) -> None:
    connection.execute(
        """
        DELETE FROM learning_item_translations
        WHERE learning_item_id = ?
        """,
        (learning_item_id,),
    )
    timestamp = utc_now()
    for language_code, translation_text in sorted(translations.items()):
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
            (learning_item_id, language_code, translation_text, timestamp, timestamp),
        )


def _replace_workbook_assets(
    connection,
    learning_item_id: int,
    grouped_item: dict[str, object],
    staged_media: dict[str, str],
) -> None:
    links: list[dict[str, object]] = []
    if grouped_item["image_url"] is not None:
        links.append(
            {
                "asset_type": ASSET_TYPE_IMAGE,
                "role": PRIMARY_IMAGE_ROLE,
                "sort_order": 0,
                "source_url": str(grouped_item["image_url"]),
                "local_path": staged_media.get("image_local_path"),
            }
        )
    if grouped_item["audio_url"] is not None:
        links.append(
            {
                "asset_type": ASSET_TYPE_AUDIO,
                "role": str(grouped_item["audio_voice"] or PRIMARY_AUDIO_ROLE),
                "sort_order": 1,
                "source_url": str(grouped_item["audio_url"]),
                "local_path": staged_media.get("audio_local_path"),
            }
        )
    replace_learning_item_assets(learning_item_id, links, connection=connection)


def _replace_topic_links(
    connection,
    grouped_items: list[dict[str, object]],
    topic_ids_by_name: dict[str, int],
    learning_item_ids_by_text: dict[str, int],
) -> int:
    if topic_ids_by_name:
        connection.execute(
            """
            DELETE FROM topic_learning_items
            WHERE topic_id IN ({placeholders})
            """.format(
                placeholders=", ".join("?" for _ in topic_ids_by_name)
            ),
            tuple(topic_ids_by_name.values()),
        )

    added_links = 0
    for grouped_item in grouped_items:
        learning_item_id = learning_item_ids_by_text[str(grouped_item["text"])]
        for topic_name in grouped_item["topics"]:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO topic_learning_items (topic_id, learning_item_id)
                VALUES (?, ?)
                """,
                (topic_ids_by_name[str(topic_name)], learning_item_id),
            )
            added_links += int(cursor.rowcount or 0)
    return added_links


def _archive_unmatched_topics(connection, workspace_id: int, topic_ids_by_name: dict[str, int]) -> None:
    timestamp = utc_now()
    if not topic_ids_by_name:
        connection.execute(
            """
            UPDATE topics
            SET is_archived = 1, updated_at = ?
            WHERE workspace_id = ?
            """,
            (timestamp, workspace_id),
        )
        return
    connection.execute(
        """
        UPDATE topics
        SET is_archived = 1, updated_at = ?
        WHERE workspace_id = ?
          AND id NOT IN ({placeholders})
        """.format(
            placeholders=", ".join("?" for _ in topic_ids_by_name)
        ),
        (timestamp, workspace_id, *topic_ids_by_name.values()),
    )


def _archive_unmatched_learning_items(
    connection,
    workspace_id: int,
    learning_item_ids_by_text: dict[str, int],
) -> None:
    timestamp = utc_now()
    if not learning_item_ids_by_text:
        connection.execute(
            """
            UPDATE learning_items
            SET is_archived = 1, updated_at = ?
            WHERE workspace_id = ?
            """,
            (timestamp, workspace_id),
        )
        return
    connection.execute(
        """
        UPDATE learning_items
        SET is_archived = 1, updated_at = ?
        WHERE workspace_id = ?
          AND id NOT IN ({placeholders})
        """.format(
            placeholders=", ".join("?" for _ in learning_item_ids_by_text)
        ),
        (timestamp, workspace_id, *learning_item_ids_by_text.values()),
    )
