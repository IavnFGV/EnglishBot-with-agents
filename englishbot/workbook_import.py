from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook

from .assets import (
    ASSET_TYPE_AUDIO,
    ASSET_TYPE_IMAGE,
    PRIMARY_AUDIO_ROLE,
    PRIMARY_IMAGE_ROLE,
    replace_learning_item_assets_for_role,
    store_remote_asset,
)
from .bulk_edit import create_bulk_edit_backup
from .db import get_connection, utc_now
from .workbook_export import LEARNING_ITEMS_SHEET, LEARNING_ITEM_COLUMNS, META_SHEET

SUPPORTED_TRANSLATION_COLUMNS = ("translation_ru", "translation_uk", "translation_bg")
TOPIC_NAME_PATTERN = re.compile(r"[^a-z0-9]+")


class WorkbookImportValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class WorkbookImportRow:
    row_number: int
    item_key: str
    text: str
    translations: dict[str, str]
    topic_titles: list[str]
    image_ref: str
    audio_ref: str
    is_archived: bool


@dataclass(frozen=True)
class FamilyWorkbookImportSummary:
    created: int
    updated: int
    archived: int
    unchanged: int
    backup_file_path: Path


def validate_family_workbook_import(file_path: Path, family_id: int) -> list[WorkbookImportRow]:
    workbook = load_workbook(file_path, data_only=False)
    if META_SHEET not in workbook.sheetnames:
        raise WorkbookImportValidationError([f"Missing required sheet: {META_SHEET}."])
    if LEARNING_ITEMS_SHEET not in workbook.sheetnames:
        raise WorkbookImportValidationError([f"Missing required sheet: {LEARNING_ITEMS_SHEET}."])

    worksheet = workbook[LEARNING_ITEMS_SHEET]
    header_cells = next(worksheet.iter_rows(min_row=1, max_row=1, values_only=True), None)
    header = [str(value or "").strip() for value in (header_cells or ())]
    if tuple(header) != LEARNING_ITEM_COLUMNS:
        raise WorkbookImportValidationError(
            [f"Unexpected workbook columns. Expected: {', '.join(LEARNING_ITEM_COLUMNS)}."]
        )

    existing_item_ids = _load_existing_family_item_ids(family_id)
    errors: list[str] = []
    rows: list[WorkbookImportRow] = []
    seen_item_keys: set[str] = set()

    for row_number, values in enumerate(
        worksheet.iter_rows(min_row=2, values_only=True),
        start=2,
    ):
        normalized = {
            column_name: _normalize_cell(value)
            for column_name, value in zip(LEARNING_ITEM_COLUMNS, values, strict=False)
        }
        if not any(normalized.values()):
            continue
        item_key = normalized["item_key"]
        text = normalized["text"]
        if not text:
            errors.append(f"Row {row_number}: text is required.")
        if item_key:
            if item_key in seen_item_keys:
                errors.append(f"Row {row_number}: duplicate item_key {item_key}.")
            seen_item_keys.add(item_key)
            matched_item_id = _parse_item_key(item_key)
            if matched_item_id is None:
                errors.append(f"Row {row_number}: invalid item_key {item_key}.")
            elif matched_item_id not in existing_item_ids:
                errors.append(f"Row {row_number}: item_key {item_key} does not belong to this family.")
        try:
            is_archived = _parse_boolish(normalized["is_archived"])
        except ValueError:
            errors.append(f"Row {row_number}: invalid is_archived value {normalized['is_archived']!r}.")
            is_archived = False

        topic_titles = _parse_topic_titles(normalized["topics"])
        rows.append(
            WorkbookImportRow(
                row_number=row_number,
                item_key=item_key,
                text=text,
                translations={
                    language_code: normalized[f"translation_{language_code}"]
                    for language_code in ("ru", "uk", "bg")
                    if normalized[f"translation_{language_code}"]
                },
                topic_titles=topic_titles,
                image_ref=normalized["image_ref"],
                audio_ref=normalized["audio_ref"],
                is_archived=is_archived,
            )
        )

    if errors:
        raise WorkbookImportValidationError(errors)
    return rows


def apply_family_workbook_import(
    file_path: Path,
    family_id: int,
    started_by_user_id: int,
    rows: list[WorkbookImportRow] | None = None,
) -> FamilyWorkbookImportSummary:
    if rows is None:
        rows = validate_family_workbook_import(file_path, family_id)
    backup_file_path = create_bulk_edit_backup(family_id=family_id, user_id=started_by_user_id)

    summary = {
        "created": 0,
        "updated": 0,
        "archived": 0,
        "unchanged": 0,
    }
    with get_connection() as connection:
        existing_items = _load_existing_items(connection, family_id)
        existing_topics = _load_existing_topics(connection, family_id)
        imported_item_ids: set[int] = set()
        active_topic_membership: dict[str, list[int]] = {}

        try:
            connection.execute("BEGIN")
            for row in rows:
                imported_item_id, change_kind = _upsert_learning_item(
                    connection,
                    family_id,
                    row,
                    existing_items,
                )
                imported_item_ids.add(imported_item_id)
                summary[change_kind] += 1
                if not row.is_archived:
                    for topic_title in row.topic_titles:
                        active_topic_membership.setdefault(topic_title, []).append(imported_item_id)

            for item_id, item in existing_items.items():
                if item_id in imported_item_ids:
                    continue
                if int(item["is_archived"]) == 0:
                    _archive_learning_item(connection, item_id)
                    summary["archived"] += 1

            _sync_topics(connection, family_id, existing_topics, active_topic_membership)
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    return FamilyWorkbookImportSummary(
        created=int(summary["created"]),
        updated=int(summary["updated"]),
        archived=int(summary["archived"]),
        unchanged=int(summary["unchanged"]),
        backup_file_path=backup_file_path,
    )


def _load_existing_family_item_ids(family_id: int) -> set[int]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id
            FROM learning_items
            WHERE family_id = ?
            """,
            (family_id,),
        ).fetchall()
    return {int(row["id"]) for row in rows}


def _load_existing_items(connection: sqlite3.Connection, family_id: int) -> dict[int, sqlite3.Row]:
    rows = connection.execute(
        """
        SELECT id, family_id, lexeme_id, text, is_archived, created_at, updated_at
        FROM learning_items
        WHERE family_id = ?
        ORDER BY id
        """,
        (family_id,),
    ).fetchall()
    return {int(row["id"]): row for row in rows}


def _load_existing_topics(connection: sqlite3.Connection, family_id: int) -> dict[str, sqlite3.Row]:
    rows = connection.execute(
        """
        SELECT id, family_id, name, title, is_archived, created_at, updated_at
        FROM topics
        WHERE family_id = ?
        ORDER BY id
        """,
        (family_id,),
    ).fetchall()
    return {_normalize_topic_identity(str(row["title"])): row for row in rows}


def _upsert_learning_item(
    connection: sqlite3.Connection,
    family_id: int,
    row: WorkbookImportRow,
    existing_items: dict[int, sqlite3.Row],
) -> tuple[int, str]:
    existing_item = existing_items.get(_parse_item_key(row.item_key) or -1)
    if existing_item is None:
        item_id = _create_learning_item(connection, family_id, row)
        _sync_translations(connection, item_id, row.translations)
        _sync_media_assets(connection, item_id, row)
        return item_id, "created"

    lexeme_id = _get_or_create_lexeme_id(connection, row.text)
    item_id = int(existing_item["id"])
    changed = (
        str(existing_item["text"]) != row.text
        or int(existing_item["lexeme_id"]) != lexeme_id
        or bool(int(existing_item["is_archived"])) != row.is_archived
    )
    if changed:
        connection.execute(
            """
            UPDATE learning_items
            SET lexeme_id = ?,
                text = ?,
                is_archived = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                lexeme_id,
                row.text,
                1 if row.is_archived else 0,
                utc_now(),
                item_id,
            ),
        )
    translation_changed = _sync_translations(connection, item_id, row.translations)
    asset_changed = _sync_media_assets(connection, item_id, row)
    if changed or translation_changed or asset_changed:
        return item_id, "updated"
    return item_id, "unchanged"


def _create_learning_item(connection: sqlite3.Connection, family_id: int, row: WorkbookImportRow) -> int:
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
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            family_id,
            _get_or_create_lexeme_id(connection, row.text),
            row.text,
            1 if row.is_archived else 0,
            utc_now(),
            utc_now(),
        ),
    )
    return int(cursor.lastrowid)


def _sync_translations(
    connection: sqlite3.Connection,
    learning_item_id: int,
    translations: dict[str, str],
) -> bool:
    existing_rows = connection.execute(
        """
        SELECT id, language_code, translation_text
        FROM learning_item_translations
        WHERE learning_item_id = ?
        ORDER BY id
        """,
        (learning_item_id,),
    ).fetchall()
    existing = {str(row["language_code"]): row for row in existing_rows}
    changed = False
    for language_code in ("ru", "uk", "bg"):
        desired_value = translations.get(language_code, "")
        current_row = existing.get(language_code)
        if desired_value:
            if current_row is None:
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
                        desired_value,
                        utc_now(),
                        utc_now(),
                    ),
                )
                changed = True
            elif str(current_row["translation_text"]) != desired_value:
                connection.execute(
                    """
                    UPDATE learning_item_translations
                    SET translation_text = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (desired_value, utc_now(), int(current_row["id"])),
                )
                changed = True
        elif current_row is not None:
            connection.execute(
                """
                DELETE FROM learning_item_translations
                WHERE id = ?
                """,
                (int(current_row["id"]),),
            )
            changed = True
    return changed


def _sync_media_assets(connection: sqlite3.Connection, learning_item_id: int, row: WorkbookImportRow) -> bool:
    image_changed = _replace_asset_ref(
        connection,
        learning_item_id,
        role=PRIMARY_IMAGE_ROLE,
        asset_type=ASSET_TYPE_IMAGE,
        asset_ref=row.image_ref,
        default_extension=".jpg",
    )
    audio_changed = _replace_asset_ref(
        connection,
        learning_item_id,
        role=PRIMARY_AUDIO_ROLE,
        asset_type=ASSET_TYPE_AUDIO,
        asset_ref=row.audio_ref,
        default_extension=".bin",
    )
    return image_changed or audio_changed


def _replace_asset_ref(
    connection: sqlite3.Connection,
    learning_item_id: int,
    *,
    role: str,
    asset_type: str,
    asset_ref: str,
    default_extension: str,
) -> bool:
    existing_assets = connection.execute(
        """
        SELECT assets.local_path, assets.source_url
        FROM learning_item_assets
        JOIN assets
          ON assets.id = learning_item_assets.asset_id
        WHERE learning_item_assets.learning_item_id = ?
          AND learning_item_assets.role = ?
        ORDER BY learning_item_assets.sort_order, learning_item_assets.id
        """,
        (learning_item_id, role),
    ).fetchall()
    current_ref = ""
    if existing_assets:
        current_ref = str(existing_assets[0]["local_path"] or existing_assets[0]["source_url"] or "")
    normalized_ref = asset_ref.strip()
    if current_ref == normalized_ref:
        return False

    source_url = normalized_ref if normalized_ref.startswith(("http://", "https://")) else None
    local_path = normalized_ref
    if source_url is not None:
        local_path = store_remote_asset(
            asset_type,
            source_url,
            filename_prefix=f"learning-item-{learning_item_id}",
            default_extension=default_extension,
        )
    replace_learning_item_assets_for_role(
        learning_item_id,
        role,
        assets=[] if not normalized_ref else [{
            "asset_type": asset_type,
            "source_url": source_url,
            "local_path": local_path,
        }],
        connection=connection,
    )
    return True


def _sync_topics(
    connection: sqlite3.Connection,
    family_id: int,
    existing_topics: dict[str, sqlite3.Row],
    active_topic_membership: dict[str, list[int]],
) -> None:
    active_topic_identities = {_normalize_topic_identity(title) for title in active_topic_membership}
    for topic_title, learning_item_ids in active_topic_membership.items():
        identity = _normalize_topic_identity(topic_title)
        existing_topic = existing_topics.get(identity)
        if existing_topic is None:
            cursor = connection.execute(
                """
                INSERT INTO topics (
                    family_id,
                    name,
                    title,
                    is_archived,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, 0, ?, ?)
                """,
                (
                    family_id,
                    _build_topic_name(identity),
                    topic_title,
                    utc_now(),
                    utc_now(),
                ),
            )
            topic_id = int(cursor.lastrowid)
        else:
            topic_id = int(existing_topic["id"])
            connection.execute(
                """
                UPDATE topics
                SET name = ?,
                    title = ?,
                    is_archived = 0,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    _build_topic_name(identity),
                    topic_title,
                    utc_now(),
                    topic_id,
                ),
            )
        connection.execute(
            """
            DELETE FROM topic_items
            WHERE topic_id = ?
            """,
            (topic_id,),
        )
        for learning_item_id in learning_item_ids:
            connection.execute(
                """
                INSERT INTO topic_items (
                    topic_id,
                    learning_item_id
                )
                VALUES (?, ?)
                """,
                (topic_id, learning_item_id),
            )

    for identity, topic in existing_topics.items():
        if identity in active_topic_identities:
            continue
        connection.execute(
            """
            UPDATE topics
            SET is_archived = 1,
                updated_at = ?
            WHERE id = ?
            """,
            (utc_now(), int(topic["id"])),
        )


def _archive_learning_item(connection: sqlite3.Connection, learning_item_id: int) -> None:
    connection.execute(
        """
        UPDATE learning_items
        SET is_archived = 1,
            updated_at = ?
        WHERE id = ?
        """,
        (utc_now(), learning_item_id),
    )


def _get_or_create_lexeme_id(connection: sqlite3.Connection, lemma: str) -> int:
    existing = connection.execute(
        """
        SELECT id
        FROM lexemes
        WHERE lemma = ?
        LIMIT 1
        """,
        (lemma,),
    ).fetchone()
    if existing is not None:
        return int(existing["id"])
    cursor = connection.execute(
        """
        INSERT INTO lexemes (lemma, created_at, updated_at)
        VALUES (?, ?, ?)
        """,
        (lemma, utc_now(), utc_now()),
    )
    return int(cursor.lastrowid)


def _normalize_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_item_key(value: str) -> int | None:
    if not value:
        return None
    match = re.fullmatch(r"item-(\d+)", value.strip())
    if match is None:
        return None
    return int(match.group(1))


def _parse_boolish(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"", "0", "false", "no"}:
        return False
    if normalized in {"1", "true", "yes"}:
        return True
    try:
        numeric_value = float(normalized)
    except ValueError:
        numeric_value = None
    if numeric_value == 0.0:
        return False
    if numeric_value == 1.0:
        return True
    raise ValueError("invalid boolean value")


def _parse_topic_titles(value: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw_topic in re.split(r"[\n,;]+", value):
        topic_title = raw_topic.strip()
        if not topic_title:
            continue
        identity = _normalize_topic_identity(topic_title)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(topic_title)
    return result


def _normalize_topic_identity(topic_title: str) -> str:
    return re.sub(r"\s+", " ", topic_title.strip().casefold())


def _build_topic_name(identity: str) -> str:
    base_name = TOPIC_NAME_PATTERN.sub("-", identity).strip("-")
    return base_name or "topic"
