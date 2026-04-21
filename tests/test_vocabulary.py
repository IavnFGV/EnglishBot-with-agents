import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.assets import (
    PRIMARY_AUDIO_ROLE,
    PRIMARY_IMAGE_ROLE,
    clone_learning_item_assets,
    create_asset,
    get_learning_item_asset,
    link_asset_to_learning_item,
    list_learning_item_assets,
    replace_learning_item_assets_for_role,
    resolve_asset_ref_for_role,
)
from englishbot.db import LEARNING_ITEM_WORKBOOK_KEY_PREFIX, build_workbook_key, get_default_content_workspace_id
from englishbot.vocabulary import (
    archive_learning_item,
    create_learning_item,
    create_learning_item_for_teacher_workspace,
    create_learning_item_translation,
    create_lexeme,
    get_learning_item,
    get_learning_item_with_translations,
    get_lexeme,
    list_learning_item_translations,
    list_learning_items,
    publish_learning_item_to_workspace,
    update_learning_item,
    upsert_learning_item_translation,
)
from englishbot.workspaces import (
    WorkspaceEditPermissionError,
    WorkspaceKindMismatchError,
    add_workspace_member,
    create_workspace,
)


def setup_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "vocabulary.sqlite3"
    db.DB_PATH = db_path
    db.init_db()
    return db_path


def _add_primary_assets(learning_item_id: int) -> None:
    image_id = create_asset("image", local_path="assets/images/run-fast.png")
    audio_id = create_asset("audio", local_path="assets/audio/run-fast.mp3")
    link_asset_to_learning_item(learning_item_id, image_id, PRIMARY_IMAGE_ROLE)
    link_asset_to_learning_item(learning_item_id, audio_id, PRIMARY_AUDIO_ROLE)


def test_init_db_creates_asset_registry_tables(tmp_path: Path) -> None:
    setup_db(tmp_path)

    with sqlite3.connect(db.DB_PATH) as connection:
        table_names = {
            row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        learning_item_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(learning_items)").fetchall()
        }

    assert "assets" in table_names
    assert "learning_item_assets" in table_names
    assert "image_ref" not in learning_item_columns
    assert "audio_ref" not in learning_item_columns


def test_init_db_migrates_legacy_media_fields_into_assets(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy_asset_migration.sqlite3"
    db.DB_PATH = db_path

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE workspaces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE lexemes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lemma TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO lexemes (lemma, created_at, updated_at)
            VALUES ('legacy', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """
        )
        connection.execute(
            """
            CREATE TABLE learning_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lexeme_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                image_ref TEXT,
                audio_ref TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO learning_items (
                lexeme_id,
                text,
                image_ref,
                audio_ref,
                created_at,
                updated_at
            )
            VALUES (
                1,
                'legacy',
                'assets/images/legacy.png',
                'https://example.com/legacy.mp3',
                '2026-01-01T00:00:00+00:00',
                '2026-01-01T00:00:00+00:00'
            )
            """
        )

    db.init_db()
    db.init_db()

    with sqlite3.connect(db_path) as connection:
        learning_item_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(learning_items)").fetchall()
        }
        assets = connection.execute(
            """
            SELECT assets.asset_type, assets.source_url, assets.local_path, learning_item_assets.role
            FROM learning_item_assets
            JOIN assets
              ON assets.id = learning_item_assets.asset_id
            ORDER BY learning_item_assets.id
            """
        ).fetchall()

    assert "image_ref" not in learning_item_columns
    assert "audio_ref" not in learning_item_columns
    assert assets == [
        ("image", None, "assets/images/legacy.png", "primary_image"),
        ("audio", "https://example.com/legacy.mp3", None, "primary_audio"),
    ]


def test_create_and_get_lexeme(tmp_path: Path) -> None:
    setup_db(tmp_path)

    lexeme_id = create_lexeme("apple")

    lexeme = get_lexeme(lexeme_id)
    assert lexeme is not None
    assert lexeme["id"] == lexeme_id
    assert lexeme["lemma"] == "apple"


def test_create_and_get_learning_item_with_linked_assets(tmp_path: Path) -> None:
    setup_db(tmp_path)
    lexeme_id = create_lexeme("run")
    default_workspace_id = get_default_content_workspace_id()

    without_assets_id = create_learning_item(lexeme_id, "run")
    with_assets_id = create_learning_item(lexeme_id, "run fast")
    _add_primary_assets(with_assets_id)

    without_assets = get_learning_item(without_assets_id)
    with_assets = get_learning_item(with_assets_id)
    assert without_assets is not None
    assert with_assets is not None
    assert without_assets["workspace_id"] == default_workspace_id
    assert with_assets["workspace_id"] == default_workspace_id
    assert without_assets["workbook_key"].startswith(f"{LEARNING_ITEM_WORKBOOK_KEY_PREFIX}-")
    assert with_assets["workbook_key"].startswith(f"{LEARNING_ITEM_WORKBOOK_KEY_PREFIX}-")
    assert without_assets["is_archived"] == 0
    assert with_assets["text"] == "run fast"
    assert resolve_asset_ref_for_role(with_assets_id, PRIMARY_IMAGE_ROLE) == "assets/images/run-fast.png"
    assert resolve_asset_ref_for_role(with_assets_id, PRIMARY_AUDIO_ROLE) == "assets/audio/run-fast.mp3"


def test_asset_registry_supports_multiple_assets_and_role_lookup(tmp_path: Path) -> None:
    setup_db(tmp_path)
    learning_item_id = create_learning_item(create_lexeme("voice"), "voice")

    first_voice = create_asset("voice", source_url="https://example.com/female.ogg")
    second_voice = create_asset("voice", source_url="https://example.com/male.ogg")
    image_asset = create_asset("image", local_path="assets/images/voice.png")
    link_asset_to_learning_item(learning_item_id, image_asset, PRIMARY_IMAGE_ROLE)
    link_asset_to_learning_item(learning_item_id, first_voice, "female_voice", sort_order=0)
    link_asset_to_learning_item(learning_item_id, second_voice, "male_voice", sort_order=1)

    assets = list_learning_item_assets(learning_item_id)

    assert len(assets) == 3
    assert get_learning_item_asset(learning_item_id, role="female_voice")["source_url"] == "https://example.com/female.ogg"
    assert get_learning_item_asset(learning_item_id, asset_type="image")["local_path"] == "assets/images/voice.png"


def test_get_learning_item_with_translations_returns_assets_slice(tmp_path: Path) -> None:
    setup_db(tmp_path)
    lexeme_id = create_lexeme("book")
    learning_item_id = create_learning_item(lexeme_id, "book")
    image_id = create_asset("image", local_path="assets/images/book.png")
    link_asset_to_learning_item(learning_item_id, image_id, PRIMARY_IMAGE_ROLE)
    create_learning_item_translation(learning_item_id, "de", "Buch")
    create_learning_item_translation(learning_item_id, "uk", "книга")

    content = get_learning_item_with_translations(learning_item_id)

    assert content is not None
    assert content["learning_item"]["id"] == learning_item_id
    assert content["learning_item"]["lexeme_id"] == lexeme_id
    assert content["learning_item"]["text"] == "book"
    assert len(content["learning_item"]["assets"]) == 1
    assert content["learning_item"]["assets"][0]["local_path"] == "assets/images/book.png"
    assert [translation["language_code"] for translation in content["translations"]] == ["de", "uk"]


def test_only_teacher_members_of_teacher_workspaces_can_edit_items(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher_workspace = create_workspace("Authoring", kind="teacher")
    student_workspace = create_workspace("Learning", kind="student")
    add_workspace_member(teacher_workspace["workspace_id"], 201, "teacher")
    add_workspace_member(teacher_workspace["workspace_id"], 202, "student")
    add_workspace_member(student_workspace["workspace_id"], 201, "teacher")
    lexeme_id = create_lexeme("bird")

    learning_item_id = create_learning_item_for_teacher_workspace(201, teacher_workspace["workspace_id"], lexeme_id, "bird")
    update_learning_item(201, learning_item_id, text="bird updated")
    upsert_learning_item_translation(201, learning_item_id, "ru", "птица")

    assert get_learning_item(learning_item_id)["text"] == "bird updated"
    assert list_learning_item_translations(learning_item_id)[0]["translation_text"] == "птица"

    with pytest.raises(WorkspaceEditPermissionError):
        create_learning_item_for_teacher_workspace(202, teacher_workspace["workspace_id"], lexeme_id, "bad")

    with pytest.raises(WorkspaceKindMismatchError):
        create_learning_item_for_teacher_workspace(201, student_workspace["workspace_id"], lexeme_id, "bad")


def test_archive_learning_item_hides_it_from_lists(tmp_path: Path) -> None:
    setup_db(tmp_path)
    workspace = create_workspace("Authoring", kind="teacher")
    add_workspace_member(workspace["workspace_id"], 301, "teacher")
    lexeme_id = create_lexeme("plant")
    learning_item_id = create_learning_item_for_teacher_workspace(301, workspace["workspace_id"], lexeme_id, "plant")

    archive_learning_item(301, learning_item_id)

    assert get_learning_item(learning_item_id)["is_archived"] == 1
    assert list_learning_items(workspace_id=workspace["workspace_id"]) == []
    assert len(list_learning_items(workspace_id=workspace["workspace_id"], include_archived=True)) == 1


def test_publish_learning_item_to_student_workspace_clones_assets(tmp_path: Path) -> None:
    setup_db(tmp_path)
    source_workspace = create_workspace("Authoring", kind="teacher")
    target_workspace = create_workspace("Learning", kind="student")
    lexeme_id = create_lexeme("tree")
    source_learning_item_id = create_learning_item(lexeme_id, "tree", workspace_id=source_workspace["workspace_id"])
    create_learning_item_translation(source_learning_item_id, "ru", "дерево")
    _add_primary_assets(source_learning_item_id)

    first_published_id = publish_learning_item_to_workspace(source_learning_item_id, target_workspace["workspace_id"])
    published_learning_item = get_learning_item(first_published_id)
    source_learning_item = get_learning_item(source_learning_item_id)

    assert published_learning_item is not None
    assert source_learning_item is not None
    assert published_learning_item["workspace_id"] == target_workspace["workspace_id"]
    assert int(published_learning_item["source_learning_item_id"]) == source_learning_item_id
    assert published_learning_item["workbook_key"].startswith(f"{LEARNING_ITEM_WORKBOOK_KEY_PREFIX}-")
    assert published_learning_item["workbook_key"] != source_learning_item["workbook_key"]
    assert resolve_asset_ref_for_role(first_published_id, PRIMARY_IMAGE_ROLE) == "assets/images/run-fast.png"
    assert get_learning_item_asset(first_published_id, role=PRIMARY_IMAGE_ROLE)["asset_id"] != get_learning_item_asset(source_learning_item_id, role=PRIMARY_IMAGE_ROLE)["asset_id"]

    create_learning_item_translation(source_learning_item_id, "uk", "дерево-uk")
    replace_learning_item_assets_for_role(
        source_learning_item_id,
        PRIMARY_IMAGE_ROLE,
        assets=[{"asset_type": "image", "local_path": "assets/images/tree-new.png"}],
    )
    second_published_id = publish_learning_item_to_workspace(source_learning_item_id, target_workspace["workspace_id"])

    assert first_published_id == second_published_id
    assert [row["language_code"] for row in list_learning_item_translations(second_published_id)] == ["ru", "uk"]
    assert resolve_asset_ref_for_role(second_published_id, PRIMARY_IMAGE_ROLE) == "assets/images/tree-new.png"


def test_learning_item_workbook_keys_are_unique_within_workspace(tmp_path: Path) -> None:
    setup_db(tmp_path)
    first_workspace = create_workspace("Authoring A", kind="teacher")
    second_workspace = create_workspace("Authoring B", kind="teacher")
    lexeme_id = create_lexeme("shared-lemma")

    create_learning_item(lexeme_id, "first text", workspace_id=first_workspace["workspace_id"], workbook_key="shared-item-key")
    create_learning_item(lexeme_id, "second text", workspace_id=second_workspace["workspace_id"], workbook_key="shared-item-key")

    with pytest.raises(sqlite3.IntegrityError):
        create_learning_item(lexeme_id, "duplicate text", workspace_id=first_workspace["workspace_id"], workbook_key="shared-item-key")


def test_vocabulary_foreign_keys_reject_orphaned_learning_content(tmp_path: Path) -> None:
    setup_db(tmp_path)

    with pytest.raises(sqlite3.IntegrityError):
        create_learning_item(999, "orphaned item")

    lexeme_id = create_lexeme("bird")
    learning_item_id = create_learning_item(lexeme_id, "bird")

    with pytest.raises(sqlite3.IntegrityError):
        create_learning_item_translation(learning_item_id + 999, "fr", "oiseau")
