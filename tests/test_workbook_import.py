import sys
from pathlib import Path

import pytest
from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.assets import PRIMARY_IMAGE_ROLE, resolve_asset_ref_for_role
from englishbot.families import create_family, create_family_learning_item, create_family_topic, list_family_topics, replace_topic_items
from englishbot.topics import get_topic_learning_item_ids
from englishbot.vocabulary import get_learning_item, list_learning_item_translations, create_learning_item_translation, create_lexeme
from englishbot.workbook_export import export_family_workbook
from englishbot.workbook_import import WorkbookImportValidationError, apply_family_workbook_import


def setup_db(tmp_path: Path, monkeypatch) -> int:
    db.DB_PATH = tmp_path / "workbook_import.sqlite3"
    monkeypatch.setenv("ENGLISHBOT_BACKUP_DIR", str(tmp_path / "backups"))
    db.init_db()
    owner = type("User", (), {"id": 1401, "username": "owner", "first_name": "Owner", "last_name": None})()
    db.save_user(owner)
    family = create_family("Home", owner.id)
    return int(family["id"])


def seed_family_content(family_id: int) -> tuple[int, int]:
    first_item_id = create_family_learning_item(family_id, create_lexeme("apple"), "apple")
    second_item_id = create_family_learning_item(family_id, create_lexeme("pear"), "pear")
    create_learning_item_translation(first_item_id, "ru", "яблоко")
    create_learning_item_translation(second_item_id, "ru", "груша")
    topic_id = create_family_topic(family_id, "fruits", "Fruits")
    replace_topic_items(topic_id, [first_item_id, second_item_id])
    with db.get_connection() as connection:
        from englishbot.assets import replace_learning_item_assets_for_role, ASSET_TYPE_IMAGE

        replace_learning_item_assets_for_role(
            first_item_id,
            PRIMARY_IMAGE_ROLE,
            assets=[{"asset_type": ASSET_TYPE_IMAGE, "local_path": "assets/images/apple.jpg"}],
            connection=connection,
        )
    return first_item_id, second_item_id


def test_import_updates_creates_archives_and_ignores_display_only_image_column(tmp_path: Path, monkeypatch) -> None:
    family_id = setup_db(tmp_path, monkeypatch)
    first_item_id, second_item_id = seed_family_content(family_id)
    workbook_path = export_family_workbook(family_id, output_path=tmp_path / "family.xlsx").file_path
    workbook = load_workbook(workbook_path)
    sheet = workbook["learning_items"]

    sheet["B2"] = "green apple"
    sheet["C2"] = "зеленое яблоко"
    sheet["F2"] = "Fruits\nFresh picks"
    sheet["H2"] = '=IMAGE("https://malicious.example.com/override.jpg")'
    sheet.delete_rows(3, 1)
    sheet.append(
        [
            "",
            "plum",
            "слива",
            "",
            "",
            "Fresh picks",
            "assets/images/plum.jpg",
            '=IMAGE("https://example.com/plum.jpg")',
            "",
            0,
        ]
    )
    workbook.save(workbook_path)

    summary = apply_family_workbook_import(workbook_path, family_id, started_by_user_id=1401)

    updated_item = get_learning_item(first_item_id)
    archived_item = get_learning_item(second_item_id)
    all_topics = list_family_topics(family_id)
    fresh_topic = next(topic for topic in all_topics if topic["title"] == "Fresh picks")
    translations = {
        row["language_code"]: row["translation_text"]
        for row in list_learning_item_translations(first_item_id)
    }
    family_items = {
        item["text"]: item
        for item in [
            get_learning_item(first_item_id),
            get_learning_item(second_item_id),
            get_learning_item(max(first_item_id, second_item_id) + 1),
        ]
        if item is not None and item["family_id"] == family_id
    }

    assert summary.created == 1
    assert summary.updated == 1
    assert summary.archived == 1
    assert summary.backup_file_path.exists()
    assert updated_item is not None
    assert updated_item["text"] == "green apple"
    assert translations["ru"] == "зеленое яблоко"
    assert resolve_asset_ref_for_role(first_item_id, PRIMARY_IMAGE_ROLE) == "assets/images/apple.jpg"
    assert archived_item is not None
    assert archived_item["is_archived"] == 1
    assert "plum" in family_items
    assert get_topic_learning_item_ids(int(fresh_topic["id"])) == [first_item_id, int(family_items["plum"]["id"])]


def test_import_validates_before_writing(tmp_path: Path, monkeypatch) -> None:
    family_id = setup_db(tmp_path, monkeypatch)
    first_item_id, _ = seed_family_content(family_id)
    workbook_path = export_family_workbook(family_id, output_path=tmp_path / "family-invalid.xlsx").file_path
    workbook = load_workbook(workbook_path)
    sheet = workbook["learning_items"]
    sheet.append(list(sheet.iter_rows(min_row=2, max_row=2, values_only=True))[0])
    workbook.save(workbook_path)

    with pytest.raises(WorkbookImportValidationError):
        apply_family_workbook_import(workbook_path, family_id, started_by_user_id=1401)

    assert get_learning_item(first_item_id)["text"] == "apple"


def test_import_runs_in_one_transaction(tmp_path: Path, monkeypatch) -> None:
    family_id = setup_db(tmp_path, monkeypatch)
    first_item_id, _ = seed_family_content(family_id)
    workbook_path = export_family_workbook(family_id, output_path=tmp_path / "family-atomic.xlsx").file_path
    workbook = load_workbook(workbook_path)
    sheet = workbook["learning_items"]
    sheet["B2"] = "changed apple"
    workbook.save(workbook_path)

    def fail_replace_asset_ref(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("englishbot.workbook_import._replace_asset_ref", fail_replace_asset_ref)

    with pytest.raises(RuntimeError):
        apply_family_workbook_import(workbook_path, family_id, started_by_user_id=1401)

    assert get_learning_item(first_item_id)["text"] == "apple"
