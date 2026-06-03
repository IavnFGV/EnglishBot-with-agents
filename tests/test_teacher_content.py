import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.families import add_family_member, create_family
from englishbot.teacher_content import (
    TeacherContentAccessError,
    build_teacher_topic_editor_snapshot,
    build_teacher_topic_full_list_overview,
    create_teacher_topic,
    create_teacher_topic_item,
    list_teacher_workspace_topics,
    update_teacher_topic_item_field,
    archive_teacher_topic_item,
)
from englishbot.vocabulary import get_learning_item, list_learning_item_translations


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "teacher_content.sqlite3"
    db.init_db()


def seed_family_user(user_id: int, family_name: str = "Home") -> tuple[int, int]:
    user = type("User", (), {
        "id": user_id,
        "username": f"user{user_id}",
        "first_name": f"User{user_id}",
        "last_name": None,
    })()
    db.save_user(user)
    family = create_family(family_name, user_id)
    return user_id, int(family["id"])


def seed_family_with_topic(
    user_id: int,
    *,
    topic_title: str = "Fruits",
    item_count: int = 1,
) -> tuple[int, int, int, list[int]]:
    user_id, family_id = seed_family_user(user_id)
    workspace_id = family_id
    topic = create_teacher_topic(user_id, workspace_id, topic_title)
    item_ids: list[int] = []
    for index in range(item_count):
        item = create_teacher_topic_item(
            user_id,
            workspace_id,
            int(topic["id"]),
            f"item-{index + 1}",
        )
        item_ids.append(int(item["learning_item_id"]))
    return user_id, family_id, workspace_id, [int(topic["id"]), *item_ids]


def test_teacher_content_topics_and_items_work_inside_family_workspace(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user_id, family_id = seed_family_user(161)
    workspace_id = family_id

    topic = create_teacher_topic(user_id, workspace_id, "Pets")
    item = create_teacher_topic_item(user_id, workspace_id, int(topic["id"]), "cat")
    topics = list_teacher_workspace_topics(user_id, workspace_id)
    snapshot = build_teacher_topic_editor_snapshot(user_id, workspace_id, int(topic["id"]))

    assert item["learning_item_id"] > 0
    assert topics == [{"id": topic["id"], "name": "pets", "title": "Pets", "item_count": 1}]
    assert snapshot["workspace_name"] == "Home"
    assert snapshot["item_count"] == 1
    assert snapshot["current_item"]["headword"] == "cat"


def test_topic_editor_snapshot_paginates_and_wraps_inside_family_topic(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user_id, family_id = seed_family_user(301)
    workspace_id = family_id
    topic = create_teacher_topic(user_id, workspace_id, "Long topic")
    item_ids: list[int] = []
    for index in range(27):
        item = create_teacher_topic_item(user_id, workspace_id, int(topic["id"]), f"item-{index + 1}")
        item_ids.append(int(item["learning_item_id"]))

    snapshot = build_teacher_topic_editor_snapshot(
        user_id,
        workspace_id,
        int(topic["id"]),
        selected_item_id=item_ids[26],
    )

    assert snapshot["page"] == 1
    assert snapshot["page_count"] == 2
    assert len(snapshot["navigator_items"]) == 2
    assert snapshot["navigator_items"][1]["is_selected"] is True
    assert snapshot["prev_item_id"] == item_ids[25]
    assert snapshot["next_item_id"] == item_ids[0]


def test_field_editing_updates_text_translation_and_audio(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user_id, family_id = seed_family_user(401)
    workspace_id = family_id
    topic = create_teacher_topic(user_id, workspace_id, "Fruits")
    item_id = int(create_teacher_topic_item(user_id, workspace_id, int(topic["id"]), "apple")["learning_item_id"])

    update_teacher_topic_item_field(user_id, workspace_id, int(topic["id"]), item_id, "text", "pear")
    update_teacher_topic_item_field(user_id, workspace_id, int(topic["id"]), item_id, "bg", "круша")
    update_teacher_topic_item_field(user_id, workspace_id, int(topic["id"]), item_id, "audio_ref", "audio://pear.mp3")

    learning_item = get_learning_item(item_id)
    translations = {row["language_code"]: row["translation_text"] for row in list_learning_item_translations(item_id)}
    snapshot = build_teacher_topic_editor_snapshot(user_id, workspace_id, int(topic["id"]), selected_item_id=item_id)

    assert learning_item is not None
    assert learning_item["text"] == "pear"
    assert translations["bg"] == "круша"
    assert snapshot["current_item"]["headword"] == "pear"
    assert snapshot["current_item"]["translations"]["bg"] == "круша"
    assert snapshot["current_item"]["audio_ref"] == "audio://pear.mp3"


def test_archive_hides_item_and_reselects_remaining_family_item(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user_id, family_id = seed_family_user(402)
    workspace_id = family_id
    topic = create_teacher_topic(user_id, workspace_id, "Fruits")
    first_item_id = int(create_teacher_topic_item(user_id, workspace_id, int(topic["id"]), "apple")["learning_item_id"])
    second_item_id = int(create_teacher_topic_item(user_id, workspace_id, int(topic["id"]), "pear")["learning_item_id"])

    archive_teacher_topic_item(user_id, workspace_id, int(topic["id"]), first_item_id)
    snapshot = build_teacher_topic_editor_snapshot(user_id, workspace_id, int(topic["id"]))

    assert snapshot["item_count"] == 1
    assert snapshot["selected_item_id"] == second_item_id


def test_topic_full_list_overview_returns_compact_family_rows(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user_id, family_id = seed_family_user(403)
    workspace_id = family_id
    topic = create_teacher_topic(user_id, workspace_id, "Fruits")
    first_item_id = int(create_teacher_topic_item(user_id, workspace_id, int(topic["id"]), "apple")["learning_item_id"])
    second_item_id = int(create_teacher_topic_item(user_id, workspace_id, int(topic["id"]), "pear")["learning_item_id"])
    update_teacher_topic_item_field(user_id, workspace_id, int(topic["id"]), first_item_id, "image_ref", "assets/images/apple.png")
    update_teacher_topic_item_field(user_id, workspace_id, int(topic["id"]), second_item_id, "audio_ref", "audio://pear.mp3")

    overview = build_teacher_topic_full_list_overview(user_id, workspace_id, int(topic["id"]))

    assert overview == {
        "topic_title": "Fruits",
        "item_count": 2,
        "rows": [
            {"headword": "apple", "has_image": True},
            {"headword": "pear", "has_image": False},
        ],
    }


def test_teacher_content_access_rejects_users_outside_family(tmp_path: Path) -> None:
    setup_db(tmp_path)
    owner_id, family_id = seed_family_user(601)
    workspace_id = family_id
    topic = create_teacher_topic(owner_id, workspace_id, "Fruits")
    item_id = int(create_teacher_topic_item(owner_id, workspace_id, int(topic["id"]), "apple")["learning_item_id"])
    outsider = type("User", (), {
        "id": 602,
        "username": "outsider",
        "first_name": "Outsider",
        "last_name": None,
    })()
    db.save_user(outsider)

    with pytest.raises(TeacherContentAccessError):
        list_teacher_workspace_topics(602, workspace_id)

    with pytest.raises(TeacherContentAccessError):
        build_teacher_topic_editor_snapshot(602, workspace_id, int(topic["id"]))

    with pytest.raises(TeacherContentAccessError):
        update_teacher_topic_item_field(602, workspace_id, int(topic["id"]), item_id, "ru", "яблоко")
