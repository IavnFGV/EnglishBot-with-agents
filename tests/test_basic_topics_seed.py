import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.basic_topics_seed import BASIC_TOPICS, seed_basic_topics


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "basic_topics_seed.sqlite3"


def test_seed_basic_topics_populates_expected_multilingual_content(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)

    result = seed_basic_topics()

    expected_item_count = sum(len(topic["items"]) for topic in BASIC_TOPICS)
    assert result == {
        "topics": 3,
        "created_lexemes": expected_item_count,
        "created_learning_items": expected_item_count,
        "created_translations": expected_item_count * 3,
    }

    with sqlite3.connect(db.DB_PATH) as connection:
        lexeme_count = connection.execute("SELECT COUNT(*) FROM lexemes").fetchone()[0]
        learning_item_count = connection.execute(
            "SELECT COUNT(*) FROM learning_items"
        ).fetchone()[0]
        translation_count = connection.execute(
            "SELECT COUNT(*) FROM learning_item_translations"
        ).fetchone()[0]

        monday_translations = connection.execute(
            """
            SELECT language_code, translation_text
            FROM learning_item_translations
            JOIN learning_items
              ON learning_items.id = learning_item_translations.learning_item_id
            JOIN lexemes
              ON lexemes.id = learning_items.lexeme_id
            WHERE lexemes.lemma = 'monday'
            ORDER BY language_code
            """
        ).fetchall()

    assert lexeme_count == expected_item_count
    assert learning_item_count == expected_item_count
    assert translation_count == expected_item_count * 3
    assert monday_translations == [
        ("bg", "понеделник"),
        ("ru", "понедельник"),
        ("uk", "понеділок"),
    ]


def test_seed_basic_topics_is_idempotent(tmp_path: Path) -> None:
    setup_db(tmp_path)

    first_run = seed_basic_topics()
    second_run = seed_basic_topics()

    expected_item_count = sum(len(topic["items"]) for topic in BASIC_TOPICS)
    assert first_run["created_learning_items"] == expected_item_count
    assert second_run == {
        "topics": 3,
        "created_lexemes": 0,
        "created_learning_items": 0,
        "created_translations": 0,
    }

    with sqlite3.connect(db.DB_PATH) as connection:
        assert connection.execute("SELECT COUNT(*) FROM lexemes").fetchone()[0] == (
            expected_item_count
        )
        assert connection.execute("SELECT COUNT(*) FROM learning_items").fetchone()[0] == (
            expected_item_count
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM learning_item_translations"
        ).fetchone()[0] == (expected_item_count * 3)
