import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.db import get_default_content_workspace_id
from englishbot.topics import (
    TopicWorkspaceMismatchError,
    create_topic,
    get_learning_items_for_topic,
    get_topic,
    get_topic_by_name,
    get_topic_learning_item_ids,
    link_learning_item_to_topic,
    list_topics,
)
from englishbot.vocabulary import create_learning_item, create_lexeme
from englishbot.workspaces import create_workspace


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "topics.sqlite3"
    db.init_db()


def seed_learning_item(lemma: str) -> int:
    lexeme_id = create_lexeme(lemma)
    return create_learning_item(lexeme_id, lemma)


def test_init_db_creates_topic_tables(tmp_path: Path) -> None:
    setup_db(tmp_path)

    with sqlite3.connect(db.DB_PATH) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert "topics" in table_names
    assert "topic_learning_items" in table_names


def test_create_and_read_topic(tmp_path: Path) -> None:
    setup_db(tmp_path)
    default_workspace_id = get_default_content_workspace_id()

    topic_id = create_topic("months", "Месяцы")

    topic = get_topic(topic_id)
    resolved = get_topic_by_name("months")
    topics = list_topics()

    assert topic is not None
    assert topic["workspace_id"] == default_workspace_id
    assert topic["name"] == "months"
    assert topic["title"] == "Месяцы"
    assert resolved is not None
    assert resolved["id"] == topic_id
    assert topics == [topics[0]]
    assert topics[0]["workspace_id"] == default_workspace_id
    assert topics[0]["name"] == "months"
    assert topics[0]["title"] == "Месяцы"
    assert topics[0]["item_count"] == 0


def test_link_learning_items_to_topic_and_read_back_in_order(tmp_path: Path) -> None:
    setup_db(tmp_path)
    topic_id = create_topic("colors", "Цвета")
    first_item_id = seed_learning_item("red")
    second_item_id = seed_learning_item("blue")

    link_learning_item_to_topic(topic_id, first_item_id)
    link_learning_item_to_topic(topic_id, second_item_id)

    assert get_topic_learning_item_ids(topic_id) == [first_item_id, second_item_id]
    assert [row["id"] for row in get_learning_items_for_topic(topic_id)] == [
        first_item_id,
        second_item_id,
    ]


def test_get_topic_by_name_returns_none_for_missing_topic(tmp_path: Path) -> None:
    setup_db(tmp_path)

    assert get_topic_by_name("missing") is None


def test_init_db_migrates_topics_to_add_workspace_id(tmp_path: Path) -> None:
    db_path = tmp_path / "topics_workspace.sqlite3"
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
            CREATE TABLE topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO topics (name, title, created_at)
            VALUES ('legacy', 'Legacy Topic', '2026-01-01T00:00:00+00:00')
            """
        )

    db.init_db()
    default_workspace_id = get_default_content_workspace_id()

    with sqlite3.connect(db_path) as connection:
        column_names = {
            row[1] for row in connection.execute("PRAGMA table_info(topics)").fetchall()
        }
        topic_row = connection.execute(
            "SELECT workspace_id, name, title FROM topics WHERE name = 'legacy'"
        ).fetchone()

    assert "workspace_id" in column_names
    assert topic_row == (default_workspace_id, "legacy", "Legacy Topic")


def test_topic_links_enforce_foreign_keys(tmp_path: Path) -> None:
    setup_db(tmp_path)
    topic_id = create_topic("weekdays", "Дни недели")

    with pytest.raises(sqlite3.IntegrityError):
        link_learning_item_to_topic(topic_id, 999)


def test_topic_links_reject_cross_workspace_learning_items(tmp_path: Path) -> None:
    setup_db(tmp_path)
    topic_id = create_topic("weekdays", "Дни недели")
    other_workspace = create_workspace("Other")
    lexeme_id = create_lexeme("shared")
    foreign_item_id = create_learning_item(
        lexeme_id,
        "shared",
        workspace_id=other_workspace["workspace_id"],
    )

    with pytest.raises(TopicWorkspaceMismatchError):
        link_learning_item_to_topic(topic_id, foreign_item_id)
