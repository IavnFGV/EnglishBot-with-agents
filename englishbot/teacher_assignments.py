import sqlite3
from .families import (
    create_homework_assignment as create_family_homework_assignment,
    get_user_family,
    list_family_learning_items,
    list_family_members,
    list_family_topics,
)
from .db import get_connection, get_user
from .homework import (
    ASSIGNMENT_KIND_HOMEWORK,
    ASSIGNMENT_MODE_STAGED_DEFAULT,
    normalize_assignment_kind,
    normalize_assignment_mode,
)
from .topics import get_topic
from .vocabulary import get_learning_item, list_learning_item_translations, list_learning_items


SOURCE_MODE_TOPIC = "topic"
SOURCE_MODE_WORDS = "words"
SUMMARY_PREVIEW_LIMIT = 5
FAMILY_WORKSPACE_ID_OFFSET = 1_000_000_000


class TeacherAssignmentError(Exception):
    pass


class TeacherAssignmentAccessError(TeacherAssignmentError):
    pass


class TeacherAssignmentDraftError(TeacherAssignmentError):
    pass


class TeacherAssignmentRecipientsRequiredError(TeacherAssignmentDraftError):
    pass


def list_assignment_workspaces(teacher_user_id: int) -> list[dict[str, object]]:
    family = get_user_family(teacher_user_id)
    if family is None:
        return []
    family_id = int(family["id"])
    return [
        {
            "workspace_id": _family_workspace_id(family_id),
            "name": str(family["name"] or "Family"),
        }
    ]


def list_assignment_topics(
    teacher_user_id: int,
    workspace_id: int,
) -> list[dict[str, object]]:
    family_id = _workspace_family_id(workspace_id)
    family = get_user_family(teacher_user_id)
    if family is None or family_id != int(family["id"]):
        raise TeacherAssignmentAccessError
    return [
        {
            "topic_id": int(topic["id"]),
            "name": str(topic["name"]),
            "title": str(topic["title"]),
            "item_count": len(_get_family_topic_learning_item_ids(int(topic["id"]))),
        }
        for topic in list_family_topics(family_id)
    ]


def build_topic_selection_summary(
    teacher_user_id: int,
    workspace_id: int,
    topic_id: int,
) -> dict[str, object]:
    family_id = _workspace_family_id(workspace_id)
    family = get_user_family(teacher_user_id)
    if family is None or family_id != int(family["id"]):
        raise TeacherAssignmentDraftError
    topic = _get_family_topic(topic_id, family_id)
    if topic is None:
        raise TeacherAssignmentDraftError
    learning_item_ids = _get_family_topic_learning_item_ids(topic_id)
    preview_items = _build_learning_item_preview_rows(learning_item_ids[:SUMMARY_PREVIEW_LIMIT])
    return {
        "source_mode": SOURCE_MODE_TOPIC,
        "workspace_id": workspace_id,
        "workspace_name": str(family["name"]),
        "topic_id": topic_id,
        "topic_title": str(topic["title"]),
        "topic_name": str(topic["name"]),
        "learning_item_ids": learning_item_ids,
        "selected_count": len(learning_item_ids),
        "preview_items": preview_items,
    }


def build_word_selection_snapshot(
    teacher_user_id: int,
    workspace_id: int,
    selected_learning_item_ids: list[int],
    *,
    current_learning_item_id: int | None = None,
) -> dict[str, object]:
    family_id = _workspace_family_id(workspace_id)
    family = get_user_family(teacher_user_id)
    if family is None or family_id != int(family["id"]):
        raise TeacherAssignmentDraftError
    workspace = {"name": str(family["name"])}
    learning_items = [
        get_learning_item(int(item["id"]))
        for item in list_family_learning_items(family_id)
    ]
    learning_items = [item for item in learning_items if item is not None]
    if not learning_items:
        return {
            "workspace_id": workspace_id,
            "workspace_name": workspace["name"] or f"Workspace {workspace_id}",
            "item_count": 0,
            "current_item": None,
            "current_index": 0,
            "prev_item_id": None,
            "next_item_id": None,
            "selected_count": 0,
            "selected_learning_item_ids": [],
            "preview_items": [],
        }

    ordered_ids = [int(item["id"]) for item in learning_items]
    normalized_selected_ids = [
        learning_item_id
        for learning_item_id in selected_learning_item_ids
        if learning_item_id in ordered_ids
    ]
    if current_learning_item_id in ordered_ids:
        current_index = ordered_ids.index(int(current_learning_item_id))
    else:
        current_index = 0
    current_learning_item = learning_items[current_index]
    preview_items = _build_learning_item_preview_rows(normalized_selected_ids[:SUMMARY_PREVIEW_LIMIT])
    return {
        "workspace_id": workspace_id,
        "workspace_name": workspace["name"] or f"Workspace {workspace_id}",
        "item_count": len(learning_items),
        "current_item": _serialize_learning_item_card(current_learning_item),
        "current_index": current_index,
        "prev_item_id": ordered_ids[(current_index - 1) % len(ordered_ids)] if len(ordered_ids) > 1 else None,
        "next_item_id": ordered_ids[(current_index + 1) % len(ordered_ids)] if len(ordered_ids) > 1 else None,
        "selected_count": len(normalized_selected_ids),
        "selected_learning_item_ids": normalized_selected_ids,
        "preview_items": preview_items,
    }


def list_assignment_recipients(teacher_user_id: int) -> list[dict[str, object]]:
    family = get_user_family(teacher_user_id)
    if family is None:
        return []
    return [
        {
            "student_user_id": int(member["telegram_user_id"]),
            "display_name": _build_user_display_name(member, int(member["telegram_user_id"])),
            "workspace_id": None,
        }
        for member in list_family_members(int(family["id"]))
    ]


def build_assignment_confirm_snapshot(
    teacher_user_id: int,
    *,
    source_mode: str,
    workspace_id: int,
    topic_id: int | None,
    selected_learning_item_ids: list[int],
    recipient_user_ids: list[int],
    assignment_kind: str = ASSIGNMENT_KIND_HOMEWORK,
    assignment_mode: str = ASSIGNMENT_MODE_STAGED_DEFAULT,
) -> dict[str, object]:
    normalized_kind = normalize_assignment_kind(assignment_kind)
    normalized_mode = normalize_assignment_mode(assignment_mode)
    family_id = _workspace_family_id(workspace_id)
    family = get_user_family(teacher_user_id)
    if family is None or int(family["id"]) != family_id:
        raise TeacherAssignmentAccessError
    workspace_name = str(family["name"] or "Family")
    recipient_lookup = {
        recipient["student_user_id"]: recipient
        for recipient in list_assignment_recipients(teacher_user_id)
    }
    selected_recipients = [
        recipient_lookup[student_user_id]
        for student_user_id in recipient_user_ids
        if student_user_id in recipient_lookup
    ]
    content_summary: dict[str, object]
    if source_mode == SOURCE_MODE_TOPIC:
        if topic_id is None:
            raise TeacherAssignmentDraftError
        content_summary = build_topic_selection_summary(teacher_user_id, workspace_id, topic_id)
    elif source_mode == SOURCE_MODE_WORDS:
        snapshot = build_word_selection_snapshot(
            teacher_user_id,
            workspace_id,
            selected_learning_item_ids,
            current_learning_item_id=selected_learning_item_ids[0] if selected_learning_item_ids else None,
        )
        if not snapshot["selected_learning_item_ids"]:
            raise TeacherAssignmentDraftError
        content_summary = {
            "source_mode": SOURCE_MODE_WORDS,
            "workspace_id": workspace_id,
            "workspace_name": workspace_name,
            "selected_count": int(snapshot["selected_count"]),
            "preview_items": list(snapshot["preview_items"]),
            "learning_item_ids": list(snapshot["selected_learning_item_ids"]),
        }
    else:
        raise TeacherAssignmentDraftError

    return {
        "workspace_id": workspace_id,
        "workspace_name": workspace_name,
        "source_mode": source_mode,
        "content_summary": content_summary,
        "assignment_kind": normalized_kind,
        "assignment_mode": normalized_mode,
        "recipients": selected_recipients,
        "has_recipients": bool(selected_recipients),
    }


def persist_assignment_draft(
    teacher_user_id: int,
    *,
    source_mode: str,
    workspace_id: int,
    topic_id: int | None,
    selected_learning_item_ids: list[int],
    recipient_user_ids: list[int],
    assignment_kind: str = ASSIGNMENT_KIND_HOMEWORK,
    assignment_mode: str = ASSIGNMENT_MODE_STAGED_DEFAULT,
) -> list[dict[str, object]]:
    if not recipient_user_ids:
        raise TeacherAssignmentRecipientsRequiredError
    family_id = _workspace_family_id(workspace_id)
    family = get_user_family(teacher_user_id)
    if family is None or int(family["id"]) != family_id:
        raise TeacherAssignmentDraftError
    if source_mode == SOURCE_MODE_TOPIC:
        if topic_id is None:
            raise TeacherAssignmentDraftError
        topic = _get_family_topic(topic_id, family_id)
        if topic is None:
            raise TeacherAssignmentDraftError
        learning_item_ids = _get_family_topic_learning_item_ids(topic_id)
        if not learning_item_ids:
            raise TeacherAssignmentDraftError
        return [
            {
                "assignment_id": create_family_homework_assignment(
                    family_id,
                    teacher_user_id,
                    student_user_id,
                    learning_item_ids,
                    title=str(topic["title"]),
                ),
                "student_user_id": student_user_id,
                "title": str(topic["title"]),
                "assignment_kind": normalize_assignment_kind(assignment_kind),
                "assignment_mode": normalize_assignment_mode(assignment_mode),
                "learning_item_ids": learning_item_ids,
            }
            for student_user_id in recipient_user_ids
        ]
    if source_mode == SOURCE_MODE_WORDS:
        if not selected_learning_item_ids:
            raise TeacherAssignmentDraftError
        return [
            {
                "assignment_id": create_family_homework_assignment(
                    family_id,
                    teacher_user_id,
                    student_user_id,
                    selected_learning_item_ids,
                ),
                "student_user_id": student_user_id,
                "title": None,
                "assignment_kind": normalize_assignment_kind(assignment_kind),
                "assignment_mode": normalize_assignment_mode(assignment_mode),
                "learning_item_ids": list(selected_learning_item_ids),
            }
            for student_user_id in recipient_user_ids
        ]
    raise TeacherAssignmentDraftError


def _serialize_learning_item_card(learning_item: dict[str, object]) -> dict[str, object]:
    translations = {
        str(row["language_code"]): str(row["translation_text"])
        for row in list_learning_item_translations(int(learning_item["id"]))
    }
    return {
        "id": int(learning_item["id"]),
        "text": str(learning_item["text"]),
        "translations": translations,
    }


def _build_learning_item_preview_rows(learning_item_ids: list[int]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for learning_item_id in learning_item_ids:
        learning_item = get_learning_item(learning_item_id)
        if learning_item is None:
            continue
        rows.append(
            {
                "id": int(learning_item["id"]),
                "text": str(learning_item["text"]),
            }
        )
    return rows


def _build_user_display_name(user: sqlite3.Row | None, fallback_user_id: int) -> str:
    if user is None:
        return f"User {fallback_user_id}"
    for field_name in ("first_name", "username", "last_name"):
        value = user[field_name]
        if value:
            return str(value)
    return f"User {fallback_user_id}"


def _family_workspace_id(family_id: int) -> int:
    return FAMILY_WORKSPACE_ID_OFFSET + family_id


def _workspace_family_id(workspace_id: int) -> int | None:
    if workspace_id >= FAMILY_WORKSPACE_ID_OFFSET:
        return workspace_id - FAMILY_WORKSPACE_ID_OFFSET
    return None


def _get_family_topic(topic_id: int, family_id: int) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, family_id, name, title, is_archived, created_at, updated_at
            FROM topics
            WHERE id = ?
              AND family_id = ?
              AND is_archived = 0
            """,
            (topic_id, family_id),
        ).fetchone()


def _get_family_topic_learning_item_ids(topic_id: int) -> list[int]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT learning_item_id
            FROM topic_items
            WHERE topic_id = ?
            ORDER BY id
            """,
            (topic_id,),
        ).fetchall()
    return [int(row["learning_item_id"]) for row in rows]
