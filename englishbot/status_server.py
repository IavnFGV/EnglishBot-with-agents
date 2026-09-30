import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

from .build_info import BuildInfo


STATUS_SERVER_HOST: Final[str] = "0.0.0.0"
STATUS_SERVER_PORT: Final[int] = 8080
logger = logging.getLogger(__name__)
MINI_APP_DIR = Path(__file__).parent / "mini_app_static"
_mini_app_bot = None


def set_mini_app_bot(bot) -> None:
    global _mini_app_bot
    _mini_app_bot = bot


def build_status_payload(build_info: BuildInfo) -> dict[str, str]:
    return {
        "service": "englishbot",
        "status": "ok",
        "version": build_info.version,
        "commit": build_info.git_commit,
        "build_time_utc": build_info.build_time_utc,
        "build_ref": build_info.build_ref,
        "env": build_info.env_name,
    }


def build_status_response(path: str, build_info: BuildInfo) -> tuple[int, bytes]:
    if path not in {"/", "/healthz", "/version"}:
        return 404, json.dumps({"error": "not_found"}).encode("utf-8")

    payload = build_status_payload(build_info)
    if path == "/version":
        payload.pop("status")

    return 200, json.dumps(payload, sort_keys=True).encode("utf-8")


def _build_http_response(status_code: int, body: bytes) -> bytes:
    reason = "OK" if status_code == 200 else "Not Found"
    headers = [
        f"HTTP/1.1 {status_code} {reason}",
        "Content-Type: application/json; charset=utf-8",
        f"Content-Length: {len(body)}",
        "Connection: close",
        "",
        "",
    ]
    return "\r\n".join(headers).encode("utf-8") + body


def _response(status: int, body: bytes, content_type: str = "application/json; charset=utf-8", cache: str = "no-store") -> bytes:
    reason = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed", 409: "Conflict", 413: "Payload Too Large", 500: "Internal Server Error", 503: "Service Unavailable"}.get(status, "Error")
    headers = [
        f"HTTP/1.1 {status} {reason}", f"Content-Type: {content_type}",
        f"Content-Length: {len(body)}", f"Cache-Control: {cache}",
        "X-Content-Type-Options: nosniff", "Connection: close", "", "",
    ]
    return "\r\n".join(headers).encode() + body


def _json_response(status: int, value: dict[str, object]) -> bytes:
    return _response(status, json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


async def _mini_app_response(method: str, path: str, headers: dict[str, str], reader: asyncio.StreamReader, bot) -> bytes:
    from .config import load_config, get_tts_base_url
    from .assets import resolve_runtime_asset_path
    from .mini_app import MiniAppError, apply_action, authorize_session, claim_completion_notification, interface_labels, safe_media_path, session_state, validate_init_data
    from .training import get_current_question, get_training_session
    from .tts import build_tts_client, get_or_create_learning_item_tts_variant, TTSClientError
    from .user_profiles import get_user_tts_voice_id
    from .i18n import translate_for_user

    if path in {"/mini-app", "/mini-app/"} and method == "GET":
        return _response(200, (MINI_APP_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
    if path in {"/mini-app/app.js", "/mini-app/style.css"} and method == "GET":
        name = path.rsplit("/", 1)[-1]
        content_type = "text/javascript; charset=utf-8" if name.endswith(".js") else "text/css; charset=utf-8"
        return _response(200, (MINI_APP_DIR / name).read_bytes(), content_type, "public, max-age=3600")
    parts = path.strip("/").split("/")
    if len(parts) < 4 or parts[:3] != ["mini-app", "api", "sessions"]:
        raise MiniAppError("session_not_found", 404)
    try:
        session_id = int(parts[3])
    except ValueError as exc:
        raise MiniAppError("session_not_found", 404) from exc
    user_id = validate_init_data(headers.get("x-telegram-init-data", ""), load_config())
    authorize_session(user_id, session_id)
    if len(parts) == 4 and method == "GET":
        state = session_state(user_id, session_id)
        state["labels"] = interface_labels(user_id)
        return _json_response(200, state)
    if len(parts) == 5 and parts[4] == "answer" and method == "POST":
        try:
            length = int(headers.get("content-length", "0"))
            if length < 1 or length > 4096:
                raise MiniAppError("invalid_answer")
            payload = json.loads(await asyncio.wait_for(reader.readexactly(length), timeout=5))
            if not isinstance(payload, dict):
                raise ValueError
            state = apply_action(user_id, session_id, str(payload.get("token", "")), str(payload.get("action", "")), payload.get("value"))
        except (ValueError, UnicodeDecodeError, asyncio.IncompleteReadError):
            raise MiniAppError("invalid_answer")
        if state["status"] == "completed" and claim_completion_notification(session_id):
            summary = state["summary"]
            session = get_training_session(session_id)
            assignment_id = session["family_homework_assignment_id"] if session else None
            if assignment_id is None:
                text = translate_for_user(user_id, "training.summary", feedback="", total_questions=summary["total"], correct_answers=summary["correct"])
            else:
                from .homework import get_assignment
                assignment = get_assignment(int(assignment_id))
                text = translate_for_user(user_id, "homework.summary", feedback="", assignment_title=str(assignment["title"] if assignment else ""), total_questions=summary["total"], correct_answers=summary["correct"])
            try:
                await bot.send_message(user_id, text)
            except Exception:
                logger.exception("Mini App completion notification failed for session %s", session_id)
        return _json_response(200, state)
    if len(parts) == 6 and parts[4] == "media" and parts[5].isdigit() and method == "GET":
        file_path, content_type = safe_media_path(user_id, session_id, int(parts[5]), "image")
        return _response(200, await asyncio.to_thread(file_path.read_bytes), content_type, "private, max-age=3600")
    if len(parts) == 5 and parts[4] == "tts" and method == "GET":
        if get_tts_base_url() is None:
            raise MiniAppError("tts_unavailable", 503)
        question = get_current_question(user_id)
        if question is None or int(question["session_id"]) != session_id:
            raise MiniAppError("session_not_found", 404)
        client = build_tts_client()
        try:
            variant = await asyncio.to_thread(get_or_create_learning_item_tts_variant, client=client, learning_item_id=int(question["learning_item_id"]), text=str(question["expected_answer"]), preferred_voice_id=get_user_tts_voice_id(user_id))
            file_path = resolve_runtime_asset_path(str(variant["local_path"])).resolve()
            file_path.relative_to(resolve_runtime_asset_path("assets").resolve())
            if not file_path.is_file() or file_path.suffix.lower() not in {".mp3", ".ogg", ".wav"}:
                raise ValueError
        except (TTSClientError, ValueError, KeyError, OSError):
            raise MiniAppError("tts_unavailable", 503)
        content_type = {".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".wav": "audio/wav"}[file_path.suffix.lower()]
        return _response(200, await asyncio.to_thread(file_path.read_bytes), content_type, "private, max-age=3600")
    raise MiniAppError("session_not_found", 404)


async def _handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    build_info: BuildInfo,
    bot=None,
) -> None:
    started = time.monotonic()
    try:
        request_head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError):
        writer.close()
        await writer.wait_closed()
        return

    request_line = request_head.splitlines()[0].decode("utf-8", errors="replace")
    parts = request_line.split(" ")
    method = parts[0] if parts else ""
    path = urlsplit(parts[1]).path if len(parts) >= 2 else "/"
    headers = {}
    for line in request_head.split(b"\r\n")[1:]:
        if b":" in line:
            key, value = line.split(b":", 1)
            headers[key.decode("ascii", "ignore").lower()] = value.strip().decode("utf-8", "replace")
    bot = bot or _mini_app_bot
    if path.startswith("/mini-app") and bot is not None:
        from .mini_app import MiniAppError
        try:
            response = await _mini_app_response(method, path, headers, reader, bot)
        except MiniAppError as exc:
            response = _json_response(exc.status, {"error": exc.code})
        except Exception:
            logger.exception("Mini App request failed")
            response = _json_response(500, {"error": "server_error"})
        elapsed_ms = (time.monotonic() - started) * 1000
        if elapsed_ms >= 500:
            logger.warning("Slow Mini App API request: method=%s duration_ms=%d", method, elapsed_ms)
    else:
        status_code, body = build_status_response(path, build_info)
        response = _build_http_response(status_code, body)
    writer.write(response)
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def start_status_server(build_info: BuildInfo, bot=None) -> asyncio.AbstractServer:
    return await asyncio.start_server(
        lambda reader, writer: _handle_connection(reader, writer, build_info, bot),
        STATUS_SERVER_HOST,
        STATUS_SERVER_PORT,
    )
