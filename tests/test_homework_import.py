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
    add_source,
    begin_processing,
    get_draft,
    save_draft,
    store_extraction,
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

    assert [(item["en"], bool(item["existing_id"]), item["topic"]) for item in draft["items"]] == [
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


def test_forward_filter_requires_forward_family_and_configured_ai(family: int, monkeypatch) -> None:
    bot = FakeBot()
    assert homework_import_handlers.is_homework_forward(FakeMessage(bot, text="cat"))
    assert not homework_import_handlers.is_homework_forward(FakeMessage(bot, text="cat", forwarded=False))
    stranger = FakeMessage(bot, text="cat")
    stranger.from_user = SimpleNamespace(id=999)
    assert not homework_import_handlers.is_homework_forward(stranger)
    monkeypatch.delenv("ENGLISHBOT_OPENROUTER_API_KEY")
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
    assert status == 200 and draft["items"][0]["en"] == "owl" and draft["labels"]["save_draft"]

    payload = {"title": "ДЗ", "mode": "easy", "assign_to": KID, "items": draft["items"]}
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
