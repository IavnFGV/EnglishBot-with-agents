import sys
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.assets import PRIMARY_IMAGE_ROLE, get_learning_item_asset
from englishbot.topics import create_topic, get_topic
from englishbot.vocabulary import (
    create_learning_item,
    create_learning_item_translation,
    create_lexeme,
    get_learning_item,
    list_learning_item_translations,
)
from englishbot.workbook_export import LEARNING_ITEMS_COLUMNS, LEARNING_ITEMS_SHEET_NAME, META_COLUMNS, META_SHEET_NAME
from englishbot.workbook_import import (
    WorkbookImportError,
    _begin_import_transaction,
    import_teacher_workspace_workbook,
)
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
    meta_rows: list[tuple[object, ...]] | None = None,
    learning_item_rows: list[tuple[object, ...]] | None = None,
    sheet_names: list[str] | None = None,
) -> bytes:
    workbook = Workbook()
    desired_sheet_names = sheet_names or [META_SHEET_NAME, LEARNING_ITEMS_SHEET_NAME]
    first_sheet = workbook.active
    first_sheet.title = desired_sheet_names[0]
    first_sheet.append(META_COLUMNS)
    for row in meta_rows or [("2", "Authoring", "ru")]:
        first_sheet.append(list(row))

    for sheet_name in desired_sheet_names[1:]:
        sheet = workbook.create_sheet(sheet_name)
        if sheet_name == LEARNING_ITEMS_SHEET_NAME:
            sheet.append(LEARNING_ITEMS_COLUMNS)
            for row in learning_item_rows or []:
                sheet.append(list(row))
        else:
            sheet.append(["legacy"])

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def install_media_download_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "englishbot.workbook_import.store_remote_asset",
        lambda asset_type, source_url, **kwargs: f"assets/workbook-import/{asset_type}/{asset_type}-stub.bin",
    )


def test_import_parses_translations_default_language_and_media_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    teacher_user_id, workspace_id = setup_db(tmp_path)
    install_media_download_stub(monkeypatch)

    workbook_bytes = build_workbook_bytes(
        learning_item_rows=[
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
    )

    result = import_teacher_workspace_workbook(teacher_user_id, workspace_id, workbook_bytes)
    with db.get_connection() as connection:
        learning_item_row = connection.execute(
            """
            SELECT learning_items.id
            FROM learning_items
            JOIN topic_learning_items
              ON topic_learning_items.learning_item_id = learning_items.id
            JOIN topics
              ON topics.id = topic_learning_items.topic_id
            WHERE learning_items.workspace_id = ?
              AND topics.name = 'verbs'
            ORDER BY learning_items.id
            LIMIT 1
            """,
            (workspace_id,),
        ).fetchone()
    assert learning_item_row is not None
    learning_item = get_learning_item(int(learning_item_row["id"]))

    assert result == {
        "created_topics": 1,
        "updated_topics": 0,
        "created_learning_items": 1,
        "updated_learning_items": 0,
        "added_topic_links": 1,
    }
    assert learning_item is not None
    assert learning_item["text"] == "run fast"
    primary_image = get_learning_item_asset(int(learning_item["id"]), role=PRIMARY_IMAGE_ROLE)
    assert primary_image is not None
    assert primary_image["source_url"] == "https://example.com/run-fast.png"
    assert str(primary_image["local_path"]).startswith("assets/workbook-import/image/")
    audio_asset = get_learning_item_asset(int(learning_item["id"]), role="alloy")
    assert audio_asset is not None
    assert audio_asset["source_url"] == "https://example.com/run-fast.mp3"
    assert str(audio_asset["local_path"]).startswith("assets/workbook-import/audio/")
    assert get_learning_item_asset(int(learning_item["id"]), role="image_preview") is None
    assert {
        (row["language_code"], row["translation_text"])
        for row in list_learning_item_translations(int(learning_item["id"]))
    } == {("ru", "бежать"), ("uk", "бігти")}


def test_import_uses_default_translation_language_for_untagged_text(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = setup_db(tmp_path)

    workbook_bytes = build_workbook_bytes(
        meta_rows=[("2", None, "bg")],
        learning_item_rows=[("sun", "слънце", "Authoring", None, None, None, None, None, 0)],
    )

    import_teacher_workspace_workbook(teacher_user_id, workspace_id, workbook_bytes)
    with db.get_connection() as connection:
        row = connection.execute(
            """
            SELECT learning_item_translations.language_code, learning_item_translations.translation_text
            FROM learning_items
            JOIN learning_item_translations
              ON learning_item_translations.learning_item_id = learning_items.id
            WHERE learning_items.workspace_id = ?
            """,
            (workspace_id,),
        ).fetchone()

    assert row is not None
    assert row["language_code"] == "bg"
    assert row["translation_text"] == "слънце"


def test_import_collects_human_readable_validation_errors(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = setup_db(tmp_path)

    workbook_bytes = build_workbook_bytes(
        learning_item_rows=[
            ("cat", "<ru> кот", None, "animals", "ftp://example.com/cat.png", None, None, None, 0),
            ("cat", "<ru>: кот", "Another", None, None, None, None, "alloy", 0),
        ]
    )

    with pytest.raises(WorkbookImportError) as error:
        import_teacher_workspace_workbook(teacher_user_id, workspace_id, workbook_bytes)

    assert (
        "Sheet 'learning_items' row 2 has invalid translation syntax '<ru> кот'."
        in str(error.value)
    )
    assert "Sheet 'learning_items' row 2 has unsupported URL in 'image_url'." in str(error.value)
    assert "Sheet 'learning_items' row 3 targets workspace 'Another'" in str(error.value)
    assert "Sheet 'learning_items' row 3 has 'audio_voice' without 'audio_url'." in str(error.value)


def test_import_uses_one_explicit_write_transaction_and_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    teacher_user_id, workspace_id = setup_db(tmp_path)
    original_learning_item_id = create_learning_item(create_lexeme("cat"), "cat", workspace_id=workspace_id)
    seen_calls: list[str] = []
    install_media_download_stub(monkeypatch)

    def recording_begin(connection) -> None:
        seen_calls.append("begin")
        _begin_import_transaction(connection)

    monkeypatch.setattr("englishbot.workbook_import._begin_import_transaction", recording_begin)
    monkeypatch.setattr(
        "englishbot.workbook_import._replace_workbook_assets",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    workbook_bytes = build_workbook_bytes(
        learning_item_rows=[("dog", "<ru>: собака", None, None, None, None, None, None, 0)]
    )

    with pytest.raises(RuntimeError):
        import_teacher_workspace_workbook(teacher_user_id, workspace_id, workbook_bytes)

    assert seen_calls == ["begin"]
    assert get_learning_item(original_learning_item_id)["text"] == "cat"
    with db.get_connection() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM learning_items WHERE workspace_id = ? AND text = 'dog'",
                (workspace_id,),
            ).fetchone()[0]
            == 0
        )


def test_import_creates_backup_and_prunes_to_latest_500(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    teacher_user_id, workspace_id = setup_db(tmp_path)
    backup_dir = db.get_workbook_import_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    for index in range(500):
        (backup_dir / f"seed-{index:03d}.sqlite3").write_bytes(b"seed")
    install_media_download_stub(monkeypatch)

    workbook_bytes = build_workbook_bytes(
        learning_item_rows=[("cat", "<ru>: кот", None, None, None, None, None, None, 0)]
    )

    import_teacher_workspace_workbook(teacher_user_id, workspace_id, workbook_bytes)

    backups = sorted(backup_dir.glob("*.sqlite3"))
    assert len(backups) == 500
    assert any("workbook_import" in path.name for path in backups)


def test_import_creates_backup_before_validation_failure(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = setup_db(tmp_path)
    backup_dir = db.get_workbook_import_backup_dir()

    workbook_bytes = build_workbook_bytes(
        learning_item_rows=[("cat", "<ru> broken", None, None, None, None, None, None, 0)]
    )

    with pytest.raises(WorkbookImportError):
        import_teacher_workspace_workbook(teacher_user_id, workspace_id, workbook_bytes)

    assert len(list(backup_dir.glob("*.sqlite3"))) == 1


def test_import_validates_global_workspace_and_topic_uniqueness(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = setup_db(tmp_path)
    duplicate_workspace = create_workspace("Authoring", kind="teacher")
    add_workspace_member(duplicate_workspace["workspace_id"], teacher_user_id, "teacher")
    other_workspace = create_workspace("Other", kind="teacher")
    add_workspace_member(other_workspace["workspace_id"], teacher_user_id, "teacher")
    create_topic("shared-topic", "shared-topic", workspace_id=int(other_workspace["workspace_id"]))

    workbook_bytes = build_workbook_bytes(
        learning_item_rows=[("cat", "<ru>: кот", None, "shared-topic", None, None, None, None, 0)]
    )

    with pytest.raises(WorkbookImportError) as error:
        import_teacher_workspace_workbook(teacher_user_id, workspace_id, workbook_bytes)

    assert "Workspace name 'Authoring' is not globally unique" in str(error.value)
    assert "Topic name 'shared-topic' already exists in workspace 'Other'" in str(error.value)


def test_import_rejects_legacy_workbook_format(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = setup_db(tmp_path)
    workbook_bytes = build_workbook_bytes(sheet_names=["topics", "learning_items"])

    with pytest.raises(WorkbookImportError) as error:
        import_teacher_workspace_workbook(teacher_user_id, workspace_id, workbook_bytes)

    assert "Legacy workbook sheets are no longer supported." in str(error.value)


def test_import_rejects_student_workspace_targets(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "workbook_import_student.sqlite3"
    db.init_db()
    teacher_user_id = 777
    workspace = create_workspace("Student Runtime", kind="student")
    add_workspace_member(workspace["workspace_id"], teacher_user_id, "teacher")
    workbook_bytes = build_workbook_bytes(learning_item_rows=[])

    with pytest.raises(WorkspaceKindMismatchError):
        import_teacher_workspace_workbook(teacher_user_id, int(workspace["workspace_id"]), workbook_bytes)


def test_import_archives_unmatched_existing_topic_and_item(tmp_path: Path) -> None:
    teacher_user_id, workspace_id = setup_db(tmp_path)
    learning_item_id = create_learning_item(create_lexeme("old"), "old", workspace_id=workspace_id)
    create_learning_item_translation(learning_item_id, "ru", "старый")
    topic_id = create_topic("legacy", "legacy", workspace_id=workspace_id)

    workbook_bytes = build_workbook_bytes(
        learning_item_rows=[("new", "<ru>: новый", None, "fresh", None, None, None, None, 0)]
    )

    import_teacher_workspace_workbook(teacher_user_id, workspace_id, workbook_bytes)

    assert get_learning_item(learning_item_id)["is_archived"] == 1
    assert get_topic(topic_id, include_archived=True)["is_archived"] == 1
