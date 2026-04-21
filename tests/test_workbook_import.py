import sqlite3
import sys
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.topics import create_topic, get_topic, get_topic_learning_item_ids
from englishbot.vocabulary import (
    create_learning_item,
    create_learning_item_translation,
    create_lexeme,
    get_learning_item,
    list_learning_item_translations,
)
from englishbot.workbook_export import (
    ASSETS_COLUMNS,
    ASSETS_SHEET_NAME,
    LEARNING_ITEMS_COLUMNS,
    LEARNING_ITEMS_SHEET_NAME,
    LEARNING_ITEM_ASSETS_COLUMNS,
    LEARNING_ITEM_ASSETS_SHEET_NAME,
    TOPIC_ITEMS_COLUMNS,
    TOPIC_ITEMS_SHEET_NAME,
    TOPICS_COLUMNS,
    TOPICS_SHEET_NAME,
)
from englishbot.workbook_import import WorkbookImportError, import_teacher_workspace_workbook
from englishbot.workspaces import WorkspaceKindMismatchError, add_workspace_member, create_workspace


def setup_db(tmp_path: Path) -> tuple[int, int]:
    db.DB_PATH = tmp_path / "workbook_import.sqlite3"
    db.init_db()
    teacher_user_id = 501
    workspace = create_workspace("Authoring", kind="teacher")
    add_workspace_member(workspace["workspace_id"], teacher_user_id, "teacher")
    return teacher_user_id, int(workspace["workspace_id"])


def build_workbook_bytes(
    *,
    topics: list[tuple[object, ...]],
    topic_items: list[tuple[object, ...]],
    learning_items: list[tuple[object, ...]],
    assets: list[tuple[object, ...]],
    learning_item_assets: list[tuple[object, ...]],
) -> bytes:
    workbook = Workbook()
    topics_sheet = workbook.active
    topics_sheet.title = TOPICS_SHEET_NAME
    topics_sheet.append(TOPICS_COLUMNS)
    for row in topics:
        topics_sheet.append(list(row))

    topic_items_sheet = workbook.create_sheet(TOPIC_ITEMS_SHEET_NAME)
    topic_items_sheet.append(TOPIC_ITEMS_COLUMNS)
    for row in topic_items:
        topic_items_sheet.append(list(row))

    learning_items_sheet = workbook.create_sheet(LEARNING_ITEMS_SHEET_NAME)
    learning_items_sheet.append(LEARNING_ITEMS_COLUMNS)
    for row in learning_items:
        learning_items_sheet.append(list(row))

    assets_sheet = workbook.create_sheet(ASSETS_SHEET_NAME)
    assets_sheet.append(ASSETS_COLUMNS)
    for row in assets:
        assets_sheet.append(list(row))

    links_sheet = workbook.create_sheet(LEARNING_ITEM_ASSETS_SHEET_NAME)
    links_sheet.append(LEARNING_ITEM_ASSETS_COLUMNS)
    for row in learning_item_assets:
        links_sheet.append(list(row))

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_import_upserts_learning_items_and_assets(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = setup_db(tmp_path)
    original_lexeme_id = create_lexeme("cat")
    existing_learning_item_id = create_learning_item(
        original_lexeme_id,
        "old text",
        workspace_id=workspace_id,
        workbook_key="item-existing",
        image_ref="old-image.png",
        audio_ref="old-audio.mp3",
    )
    create_learning_item_translation(existing_learning_item_id, "ru", "старый")

    existing_topic_id = create_topic(
        "old-topic-name",
        "Old Topic",
        workspace_id=workspace_id,
        workbook_key="topic-existing",
    )
    with db.get_connection() as connection:
        connection.execute(
            """
            INSERT INTO topic_learning_items (topic_id, learning_item_id)
            VALUES (?, ?)
            """,
            (existing_topic_id, existing_learning_item_id),
        )

    workbook_bytes = build_workbook_bytes(
        topics=[
            ("topic-existing", "animals", "Animals Updated", 1, existing_topic_id),
            ("topic-new", "verbs", "Verbs", 0, None),
        ],
        topic_items=[
            ("topic-existing", "item-existing", existing_topic_id, existing_learning_item_id),
            ("topic-new", "item-new", None, None),
        ],
        learning_items=[
            ("item-existing", "updated text", "kitten", "новый", None, None, 1, existing_learning_item_id, None),
            ("item-new", "jump", "jump", "прыгать", "стрибати", None, 0, None, None),
        ],
        assets=[
            ("asset-existing-image", "image", None, "new-image.png", None),
            ("asset-existing-audio", "audio", None, "new-audio.mp3", None),
            ("asset-new-image", "image", None, "jump.png", None),
        ],
        learning_item_assets=[
            ("item-existing", "asset-existing-image", "primary_image", 0, existing_learning_item_id, None),
            ("item-existing", "asset-existing-audio", "primary_audio", 1, existing_learning_item_id, None),
            ("item-new", "asset-new-image", "primary_image", 0, None, None),
        ],
    )

    result = import_teacher_workspace_workbook(teacher_user_id, workspace_id, workbook_bytes)
    updated_item = get_learning_item(existing_learning_item_id)

    assert result == {
        "created_topics": 1,
        "updated_topics": 1,
        "created_learning_items": 1,
        "updated_learning_items": 1,
        "created_assets": 3,
        "updated_assets": 0,
        "added_topic_links": 1,
    }
    assert updated_item is not None
    assert updated_item["text"] == "updated text"
    assert updated_item["image_ref"] == "new-image.png"
    assert updated_item["audio_ref"] == "new-audio.mp3"
    assert updated_item["is_archived"] == 1
    assert get_topic(existing_topic_id, include_archived=True)["title"] == "Animals Updated"
    assert any(row["translation_text"] == "новый" for row in list_learning_item_translations(existing_learning_item_id))
    assert len(get_topic_learning_item_ids(existing_topic_id, include_archived=True)) == 1


def test_import_rejects_missing_asset_references(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = setup_db(tmp_path)

    workbook_bytes = build_workbook_bytes(
        topics=[],
        topic_items=[],
        learning_items=[("item-a", "cat", "cat", None, None, None, 0, None, None)],
        assets=[],
        learning_item_assets=[("item-a", "asset-missing", "primary_image", 0, None, None)],
    )

    with pytest.raises(WorkbookImportError):
        import_teacher_workspace_workbook(teacher_user_id, workspace_id, workbook_bytes)


def test_import_rolls_back_on_topic_conflict(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = setup_db(tmp_path)
    existing_learning_item_id = create_learning_item(
        create_lexeme("cat"),
        "before import",
        workspace_id=workspace_id,
        workbook_key="item-existing",
    )
    create_topic("conflict-name", "Existing", workspace_id=workspace_id, workbook_key="topic-conflict")

    workbook_bytes = build_workbook_bytes(
        topics=[("topic-new", "conflict-name", "Will Conflict", 0, None)],
        topic_items=[],
        learning_items=[("item-existing", "after import", "kitten", "котёнок", None, None, 0, existing_learning_item_id, None)],
        assets=[],
        learning_item_assets=[],
    )

    with pytest.raises(sqlite3.IntegrityError):
        import_teacher_workspace_workbook(teacher_user_id, workspace_id, workbook_bytes)

    assert get_learning_item(existing_learning_item_id)["text"] == "before import"


def test_import_rejects_student_workspace_targets(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "workbook_import_student.sqlite3"
    db.init_db()
    teacher_user_id = 777
    workspace = create_workspace("Student Runtime", kind="student")
    add_workspace_member(workspace["workspace_id"], teacher_user_id, "teacher")
    workbook_bytes = build_workbook_bytes(
        topics=[],
        topic_items=[],
        learning_items=[],
        assets=[],
        learning_item_assets=[],
    )

    with pytest.raises(WorkspaceKindMismatchError):
        import_teacher_workspace_workbook(teacher_user_id, int(workspace["workspace_id"]), workbook_bytes)
