import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.teacher_content import (
    TeacherContentAccessError,
    build_teacher_topic_editor_snapshot,
    create_teacher_topic,
    create_teacher_topic_item,
    create_teacher_workspace_for_user,
    list_teacher_browsable_workspaces,
    list_teacher_publish_targets,
    list_teacher_workspace_topics,
    publish_teacher_topic_to_workspace,
    update_teacher_topic_item_field,
    archive_teacher_topic_item,
)
from englishbot.vocabulary import get_learning_item, list_learning_item_translations
from englishbot.workspaces import add_workspace_member, create_workspace


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "teacher_content.sqlite3"
    db.init_db()


def seed_workspace_with_topic(
    teacher_user_id: int,
    *,
    workspace_name: str = "Authoring",
    topic_title: str = "Fruits",
    item_count: int = 1,
) -> tuple[int, int, list[int]]:
    workspace = create_workspace(workspace_name, kind="teacher")
    add_workspace_member(workspace["workspace_id"], teacher_user_id, "teacher")
    topic = create_teacher_topic(teacher_user_id, int(workspace["workspace_id"]), topic_title)
    item_ids: list[int] = []
    for index in range(item_count):
        item = create_teacher_topic_item(
            teacher_user_id,
            int(workspace["workspace_id"]),
            int(topic["id"]),
            f"item-{index + 1}",
        )
        item_ids.append(int(item["learning_item_id"]))
    return int(workspace["workspace_id"]), int(topic["id"]), item_ids


def test_teacher_content_workspace_listing_and_creation(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher_workspace = create_workspace("Authoring", kind="teacher")
    student_workspace = create_workspace("Runtime", kind="student")
    add_workspace_member(teacher_workspace["workspace_id"], 101, "teacher")
    add_workspace_member(student_workspace["workspace_id"], 101, "teacher")

    created = create_teacher_workspace_for_user(101, "New Authoring")
    workspaces = list_teacher_browsable_workspaces(101)

    assert created["name"] == "New Authoring"
    assert workspaces == [
        {"id": teacher_workspace["workspace_id"], "name": "Authoring"},
        {"id": created["id"], "name": "New Authoring"},
    ]


def test_teacher_can_browse_and_create_topics(tmp_path: Path) -> None:
    setup_db(tmp_path)
    workspace = create_workspace("Authoring", kind="teacher")
    add_workspace_member(workspace["workspace_id"], 201, "teacher")

    created = create_teacher_topic(201, int(workspace["workspace_id"]), "My New Topic")
    topics = list_teacher_workspace_topics(201, int(workspace["workspace_id"]))

    assert created["name"] == "my-new-topic"
    assert topics == [
        {
            "id": created["id"],
            "name": "my-new-topic",
            "title": "My New Topic",
            "item_count": 0,
        }
    ]


def test_topic_editor_snapshot_paginates_and_marks_selected_item(tmp_path: Path) -> None:
    setup_db(tmp_path)
    workspace_id, topic_id, item_ids = seed_workspace_with_topic(301, item_count=27)

    snapshot = build_teacher_topic_editor_snapshot(
        301,
        workspace_id,
        topic_id,
        selected_item_id=item_ids[26],
    )

    assert snapshot["page"] == 1
    assert snapshot["page_count"] == 2
    assert len(snapshot["navigator_items"]) == 2
    assert snapshot["navigator_items"][1]["is_selected"] is True
    assert snapshot["selected_item_id"] == item_ids[26]


def test_topic_editor_snapshot_uses_db_truth_when_selected_item_becomes_archived(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    workspace_id, topic_id, item_ids = seed_workspace_with_topic(302, item_count=3)
    archive_teacher_topic_item(302, workspace_id, topic_id, item_ids[1])

    snapshot = build_teacher_topic_editor_snapshot(
        302,
        workspace_id,
        topic_id,
        selected_item_id=item_ids[1],
        page=1,
    )

    assert snapshot["selected_item_id"] == item_ids[2]
    assert snapshot["item_count"] == 2
    assert snapshot["page"] == 0


def test_field_editing_updates_text_and_adds_missing_translation(tmp_path: Path) -> None:
    setup_db(tmp_path)
    workspace_id, topic_id, item_ids = seed_workspace_with_topic(401)

    update_teacher_topic_item_field(401, workspace_id, topic_id, item_ids[0], "text", "apple")
    update_teacher_topic_item_field(401, workspace_id, topic_id, item_ids[0], "bg", "ябълка")

    learning_item = get_learning_item(item_ids[0])
    translations = {
        row["language_code"]: row["translation_text"]
        for row in list_learning_item_translations(item_ids[0])
    }
    snapshot = build_teacher_topic_editor_snapshot(
        401,
        workspace_id,
        topic_id,
        selected_item_id=item_ids[0],
    )

    assert learning_item is not None
    assert learning_item["text"] == "apple"
    assert translations["bg"] == "ябълка"
    assert snapshot["current_item"]["headword"] == "apple"
    assert snapshot["current_item"]["translations"]["bg"] == "ябълка"


def test_archive_action_hides_item_and_reselects_remaining_item(tmp_path: Path) -> None:
    setup_db(tmp_path)
    workspace_id, topic_id, item_ids = seed_workspace_with_topic(402, item_count=2)

    archive_teacher_topic_item(402, workspace_id, topic_id, item_ids[0])
    snapshot = build_teacher_topic_editor_snapshot(402, workspace_id, topic_id)

    assert snapshot["item_count"] == 1
    assert snapshot["selected_item_id"] == item_ids[1]


def test_publish_reuses_existing_topic_publish_logic(tmp_path: Path) -> None:
    setup_db(tmp_path)
    workspace_id, topic_id, item_ids = seed_workspace_with_topic(501, item_count=2)
    student_workspace = create_workspace("Runtime", kind="student")
    add_workspace_member(student_workspace["workspace_id"], 501, "teacher")

    targets = list_teacher_publish_targets(501)
    result = publish_teacher_topic_to_workspace(
        501,
        workspace_id,
        topic_id,
        int(student_workspace["workspace_id"]),
    )

    assert targets == [{"id": student_workspace["workspace_id"], "name": "Runtime"}]
    assert result["target_workspace_id"] == student_workspace["workspace_id"]
    assert result["learning_item_count"] == len(item_ids)


def test_teacher_content_access_rejects_unauthorized_browsing_and_editing(tmp_path: Path) -> None:
    setup_db(tmp_path)
    workspace_id, topic_id, item_ids = seed_workspace_with_topic(601)

    with pytest.raises(TeacherContentAccessError):
        list_teacher_workspace_topics(602, workspace_id)

    with pytest.raises(TeacherContentAccessError):
        build_teacher_topic_editor_snapshot(602, workspace_id, topic_id)

    with pytest.raises(TeacherContentAccessError):
        update_teacher_topic_item_field(602, workspace_id, topic_id, item_ids[0], "ru", "яблоко")
