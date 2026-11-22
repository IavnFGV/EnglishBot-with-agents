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


MAX_IMAGE_SIDE = 1024
MAX_TEXT_LENGTH = 200
LABEL_KEYS = (
    "title", "topics", "new_topic", "topic_title", "rename", "delete_topic",
    "delete_topic_confirm", "words", "new_word", "word", "translation",
    "other_languages", "save", "saved", "delete_word", "delete_word_confirm",
    "photo", "choose_photo", "photo_url", "use_url", "remove_photo", "no_words",
    "no_topics", "uploading", "error", "expired", "back", "cancel", "word_count",
    "search",
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
    return {key: translate_for_user(user_id, f"editor.ui.{key}", count="{count}") for key in LABEL_KEYS}


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
    }


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
    word = connection.execute("SELECT id, text FROM learning_items WHERE id = ?", (word_id,)).fetchone()
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
    }


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


def create_word(user_id: int, topic_id: int, text: object, translations: object = None) -> dict[str, object]:
    family_id = _family_id(user_id)
    clean_text = _clean_text(text, required=True)
    with get_connection() as connection:
        _require_topic(connection, family_id, topic_id)
    word_id = int(create_teacher_topic_item(user_id, family_id, topic_id, clean_text)["learning_item_id"])
    with get_connection() as connection:
        _write_translations(connection, word_id, translations)
        return _serialize_word(connection, word_id)


def update_word(user_id: int, word_id: int, text: object = None, translations: object = None) -> dict[str, object]:
    family_id = _family_id(user_id)
    with get_connection() as connection:
        word = _require_word(connection, family_id, word_id)
        if text is not None:
            clean_text = _clean_text(text, required=True)
            timestamp = utc_now()
            connection.execute(
                "UPDATE learning_items SET text = ?, updated_at = ? WHERE id = ?",
                (clean_text, timestamp, word_id),
            )
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


def normalize_image(content: bytes) -> bytes:
    """Re-encode any supported image as an upright RGB JPEG that Telegram accepts."""
    if not content:
        raise _error("invalid_image")
    try:
        with Image.open(BytesIO(content)) as source:
            image = ImageOps.exif_transpose(source)
            image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
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


def _store_word_image(word_id: int, content: bytes) -> None:
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
    _store_word_image(word_id, content)
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
    _store_word_image(word_id, content)
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
            return create_word(user_id, topic_id, payload.get("text"), payload.get("translations"))
    if len(parts) >= 2 and parts[0] == "words":
        word_id = _int_part(parts[1])
        rest = parts[2:]
        if method == "POST" and rest == []:
            payload = _json(body)
            return update_word(user_id, word_id, payload.get("text"), payload.get("translations"))
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
    raise _error("not_found", 404)
