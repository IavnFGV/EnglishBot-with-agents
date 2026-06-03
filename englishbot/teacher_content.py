import math
import re
from pathlib import Path

from .assets import (
    ASSET_TYPE_AUDIO,
    ASSET_TYPE_IMAGE,
    PRIMARY_AUDIO_ROLE,
    PRIMARY_IMAGE_ROLE,
    store_remote_asset,
    replace_learning_item_assets_for_role,
    resolve_asset_ref_for_role,
)
from .db import get_connection, utc_now
from .families import (
    create_family_learning_item,
    create_family_topic,
    get_user_family,
    list_family_topics,
    replace_topic_items as replace_family_topic_items,
)
from .topics import get_topic
from .vocabulary import (
    create_lexeme,
    get_learning_item,
    get_lexeme,
    list_learning_item_translations,
)

EDITOR_PAGE_SIZE = 25
VISIBLE_ITEM_WINDOW_SIZE = 10
SHOW_ALL_THRESHOLD = 10
TRANSLATION_LANGUAGE_CODES = ("ru", "uk", "bg")


class TeacherContentAccessError(Exception):
    pass


def list_teacher_workspace_topics(
    teacher_user_id: int,
    workspace_id: int,
) -> list[dict[str, object]]:
    family_id = workspace_id
    family = get_user_family(teacher_user_id)
    if family_id is None or family is None or int(family["id"]) != family_id:
        raise TeacherContentAccessError
    return [
        {
            "id": int(topic["id"]),
            "name": str(topic["name"]),
            "title": str(topic["title"]),
            "item_count": len(_get_family_topic_learning_items(int(topic["id"]))),
        }
        for topic in list_family_topics(family_id)
    ]


def create_teacher_topic(
    teacher_user_id: int,
    workspace_id: int,
    title: str,
) -> dict[str, object]:
    family_id = workspace_id
    family = get_user_family(teacher_user_id)
    if family_id is None or family is None or int(family["id"]) != family_id:
        raise TeacherContentAccessError
    normalized_title = title.strip()
    if not normalized_title:
        raise ValueError("topic title is required")
    topic_name = _build_unique_family_topic_name(family_id, normalized_title)
    topic_id = create_family_topic(family_id, topic_name, normalized_title)
    return {
        "id": topic_id,
        "name": topic_name,
        "title": normalized_title,
        "workspace_id": workspace_id,
        "workspace_name": str(family["name"] or "Family"),
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
    all_learning_items = _get_family_topic_learning_items(topic_id, include_archived=True)
    learning_items = _get_family_topic_learning_items(topic_id)
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
    visible_items = _build_visible_items_window(
        learning_items,
        selected_item_id=int(selected_item["id"]) if selected_item is not None else None,
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
        "visible_items": visible_items,
        "current_item": current_item,
        "show_all_available": item_count > SHOW_ALL_THRESHOLD,
        "has_prev_page": clamped_page > 0,
        "has_next_page": clamped_page + 1 < page_count,
        "prev_item_id": (
            item_ids[(selected_index - 1) % item_count]
            if selected_index is not None and item_count > 1
            else None
        ),
        "next_item_id": (
            item_ids[(selected_index + 1) % item_count]
            if selected_index is not None and item_count > 1
            else None
        ),
    }


def build_teacher_topic_full_list_overview(
    teacher_user_id: int,
    workspace_id: int,
    topic_id: int,
) -> dict[str, object]:
    _, topic = _ensure_teacher_topic_access(teacher_user_id, workspace_id, topic_id)
    learning_items = _get_family_topic_learning_items(topic_id)
    rows = []
    for learning_item in learning_items:
        current_item = _build_editor_current_item(learning_item)
        rows.append(
            {
                "headword": str(current_item["headword"]),
                "has_image": bool(current_item["image_ref"]),
            }
        )
    return {
        "topic_title": str(topic["title"]),
        "item_count": len(rows),
        "rows": rows,
    }


def create_teacher_topic_item(
    teacher_user_id: int,
    workspace_id: int,
    topic_id: int,
    text: str,
) -> dict[str, int]:
    _ensure_teacher_topic_access(teacher_user_id, workspace_id, topic_id)
    normalized_text = text.strip()
    if not normalized_text:
        raise ValueError("item text is required")
    lexeme_id = create_lexeme(normalized_text)
    family_id = workspace_id
    learning_item_id = create_family_learning_item(family_id, lexeme_id, normalized_text)
    learning_item_ids = _get_family_topic_learning_item_ids(topic_id)
    learning_item_ids.append(learning_item_id)
    replace_family_topic_items(topic_id, learning_item_ids)
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
        with get_connection() as connection:
            connection.execute(
                """
                UPDATE learning_items
                SET text = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    normalized_value,
                    utc_now(),
                    learning_item_id,
                ),
            )
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
        with get_connection() as connection:
            existing = connection.execute(
                """
                SELECT id
                FROM learning_item_translations
                WHERE learning_item_id = ? AND language_code = ?
                """,
                (learning_item_id, field_name),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO learning_item_translations (
                        learning_item_id,
                        language_code,
                        translation_text,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        learning_item_id,
                        field_name,
                        normalized_value,
                        utc_now(),
                        utc_now(),
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE learning_item_translations
                    SET translation_text = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        normalized_value,
                        utc_now(),
                        int(existing["id"]),
                    ),
                )
        return
    if field_name == "image_ref":
        source_url = None
        if normalized_value.startswith(("http://", "https://")):
            source_url = normalized_value
            normalized_value = store_remote_asset(
                ASSET_TYPE_IMAGE,
                normalized_value,
                preferred_dir=Path("assets/images/remote"),
                filename_prefix=f"learning-item-{learning_item_id}",
                default_extension=".jpg",
            )
        replace_learning_item_assets_for_role(
            learning_item_id,
            PRIMARY_IMAGE_ROLE,
            assets=[
                {
                    "asset_type": ASSET_TYPE_IMAGE,
                    "source_url": source_url,
                    "local_path": normalized_value,
                }
            ] if normalized_value else [],
        )
        return
    if field_name == "audio_ref":
        source_url = None
        if normalized_value.startswith(("http://", "https://")):
            source_url = normalized_value
            normalized_value = store_remote_asset(
                ASSET_TYPE_AUDIO,
                normalized_value,
                preferred_dir=Path("assets/audio/remote"),
                filename_prefix=f"learning-item-{learning_item_id}",
                default_extension=".bin",
            )
        replace_learning_item_assets_for_role(
            learning_item_id,
            PRIMARY_AUDIO_ROLE,
            assets=[
                {
                    "asset_type": ASSET_TYPE_AUDIO,
                    "source_url": source_url,
                    "local_path": normalized_value,
                }
            ] if normalized_value else [],
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
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE learning_items
            SET is_archived = 1, updated_at = ?
            WHERE id = ?
            """,
            (utc_now(), learning_item_id),
        )
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
    family_id = workspace_id
    family = get_user_family(teacher_user_id)
    if family is None or int(family["id"]) != family_id:
        raise TeacherContentAccessError
    return {"id": workspace_id, "name": str(family["name"] or "Family")}


def _ensure_teacher_topic_access(
    teacher_user_id: int,
    workspace_id: int,
    topic_id: int,
):
    workspace = _ensure_teacher_workspace_access(teacher_user_id, workspace_id)
    topic = get_topic(topic_id)
    family_id = workspace_id
    if topic is None or topic["family_id"] is None or int(topic["family_id"]) != family_id:
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
    if learning_item is None:
        raise TeacherContentAccessError
    topic_item_ids = {int(item["id"]) for item in _get_family_topic_learning_items(int(topic["id"]))}
    if learning_item_id not in topic_item_ids:
        raise TeacherContentAccessError
    return learning_item


def _build_unique_family_topic_name(family_id: int, title: str) -> str:
    base_name = re.sub(r"[^a-z0-9]+", "-", title.strip().lower()).strip("-")
    if not base_name:
        base_name = "topic"
    candidate = base_name
    suffix = 2
    existing_names = {str(topic["name"]) for topic in list_family_topics(family_id)}
    while candidate in existing_names:
        candidate = f"{base_name}-{suffix}"
        suffix += 1
    return candidate


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


def _get_family_topic_learning_items(topic_id: int, *, include_archived: bool = False) -> list[dict[str, object]]:
    learning_items: list[dict[str, object]] = []
    for learning_item_id in _get_family_topic_learning_item_ids(topic_id):
        learning_item = get_learning_item(learning_item_id)
        if learning_item is None:
            continue
        if include_archived or int(learning_item["is_archived"]) == 0:
            learning_items.append(learning_item)
    return learning_items


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
        "image_ref": resolve_asset_ref_for_role(int(learning_item["id"]), PRIMARY_IMAGE_ROLE),
        "audio_ref": resolve_asset_ref_for_role(int(learning_item["id"]), PRIMARY_AUDIO_ROLE),
        "is_archived": bool(learning_item["is_archived"]),
    }


def _build_item_label(learning_item) -> str:
    lexeme = get_lexeme(int(learning_item["lexeme_id"]))
    if lexeme is not None and lexeme["lemma"]:
        return str(lexeme["lemma"])
    return str(learning_item["text"])


def _build_visible_items_window(
    learning_items,
    *,
    selected_item_id: int | None,
) -> list[dict[str, object]]:
    if not learning_items or selected_item_id is None:
        return []
    item_ids = [int(learning_item["id"]) for learning_item in learning_items]
    if selected_item_id not in item_ids:
        return []
    item_count = len(learning_items)
    selected_index = item_ids.index(selected_item_id)
    window_size = min(VISIBLE_ITEM_WINDOW_SIZE, item_count)
    half_window = window_size // 2
    start = (selected_index - half_window) % item_count
    return [
        {
            "position": item_index + 1,
            "headword": _build_item_label(learning_items[item_index]),
            "has_image": bool(
                resolve_asset_ref_for_role(
                    int(learning_items[item_index]["id"]),
                    PRIMARY_IMAGE_ROLE,
                )
            ),
            "is_selected": int(learning_items[item_index]["id"]) == selected_item_id,
        }
        for item_index in (
            (start + offset) % item_count
            for offset in range(window_size)
        )
    ]
