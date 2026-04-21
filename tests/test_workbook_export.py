import sys
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.topics import create_topic_for_teacher_workspace, link_learning_item_to_topic
from englishbot.vocabulary import (
    create_learning_item_for_teacher_workspace,
    create_learning_item_translation,
    create_lexeme,
)
from englishbot.workbook_export import (
    ASSETS_COLUMNS,
    ASSETS_SHEET_NAME,
    LEARNING_ITEMS_COLUMNS,
    LEARNING_ITEMS_SHEET_NAME,
    LEARNING_ITEM_ASSETS_COLUMNS,
    LEARNING_ITEM_ASSETS_SHEET_NAME,
    SHEET_NAMES,
    TOPIC_ITEMS_COLUMNS,
    TOPIC_ITEMS_SHEET_NAME,
    TOPICS_COLUMNS,
    TOPICS_SHEET_NAME,
    export_teacher_workspace_workbook,
)
from englishbot.workspaces import add_workspace_member, create_workspace


def setup_db(tmp_path: Path) -> tuple[int, int]:
    db.DB_PATH = tmp_path / "workbook_export.sqlite3"
    db.init_db()
    teacher_user_id = 501
    workspace = create_workspace("Authoring", kind="teacher")
    add_workspace_member(workspace["workspace_id"], teacher_user_id, "teacher")
    return teacher_user_id, int(workspace["workspace_id"])


def load_exported_workbook(payload: bytes):
    return load_workbook(filename=BytesIO(payload))


def test_export_uses_asset_registry_sheets(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = setup_db(tmp_path)
    lexeme_id = create_lexeme("run")
    learning_item_id = create_learning_item_for_teacher_workspace(
        teacher_user_id,
        workspace_id,
        lexeme_id,
        "run fast",
        image_ref="assets/images/run-fast.png",
        audio_ref="assets/audio/run-fast.mp3",
    )
    create_learning_item_translation(learning_item_id, "ru", "бежать")
    topic_id = create_topic_for_teacher_workspace(
        teacher_user_id,
        workspace_id,
        "verbs",
        "Verbs",
    )
    link_learning_item_to_topic(topic_id, learning_item_id)

    workbook = load_exported_workbook(
        export_teacher_workspace_workbook(teacher_user_id, workspace_id)
    )

    assert workbook.sheetnames == SHEET_NAMES
    assert tuple(next(workbook[TOPICS_SHEET_NAME].iter_rows(values_only=True))) == tuple(TOPICS_COLUMNS)
    assert tuple(next(workbook[TOPIC_ITEMS_SHEET_NAME].iter_rows(values_only=True))) == tuple(TOPIC_ITEMS_COLUMNS)
    assert tuple(next(workbook[LEARNING_ITEMS_SHEET_NAME].iter_rows(values_only=True))) == tuple(LEARNING_ITEMS_COLUMNS)
    assert tuple(next(workbook[ASSETS_SHEET_NAME].iter_rows(values_only=True))) == tuple(ASSETS_COLUMNS)
    assert tuple(next(workbook[LEARNING_ITEM_ASSETS_SHEET_NAME].iter_rows(values_only=True))) == tuple(
        LEARNING_ITEM_ASSETS_COLUMNS
    )

    learning_item_rows = list(workbook[LEARNING_ITEMS_SHEET_NAME].iter_rows(values_only=True))[1:]
    asset_rows = list(workbook[ASSETS_SHEET_NAME].iter_rows(values_only=True))[1:]
    linked_asset_rows = list(workbook[LEARNING_ITEM_ASSETS_SHEET_NAME].iter_rows(values_only=True))[1:]

    assert len(learning_item_rows) == 1
    assert learning_item_rows[0][1] == "run fast"
    assert learning_item_rows[0][2] == "run"
    assert learning_item_rows[0][3] == "бежать"
    assert learning_item_rows[0][6] == 0
    assert [row[1] for row in asset_rows] == ["image", "audio"]
    assert {row[3] for row in asset_rows} == {
        "assets/images/run-fast.png",
        "assets/audio/run-fast.mp3",
    }
    assert [row[2] for row in linked_asset_rows] == ["primary_image", "primary_audio"]


def test_export_scopes_assets_to_one_workspace(tmp_path: Path) -> None:
    teacher_user_id, first_workspace_id = setup_db(tmp_path)
    second_workspace = create_workspace("Another", kind="teacher")
    add_workspace_member(second_workspace["workspace_id"], teacher_user_id, "teacher")

    first_item = create_learning_item_for_teacher_workspace(
        teacher_user_id,
        first_workspace_id,
        create_lexeme("cat"),
        "cat",
        image_ref="assets/images/cat.png",
    )
    second_item = create_learning_item_for_teacher_workspace(
        teacher_user_id,
        int(second_workspace["workspace_id"]),
        create_lexeme("dog"),
        "dog",
        image_ref="assets/images/dog.png",
    )
    first_topic = create_topic_for_teacher_workspace(teacher_user_id, first_workspace_id, "a", "A")
    second_topic = create_topic_for_teacher_workspace(
        teacher_user_id,
        int(second_workspace["workspace_id"]),
        "b",
        "B",
    )
    link_learning_item_to_topic(first_topic, first_item)
    link_learning_item_to_topic(second_topic, second_item)

    workbook = load_exported_workbook(
        export_teacher_workspace_workbook(teacher_user_id, first_workspace_id)
    )

    learning_item_rows = list(workbook[LEARNING_ITEMS_SHEET_NAME].iter_rows(values_only=True))[1:]
    asset_rows = list(workbook[ASSETS_SHEET_NAME].iter_rows(values_only=True))[1:]

    assert len(learning_item_rows) == 1
    assert learning_item_rows[0][1] == "cat"
    assert len(asset_rows) == 1
    assert asset_rows[0][3] == "assets/images/cat.png"
