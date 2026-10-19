from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.worksheet import Worksheet

from .assets import PRIMARY_AUDIO_ROLE, PRIMARY_IMAGE_ROLE
from .bulk_edit import get_bulk_edit_export_dir
from .config import get_infra_static_base_url
from .db import get_connection, utc_now

WORKBOOK_VERSION = "family_bulk_edit_v1"
META_SHEET = "meta"
LEARNING_ITEMS_SHEET = "learning_items"
IMAGE_REF_COLUMN_LETTER = "G"
IMAGE_COLUMN_LETTER = "H"
IMAGE_COLUMN_WIDTH = 36
LEARNING_ITEM_ROW_HEIGHT_POINTS = 192
LEARNING_ITEM_COLUMNS = (
    "item_key",
    "text",
    "translation_ru",
    "translation_uk",
    "translation_bg",
    "topics",
    "image_ref",
    "image",
    "audio_ref",
    "is_archived",
)


@dataclass(frozen=True)
class FamilyWorkbookExportResult:
    file_path: Path
    topic_count: int
    learning_item_count: int


def export_family_workbook(
    family_id: int,
    *,
    output_path: Path | None = None,
    include_archived: bool = False,
) -> FamilyWorkbookExportResult:
    if output_path is None:
        output_path = get_bulk_edit_export_dir() / f"family-{family_id}__{utc_now().replace(':', '-')}.xlsx"

    static_base_url = get_infra_static_base_url()
    workbook = Workbook()
    meta_sheet = workbook.active
    meta_sheet.title = META_SHEET
    _write_workbook_instructions(meta_sheet, family_id, include_archived=include_archived)

    learning_items_sheet = workbook.create_sheet(LEARNING_ITEMS_SHEET)
    learning_items_sheet.append(LEARNING_ITEM_COLUMNS)
    learning_items_sheet.column_dimensions[IMAGE_COLUMN_LETTER].width = IMAGE_COLUMN_WIDTH

    topic_titles_by_item_id, topic_count = _load_topic_titles_by_item_id(family_id)
    learning_item_rows = _list_family_learning_item_rows(
        family_id,
        include_archived=include_archived,
    )
    for row in learning_item_rows:
        row_number = learning_items_sheet.max_row + 1
        image_ref = _build_export_image_ref(
            image_ref=str(row["image_ref"] or ""),
            image_source_url=str(row["image_source_url"] or ""),
            static_base_url=static_base_url,
        )
        image_formula = _build_image_formula(
            image_ref=image_ref,
            row_number=row_number,
        )
        learning_items_sheet.append(
            (
                f"item-{int(row['id'])}",
                str(row["text"]),
                str(row["translation_ru"] or ""),
                str(row["translation_uk"] or ""),
                str(row["translation_bg"] or ""),
                "\n".join(topic_titles_by_item_id.get(int(row["id"]), [])),
                image_ref,
                image_formula,
                str(row["audio_ref"] or ""),
                int(row["is_archived"]),
            )
        )
        learning_items_sheet.row_dimensions[row_number].height = LEARNING_ITEM_ROW_HEIGHT_POINTS

    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)
    return FamilyWorkbookExportResult(
        file_path=output_path,
        topic_count=topic_count,
        learning_item_count=len(learning_item_rows),
    )


def _write_workbook_instructions(
    worksheet: Worksheet,
    family_id: int,
    *,
    include_archived: bool,
) -> None:
    worksheet.merge_cells("A1:C1")
    worksheet["A1"] = "Инструкция по работе с учебными словами"
    worksheet["A1"].font = Font(bold=True, color="FFFFFF", size=15)
    worksheet["A1"].fill = PatternFill("solid", fgColor="1F4E78")
    worksheet["A1"].alignment = Alignment(vertical="center")
    worksheet.row_dimensions[1].height = 28

    worksheet.merge_cells("A2:C2")
    worksheet["A2"] = (
        "Экспорт включает активные и архивные слова."
        if include_archived
        else (
            "Экспорт включает активные слова. Архивные слова скрыты; "
            "для просмотра запустите /bulk_edit_with_archived."
        )
    )
    worksheet["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    worksheet.row_dimensions[2].height = 32

    section_fill = PatternFill("solid", fgColor="D9EAF7")
    section_font = Font(bold=True, color="1F1F1F")
    header_fill = PatternFill("solid", fgColor="E2F0D9")
    header_font = Font(bold=True)

    worksheet.merge_cells("A4:C4")
    worksheet["A4"] = "Основные правила"
    worksheet["A4"].font = section_font
    worksheet["A4"].fill = section_fill
    for cell in worksheet[4][:3]:
        cell.fill = section_fill

    rules = (
        (
            "Темы",
            (
                "Назначьте слову одну или несколько тем. Без темы оно не будет видно "
                "в редакторе тем и тематических уроках."
            ),
        ),
        (
            "Как убрать слово",
            (
                "Удалите всю строку и загрузите файл. Слово будет архивировано, а не "
                "удалено из базы. Не удаляйте строки слов, которые хотите оставить активными."
            ),
        ),
        (
            "Архив и восстановление",
            (
                "В /bulk_edit_with_archived установите is_archived = 0 и назначьте тему, "
                "чтобы восстановить слово. Значение 1 оставляет его в архиве."
            ),
        ),
        (
            "Новые слова",
            (
                "Добавьте отдельную строку, оставьте item_key пустым и заполните text. "
                "Не меняйте и не копируйте item_key существующих слов."
            ),
        ),
    )
    for row in rules:
        worksheet.append(row)

    worksheet.merge_cells("A11:C11")
    worksheet["A11"] = "Столбцы листа learning_items"
    worksheet["A11"].font = section_font
    worksheet["A11"].fill = section_fill
    for cell in worksheet[11][:3]:
        cell.fill = section_fill

    worksheet.append(("Столбец", "Назначение", "Как редактировать"))
    for cell in worksheet[12][:3]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(wrap_text=True, vertical="top")

    columns = (
        (
            "item_key",
            "Постоянный идентификатор слова.",
            "Не меняйте и не копируйте. Для нового слова оставьте пустым.",
        ),
        (
            "text",
            "Английское слово или фраза.",
            "Измените текст в этой ячейке, чтобы обновить существующее слово.",
        ),
        (
            "translation_ru",
            "Перевод на русский.",
            "Необязательное поле; пустая ячейка удаляет этот перевод.",
        ),
        (
            "translation_uk",
            "Перевод на украинский.",
            "Необязательное поле; пустая ячейка удаляет этот перевод.",
        ),
        (
            "translation_bg",
            "Перевод на болгарский.",
            "Необязательное поле; пустая ячейка удаляет этот перевод.",
        ),
        (
            "topics",
            "Группы/темы, к которым относится слово.",
            (
                "Перечислите названия тем; разделяйте их новой строкой, запятой или "
                "точкой с запятой. Если поле пустое, слово не появится в редакторе и "
                "уроках по темам."
            ),
        ),
        (
            "image_ref",
            "Ссылка или путь к изображению.",
            "Это редактируемое поле; оставьте пустым, чтобы убрать изображение.",
        ),
        (
            "image",
            "Предпросмотр изображения.",
            "Только для просмотра. Не редактируйте: импорт игнорирует эту колонку.",
        ),
        (
            "audio_ref",
            "Ссылка или путь к аудио.",
            "Это редактируемое поле; оставьте пустым, чтобы убрать аудио.",
        ),
        (
            "is_archived",
            "Состояние слова: 0 — активно, 1 — в архиве.",
            "Используйте 1 для временного исключения из обучения; чтобы восстановить, "
            "укажите 0 и назначьте тему.",
        ),
    )
    for row in columns:
        worksheet.append(row)

    for row in worksheet.iter_rows(min_row=5, max_row=10, min_col=1, max_col=3):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    for row in worksheet.iter_rows(min_row=13, max_row=22, min_col=1, max_col=3):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    worksheet.column_dimensions["A"].width = 24
    worksheet.column_dimensions["B"].width = 44
    worksheet.column_dimensions["C"].width = 88
    for row_number in range(5, 11):
        worksheet.row_dimensions[row_number].height = 48
    for row_number in range(13, 23):
        worksheet.row_dimensions[row_number].height = 42

    metadata_start = 24
    worksheet.cell(metadata_start, 1, "field").font = header_font
    worksheet.cell(metadata_start, 2, "value").font = header_font
    for row_number, (field, value) in enumerate(
        (
            ("version", WORKBOOK_VERSION),
            ("family_id", family_id),
            ("exported_at_utc", utc_now()),
        ),
        start=metadata_start + 1,
    ):
        worksheet.cell(row_number, 1, field)
        worksheet.cell(row_number, 2, value)


def _list_family_learning_item_rows(
    family_id: int,
    *,
    include_archived: bool = False,
) -> list[dict[str, object]]:
    archive_filter = "" if include_archived else "AND learning_items.is_archived = 0"
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT
                learning_items.id,
                learning_items.text,
                learning_items.is_archived,
                MAX(CASE WHEN translations.language_code = 'ru' THEN translations.translation_text END) AS translation_ru,
                MAX(CASE WHEN translations.language_code = 'uk' THEN translations.translation_text END) AS translation_uk,
                MAX(CASE WHEN translations.language_code = 'bg' THEN translations.translation_text END) AS translation_bg,
                image_assets.local_path AS image_local_path,
                image_assets.source_url AS image_source_url,
                audio_assets.local_path AS audio_local_path,
                audio_assets.source_url AS audio_source_url
            FROM learning_items
            LEFT JOIN learning_item_translations AS translations
              ON translations.learning_item_id = learning_items.id
            LEFT JOIN learning_item_assets AS image_links
              ON image_links.learning_item_id = learning_items.id
             AND image_links.role = ?
            LEFT JOIN assets AS image_assets
              ON image_assets.id = image_links.asset_id
            LEFT JOIN learning_item_assets AS audio_links
              ON audio_links.learning_item_id = learning_items.id
             AND audio_links.role = ?
            LEFT JOIN assets AS audio_assets
              ON audio_assets.id = audio_links.asset_id
            WHERE learning_items.family_id = ?
              {archive_filter}
            GROUP BY
                learning_items.id,
                learning_items.text,
                learning_items.is_archived,
                image_assets.local_path,
                image_assets.source_url,
                audio_assets.local_path,
                audio_assets.source_url
            ORDER BY learning_items.id
            """,
            (
                PRIMARY_IMAGE_ROLE,
                PRIMARY_AUDIO_ROLE,
                family_id,
            ),
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "text": str(row["text"]),
            "is_archived": int(row["is_archived"]),
            "translation_ru": row["translation_ru"],
            "translation_uk": row["translation_uk"],
            "translation_bg": row["translation_bg"],
            "image_ref": row["image_local_path"] or row["image_source_url"],
            "image_source_url": row["image_source_url"],
            "audio_ref": row["audio_local_path"] or row["audio_source_url"],
        }
        for row in rows
    ]


def _load_topic_titles_by_item_id(family_id: int) -> tuple[dict[int, list[str]], int]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                topic_items.learning_item_id,
                topics.title
            FROM topic_items
            JOIN topics
              ON topics.id = topic_items.topic_id
            JOIN learning_items
              ON learning_items.id = topic_items.learning_item_id
            WHERE topics.family_id = ?
              AND learning_items.family_id = ?
            ORDER BY topics.title, topic_items.id
            """,
            (family_id, family_id),
        ).fetchall()
        topic_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM topics
                WHERE family_id = ?
                """,
                (family_id,),
            ).fetchone()[0]
        )
    topic_titles_by_item_id: dict[int, list[str]] = {}
    for row in rows:
        topic_titles_by_item_id.setdefault(int(row["learning_item_id"]), []).append(str(row["title"]))
    return topic_titles_by_item_id, topic_count


def _build_export_image_ref(*, image_ref: str, image_source_url: str, static_base_url: str | None) -> str:
    return (
        _build_public_image_url(image_ref=image_ref, static_base_url=static_base_url)
        or image_source_url.strip()
        or image_ref.strip()
    )


def _build_image_formula(*, image_ref: str, row_number: int) -> str:
    if not image_ref.startswith(("http://", "https://")):
        return ""
    return f"=IMAGE({IMAGE_REF_COLUMN_LETTER}{row_number})"


def _build_public_image_url(*, image_ref: str, static_base_url: str | None) -> str | None:
    if static_base_url is None:
        return None

    normalized_ref = image_ref.strip().replace("\\", "/")
    if not normalized_ref or normalized_ref.startswith(("http://", "https://")):
        return None

    if normalized_ref.startswith("/app/assets/"):
        public_path = normalized_ref.removeprefix("/app/assets/")
    elif normalized_ref.startswith("assets/"):
        public_path = normalized_ref.removeprefix("assets/")
    else:
        return None

    public_path = public_path.strip("/")
    if not public_path:
        return None
    return f"{static_base_url}/{quote(public_path, safe='/')}"
