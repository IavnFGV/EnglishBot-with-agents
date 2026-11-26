"""Homework sets: tutor homework collected from forwarded messages, drafted by AI, saved as items."""

import json
import logging
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

from .ai_extraction import KIND_WORDS, SUPPORTED_KINDS, ExtractionResult
from .assets import (
    ASSET_TYPE_IMAGE,
    PRIMARY_IMAGE_ROLE,
    get_asset,
    delete_unreferenced_files,
    get_learning_item_asset,
    resolve_runtime_asset_path,
    store_homework_photo,
)
from .db import get_connection, utc_now
from .families import create_homework_assignment, get_user_family, list_family_members
from .i18n import translate_for_user
from .teacher_content import create_teacher_topic, create_teacher_topic_item
from .training import TRAINING_MODES
from .verbs import DEFAULT_VERB_TOPIC, ITEM_TYPE_WORD, VerbFormsError, create_family_verb, find_family_verb, load_forms, validate_forms


logger = logging.getLogger(__name__)


STATUS_COLLECTING = "collecting"
STATUS_PROCESSING = "processing"
STATUS_DRAFT = "draft"
STATUS_FAILED = "failed"
STATUS_SAVED = "saved"
STATUS_CANCELLED = "cancelled"
STATUS_ARCHIVED = "archived"
ASSIGNMENT_CANCELLED = "cancelled"
MAX_SOURCES = 30
MAX_TEXT_LENGTH = 200
MAX_INSTRUCTIONS_LENGTH = 4000
MAX_PHOTO_SIDE = 1600  # worksheets must stay readable, so larger than dictionary pictures
KIND_MANUAL = "manual"  # no AI: the draft starts from the forwarded text and photos only

# Task kinds of a homework set. Words and irregular verbs are drilled in training; paper work is
# ticked off; notes (rules, theory, the tutor's text) are only shown.
TASK_WORDS = "words"
TASK_VERBS = "verbs"
TASK_PAPER = "paper"
TASK_NOTE = "note"
TASK_KINDS = (TASK_WORDS, TASK_VERBS, TASK_PAPER, TASK_NOTE)
DRILL_KINDS = (TASK_WORDS, TASK_VERBS)


class HomeworkSetError(Exception):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def _family_id(user_id: int) -> int:
    family = get_user_family(user_id)
    if family is None:
        raise HomeworkSetError("access_denied", 403)
    return int(family["id"])


def _get_set(connection, user_id: int, set_id: int):
    row = connection.execute(
        "SELECT * FROM homework_sets WHERE id = ? AND family_id = ?",
        (set_id, _family_id(user_id)),
    ).fetchone()
    if row is None:
        raise HomeworkSetError("set_not_found", 404)
    return row


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())[:MAX_TEXT_LENGTH]


def summarize_sources(row) -> dict[str, int]:
    sources = json.loads(row["sources_json"] or "[]")
    return {
        "texts": sum(1 for source in sources if source.get("text")),
        "photos": sum(1 for source in sources if source.get("photo_file_id")),
    }


def get_collecting_set(user_id: int):
    with get_connection() as connection:
        return connection.execute(
            "SELECT * FROM homework_sets WHERE created_by_user_id = ? AND status = ? ORDER BY id DESC LIMIT 1",
            (user_id, STATUS_COLLECTING),
        ).fetchone()


def add_source(user_id: int, *, text: str | None = None, photo_file_id: str | None = None):
    """Append a forwarded text or photo to the user's collecting set, creating it if needed."""
    family_id = _family_id(user_id)
    source = {key: value for key, value in (("text", (text or "").strip()), ("photo_file_id", photo_file_id)) if value}
    if not source:
        raise HomeworkSetError("empty_source")
    timestamp = utc_now()
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM homework_sets WHERE created_by_user_id = ? AND status = ? ORDER BY id DESC LIMIT 1",
            (user_id, STATUS_COLLECTING),
        ).fetchone()
        if row is None:
            cursor = connection.execute(
                """
                INSERT INTO homework_sets (family_id, created_by_user_id, status, sources_json, created_at, updated_at)
                VALUES (?, ?, ?, '[]', ?, ?)
                """,
                (family_id, user_id, STATUS_COLLECTING, timestamp, timestamp),
            )
            set_id = int(cursor.lastrowid)
            sources: list[dict[str, str]] = []
        else:
            set_id = int(row["id"])
            sources = json.loads(row["sources_json"] or "[]")
        if len(sources) >= MAX_SOURCES:
            raise HomeworkSetError("too_many_sources")
        sources.append(source)
        connection.execute(
            "UPDATE homework_sets SET sources_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(sources, ensure_ascii=False), timestamp, set_id),
        )
        return connection.execute("SELECT * FROM homework_sets WHERE id = ?", (set_id,)).fetchone()


def set_control_message(set_id: int, chat_id: int | None, message_id: int | None) -> None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE homework_sets SET control_chat_id = ?, control_message_id = ?, updated_at = ? WHERE id = ?",
            (chat_id, message_id, utc_now(), set_id),
        )


def cancel_set(user_id: int, set_id: int) -> None:
    with get_connection() as connection:
        row = _get_set(connection, user_id, set_id)
        if row["status"] in (STATUS_SAVED, STATUS_CANCELLED):
            raise HomeworkSetError("set_not_active")
        connection.execute(
            "UPDATE homework_sets SET status = ?, updated_at = ? WHERE id = ?",
            (STATUS_CANCELLED, utc_now(), set_id),
        )
        _drop_set_assets(connection, set_id, keep=set())


def begin_processing(user_id: int, set_id: int, kind: str) -> list[dict[str, str]]:
    """Lock the set for extraction and return its sources."""
    if kind not in (*SUPPORTED_KINDS, KIND_MANUAL):
        raise HomeworkSetError("unsupported_kind")
    with get_connection() as connection:
        row = _get_set(connection, user_id, set_id)
        if row["status"] not in (STATUS_COLLECTING, STATUS_FAILED):
            raise HomeworkSetError("set_not_active")
        connection.execute(
            "UPDATE homework_sets SET status = ?, kind = ?, error = NULL, updated_at = ? WHERE id = ?",
            (STATUS_PROCESSING, kind, utc_now(), set_id),
        )
        return json.loads(row["sources_json"] or "[]")


def mark_failed(set_id: int, error: str) -> None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE homework_sets SET status = ?, error = ?, updated_at = ? WHERE id = ?",
            (STATUS_FAILED, error[:500], utc_now(), set_id),
        )


def _existing_words(connection, family_id: int) -> dict[str, int]:
    return {
        str(row["text"]).strip().lower(): int(row["id"])
        for row in connection.execute(
            "SELECT id, text FROM learning_items WHERE family_id = ? AND is_archived = 0 AND item_type = ? ORDER BY id",
            (family_id, ITEM_TYPE_WORD),
        ).fetchall()
    }


def _active_topics(connection, family_id: int) -> list[dict[str, object]]:
    return [
        {"id": int(row["id"]), "title": str(row["title"])}
        for row in connection.execute(
            "SELECT id, title FROM topics WHERE family_id = ? AND is_archived = 0 ORDER BY title COLLATE NOCASE",
            (family_id,),
        ).fetchall()
    ]


def _match_topic_title(title: str, topics: list[dict[str, object]]) -> str:
    for topic in topics:
        if str(topic["title"]).strip().lower() == title.strip().lower():
            return str(topic["title"])
    return title


# Photos of a set


ROLE_SOURCE = "source"
ROLE_CROP = "crop"
CROP_INSET = 0.06  # model boxes often clip a caption edge; trimming the border removes it
MIN_CROP_SIDE = 80
ABANDONED_DRAFT_DAYS = 30


def _store_photo(connection, set_id: int, content: bytes, role: str = ROLE_SOURCE) -> int:
    from .dictionary_editor import normalize_image

    local_path = store_homework_photo(set_id, normalize_image(content, MAX_PHOTO_SIDE))
    # Same connection as the caller: a second connection would wait on this one's write lock.
    asset_id = int(connection.execute(
        "INSERT INTO assets (asset_type, source_url, local_path, created_at) VALUES (?, NULL, ?, ?)",
        (ASSET_TYPE_IMAGE, local_path, utc_now()),
    ).lastrowid)
    connection.execute(
        "INSERT INTO homework_set_photos (homework_set_id, asset_id, created_at, role) VALUES (?, ?, ?, ?)",
        (set_id, asset_id, utc_now(), role),
    )
    return asset_id


def _set_photo_ids(connection, set_id: int, role: str | None = ROLE_SOURCE) -> list[int]:
    """Gallery pages by default; role=None also includes word crops."""
    query = "SELECT asset_id FROM homework_set_photos WHERE homework_set_id = ?"
    params: tuple = (set_id,)
    if role is not None:
        query += " AND role = ?"
        params = (set_id, role)
    return [int(row["asset_id"]) for row in connection.execute(query + " ORDER BY id", params).fetchall()]


def _asset_path(connection, asset_id: int) -> Path | None:
    asset = get_asset(asset_id, connection=connection)
    if asset is None or not asset["local_path"]:
        return None
    path = resolve_runtime_asset_path(str(asset["local_path"]))
    return path if path.is_file() else None


def _cut(connection, set_id: int, source_id: int, box: object, inset: float) -> int | None:
    """Cut a 0-1000 [y_min, x_min, y_max, x_max] box out of a gallery page; None when too small."""
    from PIL import Image

    if not isinstance(box, list) or len(box) != 4:
        raise HomeworkSetError("invalid_request")
    try:
        y_min, x_min, y_max, x_max = (max(0.0, min(1000.0, float(value))) for value in box)
    except (TypeError, ValueError) as exc:
        raise HomeworkSetError("invalid_request") from exc
    path = _asset_path(connection, source_id)
    if path is None:
        raise HomeworkSetError("image_not_found", 404)
    with Image.open(path) as image:
        width, height = image.size
        left, right = x_min * width / 1000, x_max * width / 1000
        top, bottom = y_min * height / 1000, y_max * height / 1000
        pad_x, pad_y = (right - left) * inset, (bottom - top) * inset
        area = (round(left + pad_x), round(top + pad_y), round(right - pad_x), round(bottom - pad_y))
        if min(area[2] - area[0], area[3] - area[1]) < MIN_CROP_SIDE:
            return None
        output = BytesIO()
        image.convert("RGB").crop(area).save(output, format="JPEG", quality=90)
    return _store_photo(connection, set_id, output.getvalue(), ROLE_CROP)


def _drop_set_assets(connection, set_id: int, keep: set[int]) -> None:
    """Delete the set's photos and crops except `keep`, with their files."""
    rows = connection.execute(
        """
        SELECT homework_set_photos.asset_id, assets.local_path FROM homework_set_photos
        LEFT JOIN assets ON assets.id = homework_set_photos.asset_id
        WHERE homework_set_photos.homework_set_id = ?
        """,
        (set_id,),
    ).fetchall()
    doomed = [row for row in rows if int(row["asset_id"]) not in keep]
    for row in doomed:
        asset_id = int(row["asset_id"])
        connection.execute("DELETE FROM homework_set_photos WHERE homework_set_id = ? AND asset_id = ?", (set_id, asset_id))
        connection.execute("DELETE FROM telegram_asset_file_cache WHERE asset_id = ?", (asset_id,))
        connection.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
    delete_unreferenced_files(connection, [row["local_path"] for row in doomed])


def _attached_photo_ids(connection, set_id: int) -> set[int]:
    return {
        int(row["asset_id"])
        for row in connection.execute(
            """
            SELECT homework_set_task_assets.asset_id FROM homework_set_task_assets
            JOIN homework_set_tasks ON homework_set_tasks.id = homework_set_task_assets.task_id
            WHERE homework_set_tasks.homework_set_id = ?
            """,
            (set_id,),
        ).fetchall()
    }


def cleanup_abandoned_sets(max_age_days: int = ABANDONED_DRAFT_DAYS) -> int:
    """Cancel drafts and batches left untouched for a long time and delete their photos."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat(timespec="seconds")
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT id FROM homework_sets WHERE status IN (?, ?, ?, ?) AND updated_at < ?",
            (STATUS_COLLECTING, STATUS_PROCESSING, STATUS_DRAFT, STATUS_FAILED, cutoff),
        ).fetchall()
        for row in rows:
            connection.execute(
                "UPDATE homework_sets SET status = ?, updated_at = ? WHERE id = ?",
                (STATUS_CANCELLED, utc_now(), int(row["id"])),
            )
            _drop_set_assets(connection, int(row["id"]), keep=set())
    return len(rows)


def crop_set_photo(user_id: int, set_id: int, source_id: object, box: object) -> dict[str, object]:
    """A word picture cut by hand from one of the set's pages."""
    with get_connection() as connection:
        row = _get_set(connection, user_id, set_id)
        if row["status"] != STATUS_DRAFT:
            raise HomeworkSetError("draft_not_available", 409)
        try:
            source = int(source_id)
        except (TypeError, ValueError) as exc:
            raise HomeworkSetError("invalid_request") from exc
        if source not in _set_photo_ids(connection, set_id):
            raise HomeworkSetError("image_not_found", 404)
        asset_id = _cut(connection, set_id, source, box, inset=0)
    if asset_id is None:
        raise HomeworkSetError("crop_too_small")
    return {"id": asset_id}


def add_word_picture(user_id: int, set_id: int, content: bytes) -> dict[str, object]:
    """A word picture uploaded from the phone instead of cut from a page."""
    with get_connection() as connection:
        row = _get_set(connection, user_id, set_id)
        if row["status"] != STATUS_DRAFT:
            raise HomeworkSetError("draft_not_available", 409)
        try:
            asset_id = _store_photo(connection, set_id, content, ROLE_CROP)
        except HomeworkSetError:
            raise
        except Exception as exc:
            raise HomeworkSetError("invalid_image") from exc
    return {"id": asset_id}


def store_source_photos(set_id: int, images: list[bytes]) -> list[int]:
    """Keep the forwarded photos once per set (a retry does not duplicate them); bad images are skipped."""
    with get_connection() as connection:
        if _set_photo_ids(connection, set_id):
            return _set_photo_ids(connection, set_id)
        for content in images:
            try:
                _store_photo(connection, set_id, content)
            except Exception:  # one unreadable photo must not lose the rest
                logger.warning("Skipped an unreadable homework photo: set=%s", set_id, exc_info=True)
        return _set_photo_ids(connection, set_id)


def add_set_photo(user_id: int, set_id: int, content: bytes) -> dict[str, object]:
    """Upload a photo into the set's gallery from the editor."""
    with get_connection() as connection:
        row = _get_set(connection, user_id, set_id)
        if row["status"] not in (STATUS_DRAFT, STATUS_SAVED, STATUS_ARCHIVED):
            raise HomeworkSetError("set_not_active", 409)
        try:
            asset_id = _store_photo(connection, set_id, content)
        except HomeworkSetError:
            raise
        except Exception as exc:
            raise HomeworkSetError("invalid_image") from exc
    return {"id": asset_id}


def set_photo_path(user_id: int, set_id: int, asset_id: int) -> Path:
    with get_connection() as connection:
        _get_set(connection, user_id, set_id)
        if asset_id not in _set_photo_ids(connection, set_id, role=None):
            raise HomeworkSetError("image_not_found", 404)
        path = _asset_path(connection, asset_id)
    if path is None:
        raise HomeworkSetError("image_not_found", 404)
    return path


# Draft content: an ordered list of tasks, each with its own words and photos


def _new_task(kind: str, *, title: str = "", instructions: str = "", items: list | None = None, photos: list | None = None) -> dict[str, object]:
    return {"kind": kind, "title": title, "instructions": instructions, "enabled": True, "items": items or [], "photos": photos or []}


def _tutor_text(sources: list[dict[str, str]]) -> str:
    return "\n\n".join(source["text"] for source in sources if source.get("text"))[:MAX_INSTRUCTIONS_LENGTH]


def _default_title(row) -> str:
    return translate_for_user(
        int(row["created_by_user_id"]),
        "homework_import.default_title",
        date=datetime.now(timezone.utc).strftime("%d.%m.%Y"),
    )


def _write_draft(connection, row, draft: dict[str, object]) -> None:
    connection.execute(
        "UPDATE homework_sets SET status = ?, title = COALESCE(title, ?), draft_json = ?, updated_at = ? WHERE id = ?",
        (STATUS_DRAFT, _default_title(row), json.dumps(draft, ensure_ascii=False), utc_now(), int(row["id"])),
    )


def _draft_tasks(row, items: list[dict[str, object]], verbs: list[dict[str, object]] | None = None) -> list[dict[str, object]]:
    """Words, then verbs, then the tutor's forwarded text as a note the parent can keep, edit, or switch off."""
    tasks = [_new_task(TASK_WORDS, items=items)] if items or not verbs else []
    if verbs:
        tasks.append(_new_task(TASK_VERBS, items=verbs))
    text = _tutor_text(json.loads(row["sources_json"] or "[]"))
    if text:
        tasks.append(_new_task(TASK_NOTE, title=translate_for_user(int(row["created_by_user_id"]), "homework_task.tutor_text"), instructions=text))
    return tasks


def _word_has_picture(connection, word_id: int) -> bool:
    return get_learning_item_asset(word_id, role=PRIMARY_IMAGE_ROLE, connection=connection) is not None


def store_extraction(set_id: int, result: ExtractionResult, picture_ids: list[int] | None = None) -> dict[str, int]:
    """Turn model output into an editable draft, marking known words and cutting word pictures.

    picture_ids[n - 1] is the gallery page the model saw as "Picture n"; without it no pictures are cut.
    """
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM homework_sets WHERE id = ?", (set_id,)).fetchone()
        family_id = int(row["family_id"])
        existing = _existing_words(connection, family_id)
        topics = _active_topics(connection, family_id)
        items = []
        for entry in result.items:
            existing_id = existing.get(str(entry["en"]).lower())
            item = {
                "en": entry["en"],
                "ru": entry["ru"],
                "topic": _match_topic_title(str(entry["topic"]), topics) if entry["topic"] else "",
                "existing_id": existing_id,
                "current_image": bool(existing_id and _word_has_picture(connection, existing_id)),
            }
            picture = entry.get("picture")
            if picture_ids and isinstance(picture, int) and picture <= len(picture_ids):
                source = picture_ids[picture - 1]
                try:
                    crop = _cut(connection, set_id, source, entry.get("box"), inset=CROP_INSET)
                except HomeworkSetError:
                    crop = None
                if crop is not None:
                    item["image_id"] = crop
                    item["crop"] = {"photo": source, "box": entry["box"]}
            items.append(item)
        verbs = []
        for verb in result.verbs:
            existing_id = find_family_verb(connection, family_id, verb["base"])
            verbs.append({
                **verb,
                "topic": _match_topic_title(DEFAULT_VERB_TOPIC, topics),
                "existing_id": existing_id,
            })
        _write_draft(connection, row, {"model": result.model, "tasks": _draft_tasks(row, items, verbs)})
    entries = [*items, *verbs]
    known = sum(1 for item in entries if item["existing_id"])
    return {"total": len(entries), "words": len(items), "verbs": len(verbs), "new": len(entries) - known, "existing": known}


def store_manual_draft(set_id: int) -> None:
    """A draft without AI: an empty words task plus the forwarded text; photos wait in the gallery."""
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM homework_sets WHERE id = ?", (set_id,)).fetchone()
        _write_draft(connection, row, {"model": None, "tasks": _draft_tasks(row, [])})


def create_empty_draft(user_id: int) -> dict[str, object]:
    """Start a homework draft from the editor, without forwarding anything."""
    family_id = _family_id(user_id)
    timestamp = utc_now()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO homework_sets (family_id, created_by_user_id, status, sources_json, created_at, updated_at)
            VALUES (?, ?, ?, '[]', ?, ?)
            """,
            (family_id, user_id, STATUS_PROCESSING, timestamp, timestamp),
        )
        set_id = int(cursor.lastrowid)
        row = connection.execute("SELECT * FROM homework_sets WHERE id = ?", (set_id,)).fetchone()
        _write_draft(connection, row, {"model": None, "tasks": [_new_task(TASK_WORDS)]})
    return {"id": set_id}


def _tasks_of_draft(draft: dict[str, object]) -> list[dict[str, object]]:
    """Drafts stored before tasks existed held a flat word list."""
    if isinstance(draft.get("tasks"), list):
        return draft["tasks"]
    return [_new_task(TASK_WORDS, items=list(draft.get("items") or []))]


def _task_kinds(user_id: int) -> list[dict[str, str]]:
    return [{"code": kind, "label": translate_for_user(user_id, f"homework_task.kind.{kind}")} for kind in TASK_KINDS]


def _display_name(member) -> str:
    for field in ("first_name", "username", "last_name"):
        if member[field]:
            return str(member[field])
    return str(member["telegram_user_id"])


def _assignment_defaults(user_id: int, family_id: int) -> dict[str, object]:
    """Recipient and mode of the author's last assignment, so assigning is usually one tap."""
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT assigned_to_user_id, training_mode FROM homework_assignments
            WHERE assigned_by_user_id = ? AND family_id = ? ORDER BY id DESC LIMIT 1
            """,
            (user_id, family_id),
        ).fetchone()
    if row is None:
        return {"recipient": None, "mode": TRAINING_MODES[0]}
    return {"recipient": int(row["assigned_to_user_id"]), "mode": str(row["training_mode"])}


def get_draft(user_id: int, set_id: int) -> dict[str, object]:
    family_id = _family_id(user_id)
    with get_connection() as connection:
        row = _get_set(connection, user_id, set_id)
        if row["status"] != STATUS_DRAFT:
            raise HomeworkSetError("draft_not_available", 409)
        draft = json.loads(row["draft_json"] or "{}")
        topics = _active_topics(connection, family_id)
        photos = _set_photo_ids(connection, set_id)
    members = [
        {"id": int(member["telegram_user_id"]), "name": _display_name(member)}
        for member in list_family_members(family_id)
    ]
    members.sort(key=lambda member: member["id"] == user_id)
    return {
        "set": {"id": set_id, "title": str(row["title"] or ""), "kind": str(row["kind"] or KIND_WORDS)},
        "tasks": _tasks_of_draft(draft),
        "photos": photos,
        "task_kinds": _task_kinds(user_id),
        "topics": topics,
        "members": members,
        "defaults": _assignment_defaults(user_id, family_id),
        "modes": [{"code": mode, "label": translate_for_user(user_id, f"training.mode.{mode}")} for mode in TRAINING_MODES],
    }


def update_draft(user_id: int, set_id: int, payload: dict[str, object]) -> dict[str, object]:
    """Keep the editor's unsaved work (title and tasks) so closing the page loses nothing."""
    raw_tasks = payload.get("tasks")
    if not isinstance(raw_tasks, list) or not all(isinstance(task, dict) and task.get("kind") in TASK_KINDS for task in raw_tasks):
        raise HomeworkSetError("invalid_request")
    with get_connection() as connection:
        row = _get_set(connection, user_id, set_id)
        if row["status"] != STATUS_DRAFT:
            raise HomeworkSetError("draft_not_available", 409)
        draft = json.loads(row["draft_json"] or "{}")
        draft["tasks"] = raw_tasks
        title = _clean(payload.get("title"))
        connection.execute(
            "UPDATE homework_sets SET title = COALESCE(?, title), draft_json = ?, updated_at = ? WHERE id = ?",
            (title or None, json.dumps(draft, ensure_ascii=False), utc_now(), set_id),
        )
    return {"saved": True}


def _resolve_topic_id(user_id: int, family_id: int, title: str, cache: dict[str, int]) -> int | None:
    key = title.strip().lower()
    if not key:
        return None
    if key not in cache:
        with get_connection() as connection:
            for topic in _active_topics(connection, family_id):
                cache.setdefault(str(topic["title"]).strip().lower(), int(topic["id"]))
        if key not in cache:
            cache[key] = int(create_teacher_topic(user_id, family_id, title.strip())["id"])
    return cache[key]


def _link_word_to_topic(connection, topic_id: int, word_id: int) -> None:
    linked = connection.execute(
        "SELECT 1 FROM topic_items WHERE topic_id = ? AND learning_item_id = ?",
        (topic_id, word_id),
    ).fetchone()
    if linked is None:
        connection.execute("INSERT INTO topic_items (topic_id, learning_item_id) VALUES (?, ?)", (topic_id, word_id))


def _ensure_word(user_id: int, family_id: int, english: str, russian: str, topic: str, topic_cache: dict[str, int]) -> tuple[int, bool]:
    """Reuse the family word with this text or create it under the topic; return (id, created)."""
    topic_id = _resolve_topic_id(user_id, family_id, topic, topic_cache)
    with get_connection() as connection:
        word_id = _existing_words(connection, family_id).get(english.lower())
    if word_id is not None:
        if topic_id is not None:
            with get_connection() as connection:
                _link_word_to_topic(connection, topic_id, word_id)
        return word_id, False
    if topic_id is None:
        raise HomeworkSetError("topic_required")
    word_id = int(create_teacher_topic_item(user_id, family_id, topic_id, english)["learning_item_id"])
    if russian:
        timestamp = utc_now()
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO learning_item_translations
                    (learning_item_id, language_code, translation_text, created_at, updated_at)
                VALUES (?, 'ru', ?, ?, ?)
                """,
                (word_id, russian, timestamp, timestamp),
            )
    return word_id, True


def _ensure_verb(user_id: int, family_id: int, entry: dict[str, object], topic_cache: dict[str, int]) -> tuple[int, bool]:
    """Reuse the family verb with this base form or create it with its forms; return (id, created)."""
    try:
        base, past, participle = validate_forms(entry.get("base"), entry.get("past"), entry.get("participle"))
    except VerbFormsError as exc:
        raise HomeworkSetError("invalid_verb_forms") from exc
    topic_id = _resolve_topic_id(user_id, family_id, _clean(entry.get("topic")) or DEFAULT_VERB_TOPIC, topic_cache)
    with get_connection() as connection:
        verb_id = find_family_verb(connection, family_id, base)
        if verb_id is not None:
            _link_word_to_topic(connection, int(topic_id), verb_id)
            return verb_id, False
    return create_family_verb(family_id, int(topic_id), base, past, participle, _clean(entry.get("ru"))), True


def _clean_instructions(value: object) -> str:
    lines = [" ".join(line.split()) for line in str(value or "").replace("\r", "").split("\n")]
    return "\n".join(lines).strip()[:MAX_INSTRUCTIONS_LENGTH]


def _payload_tasks(payload: dict[str, object], photo_ids: list[int]) -> list[dict[str, object]]:
    """Validate the enabled tasks of a save request; a flat `items` list means one words task."""
    raw_tasks = payload.get("tasks")
    if raw_tasks is None and isinstance(payload.get("items"), list):
        raw_tasks = [{"kind": TASK_WORDS, "items": payload["items"]}]
    if not isinstance(raw_tasks, list):
        raise HomeworkSetError("invalid_request")
    tasks = []
    for raw in raw_tasks:
        if not isinstance(raw, dict) or not raw.get("enabled", True):
            continue
        kind = str(raw.get("kind") or "")
        if kind not in TASK_KINDS:
            raise HomeworkSetError("invalid_task_kind")
        items = raw.get("items") if kind in DRILL_KINDS else []
        photos = raw.get("photos") or []
        if not isinstance(items, list) or not isinstance(photos, list):
            raise HomeworkSetError("invalid_request")
        attached = []
        for photo in photos:
            try:
                asset_id = int(photo)
            except (TypeError, ValueError) as exc:
                raise HomeworkSetError("invalid_request") from exc
            if asset_id not in photo_ids:
                raise HomeworkSetError("image_not_found", 404)
            if asset_id not in attached:
                attached.append(asset_id)
        tasks.append({
            "kind": kind,
            "title": _clean(raw.get("title")),
            "instructions": _clean_instructions(raw.get("instructions")),
            "items": [
                item for item in items
                if isinstance(item, dict) and item.get("include", True) and _clean(item.get("base" if kind == TASK_VERBS else "en"))
            ],
            "photos": attached,
        })
    # A task with nothing in it would only be an empty line for the learner.
    return [task for task in tasks if task["items"] or task["photos"] or task["instructions"] or (task["kind"] not in DRILL_KINDS and task["title"])]


def _insert_task(connection, set_id: int, order: int, task: dict[str, object]) -> int:
    cursor = connection.execute(
        """
        INSERT INTO homework_set_tasks (homework_set_id, task_order, task_kind, title, instructions, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (set_id, order, task["kind"], task["title"] or None, task["instructions"] or None, utc_now()),
    )
    task_id = int(cursor.lastrowid)
    connection.executemany(
        "INSERT INTO homework_set_task_assets (task_id, asset_id, sort_order) VALUES (?, ?, ?)",
        [(task_id, asset_id, position) for position, asset_id in enumerate(task["photos"])],
    )
    return task_id


def _entry_picture(entry: dict[str, object], set_asset_ids: set[int]) -> int | None:
    try:
        image_id = int(entry["image_id"]) if entry.get("image_id") is not None else None
    except (TypeError, ValueError) as exc:
        raise HomeworkSetError("invalid_request") from exc
    if image_id is not None and image_id not in set_asset_ids:
        raise HomeworkSetError("image_not_found", 404)
    return image_id


def _apply_word_pictures(pictures: list[tuple[int, int, bool]]) -> int:
    """Copy chosen crops into the dictionary as word pictures; returns how many words got one."""
    from .dictionary_editor import store_word_image

    applied = 0
    for word_id, image_id, replace in pictures:
        with get_connection() as connection:
            if not replace and _word_has_picture(connection, word_id):
                continue
            path = _asset_path(connection, image_id)
        if path is None:
            continue
        store_word_image(word_id, path.read_bytes())
        applied += 1
    return applied


def save_draft(user_id: int, set_id: int, payload: dict[str, object]) -> dict[str, object]:
    """Store the draft's tasks: create or reuse words, attach photos, optionally assign homework."""
    family_id = _family_id(user_id)
    with get_connection() as connection:
        row = _get_set(connection, user_id, set_id)
        if row["status"] != STATUS_DRAFT:
            raise HomeworkSetError("draft_not_available", 409)
        photo_ids = _set_photo_ids(connection, set_id)
        set_asset_ids = set(_set_photo_ids(connection, set_id, role=None))
    title = _clean(payload.get("title")) or str(row["title"] or "")
    tasks = _payload_tasks(payload, photo_ids)
    if not tasks:
        raise HomeworkSetError("draft_empty")
    mode = str(payload.get("mode") or "easy")
    if mode not in TRAINING_MODES:
        raise HomeworkSetError("invalid_mode")
    assign_to = payload.get("assign_to")
    member_ids = {int(member["telegram_user_id"]) for member in list_family_members(family_id)}
    if assign_to is not None:
        try:
            assign_to = int(assign_to)
        except (TypeError, ValueError) as exc:
            raise HomeworkSetError("invalid_recipient") from exc
        if assign_to not in member_ids:
            raise HomeworkSetError("invalid_recipient")

    # Words are created before the set rows are written, since that uses its own connections.
    topic_cache: dict[str, int] = {}
    word_ids: list[int] = []
    pictures: list[tuple[int, int, bool]] = []
    created = 0
    for task in tasks:
        task_word_ids = []
        for entry in task["items"]:
            if task["kind"] == TASK_VERBS:
                word_id, is_new = _ensure_verb(user_id, family_id, entry, topic_cache)
                created += int(is_new)
                if word_id not in word_ids:
                    word_ids.append(word_id)
                    task_word_ids.append(word_id)
                continue
            word_id, is_new = _ensure_word(user_id, family_id, _clean(entry.get("en")), _clean(entry.get("ru")), _clean(entry.get("topic")), topic_cache)
            created += int(is_new)
            picture = _entry_picture(entry, set_asset_ids)
            if picture is not None:
                # A known word keeps its picture unless the parent chose a new one for it.
                pictures.append((word_id, picture, is_new or bool(entry.get("image_user"))))
            if word_id not in word_ids:  # a word drilled once per homework, in its first task
                word_ids.append(word_id)
                task_word_ids.append(word_id)
        task["word_ids"] = task_word_ids

    with get_connection() as connection:
        connection.execute("DELETE FROM homework_set_items WHERE homework_set_id = ?", (set_id,))
        order = 0
        for task_order, task in enumerate(tasks):
            task_id = _insert_task(connection, set_id, task_order, task)
            for word_id in task["word_ids"]:
                connection.execute(
                    "INSERT INTO homework_set_items (homework_set_id, item_kind, learning_item_id, item_order, task_id) VALUES (?, 'word', ?, ?, ?)",
                    (set_id, word_id, order, task_id),
                )
                order += 1
        timestamp = utc_now()
        connection.execute(
            "UPDATE homework_sets SET status = ?, title = ?, saved_at = ?, updated_at = ? WHERE id = ?",
            (STATUS_SAVED, title, timestamp, timestamp, set_id),
        )

    # Only words and paper work can be finished; a homework of notes alone would never end.
    pictured = _apply_word_pictures(pictures)
    # Word pictures are copies now; only photos attached to a task are still needed.
    with get_connection() as connection:
        _drop_set_assets(connection, set_id, keep=_attached_photo_ids(connection, set_id))

    assignment_id = None
    if assign_to is not None and (word_ids or any(task["kind"] == TASK_PAPER for task in tasks)):
        assignment_id = create_homework_assignment(
            family_id, user_id, assign_to, word_ids,
            title=title, training_mode=mode, homework_set_id=set_id,
        )
    return {
        "saved": True,
        "title": title,
        "task_count": len(tasks),
        "word_count": len(word_ids),
        "pictured_words": pictured,
        "created_words": created,
        "assignment_id": assignment_id,
        "assigned_to": assign_to if assignment_id else None,
    }


def _require_saved(connection, user_id: int, set_id: int):
    """A saved set, archived or not; drafts and cancelled batches are not sets yet."""
    row = _get_set(connection, user_id, set_id)
    if row["status"] not in (STATUS_SAVED, STATUS_ARCHIVED):
        raise HomeworkSetError("set_not_found", 404)
    return row


def list_sets(user_id: int, *, archived: bool = False) -> list[dict[str, object]]:
    family_id = _family_id(user_id)
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT homework_sets.id, homework_sets.title, homework_sets.saved_at,
                   (SELECT COUNT(*) FROM homework_set_items WHERE homework_set_id = homework_sets.id) AS item_count,
                   (SELECT COUNT(*) FROM homework_assignments WHERE homework_set_id = homework_sets.id) AS assignment_count,
                   (SELECT COUNT(*) FROM homework_assignments WHERE homework_set_id = homework_sets.id AND status = 'active') AS active_count
            FROM homework_sets
            WHERE family_id = ? AND status = ?
            ORDER BY homework_sets.saved_at DESC, homework_sets.id DESC
            """,
            (family_id, STATUS_ARCHIVED if archived else STATUS_SAVED),
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "title": str(row["title"] or ""),
            "saved_at": str(row["saved_at"] or ""),
            "item_count": int(row["item_count"]),
            "assignment_count": int(row["assignment_count"]),
            "active_count": int(row["active_count"]),
        }
        for row in rows
    ]


def _member_names(family_id: int) -> dict[int, str]:
    return {int(member["telegram_user_id"]): _display_name(member) for member in list_family_members(family_id)}


def _saved_tasks(connection, set_id: int) -> list[dict[str, object]]:
    tasks = []
    for task in connection.execute(
        "SELECT * FROM homework_set_tasks WHERE homework_set_id = ? ORDER BY task_order, id", (set_id,)
    ).fetchall():
        photos = [
            int(row["asset_id"])
            for row in connection.execute(
                "SELECT asset_id FROM homework_set_task_assets WHERE task_id = ? ORDER BY sort_order", (int(task["id"]),)
            ).fetchall()
        ]
        tasks.append({
            "id": int(task["id"]),
            "kind": str(task["task_kind"]),
            "title": str(task["title"] or ""),
            "instructions": str(task["instructions"] or ""),
            "photos": photos,
        })
    return tasks


def _words_task_id(connection, set_id: int) -> int:
    """The first words task of a saved set, created if the set has none (e.g. only paper work)."""
    row = connection.execute(
        "SELECT id FROM homework_set_tasks WHERE homework_set_id = ? AND task_kind = ? ORDER BY task_order, id LIMIT 1",
        (set_id, TASK_WORDS),
    ).fetchone()
    if row is not None:
        return int(row["id"])
    next_order = connection.execute(
        "SELECT COALESCE(MAX(task_order), -1) + 1 FROM homework_set_tasks WHERE homework_set_id = ?", (set_id,)
    ).fetchone()[0]
    return _insert_task(connection, set_id, int(next_order), {"kind": TASK_WORDS, "title": "", "instructions": "", "photos": []})


def get_set(user_id: int, set_id: int) -> dict[str, object]:
    family_id = _family_id(user_id)
    with get_connection() as connection:
        row = _require_saved(connection, user_id, set_id)
        tasks = _saved_tasks(connection, set_id)
        words = connection.execute(
            """
            SELECT learning_items.id, learning_items.text, learning_items.is_archived, homework_set_items.task_id,
                   learning_items.item_type, learning_items.details_json,
                   (SELECT translation_text FROM learning_item_translations
                    WHERE learning_item_id = learning_items.id AND language_code = 'ru') AS ru
            FROM homework_set_items
            JOIN learning_items ON learning_items.id = homework_set_items.learning_item_id
            WHERE homework_set_items.homework_set_id = ?
            ORDER BY homework_set_items.item_order
            """,
            (set_id,),
        ).fetchall()
        assignments = connection.execute(
            """
            SELECT id, assigned_to_user_id, status, training_mode, created_at
            FROM homework_assignments WHERE homework_set_id = ? ORDER BY id DESC
            """,
            (set_id,),
        ).fetchall()
    names = _member_names(family_id)
    members = [{"id": member_id, "name": name} for member_id, name in names.items()]
    members.sort(key=lambda member: member["id"] == user_id)
    with get_connection() as connection:
        topics = _active_topics(connection, family_id)
    return {
        "set": {
            "id": set_id,
            "title": str(row["title"] or ""),
            "saved_at": str(row["saved_at"] or ""),
            "archived": row["status"] == STATUS_ARCHIVED,
        },
        "topics": topics,
        "tasks": tasks,
        "task_kinds": _task_kinds(user_id),
        "words": [
            {
                "id": int(word["id"]), "text": _display_text(word), "ru": str(word["ru"] or ""),
                "archived": bool(word["is_archived"]), "task_id": int(word["task_id"]) if word["task_id"] is not None else None,
            }
            for word in words
        ],
        "assignments": [
            {
                "id": int(assignment["id"]),
                "to": names.get(int(assignment["assigned_to_user_id"]), str(assignment["assigned_to_user_id"])),
                "status": str(assignment["status"]),
                "mode": translate_for_user(user_id, f"training.mode.{assignment['training_mode']}"),
                "created_at": str(assignment["created_at"]),
            }
            for assignment in assignments
        ],
        "members": members,
        "defaults": _assignment_defaults(user_id, family_id),
        "modes": [{"code": mode, "label": translate_for_user(user_id, f"training.mode.{mode}")} for mode in TRAINING_MODES],
    }


def _display_text(word) -> str:
    """A verb is listed with all three forms: "go – went – gone"."""
    forms = load_forms(word["details_json"]) if word["item_type"] != ITEM_TYPE_WORD else None
    return " – ".join([str(word["text"]), *forms]) if forms else str(word["text"])


def rename_set(user_id: int, set_id: int, title: object) -> dict[str, object]:
    """Rename the set and every homework assigned from it, so the learner sees the new name."""
    clean_title = _clean(title)
    if not clean_title:
        raise HomeworkSetError("text_required")
    with get_connection() as connection:
        _require_saved(connection, user_id, set_id)
        timestamp = utc_now()
        connection.execute(
            "UPDATE homework_sets SET title = ?, updated_at = ? WHERE id = ?",
            (clean_title, timestamp, set_id),
        )
        connection.execute(
            "UPDATE homework_assignments SET title = ?, updated_at = ? WHERE homework_set_id = ?",
            (clean_title, timestamp, set_id),
        )
    return {"id": set_id, "title": clean_title}


def assign_set(user_id: int, set_id: int, assign_to: object, mode: object) -> dict[str, object]:
    """Assign the set's still-active words again as a new homework."""
    family_id = _family_id(user_id)
    training_mode = str(mode or "easy")
    if training_mode not in TRAINING_MODES:
        raise HomeworkSetError("invalid_mode")
    try:
        recipient = int(assign_to)
    except (TypeError, ValueError) as exc:
        raise HomeworkSetError("invalid_recipient") from exc
    if recipient not in _member_names(family_id):
        raise HomeworkSetError("invalid_recipient")
    with get_connection() as connection:
        row = _require_saved(connection, user_id, set_id)
        word_ids = [
            int(item["learning_item_id"])
            for item in connection.execute(
                """
                SELECT homework_set_items.learning_item_id
                FROM homework_set_items
                JOIN learning_items ON learning_items.id = homework_set_items.learning_item_id
                WHERE homework_set_items.homework_set_id = ? AND learning_items.is_archived = 0
                ORDER BY homework_set_items.item_order
                """,
                (set_id,),
            ).fetchall()
        ]
        has_paper = connection.execute(
            "SELECT 1 FROM homework_set_tasks WHERE homework_set_id = ? AND task_kind = ?", (set_id, TASK_PAPER)
        ).fetchone() is not None
    if not word_ids and not has_paper:
        raise HomeworkSetError("set_empty")
    title = str(row["title"] or "")
    assignment_id = create_homework_assignment(
        family_id, user_id, recipient, word_ids,
        title=title, training_mode=training_mode, homework_set_id=set_id,
    )
    return {"assignment_id": assignment_id, "assigned_to": recipient, "title": title, "word_count": len(word_ids)}


def list_drafts(user_id: int) -> list[dict[str, object]]:
    """Unsaved drafts of the family, so one can be reopened without the bot message."""
    family_id = _family_id(user_id)
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT id, title, draft_json, updated_at FROM homework_sets WHERE family_id = ? AND status = ? ORDER BY updated_at DESC, id DESC",
            (family_id, STATUS_DRAFT),
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "title": str(row["title"] or ""),
            "updated_at": str(row["updated_at"] or ""),
            "item_count": sum(
                len(task.get("items") or [])
                for task in _tasks_of_draft(json.loads(row["draft_json"] or "{}"))
                if task.get("kind") in DRILL_KINDS
            ),
        }
        for row in rows
    ]


def _set_status(user_id: int, set_id: int, status: str) -> dict[str, object]:
    with get_connection() as connection:
        _require_saved(connection, user_id, set_id)
        connection.execute(
            "UPDATE homework_sets SET status = ?, updated_at = ? WHERE id = ?",
            (status, utc_now(), set_id),
        )
    return {"id": set_id, "archived": status == STATUS_ARCHIVED}


def archive_set(user_id: int, set_id: int) -> dict[str, object]:
    """Hide the set from the main list; its homework is not touched."""
    return _set_status(user_id, set_id, STATUS_ARCHIVED)


def restore_set(user_id: int, set_id: int) -> dict[str, object]:
    return _set_status(user_id, set_id, STATUS_SAVED)


def add_set_word(user_id: int, set_id: int, payload: dict[str, object]) -> dict[str, object]:
    """Add an existing family word (word_id) or a new one (en, ru, topic); affects future assignments only."""
    family_id = _family_id(user_id)
    with get_connection() as connection:
        _require_saved(connection, user_id, set_id)
    if payload.get("word_id") is not None:
        try:
            word_id = int(payload["word_id"])
        except (TypeError, ValueError) as exc:
            raise HomeworkSetError("invalid_request") from exc
        with get_connection() as connection:
            found = connection.execute(
                "SELECT 1 FROM learning_items WHERE id = ? AND family_id = ? AND is_archived = 0",
                (word_id, family_id),
            ).fetchone()
        if found is None:
            raise HomeworkSetError("word_not_found", 404)
    else:
        english = _clean(payload.get("en"))
        if not english:
            raise HomeworkSetError("text_required")
        word_id, _ = _ensure_word(user_id, family_id, english, _clean(payload.get("ru")), _clean(payload.get("topic")), {})
    with get_connection() as connection:
        _append_set_items(connection, set_id, [word_id])
    return get_set(user_id, set_id)


def add_set_topic(user_id: int, set_id: int, topic_id: object) -> dict[str, object]:
    """Add every active word and verb of a family topic to a saved set; ones already there are kept once."""
    family_id = _family_id(user_id)
    try:
        topic_id = int(topic_id)
    except (TypeError, ValueError) as exc:
        raise HomeworkSetError("invalid_request") from exc
    with get_connection() as connection:
        _require_saved(connection, user_id, set_id)
        topic = connection.execute(
            "SELECT 1 FROM topics WHERE id = ? AND family_id = ? AND is_archived = 0", (topic_id, family_id)
        ).fetchone()
        if topic is None:
            raise HomeworkSetError("topic_not_found", 404)
        word_ids = [
            int(row["id"])
            for row in connection.execute(
                """
                SELECT learning_items.id FROM topic_items
                JOIN learning_items ON learning_items.id = topic_items.learning_item_id
                WHERE topic_items.topic_id = ? AND learning_items.family_id = ? AND learning_items.is_archived = 0
                ORDER BY topic_items.id
                """,
                (topic_id, family_id),
            ).fetchall()
        ]
        _append_set_items(connection, set_id, word_ids)
    return get_set(user_id, set_id)


def _append_set_items(connection, set_id: int, word_ids: list[int]) -> None:
    """Append words to a saved set; verbs go to its verbs task when it has one, the rest to the words task."""
    present = {
        int(row["learning_item_id"])
        for row in connection.execute(
            "SELECT learning_item_id FROM homework_set_items WHERE homework_set_id = ?", (set_id,)
        ).fetchall()
    }
    next_order = int(connection.execute(
        "SELECT COALESCE(MAX(item_order), -1) + 1 FROM homework_set_items WHERE homework_set_id = ?", (set_id,)
    ).fetchone()[0])
    verbs_task = connection.execute(
        "SELECT id FROM homework_set_tasks WHERE homework_set_id = ? AND task_kind = ? ORDER BY task_order, id LIMIT 1",
        (set_id, TASK_VERBS),
    ).fetchone()
    words_task_id = None
    for word_id in word_ids:
        if word_id in present:
            continue
        item_type = connection.execute("SELECT item_type FROM learning_items WHERE id = ?", (word_id,)).fetchone()[0]
        if item_type != ITEM_TYPE_WORD and verbs_task is not None:
            task_id = int(verbs_task["id"])
        else:
            if words_task_id is None:
                words_task_id = _words_task_id(connection, set_id)
            task_id = words_task_id
        connection.execute(
            "INSERT INTO homework_set_items (homework_set_id, item_kind, learning_item_id, item_order, task_id) VALUES (?, 'word', ?, ?, ?)",
            (set_id, word_id, next_order, task_id),
        )
        present.add(word_id)
        next_order += 1


def remove_set_word(user_id: int, set_id: int, word_id: int) -> dict[str, object]:
    with get_connection() as connection:
        _require_saved(connection, user_id, set_id)
        connection.execute(
            "DELETE FROM homework_set_items WHERE homework_set_id = ? AND learning_item_id = ?",
            (set_id, word_id),
        )
    return get_set(user_id, set_id)


def list_assignments(user_id: int) -> dict[str, list[dict[str, object]]]:
    """Family homework for the parent: active with progress, then finished and cancelled."""
    family_id = _family_id(user_id)
    names = _member_names(family_id)
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT homework_assignments.id, homework_assignments.title, homework_assignments.status,
                   homework_assignments.training_mode, homework_assignments.assigned_to_user_id,
                   homework_assignments.created_at, homework_assignments.completed_at,
                   homework_assignments.updated_at, homework_assignments.homework_set_id,
                   (SELECT COUNT(*) FROM homework_assignment_items
                    WHERE homework_assignment_id = homework_assignments.id) AS total,
                   (SELECT COUNT(*) FROM training_session_items
                    WHERE session_id = (SELECT MAX(id) FROM training_sessions
                                        WHERE family_homework_assignment_id = homework_assignments.id)
                      AND is_completed = 1) AS done,
                   homework_assignments.words_completed_at,
                   (SELECT COUNT(*) FROM homework_set_tasks
                    WHERE homework_set_id = homework_assignments.homework_set_id AND task_kind = 'paper') AS paper_total,
                   (SELECT COUNT(*) FROM homework_assignment_task_done
                    WHERE homework_assignment_id = homework_assignments.id) AS paper_done
            FROM homework_assignments
            WHERE family_id = ?
            ORDER BY homework_assignments.id DESC
            """,
            (family_id,),
        ).fetchall()
    def serialize(row) -> dict[str, object]:
        total = int(row["total"])
        words_finished = row["status"] == "completed" or row["words_completed_at"] is not None
        done = total if words_finished else min(int(row["done"] or 0), total)
        return {
            "id": int(row["id"]),
            "title": str(row["title"] or translate_for_user(user_id, "homework.default_title")),
            "status": str(row["status"]),
            "to": names.get(int(row["assigned_to_user_id"]), str(row["assigned_to_user_id"])),
            "mode": translate_for_user(user_id, f"training.mode.{row['training_mode']}"),
            "created_at": str(row["created_at"]),
            "finished_at": str(row["completed_at"] or row["updated_at"]),
            "set_id": int(row["homework_set_id"]) if row["homework_set_id"] is not None else None,
            "done": done,
            "total": total,
            "paper_done": int(row["paper_done"]),
            "paper_total": int(row["paper_total"]),
        }
    items = [serialize(row) for row in rows]
    return {
        "active": [item for item in items if item["status"] == "active"],
        "finished": [item for item in items if item["status"] != "active"],
    }


def cancel_assignment(user_id: int, assignment_id: int) -> dict[str, object]:
    """Cancel unfinished homework and close its running session so finishing it cannot complete it."""
    family_id = _family_id(user_id)
    with get_connection() as connection:
        row = connection.execute(
            "SELECT status FROM homework_assignments WHERE id = ? AND family_id = ?",
            (assignment_id, family_id),
        ).fetchone()
        if row is None:
            raise HomeworkSetError("assignment_not_found", 404)
        if row["status"] != "active":
            raise HomeworkSetError("assignment_not_active", 409)
        timestamp = utc_now()
        connection.execute(
            "UPDATE training_sessions SET status = ?, updated_at = ? WHERE family_homework_assignment_id = ? AND status = 'active'",
            (ASSIGNMENT_CANCELLED, timestamp, assignment_id),
        )
        connection.execute(
            "UPDATE homework_assignments SET status = ?, updated_at = ? WHERE id = ?",
            (ASSIGNMENT_CANCELLED, timestamp, assignment_id),
        )
    return {"id": assignment_id, "status": ASSIGNMENT_CANCELLED}
