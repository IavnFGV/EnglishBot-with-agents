"""Word pictures with the family heroine, drawn by the optional artist container.

The bot and the artist share only a folder (ENGLISHBOT_HEROINE_DIR):
  jobs/<id>.json             written by the bot, removed by the artist when done
  results/<id>/result.json   written by the artist last, after card.png
  status.json                artist heartbeat: ready, busy, auth_required, limited
The bot re-encodes every result into its own storage before anyone sees it.
"""

import asyncio
import json
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from .assets import PRIMARY_IMAGE_ROLE, resolve_runtime_asset_path
from .config import get_heroine_dir, get_owner_telegram_user_id
from .db import get_connection, utc_now
from .families import get_user_family
from .mini_app import MiniAppError


logger = logging.getLogger(__name__)

STATUS_QUEUED = "queued"
STATUS_READY = "ready"
STATUS_FAILED = "failed"
STATUS_APPROVED = "approved"
STATUS_SKIPPED = "skipped"
OPEN_STATUSES = (STATUS_QUEUED, STATUS_READY, STATUS_FAILED)

CANDIDATE_DIR = Path("assets/images/heroine-candidates")
MAX_SCENE_LENGTH = 500
# A freshly created word gets time for a hand-picked picture before the artist is asked.
AUTO_REQUEST_DELAY = timedelta(minutes=10)
WORKER_STALE_AFTER = timedelta(minutes=10)
LOOP_INTERVAL_SECONDS = 60
AUTH_NOTIFIED_SETTING = "heroine_auth_notified"


def _error(code: str, status: int = 400) -> MiniAppError:
    return MiniAppError(code, status)


def _root() -> Path:
    root = get_heroine_dir()
    if root is None:
        raise _error("heroine_unavailable", 503)
    return root


def _family_id(user_id: int) -> int:
    family = get_user_family(user_id)
    if family is None:
        raise _error("access_denied", 403)
    return int(family["id"])


def _clean_scene(value: object) -> str | None:
    text = " ".join(str(value or "").split())
    if len(text) > MAX_SCENE_LENGTH:
        raise _error("text_too_long")
    return text or None


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial")
    partial.write_bytes(content)
    os.replace(partial, path)


def _translation(connection, item_id: int) -> str:
    rows = connection.execute(
        "SELECT language_code, translation_text FROM learning_item_translations WHERE learning_item_id = ?",
        (item_id,),
    ).fetchall()
    by_code = {str(row["language_code"]): str(row["translation_text"]) for row in rows}
    return by_code.get("ru") or next(iter(by_code.values()), "")


def _enqueue(connection, root: Path, family_id: int, item_id: int, word: str,
             scene_request: str | None, requested_by: int | None) -> int:
    timestamp = utc_now()
    cursor = connection.execute(
        """
        INSERT INTO heroine_pictures
            (family_id, learning_item_id, status, scene_request, requested_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (family_id, item_id, STATUS_QUEUED, scene_request, requested_by, timestamp, timestamp),
    )
    picture_id = int(cursor.lastrowid)
    job = {"id": picture_id, "word": word, "translation": _translation(connection, item_id), "scene": scene_request}
    _atomic_write(root / "jobs" / f"{picture_id}.json", json.dumps(job, ensure_ascii=False).encode())
    return picture_id


def _close(connection, root: Path | None, row, status: str) -> None:
    """Finish an open picture: drop its job, its candidate file, and mark the row."""
    if root is not None:
        (root / "jobs" / f"{int(row['id'])}.json").unlink(missing_ok=True)
    if row["local_path"]:
        resolve_runtime_asset_path(str(row["local_path"])).unlink(missing_ok=True)
    connection.execute(
        "UPDATE heroine_pictures SET status = ?, local_path = NULL, updated_at = ? WHERE id = ?",
        (status, utc_now(), int(row["id"])),
    )


def request_picture(user_id: int, word_id: int, scene: object = None) -> dict[str, object]:
    """Ask the artist for a new picture of a word; any open picture of that word is skipped."""
    family_id = _family_id(user_id)
    root = _root()
    scene_request = _clean_scene(scene)
    with get_connection() as connection:
        word = connection.execute(
            "SELECT id, text FROM learning_items WHERE id = ? AND family_id = ? AND is_archived = 0",
            (word_id, family_id),
        ).fetchone()
        if word is None:
            raise _error("word_not_found", 404)
        for row in connection.execute(
            f"SELECT id, local_path FROM heroine_pictures WHERE learning_item_id = ? AND status IN ({','.join('?' * len(OPEN_STATUSES))})",
            (word_id, *OPEN_STATUSES),
        ).fetchall():
            _close(connection, root, row, STATUS_SKIPPED)
        picture_id = _enqueue(connection, root, family_id, word_id, str(word["text"]), scene_request, user_id)
        return _serialize(connection, picture_id)


def enqueue_missing_pictures(now: datetime | None = None) -> int:
    """Request pictures for active words that have none and were never drawn before."""
    root = get_heroine_dir()
    if root is None:
        return 0
    cutoff = ((now or datetime.now(timezone.utc)) - AUTO_REQUEST_DELAY).isoformat(timespec="seconds")
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT learning_items.id, learning_items.family_id, learning_items.text
            FROM learning_items
            WHERE learning_items.is_archived = 0
              AND learning_items.family_id IS NOT NULL
              AND learning_items.created_at <= ?
              AND NOT EXISTS (
                SELECT 1 FROM learning_item_assets
                WHERE learning_item_assets.learning_item_id = learning_items.id AND role = ?
              )
              AND NOT EXISTS (
                SELECT 1 FROM heroine_pictures WHERE heroine_pictures.learning_item_id = learning_items.id
              )
            ORDER BY learning_items.id
            """,
            (cutoff, PRIMARY_IMAGE_ROLE),
        ).fetchall()
        for row in rows:
            _enqueue(connection, root, int(row["family_id"]), int(row["id"]), str(row["text"]), None, None)
    return len(rows)


def collect_results() -> int:
    """Move finished artist results into bot storage; returns how many rows changed."""
    root = get_heroine_dir()
    results_dir = root / "results" if root is not None else None
    if results_dir is None or not results_dir.is_dir():
        return 0
    changed = 0
    for folder in sorted(results_dir.iterdir()):
        result_file = folder / "result.json"
        if not folder.name.isdigit() or folder.is_symlink() or not folder.is_dir() or not result_file.is_file():
            continue
        # The artist container is not trusted with the bot's files: never follow its links.
        if result_file.is_symlink() or (folder / "card.png").is_symlink():
            result = {"status": "failed", "error": "the artist returned a link instead of a file"}
        else:
            try:
                result = json.loads(result_file.read_text(encoding="utf-8"))
                if not isinstance(result, dict):
                    raise ValueError("result is not an object")
            except (OSError, ValueError) as exc:
                result = {"status": "failed", "error": f"unreadable result: {exc}"}
        changed += _store_result(int(folder.name), folder, result)
    return changed


def _store_result(picture_id: int, folder: Path, result: dict) -> int:
    from .dictionary_editor import normalize_image

    changed = 0
    with get_connection() as connection:
        row = connection.execute(
            "SELECT id FROM heroine_pictures WHERE id = ? AND status = ?", (picture_id, STATUS_QUEUED)
        ).fetchone()
        if row is not None:
            status, local_path, error = STATUS_FAILED, None, str(result.get("error") or "no picture")[:300]
            card = folder / "card.png"
            if result.get("status") == "ok" and card.is_file() and not card.is_symlink():
                try:
                    content = normalize_image(card.read_bytes())
                except (MiniAppError, OSError):
                    error = "the artist returned an invalid image"
                else:
                    relative = CANDIDATE_DIR / f"heroine-{picture_id}-{uuid4().hex}.jpg"
                    _atomic_write(resolve_runtime_asset_path(relative), content)
                    status, local_path, error = STATUS_READY, relative.as_posix(), None
            scene = " ".join(str(result.get("scene") or "").split())[:MAX_SCENE_LENGTH] or None
            connection.execute(
                "UPDATE heroine_pictures SET status = ?, local_path = ?, scene = ?, error = ?, updated_at = ? WHERE id = ?",
                (status, local_path, scene, error, utc_now(), picture_id),
            )
            changed = 1
    # A result for a skipped or replaced picture is simply dropped.
    shutil.rmtree(folder, ignore_errors=True)
    return changed


def worker_state(now: datetime | None = None) -> str:
    """Artist state from its heartbeat; offline when missing or stale."""
    root = get_heroine_dir()
    if root is None:
        return "disabled"
    try:
        status = json.loads((root / "status.json").read_text(encoding="utf-8"))
        updated = datetime.fromisoformat(str(status["updated_at"]))
        state = str(status["state"])
    except (OSError, ValueError, KeyError, TypeError):
        return "offline"
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    if (now or datetime.now(timezone.utc)) - updated > WORKER_STALE_AFTER:
        return "offline"
    return state if state in {"ready", "busy", "auth_required", "limited"} else "offline"


def _serialize(connection, picture_id: int) -> dict[str, object]:
    row = connection.execute(
        """
        SELECT heroine_pictures.*, learning_items.text AS word
        FROM heroine_pictures JOIN learning_items ON learning_items.id = heroine_pictures.learning_item_id
        WHERE heroine_pictures.id = ?
        """,
        (picture_id,),
    ).fetchone()
    return {
        "id": int(row["id"]),
        "word_id": int(row["learning_item_id"]),
        "word": str(row["word"]),
        "status": str(row["status"]),
        "scene_request": row["scene_request"],
        "scene": row["scene"],
        "error": row["error"],
    }


def list_pictures(user_id: int) -> dict[str, object]:
    family_id = _family_id(user_id)
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT heroine_pictures.id FROM heroine_pictures
            JOIN learning_items ON learning_items.id = heroine_pictures.learning_item_id
            WHERE heroine_pictures.family_id = ? AND learning_items.is_archived = 0
              AND heroine_pictures.status IN ({','.join('?' * len(OPEN_STATUSES))})
            ORDER BY heroine_pictures.status = 'queued', heroine_pictures.id
            """,
            (family_id, *OPEN_STATUSES),
        ).fetchall()
        pictures = [_serialize(connection, int(row["id"])) for row in rows]
    return {"pictures": pictures, "worker": worker_state()}


def count_open_pictures(user_id: int) -> int:
    family = get_user_family(user_id)
    if family is None or get_heroine_dir() is None:
        return 0
    with get_connection() as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM heroine_pictures WHERE family_id = ? AND status IN (?, ?)",
            (int(family["id"]), STATUS_READY, STATUS_FAILED),
        ).fetchone()
    return int(row[0])


def _require_open(connection, family_id: int, picture_id: int):
    row = connection.execute(
        f"SELECT * FROM heroine_pictures WHERE id = ? AND family_id = ? AND status IN ({','.join('?' * len(OPEN_STATUSES))})",
        (picture_id, family_id, *OPEN_STATUSES),
    ).fetchone()
    if row is None:
        raise _error("picture_not_found", 404)
    return row


def approve_picture(user_id: int, picture_id: int) -> dict[str, object]:
    """Make a ready candidate the word's picture."""
    from .dictionary_editor import store_word_image

    family_id = _family_id(user_id)
    with get_connection() as connection:
        row = _require_open(connection, family_id, picture_id)
        if row["status"] != STATUS_READY or not row["local_path"]:
            raise _error("picture_not_ready", 409)
        content = resolve_runtime_asset_path(str(row["local_path"])).read_bytes()
    store_word_image(int(row["learning_item_id"]), content)
    with get_connection() as connection:
        _close(connection, get_heroine_dir(), row, STATUS_APPROVED)
        return _serialize(connection, picture_id)


def skip_picture(user_id: int, picture_id: int) -> dict[str, object]:
    family_id = _family_id(user_id)
    with get_connection() as connection:
        row = _require_open(connection, family_id, picture_id)
        _close(connection, get_heroine_dir(), row, STATUS_SKIPPED)
        return _serialize(connection, picture_id)


def redraw_picture(user_id: int, picture_id: int, scene: object = None) -> dict[str, object]:
    family_id = _family_id(user_id)
    with get_connection() as connection:
        row = _require_open(connection, family_id, picture_id)
    return request_picture(user_id, int(row["learning_item_id"]), scene)


def candidate_path(user_id: int, picture_id: int) -> Path:
    family_id = _family_id(user_id)
    with get_connection() as connection:
        row = _require_open(connection, family_id, picture_id)
    path = resolve_runtime_asset_path(str(row["local_path"] or ""))
    if not row["local_path"] or not path.is_file():
        raise _error("image_not_found", 404)
    return path


def claim_notifications() -> dict[int, dict[str, list[str]]]:
    """Finished pictures nobody was told about yet, grouped by recipient."""
    owner = get_owner_telegram_user_id()
    grouped: dict[int, dict[str, list[str]]] = {}
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT heroine_pictures.id, heroine_pictures.status, heroine_pictures.requested_by, learning_items.text
            FROM heroine_pictures JOIN learning_items ON learning_items.id = heroine_pictures.learning_item_id
            WHERE heroine_pictures.notified = 0 AND heroine_pictures.status IN (?, ?)
            ORDER BY heroine_pictures.id
            """,
            (STATUS_READY, STATUS_FAILED),
        ).fetchall()
        for row in rows:
            connection.execute("UPDATE heroine_pictures SET notified = 1 WHERE id = ?", (int(row["id"]),))
            chat_id = row["requested_by"] if row["requested_by"] is not None else owner
            if chat_id is None:
                continue
            bucket = grouped.setdefault(int(chat_id), {STATUS_READY: [], STATUS_FAILED: []})
            bucket[str(row["status"])].append(str(row["text"]))
    return grouped


def claim_auth_alert(state: str) -> bool:
    """True once per period in which the artist needs a new login."""
    with get_connection() as connection:
        row = connection.execute("SELECT value FROM app_settings WHERE key = ?", (AUTH_NOTIFIED_SETTING,)).fetchone()
        notified = row is not None and row["value"] == "1"
        wanted = state == "auth_required"
        if notified != wanted and state != "offline":
            connection.execute(
                """
                INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (AUTH_NOTIFIED_SETTING, "1" if wanted else "0", utc_now()),
            )
        return wanted and not notified


async def notify(bot) -> None:
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

    from .config import get_mini_app_url
    from .i18n import translate_for_user

    base_url = get_mini_app_url()
    for chat_id, words in (await asyncio.to_thread(claim_notifications)).items():
        lines = []
        if words[STATUS_READY]:
            lines.append(translate_for_user(chat_id, "heroine.notify.ready", words=", ".join(words[STATUS_READY])))
        if words[STATUS_FAILED]:
            lines.append(translate_for_user(chat_id, "heroine.notify.failed", words=", ".join(words[STATUS_FAILED])))
        markup = None
        if base_url:
            markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                text=translate_for_user(chat_id, "heroine.notify.open"),
                web_app=WebAppInfo(url=f"{base_url}/editor?pictures=1"),
            )]])
        try:
            await bot.send_message(chat_id=chat_id, text="\n".join(lines), reply_markup=markup)
        except Exception:
            logger.exception("Could not send heroine picture notification: chat_id=%s", chat_id)
    owner = get_owner_telegram_user_id()
    if owner is not None and await asyncio.to_thread(claim_auth_alert, worker_state()):
        try:
            await bot.send_message(chat_id=owner, text=translate_for_user(owner, "heroine.notify.login"))
        except Exception:
            logger.exception("Could not send the heroine artist login alert")


async def run_heroine_loop(bot, *, interval_seconds: int = LOOP_INTERVAL_SECONDS) -> None:
    if get_heroine_dir() is None:
        return
    while True:
        try:
            queued = await asyncio.to_thread(enqueue_missing_pictures)
            if queued:
                logger.info("Requested %d heroine pictures for words without a picture", queued)
            collected = await asyncio.to_thread(collect_results)
            if collected:
                logger.info("Collected %d heroine artist results", collected)
            await notify(bot)
        except Exception:
            logger.exception("Heroine picture loop failed")
        await asyncio.sleep(interval_seconds)
