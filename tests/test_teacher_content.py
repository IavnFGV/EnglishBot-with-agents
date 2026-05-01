import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.teacher_content import (
    TeacherContentAccessError,
    build_teacher_topic_editor_snapshot,
    build_teacher_topic_full_list_overview,
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


def test_topic_editor_snapshot_adds_visible_item_window_and_show_all_threshold(tmp_path: Path) -> None:
    setup_db(tmp_path)
    workspace_id, topic_id, item_ids = seed_workspace_with_topic(303, item_count=11)

    snapshot = build_teacher_topic_editor_snapshot(
        303,
        workspace_id,
        topic_id,
        selected_item_id=item_ids[5],
    )
    short_snapshot = build_teacher_topic_editor_snapshot(
        303,
        workspace_id,
        topic_id,
        selected_item_id=item_ids[0],
        page=0,
    )

    assert snapshot["show_all_available"] is True
    assert snapshot["visible_items"] == [
        {"position": 1, "headword": "item-1", "has_image": False, "is_selected": False},
        {"position": 2, "headword": "item-2", "has_image": False, "is_selected": False},
        {"position": 3, "headword": "item-3", "has_image": False, "is_selected": False},
        {"position": 4, "headword": "item-4", "has_image": False, "is_selected": False},
        {"position": 5, "headword": "item-5", "has_image": False, "is_selected": False},
        {"position": 6, "headword": "item-6", "has_image": False, "is_selected": True},
        {"position": 7, "headword": "item-7", "has_image": False, "is_selected": False},
        {"position": 8, "headword": "item-8", "has_image": False, "is_selected": False},
        {"position": 9, "headword": "item-9", "has_image": False, "is_selected": False},
        {"position": 10, "headword": "item-10", "has_image": False, "is_selected": False},
    ]
    assert short_snapshot["visible_items"] == [
        {"position": 7, "headword": "item-7", "has_image": False, "is_selected": False},
        {"position": 8, "headword": "item-8", "has_image": False, "is_selected": False},
        {"position": 9, "headword": "item-9", "has_image": False, "is_selected": False},
        {"position": 10, "headword": "item-10", "has_image": False, "is_selected": False},
        {"position": 11, "headword": "item-11", "has_image": False, "is_selected": False},
        {"position": 1, "headword": "item-1", "has_image": False, "is_selected": True},
        {"position": 2, "headword": "item-2", "has_image": False, "is_selected": False},
        {"position": 3, "headword": "item-3", "has_image": False, "is_selected": False},
        {"position": 4, "headword": "item-4", "has_image": False, "is_selected": False},
        {"position": 5, "headword": "item-5", "has_image": False, "is_selected": False},
    ]
    assert short_snapshot["show_all_available"] is True


def test_topic_editor_snapshot_wraps_prev_and_next_item_ids(tmp_path: Path) -> None:
    setup_db(tmp_path)
    workspace_id, topic_id, item_ids = seed_workspace_with_topic(305, item_count=3)

    first_snapshot = build_teacher_topic_editor_snapshot(
        305,
        workspace_id,
        topic_id,
        selected_item_id=item_ids[0],
    )
    last_snapshot = build_teacher_topic_editor_snapshot(
        305,
        workspace_id,
        topic_id,
        selected_item_id=item_ids[2],
    )

    assert first_snapshot["prev_item_id"] == item_ids[2]
    assert first_snapshot["next_item_id"] == item_ids[1]
    assert last_snapshot["prev_item_id"] == item_ids[1]
    assert last_snapshot["next_item_id"] == item_ids[0]


def test_topic_editor_snapshot_hides_show_all_for_ten_or_fewer_items(tmp_path: Path) -> None:
    setup_db(tmp_path)
    workspace_id, topic_id, item_ids = seed_workspace_with_topic(304, item_count=10)

    snapshot = build_teacher_topic_editor_snapshot(
        304,
        workspace_id,
        topic_id,
        selected_item_id=item_ids[0],
    )

    assert snapshot["show_all_available"] is False


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
    update_teacher_topic_item_field(401, workspace_id, topic_id, item_ids[0], "audio_ref", "audio://apple.mp3")

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
    assert snapshot["current_item"]["audio_ref"] == "audio://apple.mp3"


def test_field_editing_remote_media_keeps_source_url_and_saves_local_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_db(tmp_path)
    workspace_id, topic_id, item_ids = seed_workspace_with_topic(402)
    stored_calls: list[tuple[str, str]] = []

    def fake_store_remote_asset(asset_type: str, source_url: str, **kwargs: object) -> str:
        stored_calls.append((asset_type, source_url))
        if asset_type == "image":
            return "assets/images/remote/item-image.jpg"
        return "assets/audio/remote/item-audio.mp3"

    monkeypatch.setattr(
        "englishbot.teacher_content.store_remote_asset",
        fake_store_remote_asset,
    )

    update_teacher_topic_item_field(
        402,
        workspace_id,
        topic_id,
        item_ids[0],
        "image_ref",
        "https://example.com/apple.jpg",
    )
    update_teacher_topic_item_field(
        402,
        workspace_id,
        topic_id,
        item_ids[0],
        "audio_ref",
        "https://example.com/apple.mp3",
    )

    learning_item = get_learning_item(item_ids[0])

    assert stored_calls == [
        ("image", "https://example.com/apple.jpg"),
        ("audio", "https://example.com/apple.mp3"),
    ]
    assert learning_item is not None
    assert learning_item["image_ref"] == "assets/images/remote/item-image.jpg"
    assert learning_item["audio_ref"] == "assets/audio/remote/item-audio.mp3"
    assert [
        (asset["asset_type"], asset["source_url"], asset["local_path"], asset["role"])
        for asset in learning_item["assets"]
    ] == [
        ("image", "https://example.com/apple.jpg", "assets/images/remote/item-image.jpg", "primary_image"),
        ("audio", "https://example.com/apple.mp3", "assets/audio/remote/item-audio.mp3", "primary_audio"),
    ]


def test_archive_action_hides_item_and_reselects_remaining_item(tmp_path: Path) -> None:
    setup_db(tmp_path)
    workspace_id, topic_id, item_ids = seed_workspace_with_topic(402, item_count=2)

    archive_teacher_topic_item(402, workspace_id, topic_id, item_ids[0])
    snapshot = build_teacher_topic_editor_snapshot(402, workspace_id, topic_id)

    assert snapshot["item_count"] == 1
    assert snapshot["selected_item_id"] == item_ids[1]


def test_topic_full_list_overview_returns_headwords_and_image_flags_only(tmp_path: Path) -> None:
    setup_db(tmp_path)
    workspace_id, topic_id, item_ids = seed_workspace_with_topic(403, item_count=2)
    update_teacher_topic_item_field(403, workspace_id, topic_id, item_ids[0], "ru", "яблоко")
    update_teacher_topic_item_field(403, workspace_id, topic_id, item_ids[0], "image_ref", "assets/images/apple.png")
    update_teacher_topic_item_field(403, workspace_id, topic_id, item_ids[1], "audio_ref", "audio://pear.mp3")

    overview = build_teacher_topic_full_list_overview(403, workspace_id, topic_id)

    assert overview == {
        "topic_title": "Fruits",
        "item_count": 2,
        "rows": [
            {"headword": "item-1", "has_image": True},
            {"headword": "item-2", "has_image": False},
        ],
    }


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
