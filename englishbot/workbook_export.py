from io import BytesIO

from openpyxl import Workbook

from .assets import (
    IMAGE_PREVIEW_ROLE,
    ASSET_TYPE_AUDIO,
    PRIMARY_AUDIO_ROLE,
    PRIMARY_IMAGE_ROLE,
    list_learning_item_assets,
    resolve_asset_ref_for_role,
)
from .db import DEFAULT_BOT_LANGUAGE, get_connection
from .workspaces import ensure_teacher_can_edit_workspace_content


WORKBOOK_VERSION = "2"
META_SHEET_NAME = "meta"
LEARNING_ITEMS_SHEET_NAME = "learning_items"
SHEET_NAMES = [META_SHEET_NAME, LEARNING_ITEMS_SHEET_NAME]

META_COLUMNS = [
    "version",
    "default_workspace",
    "default_translation_language",
]
LEARNING_ITEMS_COLUMNS = [
    "text",
    "translations",
    "workspace",
    "topic",
    "image_url",
    "image_preview",
    "audio_url",
    "audio_voice",
    "is_archived",
]


def export_teacher_workspace_workbook(teacher_user_id: int, workspace_id: int) -> bytes:
    ensure_teacher_can_edit_workspace_content(workspace_id, teacher_user_id)

    workbook = Workbook()
    meta_sheet = workbook.active
    meta_sheet.title = META_SHEET_NAME
    learning_items_sheet = workbook.create_sheet(LEARNING_ITEMS_SHEET_NAME)

    default_workspace = _get_workspace_name(workspace_id)
    default_translation_language = _get_default_translation_language(workspace_id)

    _write_sheet(
        meta_sheet,
        META_COLUMNS,
        [
            (
                WORKBOOK_VERSION,
                default_workspace,
                default_translation_language,
            )
        ],
    )
    _write_sheet(
        learning_items_sheet,
        LEARNING_ITEMS_COLUMNS,
        _list_learning_item_rows(workspace_id, default_workspace, default_translation_language),
    )

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _write_sheet(sheet, columns: list[str], rows: list[tuple[object, ...]]) -> None:
    sheet.append(columns)
    for row in rows:
        sheet.append(list(row))


def _get_workspace_name(workspace_id: int) -> str:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT name
            FROM workspaces
            WHERE id = ?
            """,
            (workspace_id,),
        ).fetchone()
    if row is None:
        return ""
    return str(row["name"] or "")


def _get_default_translation_language(workspace_id: int) -> str:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT learning_item_translations.language_code, COUNT(*) AS translation_count
            FROM learning_items
            JOIN learning_item_translations
              ON learning_item_translations.learning_item_id = learning_items.id
            WHERE learning_items.workspace_id = ?
            GROUP BY learning_item_translations.language_code
            ORDER BY translation_count DESC, learning_item_translations.language_code ASC
            LIMIT 1
            """,
            (workspace_id,),
        ).fetchone()
    if row is None or row["language_code"] is None:
        return DEFAULT_BOT_LANGUAGE
    return str(row["language_code"])


def _list_learning_item_rows(
    workspace_id: int,
    default_workspace: str,
    default_translation_language: str,
) -> list[tuple[object, ...]]:
    with get_connection() as connection:
        item_rows = connection.execute(
            """
            SELECT id, text, is_archived
            FROM learning_items
            WHERE workspace_id = ?
            ORDER BY id
            """,
            (workspace_id,),
        ).fetchall()

        rows: list[tuple[object, ...]] = []
        for item_row in item_rows:
            learning_item_id = int(item_row["id"])
            topic_names = _get_topic_names(connection, learning_item_id)
            translations = _format_translations(
                _get_translations(connection, learning_item_id),
                default_translation_language,
            )
            base_row = (
                str(item_row["text"]),
                translations,
                "" if default_workspace else default_workspace,
                None,
                resolve_asset_ref_for_role(learning_item_id, PRIMARY_IMAGE_ROLE),
                resolve_asset_ref_for_role(learning_item_id, IMAGE_PREVIEW_ROLE),
                _get_audio_reference(connection, learning_item_id),
                _get_audio_voice(connection, learning_item_id),
                int(item_row["is_archived"]),
            )
            if not topic_names:
                rows.append(base_row)
                continue
            for topic_name in topic_names:
                rows.append(base_row[:3] + (topic_name,) + base_row[4:])
    return rows


def _get_topic_names(connection, learning_item_id: int) -> list[str]:
    rows = connection.execute(
        """
        SELECT topics.name
        FROM topic_learning_items
        JOIN topics
          ON topics.id = topic_learning_items.topic_id
        WHERE topic_learning_items.learning_item_id = ?
        ORDER BY topics.name, topics.id
        """,
        (learning_item_id,),
    ).fetchall()
    return [str(row["name"]) for row in rows]


def _get_translations(connection, learning_item_id: int) -> dict[str, str]:
    rows = connection.execute(
        """
        SELECT language_code, translation_text
        FROM learning_item_translations
        WHERE learning_item_id = ?
        ORDER BY language_code, id
        """,
        (learning_item_id,),
    ).fetchall()
    translations: dict[str, str] = {}
    for row in rows:
        language_code = str(row["language_code"])
        translations.setdefault(language_code, str(row["translation_text"]))
    return translations


def _get_audio_reference(connection, learning_item_id: int) -> str | None:
    for asset_row in list_learning_item_assets(learning_item_id, connection=connection):
        if str(asset_row["asset_type"]) == ASSET_TYPE_AUDIO:
            if asset_row["source_url"] is not None:
                return str(asset_row["source_url"])
            if asset_row["local_path"] is not None:
                return str(asset_row["local_path"])
    return resolve_asset_ref_for_role(
        learning_item_id,
        PRIMARY_AUDIO_ROLE,
        asset_type=ASSET_TYPE_AUDIO,
    )


def _get_audio_voice(connection, learning_item_id: int) -> str | None:
    for asset_row in list_learning_item_assets(learning_item_id, connection=connection):
        if str(asset_row["asset_type"]) == ASSET_TYPE_AUDIO:
            return str(asset_row["role"])
    return None


def _format_translations(
    translations: dict[str, str],
    default_translation_language: str,
) -> str | None:
    if not translations:
        return None

    lines: list[str] = []
    default_translation = translations.get(default_translation_language)
    if default_translation is not None:
        lines.append(default_translation)
    for language_code in sorted(translations):
        if language_code == default_translation_language:
            continue
        lines.append(f"<{language_code}>: {translations[language_code]}")
    return "\n".join(lines)
