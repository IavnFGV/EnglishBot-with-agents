import asyncio
import io
import json
import urllib.error
from pathlib import Path

import pytest
from aiogram.types import User

from englishbot import ai_extraction, ai_models, db, dictionary_editor
from englishbot.ai_extraction import AIExtractionUnavailable, ExtractionSource, extract_items
from englishbot.ai_models import (
    fetch_free_vision_models,
    get_model_queue,
    get_model_stats,
    record_model_result,
    set_model_queue,
    sync_model_queue,
)
from englishbot.daily_maintenance import sync_ai_models
from englishbot.families import add_family_member, create_family
from englishbot.mini_app import MiniAppError

OWNER = 501
WIFE = 502
FREE_A = "vendor/model-a:free"
FREE_B = "vendor/model-b:free"


@pytest.fixture
def setup(tmp_path: Path, monkeypatch) -> None:
    db.DB_PATH = tmp_path / "models.sqlite3"
    db.init_db()
    for user_id in (OWNER, WIFE):
        db.save_user(User(id=user_id, is_bot=False, first_name=str(user_id)))
    family = create_family("Home", OWNER)
    add_family_member(int(family["id"]), WIFE)
    monkeypatch.setenv("ENGLISHBOT_OWNER_TELEGRAM_USER_ID", str(OWNER))
    monkeypatch.setenv("ENGLISHBOT_OPENROUTER_API_KEY", "key")
    monkeypatch.setenv("ENGLISHBOT_AI_MODELS", f"{FREE_A},{FREE_B}")
    ai_models._catalog_cache.update(at=0.0, models=None)


def catalog(*entries) -> io.BytesIO:
    return io.BytesIO(json.dumps({"data": list(entries)}).encode())


def entry(model_id: str, inputs=("text", "image"), outputs=("text",)) -> dict:
    return {"id": model_id, "name": model_id.upper(), "architecture": {"input_modalities": list(inputs), "output_modalities": list(outputs)}}


def test_queue_defaults_to_env_and_saved_queue_wins(setup) -> None:
    assert get_model_queue() == [FREE_A, FREE_B]
    assert set_model_queue([FREE_B, FREE_B]) == [FREE_B]
    assert get_model_queue() == [FREE_B]
    with pytest.raises(ValueError):
        set_model_queue(["vendor/paid-model"])


def test_stats_accumulate_per_model(setup) -> None:
    record_model_result(FREE_A, ok=True, seconds=2.0)
    record_model_result(FREE_A, ok=True, seconds=4.0)
    record_model_result(FREE_A, ok=False, seconds=1.0, error="HTTP 429")
    stats = get_model_stats()[FREE_A]
    assert (stats["successes"], stats["failures"], stats["avg_seconds"], stats["last_error"]) == (2, 1, 3.0, "HTTP 429")


def test_catalog_keeps_only_free_models_that_read_images_and_answer_text(setup, monkeypatch) -> None:
    monkeypatch.setattr(ai_models.urllib.request, "urlopen", lambda *a, **k: catalog(
        entry(FREE_A),
        entry("vendor/paid"),
        entry("vendor/text-only:free", inputs=("text",)),
        entry("vendor/music:free", outputs=("audio",)),
    ))
    assert [model["id"] for model in fetch_free_vision_models()] == [FREE_A]


def test_extraction_moves_to_next_model_and_records_both(setup, monkeypatch) -> None:
    calls = []

    def fake_post(body, api_key):
        calls.append(body["model"])
        if body["model"] == FREE_A:
            raise urllib.error.HTTPError("url", 429, "busy", {}, None)
        return {"choices": [{"message": {"content": '{"words":[{"en":"owl","ru":"сова","topic":"Birds"}]}'}}]}

    monkeypatch.setattr(ai_extraction, "_post", fake_post)
    result = extract_items("words", [ExtractionSource(text="owl - сова")])

    assert calls == [FREE_A, FREE_B] and result.model == FREE_B
    stats = get_model_stats()
    assert (stats[FREE_A]["failures"], stats[FREE_B]["successes"]) == (1, 1)
    monkeypatch.setattr(ai_extraction, "_post", lambda body, key: (_ for _ in ()).throw(OSError("down")))
    with pytest.raises(AIExtractionUnavailable) as caught:
        extract_items("words", [ExtractionSource(text="owl")])
    assert FREE_A in str(caught.value) and FREE_B in str(caught.value)


def test_sync_drops_models_that_stopped_being_free_and_reports_new_ones(setup) -> None:
    first = sync_model_queue([FREE_A, FREE_B])
    assert first == {"removed": [], "new": [], "queue": [FREE_A, FREE_B]}  # the first run only remembers the catalog

    report = sync_model_queue([FREE_B, "vendor/model-c:free"])

    assert report == {"removed": [FREE_A], "new": ["vendor/model-c:free"], "queue": [FREE_B]}


class FakeBot:
    def __init__(self) -> None:
        self.sent = []

    async def send_message(self, **kwargs) -> None:
        self.sent.append(kwargs)


def test_daily_sync_notifies_owner_only_about_changes(setup, monkeypatch) -> None:
    available = [[{"id": FREE_A}, {"id": FREE_B}], [{"id": FREE_B}]]
    monkeypatch.setattr(ai_models, "fetch_free_vision_models", lambda: available.pop(0))
    bot = FakeBot()

    asyncio.run(sync_ai_models(bot))
    assert bot.sent == []
    asyncio.run(sync_ai_models(bot))

    assert bot.sent[0]["chat_id"] == OWNER
    assert FREE_A in bot.sent[0]["text"] and FREE_B in bot.sent[0]["text"]


def editor(user_id: int, method: str, path: list[str], payload=None):
    body = json.dumps(payload).encode() if payload is not None else b""
    return dictionary_editor.route_editor_request(method, path, user_id, body)


def test_models_api_is_owner_only_and_edits_queue(setup, monkeypatch) -> None:
    monkeypatch.setattr(ai_models, "get_free_vision_models_cached", lambda: [
        {"id": FREE_A, "name": "Model A"}, {"id": FREE_B, "name": "Model B"}, {"id": "vendor/model-c:free", "name": "Model C"},
    ])
    with pytest.raises(MiniAppError) as caught:
        editor(WIFE, "GET", ["models"])
    assert caught.value.status == 403
    assert editor(OWNER, "GET", ["topics"])["is_owner"] is True
    assert editor(WIFE, "GET", ["topics"])["is_owner"] is False

    state = editor(OWNER, "GET", ["models"])
    assert [model["id"] for model in state["queue"]] == [FREE_A, FREE_B]
    assert [model["id"] for model in state["available"]] == ["vendor/model-c:free"]

    state = editor(OWNER, "POST", ["models"], {"queue": ["vendor/model-c:free", FREE_A]})
    assert [model["id"] for model in state["queue"]] == ["vendor/model-c:free", FREE_A]
    with pytest.raises(MiniAppError):
        editor(OWNER, "POST", ["models"], {"queue": ["vendor/paid"]})


def test_model_check_scores_the_sample(setup, monkeypatch) -> None:
    reply = '{"words":[{"en":"Dragon","ru":"дракон","topic":"Fairy Tales"},{"en":"Castle","ru":"замок","topic":"Fairy Tales"},{"en":"Wizard","ru":"волшебник","topic":"Fairy Tales"}],"verbs":[{"base":"go","past":"went","participle":"gone","ru":"идти"}]}'
    monkeypatch.setattr(ai_extraction, "_post", lambda body, key: {"choices": [{"message": {"content": reply}}]})
    result = editor(OWNER, "POST", ["models", "test"], {"model": FREE_B})
    assert (result["ok"], result["found"], result["expected"]) == (True, 4, 6)
    monkeypatch.setattr(ai_extraction, "_post", lambda body, key: (_ for _ in ()).throw(OSError("down")))
    failed = editor(OWNER, "POST", ["models", "test"], {"model": FREE_B})
    assert failed["ok"] is False and "down" in failed["error"]
