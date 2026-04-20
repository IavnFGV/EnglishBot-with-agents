import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.teacher_content import (
    TeacherContentAccessError,
    get_teacher_topic_preview,
    list_teacher_browsable_workspaces,
    list_teacher_workspace_topics,
)
from englishbot.topics import archive_topic, create_topic_for_teacher_workspace, link_learning_item_to_topic
from englishbot.vocabulary import (
    create_learning_item_for_teacher_workspace,
    create_learning_item_translation,
    create_lexeme,
)
from englishbot.workspaces import add_workspace_member, create_workspace


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "teacher_content.sqlite3"
    db.init_db()


def seed_topic_with_item(
    teacher_user_id: int,
    workspace_id: int,
    *,
    lemma: str = "apple",
    title: str = "Fruits",
    topic_name: str = "fruits",
    image_ref: str | None = None,
    audio_ref: str | None = None,
) -> int:
    lexeme_id = create_lexeme(lemma)
    learning_item_id = create_learning_item_for_teacher_workspace(
        teacher_user_id,
        workspace_id,
        lexeme_id,
        lemma,
        image_ref=image_ref,
        audio_ref=audio_ref,
    )
    create_learning_item_translation(learning_item_id, "ru", "яблоко")
    create_learning_item_translation(learning_item_id, "uk", "яблуко")
    topic_id = create_topic_for_teacher_workspace(
        teacher_user_id,
        workspace_id,
        topic_name,
        title,
    )
    link_learning_item_to_topic(topic_id, learning_item_id)
    return topic_id


def test_list_teacher_browsable_workspaces_returns_only_teacher_kind_workspaces_for_teacher_member(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    teacher_workspace = create_workspace("Authoring", kind="teacher")
    student_workspace = create_workspace("Runtime", kind="student")
    add_workspace_member(teacher_workspace["workspace_id"], 101, "teacher")
    add_workspace_member(student_workspace["workspace_id"], 101, "teacher")

    workspaces = list_teacher_browsable_workspaces(101)

    assert workspaces == [{"id": teacher_workspace["workspace_id"], "name": "Authoring"}]


def test_list_teacher_workspace_topics_denies_non_member_or_wrong_role_access(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    workspace = create_workspace("Authoring", kind="teacher")
    add_workspace_member(workspace["workspace_id"], 201, "teacher")
    add_workspace_member(workspace["workspace_id"], 202, "student")
    seed_topic_with_item(201, workspace["workspace_id"])

    with pytest.raises(TeacherContentAccessError):
        list_teacher_workspace_topics(202, workspace["workspace_id"])

    with pytest.raises(TeacherContentAccessError):
        list_teacher_workspace_topics(203, workspace["workspace_id"])


def test_list_teacher_workspace_topics_returns_non_archived_topics_for_authorized_teacher(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    workspace = create_workspace("Authoring", kind="teacher")
    add_workspace_member(workspace["workspace_id"], 301, "teacher")
    visible_topic_id = seed_topic_with_item(
        301,
        workspace["workspace_id"],
        lemma="apple",
        title="Visible",
        topic_name="visible",
    )
    archived_topic_id = seed_topic_with_item(
        301,
        workspace["workspace_id"],
        lemma="pear",
        title="Archived",
        topic_name="archived",
    )
    archive_topic(301, archived_topic_id)

    topics = list_teacher_workspace_topics(301, workspace["workspace_id"])

    assert topics == [
        {
            "id": visible_topic_id,
            "name": "visible",
            "title": "Visible",
            "item_count": 1,
        }
    ]


def test_get_teacher_topic_preview_returns_headword_translations_and_optional_asset_refs(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    workspace = create_workspace("Authoring", kind="teacher")
    add_workspace_member(workspace["workspace_id"], 401, "teacher")
    topic_id = seed_topic_with_item(
        401,
        workspace["workspace_id"],
        image_ref="img://apple",
        audio_ref="audio://apple",
    )

    preview = get_teacher_topic_preview(401, workspace["workspace_id"], topic_id)

    assert preview["topic_title"] == "Fruits"
    assert preview["items"] == [
        {
            "headword": "apple",
            "translations": ["яблоко", "яблуко"],
            "image_ref": "img://apple",
            "audio_ref": "audio://apple",
        }
    ]


def test_get_teacher_topic_preview_rejects_topic_from_other_workspace_even_if_topic_id_exists(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    first_workspace = create_workspace("Authoring A", kind="teacher")
    second_workspace = create_workspace("Authoring B", kind="teacher")
    add_workspace_member(first_workspace["workspace_id"], 501, "teacher")
    add_workspace_member(second_workspace["workspace_id"], 501, "teacher")
    topic_id = seed_topic_with_item(501, second_workspace["workspace_id"])

    with pytest.raises(TeacherContentAccessError):
        get_teacher_topic_preview(501, first_workspace["workspace_id"], topic_id)
