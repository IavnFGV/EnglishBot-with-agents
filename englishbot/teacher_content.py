from .topics import get_learning_items_for_topic, get_topic, list_topics
from .vocabulary import get_lexeme, list_learning_item_translations
from .workspaces import (
    WorkspaceEditPermissionError,
    WorkspaceKindMismatchError,
    WorkspaceNotFoundError,
    ensure_teacher_can_edit_workspace_content,
    find_workspaces_for_user_by_role,
)


class TeacherContentAccessError(Exception):
    pass


def list_teacher_browsable_workspaces(teacher_user_id: int) -> list[dict[str, object]]:
    workspaces = find_workspaces_for_user_by_role(teacher_user_id, "teacher")
    return [
        {
            "id": int(workspace["id"]),
            "name": workspace["name"],
        }
        for workspace in workspaces
        if str(workspace["kind"]) == "teacher"
    ]


def list_teacher_workspace_topics(
    teacher_user_id: int,
    workspace_id: int,
) -> list[dict[str, object]]:
    _ensure_teacher_workspace_access(teacher_user_id, workspace_id)
    return [
        {
            "id": int(topic["id"]),
            "name": topic["name"],
            "title": topic["title"],
            "item_count": int(topic["item_count"]),
        }
        for topic in list_topics(workspace_id)
    ]


def get_teacher_topic_preview(
    teacher_user_id: int,
    workspace_id: int,
    topic_id: int,
) -> dict[str, object]:
    workspace = _ensure_teacher_workspace_access(teacher_user_id, workspace_id)
    topic = get_topic(topic_id)
    if topic is None or int(topic["workspace_id"]) != workspace_id:
        raise TeacherContentAccessError

    items: list[dict[str, object]] = []
    for learning_item in get_learning_items_for_topic(topic_id):
        lexeme = get_lexeme(int(learning_item["lexeme_id"]))
        translations = list_learning_item_translations(int(learning_item["id"]))
        items.append(
            {
                "headword": (
                    str(lexeme["lemma"])
                    if lexeme is not None and lexeme["lemma"] is not None
                    else str(learning_item["text"])
                ),
                "translations": [
                    str(translation["translation_text"])
                    for translation in translations
                ],
                "image_ref": learning_item["image_ref"],
                "audio_ref": learning_item["audio_ref"],
            }
        )

    return {
        "workspace_id": int(workspace["id"]),
        "workspace_name": workspace["name"],
        "topic_id": int(topic["id"]),
        "topic_title": topic["title"],
        "topic_name": topic["name"],
        "items": items,
    }


def _ensure_teacher_workspace_access(teacher_user_id: int, workspace_id: int):
    try:
        return ensure_teacher_can_edit_workspace_content(workspace_id, teacher_user_id)
    except (
        WorkspaceEditPermissionError,
        WorkspaceKindMismatchError,
        WorkspaceNotFoundError,
    ):
        raise TeacherContentAccessError from None
