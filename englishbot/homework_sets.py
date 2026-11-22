"""Homework sets: tutor homework collected from forwarded messages, drafted by AI, saved as items."""

import json
from datetime import datetime, timezone

from .ai_extraction import KIND_WORDS, SUPPORTED_KINDS, ExtractionResult
from .db import get_connection, utc_now
from .families import create_homework_assignment, get_user_family, list_family_members
from .i18n import translate_for_user
from .teacher_content import create_teacher_topic, create_teacher_topic_item
from .training import TRAINING_MODES


STATUS_COLLECTING = "collecting"
STATUS_PROCESSING = "processing"
STATUS_DRAFT = "draft"
STATUS_FAILED = "failed"
STATUS_SAVED = "saved"
STATUS_CANCELLED = "cancelled"
MAX_SOURCES = 30
MAX_TEXT_LENGTH = 200


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


def begin_processing(user_id: int, set_id: int, kind: str) -> list[dict[str, str]]:
    """Lock the set for extraction and return its sources."""
    if kind not in SUPPORTED_KINDS:
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
            "SELECT id, text FROM learning_items WHERE family_id = ? AND is_archived = 0 ORDER BY id",
            (family_id,),
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


def store_extraction(set_id: int, result: ExtractionResult) -> dict[str, int]:
    """Turn model output into an editable draft, marking words the family already has."""
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM homework_sets WHERE id = ?", (set_id,)).fetchone()
        family_id = int(row["family_id"])
        existing = _existing_words(connection, family_id)
        topics = _active_topics(connection, family_id)
        items = []
        for entry in result.items:
            items.append({
                "en": entry["en"],
                "ru": entry["ru"],
                "topic": _match_topic_title(entry["topic"], topics) if entry["topic"] else "",
                "existing_id": existing.get(entry["en"].lower()),
            })
        draft = {"model": result.model, "items": items}
        title = translate_for_user(
            int(row["created_by_user_id"]),
            "homework_import.default_title",
            date=datetime.now(timezone.utc).strftime("%d.%m.%Y"),
        )
        connection.execute(
            "UPDATE homework_sets SET status = ?, title = ?, draft_json = ?, updated_at = ? WHERE id = ?",
            (STATUS_DRAFT, title, json.dumps(draft, ensure_ascii=False), utc_now(), set_id),
        )
    known = sum(1 for item in items if item["existing_id"])
    return {"total": len(items), "new": len(items) - known, "existing": known}


def _display_name(member) -> str:
    for field in ("first_name", "username", "last_name"):
        if member[field]:
            return str(member[field])
    return str(member["telegram_user_id"])


def get_draft(user_id: int, set_id: int) -> dict[str, object]:
    family_id = _family_id(user_id)
    with get_connection() as connection:
        row = _get_set(connection, user_id, set_id)
        if row["status"] != STATUS_DRAFT:
            raise HomeworkSetError("draft_not_available", 409)
        draft = json.loads(row["draft_json"] or "{}")
        topics = _active_topics(connection, family_id)
    members = [
        {"id": int(member["telegram_user_id"]), "name": _display_name(member)}
        for member in list_family_members(family_id)
    ]
    members.sort(key=lambda member: member["id"] == user_id)
    return {
        "set": {"id": set_id, "title": str(row["title"] or ""), "kind": str(row["kind"] or KIND_WORDS)},
        "items": draft.get("items", []),
        "topics": topics,
        "members": members,
        "modes": [{"code": mode, "label": translate_for_user(user_id, f"training.mode.{mode}")} for mode in TRAINING_MODES],
    }


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


def save_draft(user_id: int, set_id: int, payload: dict[str, object]) -> dict[str, object]:
    """Create or reuse words, file them under topics, record set items, optionally assign homework."""
    family_id = _family_id(user_id)
    with get_connection() as connection:
        row = _get_set(connection, user_id, set_id)
        if row["status"] != STATUS_DRAFT:
            raise HomeworkSetError("draft_not_available", 409)
    title = _clean(payload.get("title")) or str(row["title"] or "")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise HomeworkSetError("invalid_request")
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

    topic_cache: dict[str, int] = {}
    word_ids: list[int] = []
    created = 0
    for entry in raw_items:
        if not isinstance(entry, dict) or not entry.get("include", True):
            continue
        english = _clean(entry.get("en"))
        if not english:
            continue
        russian = _clean(entry.get("ru"))
        topic_id = _resolve_topic_id(user_id, family_id, _clean(entry.get("topic")), topic_cache)
        with get_connection() as connection:
            word_id = _existing_words(connection, family_id).get(english.lower())
        if word_id is None:
            if topic_id is None:
                raise HomeworkSetError("topic_required")
            word_id = int(create_teacher_topic_item(user_id, family_id, topic_id, english)["learning_item_id"])
            created += 1
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
        elif topic_id is not None:
            with get_connection() as connection:
                _link_word_to_topic(connection, topic_id, word_id)
        if word_id not in word_ids:
            word_ids.append(word_id)

    with get_connection() as connection:
        connection.execute("DELETE FROM homework_set_items WHERE homework_set_id = ?", (set_id,))
        connection.executemany(
            "INSERT INTO homework_set_items (homework_set_id, item_kind, learning_item_id, item_order) VALUES (?, 'word', ?, ?)",
            [(set_id, word_id, order) for order, word_id in enumerate(word_ids)],
        )
        timestamp = utc_now()
        connection.execute(
            "UPDATE homework_sets SET status = ?, title = ?, saved_at = ?, updated_at = ? WHERE id = ?",
            (STATUS_SAVED, title, timestamp, timestamp, set_id),
        )

    assignment_id = None
    if assign_to is not None and word_ids:
        assignment_id = create_homework_assignment(
            family_id, user_id, assign_to, word_ids,
            title=title, training_mode=mode, homework_set_id=set_id,
        )
    return {
        "saved": True,
        "title": title,
        "word_count": len(word_ids),
        "created_words": created,
        "assignment_id": assignment_id,
        "assigned_to": assign_to if assignment_id else None,
    }
