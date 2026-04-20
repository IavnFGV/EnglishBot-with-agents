import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.db import get_default_content_workspace_id
from englishbot.topics import (
    TopicWorkspaceMismatchError,
    archive_topic,
    create_topic,
    create_topic_for_teacher_workspace,
    find_topic_by_name_for_teacher_workspace,
    get_learning_items_for_topic,
    get_topic,
    get_topic_by_name,
    get_topic_learning_item_ids,
    link_learning_item_to_topic,
    list_topics,
    publish_topic_to_workspace,
    rename_topic,
    replace_topic_learning_items,
)
from englishbot.vocabulary import create_learning_item, create_lexeme
from englishbot.workspaces import (
    WorkspaceEditPermissionError,
    WorkspaceKindMismatchError,
    create_workspace,
    add_workspace_member,
)


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "topics.sqlite3"
    db.init_db()


def seed_learning_item(lemma: str, workspace_id: int | None = None) -> int:
    lexeme_id = create_lexeme(lemma)
    return create_learning_item(lexeme_id, lemma, workspace_id=workspace_id)


def test_init_db_creates_topic_tables_with_archive_fields(tmp_path: Path) -> None:
    setup_db(tmp_path)

    with sqlite3.connect(db.DB_PATH) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        column_names = {row[1] for row in connection.execute("PRAGMA table_info(topics)")}

    assert "topics" in table_names
    assert "topic_learning_items" in table_names
    assert "is_archived" in column_names
    assert "updated_at" in column_names


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


def test_init_db_migrates_topics_to_add_workspace_and_archive_columns(tmp_path: Path) -> None:
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
            "SELECT workspace_id, is_archived, updated_at FROM topics WHERE name = 'legacy'"
        ).fetchone()

    assert "workspace_id" in column_names
    assert "is_archived" in column_names
    assert "updated_at" in column_names
    assert topic_row[0] == default_workspace_id
    assert topic_row[1] == 0
    assert topic_row[2] == "2026-01-01T00:00:00+00:00"


def test_topic_links_enforce_foreign_keys(tmp_path: Path) -> None:
    setup_db(tmp_path)
    topic_id = create_topic("weekdays", "Дни недели")

    with pytest.raises(sqlite3.IntegrityError):
        link_learning_item_to_topic(topic_id, 999)


def test_topic_links_reject_cross_workspace_learning_items(tmp_path: Path) -> None:
    setup_db(tmp_path)
    topic_id = create_topic("weekdays", "Дни недели")
    other_workspace = create_workspace("Other", kind="teacher")
    foreign_item_id = seed_learning_item("shared", workspace_id=other_workspace["workspace_id"])

    with pytest.raises(TopicWorkspaceMismatchError):
        link_learning_item_to_topic(topic_id, foreign_item_id)


def test_only_teacher_members_of_teacher_workspaces_can_edit_topics(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher_workspace = create_workspace("Authoring", kind="teacher")
    student_workspace = create_workspace("Learning", kind="student")
    add_workspace_member(teacher_workspace["workspace_id"], 201, "teacher")
    add_workspace_member(teacher_workspace["workspace_id"], 202, "student")
    add_workspace_member(student_workspace["workspace_id"], 201, "teacher")

    topic_id = create_topic_for_teacher_workspace(201, teacher_workspace["workspace_id"], "verbs", "Глаголы")
    rename_topic(201, topic_id, title="Новые глаголы")
    assert get_topic(topic_id)["title"] == "Новые глаголы"

    with pytest.raises(WorkspaceEditPermissionError):
        create_topic_for_teacher_workspace(202, teacher_workspace["workspace_id"], "bad", "Bad")

    with pytest.raises(WorkspaceKindMismatchError):
        create_topic_for_teacher_workspace(201, student_workspace["workspace_id"], "bad", "Bad")


def test_archive_topic_hides_it_from_discovery(tmp_path: Path) -> None:
    setup_db(tmp_path)
    workspace = create_workspace("Authoring", kind="teacher")
    add_workspace_member(workspace["workspace_id"], 301, "teacher")
    topic_id = create_topic_for_teacher_workspace(301, workspace["workspace_id"], "plants", "Растения")

    archive_topic(301, topic_id)

    assert get_topic(topic_id) is None
    assert get_topic(topic_id, include_archived=True)["is_archived"] == 1
    assert list_topics(workspace["workspace_id"]) == []


def test_publish_topic_to_student_workspace_copies_and_updates_membership(tmp_path: Path) -> None:
    setup_db(tmp_path)
    source_workspace = create_workspace("Authoring", kind="teacher")
    target_workspace = create_workspace("Learning", kind="student")
    add_workspace_member(source_workspace["workspace_id"], 401, "teacher")
    topic_id = create_topic_for_teacher_workspace(401, source_workspace["workspace_id"], "animals", "Животные")
    first_item_id = seed_learning_item("cat", workspace_id=source_workspace["workspace_id"])
    second_item_id = seed_learning_item("dog", workspace_id=source_workspace["workspace_id"])
    replace_topic_learning_items(401, topic_id, [first_item_id, second_item_id])

    first_publish = publish_topic_to_workspace(topic_id, target_workspace["workspace_id"])
    published_topic = get_topic(int(first_publish["topic_id"]))

    assert published_topic is not None
    assert published_topic["workspace_id"] == target_workspace["workspace_id"]
    assert int(published_topic["source_topic_id"]) == topic_id
    assert first_publish["learning_item_ids"] != [first_item_id, second_item_id]

    replace_topic_learning_items(401, topic_id, [second_item_id])
    second_publish = publish_topic_to_workspace(topic_id, target_workspace["workspace_id"])

    assert second_publish["topic_id"] == first_publish["topic_id"]
    assert get_topic_learning_item_ids(int(second_publish["topic_id"])) == second_publish["learning_item_ids"]
    assert len(second_publish["learning_item_ids"]) == 1


def test_find_topic_by_name_for_teacher_workspace_is_workspace_scoped(tmp_path: Path) -> None:
    setup_db(tmp_path)
    first_workspace = create_workspace("Authoring A", kind="teacher")
    second_workspace = create_workspace("Authoring B", kind="teacher")
    add_workspace_member(first_workspace["workspace_id"], 501, "teacher")
    add_workspace_member(second_workspace["workspace_id"], 501, "teacher")
    first_topic_id = create_topic_for_teacher_workspace(
        501,
        first_workspace["workspace_id"],
        "shared",
        "Первая тема",
    )
    second_topic_id = create_topic_for_teacher_workspace(
        501,
        second_workspace["workspace_id"],
        "shared",
        "Вторая тема",
    )

    first_topic = find_topic_by_name_for_teacher_workspace(501, first_workspace["workspace_id"], "shared")
    second_topic = find_topic_by_name_for_teacher_workspace(501, second_workspace["workspace_id"], "shared")

    assert first_topic is not None
    assert second_topic is not None
    assert first_topic["id"] == first_topic_id
    assert second_topic["id"] == second_topic_id
