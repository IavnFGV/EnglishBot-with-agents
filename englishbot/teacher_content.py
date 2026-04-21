import math
import re

from .db import get_connection, utc_now
from .topics import (
    create_topic_for_teacher_workspace,
    get_learning_items_for_topic,
    get_topic,
    get_topic_by_name,
    list_topics,
    link_learning_item_to_topic,
    publish_topic_to_workspace,
)
from .vocabulary import (
    archive_learning_item,
    create_learning_item_for_teacher_workspace,
    create_lexeme,
    get_learning_item,
    get_lexeme,
    list_learning_item_translations,
    update_learning_item,
    upsert_learning_item_translation,
)
from .workspaces import (
    ROLE_TEACHER,
    WORKSPACE_KIND_STUDENT,
    WorkspaceEditPermissionError,
    WorkspaceKindMismatchError,
    WorkspaceNotFoundError,
    add_workspace_member,
    create_workspace,
    ensure_teacher_can_edit_workspace_content,
    find_workspaces_for_user_by_role,
    get_workspace,
)

EDITOR_PAGE_SIZE = 25
TRANSLATION_LANGUAGE_CODES = ("ru", "uk", "bg")


class TeacherContentAccessError(Exception):
    pass


class TeacherContentPublishTargetError(Exception):
    pass


def list_teacher_browsable_workspaces(teacher_user_id: int) -> list[dict[str, object]]:
    workspaces = find_workspaces_for_user_by_role(teacher_user_id, ROLE_TEACHER)
    return [
        {
            "id": int(workspace["id"]),
            "name": workspace["name"] or f"Workspace {int(workspace['id'])}",
        }
        for workspace in workspaces
        if str(workspace["kind"]) == ROLE_TEACHER
    ]


def create_teacher_workspace_for_user(
    teacher_user_id: int,
    name: str,
) -> dict[str, object]:
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("workspace name is required")
    workspace = create_workspace(normalized_name, kind=ROLE_TEACHER)
    add_workspace_member(int(workspace["workspace_id"]), teacher_user_id, ROLE_TEACHER)
    return {
        "id": int(workspace["workspace_id"]),
        "name": workspace["name"] or normalized_name,
    }


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


def create_teacher_topic(
    teacher_user_id: int,
    workspace_id: int,
    title: str,
) -> dict[str, object]:
    workspace = _ensure_teacher_workspace_access(teacher_user_id, workspace_id)
    normalized_title = title.strip()
    if not normalized_title:
        raise ValueError("topic title is required")
    topic_name = _build_unique_topic_name(workspace_id, normalized_title)
    topic_id = create_topic_for_teacher_workspace(
        teacher_user_id,
        workspace_id,
        topic_name,
        normalized_title,
    )
    return {
        "id": topic_id,
        "name": topic_name,
        "title": normalized_title,
        "workspace_id": int(workspace["id"]),
        "workspace_name": workspace["name"] or f"Workspace {int(workspace['id'])}",
    }


def build_teacher_topic_editor_snapshot(
    teacher_user_id: int,
    workspace_id: int,
    topic_id: int,
    *,
    selected_item_id: int | None = None,
    page: int = 0,
) -> dict[str, object]:
    workspace, topic = _ensure_teacher_topic_access(teacher_user_id, workspace_id, topic_id)
    all_learning_items = get_learning_items_for_topic(topic_id, include_archived=True)
    learning_items = get_learning_items_for_topic(topic_id)
    item_ids = [int(learning_item["id"]) for learning_item in learning_items]
    item_count = len(learning_items)

    if item_count == 0:
        clamped_page = 0
        selected_index = None
        selected_item = None
    else:
        if selected_item_id is not None and selected_item_id in item_ids:
            selected_index = item_ids.index(selected_item_id)
            clamped_page = selected_index // EDITOR_PAGE_SIZE
        else:
            resolved_selected_item_id = None
            if selected_item_id is not None:
                all_item_ids = [int(learning_item["id"]) for learning_item in all_learning_items]
                if selected_item_id in all_item_ids:
                    archived_index = all_item_ids.index(selected_item_id)
                    for candidate_id in all_item_ids[archived_index + 1:]:
                        if candidate_id in item_ids:
                            resolved_selected_item_id = candidate_id
                            break
                    if resolved_selected_item_id is None:
                        for candidate_id in reversed(all_item_ids[:archived_index]):
                            if candidate_id in item_ids:
                                resolved_selected_item_id = candidate_id
                                break
            if resolved_selected_item_id is not None:
                selected_index = item_ids.index(resolved_selected_item_id)
                clamped_page = selected_index // EDITOR_PAGE_SIZE
            else:
                page_count = math.ceil(item_count / EDITOR_PAGE_SIZE)
                clamped_page = min(max(page, 0), max(page_count - 1, 0))
                selected_index = min(clamped_page * EDITOR_PAGE_SIZE, item_count - 1)
        selected_item = learning_items[selected_index]

    page_count = max(math.ceil(item_count / EDITOR_PAGE_SIZE), 1)
    page_start = clamped_page * EDITOR_PAGE_SIZE
    page_items = learning_items[page_start:page_start + EDITOR_PAGE_SIZE]
    current_item = (
        _build_editor_current_item(selected_item)
        if selected_item is not None
        else None
    )

    return {
        "workspace_id": int(workspace["id"]),
        "workspace_name": workspace["name"] or f"Workspace {int(workspace['id'])}",
        "topic_id": int(topic["id"]),
        "topic_title": topic["title"],
        "topic_name": topic["name"],
        "page": clamped_page,
        "page_count": page_count,
        "item_count": item_count,
        "selected_item_id": int(selected_item["id"]) if selected_item is not None else None,
        "selected_item_index": selected_index,
        "navigator_items": [
            {
                "id": int(learning_item["id"]),
                "label": _build_item_label(learning_item),
                "is_selected": (
                    selected_item is not None
                    and int(learning_item["id"]) == int(selected_item["id"])
                ),
            }
            for learning_item in page_items
        ],
        "current_item": current_item,
        "has_prev_page": clamped_page > 0,
        "has_next_page": clamped_page + 1 < page_count,
        "prev_item_id": (
            item_ids[selected_index - 1]
            if selected_index is not None and selected_index > 0
            else None
        ),
        "next_item_id": (
            item_ids[selected_index + 1]
            if selected_index is not None and selected_index + 1 < item_count
            else None
        ),
    }


def create_teacher_topic_item(
    teacher_user_id: int,
    workspace_id: int,
    topic_id: int,
    text: str,
) -> dict[str, int]:
    _, topic = _ensure_teacher_topic_access(teacher_user_id, workspace_id, topic_id)
    normalized_text = text.strip()
    if not normalized_text:
        raise ValueError("item text is required")
    lexeme_id = create_lexeme(normalized_text)
    learning_item_id = create_learning_item_for_teacher_workspace(
        teacher_user_id,
        int(topic["workspace_id"]),
        lexeme_id,
        normalized_text,
    )
    link_learning_item_to_topic(topic_id, learning_item_id)
    return {"learning_item_id": learning_item_id}


def update_teacher_topic_item_field(
    teacher_user_id: int,
    workspace_id: int,
    topic_id: int,
    learning_item_id: int,
    field_name: str,
    value: str,
) -> None:
    learning_item = _ensure_teacher_topic_item_access(
        teacher_user_id,
        workspace_id,
        topic_id,
        learning_item_id,
    )
    normalized_value = value.strip()
    if not normalized_value:
        raise ValueError("field value is required")
    if field_name == "text":
        update_learning_item(
            teacher_user_id,
            learning_item_id,
            text=normalized_value,
        )
        with get_connection() as connection:
            connection.execute(
                """
                UPDATE lexemes
                SET lemma = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    normalized_value,
                    utc_now(),
                    int(learning_item["lexeme_id"]),
                ),
            )
        return
    if field_name in TRANSLATION_LANGUAGE_CODES:
        upsert_learning_item_translation(
            teacher_user_id,
            learning_item_id,
            field_name,
            normalized_value,
        )
        return
    if field_name in {"image_ref", "audio_ref"}:
        update_learning_item(
            teacher_user_id,
            learning_item_id,
            **{field_name: normalized_value},
        )
        return
    raise ValueError(f"unsupported field: {field_name}")


def update_teacher_topic_item_image_ref(
    teacher_user_id: int,
    workspace_id: int,
    topic_id: int,
    learning_item_id: int,
    image_ref: str,
) -> None:
    update_teacher_topic_item_field(
        teacher_user_id,
        workspace_id,
        topic_id,
        learning_item_id,
        "image_ref",
        image_ref,
    )


def archive_teacher_topic_item(
    teacher_user_id: int,
    workspace_id: int,
    topic_id: int,
    learning_item_id: int,
) -> None:
    _ensure_teacher_topic_item_access(
        teacher_user_id,
        workspace_id,
        topic_id,
        learning_item_id,
    )
    archive_learning_item(teacher_user_id, learning_item_id)


def list_teacher_publish_targets(teacher_user_id: int) -> list[dict[str, object]]:
    workspaces = find_workspaces_for_user_by_role(teacher_user_id, ROLE_TEACHER)
    return [
        {
            "id": int(workspace["id"]),
            "name": workspace["name"] or f"Workspace {int(workspace['id'])}",
        }
        for workspace in workspaces
        if str(workspace["kind"]) == WORKSPACE_KIND_STUDENT
    ]


def publish_teacher_topic_to_workspace(
    teacher_user_id: int,
    workspace_id: int,
    topic_id: int,
    target_workspace_id: int,
) -> dict[str, object]:
    _, topic = _ensure_teacher_topic_access(teacher_user_id, workspace_id, topic_id)
    target_workspace = get_workspace(target_workspace_id)
    if target_workspace is None or str(target_workspace["kind"]) != WORKSPACE_KIND_STUDENT:
        raise TeacherContentPublishTargetError
    if target_workspace_id not in {
        int(workspace["id"]) for workspace in list_teacher_publish_targets(teacher_user_id)
    }:
        raise TeacherContentPublishTargetError
    result = publish_topic_to_workspace(int(topic["id"]), target_workspace_id)
    return {
        "target_workspace_id": target_workspace_id,
        "target_workspace_name": target_workspace["name"] or f"Workspace {target_workspace_id}",
        "topic_id": int(result["topic_id"]),
        "topic_title": str(result["title"]),
        "learning_item_count": len(result["learning_item_ids"]),
    }


def get_teacher_topic_preview(
    teacher_user_id: int,
    workspace_id: int,
    topic_id: int,
) -> dict[str, object]:
    snapshot = build_teacher_topic_editor_snapshot(
        teacher_user_id,
        workspace_id,
        topic_id,
    )
    items: list[dict[str, object]] = []
    for navigator_item in snapshot["navigator_items"]:
        learning_item = get_learning_item(int(navigator_item["id"]))
        if learning_item is None:
            continue
        current_item = _build_editor_current_item(learning_item)
        items.append(
            {
                "headword": current_item["headword"],
                "translations": [
                    current_item["translations"][language_code]
                    for language_code in TRANSLATION_LANGUAGE_CODES
                    if current_item["translations"][language_code]
                ],
                "image_ref": current_item["image_ref"],
                "audio_ref": current_item["audio_ref"],
            }
        )
    return {
        "workspace_id": snapshot["workspace_id"],
        "workspace_name": snapshot["workspace_name"],
        "topic_id": snapshot["topic_id"],
        "topic_title": snapshot["topic_title"],
        "topic_name": snapshot["topic_name"],
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


def _ensure_teacher_topic_access(
    teacher_user_id: int,
    workspace_id: int,
    topic_id: int,
):
    workspace = _ensure_teacher_workspace_access(teacher_user_id, workspace_id)
    topic = get_topic(topic_id)
    if topic is None or int(topic["workspace_id"]) != workspace_id:
        raise TeacherContentAccessError
    return workspace, topic


def _ensure_teacher_topic_item_access(
    teacher_user_id: int,
    workspace_id: int,
    topic_id: int,
    learning_item_id: int,
):
    _, topic = _ensure_teacher_topic_access(teacher_user_id, workspace_id, topic_id)
    learning_item = get_learning_item(learning_item_id)
    if learning_item is None or int(learning_item["workspace_id"]) != workspace_id:
        raise TeacherContentAccessError
    topic_item_ids = {
        int(item["id"])
        for item in get_learning_items_for_topic(int(topic["id"]))
    }
    if learning_item_id not in topic_item_ids:
        raise TeacherContentAccessError
    return learning_item


def _build_unique_topic_name(workspace_id: int, title: str) -> str:
    base_name = re.sub(r"[^a-z0-9]+", "-", title.strip().lower()).strip("-")
    if not base_name:
        base_name = "topic"
    candidate = base_name
    suffix = 2
    while get_topic_by_name(candidate, workspace_id=workspace_id, include_archived=True) is not None:
        candidate = f"{base_name}-{suffix}"
        suffix += 1
    return candidate


def _build_editor_current_item(learning_item) -> dict[str, object]:
    lexeme = get_lexeme(int(learning_item["lexeme_id"]))
    translations_by_language = {
        language_code: ""
        for language_code in TRANSLATION_LANGUAGE_CODES
    }
    for translation in list_learning_item_translations(int(learning_item["id"])):
        language_code = str(translation["language_code"])
        if language_code in translations_by_language and not translations_by_language[language_code]:
            translations_by_language[language_code] = str(translation["translation_text"])
    return {
        "id": int(learning_item["id"]),
        "headword": (
            str(lexeme["lemma"])
            if lexeme is not None and lexeme["lemma"] is not None
            else str(learning_item["text"])
        ),
        "text": str(learning_item["text"]),
        "translations": translations_by_language,
        "image_ref": (
            str(learning_item["image_ref"])
            if learning_item["image_ref"] is not None
            else None
        ),
        "audio_ref": (
            str(learning_item["audio_ref"])
            if learning_item["audio_ref"] is not None
            else None
        ),
        "is_archived": bool(learning_item["is_archived"]),
    }


def _build_item_label(learning_item) -> str:
    lexeme = get_lexeme(int(learning_item["lexeme_id"]))
    if lexeme is not None and lexeme["lemma"]:
        return str(lexeme["lemma"])
    return str(learning_item["text"])
