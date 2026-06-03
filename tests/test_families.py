import sqlite3
import sys
from pathlib import Path

import pytest
from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.families import (
    FamilyMembershipError,
    DEMO_FAMILY_TOPICS,
    add_user_to_owner_family,
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
    ensure_user_family,
    seed_demo_family_content,
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


def test_owner_family_helpers_create_and_extend_owner_family(tmp_path: Path) -> None:
    setup_db(tmp_path)
    owner = make_user(820, "Owner")
    child = make_user(821, "Child")
    db.save_user(owner)
    db.save_user(child)

    family = ensure_user_family(owner.id)
    same_family, status = add_user_to_owner_family(owner.id, child.id)
    repeated_family, repeated_status = add_user_to_owner_family(owner.id, child.id)

    assert int(family["id"]) == int(same_family["id"]) == int(repeated_family["id"])
    assert status == "added"
    assert repeated_status == "already_member"
    assert get_user_family(child.id)["id"] == family["id"]


def test_seed_demo_family_content_creates_expected_topics_items_and_is_idempotent(tmp_path: Path) -> None:
    setup_db(tmp_path)
    owner = make_user(822, "Owner")
    db.save_user(owner)

    first_result = seed_demo_family_content(owner.id)
    second_result = seed_demo_family_content(owner.id)
    family_id = int(first_result["family_id"])
    topics = list_family_topics(family_id)
    items = list_family_learning_items(family_id)

    assert first_result["created_topics"] == len(DEMO_FAMILY_TOPICS)
    assert first_result["created_items"] == sum(len(topic["items"]) for topic in DEMO_FAMILY_TOPICS)
    assert second_result["created_topics"] == 0
    assert second_result["created_items"] == 0
    assert [topic["title"] for topic in topics] == ["Colors", "Seasons"]
    assert len(items) == 10


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
