from io import BytesIO

from openpyxl import Workbook

from .db import get_connection
from .workspaces import ensure_teacher_can_edit_workspace_content


TOPICS_SHEET_NAME = "topics"
TOPIC_ITEMS_SHEET_NAME = "topic_items"
LEARNING_ITEMS_SHEET_NAME = "learning_items"
SHEET_NAMES = [
    TOPICS_SHEET_NAME,
    TOPIC_ITEMS_SHEET_NAME,
    LEARNING_ITEMS_SHEET_NAME,
]

TOPICS_COLUMNS = [
    "topic_workbook_key",
    "topic_name",
    "topic_title",
    "is_archived",
    "topic_db_id",
]
TOPIC_ITEMS_COLUMNS = [
    "topic_workbook_key",
    "learning_item_workbook_key",
    "topic_db_id",
    "learning_item_db_id",
]
LEARNING_ITEMS_COLUMNS = [
    "learning_item_workbook_key",
    "text",
    "lexeme_headword",
    "translation_ru",
    "translation_uk",
    "translation_bg",
    "image_ref",
    "image",
    "audio_ref",
    "is_archived",
    "learning_item_db_id",
    "lexeme_db_id",
]


def export_teacher_workspace_workbook(teacher_user_id: int, workspace_id: int) -> bytes:
    ensure_teacher_can_edit_workspace_content(workspace_id, teacher_user_id)

    workbook = Workbook()
    topics_sheet = workbook.active
    topics_sheet.title = TOPICS_SHEET_NAME
    topic_items_sheet = workbook.create_sheet(TOPIC_ITEMS_SHEET_NAME)
    learning_items_sheet = workbook.create_sheet(LEARNING_ITEMS_SHEET_NAME)

    _write_sheet(topics_sheet, TOPICS_COLUMNS, _list_topics(workspace_id))
    _write_sheet(topic_items_sheet, TOPIC_ITEMS_COLUMNS, _list_topic_items(workspace_id))
    _write_sheet(
        learning_items_sheet,
        LEARNING_ITEMS_COLUMNS,
        _list_learning_items(workspace_id),
    )

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _write_sheet(sheet, columns: list[str], rows: list[tuple[object, ...]]) -> None:
    sheet.append(columns)
    for row in rows:
        sheet.append(list(row))


def _build_google_sheets_image_formula(image_ref: str | None) -> str | None:
    if image_ref is None:
        return None
    normalized_ref = str(image_ref).strip()
    if not normalized_ref:
        return None
    escaped_ref = normalized_ref.replace('"', '""')
    return f'=IMAGE("{escaped_ref}")'


def _list_topics(workspace_id: int) -> list[tuple[object, ...]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                workbook_key,
                name,
                title,
                is_archived,
                id
            FROM topics
            WHERE workspace_id = ?
            ORDER BY id
            """,
            (workspace_id,),
        ).fetchall()
    return [
        (
            str(row["workbook_key"]),
            str(row["name"]),
            str(row["title"]),
            int(row["is_archived"]),
            int(row["id"]),
        )
        for row in rows
    ]


def _list_topic_items(workspace_id: int) -> list[tuple[object, ...]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                topics.workbook_key AS topic_workbook_key,
                learning_items.workbook_key AS learning_item_workbook_key,
                topics.id AS topic_db_id,
                learning_items.id AS learning_item_db_id
            FROM topic_learning_items
            JOIN topics
              ON topics.id = topic_learning_items.topic_id
            JOIN learning_items
              ON learning_items.id = topic_learning_items.learning_item_id
            WHERE topics.workspace_id = ?
              AND learning_items.workspace_id = ?
            ORDER BY topic_learning_items.id
            """,
            (workspace_id, workspace_id),
        ).fetchall()
    return [
        (
            str(row["topic_workbook_key"]),
            str(row["learning_item_workbook_key"]),
            int(row["topic_db_id"]),
            int(row["learning_item_db_id"]),
        )
        for row in rows
    ]


def _list_learning_items(workspace_id: int) -> list[tuple[object, ...]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                learning_items.workbook_key,
                learning_items.text,
                lexemes.lemma AS lexeme_headword,
                (
                    SELECT translation_text
                    FROM learning_item_translations
                    WHERE learning_item_id = learning_items.id
                      AND language_code = 'ru'
                    ORDER BY id
                    LIMIT 1
                ) AS translation_ru,
                (
                    SELECT translation_text
                    FROM learning_item_translations
                    WHERE learning_item_id = learning_items.id
                      AND language_code = 'uk'
                    ORDER BY id
                    LIMIT 1
                ) AS translation_uk,
                (
                    SELECT translation_text
                    FROM learning_item_translations
                    WHERE learning_item_id = learning_items.id
                      AND language_code = 'bg'
                    ORDER BY id
                    LIMIT 1
                ) AS translation_bg,
                learning_items.image_ref,
                learning_items.audio_ref,
                learning_items.is_archived,
                learning_items.id AS learning_item_db_id,
                learning_items.lexeme_id AS lexeme_db_id
            FROM learning_items
            JOIN lexemes
              ON lexemes.id = learning_items.lexeme_id
            WHERE learning_items.workspace_id = ?
            ORDER BY learning_items.id
            """,
            (workspace_id,),
        ).fetchall()
    return [
        (
            str(row["workbook_key"]),
            str(row["text"]),
            str(row["lexeme_headword"]),
            row["translation_ru"],
            row["translation_uk"],
            row["translation_bg"],
            row["image_ref"],
            _build_google_sheets_image_formula(row["image_ref"]),
            row["audio_ref"],
            int(row["is_archived"]),
            int(row["learning_item_db_id"]),
            int(row["lexeme_db_id"]),
        )
        for row in rows
    ]
