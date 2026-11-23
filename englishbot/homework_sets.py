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
STATUS_ARCHIVED = "archived"
ASSIGNMENT_CANCELLED = "cancelled"
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
        "defaults": _assignment_defaults(user_id, family_id),
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
        word_id, is_new = _ensure_word(user_id, family_id, english, _clean(entry.get("ru")), _clean(entry.get("topic")), topic_cache)
        created += int(is_new)
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


def get_set(user_id: int, set_id: int) -> dict[str, object]:
    family_id = _family_id(user_id)
    with get_connection() as connection:
        row = _require_saved(connection, user_id, set_id)
        words = connection.execute(
            """
            SELECT learning_items.id, learning_items.text, learning_items.is_archived,
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
        "words": [
            {"id": int(word["id"]), "text": str(word["text"]), "ru": str(word["ru"] or ""), "archived": bool(word["is_archived"])}
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
    if not word_ids:
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
            "item_count": len(json.loads(row["draft_json"] or "{}").get("items", [])),
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
        present = connection.execute(
            "SELECT 1 FROM homework_set_items WHERE homework_set_id = ? AND learning_item_id = ?",
            (set_id, word_id),
        ).fetchone()
        if present is None:
            next_order = connection.execute(
                "SELECT COALESCE(MAX(item_order), -1) + 1 FROM homework_set_items WHERE homework_set_id = ?",
                (set_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO homework_set_items (homework_set_id, item_kind, learning_item_id, item_order) VALUES (?, 'word', ?, ?)",
                (set_id, word_id, int(next_order)),
            )
    return get_set(user_id, set_id)


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
                      AND is_completed = 1) AS done
            FROM homework_assignments
            WHERE family_id = ?
            ORDER BY homework_assignments.id DESC
            """,
            (family_id,),
        ).fetchall()
    def serialize(row) -> dict[str, object]:
        total = int(row["total"])
        done = total if row["status"] == "completed" else min(int(row["done"] or 0), total)
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
