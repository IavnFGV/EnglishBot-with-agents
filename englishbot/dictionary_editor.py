"""Family dictionary editing for the web editor: topics, words, translations, images."""

import json
import mimetypes
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .assets import (
    ASSET_TYPE_IMAGE,
    PRIMARY_IMAGE_ROLE,
    download_remote_asset_content,
    get_learning_item_asset,
    replace_learning_item_assets_for_role,
    resolve_runtime_asset_path,
    store_teacher_content_image,
)
from .db import get_connection, utc_now
from .families import get_user_family
from .i18n import LANGUAGE_LABELS, translate_for_user
from .mini_app import MiniAppError
from .teacher_content import TRANSLATION_LANGUAGE_CODES, create_teacher_topic, create_teacher_topic_item
from .verbs import ITEM_TYPE_VERB, ITEM_TYPE_WORD, VerbFormsError, create_family_verb, load_forms, set_item_verb_forms


MAX_IMAGE_SIDE = 1024
MAX_TEXT_LENGTH = 200
LABEL_KEYS = (
    "title", "topics", "new_topic", "topic_title", "rename", "delete_topic",
    "delete_topic_confirm", "words", "new_word", "word", "translation",
    "other_languages", "save", "saved", "delete_word", "delete_word_confirm",
    "photo", "choose_photo", "photo_url", "use_url", "remove_photo", "no_words",
    "no_topics", "uploading", "error", "expired", "back", "cancel", "word_count",
    "search", "draft_title", "draft_name", "draft_topic", "already_known", "assign_to",
    "dont_assign", "mode", "save_draft", "draft_saved", "draft_saved_assigned", "add_item",
    "new_topic_option", "draft_empty", "draft_unavailable", "draft_words",
    "sets", "no_sets", "set_words", "set_assignments", "assign_again", "assign",
    "assigned_ok", "assignment_active", "assignment_completed", "never_assigned",
    "models", "models_queue", "models_available", "models_hint", "models_empty_queue",
    "models_not_configured", "models_catalog_error", "model_add", "model_remove", "model_test",
    "model_testing", "model_test_ok", "model_test_failed", "model_stats", "model_no_stats",
    "model_not_free", "model_avg_seconds", "drafts", "delete_draft", "delete_draft_confirm", "saved_sets", "archive_set", "archive_set_confirm", "restore_set", "archive", "archived_note", "sets_in_progress", "show_more", "search_sets",
    "remove_from_set", "add_to_set", "search_dictionary", "create_word", "set_edit_note", "homework_list", "homework_now", "homework_finished", "cancel_homework", "cancel_homework_confirm", "homework_none", "homework_cancelled", "words_done", "assigned_on", "open_set",
    "new_homework", "tasks", "add_task", "task_title", "task_instructions", "task_enabled", "delete_task",
    "attach_photo", "upload_photo", "gallery", "gallery_hint", "photo_unused", "photo_in_task", "detach_photo",
    "no_photos", "move_up", "move_down",
    "word_picture", "picture_done", "picture_other_page", "picture_upload", "picture_remove", "picture_hint",
    "picture_too_small", "picture_kept",
    "heroine_pictures", "heroine_draw", "heroine_idea", "heroine_idea_hint", "heroine_drawing",
    "heroine_requested", "heroine_use", "heroine_redraw", "heroine_skip", "heroine_none", "heroine_failed",
    "heroine_scene", "heroine_state_offline", "heroine_state_auth_required", "heroine_state_limited",
    "heroine_count_drawing", "heroine_count_ready", "heroine_ready_open",
    "remove_word", "add_topic", "add_topic_hint", "draft_autosaved", "new_words_topic",
    "verb", "verb_base", "verb_past", "verb_participle", "verb_hint", "verb_forms_invalid", "create_verb",
)


def _error(code: str, status: int = 400) -> MiniAppError:
    return MiniAppError(code, status)


def _family_id(user_id: int) -> int:
    family = get_user_family(user_id)
    if family is None:
        raise _error("access_denied", 403)
    return int(family["id"])


def _clean_text(value: object, *, required: bool) -> str:
    text = " ".join(str(value or "").split())
    if required and not text:
        raise _error("text_required")
    if len(text) > MAX_TEXT_LENGTH:
        raise _error("text_too_long")
    return text


def _require_topic(connection, family_id: int, topic_id: int):
    topic = connection.execute(
        "SELECT id, title FROM topics WHERE id = ? AND family_id = ? AND is_archived = 0",
        (topic_id, family_id),
    ).fetchone()
    if topic is None:
        raise _error("topic_not_found", 404)
    return topic


def _require_word(connection, family_id: int, word_id: int):
    word = connection.execute(
        "SELECT id, lexeme_id, text FROM learning_items WHERE id = ? AND family_id = ? AND is_archived = 0",
        (word_id, family_id),
    ).fetchone()
    if word is None:
        raise _error("word_not_found", 404)
    return word


def editor_labels(user_id: int) -> dict[str, str]:
    placeholders = {name: "{" + name + "}" for name in ("count", "found", "expected", "seconds", "error", "ok", "fail", "done", "total", "date", "tasks")}
    return {key: translate_for_user(user_id, f"editor.ui.{key}", **placeholders) for key in LABEL_KEYS}


def list_topics(user_id: int) -> dict[str, object]:
    family_id = _family_id(user_id)
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT topics.id, topics.title,
                   COUNT(learning_items.id) AS word_count
            FROM topics
            LEFT JOIN topic_items ON topic_items.topic_id = topics.id
            LEFT JOIN learning_items
              ON learning_items.id = topic_items.learning_item_id AND learning_items.is_archived = 0
            WHERE topics.family_id = ? AND topics.is_archived = 0
            GROUP BY topics.id
            ORDER BY topics.title COLLATE NOCASE, topics.id
            """,
            (family_id,),
        ).fetchall()
    return {
        "topics": [
            {"id": int(row["id"]), "title": str(row["title"]), "word_count": int(row["word_count"])}
            for row in rows
        ],
        "languages": [
            {"code": code, "label": LANGUAGE_LABELS[code]} for code in TRANSLATION_LANGUAGE_CODES
        ],
        "labels": editor_labels(user_id),
        "is_owner": _is_owner(user_id),
        "heroine": _heroine_summary(user_id),
    }


def _heroine_summary(user_id: int) -> dict[str, object] | None:
    from .config import get_heroine_dir
    from .heroine_pictures import picture_counts

    if get_heroine_dir() is None:
        return None
    return picture_counts(user_id)


def _is_owner(user_id: int) -> bool:
    from .config import get_owner_telegram_user_id

    return get_owner_telegram_user_id() == user_id


def create_topic(user_id: int, title: object) -> dict[str, object]:
    family_id = _family_id(user_id)
    topic = create_teacher_topic(user_id, family_id, _clean_text(title, required=True))
    return {"id": int(str(topic["id"])), "title": str(topic["title"]), "word_count": 0}


def rename_topic(user_id: int, topic_id: int, title: object) -> dict[str, object]:
    family_id = _family_id(user_id)
    clean_title = _clean_text(title, required=True)
    with get_connection() as connection:
        _require_topic(connection, family_id, topic_id)
        connection.execute(
            "UPDATE topics SET title = ?, updated_at = ? WHERE id = ?",
            (clean_title, utc_now(), topic_id),
        )
    return {"id": topic_id, "title": clean_title}


def delete_topic(user_id: int, topic_id: int) -> dict[str, object]:
    """Archive the topic and the words that belong to no other active topic."""
    family_id = _family_id(user_id)
    timestamp = utc_now()
    with get_connection() as connection:
        _require_topic(connection, family_id, topic_id)
        connection.execute(
            "UPDATE topics SET is_archived = 1, updated_at = ? WHERE id = ?",
            (timestamp, topic_id),
        )
        connection.execute(
            """
            UPDATE learning_items
            SET is_archived = 1, updated_at = ?
            WHERE id IN (SELECT learning_item_id FROM topic_items WHERE topic_id = ?)
              AND NOT EXISTS (
                SELECT 1 FROM topic_items AS other
                JOIN topics ON topics.id = other.topic_id
                WHERE other.learning_item_id = learning_items.id
                  AND other.topic_id != ? AND topics.is_archived = 0
              )
            """,
            (timestamp, topic_id, topic_id),
        )
    return {"deleted": True}


def _serialize_word(connection, word_id: int) -> dict[str, object]:
    word = connection.execute(
        "SELECT id, text, item_type, details_json FROM learning_items WHERE id = ?", (word_id,)
    ).fetchone()
    translations = {
        str(row["language_code"]): str(row["translation_text"])
        for row in connection.execute(
            "SELECT language_code, translation_text FROM learning_item_translations WHERE learning_item_id = ?",
            (word_id,),
        ).fetchall()
    }
    image = get_learning_item_asset(word_id, role=PRIMARY_IMAGE_ROLE, connection=connection)
    return {
        "id": int(word["id"]),
        "text": str(word["text"]),
        "translations": {code: translations.get(code, "") for code in TRANSLATION_LANGUAGE_CODES},
        "image_id": int(image["asset_id"]) if image is not None else None,
        **_verb_fields(word),
    }


def _verb_fields(word) -> dict[str, object]:
    forms = load_forms(word["details_json"]) if word["item_type"] == ITEM_TYPE_VERB else None
    if forms is None:
        return {"type": ITEM_TYPE_WORD, "forms": None}
    return {"type": ITEM_TYPE_VERB, "forms": {"past": forms[0], "participle": forms[1]}}


def _verb_payload(verb: object) -> dict[str, object] | None:
    """The editor sends {"past", "participle"} for a verb and null for a plain word."""
    if verb is None:
        return None
    if not isinstance(verb, dict):
        raise _error("invalid_verb_forms")
    return verb


def list_words(user_id: int, topic_id: int) -> dict[str, object]:
    family_id = _family_id(user_id)
    with get_connection() as connection:
        topic = _require_topic(connection, family_id, topic_id)
        rows = connection.execute(
            """
            SELECT learning_items.id
            FROM topic_items
            JOIN learning_items ON learning_items.id = topic_items.learning_item_id
            WHERE topic_items.topic_id = ? AND learning_items.is_archived = 0
            ORDER BY topic_items.id
            """,
            (topic_id,),
        ).fetchall()
        words = [_serialize_word(connection, int(row["id"])) for row in rows]
    return {"topic": {"id": topic_id, "title": str(topic["title"])}, "words": words}


def _write_translations(connection, word_id: int, translations: object) -> None:
    if not isinstance(translations, dict):
        return
    timestamp = utc_now()
    for code in TRANSLATION_LANGUAGE_CODES:
        if code not in translations:
            continue
        text = _clean_text(translations[code], required=False)
        connection.execute(
            "DELETE FROM learning_item_translations WHERE learning_item_id = ? AND language_code = ?",
            (word_id, code),
        )
        if text:
            connection.execute(
                """
                INSERT INTO learning_item_translations
                    (learning_item_id, language_code, translation_text, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (word_id, code, text, timestamp, timestamp),
            )


def create_word(user_id: int, topic_id: int, text: object, translations: object = None, verb: object = None) -> dict[str, object]:
    family_id = _family_id(user_id)
    clean_text = _clean_text(text, required=True)
    forms = _verb_payload(verb)
    with get_connection() as connection:
        _require_topic(connection, family_id, topic_id)
    if forms is not None:
        try:
            word_id = create_family_verb(family_id, topic_id, clean_text, forms.get("past"), forms.get("participle"))
        except VerbFormsError as exc:
            raise _error("invalid_verb_forms") from exc
    else:
        word_id = int(create_teacher_topic_item(user_id, family_id, topic_id, clean_text)["learning_item_id"])
    with get_connection() as connection:
        _write_translations(connection, word_id, translations)
        return _serialize_word(connection, word_id)


def update_word(
    user_id: int, word_id: int, text: object = None, translations: object = None, verb: object = ...,
) -> dict[str, object]:
    """verb: forms dict makes the item a verb, None a plain word; omitted keeps its type."""
    family_id = _family_id(user_id)
    with get_connection() as connection:
        word = _require_word(connection, family_id, word_id)
        if verb is not ...:
            try:
                base = _clean_text(text, required=True) if text is not None else str(word["text"])
                set_item_verb_forms(connection, word_id, _verb_payload(verb), base.lower())
            except VerbFormsError as exc:
                raise _error("invalid_verb_forms") from exc
        if text is not None:
            clean_text = _clean_text(text, required=True)
            timestamp = utc_now()
            connection.execute(
                "UPDATE learning_items SET text = ?, updated_at = ? WHERE id = ?",
                (clean_text, timestamp, word_id),
            )
            same = connection.execute(
                "SELECT id FROM lexemes WHERE lemma = ? AND id != ?", (clean_text, int(word["lexeme_id"]))
            ).fetchone()
            if same is not None:  # lemmas are unique: share the existing one instead of renaming into it
                connection.execute("UPDATE learning_items SET lexeme_id = ? WHERE id = ?", (int(same["id"]), word_id))
            else:
                connection.execute(
                    "UPDATE lexemes SET lemma = ?, updated_at = ? WHERE id = ?",
                    (clean_text, timestamp, int(word["lexeme_id"])),
                )
        _write_translations(connection, word_id, translations)
        return _serialize_word(connection, word_id)


def delete_word(user_id: int, word_id: int) -> dict[str, object]:
    family_id = _family_id(user_id)
    with get_connection() as connection:
        _require_word(connection, family_id, word_id)
        connection.execute(
            "UPDATE learning_items SET is_archived = 1, updated_at = ? WHERE id = ?",
            (utc_now(), word_id),
        )
    return {"deleted": True}


def normalize_image(content: bytes, max_side: int = MAX_IMAGE_SIDE) -> bytes:
    """Re-encode any supported image as an upright RGB JPEG that Telegram accepts."""
    if not content:
        raise _error("invalid_image")
    try:
        with Image.open(BytesIO(content)) as source:
            image = ImageOps.exif_transpose(source)
            image.thumbnail((max_side, max_side))
            if image.mode in ("RGBA", "LA", "P"):
                image = image.convert("RGBA")
                background = Image.new("RGB", image.size, "white")
                background.paste(image, mask=image.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            output = BytesIO()
            image.save(output, format="JPEG", quality=85, optimize=True)
    except (OSError, SyntaxError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise _error("invalid_image") from exc
    return output.getvalue()


def store_word_image(word_id: int, content: bytes) -> None:
    local_path = store_teacher_content_image(word_id, normalize_image(content), extension=".jpg")
    replace_learning_item_assets_for_role(
        word_id,
        PRIMARY_IMAGE_ROLE,
        assets=[{"asset_type": ASSET_TYPE_IMAGE, "source_url": None, "local_path": local_path}],
    )


def set_word_image(user_id: int, word_id: int, content: bytes) -> dict[str, object]:
    family_id = _family_id(user_id)
    with get_connection() as connection:
        _require_word(connection, family_id, word_id)
    store_word_image(word_id, content)
    with get_connection() as connection:
        return _serialize_word(connection, word_id)


def set_word_image_from_url(user_id: int, word_id: int, url: object) -> dict[str, object]:
    family_id = _family_id(user_id)
    with get_connection() as connection:
        _require_word(connection, family_id, word_id)
    source_url = str(url or "").strip()
    if not source_url.startswith(("http://", "https://")):
        raise _error("invalid_url")
    try:
        content = download_remote_asset_content(ASSET_TYPE_IMAGE, source_url)
    except (OSError, ValueError) as exc:
        raise _error("image_download_failed") from exc
    store_word_image(word_id, content)
    with get_connection() as connection:
        return _serialize_word(connection, word_id)


def clear_word_image(user_id: int, word_id: int) -> dict[str, object]:
    family_id = _family_id(user_id)
    with get_connection() as connection:
        _require_word(connection, family_id, word_id)
    replace_learning_item_assets_for_role(word_id, PRIMARY_IMAGE_ROLE, assets=[])
    with get_connection() as connection:
        return _serialize_word(connection, word_id)


def word_image_path(user_id: int, word_id: int) -> Path:
    family_id = _family_id(user_id)
    with get_connection() as connection:
        _require_word(connection, family_id, word_id)
        image = get_learning_item_asset(word_id, role=PRIMARY_IMAGE_ROLE, connection=connection)
    if image is None or not image["local_path"]:
        raise _error("image_not_found", 404)
    path = resolve_runtime_asset_path(str(image["local_path"]))
    if not path.is_file():
        raise _error("image_not_found", 404)
    return path


def _int_part(value: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise _error("not_found", 404) from exc


def _json(body: bytes) -> dict[str, object]:
    try:
        payload = json.loads(body or b"{}")
    except (ValueError, UnicodeDecodeError) as exc:
        raise _error("invalid_request") from exc
    if not isinstance(payload, dict):
        raise _error("invalid_request")
    return payload


def route_editor_request(method: str, parts: list[str], user_id: int, body: bytes):
    """Dispatch /mini-app/api/editor/<parts>; returns a JSON dict or (bytes, content_type)."""
    if method == "GET" and parts in ([], ["topics"]):
        return list_topics(user_id)
    if parts == ["words", "search"] and method == "POST":
        payload = _json(body)
        item_type = payload.get("type") if payload.get("type") in (ITEM_TYPE_WORD, ITEM_TYPE_VERB) else None
        return {"words": search_words(user_id, payload.get("q"), item_type=item_type)}
    if method == "POST" and parts == ["topics"]:
        return create_topic(user_id, _json(body).get("title"))
    if len(parts) >= 2 and parts[0] == "topics":
        topic_id = _int_part(parts[1])
        rest = parts[2:]
        if method == "POST" and rest == []:
            return rename_topic(user_id, topic_id, _json(body).get("title"))
        if method == "POST" and rest == ["delete"]:
            return delete_topic(user_id, topic_id)
        if method == "GET" and rest == ["words"]:
            return list_words(user_id, topic_id)
        if method == "POST" and rest == ["words"]:
            payload = _json(body)
            return create_word(user_id, topic_id, payload.get("text"), payload.get("translations"), payload.get("verb"))
    if len(parts) >= 2 and parts[0] == "words":
        word_id = _int_part(parts[1])
        rest = parts[2:]
        if method == "POST" and rest == []:
            payload = _json(body)
            return update_word(user_id, word_id, payload.get("text"), payload.get("translations"), payload.get("verb", ...))
        if method == "POST" and rest == ["delete"]:
            return delete_word(user_id, word_id)
        if method == "GET" and rest == ["image"]:
            path = word_image_path(user_id, word_id)
            return path.read_bytes(), mimetypes.guess_type(path.name)[0] or "image/jpeg"
        if method == "POST" and rest == ["image"]:
            return set_word_image(user_id, word_id, body)
        if method == "POST" and rest == ["image-url"]:
            return set_word_image_from_url(user_id, word_id, _json(body).get("url"))
        if method == "POST" and rest == ["image", "delete"]:
            return clear_word_image(user_id, word_id)
    if len(parts) == 3 and parts[0] == "words" and parts[2] == "heroine" and method == "POST":
        from .heroine_pictures import request_picture

        return request_picture(user_id, _int_part(parts[1]), _json(body).get("scene"))
    if parts and parts[0] == "heroine":
        return _route_heroine(method, parts[1:], user_id, body)
    if parts and parts[0] == "assignments":
        return _route_assignments(method, parts[1:], user_id)
    if parts and parts[0] == "models":
        return _route_models(method, parts[1:], user_id, body)
    if parts and parts[0] == "sets":
        return _route_sets(method, parts[1:], user_id, body)
    if parts == ["imports"] and method == "POST":
        from .homework_sets import create_empty_draft

        return create_empty_draft(user_id)
    if len(parts) >= 2 and parts[0] == "imports":
        return _route_import(method, _int_part(parts[1]), parts[2:], user_id, body)
    raise _error("not_found", 404)


def search_words(user_id: int, query: object, limit: int = 20, item_type: object = None) -> list[dict[str, object]]:
    """Family words whose English text or translation contains the query (any letter case); optionally one type."""
    family_id = _family_id(user_id)
    needle = _clean_text(query, required=False).casefold()
    if not needle:
        return []
    # SQLite lower() only folds ASCII, so Cyrillic matching is done here; a family dictionary is small.
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT learning_items.id, learning_items.text,
                   group_concat(learning_item_translations.translation_text, ' ') AS translations
            FROM learning_items
            LEFT JOIN learning_item_translations ON learning_item_translations.learning_item_id = learning_items.id
            WHERE learning_items.family_id = ? AND learning_items.is_archived = 0
              AND (? IS NULL OR learning_items.item_type = ?)
            GROUP BY learning_items.id
            """,
            (family_id, item_type, item_type),
        ).fetchall()
        matches = sorted(
            (row for row in rows if needle in f"{row['text']} {row['translations'] or ''}".casefold()),
            key=lambda row: str(row["text"]).casefold(),
        )[:limit]
        return [_serialize_word(connection, int(row["id"])) for row in matches]


def _route_heroine(method: str, rest: list[str], user_id: int, body: bytes):
    from .heroine_pictures import approve_picture, candidate_path, list_pictures, redraw_picture, skip_picture

    if method == "GET" and rest == []:
        return {**list_pictures(user_id), "labels": editor_labels(user_id)}
    if len(rest) == 2:
        picture_id = _int_part(rest[0])
        if method == "GET" and rest[1] == "image":
            return candidate_path(user_id, picture_id).read_bytes(), "image/jpeg"
        if method == "POST" and rest[1] == "approve":
            return approve_picture(user_id, picture_id)
        if method == "POST" and rest[1] == "skip":
            return skip_picture(user_id, picture_id)
        if method == "POST" and rest[1] == "redraw":
            return redraw_picture(user_id, picture_id, _json(body).get("scene"))
    raise _error("not_found", 404)


def _route_assignments(method: str, rest: list[str], user_id: int):
    from .homework_sets import HomeworkSetError, cancel_assignment, list_assignments

    try:
        if method == "GET" and rest == []:
            return list_assignments(user_id)
        if method == "POST" and len(rest) == 2 and rest[1] == "cancel":
            return cancel_assignment(user_id, _int_part(rest[0]))
    except HomeworkSetError as exc:
        raise _error(exc.code, exc.status) from exc
    raise _error("not_found", 404)


def _models_state() -> dict[str, object]:
    from .ai_models import get_free_vision_models_cached, get_model_queue, get_model_stats
    from .config import get_openrouter_api_key

    stats = get_model_stats()
    queue = get_model_queue()
    catalog_error = None
    try:
        catalog = get_free_vision_models_cached()
    except (OSError, ValueError) as exc:
        catalog, catalog_error = [], str(exc)
    names = {str(model["id"]): str(model["name"]) for model in catalog}
    return {
        "configured": get_openrouter_api_key() is not None,
        "catalog_error": catalog_error,
        "queue": [
            {"id": model, "name": names.get(model, model), "free_now": model in names or catalog_error is not None, "stats": stats.get(model)}
            for model in queue
        ],
        "available": [
            {"id": model_id, "name": name, "stats": stats.get(model_id)}
            for model_id, name in names.items() if model_id not in queue
        ],
    }


def _route_models(method: str, rest: list[str], user_id: int, body: bytes):
    from .ai_models import run_model_check, set_model_queue
    from .config import get_owner_telegram_user_id

    if get_owner_telegram_user_id() != user_id:
        raise _error("access_denied", 403)
    if method == "GET" and rest == []:
        return _models_state()
    if method == "POST" and rest == []:
        queue = _json(body).get("queue")
        if not isinstance(queue, list):
            raise _error("invalid_request")
        try:
            set_model_queue([str(model) for model in queue])
        except ValueError as exc:
            raise _error("invalid_model") from exc
        return _models_state()
    if method == "POST" and rest == ["test"]:
        try:
            return run_model_check(str(_json(body).get("model") or ""))
        except ValueError as exc:
            raise _error("invalid_model") from exc
    raise _error("not_found", 404)


def _route_sets(method: str, rest: list[str], user_id: int, body: bytes):
    from .homework_sets import (
        HomeworkSetError, add_set_topic, add_set_word, archive_set, assign_set, get_set, list_drafts, list_sets,
        remove_set_word, rename_set, restore_set,
    )

    try:
        if method == "GET" and rest == []:
            return {
                "sets": list_sets(user_id),
                "drafts": list_drafts(user_id),
                "archived_count": len(list_sets(user_id, archived=True)),
                "labels": editor_labels(user_id),
            }
        if method == "GET" and rest == ["archive"]:
            return {"sets": list_sets(user_id, archived=True)}
        if rest:
            set_id = _int_part(rest[0])
            photo = _route_set_photos(method, set_id, rest[1:], user_id, body)
            if photo is not None:
                return photo
            if method == "GET" and rest[1:] == []:
                return get_set(user_id, set_id)
            if method == "POST" and rest[1:] == []:
                return rename_set(user_id, set_id, _json(body).get("title"))
            if method == "POST" and rest[1:] == ["archive"]:
                return archive_set(user_id, set_id)
            if method == "POST" and rest[1:] == ["restore"]:
                return restore_set(user_id, set_id)
            if method == "POST" and rest[1:] == ["words"]:
                return add_set_word(user_id, set_id, _json(body))
            if method == "POST" and rest[1:] == ["topic"]:
                return add_set_topic(user_id, set_id, _json(body).get("topic_id"))
            if method == "POST" and len(rest) == 4 and rest[1] == "words" and rest[3] == "delete":
                return remove_set_word(user_id, set_id, _int_part(rest[2]))
            if method == "POST" and rest[1:] == ["assign"]:
                payload = _json(body)
                result = assign_set(user_id, set_id, payload.get("assign_to"), payload.get("mode"))
                result["_notify"] = [{"chat_id": result["assigned_to"], "title": result["title"]}]
                return result
    except HomeworkSetError as exc:
        raise _error(exc.code, exc.status) from exc
    raise _error("not_found", 404)


def _route_import(method: str, set_id: int, rest: list[str], user_id: int, body: bytes):
    from .homework_sets import HomeworkSetError, cancel_set, get_draft, save_draft, update_draft

    try:
        photo = _route_set_photos(method, set_id, rest, user_id, body)
        if photo is not None:
            return photo
        if method == "GET" and rest == []:
            draft = get_draft(user_id, set_id)
            draft["labels"] = editor_labels(user_id)
            return draft
        if method == "POST" and rest == []:
            return update_draft(user_id, set_id, _json(body))
        if method == "POST" and rest == ["save"]:
            result = save_draft(user_id, set_id, _json(body))
            if result["assigned_to"] is not None:
                # status_server delivers this through the bot after the response is built.
                result["_notify"] = [{"chat_id": result["assigned_to"], "title": result["title"]}]
            return result
        if method == "POST" and rest == ["cancel"]:
            get_draft(user_id, set_id)  # only drafts can be deleted from the editor
            cancel_set(user_id, set_id)
            return {"deleted": True}
    except HomeworkSetError as exc:
        raise _error(exc.code, exc.status) from exc
    raise _error("not_found", 404)


def _route_set_photos(method: str, set_id: int, rest: list[str], user_id: int, body: bytes):
    """Photos of a homework set (draft or saved): upload into its gallery, or read one."""
    from .homework_sets import add_set_photo, add_word_picture, crop_set_photo, set_photo_path

    if rest == ["photos"] and method == "POST":
        return add_set_photo(user_id, set_id, body)
    if rest == ["word-picture"] and method == "POST":
        return add_word_picture(user_id, set_id, body)
    if rest == ["crop"] and method == "POST":
        payload = _json(body)
        return crop_set_photo(user_id, set_id, payload.get("photo"), payload.get("box"))
    if len(rest) == 2 and rest[0] == "photos" and method == "GET":
        path = set_photo_path(user_id, set_id, _int_part(rest[1]))
        return path.read_bytes(), "image/jpeg"
    return None
