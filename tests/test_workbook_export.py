import sys
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.topics import (
    archive_topic,
    create_topic_for_teacher_workspace,
    link_learning_item_to_topic,
    publish_topic_to_workspace,
)
from englishbot.vocabulary import (
    archive_learning_item,
    create_learning_item_for_teacher_workspace,
    create_learning_item_translation,
    create_lexeme,
    get_learning_item,
)
from englishbot.workbook_export import (
    LEARNING_ITEMS_COLUMNS,
    LEARNING_ITEMS_SHEET_NAME,
    SHEET_NAMES,
    TOPIC_ITEMS_COLUMNS,
    TOPIC_ITEMS_SHEET_NAME,
    TOPICS_COLUMNS,
    TOPICS_SHEET_NAME,
    export_teacher_workspace_workbook,
)
from englishbot.workspaces import (
    WorkspaceKindMismatchError,
    add_workspace_member,
    create_workspace,
)


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "workbook_export.sqlite3"
    db.init_db()


def load_exported_workbook(payload: bytes):
    return load_workbook(filename=BytesIO(payload))


def sheet_rows(sheet) -> list[tuple[object, ...]]:
    return list(sheet.iter_rows(values_only=True))


def header(sheet) -> tuple[object, ...]:
    return sheet_rows(sheet)[0]


def body_rows(sheet) -> list[tuple[object, ...]]:
    return sheet_rows(sheet)[1:]


def create_teacher_workspace(tmp_path: Path, teacher_user_id: int = 501) -> tuple[int, int]:
    setup_db(tmp_path)
    workspace = create_workspace("Authoring", kind="teacher")
    add_workspace_member(workspace["workspace_id"], teacher_user_id, "teacher")
    return teacher_user_id, int(workspace["workspace_id"])


def seed_learning_item(
    teacher_user_id: int,
    workspace_id: int,
    lemma: str,
    *,
    text: str | None = None,
    image_ref: str | None = None,
    audio_ref: str | None = None,
    translations: dict[str, str] | None = None,
) -> int:
    lexeme_id = create_lexeme(lemma)
    learning_item_id = create_learning_item_for_teacher_workspace(
        teacher_user_id,
        workspace_id,
        lexeme_id,
        text or lemma,
        image_ref=image_ref,
        audio_ref=audio_ref,
    )
    for language_code, translation_text in (translations or {}).items():
        create_learning_item_translation(learning_item_id, language_code, translation_text)
    return learning_item_id


def test_export_creates_valid_xlsx(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = create_teacher_workspace(tmp_path)
    seed_learning_item(teacher_user_id, workspace_id, "cat", translations={"ru": "кот"})

    payload = export_teacher_workspace_workbook(teacher_user_id, workspace_id)
    workbook = load_exported_workbook(payload)

    assert payload.startswith(b"PK")
    assert workbook.sheetnames == SHEET_NAMES


def test_export_has_exact_sheet_names(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = create_teacher_workspace(tmp_path)

    workbook = load_exported_workbook(
        export_teacher_workspace_workbook(teacher_user_id, workspace_id)
    )

    assert workbook.sheetnames == SHEET_NAMES


def test_export_uses_deterministic_columns(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = create_teacher_workspace(tmp_path)

    workbook = load_exported_workbook(
        export_teacher_workspace_workbook(teacher_user_id, workspace_id)
    )

    assert header(workbook[TOPICS_SHEET_NAME]) == tuple(TOPICS_COLUMNS)
    assert header(workbook[TOPIC_ITEMS_SHEET_NAME]) == tuple(TOPIC_ITEMS_COLUMNS)
    assert header(workbook[LEARNING_ITEMS_SHEET_NAME]) == tuple(LEARNING_ITEMS_COLUMNS)


def test_export_uses_workbook_keys_as_primary_identity(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = create_teacher_workspace(tmp_path)
    learning_item_id = seed_learning_item(teacher_user_id, workspace_id, "cat")
    topic_id = create_topic_for_teacher_workspace(
        teacher_user_id,
        workspace_id,
        "animals",
        "Animals",
    )
    link_learning_item_to_topic(topic_id, learning_item_id)

    workbook = load_exported_workbook(
        export_teacher_workspace_workbook(teacher_user_id, workspace_id)
    )
    with db.get_connection() as connection:
        topic = connection.execute(
            "SELECT workbook_key FROM topics WHERE id = ?",
            (topic_id,),
        ).fetchone()
    learning_item = get_learning_item(learning_item_id)

    topic_row = body_rows(workbook[TOPICS_SHEET_NAME])[0]
    topic_item_row = body_rows(workbook[TOPIC_ITEMS_SHEET_NAME])[0]
    learning_item_row = body_rows(workbook[LEARNING_ITEMS_SHEET_NAME])[0]

    assert topic is not None
    assert learning_item is not None
    assert topic_row[0] == topic["workbook_key"]
    assert topic_item_row[0] == topic["workbook_key"]
    assert topic_item_row[1] == learning_item["workbook_key"]
    assert learning_item_row[0] == learning_item["workbook_key"]


def test_export_maps_translations_to_wide_columns(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = create_teacher_workspace(tmp_path)
    seed_learning_item(
        teacher_user_id,
        workspace_id,
        "book",
        translations={
            "ru": "книга",
            "uk": "книга-uk",
            "bg": "книга-bg",
            "de": "Buch",
        },
    )
    seed_learning_item(
        teacher_user_id,
        workspace_id,
        "tree",
        translations={"ru": "дерево"},
    )

    workbook = load_exported_workbook(
        export_teacher_workspace_workbook(teacher_user_id, workspace_id)
    )
    rows = body_rows(workbook[LEARNING_ITEMS_SHEET_NAME])

    assert rows[0][3:6] == ("книга", "книга-uk", "книга-bg")
    assert rows[1][3] == "дерево"
    assert rows[1][4] is None
    assert rows[1][5] is None


def test_export_includes_archive_and_asset_fields(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = create_teacher_workspace(tmp_path)
    learning_item_id = seed_learning_item(
        teacher_user_id,
        workspace_id,
        "run",
        text="run fast",
        image_ref="assets/images/run-fast.png",
        audio_ref="assets/audio/run-fast.mp3",
    )
    topic_id = create_topic_for_teacher_workspace(
        teacher_user_id,
        workspace_id,
        "verbs",
        "Verbs",
    )
    link_learning_item_to_topic(topic_id, learning_item_id)
    archive_topic(teacher_user_id, topic_id)
    archive_learning_item(teacher_user_id, learning_item_id)

    workbook = load_exported_workbook(
        export_teacher_workspace_workbook(teacher_user_id, workspace_id)
    )
    topic_row = body_rows(workbook[TOPICS_SHEET_NAME])[0]
    learning_item_row = body_rows(workbook[LEARNING_ITEMS_SHEET_NAME])[0]

    assert topic_row[3] == 1
    assert learning_item_row[6] == "assets/images/run-fast.png"
    assert learning_item_row[7] == '=IMAGE("assets/images/run-fast.png")'
    assert learning_item_row[8] == "assets/audio/run-fast.mp3"
    assert learning_item_row[9] == 1


def test_export_leaves_display_image_blank_without_image_ref(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = create_teacher_workspace(tmp_path)
    seed_learning_item(
        teacher_user_id,
        workspace_id,
        "tree",
        audio_ref="assets/audio/tree.mp3",
    )

    workbook = load_exported_workbook(
        export_teacher_workspace_workbook(teacher_user_id, workspace_id)
    )
    learning_item_row = body_rows(workbook[LEARNING_ITEMS_SHEET_NAME])[0]

    assert learning_item_row[6] is None
    assert learning_item_row[7] is None
    assert learning_item_row[8] == "assets/audio/tree.mp3"


def test_export_is_scoped_to_one_teacher_workspace(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher_user_id = 601
    first_workspace = create_workspace("Authoring A", kind="teacher")
    second_workspace = create_workspace("Authoring B", kind="teacher")
    add_workspace_member(first_workspace["workspace_id"], teacher_user_id, "teacher")
    add_workspace_member(second_workspace["workspace_id"], teacher_user_id, "teacher")
    first_item_id = seed_learning_item(teacher_user_id, first_workspace["workspace_id"], "cat")
    second_item_id = seed_learning_item(teacher_user_id, second_workspace["workspace_id"], "dog")
    first_topic_id = create_topic_for_teacher_workspace(
        teacher_user_id,
        first_workspace["workspace_id"],
        "shared",
        "First",
    )
    second_topic_id = create_topic_for_teacher_workspace(
        teacher_user_id,
        second_workspace["workspace_id"],
        "shared",
        "Second",
    )
    link_learning_item_to_topic(first_topic_id, first_item_id)
    link_learning_item_to_topic(second_topic_id, second_item_id)

    workbook = load_exported_workbook(
        export_teacher_workspace_workbook(teacher_user_id, first_workspace["workspace_id"])
    )

    assert len(body_rows(workbook[TOPICS_SHEET_NAME])) == 1
    assert len(body_rows(workbook[TOPIC_ITEMS_SHEET_NAME])) == 1
    assert len(body_rows(workbook[LEARNING_ITEMS_SHEET_NAME])) == 1
    assert body_rows(workbook[TOPICS_SHEET_NAME])[0][2] == "First"
    assert body_rows(workbook[LEARNING_ITEMS_SHEET_NAME])[0][1] == "cat"


def test_export_excludes_student_workspace_runtime_data(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher_user_id = 701
    teacher_workspace = create_workspace("Authoring", kind="teacher")
    student_workspace = create_workspace("Runtime", kind="student")
    add_workspace_member(teacher_workspace["workspace_id"], teacher_user_id, "teacher")
    add_workspace_member(student_workspace["workspace_id"], teacher_user_id, "teacher")

    teacher_item_id = seed_learning_item(
        teacher_user_id,
        teacher_workspace["workspace_id"],
        "cat",
        translations={"ru": "кот"},
    )
    teacher_topic_id = create_topic_for_teacher_workspace(
        teacher_user_id,
        teacher_workspace["workspace_id"],
        "animals",
        "Animals",
    )
    link_learning_item_to_topic(teacher_topic_id, teacher_item_id)

    publish_result = publish_topic_to_workspace(
        teacher_topic_id,
        student_workspace["workspace_id"],
    )
    with pytest.raises(WorkspaceKindMismatchError):
        export_teacher_workspace_workbook(teacher_user_id, student_workspace["workspace_id"])

    workbook = load_exported_workbook(
        export_teacher_workspace_workbook(teacher_user_id, teacher_workspace["workspace_id"])
    )
    teacher_learning_item = get_learning_item(teacher_item_id)
    published_learning_item = get_learning_item(int(publish_result["learning_item_ids"][0]))

    with db.get_connection() as connection:
        teacher_topic = connection.execute(
            "SELECT workbook_key FROM topics WHERE id = ?",
            (teacher_topic_id,),
        ).fetchone()
        published_topic = connection.execute(
            "SELECT workbook_key FROM topics WHERE id = ?",
            (int(publish_result["topic_id"]),),
        ).fetchone()

    assert len(body_rows(workbook[TOPICS_SHEET_NAME])) == 1
    assert len(body_rows(workbook[TOPIC_ITEMS_SHEET_NAME])) == 1
    assert len(body_rows(workbook[LEARNING_ITEMS_SHEET_NAME])) == 1
    assert body_rows(workbook[LEARNING_ITEMS_SHEET_NAME])[0][1] == "cat"
    assert teacher_topic is not None
    assert published_topic is not None
    assert teacher_learning_item is not None
    assert published_learning_item is not None
    assert body_rows(workbook[TOPICS_SHEET_NAME])[0][0] == teacher_topic["workbook_key"]
    assert body_rows(workbook[LEARNING_ITEMS_SHEET_NAME])[0][0] == teacher_learning_item["workbook_key"]
    assert teacher_topic["workbook_key"] != published_topic["workbook_key"]
    assert teacher_learning_item["workbook_key"] != published_learning_item["workbook_key"]
