from .db import get_connection
from .i18n import DEFAULT_LANGUAGE_CODE, translate
from .workbook_export import export_teacher_workspace_workbook
from .workbook_import import import_teacher_workspace_workbook


def export_teacher_workspace_workbook_file(
    teacher_user_id: int,
    workspace_id: int,
) -> dict[str, object]:
    workbook_bytes = export_teacher_workspace_workbook(teacher_user_id, workspace_id)
    counts = _get_workspace_content_counts(workspace_id)
    return {
        "workspace_id": workspace_id,
        "filename": build_workbook_filename(workspace_id),
        "workbook_bytes": workbook_bytes,
        **counts,
    }


def import_teacher_workspace_workbook_file(
    teacher_user_id: int,
    workspace_id: int,
    workbook_bytes: bytes,
) -> dict[str, int]:
    result = import_teacher_workspace_workbook(
        teacher_user_id,
        workspace_id,
        workbook_bytes,
    )
    return {
        "workspace_id": workspace_id,
        **result,
    }


def build_workbook_filename(workspace_id: int) -> str:
    return f"teacher-workspace-{workspace_id}.xlsx"


def build_export_summary_text(
    report: dict[str, object],
    language_code: str = DEFAULT_LANGUAGE_CODE,
) -> str:
    return translate(
        "workbook.export.summary",
        language_code,
        workspace_id=report["workspace_id"],
        topic_count=report["topic_count"],
        learning_item_count=report["learning_item_count"],
        topic_link_count=report["topic_link_count"],
    )


def build_import_summary_text(
    report: dict[str, int],
    language_code: str = DEFAULT_LANGUAGE_CODE,
) -> str:
    return translate(
        "workbook.import.summary",
        language_code,
        workspace_id=report["workspace_id"],
        created_topics=report["created_topics"],
        updated_topics=report["updated_topics"],
        created_learning_items=report["created_learning_items"],
        updated_learning_items=report["updated_learning_items"],
        added_topic_links=report["added_topic_links"],
    )


def _get_workspace_content_counts(workspace_id: int) -> dict[str, int]:
    with get_connection() as connection:
        topic_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM topics
                WHERE workspace_id = ?
                """,
                (workspace_id,),
            ).fetchone()[0]
        )
        learning_item_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM learning_items
                WHERE workspace_id = ?
                """,
                (workspace_id,),
            ).fetchone()[0]
        )
        topic_link_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM topic_learning_items
                JOIN topics
                  ON topics.id = topic_learning_items.topic_id
                JOIN learning_items
                  ON learning_items.id = topic_learning_items.learning_item_id
                WHERE topics.workspace_id = ?
                  AND learning_items.workspace_id = ?
                """,
                (workspace_id, workspace_id),
            ).fetchone()[0]
        )
    return {
        "topic_count": topic_count,
        "learning_item_count": learning_item_count,
        "topic_link_count": topic_link_count,
    }
