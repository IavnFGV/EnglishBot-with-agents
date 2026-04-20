import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.topics import create_topic_for_teacher_workspace, link_learning_item_to_topic
from englishbot.vocabulary import (
    create_learning_item_for_teacher_workspace,
    create_learning_item_translation,
    create_lexeme,
)
from englishbot.workbook_admin import (
    build_export_summary_text,
    build_import_summary_text,
    export_teacher_workspace_workbook_file,
)
from englishbot.workspaces import (
    WorkspaceEditPermissionError,
    add_workspace_member,
    create_workspace,
)


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "workbook_admin.sqlite3"
    db.init_db()


def create_teacher_workspace(tmp_path: Path, teacher_user_id: int = 901) -> tuple[int, int]:
    setup_db(tmp_path)
    workspace = create_workspace("Authoring", kind="teacher")
    add_workspace_member(workspace["workspace_id"], teacher_user_id, "teacher")
    return teacher_user_id, int(workspace["workspace_id"])


def seed_workspace_content(teacher_user_id: int, workspace_id: int) -> None:
    cat_lexeme_id = create_lexeme("cat")
    cat_learning_item_id = create_learning_item_for_teacher_workspace(
        teacher_user_id,
        workspace_id,
        cat_lexeme_id,
        "cat",
    )
    create_learning_item_translation(cat_learning_item_id, "ru", "кот")

    dog_lexeme_id = create_lexeme("dog")
    dog_learning_item_id = create_learning_item_for_teacher_workspace(
        teacher_user_id,
        workspace_id,
        dog_lexeme_id,
        "dog",
    )
    topic_id = create_topic_for_teacher_workspace(
        teacher_user_id,
        workspace_id,
        "animals",
        "Animals",
    )
    link_learning_item_to_topic(topic_id, cat_learning_item_id)
    link_learning_item_to_topic(topic_id, dog_learning_item_id)


def test_export_workbook_file_includes_filename_and_counts(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = create_teacher_workspace(tmp_path)
    seed_workspace_content(teacher_user_id, workspace_id)

    report = export_teacher_workspace_workbook_file(teacher_user_id, workspace_id)

    assert report["workspace_id"] == workspace_id
    assert report["filename"] == f"teacher-workspace-{workspace_id}.xlsx"
    assert bytes(report["workbook_bytes"]).startswith(b"PK")
    assert report["topic_count"] == 1
    assert report["learning_item_count"] == 2
    assert report["topic_link_count"] == 2
    assert (
        build_export_summary_text(report)
        == f"Экспорт workbook для workspace {workspace_id}: topics=1, learning_items=2, topic_links=2."
    )


def test_export_workbook_file_requires_teacher_membership(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = create_teacher_workspace(tmp_path)

    with pytest.raises(WorkspaceEditPermissionError):
        export_teacher_workspace_workbook_file(teacher_user_id + 1, workspace_id)


def test_import_summary_text_is_compact_and_stable() -> None:
    report = {
        "workspace_id": 17,
        "created_topics": 1,
        "updated_topics": 2,
        "created_learning_items": 3,
        "updated_learning_items": 4,
        "added_topic_links": 5,
    }

    assert (
        build_import_summary_text(report)
        == "Импорт workbook выполнен для workspace 17: "
        "created_topics=1, updated_topics=2, created_learning_items=3, "
        "updated_learning_items=4, added_topic_links=5."
    )
