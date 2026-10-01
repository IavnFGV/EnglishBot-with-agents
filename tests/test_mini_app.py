import asyncio
import time
from pathlib import Path

import pytest
from aiogram.types import User

from englishbot import db
from englishbot.assets import PRIMARY_IMAGE_ROLE, create_asset, link_asset_to_learning_item
from englishbot.families import create_family, create_family_learning_item, add_family_member, create_homework_assignment
from englishbot.mini_app import (
    MiniAppError, apply_action, authorize_session, claim_completion_notification,
    public_question, question_token, safe_media_path, session_state,
    sign_test_init_data, validate_init_data,
)
from englishbot.mini_app_handlers import build_mini_app_url, offer_training_interfaces
from englishbot.config import get_mini_app_url
from englishbot.training import create_training_session, get_current_question, submit_training_answer
from englishbot.homework import start_assignment_training_session
from englishbot.status_server import _mini_app_response
from englishbot.status_server import _handle_connection
from englishbot.build_info import BuildInfo
from englishbot.vocabulary import create_learning_item_translation, create_lexeme


TOKEN = "123456:test-token"


def seed(tmp_path: Path, mode: str = "easy") -> tuple[int, int]:
    db.DB_PATH = tmp_path / "mini.sqlite3"
    db.init_db()
    user = User(id=711, is_bot=False, first_name="Learner")
    db.save_user(user)
    family = create_family("Home", user.id)
    for index in range(3):
        lexeme_id = create_lexeme(f"mini-{index}")
        item_id = create_family_learning_item(int(family["id"]), lexeme_id, f"mini-{index}")
        create_learning_item_translation(item_id, "ru", f"слово-{index}")
    session_id = int(create_training_session(user.id, training_mode=mode)["session_id"])
    return user.id, session_id


def error_code(call) -> str:
    with pytest.raises(MiniAppError) as caught:
        call()
    return caught.value.code


def test_signed_init_data_and_session_access(tmp_path: Path) -> None:
    user_id, session_id = seed(tmp_path)
    signed = sign_test_init_data(user_id, TOKEN)
    assert validate_init_data(signed, TOKEN) == user_id
    assert authorize_session(user_id, session_id)["id"] == session_id
    assert error_code(lambda: validate_init_data(signed + "x", TOKEN)) == "unauthorized"
    assert error_code(lambda: validate_init_data(signed.replace("hash=", "missing="), TOKEN)) == "unauthorized"
    old = sign_test_init_data(user_id, TOKEN, int(time.time()) - 7200)
    assert error_code(lambda: validate_init_data(old, TOKEN)) == "expired_init_data"
    unknown = sign_test_init_data(999999, TOKEN)
    assert error_code(lambda: validate_init_data(unknown, TOKEN)) == "unauthorized"
    assert error_code(lambda: authorize_session(999999, session_id)) == "access_denied"


def test_current_question_and_double_answer_are_sqlite_backed(tmp_path: Path) -> None:
    user_id, session_id = seed(tmp_path)
    state = session_state(user_id, session_id)
    question = state["question"]
    assert "homework_progress" not in state
    assert "expected_answer" not in question
    assert session_state(user_id, session_id)["question"]["token"] == question["token"]
    wrong = apply_action(user_id, session_id, question["token"], "easy", 0 if get_current_question(user_id)["options"][0] != get_current_question(user_id)["expected_answer"] else 1)
    assert wrong["status"] == "active"
    assert wrong["question"]["token"] != question["token"]
    assert error_code(lambda: apply_action(user_id, session_id, question["token"], "easy", 0)) == "stale_question"
    assert session_state(user_id, session_id)["question"]["token"] == wrong["question"]["token"]
    answer = str(get_current_question(user_id)["expected_answer"])
    submit_training_answer(user_id, answer)
    assert error_code(lambda: apply_action(user_id, session_id, wrong["question"]["token"], "easy", 0)) == "stale_question"


def test_medium_edits_change_question_version(tmp_path: Path) -> None:
    user_id, session_id = seed(tmp_path, "medium")
    first = session_state(user_id, session_id)["question"]
    added = apply_action(user_id, session_id, first["token"], "add", 0)["question"]
    assert added["token"] != first["token"]
    assert added["selected"] == [0]
    popped = apply_action(user_id, session_id, added["token"], "backspace")["question"]
    assert popped["selected"] == []
    assert popped["token"] != added["token"]


def test_medium_phrase_preserves_word_boundary_in_answer_mask(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "medium-phrase.sqlite3"
    db.init_db()
    user = User(id=712, is_bot=False, first_name="Learner")
    db.save_user(user)
    family = create_family("Home", user.id)
    lexeme_id = create_lexeme("action figure")
    item_id = create_family_learning_item(int(family["id"]), lexeme_id, "action figure")
    create_learning_item_translation(item_id, "ru", "фигурка")
    session_id = int(create_training_session(user.id, training_mode="medium")["session_id"])

    question = session_state(user.id, session_id)["question"]

    assert "  " in question["answer_mask"]
    assert " " not in question["letters"]


def test_medium_selection_can_be_saved_in_one_request(tmp_path: Path) -> None:
    user_id, session_id = seed(tmp_path, "medium")
    first = session_state(user_id, session_id)["question"]
    selected = [0, 1]
    saved = apply_action(user_id, session_id, first["token"], "set_medium", selected)["question"]
    assert saved["selected"] == selected
    assert saved["token"] != first["token"]
    assert error_code(lambda: apply_action(user_id, session_id, first["token"], "set_medium", [0])) == "stale_question"
    assert error_code(lambda: apply_action(user_id, session_id, saved["token"], "set_medium", [0, 0])) == "invalid_answer"
    assert error_code(lambda: apply_action(user_id, session_id, saved["token"], "set_medium", [999])) == "invalid_answer"
    cleared = apply_action(user_id, session_id, saved["token"], "set_medium", [])["question"]
    assert cleared["selected"] == []


def test_medium_check_and_hard_skip_use_shared_training_rules(tmp_path: Path) -> None:
    user_id, session_id = seed(tmp_path)
    with db.get_connection() as connection:
        connection.execute(
            "UPDATE training_session_items SET current_stage = 'medium', easy_correct_count = 2 WHERE session_id = ? AND item_order = 0",
            (session_id,),
        )
    question = get_current_question(user_id)
    assert question["exercise_type"] == "jumbled_letters"
    remaining = list(enumerate(str(question["jumbled_letters"])))
    for character in str(question["expected_answer"]).replace(" ", ""):
        index, _ = next(pair for pair in remaining if pair[1] == character)
        remaining = [pair for pair in remaining if pair[0] != index]
        token = session_state(user_id, session_id)["question"]["token"]
        apply_action(user_id, session_id, token, "add", index)
    token = session_state(user_id, session_id)["question"]["token"]
    checked = apply_action(user_id, session_id, token, "check")
    assert checked["feedback"] == "correct"
    with db.get_connection() as connection:
        connection.execute(
            "UPDATE training_session_items SET current_stage = 'hard', hard_unlocked = 1 WHERE session_id = ? AND item_order = ?",
            (session_id, checked["question"]["number"] - 1),
        )
    hard = get_current_question(user_id)
    assert hard["can_skip_hard"]
    skipped = apply_action(user_id, session_id, question_token(hard), "skip")
    assert skipped["feedback"] == "skipped"


def test_media_cannot_read_unlinked_or_outside_asset(tmp_path: Path) -> None:
    user_id, session_id = seed(tmp_path)
    assert error_code(lambda: safe_media_path(user_id, session_id, 1, "image")) == "media_not_found"
    assert error_code(lambda: safe_media_path(user_id, session_id, 1, "../image")) == "media_not_found"


def test_media_allows_only_current_item_image_inside_assets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    user_id, session_id = seed(tmp_path)
    current = get_current_question(user_id)
    image = tmp_path / "assets" / "images" / "test.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    asset_id = create_asset("image", local_path="assets/images/test.png")
    link_asset_to_learning_item(int(current["learning_item_id"]), asset_id, PRIMARY_IMAGE_ROLE)
    assert safe_media_path(user_id, session_id, asset_id, "image")[0] == image
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"\x89PNG\r\n\x1a\n")
    other_id = create_asset("image", local_path="outside.png")
    link_asset_to_learning_item(int(current["learning_item_id"]), other_id, "image_preview")
    assert error_code(lambda: safe_media_path(user_id, session_id, other_id, "image")) == "media_not_found"


def test_media_rejects_linked_path_outside_assets(tmp_path: Path) -> None:
    user_id, session_id = seed(tmp_path)
    current = get_current_question(user_id)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"\x89PNG\r\n\x1a\n")
    asset_id = create_asset("image", local_path="outside.png")
    link_asset_to_learning_item(int(current["learning_item_id"]), asset_id, PRIMARY_IMAGE_ROLE)
    assert error_code(lambda: safe_media_path(user_id, session_id, asset_id, "image")) == "media_not_found"


def test_no_image_placeholder_uses_existing_runtime_asset(tmp_path: Path, monkeypatch) -> None:
    runtime_image = tmp_path / "assets" / "images" / "no-image.png"
    runtime_image.parent.mkdir(parents=True)
    runtime_image.write_bytes((Path(__file__).resolve().parents[1] / "assets/images/no-image.png").read_bytes())
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "data" / "englishbot.sqlite3")

    async def request():
        reader = asyncio.StreamReader()
        reader.feed_eof()
        return await _mini_app_response("GET", "/mini-app/no-image.png", {}, reader, None)

    response = asyncio.run(request())
    assert b"Content-Type: image/png" in response
    assert response.endswith(runtime_image.read_bytes())


def test_mini_app_script_refreshes_after_deploy() -> None:
    async def request():
        reader = asyncio.StreamReader()
        reader.feed_eof()
        return await _mini_app_response("GET", "/mini-app/app.js", {}, reader, None)

    response = asyncio.run(request())
    assert b"Cache-Control: no-store" in response


def test_mini_app_page_versions_static_assets() -> None:
    async def request():
        reader = asyncio.StreamReader()
        reader.feed_eof()
        return await _mini_app_response("GET", "/mini-app", {}, reader, None)

    response = asyncio.run(request())
    assert b"/mini-app/app.js?v=" in response
    assert b"/mini-app/style.css?v=" in response


def test_mini_app_style_preserves_medium_phrase_spacing() -> None:
    async def request():
        reader = asyncio.StreamReader()
        reader.feed_eof()
        return await _mini_app_response("GET", "/mini-app/style.css", {}, reader, None)

    response = asyncio.run(request())
    assert b"white-space: pre-wrap" in response


def test_mini_app_launch_url_changes_with_deployed_commit(monkeypatch) -> None:
    monkeypatch.setenv("ENGLISHBOT_GIT_COMMIT", "abcdef1234567890")
    assert build_mini_app_url("https://example.test/mini-app?session=1&v=old", 42) == (
        "https://example.test/mini-app?session=42&v=abcdef123456"
    )


def test_homework_session_checks_current_assignment_owner(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "homework-mini.sqlite3"
    db.init_db()
    owner = User(id=801, is_bot=False, first_name="Owner")
    child = User(id=802, is_bot=False, first_name="Child")
    stranger = User(id=803, is_bot=False, first_name="Stranger")
    for user in (owner, child, stranger):
        db.save_user(user)
    family = create_family("Home", owner.id)
    add_family_member(int(family["id"]), child.id)
    add_family_member(int(family["id"]), stranger.id)
    items = []
    for index in range(3):
        item_id = create_family_learning_item(int(family["id"]), create_lexeme(f"hw-mini-{index}"), f"hw-mini-{index}")
        create_learning_item_translation(item_id, "ru", f"слово-{index}")
        items.append(item_id)
    assignment_id = create_homework_assignment(int(family["id"]), owner.id, child.id, items, title="Practice")
    session_id = int(start_assignment_training_session(child.id, assignment_id)["session_id"])
    assert authorize_session(child.id, session_id)["id"] == session_id
    assert error_code(lambda: authorize_session(stranger.id, session_id)) == "access_denied"
    with db.get_connection() as connection:
        connection.execute("UPDATE homework_assignments SET assigned_to_user_id = ? WHERE id = ?", (stranger.id, assignment_id))
    assert error_code(lambda: authorize_session(child.id, session_id)) == "access_denied"


def test_homework_progress_counts_completed_words_without_boost(tmp_path):
    user_id, _ = seed(tmp_path)
    family_id = int(db.get_connection().execute("SELECT id FROM families").fetchone()[0])
    assignment_id = create_homework_assignment(family_id, user_id, user_id, [1, 2, 3], training_mode="hard")
    session_id = start_assignment_training_session(user_id, assignment_id)["session_id"]
    initial = session_state(user_id, session_id)["homework_progress"]
    assert initial["completed"] == 0
    assert "boost_active" not in initial
    question = get_current_question(user_id)
    helped = apply_action(user_id, session_id, question_token(question), "skip")
    assert helped["question"]["type"] == "jumbled_letters"
    submit_training_answer(user_id, str(get_current_question(user_id)["expected_answer"]))
    progress = session_state(user_id, session_id)["homework_progress"]
    assert progress["completed"] == 1
    assert progress["segments"][0] == {"value": 1.0, "hard_clear": False}


def test_http_transport_auth_state_and_answer(tmp_path: Path, monkeypatch) -> None:
    user_id, session_id = seed(tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    headers = {"x-telegram-init-data": sign_test_init_data(user_id, TOKEN)}
    class Bot:
        async def send_message(self, *_):
            pass
    async def request(path: str, method: str = "GET", body: bytes = b"") -> bytes:
        reader = asyncio.StreamReader()
        reader.feed_data(body)
        reader.feed_eof()
        request_headers = dict(headers)
        request_headers["content-length"] = str(len(body))
        return await _mini_app_response(method, path, request_headers, reader, Bot())
    import json
    path = f"/mini-app/api/sessions/{session_id}"
    response = asyncio.run(request(path))
    body = json.loads(response.split(b"\r\n\r\n", 1)[1])
    assert body["question"]["token"]
    answer = json.dumps({"token": body["question"]["token"], "action": "easy", "value": 0}).encode()
    answered = asyncio.run(request(path + "/answer", "POST", answer))
    assert b'"status":"active"' in answered


def test_tts_endpoint_reuses_persisted_variant(tmp_path: Path, monkeypatch) -> None:
    user_id, session_id = seed(tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("ENGLISHBOT_TTS_BASE_URL", "http://tts.internal")
    from englishbot import tts
    from englishbot.tts import TTSVoice, TTSVoiceCatalog
    calls = []
    class Client:
        model_key = "test-model"
        def fetch_voices(self):
            return TTSVoiceCatalog("voice", (TTSVoice("voice", "Voice"),))
        def synthesize(self, *, text, voice_id):
            calls.append((text, voice_id))
            return b"OggSdemo"
    monkeypatch.setattr(tts, "build_tts_client", lambda: Client())
    headers = {"x-telegram-init-data": sign_test_init_data(user_id, TOKEN)}
    async def request():
        reader = asyncio.StreamReader()
        reader.feed_eof()
        return await _mini_app_response("GET", f"/mini-app/api/sessions/{session_id}/tts", headers, reader, None)
    first = asyncio.run(request())
    second = asyncio.run(request())
    assert b"Content-Type: audio/ogg" in first
    assert first.endswith(b"OggSdemo")
    assert second.endswith(b"OggSdemo")
    assert len(calls) == 1


def test_tts_endpoint_disabled_or_failing_does_not_advance_session(tmp_path: Path, monkeypatch) -> None:
    user_id, session_id = seed(tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    headers = {"x-telegram-init-data": sign_test_init_data(user_id, TOKEN)}
    async def request():
        reader = asyncio.StreamReader()
        reader.feed_eof()
        return await _mini_app_response("GET", f"/mini-app/api/sessions/{session_id}/tts", headers, reader, None)
    token = session_state(user_id, session_id)["question"]["token"]
    monkeypatch.delenv("ENGLISHBOT_TTS_BASE_URL", raising=False)
    assert error_code(lambda: asyncio.run(request())) == "tts_unavailable"
    monkeypatch.setenv("ENGLISHBOT_TTS_BASE_URL", "http://tts.internal")
    from englishbot import tts
    from englishbot.tts import TTSUnavailableError
    class Client:
        model_key = "test-model"
        def fetch_voices(self):
            raise TTSUnavailableError("offline")
    monkeypatch.setattr(tts, "build_tts_client", lambda: Client())
    assert error_code(lambda: asyncio.run(request())) == "tts_unavailable"
    assert session_state(user_id, session_id)["question"]["token"] == token


def test_http_completion_sends_summary_once(tmp_path: Path, monkeypatch) -> None:
    user_id, session_id = seed(tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    with db.get_connection() as connection:
        connection.execute("UPDATE training_session_items SET is_completed = 1 WHERE session_id = ? AND item_order != 0", (session_id,))
        connection.execute("UPDATE training_session_items SET current_stage = 'hard', hard_unlocked = 1, easy_correct_count = 2, medium_correct_count = 2 WHERE session_id = ? AND item_order = 0", (session_id,))
    question = get_current_question(user_id)
    assert question["exercise_type"] == "typed_answer"
    import json
    payload = json.dumps({"token": question_token(question), "action": "hard", "value": question["expected_answer"]}).encode()
    headers = {"x-telegram-init-data": sign_test_init_data(user_id, TOKEN), "content-length": str(len(payload))}
    sent = []
    class Bot:
        async def send_message(self, user, text):
            sent.append((user, text))
    async def request():
        reader = asyncio.StreamReader()
        reader.feed_data(payload)
        reader.feed_eof()
        return await _mini_app_response("POST", f"/mini-app/api/sessions/{session_id}/answer", headers, reader, Bot())
    response = asyncio.run(request())
    assert b'"status":"completed"' in response
    assert len(sent) == 1
    assert error_code(lambda: asyncio.run(request())) == "session_completed"
    assert len(sent) == 1


def test_existing_http_server_serves_authenticated_session(tmp_path: Path, monkeypatch) -> None:
    user_id, session_id = seed(tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    signed = sign_test_init_data(user_id, TOKEN)
    build = BuildInfo("test", "abc", "today", "main", "local")
    class Bot:
        async def send_message(self, *_):
            pass
    async def smoke():
        server = await asyncio.start_server(lambda reader, writer: _handle_connection(reader, writer, build, Bot()), "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(f"GET /mini-app/api/sessions/{session_id} HTTP/1.1\r\nHost: localhost\r\nX-Telegram-Init-Data: {signed}\r\n\r\n".encode())
            await writer.drain()
            result = await reader.read()
            writer.close()
            await writer.wait_closed()
            return result
        finally:
            server.close()
            await server.wait_closed()
    response = asyncio.run(smoke())
    assert response.startswith(b"HTTP/1.1 200 OK")
    assert b'"question"' in response


def test_completion_notification_claim_is_idempotent(tmp_path: Path) -> None:
    _, session_id = seed(tmp_path)
    assert claim_completion_notification(session_id)
    assert not claim_completion_notification(session_id)


def test_interface_choice_uses_existing_session_and_https_url(tmp_path: Path, monkeypatch) -> None:
    user_id, session_id = seed(tmp_path)
    class Message:
        def __init__(self):
            self.sent = []
        async def answer(self, text, reply_markup=None):
            self.sent.append((text, reply_markup))
    message = Message()
    monkeypatch.delenv("ENGLISHBOT_MINI_APP_URL", raising=False)
    assert asyncio.run(offer_training_interfaces(message, user_id)) is False
    assert not message.sent
    monkeypatch.setenv("ENGLISHBOT_MINI_APP_URL", "https://example.test/mini-app")
    assert asyncio.run(offer_training_interfaces(message, user_id)) is True
    buttons = message.sent[0][1].inline_keyboard
    assert buttons[0][0].web_app.url == f"https://example.test/mini-app?session={session_id}"
    assert buttons[1][0].callback_data.endswith(str(session_id))
    assert build_mini_app_url("https://example.test/mini-app?x=1", session_id) == f"https://example.test/mini-app?x=1&session={session_id}"


def test_invalid_optional_url_falls_back_to_telegram(monkeypatch) -> None:
    monkeypatch.setenv("ENGLISHBOT_MINI_APP_URL", "http://localhost:8080/mini-app")
    assert get_mini_app_url() is None
