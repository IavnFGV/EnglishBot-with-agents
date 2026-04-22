import sqlite3

from .db import get_connection, get_user
from .homework import (
    ASSIGNMENT_KIND_HOMEWORK,
    ASSIGNMENT_MODE_STAGED_DEFAULT,
    create_assignment,
    create_assignment_from_group,
    normalize_assignment_kind,
    normalize_assignment_mode,
)
from .teacher_content import (
    TeacherContentAccessError,
    list_teacher_browsable_workspaces,
    list_teacher_workspace_topics,
)
from .topics import get_topic, get_topic_learning_item_ids
from .vocabulary import get_learning_item, list_learning_item_translations, list_learning_items
from .workspaces import (
    WorkspaceEditPermissionError,
    WorkspaceKindMismatchError,
    WorkspaceNotFoundError,
    ensure_teacher_can_edit_workspace_content,
    find_shared_workspace_for_teacher_and_student,
)


SOURCE_MODE_TOPIC = "topic"
SOURCE_MODE_WORDS = "words"
SUMMARY_PREVIEW_LIMIT = 5


class TeacherAssignmentError(Exception):
    pass


class TeacherAssignmentAccessError(TeacherAssignmentError):
    pass


class TeacherAssignmentDraftError(TeacherAssignmentError):
    pass


class TeacherAssignmentRecipientsRequiredError(TeacherAssignmentDraftError):
    pass


def list_assignment_workspaces(teacher_user_id: int) -> list[dict[str, object]]:
    return list_teacher_browsable_workspaces(teacher_user_id)


def list_assignment_topics(
    teacher_user_id: int,
    workspace_id: int,
) -> list[dict[str, object]]:
    try:
        return list_teacher_workspace_topics(teacher_user_id, workspace_id)
    except TeacherContentAccessError as error:
        raise TeacherAssignmentAccessError from error


def build_topic_selection_summary(
    teacher_user_id: int,
    workspace_id: int,
    topic_id: int,
) -> dict[str, object]:
    workspace = _ensure_teacher_workspace(teacher_user_id, workspace_id)
    topic = get_topic(topic_id)
    if topic is None or int(topic["workspace_id"]) != workspace_id:
        raise TeacherAssignmentDraftError
    learning_item_ids = get_topic_learning_item_ids(topic_id)
    preview_items = _build_learning_item_preview_rows(learning_item_ids[:SUMMARY_PREVIEW_LIMIT])
    return {
        "source_mode": SOURCE_MODE_TOPIC,
        "workspace_id": workspace_id,
        "workspace_name": workspace["name"] or f"Workspace {workspace_id}",
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
    workspace = _ensure_teacher_workspace(teacher_user_id, workspace_id)
    learning_items = list_learning_items(workspace_id=workspace_id)
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
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT student_user_id, created_at
            FROM teacher_student_links
            WHERE teacher_user_id = ?
            ORDER BY student_user_id
            """,
            (teacher_user_id,),
        ).fetchall()

    recipients: list[dict[str, object]] = []
    for row in rows:
        student_user_id = int(row["student_user_id"])
        shared_workspace = find_shared_workspace_for_teacher_and_student(
            teacher_user_id,
            student_user_id,
            kind="student",
        )
        if shared_workspace is None:
            continue
        user = get_user(student_user_id)
        recipients.append(
            {
                "student_user_id": student_user_id,
                "display_name": _build_user_display_name(user, student_user_id),
                "workspace_id": int(shared_workspace["id"]),
            }
        )
    return recipients


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
    workspace = _ensure_teacher_workspace(teacher_user_id, workspace_id)
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
            "workspace_name": workspace["name"] or f"Workspace {workspace_id}",
            "selected_count": int(snapshot["selected_count"]),
            "preview_items": list(snapshot["preview_items"]),
            "learning_item_ids": list(snapshot["selected_learning_item_ids"]),
        }
    else:
        raise TeacherAssignmentDraftError

    return {
        "workspace_id": workspace_id,
        "workspace_name": workspace["name"] or f"Workspace {workspace_id}",
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
    if source_mode == SOURCE_MODE_TOPIC:
        if topic_id is None:
            raise TeacherAssignmentDraftError
        topic = get_topic(topic_id)
        if topic is None or int(topic["workspace_id"]) != workspace_id:
            raise TeacherAssignmentDraftError
        results = [
            create_assignment_from_group(
                teacher_user_id,
                student_user_id,
                workspace_id,
                str(topic["name"]),
                assignment_kind=assignment_kind,
                assignment_mode=assignment_mode,
            )
            for student_user_id in recipient_user_ids
        ]
        return results
    if source_mode == SOURCE_MODE_WORDS:
        if not selected_learning_item_ids:
            raise TeacherAssignmentDraftError
        return [
            create_assignment(
                teacher_user_id,
                student_user_id,
                selected_learning_item_ids,
                assignment_kind=assignment_kind,
                assignment_mode=assignment_mode,
            )
            for student_user_id in recipient_user_ids
        ]
    raise TeacherAssignmentDraftError


def _ensure_teacher_workspace(teacher_user_id: int, workspace_id: int) -> sqlite3.Row:
    try:
        return ensure_teacher_can_edit_workspace_content(workspace_id, teacher_user_id)
    except (WorkspaceEditPermissionError, WorkspaceKindMismatchError, WorkspaceNotFoundError) as error:
        raise TeacherAssignmentAccessError from error


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
