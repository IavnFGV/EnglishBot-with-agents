import sqlite3
import sys
from pathlib import Path

import pytest
from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.families import (
    FamilyMembershipError,
    create_family,
    create_family_learning_item,
    create_family_topic,
    create_homework_assignment,
    get_homework_assignment,
    get_user_family,
    get_user_progress,
    list_family_learning_items,
    list_family_members,
    list_family_topics,
    replace_topic_items,
    upsert_user_progress,
    add_family_member,
)
from englishbot.vocabulary import create_learning_item_translation, create_lexeme


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "families.sqlite3"
    db.init_db()


def test_init_db_creates_family_first_tables_and_columns(tmp_path: Path) -> None:
    setup_db(tmp_path)

    with sqlite3.connect(db.DB_PATH) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        learning_item_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(learning_items)")
        }
        topic_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(topics)")
        }

    assert {
        "families",
        "family_members",
        "topic_items",
        "user_progress",
        "homework_assignments",
        "homework_assignment_items",
    }.issubset(table_names)
    assert "family_id" in learning_item_columns
    assert "family_id" in topic_columns


def test_create_family_adds_creator_as_single_family_member(tmp_path: Path) -> None:
    setup_db(tmp_path)
    parent = make_user(801, "Parent")
    db.save_user(parent)

    family = create_family("Home", parent.id)
    stored_family = get_user_family(parent.id)
    members = list_family_members(int(family["id"]))

    assert stored_family is not None
    assert stored_family["id"] == family["id"]
    assert [member["telegram_user_id"] for member in members] == [parent.id]


def test_add_family_member_rejects_second_family_membership(tmp_path: Path) -> None:
    setup_db(tmp_path)
    parent = make_user(802, "Parent")
    child = make_user(803, "Child")
    other_parent = make_user(804, "Other")
    db.save_user(parent)
    db.save_user(child)
    db.save_user(other_parent)

    family = create_family("Home", parent.id)
    other_family = create_family("Other Home", other_parent.id)
    add_family_member(int(family["id"]), child.id)

    with pytest.raises(FamilyMembershipError):
        add_family_member(int(other_family["id"]), child.id)


def test_family_learning_items_and_topics_are_scoped_to_one_family(tmp_path: Path) -> None:
    setup_db(tmp_path)
    parent = make_user(805, "Parent")
    child = make_user(806, "Child")
    outsider = make_user(807, "Outsider")
    db.save_user(parent)
    db.save_user(child)
    db.save_user(outsider)

    family = create_family("Home", parent.id)
    other_family = create_family("Other", outsider.id)
    add_family_member(int(family["id"]), child.id)

    cat_item_id = create_family_learning_item(int(family["id"]), create_lexeme("cat"), "cat")
    dog_item_id = create_family_learning_item(int(family["id"]), create_lexeme("dog"), "dog")
    create_learning_item_translation(cat_item_id, "ru", "кот")
    create_learning_item_translation(dog_item_id, "ru", "собака")
    other_item_id = create_family_learning_item(
        int(other_family["id"]),
        create_lexeme("bird"),
        "bird",
    )
    create_learning_item_translation(other_item_id, "ru", "птица")

    topic_id = create_family_topic(int(family["id"]), "pets", "Pets")
    replace_topic_items(topic_id, [cat_item_id, dog_item_id])

    assert [row["text"] for row in list_family_learning_items(int(family["id"]))] == ["cat", "dog"]
    assert [row["text"] for row in list_family_learning_items(int(other_family["id"]))] == ["bird"]
    assert [row["title"] for row in list_family_topics(int(family["id"]))] == ["Pets"]
    assert list_family_topics(int(other_family["id"])) == []


def test_family_homework_and_progress_persist_personal_state(tmp_path: Path) -> None:
    setup_db(tmp_path)
    parent = make_user(808, "Parent")
    child = make_user(809, "Child")
    db.save_user(parent)
    db.save_user(child)

    family = create_family("Home", parent.id)
    add_family_member(int(family["id"]), child.id)
    item_id = create_family_learning_item(int(family["id"]), create_lexeme("apple"), "apple")
    create_learning_item_translation(item_id, "ru", "яблоко")

    assignment_id = create_homework_assignment(
        int(family["id"]),
        parent.id,
        child.id,
        [item_id],
        title="Fruit",
    )
    upsert_user_progress(child.id, item_id, status="learning", correct_streak=2)

    assignment = get_homework_assignment(assignment_id)
    progress = get_user_progress(child.id, item_id)

    assert assignment is not None
    assert assignment["assigned_to_user_id"] == child.id
    assert assignment["title"] == "Fruit"
    assert progress is not None
    assert progress["status"] == "learning"
    assert progress["correct_streak"] == 2
