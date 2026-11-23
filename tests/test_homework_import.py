import asyncio
import io
import json
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiogram.types import User
from PIL import Image

from englishbot import ai_extraction, db, homework_import_handlers, status_server
from englishbot.ai_extraction import (
    AIExtractionUnavailable,
    ExtractionResult,
    ExtractionSource,
    extract_items,
    normalize_words,
    parse_json_object,
)
from englishbot.dictionary_editor import create_topic, create_word
from englishbot.families import add_family_member, create_family
from englishbot.homework_sets import (
    HomeworkSetError,
    add_set_photo,
    add_word_picture,
    crop_set_photo,
    add_source,
    begin_processing,
    create_empty_draft,
    get_draft,
    get_set,
    save_draft,
    set_photo_path,
    store_extraction,
    store_source_photos,
)
from englishbot.mini_app import MiniAppError, sign_test_init_data
from englishbot.status_server import _mini_app_response


TOKEN = "123456:test-token"
MOM = 901
KID = 902
STRANGER = 903


@pytest.fixture
def family(tmp_path: Path, monkeypatch) -> int:
    db.DB_PATH = tmp_path / "data" / "import.sqlite3"
    db.DB_PATH.parent.mkdir()
    db.init_db()
    for user_id, name in ((MOM, "Mom"), (KID, "Teia"), (STRANGER, "Other")):
        db.save_user(User(id=user_id, is_bot=False, first_name=name))
    family_row = create_family("Home", MOM)
    add_family_member(int(family_row["id"]), KID)
    create_family("Other", STRANGER)
    monkeypatch.setenv("ENGLISHBOT_OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("ENGLISHBOT_AI_MODELS", raising=False)
    return int(family_row["id"])


def error_code(call) -> str:
    with pytest.raises(HomeworkSetError) as caught:
        call()
    return caught.value.code


# Model reply parsing


def test_parse_json_object_tolerates_fences_and_prose() -> None:
    assert parse_json_object('Sure!\n```json\n{"words": []}\n```') == {"words": []}
    with pytest.raises(ValueError):
        parse_json_object("no json here")


def test_normalize_words_dedupes_and_skips_invalid_entries() -> None:
    payload = {"words": [
        {"en": " Dragon ", "ru": "дракон", "topic": "Fairy Tales"},
        {"en": "dragon", "ru": "дракон", "topic": "Fairy Tales"},
        {"en": "", "ru": "пусто"},
        "garbage",
        {"en": "wizard", "ru": None, "topic": None},
    ]}
    assert normalize_words(payload) == [
        {"en": "Dragon", "ru": "дракон", "topic": "Fairy Tales"},
        {"en": "wizard", "ru": "", "topic": ""},
    ]
    assert normalize_words({"words": "nope"}) == []


def test_extract_items_sends_first_queued_model_and_images(family: int, monkeypatch) -> None:
    sent = {}

    def fake_post(body, api_key):
        sent.update(body=body, api_key=api_key)
        return {"model": "particle-ai/particle-1:free", "choices": [{"message": {"content": '{"words":[{"en":"cat","ru":"кошка","topic":"Animals"}]}'}}]}

    monkeypatch.setattr(ai_extraction, "_post", fake_post)
    photo = io.BytesIO()
    Image.new("RGB", (3000, 1000), "white").save(photo, format="PNG")

    result = extract_items("words", [ExtractionSource(text="cat - кошка"), ExtractionSource(image=photo.getvalue())])

    assert result.model == "particle-ai/particle-1:free"
    assert result.items == [{"en": "cat", "ru": "кошка", "topic": "Animals"}]
    assert sent["api_key"] == "test-key"
    assert sent["body"]["model"] == "particle-ai/particle-1:free"
    image_parts = [part for part in sent["body"]["messages"][1]["content"] if part["type"] == "image_url"]
    assert image_parts[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_extract_items_reports_unavailable_models(family: int, monkeypatch) -> None:
    def failing_post(body, api_key):
        raise urllib.error.HTTPError("url", 429, "rate limited", {}, None)

    monkeypatch.setattr(ai_extraction, "_post", failing_post)
    with pytest.raises(AIExtractionUnavailable):
        extract_items("words", [ExtractionSource(text="cat")])
    monkeypatch.delenv("ENGLISHBOT_OPENROUTER_API_KEY")
    with pytest.raises(AIExtractionUnavailable):
        extract_items("words", [ExtractionSource(text="cat")])


# Homework set lifecycle


def make_draft(items: list[dict[str, str]]) -> int:
    add_source(MOM, text="Fairy Tales: Dragon - дракон")
    row = add_source(MOM, photo_file_id="photo-1")
    set_id = int(row["id"])
    begin_processing(MOM, set_id, "words")
    store_extraction(set_id, ExtractionResult(model="test-model", items=items))
    return set_id


def test_sources_accumulate_in_one_collecting_set(family: int) -> None:
    first = add_source(MOM, text="hello")
    second = add_source(MOM, photo_file_id="file-1")
    assert first["id"] == second["id"]
    assert json.loads(second["sources_json"]) == [{"text": "hello"}, {"photo_file_id": "file-1"}]
    assert error_code(lambda: add_source(MOM)) == "empty_source"
    assert error_code(lambda: begin_processing(STRANGER, int(first["id"]), "words")) == "set_not_found"
    assert error_code(lambda: begin_processing(MOM, int(first["id"]), "verbs")) == "unsupported_kind"


def test_draft_marks_known_words_and_reuses_existing_topic_title(family: int) -> None:
    topic = create_topic(MOM, "Fairy Tales")
    create_word(MOM, topic["id"], "dragon", {"ru": "дракон"})

    set_id = make_draft([
        {"en": "Dragon", "ru": "дракон", "topic": "fairy tales"},
        {"en": "wizard", "ru": "волшебник", "topic": "fairy tales"},
    ])
    draft = get_draft(MOM, set_id)

    assert [(item["en"], bool(item["existing_id"]), item["topic"]) for item in draft["tasks"][0]["items"]] == [
        ("Dragon", True, "Fairy Tales"),
        ("wizard", False, "Fairy Tales"),
    ]
    assert draft["set"]["title"].startswith("Homework ")
    assert [member["id"] for member in draft["members"]][-1] == MOM  # the author is listed last
    assert {mode["code"] for mode in draft["modes"]} == {"easy", "medium", "hard"}


def test_save_draft_creates_words_links_known_ones_and_assigns_homework(family: int) -> None:
    animals = create_topic(MOM, "Animals")
    cat = create_word(MOM, animals["id"], "cat", {"ru": "кошка"})
    set_id = make_draft([])

    result = save_draft(MOM, set_id, {
        "title": "ДЗ 23.11",
        "mode": "medium",
        "assign_to": KID,
        "items": [
            {"en": "Dragon", "ru": "дракон", "topic": "Fairy Tales", "include": True},
            {"en": "cat", "ru": "", "topic": "Fairy Tales", "include": True, "existing_id": cat["id"]},
            {"en": "skip me", "ru": "", "topic": "Fairy Tales", "include": False},
            {"en": "Candles", "ru": "свечи", "topic": "Birthday", "include": True},
        ],
    })

    assert result["word_count"] == 3 and result["created_words"] == 2 and result["assigned_to"] == KID
    with db.get_connection() as connection:
        topics = {row["title"]: row["id"] for row in connection.execute("SELECT id, title FROM topics WHERE is_archived = 0")}
        assert set(topics) == {"Animals", "Fairy Tales", "Birthday"}
        fairy_words = [row[0] for row in connection.execute(
            "SELECT li.text FROM topic_items ti JOIN learning_items li ON li.id = ti.learning_item_id WHERE ti.topic_id = ? ORDER BY ti.id",
            (topics["Fairy Tales"],),
        )]
        assert fairy_words == ["Dragon", "cat"]
        assert connection.execute("SELECT COUNT(*) FROM learning_items WHERE lower(text) = 'cat'").fetchone()[0] == 1
        assignment = connection.execute("SELECT * FROM homework_assignments WHERE id = ?", (result["assignment_id"],)).fetchone()
        assert (assignment["assigned_to_user_id"], assignment["training_mode"], assignment["homework_set_id"], assignment["title"]) == (KID, "medium", set_id, "ДЗ 23.11")
        assert connection.execute("SELECT COUNT(*) FROM homework_set_items WHERE homework_set_id = ?", (set_id,)).fetchone()[0] == 3
        translation = connection.execute(
            "SELECT t.translation_text FROM learning_item_translations t JOIN learning_items li ON li.id = t.learning_item_id WHERE li.text = 'Candles'"
        ).fetchone()[0]
        assert translation == "свечи"

    assert error_code(lambda: save_draft(MOM, set_id, {"items": []})) == "draft_not_available"


def test_save_draft_validates_recipient_mode_and_topic(family: int) -> None:
    set_id = make_draft([])
    new_word = [{"en": "owl", "ru": "сова", "topic": "", "include": True}]
    assert error_code(lambda: save_draft(MOM, set_id, {"items": new_word, "assign_to": STRANGER})) == "invalid_recipient"
    assert error_code(lambda: save_draft(MOM, set_id, {"items": new_word, "mode": "insane"})) == "invalid_mode"
    assert error_code(lambda: save_draft(MOM, set_id, {"items": new_word})) == "topic_required"


def test_save_without_recipient_only_saves_the_set(family: int) -> None:
    set_id = make_draft([])
    result = save_draft(MOM, set_id, {"items": [{"en": "owl", "ru": "сова", "topic": "Birds"}], "assign_to": None})
    assert result["assignment_id"] is None and result["word_count"] == 1


# Telegram flow


class FakeBot:
    def __init__(self) -> None:
        self.deleted: list[int] = []
        self.sent: list[dict[str, object]] = []

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        self.deleted.append(message_id)

    async def download(self, file_id: str):
        output = io.BytesIO()
        Image.new("RGB", (20, 20), "white").save(output, format="PNG")
        output.seek(0)
        return output

    async def send_message(self, **kwargs) -> None:
        self.sent.append(kwargs)


class FakeMessage:
    counter = 100

    def __init__(self, bot: FakeBot, *, text=None, photo=None, forwarded=True) -> None:
        self.bot = bot
        self.from_user = SimpleNamespace(id=MOM)
        self.chat = SimpleNamespace(id=MOM, type="private")
        self.forward_origin = object() if forwarded else None
        self.text = text
        self.caption = None
        self.photo = photo
        self.answers: list[tuple[str, object]] = []
        self.edits: list[tuple[str, object]] = []

    async def answer(self, text: str, reply_markup=None):
        FakeMessage.counter += 1
        self.answers.append((text, reply_markup))
        return SimpleNamespace(chat=SimpleNamespace(id=MOM), message_id=FakeMessage.counter)

    async def edit_text(self, text: str, reply_markup=None) -> None:
        self.edits.append((text, reply_markup))


class FakeCallback:
    def __init__(self, data: str, message: FakeMessage) -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=MOM)
        self.message = message

    async def answer(self, *args, **kwargs) -> None:
        return None


def test_forward_filter_requires_forward_family_and_the_editor(family: int, monkeypatch) -> None:
    monkeypatch.setenv("ENGLISHBOT_MINI_APP_URL", "https://example.org/mini-app")
    bot = FakeBot()
    assert homework_import_handlers.is_homework_forward(FakeMessage(bot, text="cat"))
    assert not homework_import_handlers.is_homework_forward(FakeMessage(bot, text="cat", forwarded=False))
    stranger = FakeMessage(bot, text="cat")
    stranger.from_user = SimpleNamespace(id=999)
    assert not homework_import_handlers.is_homework_forward(stranger)
    monkeypatch.delenv("ENGLISHBOT_OPENROUTER_API_KEY")  # without AI the draft can still be filled by hand
    assert homework_import_handlers.is_homework_forward(FakeMessage(bot, text="cat"))
    monkeypatch.delenv("ENGLISHBOT_MINI_APP_URL")
    assert not homework_import_handlers.is_homework_forward(FakeMessage(bot, text="cat"))


def test_forward_then_words_produces_draft_link(family: int, monkeypatch) -> None:
    monkeypatch.setenv("ENGLISHBOT_MINI_APP_URL", "https://example.org/mini-app")
    seen_sources = []

    def fake_extract(kind, sources):
        seen_sources.extend(sources)
        return ExtractionResult(model="m", items=[{"en": "dragon", "ru": "дракон", "topic": "Fairy Tales"}])

    monkeypatch.setattr(homework_import_handlers, "extract_items", fake_extract)
    bot = FakeBot()

    async def scenario():
        first = FakeMessage(bot, text="Dragon - дракон")
        await homework_import_handlers.collect_homework_forward(first)
        second = FakeMessage(bot, photo=[SimpleNamespace(file_id="small"), SimpleNamespace(file_id="big")])
        await homework_import_handlers.collect_homework_forward(second)
        keyboard = second.answers[-1][1]
        words_data = keyboard.inline_keyboard[0][0].callback_data
        await homework_import_handlers.handle_homework_import_callback(FakeCallback(words_data, second))
        await asyncio.gather(*homework_import_handlers._background_tasks)
        return first, second

    first, second = asyncio.run(scenario())

    assert "messages 1, photos 1" in second.answers[-1][0]
    assert bot.deleted == [first.counter - 1]  # the first control message was replaced
    assert [source.text for source in seen_sources] == ["Dragon - дракон", None]
    assert seen_sources[1].image is not None
    final_text, final_keyboard = second.edits[-1]
    assert "Words found: 1" in final_text
    assert final_keyboard.inline_keyboard[0][0].web_app.url.startswith("https://example.org/mini-app/editor?import=")


def test_failed_extraction_offers_retry(family: int, monkeypatch) -> None:
    def failing(kind, sources):
        raise AIExtractionUnavailable("HTTP 429")

    monkeypatch.setattr(homework_import_handlers, "extract_items", failing)
    bot = FakeBot()

    async def scenario():
        message = FakeMessage(bot, text="Dragon - дракон")
        await homework_import_handlers.collect_homework_forward(message)
        data = message.answers[-1][1].inline_keyboard[0][0].callback_data
        await homework_import_handlers.handle_homework_import_callback(FakeCallback(data, message))
        await asyncio.gather(*homework_import_handlers._background_tasks)
        return message

    message = asyncio.run(scenario())
    text, keyboard = message.edits[-1]
    assert "unavailable" in text
    assert keyboard.inline_keyboard[0][0].callback_data.startswith("hwimport:words:")


# Editor HTTP API


def request(path: str, *, method: str = "GET", body: bytes = b"") -> tuple[int, dict]:
    async def run() -> bytes:
        reader = asyncio.StreamReader()
        reader.feed_data(body)
        reader.feed_eof()
        headers = {"content-length": str(len(body)), "x-telegram-init-data": sign_test_init_data(MOM, TOKEN)}
        return await _mini_app_response(method, path, headers, reader, object())

    try:
        response = asyncio.run(run())
    except MiniAppError as exc:
        return exc.status, {"error": exc.code}
    head, payload = response.split(b"\r\n\r\n", 1)
    return int(head.split(b" ")[1]), json.loads(payload)


def test_http_draft_load_save_and_notify_child(family: int, monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    bot = FakeBot()
    monkeypatch.setattr(status_server, "_mini_app_bot", bot)
    set_id = make_draft([{"en": "owl", "ru": "сова", "topic": "Birds"}])

    status, draft = request(f"/mini-app/api/editor/imports/{set_id}")
    assert status == 200 and draft["tasks"][0]["items"][0]["en"] == "owl" and draft["labels"]["save_draft"]

    payload = {"title": "ДЗ", "mode": "easy", "assign_to": KID, "tasks": draft["tasks"]}
    status, result = request(f"/mini-app/api/editor/imports/{set_id}/save", method="POST", body=json.dumps(payload).encode())
    assert status == 200 and result["assigned_to"] == KID and "_notify" not in result
    assert bot.sent[0]["chat_id"] == KID and "ДЗ" in bot.sent[0]["text"]

    status, result = request(f"/mini-app/api/editor/imports/{set_id}")
    assert (status, result["error"]) == (409, "draft_not_available")


# Saved sets: list, rename, assign again


def saved_set(assign_to: int | None = KID) -> int:
    set_id = make_draft([])
    save_draft(MOM, set_id, {
        "title": "ДЗ 23.11",
        "assign_to": assign_to,
        "items": [
            {"en": "owl", "ru": "сова", "topic": "Birds"},
            {"en": "crow", "ru": "ворона", "topic": "Birds"},
        ],
    })
    return set_id


def test_saved_sets_are_listed_with_words_and_assignments(family: int) -> None:
    from englishbot.homework_sets import get_set, list_sets

    set_id = saved_set()
    make_draft([])  # an unsaved draft must not be listed

    assert [(row["id"], row["title"], row["item_count"], row["assignment_count"]) for row in list_sets(MOM)] == [(set_id, "ДЗ 23.11", 2, 1)]
    assert list_sets(STRANGER) == []
    details = get_set(MOM, set_id)
    assert [word["text"] for word in details["words"]] == ["owl", "crow"]
    assert details["assignments"][0]["to"] == "Teia"
    assert error_code(lambda: get_set(STRANGER, set_id)) == "set_not_found"


def test_rename_set_also_renames_its_assignments(family: int) -> None:
    from englishbot.homework_sets import rename_set

    set_id = saved_set()
    assert rename_set(MOM, set_id, "  Птицы, часть 1 ")["title"] == "Птицы, часть 1"
    with db.get_connection() as connection:
        assert connection.execute("SELECT title FROM homework_sets WHERE id = ?", (set_id,)).fetchone()[0] == "Птицы, часть 1"
        assert [row[0] for row in connection.execute("SELECT title FROM homework_assignments WHERE homework_set_id = ?", (set_id,))] == ["Птицы, часть 1"]
    assert error_code(lambda: rename_set(MOM, set_id, "   ")) == "text_required"


def test_assign_set_again_skips_deleted_words(family: int) -> None:
    from englishbot.dictionary_editor import delete_word
    from englishbot.homework_sets import assign_set, get_set

    set_id = saved_set(assign_to=None)
    owl_id = get_set(MOM, set_id)["words"][0]["id"]
    delete_word(MOM, owl_id)

    result = assign_set(MOM, set_id, KID, "hard")

    assert result["word_count"] == 1
    with db.get_connection() as connection:
        assignment = connection.execute("SELECT training_mode, homework_set_id FROM homework_assignments WHERE id = ?", (result["assignment_id"],)).fetchone()
        assert tuple(assignment) == ("hard", set_id)
    assert error_code(lambda: assign_set(MOM, set_id, STRANGER, "easy")) == "invalid_recipient"
    assert error_code(lambda: assign_set(MOM, set_id, KID, "nope")) == "invalid_mode"


def test_http_sets_rename_and_assign_notifies(family: int, monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    bot = FakeBot()
    monkeypatch.setattr(status_server, "_mini_app_bot", bot)
    set_id = saved_set(assign_to=None)

    status, listing = request("/mini-app/api/editor/sets")
    assert status == 200 and listing["sets"][0]["id"] == set_id and listing["labels"]["sets"]
    status, renamed = request(f"/mini-app/api/editor/sets/{set_id}", method="POST", body=json.dumps({"title": "Birds 1"}).encode())
    assert (status, renamed["title"]) == (200, "Birds 1")
    status, assigned = request(f"/mini-app/api/editor/sets/{set_id}/assign", method="POST", body=json.dumps({"assign_to": KID, "mode": "easy"}).encode())
    assert status == 200 and assigned["word_count"] == 2
    assert bot.sent[0]["chat_id"] == KID and "Birds 1" in bot.sent[0]["text"]


def test_drafts_are_listed_until_saved_or_deleted(family: int, monkeypatch) -> None:
    from englishbot.dictionary_editor import route_editor_request

    def editor(method: str, path: list[str], user_id: int = MOM):
        return route_editor_request(method, path, user_id, b"{}")

    kept = make_draft([{"en": "owl", "ru": "сова", "topic": "Birds"}])
    listing = editor("GET", ["sets"])
    assert [(draft["id"], draft["item_count"]) for draft in listing["drafts"]] == [(kept, 1)]
    assert editor("GET", ["sets"], STRANGER)["drafts"] == []

    assert editor("POST", ["imports", str(kept), "cancel"]) == {"deleted": True}
    assert editor("GET", ["sets"])["drafts"] == []

    saved = saved_set(assign_to=None)
    assert editor("GET", ["sets"])["drafts"] == []
    with pytest.raises(MiniAppError) as caught:
        editor("POST", ["imports", str(saved), "cancel"])
    assert caught.value.code == "draft_not_available"


def test_archive_hides_set_without_touching_homework_and_restore_brings_it_back(family: int) -> None:
    from englishbot.homework_sets import archive_set, get_set, list_sets, restore_set

    set_id = saved_set()  # assigned to KID, still active
    archive_set(MOM, set_id)

    assert list_sets(MOM) == []
    assert [row["id"] for row in list_sets(MOM, archived=True)] == [set_id]
    assert get_set(MOM, set_id)["set"]["archived"] is True
    with db.get_connection() as connection:
        assert connection.execute("SELECT status FROM homework_assignments WHERE homework_set_id = ?", (set_id,)).fetchone()[0] == "active"

    restore_set(MOM, set_id)
    assert [row["id"] for row in list_sets(MOM)] == [set_id]
    assert list_sets(MOM, archived=True) == []


def test_set_words_can_be_added_from_dictionary_or_created_and_removed(family: int) -> None:
    from englishbot.dictionary_editor import search_words
    from englishbot.homework_sets import add_set_word, assign_set, remove_set_word

    animals = create_topic(MOM, "Animals")
    cat = create_word(MOM, animals["id"], "cat", {"ru": "кошка"})
    set_id = saved_set()  # owl, crow; already assigned once

    assert [word["text"] for word in search_words(MOM, "КОШ")] == ["cat"]  # Cyrillic is matched in any case
    from englishbot.dictionary_editor import route_editor_request
    assert [word["text"] for word in route_editor_request("POST", ["words", "search"], MOM, '{"q": "Cat"}'.encode())["words"]] == ["cat"]
    assert search_words(STRANGER, "cat") == []
    add_set_word(MOM, set_id, {"word_id": cat["id"]})
    details = add_set_word(MOM, set_id, {"en": "eagle", "ru": "орёл", "topic": "Birds"})
    assert [word["text"] for word in details["words"]] == ["owl", "crow", "cat", "eagle"]
    add_set_word(MOM, set_id, {"word_id": cat["id"]})  # adding twice keeps one entry
    owl_id = details["words"][0]["id"]
    details = remove_set_word(MOM, set_id, owl_id)
    assert [word["text"] for word in details["words"]] == ["crow", "cat", "eagle"]
    assert error_code(lambda: add_set_word(MOM, set_id, {"en": "hawk", "ru": "ястреб", "topic": ""})) == "topic_required"

    with db.get_connection() as connection:
        first = connection.execute("SELECT id FROM homework_assignments WHERE homework_set_id = ? ORDER BY id", (set_id,)).fetchone()[0]
        assert connection.execute("SELECT COUNT(*) FROM homework_assignment_items WHERE homework_assignment_id = ?", (first,)).fetchone()[0] == 2
    assert assign_set(MOM, set_id, KID, "easy")["word_count"] == 3  # the next assignment uses the edited set


def test_homework_overview_shows_progress_and_cancel_closes_the_session(family: int) -> None:
    from englishbot.homework import list_active_assignments
    from englishbot.homework_sets import cancel_assignment, list_assignments

    set_id = saved_set()
    with db.get_connection() as connection:
        assignment_id = connection.execute("SELECT id FROM homework_assignments WHERE homework_set_id = ?", (set_id,)).fetchone()[0]
        session_id = connection.execute(
            "INSERT INTO training_sessions (telegram_user_id, family_homework_assignment_id, current_index, correct_answers, total_questions, status, created_at, updated_at)"
            " VALUES (?, ?, 0, 1, 2, 'active', 'x', 'x')",
            (KID, assignment_id),
        ).lastrowid
        for order, completed in enumerate((1, 0)):
            connection.execute(
                "INSERT INTO training_session_items (session_id, learning_item_id, prompt_text, expected_answer, item_order, is_completed)"
                " VALUES (?, (SELECT learning_item_id FROM homework_assignment_items WHERE homework_assignment_id = ? AND item_order = ?), 'p', 'a', ?, ?)",
                (session_id, assignment_id, order, order, completed),
            )

    overview = list_assignments(MOM)
    assert [(row["id"], row["done"], row["total"], row["to"], row["set_id"]) for row in overview["active"]] == [(assignment_id, 1, 2, "Teia", set_id)]
    assert list_assignments(STRANGER) == {"active": [], "finished": []}

    cancel_assignment(MOM, assignment_id)

    assert list_active_assignments(KID) == []
    overview = list_assignments(MOM)
    assert overview["active"] == [] and overview["finished"][0]["status"] == "cancelled"
    with db.get_connection() as connection:
        assert connection.execute("SELECT status FROM training_sessions WHERE id = ?", (session_id,)).fetchone()[0] == "cancelled"
    assert error_code(lambda: cancel_assignment(MOM, assignment_id)) == "assignment_not_active"
    assert error_code(lambda: cancel_assignment(STRANGER, assignment_id)) == "assignment_not_found"


def test_assign_defaults_follow_the_last_assignment_and_sets_report_activity(family: int) -> None:
    from englishbot.homework_sets import assign_set, get_set, list_sets

    first = make_draft([])
    assert get_draft(MOM, first)["defaults"] == {"recipient": None, "mode": "easy"}
    save_draft(MOM, first, {"items": [{"en": "owl", "ru": "сова", "topic": "Birds"}], "assign_to": None})
    assign_set(MOM, first, KID, "medium")

    second = make_draft([])
    assert get_draft(MOM, second)["defaults"] == {"recipient": KID, "mode": "medium"}
    assert get_set(MOM, first)["defaults"] == {"recipient": KID, "mode": "medium"}
    assert [(row["id"], row["active_count"]) for row in list_sets(MOM)] == [(first, 1)]


def test_word_picked_from_another_topic_joins_homework_without_moving_topics(family: int) -> None:
    transport = create_topic(MOM, "Transport")
    boat = create_word(MOM, transport["id"], "boat", {"ru": "лодка"})
    set_id = make_draft([{"en": "shark", "ru": "акула", "topic": "Fishes"}])

    result = save_draft(MOM, set_id, {
        "assign_to": KID,
        "items": [
            {"en": "shark", "ru": "акула", "topic": "Fishes", "include": True},
            {"en": "boat", "ru": "лодка", "topic": "", "include": True, "existing_id": boat["id"]},
        ],
    })

    assert result["word_count"] == 2 and result["created_words"] == 1
    with db.get_connection() as connection:
        topics_of_boat = [row[0] for row in connection.execute(
            "SELECT topics.title FROM topic_items JOIN topics ON topics.id = topic_items.topic_id WHERE topic_items.learning_item_id = ?",
            (boat["id"],),
        )]
        assert topics_of_boat == ["Transport"]
        homework_words = [row[0] for row in connection.execute(
            "SELECT li.text FROM homework_assignment_items hai JOIN learning_items li ON li.id = hai.learning_item_id WHERE hai.homework_assignment_id = ? ORDER BY hai.item_order",
            (result["assignment_id"],),
        )]
        assert homework_words == ["shark", "boat"]


# Tasks and photos


def png_bytes(color: str = "white") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(output, format="PNG")
    return output.getvalue()


def test_draft_starts_with_words_and_the_tutor_text_as_a_note(family: int) -> None:
    set_id = make_draft([{"en": "owl", "ru": "сова", "topic": "Birds"}])
    tasks = get_draft(MOM, set_id)["tasks"]
    assert [task["kind"] for task in tasks] == ["words", "note"]
    assert tasks[1]["instructions"] == "Fairy Tales: Dragon - дракон"
    assert tasks[1]["enabled"] is True


def test_source_photos_are_stored_once_and_bad_images_skipped(family: int) -> None:
    set_id = make_draft([])
    first = store_source_photos(set_id, [png_bytes(), b"not an image", png_bytes("red")])
    assert len(first) == 2
    assert store_source_photos(set_id, [png_bytes()]) == first  # a retry does not duplicate them
    assert set_photo_path(MOM, set_id, first[0]).read_bytes()[:2] == b"\xff\xd8"  # stored as JPEG
    assert get_draft(MOM, set_id)["photos"] == first
    assert error_code(lambda: set_photo_path(STRANGER, set_id, first[0])) == "set_not_found"
    assert error_code(lambda: set_photo_path(MOM, set_id, 99999)) == "image_not_found"


def test_save_keeps_task_order_photos_and_word_links(family: int) -> None:
    set_id = make_draft([])
    photo_a, photo_b = store_source_photos(set_id, [png_bytes(), png_bytes("red")])
    uploaded = add_set_photo(MOM, set_id, png_bytes("blue"))["id"]
    result = save_draft(MOM, set_id, {"title": "ДЗ", "assign_to": KID, "tasks": [
        {"kind": "paper", "title": "Crossword", "instructions": "Fill it in\non paper", "photos": [photo_a, uploaded]},
        {"kind": "words", "items": [{"en": "owl", "ru": "сова", "topic": "Birds"}], "photos": [photo_b]},
        {"kind": "note", "title": "Skipped", "instructions": "x", "enabled": False},
        {"kind": "words", "items": [{"en": "owl", "ru": "сова", "topic": "Birds"}, {"en": "crow", "ru": "ворона", "topic": "Birds"}]},
        {"kind": "paper", "title": "", "instructions": "", "photos": []},  # empty: dropped
    ]})
    assert (result["task_count"], result["word_count"], result["assignment_id"] is not None) == (3, 2, True)

    saved = get_set(MOM, set_id)
    assert [(task["kind"], task["title"], task["photos"]) for task in saved["tasks"]] == [
        ("paper", "Crossword", [photo_a, uploaded]),
        ("words", "", [photo_b]),
        ("words", "", []),
    ]
    assert saved["tasks"][0]["instructions"] == "Fill it in\non paper"
    words_by_task = {word["text"]: word["task_id"] for word in saved["words"]}
    assert words_by_task == {"owl": saved["tasks"][1]["id"], "crow": saved["tasks"][2]["id"]}  # owl only once


def test_save_rejects_foreign_photos_unknown_kinds_and_empty_drafts(family: int) -> None:
    other = make_draft([])
    foreign = store_source_photos(other, [png_bytes()])[0]
    set_id = create_empty_draft(MOM)["id"]
    assert error_code(lambda: save_draft(MOM, set_id, {"tasks": [{"kind": "paper", "title": "x", "photos": [foreign]}]})) == "image_not_found"
    assert error_code(lambda: save_draft(MOM, set_id, {"tasks": [{"kind": "poem", "title": "x"}]})) == "invalid_task_kind"
    assert error_code(lambda: save_draft(MOM, set_id, {"tasks": [{"kind": "words", "items": []}]})) == "draft_empty"
    assert error_code(lambda: add_set_photo(MOM, set_id, b"junk")) == "invalid_image"


def test_empty_draft_from_the_editor_has_one_words_task(family: int) -> None:
    set_id = create_empty_draft(MOM)["id"]
    draft = get_draft(MOM, set_id)
    assert [task["kind"] for task in draft["tasks"]] == ["words"] and draft["photos"] == []
    assert {kind["code"] for kind in draft["task_kinds"]} == {"words", "paper", "note"}


def test_manual_draft_skips_ai_and_keeps_text_and_photos(family: int, monkeypatch) -> None:
    monkeypatch.setenv("ENGLISHBOT_MINI_APP_URL", "https://example.org/mini-app")
    monkeypatch.delenv("ENGLISHBOT_OPENROUTER_API_KEY")

    def no_ai(kind, sources):
        raise AssertionError("AI must not be called")

    monkeypatch.setattr(homework_import_handlers, "extract_items", no_ai)
    bot = FakeBot()

    async def scenario():
        await homework_import_handlers.collect_homework_forward(FakeMessage(bot, text="Crossword: weather"))
        message = FakeMessage(bot, photo=[SimpleNamespace(file_id="big")])
        await homework_import_handlers.collect_homework_forward(message)
        buttons = [row[0].callback_data for row in message.answers[-1][1].inline_keyboard]
        assert buttons[0].startswith("hwimport:manual:")  # no AI button without a key
        await homework_import_handlers.handle_homework_import_callback(FakeCallback(buttons[0], message))
        await asyncio.gather(*homework_import_handlers._background_tasks)
        return message, int(buttons[0].rsplit(":", 1)[1])

    message, set_id = asyncio.run(scenario())
    draft = get_draft(MOM, set_id)
    assert [task["kind"] for task in draft["tasks"]] == ["words", "note"]
    assert draft["tasks"][1]["instructions"] == "Crossword: weather"
    assert len(draft["photos"]) == 1
    text, keyboard = message.edits[-1]
    assert "draft is ready" in text and keyboard.inline_keyboard[0][0].web_app is not None


def test_http_new_homework_upload_and_read_photo(family: int, monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    status, created = request("/mini-app/api/editor/imports", method="POST")
    assert status == 200
    set_id = created["id"]
    status, photo = request(f"/mini-app/api/editor/imports/{set_id}/photos", method="POST", body=png_bytes())
    assert status == 200

    async def read_photo() -> bytes:
        reader = asyncio.StreamReader()
        reader.feed_eof()
        headers = {"content-length": "0", "x-telegram-init-data": sign_test_init_data(MOM, TOKEN)}
        return await _mini_app_response("GET", f"/mini-app/api/editor/sets/{set_id}/photos/{photo['id']}", headers, reader, object())

    response = asyncio.run(read_photo())
    head, content = response.split(b"\r\n\r\n", 1)
    assert b"200" in head.split(b"\r\n")[0] and b"image/jpeg" in head and content[:2] == b"\xff\xd8"


def test_sets_saved_before_tasks_get_one_words_task(family: int) -> None:
    set_id = saved_set(assign_to=None)
    with db.get_connection() as connection:
        connection.execute("UPDATE homework_set_items SET task_id = NULL WHERE homework_set_id = ?", (set_id,))
        connection.execute("DELETE FROM homework_set_tasks WHERE homework_set_id = ?", (set_id,))
    db.init_db()
    saved = get_set(MOM, set_id)
    assert [task["kind"] for task in saved["tasks"]] == ["words"]
    assert {word["task_id"] for word in saved["words"]} == {saved["tasks"][0]["id"]}


# Word pictures cut from the tutor's pages


def page_bytes() -> bytes:
    output = io.BytesIO()
    page = Image.new("RGB", (800, 600), "white")
    page.paste(Image.new("RGB", (300, 300), "red"), (100, 100))  # the "drawing" of the first word
    page.save(output, format="PNG")
    return output.getvalue()


def test_normalize_words_keeps_valid_picture_boxes() -> None:
    payload = {"words": [
        {"en": "tuna", "ru": "тунец", "picture": 1, "box": [100, 50, 400, 500]},
        {"en": "eel", "ru": "угорь", "picture": "2", "box": [0, 0, 1200, 900]},
        {"en": "shark", "ru": "акула", "picture": 0, "box": [1, 2, 300, 400]},
        {"en": "fin", "ru": "плавник", "picture": 1, "box": [10, 10, 15, 15]},
        {"en": "owl", "ru": "сова", "picture": 1, "box": "nope"},
    ]}
    words = normalize_words(payload)
    assert words[0]["picture"] == 1 and words[0]["box"] == [100.0, 50.0, 400.0, 500.0]
    assert words[1]["picture"] == 2 and words[1]["box"] == [0.0, 0.0, 1000.0, 900.0]  # clamped
    assert all("box" not in word for word in words[2:])


def test_pictures_are_numbered_for_the_model(family: int, monkeypatch) -> None:
    sent = {}

    def fake_post(body, api_key):
        sent.update(body=body)
        return {"choices": [{"message": {"content": '{"words": []}'}}]}

    monkeypatch.setattr(ai_extraction, "_post", fake_post)
    extract_items("words", [ExtractionSource(image=page_bytes()), ExtractionSource(image=page_bytes())])
    texts = [part["text"] for part in sent["body"]["messages"][1]["content"] if part["type"] == "text"]
    assert "Picture 1:" in texts and "Picture 2:" in texts


def test_extraction_cuts_word_pictures_from_the_pages(family: int) -> None:
    topic = create_topic(MOM, "Fish")
    known = create_word(MOM, topic["id"], "tuna", {"ru": "тунец"})
    with_picture = create_word(MOM, topic["id"], "eel", {"ru": "угорь"})
    from englishbot.dictionary_editor import set_word_image
    set_word_image(MOM, with_picture["id"], page_bytes())

    row = add_source(MOM, text="Fish")
    set_id = int(row["id"])
    begin_processing(MOM, set_id, "words")
    pages = store_source_photos(set_id, [page_bytes()])
    store_extraction(set_id, ExtractionResult(model="m", items=[
        {"en": "shark", "ru": "акула", "topic": "Fish", "picture": 1, "box": [167, 125, 667, 500]},
        {"en": "tuna", "ru": "тунец", "topic": "Fish", "picture": 1, "box": [167, 125, 667, 500]},
        {"en": "eel", "ru": "угорь", "topic": "Fish", "picture": 1, "box": [167, 125, 667, 500]},
        {"en": "fin", "ru": "плавник", "topic": "Fish", "picture": 1, "box": [0, 0, 30, 30]},  # too small
        {"en": "plaice", "ru": "камбала", "topic": "Fish", "picture": 5, "box": [0, 0, 500, 500]},  # no such page
    ]), pages)
    items = {item["en"]: item for item in get_draft(MOM, set_id)["tasks"][0]["items"]}

    assert items["shark"]["crop"] == {"photo": pages[0], "box": [167, 125, 667, 500]}
    with Image.open(set_photo_path(MOM, set_id, items["shark"]["image_id"])) as crop:
        # Trimmed inside the red block, so no white page (and no caption) is left.
        assert crop.size[0] < 300 and crop.getpixel((2, 2))[0] > 200 and crop.getpixel((2, 2))[1] < 60
    assert "image_id" not in items["fin"] and "image_id" not in items["plaice"]
    assert (items["tuna"]["current_image"], items["eel"]["current_image"]) == (False, True)
    assert get_draft(MOM, set_id)["photos"] == pages  # crops stay out of the gallery
    del known


def test_save_turns_crops_into_word_pictures_but_keeps_existing_ones(family: int) -> None:
    from englishbot.assets import PRIMARY_IMAGE_ROLE, get_learning_item_asset
    from englishbot.dictionary_editor import set_word_image

    topic = create_topic(MOM, "Fish")
    eel = create_word(MOM, topic["id"], "eel", {"ru": "угорь"})
    set_word_image(MOM, eel["id"], page_bytes())
    before = get_learning_item_asset(eel["id"], role=PRIMARY_IMAGE_ROLE)["asset_id"]
    tuna = create_word(MOM, topic["id"], "tuna", {"ru": "тунец"})
    set_word_image(MOM, tuna["id"], page_bytes())

    set_id = make_draft([])
    page = store_source_photos(set_id, [page_bytes()])[0]
    crop = crop_set_photo(MOM, set_id, page, [100, 100, 900, 900])["id"]
    upload = add_word_picture(MOM, set_id, png_bytes("green"))["id"]
    result = save_draft(MOM, set_id, {"tasks": [{"kind": "words", "items": [
        {"en": "shark", "ru": "акула", "topic": "Fish", "image_id": crop},
        {"en": "eel", "existing_id": eel["id"], "image_id": crop},  # model crop: the old picture stays
        {"en": "tuna", "existing_id": tuna["id"], "image_id": upload, "image_user": True},  # chosen by hand: replaced
    ]}]})
    assert result["pictured_words"] == 2
    words = {word["text"]: word["id"] for word in get_set(MOM, set_id)["words"]}
    assert get_learning_item_asset(words["shark"], role=PRIMARY_IMAGE_ROLE) is not None
    assert get_learning_item_asset(eel["id"], role=PRIMARY_IMAGE_ROLE)["asset_id"] == before
    assert get_learning_item_asset(tuna["id"], role=PRIMARY_IMAGE_ROLE)["asset_id"] != before


def test_manual_crop_checks_the_page_size_and_owner(family: int) -> None:
    other = make_draft([])
    foreign = store_source_photos(other, [page_bytes()])[0]
    set_id = make_draft([])
    page = store_source_photos(set_id, [page_bytes()])[0]
    assert error_code(lambda: crop_set_photo(MOM, set_id, foreign, [0, 0, 500, 500])) == "image_not_found"
    assert error_code(lambda: crop_set_photo(MOM, set_id, page, [0, 0, 50, 50])) == "crop_too_small"
    assert error_code(lambda: crop_set_photo(MOM, set_id, page, "x")) == "invalid_request"
    assert error_code(lambda: crop_set_photo(STRANGER, set_id, page, [0, 0, 500, 500])) == "set_not_found"
    assert error_code(lambda: save_draft(MOM, set_id, {"tasks": [{"kind": "words", "items": [
        {"en": "owl", "ru": "сова", "topic": "Birds", "image_id": foreign}]}]})) == "image_not_found"


def test_http_crop_and_word_picture(family: int, monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    set_id = make_draft([])
    page = store_source_photos(set_id, [page_bytes()])[0]
    body = json.dumps({"photo": page, "box": [100, 100, 600, 600]}).encode()
    status, result = request(f"/mini-app/api/editor/imports/{set_id}/crop", method="POST", body=body)
    assert status == 200 and result["id"]
    status, result = request(f"/mini-app/api/editor/imports/{set_id}/word-picture", method="POST", body=png_bytes())
    assert status == 200 and result["id"]


def test_forwarded_page_gives_the_draft_word_a_picture(family: int, monkeypatch) -> None:
    monkeypatch.setenv("ENGLISHBOT_MINI_APP_URL", "https://example.org/mini-app")

    class PageBot(FakeBot):
        async def download(self, file_id: str):
            return io.BytesIO(page_bytes())

    def fake_extract(kind, sources):
        return ExtractionResult(model="m", items=[{"en": "shark", "ru": "акула", "topic": "Fish", "picture": 1, "box": [167, 125, 667, 500]}])

    monkeypatch.setattr(homework_import_handlers, "extract_items", fake_extract)
    bot = PageBot()

    async def scenario():
        message = FakeMessage(bot, photo=[SimpleNamespace(file_id="page")])
        await homework_import_handlers.collect_homework_forward(message)
        data = message.answers[-1][1].inline_keyboard[0][0].callback_data
        await homework_import_handlers.handle_homework_import_callback(FakeCallback(data, message))
        await asyncio.gather(*homework_import_handlers._background_tasks)
        return int(data.rsplit(":", 1)[1])

    set_id = asyncio.run(scenario())
    item = get_draft(MOM, set_id)["tasks"][0]["items"][0]
    assert item["image_id"] and item["crop"]["photo"] == get_draft(MOM, set_id)["photos"][0]


# No leftovers on disk


def homework_files(tmp_root: Path) -> set[str]:
    folder = tmp_root / "assets" / "images" / "homework"
    return {path.name for path in folder.glob("*")} if folder.exists() else set()


def test_save_keeps_only_task_photos_and_cancel_deletes_everything(family: int) -> None:
    root = db.DB_PATH.parent.parent
    set_id = make_draft([])
    attached, loose = store_source_photos(set_id, [page_bytes(), page_bytes()])
    crop = crop_set_photo(MOM, set_id, attached, [100, 100, 900, 900])["id"]
    unused_crop = crop_set_photo(MOM, set_id, loose, [100, 100, 900, 900])["id"]
    assert len(homework_files(root)) == 4
    save_draft(MOM, set_id, {"tasks": [
        {"kind": "words", "items": [{"en": "shark", "ru": "акула", "topic": "Fish", "image_id": crop}]},
        {"kind": "paper", "title": "Crossword", "photos": [attached]},
    ]})
    assert len(homework_files(root)) == 1  # the attached page; the word picture was copied to the dictionary
    assert set_photo_path(MOM, set_id, attached).is_file()
    assert error_code(lambda: set_photo_path(MOM, set_id, unused_crop)) == "image_not_found"

    other = make_draft([])
    store_source_photos(other, [page_bytes()])
    assert len(homework_files(root)) == 2
    from englishbot.homework_sets import cancel_set
    cancel_set(MOM, other)
    assert len(homework_files(root)) == 1


def test_abandoned_drafts_are_cancelled_with_their_photos(family: int) -> None:
    from englishbot.homework_sets import cleanup_abandoned_sets

    root = db.DB_PATH.parent.parent
    old = make_draft([])
    store_source_photos(old, [page_bytes()])
    fresh = make_draft([])
    store_source_photos(fresh, [page_bytes()])
    with db.get_connection() as connection:
        connection.execute("UPDATE homework_sets SET updated_at = '2020-01-01T00:00:00+00:00' WHERE id = ?", (old,))
    assert cleanup_abandoned_sets() == 1
    assert len(homework_files(root)) == 1
    assert error_code(lambda: get_draft(MOM, old)) == "draft_not_available"
    assert get_draft(MOM, fresh)["photos"]


def test_replacing_a_word_picture_deletes_the_old_file(family: int) -> None:
    from englishbot.dictionary_editor import set_word_image

    root = db.DB_PATH.parent.parent
    topic = create_topic(MOM, "Fish")
    word = create_word(MOM, topic["id"], "eel", {"ru": "угорь"})
    folder = root / "assets" / "images" / "teacher-content"
    set_word_image(MOM, word["id"], page_bytes())
    set_word_image(MOM, word["id"], png_bytes("blue"))
    assert len(list(folder.glob("*"))) == 1
