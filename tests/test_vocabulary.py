import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.vocabulary import (
    create_learning_item,
    create_learning_item_translation,
    create_lexeme,
    get_learning_item,
    get_learning_item_with_translations,
    get_lexeme,
    list_learning_item_translations,
)


def setup_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "vocabulary.sqlite3"
    db.DB_PATH = db_path
    db.init_db()
    return db_path


def test_init_db_creates_vocabulary_tables(tmp_path: Path) -> None:
    setup_db(tmp_path)

    with sqlite3.connect(db.DB_PATH) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert "lexemes" in table_names
    assert "learning_items" in table_names
    assert "learning_item_translations" in table_names


def test_init_db_migrates_learning_items_to_add_nullable_asset_refs(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "vocabulary_migration.sqlite3"
    db.DB_PATH = db_path

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE learning_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lexeme_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    db.init_db()

    with sqlite3.connect(db_path) as connection:
        column_names = {
            row[1]
            for row in connection.execute("PRAGMA table_info(learning_items)").fetchall()
        }

    assert "image_ref" in column_names
    assert "audio_ref" in column_names


def test_create_and_get_lexeme(tmp_path: Path) -> None:
    setup_db(tmp_path)

    lexeme_id = create_lexeme("apple")

    lexeme = get_lexeme(lexeme_id)
    assert lexeme is not None
    assert lexeme["id"] == lexeme_id
    assert lexeme["lemma"] == "apple"


def test_create_and_get_learning_item_with_nullable_assets(tmp_path: Path) -> None:
    setup_db(tmp_path)
    lexeme_id = create_lexeme("run")

    without_assets_id = create_learning_item(lexeme_id, "run")
    with_assets_id = create_learning_item(
        lexeme_id,
        "run fast",
        image_ref="assets/images/run-fast.png",
        audio_ref="assets/audio/run-fast.mp3",
    )

    without_assets = get_learning_item(without_assets_id)
    with_assets = get_learning_item(with_assets_id)
    assert without_assets is not None
    assert with_assets is not None
    assert without_assets["text"] == "run"
    assert without_assets["image_ref"] is None
    assert without_assets["audio_ref"] is None
    assert with_assets["text"] == "run fast"
    assert with_assets["image_ref"] == "assets/images/run-fast.png"
    assert with_assets["audio_ref"] == "assets/audio/run-fast.mp3"


def test_create_and_list_learning_item_translations(tmp_path: Path) -> None:
    setup_db(tmp_path)
    lexeme_id = create_lexeme("cat")
    learning_item_id = create_learning_item(lexeme_id, "cat")

    create_learning_item_translation(learning_item_id, "es", "gato")
    create_learning_item_translation(learning_item_id, "ru", "кот")

    translations = list_learning_item_translations(learning_item_id)

    assert [translation["language_code"] for translation in translations] == ["es", "ru"]
    assert [translation["translation_text"] for translation in translations] == [
        "gato",
        "кот",
    ]


def test_get_learning_item_with_translations_returns_full_content_slice(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    lexeme_id = create_lexeme("book")
    learning_item_id = create_learning_item(
        lexeme_id,
        "book",
        image_ref="assets/images/book.png",
    )
    create_learning_item_translation(learning_item_id, "de", "Buch")
    create_learning_item_translation(learning_item_id, "uk", "книга")

    content = get_learning_item_with_translations(learning_item_id)

    assert content is not None
    assert content["learning_item"]["id"] == learning_item_id
    assert content["learning_item"]["lexeme_id"] == lexeme_id
    assert content["learning_item"]["text"] == "book"
    assert content["learning_item"]["image_ref"] == "assets/images/book.png"
    assert content["learning_item"]["audio_ref"] is None
    assert [translation["language_code"] for translation in content["translations"]] == [
        "de",
        "uk",
    ]
    assert [
        translation["translation_text"] for translation in content["translations"]
    ] == ["Buch", "книга"]


def test_vocabulary_foreign_keys_reject_orphaned_learning_content(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)

    with pytest.raises(sqlite3.IntegrityError):
        create_learning_item(999, "orphaned item")

    lexeme_id = create_lexeme("bird")
    learning_item_id = create_learning_item(lexeme_id, "bird")

    with pytest.raises(sqlite3.IntegrityError):
        create_learning_item_translation(learning_item_id + 999, "fr", "oiseau")
