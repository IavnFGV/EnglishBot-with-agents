import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.basic_topics_seed import (
    BASIC_TOPICS,
    list_basic_topic_groups,
    resolve_basic_topic_learning_item_ids,
    seed_basic_topics,
)
from englishbot.db import DEFAULT_CONTENT_WORKSPACE_NAME, get_default_content_workspace_id


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
        "created_topics": 3,
        "created_lexemes": expected_item_count,
        "created_learning_items": expected_item_count,
        "created_translations": expected_item_count * 3,
        "created_topic_links": expected_item_count,
    }

    with sqlite3.connect(db.DB_PATH) as connection:
        workspace_rows = connection.execute(
            "SELECT id, name FROM workspaces ORDER BY id"
        ).fetchall()
        topic_count = connection.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
        lexeme_count = connection.execute("SELECT COUNT(*) FROM lexemes").fetchone()[0]
        learning_item_count = connection.execute(
            "SELECT COUNT(*) FROM learning_items"
        ).fetchone()[0]
        translation_count = connection.execute(
            "SELECT COUNT(*) FROM learning_item_translations"
        ).fetchone()[0]
        topic_link_count = connection.execute(
            "SELECT COUNT(*) FROM topic_learning_items"
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
        seeded_topic_workspace_ids = {
            row[0] for row in connection.execute("SELECT DISTINCT workspace_id FROM topics")
        }
        seeded_item_workspace_ids = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT workspace_id FROM learning_items"
            )
        }

    default_workspace_id = get_default_content_workspace_id()
    assert workspace_rows == [(default_workspace_id, DEFAULT_CONTENT_WORKSPACE_NAME)]
    assert topic_count == len(BASIC_TOPICS)
    assert lexeme_count == expected_item_count
    assert learning_item_count == expected_item_count
    assert translation_count == expected_item_count * 3
    assert topic_link_count == expected_item_count
    assert seeded_topic_workspace_ids == {default_workspace_id}
    assert seeded_item_workspace_ids == {default_workspace_id}
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
        "created_topics": 0,
        "created_lexemes": 0,
        "created_learning_items": 0,
        "created_translations": 0,
        "created_topic_links": 0,
    }

    with sqlite3.connect(db.DB_PATH) as connection:
        assert connection.execute("SELECT COUNT(*) FROM topics").fetchone()[0] == len(BASIC_TOPICS)
        assert connection.execute("SELECT COUNT(*) FROM lexemes").fetchone()[0] == (
            expected_item_count
        )
        assert connection.execute("SELECT COUNT(*) FROM learning_items").fetchone()[0] == (
            expected_item_count
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM learning_item_translations"
        ).fetchone()[0] == (expected_item_count * 3)
        assert connection.execute("SELECT COUNT(*) FROM topic_learning_items").fetchone()[0] == (
            expected_item_count
        )


def test_list_basic_topic_groups_returns_named_seeded_packs(tmp_path: Path) -> None:
    setup_db(tmp_path)
    seed_basic_topics()

    groups = list_basic_topic_groups()

    assert groups == [
        {"name": "weekdays", "title": "Дни недели", "item_count": 7},
        {"name": "months", "title": "Месяцы", "item_count": 6},
        {"name": "colors", "title": "Цвета", "item_count": 6},
    ]


def test_resolve_basic_topic_learning_item_ids_uses_seeded_learning_items(tmp_path: Path) -> None:
    setup_db(tmp_path)
    seed_basic_topics()

    learning_item_ids = resolve_basic_topic_learning_item_ids("weekdays")

    assert len(learning_item_ids) == 7
    with sqlite3.connect(db.DB_PATH) as connection:
        lemmas = [
            row[0]
            for row in connection.execute(
                """
                SELECT lexemes.lemma
                FROM learning_items
                JOIN lexemes
                  ON lexemes.id = learning_items.lexeme_id
                WHERE learning_items.id IN (?, ?, ?, ?, ?, ?, ?)
                ORDER BY CASE learning_items.id
                    WHEN ? THEN 0
                    WHEN ? THEN 1
                    WHEN ? THEN 2
                    WHEN ? THEN 3
                    WHEN ? THEN 4
                    WHEN ? THEN 5
                    WHEN ? THEN 6
                END
                """,
                tuple(learning_item_ids + learning_item_ids),
            ).fetchall()
        ]

    assert lemmas == [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]
