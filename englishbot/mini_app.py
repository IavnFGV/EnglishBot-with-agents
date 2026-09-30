"""Authenticated HTTP transport for the existing learner training engine."""

from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import time
from pathlib import Path
from urllib.parse import parse_qsl

from .assets import get_learning_item_asset, resolve_runtime_asset_path, PRIMARY_IMAGE_ROLE
from .config import get_tts_base_url
from .db import get_connection, get_user, utc_now
from .families import get_user_family
from .homework import get_assignment, get_assignment_progress_snapshot
from .i18n import translate_for_user
from .training import (
    append_medium_answer_letter,
    get_current_question,
    get_training_session,
    get_homework_item_progress_value,
    pop_medium_answer_letter,
    set_medium_answer_letters,
    skip_optional_hard,
    submit_medium_answer,
    submit_training_answer,
)


MAX_INIT_DATA_AGE_SECONDS = 3600


class MiniAppError(Exception):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def sign_test_init_data(user_id: int, bot_token: str, auth_date: int | None = None) -> str:
    """Build signed initData for local automated tests with a test bot token."""
    from urllib.parse import urlencode

    values = {"auth_date": str(auth_date or int(time.time())), "user": json.dumps({"id": user_id}, separators=(",", ":"))}
    check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def validate_init_data(raw: str, bot_token: str, *, now: int | None = None) -> int:
    if not raw or len(raw) > 8192:
        raise MiniAppError("unauthorized", 401)
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise MiniAppError("unauthorized", 401) from exc
    values = dict(pairs)
    if len(values) != len(pairs) or not values.get("hash"):
        raise MiniAppError("unauthorized", 401)
    received_hash = values.pop("hash")
    check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise MiniAppError("unauthorized", 401)
    try:
        auth_date = int(values["auth_date"])
        user_id = int(json.loads(values["user"])["id"])
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise MiniAppError("unauthorized", 401) from exc
    current = int(time.time()) if now is None else now
    if auth_date > current + 60 or current - auth_date > MAX_INIT_DATA_AGE_SECONDS:
        raise MiniAppError("expired_init_data", 401)
    if user_id <= 0 or get_user(user_id) is None:
        raise MiniAppError("unauthorized", 401)
    return user_id


def authorize_session(user_id: int, session_id: int):
    session = get_training_session(session_id)
    if session is None:
        raise MiniAppError("session_not_found", 404)
    if int(session["telegram_user_id"]) != user_id:
        raise MiniAppError("access_denied", 403)
    family = get_user_family(user_id)
    if family is None:
        raise MiniAppError("access_denied", 403)
    with get_connection() as connection:
        foreign_item = connection.execute(
            """SELECT 1 FROM training_session_items
               JOIN learning_items ON learning_items.id = training_session_items.learning_item_id
               WHERE training_session_items.session_id = ? AND (learning_items.family_id IS NULL OR learning_items.family_id != ?) LIMIT 1""",
            (session_id, int(family["id"])),
        ).fetchone()
    if foreign_item is not None:
        raise MiniAppError("access_denied", 403)
    assignment_id = session["family_homework_assignment_id"]
    if assignment_id is not None:
        assignment = get_assignment(int(assignment_id))
        if assignment is None or int(assignment["student_user_id"]) != user_id or int(assignment["family_id"]) != int(family["id"]):
            raise MiniAppError("access_denied", 403)
    return session


def question_token(question: dict[str, object]) -> str:
    fields = (
        "session_id", "session_item_id", "current_index", "current_stage", "question_version",
        "easy_correct_count", "medium_correct_count", "correct_streak",
        "hard_unlocked", "hard_completed", "selected_letter_indexes",
    )
    data = json.dumps([question.get(field) for field in fields], separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()[:24]


def public_question(question: dict[str, object]) -> dict[str, object]:
    image_asset_id = question.get("image_asset_id")
    return {
        "token": question_token(question),
        "type": question["exercise_type"],
        "prompt": question["prompt"],
        "hint": question["hint_text"],
        "first_letter": question["first_letter"],
        "options": question["options"] if question["exercise_type"] == "multiple_choice" else None,
        "letters": question["jumbled_letters"] if question["exercise_type"] == "jumbled_letters" else None,
        "selected": question["selected_letter_indexes"],
        "answer_mask": question["medium_answer_mask"],
        "number": question["question_number"],
        "total": question["total_questions"],
        "completed": question["completed_items"],
        "can_skip_hard": question["can_skip_hard"],
        "image_asset_id": image_asset_id,
        "tts_available": get_tts_base_url() is not None,
    }


def interface_labels(user_id: int) -> dict[str, str]:
    keys = (
        "loading", "word", "done", "great", "correct_answers", "back",
        "check", "skip", "listen", "type", "connection", "retry",
        "audio_unavailable", "expired", "starts", "feedback_correct",
        "feedback_incorrect", "feedback_skipped", "homework_progress", "combo", "boost_active",
    )
    return {
        key: translate_for_user(
            user_id,
            f"mini_app.ui.{key}",
            count="{count}",
            letter="{letter}",
            completed="{completed}",
            total="{total}",
        )
        for key in keys
    }


def session_state(user_id: int, session_id: int) -> dict[str, object]:
    session = authorize_session(user_id, session_id)
    if session["status"] == "completed":
        state = {"status": "completed", "summary": {"total": int(session["total_questions"]), "correct": int(session["correct_answers"])}}
    else:
        question = get_current_question(user_id)
        if question is None or int(question["session_id"]) != session_id:
            raise MiniAppError("session_not_found", 404)
        state = {"status": "active", "question": public_question(question)}
    assignment_id = session["family_homework_assignment_id"]
    if assignment_id is not None:
        snapshot = get_assignment_progress_snapshot(int(assignment_id), session_id)
        state["homework_progress"] = {
            "completed": int(snapshot["completed_items"]),
            "total": int(snapshot["total_items"]),
            "streak": int(snapshot["homework_correct_streak"]),
            "boost_active": bool(snapshot["homework_hard_mode"]),
            "segments": [
                {"value": get_homework_item_progress_value(item), "hard_clear": bool(item["hard_completed"])}
                for item in snapshot["items"]
            ],
        }
    return state


def apply_action(user_id: int, session_id: int, token: str, action: str, value: object = None) -> dict[str, object]:
    session = authorize_session(user_id, session_id)
    if session["status"] == "completed":
        raise MiniAppError("session_completed", 409)
    question = get_current_question(user_id)
    if question is None or int(question["session_id"]) != session_id:
        raise MiniAppError("session_not_found", 404)
    if token != question_token(question):
        raise MiniAppError("stale_question", 409)
    exercise_type = question["exercise_type"]
    if action == "easy" and exercise_type == "multiple_choice":
        if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value >= len(question["options"]):
            raise MiniAppError("invalid_answer")
        result = submit_training_answer(user_id, str(question["options"][value]))
    elif action == "add" and exercise_type == "jumbled_letters":
        if not isinstance(value, int) or isinstance(value, bool):
            raise MiniAppError("invalid_answer")
        if value < 0 or value >= len(str(question["jumbled_letters"])) or value in question["selected_letter_indexes"]:
            raise MiniAppError("invalid_answer")
        append_medium_answer_letter(user_id, value)
        result = None
    elif action == "backspace" and exercise_type == "jumbled_letters":
        pop_medium_answer_letter(user_id)
        result = None
    elif action == "set_medium" and exercise_type == "jumbled_letters":
        if not isinstance(value, list) or any(not isinstance(index, int) or isinstance(index, bool) for index in value):
            raise MiniAppError("invalid_answer")
        try:
            set_medium_answer_letters(user_id, value)
        except ValueError as exc:
            raise MiniAppError("invalid_answer") from exc
        result = None
    elif action == "check" and exercise_type == "jumbled_letters":
        result = submit_medium_answer(user_id)
    elif action == "hard" and exercise_type == "typed_answer":
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise MiniAppError("invalid_answer")
        result = submit_training_answer(user_id, value)
    elif action == "skip" and question["can_skip_hard"]:
        result = skip_optional_hard(user_id)
    else:
        raise MiniAppError("invalid_answer")
    state = session_state(user_id, session_id)
    if result is not None:
        state["feedback"] = "correct" if result["is_correct"] else "incorrect"
        if result.get("skipped_hard"):
            state["feedback"] = "skipped"
    return state


def claim_completion_notification(session_id: int) -> bool:
    with get_connection() as connection:
        cursor = connection.execute(
            "INSERT OR IGNORE INTO mini_app_completion_notifications (session_id, created_at) VALUES (?, ?)",
            (session_id, utc_now()),
        )
        return cursor.rowcount == 1


def safe_media_path(user_id: int, session_id: int, asset_id: int, kind: str) -> tuple[Path, str]:
    authorize_session(user_id, session_id)
    question = get_current_question(user_id)
    if question is None or int(question["session_id"]) != session_id:
        raise MiniAppError("media_not_found", 404)
    if kind != "image" or int(question.get("image_asset_id") or 0) != asset_id:
        raise MiniAppError("media_not_found", 404)
    asset = get_learning_item_asset(int(question["learning_item_id"]), role=PRIMARY_IMAGE_ROLE, asset_type="image")
    if asset is None or int(asset["asset_id"]) != asset_id:
        raise MiniAppError("media_not_found", 404)
    raw_path = str(asset["local_path"] or "")
    if not raw_path:
        raise MiniAppError("media_not_found", 404)
    path = resolve_runtime_asset_path(raw_path).resolve()
    try:
        path.relative_to(resolve_runtime_asset_path("assets").resolve())
    except ValueError as exc:
        raise MiniAppError("media_not_found", 404) from exc
    content_type = mimetypes.guess_type(path.name)[0]
    if content_type not in {"image/png", "image/jpeg", "image/webp", "image/gif"} or not path.is_file():
        raise MiniAppError("media_not_found", 404)
    return path, content_type
