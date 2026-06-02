import sqlite3
import sys
from pathlib import Path

import pytest
from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.families import (
    add_family_member,
    create_family,
    create_family_learning_item,
    create_family_topic,
    replace_topic_items,
)
from englishbot.topic_access import (
    EmptyTopicError,
    TopicAccessDeniedError,
    TopicNotFoundError,
    list_accessible_topics,
    start_topic_training_session,
    student_has_topic_access,
)
from englishbot.training import get_active_training_session
from englishbot.vocabulary import create_learning_item_translation, create_lexeme


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "topic_access.sqlite3"
    db.init_db()


def seed_family_topic() -> tuple[sqlite3.Row, User, User, int]:
    parent = make_user(721, "Parent")
    child = make_user(722, "Child")
    db.save_user(parent)
    db.save_user(child)
    family = create_family("Home", parent.id)
    add_family_member(int(family["id"]), child.id)
    first_item_id = create_family_learning_item(int(family["id"]), create_lexeme("cat-family"), "cat")
    second_item_id = create_family_learning_item(int(family["id"]), create_lexeme("dog-family"), "dog")
    create_learning_item_translation(first_item_id, "ru", "кот")
    create_learning_item_translation(second_item_id, "ru", "собака")
    topic_id = create_family_topic(int(family["id"]), "pets", "Pets")
    replace_topic_items(topic_id, [first_item_id, second_item_id])
    return family, parent, child, topic_id


def test_list_accessible_topics_returns_family_topics(tmp_path: Path) -> None:
    setup_db(tmp_path)
    _, _, child, _ = seed_family_topic()

    topics = list_accessible_topics(child.id)

    assert [topic["name"] for topic in topics] == ["pets"]
    assert [topic["title"] for topic in topics] == ["Pets"]
    assert [int(topic["item_count"]) for topic in topics] == [2]


def test_list_accessible_topics_returns_empty_for_user_without_family(tmp_path: Path) -> None:
    setup_db(tmp_path)
    outsider = make_user(723, "Outsider")
    db.save_user(outsider)

    assert list_accessible_topics(outsider.id) == []


def test_student_has_topic_access_checks_family_membership(tmp_path: Path) -> None:
    setup_db(tmp_path)
    _, _, child, topic_id = seed_family_topic()

    assert student_has_topic_access(child.id, topic_id) is True
    assert student_has_topic_access(child.id, 999) is False


def test_start_topic_training_session_uses_family_topic_items(tmp_path: Path) -> None:
    setup_db(tmp_path)
    _, _, child, topic_id = seed_family_topic()

    result = start_topic_training_session(child.id, topic_id)
    question = result["question"]
    active_session = get_active_training_session(child.id)

    assert question is not None
    assert result["topic_title"] == "Pets"
    assert question["prompt"] == "кот"
    assert active_session is not None
    assert active_session["assignment_id"] is None


def test_start_topic_training_session_rejects_user_from_other_family(tmp_path: Path) -> None:
    setup_db(tmp_path)
    _, _, _, topic_id = seed_family_topic()
    outsider = make_user(724, "Outsider")
    db.save_user(outsider)

    with pytest.raises(TopicAccessDeniedError):
        start_topic_training_session(outsider.id, topic_id)


def test_start_topic_training_session_rejects_unknown_topic(tmp_path: Path) -> None:
    setup_db(tmp_path)
    _, _, child, _ = seed_family_topic()

    with pytest.raises(TopicNotFoundError):
        start_topic_training_session(child.id, 999)


def test_start_topic_training_session_rejects_empty_topic(tmp_path: Path) -> None:
    setup_db(tmp_path)
    parent = make_user(725, "Parent")
    child = make_user(726, "Child")
    db.save_user(parent)
    db.save_user(child)
    family = create_family("Home", parent.id)
    add_family_member(int(family["id"]), child.id)
    topic_id = create_family_topic(int(family["id"]), "empty", "Empty")

    with pytest.raises(EmptyTopicError):
        start_topic_training_session(child.id, topic_id)
