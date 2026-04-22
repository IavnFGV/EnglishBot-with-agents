import sys
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.assets import IMAGE_PREVIEW_ROLE, create_asset, link_asset_to_learning_item
from englishbot.topics import create_topic_for_teacher_workspace, link_learning_item_to_topic
from englishbot.vocabulary import (
    create_learning_item_for_teacher_workspace,
    create_learning_item_translation,
    create_lexeme,
)
from englishbot.workbook_export import (
    LEARNING_ITEMS_COLUMNS,
    LEARNING_ITEMS_SHEET_NAME,
    META_COLUMNS,
    META_SHEET_NAME,
    SHEET_NAMES,
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


def test_export_uses_canonical_two_sheet_workbook(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = setup_db(tmp_path)
    learning_item_id = create_learning_item_for_teacher_workspace(
        teacher_user_id,
        workspace_id,
        create_lexeme("run"),
        "run fast",
        image_ref="https://example.com/run-fast.png",
    )
    create_learning_item_translation(learning_item_id, "ru", "бежать")
    create_learning_item_translation(learning_item_id, "uk", "бігти")
    image_preview_asset_id = create_asset("image", local_path="assets/images/run-preview.png")
    link_asset_to_learning_item(learning_item_id, image_preview_asset_id, IMAGE_PREVIEW_ROLE)
    audio_asset_id = create_asset(
        "audio",
        source_url="https://example.com/run-fast.mp3",
        local_path="assets/audio/run-fast.mp3",
    )
    link_asset_to_learning_item(learning_item_id, audio_asset_id, "alloy")
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
    assert tuple(next(workbook[META_SHEET_NAME].iter_rows(values_only=True))) == tuple(META_COLUMNS)
    assert tuple(next(workbook[LEARNING_ITEMS_SHEET_NAME].iter_rows(values_only=True))) == tuple(
        LEARNING_ITEMS_COLUMNS
    )

    meta_rows = list(workbook[META_SHEET_NAME].iter_rows(values_only=True))[1:]
    learning_rows = list(workbook[LEARNING_ITEMS_SHEET_NAME].iter_rows(values_only=True))[1:]

    assert meta_rows == [("2", "Authoring", "ru")]
    assert learning_rows == [
        (
            "run fast",
            "бежать\n<uk>: бігти",
            None,
            "verbs",
            "https://example.com/run-fast.png",
            "assets/images/run-preview.png",
            "https://example.com/run-fast.mp3",
            "alloy",
            0,
        )
    ]


def test_export_duplicates_row_per_topic_and_removes_legacy_sheet_assumptions(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = setup_db(tmp_path)
    learning_item_id = create_learning_item_for_teacher_workspace(
        teacher_user_id,
        workspace_id,
        create_lexeme("cat"),
        "cat",
    )
    first_topic_id = create_topic_for_teacher_workspace(teacher_user_id, workspace_id, "animals", "Animals")
    second_topic_id = create_topic_for_teacher_workspace(teacher_user_id, workspace_id, "pets", "Pets")
    link_learning_item_to_topic(first_topic_id, learning_item_id)
    link_learning_item_to_topic(second_topic_id, learning_item_id)

    workbook = load_exported_workbook(
        export_teacher_workspace_workbook(teacher_user_id, workspace_id)
    )

    assert "topics" not in workbook.sheetnames
    rows = list(workbook[LEARNING_ITEMS_SHEET_NAME].iter_rows(values_only=True))[1:]
    assert [row[3] for row in rows] == ["animals", "pets"]
