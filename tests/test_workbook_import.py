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
    LEARNING_ITEMS_COLUMNS,
    LEARNING_ITEMS_SHEET_NAME,
    TOPIC_ITEMS_COLUMNS,
    TOPIC_ITEMS_SHEET_NAME,
    TOPICS_COLUMNS,
    TOPICS_SHEET_NAME,
)
from englishbot.workbook_import import (
    WorkbookImportError,
    import_teacher_workspace_workbook,
)
from englishbot.workspaces import (
    WorkspaceKindMismatchError,
    add_workspace_member,
    create_workspace,
)


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "workbook_import.sqlite3"
    db.init_db()


def create_teacher_workspace(tmp_path: Path, teacher_user_id: int = 501) -> tuple[int, int]:
    setup_db(tmp_path)
    workspace = create_workspace("Authoring", kind="teacher")
    add_workspace_member(workspace["workspace_id"], teacher_user_id, "teacher")
    return teacher_user_id, int(workspace["workspace_id"])


def build_workbook_bytes(
    *,
    topics: list[tuple[object, ...]],
    topic_items: list[tuple[object, ...]],
    learning_items: list[tuple[object, ...]],
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

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def get_lemma_for_learning_item(learning_item_id: int) -> str:
    with db.get_connection() as connection:
        row = connection.execute(
            """
            SELECT lexemes.lemma
            FROM learning_items
            JOIN lexemes
              ON lexemes.id = learning_items.lexeme_id
            WHERE learning_items.id = ?
            """,
            (learning_item_id,),
        ).fetchone()
    assert row is not None
    return str(row["lemma"])


def test_import_upserts_topics_learning_items_and_links(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = create_teacher_workspace(tmp_path)

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
    create_learning_item_translation(existing_learning_item_id, "uk", "старий")

    shared_learning_item_id = create_learning_item(
        original_lexeme_id,
        "shared cat",
        workspace_id=workspace_id,
        workbook_key="item-shared",
    )
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
            VALUES (?, ?), (?, ?)
            """,
            (
                existing_topic_id,
                existing_learning_item_id,
                existing_topic_id,
                shared_learning_item_id,
            ),
        )

    workbook_bytes = build_workbook_bytes(
        topics=[
            ("topic-existing", "animals", "Animals Updated", 1, existing_topic_id),
            ("topic-new", "verbs", "Verbs", 0, None),
        ],
        topic_items=[
            ("topic-existing", "item-existing", existing_topic_id, existing_learning_item_id),
            ("topic-existing", "item-new", existing_topic_id, None),
            ("topic-new", "item-new", None, None),
        ],
        learning_items=[
            (
                "item-existing",
                "updated text",
                "kitten",
                "новый",
                "",
                "коте-bg",
                "new-image.png",
                "=IMAGE(\"should-be-ignored.png\")",
                "new-audio.mp3",
                1,
                existing_learning_item_id,
                None,
            ),
            (
                "item-new",
                "jump",
                "jump",
                "прыгать",
                "стрибати",
                None,
                "jump.png",
                "=IMAGE(\"ignored-too.png\")",
                None,
                0,
                None,
                None,
            ),
        ],
    )

    result = import_teacher_workspace_workbook(teacher_user_id, workspace_id, workbook_bytes)

    updated_topic = get_topic(existing_topic_id, include_archived=True)
    with db.get_connection() as connection:
        new_topics = [
            row
            for row in connection.execute(
                """
                SELECT id, workbook_key, name, title, is_archived
                FROM topics
                WHERE workspace_id = ?
                ORDER BY id
                """,
                (workspace_id,),
            ).fetchall()
            if row["workbook_key"] == "topic-new"
        ]
        created_learning_items = [
            row
            for row in connection.execute(
                """
                SELECT id, workbook_key
                FROM learning_items
                WHERE workspace_id = ?
                ORDER BY id
                """,
                (workspace_id,),
            ).fetchall()
            if row["workbook_key"] == "item-new"
        ]

    updated_learning_item = get_learning_item(existing_learning_item_id)

    assert result == {
        "created_topics": 1,
        "updated_topics": 1,
        "created_learning_items": 1,
        "updated_learning_items": 1,
        "added_topic_links": 2,
    }
    assert updated_topic is not None
    assert updated_topic["name"] == "animals"
    assert updated_topic["title"] == "Animals Updated"
    assert updated_topic["is_archived"] == 1
    assert len(new_topics) == 1

    assert updated_learning_item is not None
    assert updated_learning_item["text"] == "updated text"
    assert updated_learning_item["image_ref"] == "new-image.png"
    assert updated_learning_item["audio_ref"] == "new-audio.mp3"
    assert updated_learning_item["is_archived"] == 1
    assert get_lemma_for_learning_item(existing_learning_item_id) == "kitten"
    assert get_lemma_for_learning_item(shared_learning_item_id) == "cat"

    translations = {
        row["language_code"]: row["translation_text"]
        for row in list_learning_item_translations(existing_learning_item_id)
    }
    assert translations["ru"] == "новый"
    assert translations["uk"] == "старий"
    assert translations["bg"] == "коте-bg"

    assert len(created_learning_items) == 1
    created_learning_item_id = int(created_learning_items[0]["id"])
    assert set(get_topic_learning_item_ids(existing_topic_id, include_archived=True)) == {
        existing_learning_item_id,
        shared_learning_item_id,
        created_learning_item_id,
    }
    new_topic = get_topic(int(new_topics[0]["id"]), include_archived=True)
    assert new_topic is not None
    assert get_topic_learning_item_ids(int(new_topic["id"]), include_archived=True) == [
        created_learning_item_id
    ]


def test_import_fails_fast_on_broken_topic_item_reference(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = create_teacher_workspace(tmp_path)

    workbook_bytes = build_workbook_bytes(
        topics=[("topic-existing", "animals", "Animals", 0, None)],
        topic_items=[("topic-existing", "item-missing", None, None)],
        learning_items=[
            (
                "item-existing",
                "cat",
                "cat",
                None,
                None,
                None,
                None,
                None,
                None,
                0,
                None,
                None,
            )
        ],
    )

    with pytest.raises(WorkbookImportError):
        import_teacher_workspace_workbook(teacher_user_id, workspace_id, workbook_bytes)

    assert get_topic(1, include_archived=True) is None
    assert get_learning_item(1) is None


def test_import_rolls_back_all_changes_on_late_failure(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = create_teacher_workspace(tmp_path)
    lexeme_id = create_lexeme("cat")
    existing_learning_item_id = create_learning_item(
        lexeme_id,
        "before import",
        workspace_id=workspace_id,
        workbook_key="item-existing",
    )
    create_topic("conflict-name", "Existing", workspace_id=workspace_id, workbook_key="topic-conflict")

    workbook_bytes = build_workbook_bytes(
        topics=[("topic-new", "conflict-name", "Will Conflict", 0, None)],
        topic_items=[],
        learning_items=[
            (
                "item-existing",
                "after import",
                "kitten",
                "котёнок",
                None,
                None,
                None,
                "=IMAGE(\"ignored.png\")",
                None,
                0,
                existing_learning_item_id,
                None,
            )
        ],
    )

    with pytest.raises(sqlite3.IntegrityError):
        import_teacher_workspace_workbook(teacher_user_id, workspace_id, workbook_bytes)

    persisted_learning_item = get_learning_item(existing_learning_item_id)
    assert persisted_learning_item is not None
    assert persisted_learning_item["text"] == "before import"
    assert get_lemma_for_learning_item(existing_learning_item_id) == "cat"
    with db.get_connection() as connection:
        count = connection.execute(
            """
            SELECT COUNT(*)
            FROM topics
            WHERE workspace_id = ? AND workbook_key = 'topic-new'
            """,
            (workspace_id,),
        ).fetchone()[0]
    assert count == 0


def test_import_rejects_duplicate_workbook_keys(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = create_teacher_workspace(tmp_path)

    workbook_bytes = build_workbook_bytes(
        topics=[
            ("topic-dup", "animals", "Animals", 0, None),
            ("topic-dup", "verbs", "Verbs", 0, None),
        ],
        topic_items=[],
        learning_items=[],
    )

    with pytest.raises(WorkbookImportError):
        import_teacher_workspace_workbook(teacher_user_id, workspace_id, workbook_bytes)


def test_import_rejects_invalid_archive_values(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = create_teacher_workspace(tmp_path)

    workbook_bytes = build_workbook_bytes(
        topics=[("topic-existing", "animals", "Animals", "maybe", None)],
        topic_items=[],
        learning_items=[],
    )

    with pytest.raises(WorkbookImportError):
        import_teacher_workspace_workbook(teacher_user_id, workspace_id, workbook_bytes)


def test_import_rejects_student_workspace_targets(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher_user_id = 777
    workspace = create_workspace("Student Runtime", kind="student")
    add_workspace_member(workspace["workspace_id"], teacher_user_id, "teacher")
    workbook_bytes = build_workbook_bytes(topics=[], topic_items=[], learning_items=[])

    with pytest.raises(WorkspaceKindMismatchError):
        import_teacher_workspace_workbook(
            teacher_user_id,
            int(workspace["workspace_id"]),
            workbook_bytes,
        )
