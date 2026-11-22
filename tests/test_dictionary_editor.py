import asyncio
import json
from io import BytesIO
from pathlib import Path

import pytest
from aiogram.types import User
from PIL import Image

from englishbot import db
from englishbot.dictionary_editor import (
    clear_word_image,
    create_topic,
    create_word,
    delete_topic,
    delete_word,
    list_topics,
    list_words,
    normalize_image,
    rename_topic,
    set_word_image,
    update_word,
    word_image_path,
)
from englishbot.families import add_family_member, create_family
from englishbot.mini_app import MiniAppError, sign_test_init_data
from englishbot.status_server import _mini_app_response
from englishbot.teacher_content_handlers import build_editor_keyboard, build_editor_url
from englishbot.topics import get_topic_learning_item_ids


TOKEN = "123456:test-token"
PARENT = 801
CHILD = 802
STRANGER = 803


@pytest.fixture
def family(tmp_path: Path) -> int:
    db.DB_PATH = tmp_path / "data" / "editor.sqlite3"
    db.DB_PATH.parent.mkdir()
    db.init_db()
    for user_id in (PARENT, CHILD, STRANGER):
        db.save_user(User(id=user_id, is_bot=False, first_name=f"user-{user_id}"))
    family_row = create_family("Home", PARENT)
    add_family_member(int(family_row["id"]), CHILD)
    create_family("Other", STRANGER)
    return int(family_row["id"])


def png_bytes(size=(2000, 1000), mode="RGBA") -> bytes:
    output = BytesIO()
    Image.new(mode, size, (255, 0, 0, 0) if mode == "RGBA" else (255, 0, 0)).save(output, format="PNG")
    return output.getvalue()


def error_code(call) -> str:
    with pytest.raises(MiniAppError) as caught:
        call()
    return caught.value.code


def test_topic_and_word_lifecycle(family: int) -> None:
    topic = create_topic(PARENT, "  Animals ")
    assert topic["title"] == "Animals"
    word = create_word(PARENT, topic["id"], " cat ", {"ru": "кошка", "uk": ""})
    assert word["text"] == "cat"
    assert word["translations"] == {"ru": "кошка", "uk": "", "bg": ""}

    updated = update_word(CHILD, word["id"], "big cat", {"ru": "", "uk": "кіт"})
    assert updated["text"] == "big cat"
    assert updated["translations"] == {"ru": "", "uk": "кіт", "bg": ""}

    assert rename_topic(PARENT, topic["id"], "Pets")["title"] == "Pets"
    topics = list_topics(PARENT)
    assert [(row["title"], row["word_count"]) for row in topics["topics"]] == [("Pets", 1)]
    assert topics["labels"]["save"]

    delete_word(PARENT, word["id"])
    assert list_words(PARENT, topic["id"])["words"] == []
    assert error_code(lambda: update_word(PARENT, word["id"], "x")) == "word_not_found"


def test_other_family_cannot_read_or_change_content(family: int) -> None:
    topic = create_topic(PARENT, "Animals")
    word = create_word(PARENT, topic["id"], "cat")
    assert list_topics(STRANGER)["topics"] == []
    assert error_code(lambda: list_words(STRANGER, topic["id"])) == "topic_not_found"
    assert error_code(lambda: update_word(STRANGER, word["id"], "dog")) == "word_not_found"
    assert error_code(lambda: create_word(STRANGER, topic["id"], "dog")) == "topic_not_found"
    assert error_code(lambda: list_topics(999)) == "access_denied"


def test_validation_rejects_empty_and_long_text(family: int) -> None:
    topic = create_topic(PARENT, "Animals")
    assert error_code(lambda: create_word(PARENT, topic["id"], "   ")) == "text_required"
    assert error_code(lambda: create_word(PARENT, topic["id"], "x" * 201)) == "text_too_long"
    assert error_code(lambda: create_topic(PARENT, "")) == "text_required"


def test_deleting_topic_keeps_words_shared_with_another_topic(family: int) -> None:
    from englishbot.families import replace_topic_items

    animals = create_topic(PARENT, "Animals")
    pets = create_topic(PARENT, "Pets")
    cat = create_word(PARENT, animals["id"], "cat")
    lion = create_word(PARENT, animals["id"], "lion")
    replace_topic_items(pets["id"], [cat["id"]])

    delete_topic(PARENT, animals["id"])

    assert [row["title"] for row in list_topics(PARENT)["topics"]] == ["Pets"]
    assert get_topic_learning_item_ids(pets["id"]) == [cat["id"]]
    assert error_code(lambda: update_word(PARENT, lion["id"], "tiger")) == "word_not_found"


def test_normalize_image_produces_bounded_jpeg_from_transparent_png() -> None:
    result = normalize_image(png_bytes())
    with Image.open(BytesIO(result)) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"
        assert max(image.size) == 1024
        assert image.getpixel((10, 10)) == (255, 255, 255)
    assert error_code(lambda: normalize_image(b"not an image")) == "invalid_image"
    assert error_code(lambda: normalize_image(b"")) == "invalid_image"


def test_word_image_upload_replace_and_clear(family: int) -> None:
    topic = create_topic(PARENT, "Animals")
    word = create_word(PARENT, topic["id"], "cat")

    first = set_word_image(PARENT, word["id"], png_bytes(mode="RGB"))
    first_path = word_image_path(PARENT, word["id"])
    assert first["image_id"] and first_path.suffix == ".jpg" and first_path.is_file()

    second = set_word_image(PARENT, word["id"], png_bytes((300, 300), "RGB"))
    assert second["image_id"] != first["image_id"]
    assert error_code(lambda: word_image_path(STRANGER, word["id"])) == "word_not_found"

    assert clear_word_image(PARENT, word["id"])["image_id"] is None
    assert error_code(lambda: word_image_path(PARENT, word["id"])) == "image_not_found"


def request(path: str, *, user_id: int | None = PARENT, method: str = "GET", body: bytes = b"", length: int | None = None) -> tuple[int, bytes]:
    async def run() -> bytes:
        reader = asyncio.StreamReader()
        reader.feed_data(body)
        reader.feed_eof()
        headers = {"content-length": str(len(body) if length is None else length)}
        if user_id is not None:
            headers["x-telegram-init-data"] = sign_test_init_data(user_id, TOKEN)
        return await _mini_app_response(method, path, headers, reader, object())

    try:
        response = asyncio.run(run())
    except MiniAppError as exc:
        return exc.status, exc.code.encode()
    head, payload = response.split(b"\r\n\r\n", 1)
    return int(head.split(b" ")[1]), payload


def test_http_editor_flow_with_image_upload(family: int, monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    status, payload = request("/mini-app/api/editor/topics", method="POST", body=json.dumps({"title": "Food"}).encode())
    assert status == 200
    topic_id = json.loads(payload)["id"]

    status, payload = request(
        f"/mini-app/api/editor/topics/{topic_id}/words",
        method="POST",
        body=json.dumps({"text": "apple", "translations": {"ru": "яблоко"}}).encode(),
    )
    word = json.loads(payload)
    assert status == 200 and word["translations"]["ru"] == "яблоко"

    status, payload = request(f"/mini-app/api/editor/words/{word['id']}/image", method="POST", body=png_bytes((400, 200), "RGB"))
    assert status == 200 and json.loads(payload)["image_id"]

    status, payload = request(f"/mini-app/api/editor/words/{word['id']}/image")
    assert status == 200 and payload[:3] == b"\xff\xd8\xff"

    status, payload = request(f"/mini-app/api/editor/topics/{topic_id}/words")
    assert [row["text"] for row in json.loads(payload)["words"]] == ["apple"]


def test_http_editor_requires_valid_init_data_and_bounded_body(family: int, monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    assert request("/mini-app/api/editor/topics", user_id=None)[0] == 401
    assert request("/mini-app/api/editor/topics", method="POST", body=b"{}", length=10**6) == (413, b"request_too_large")
    assert request("/mini-app/api/editor/unknown")[0] == 404
    assert request("/mini-app/api/editor/topics", method="POST", body=b"[1]") == (400, b"invalid_request")


def test_editor_page_and_assets_are_served(family: int) -> None:
    status, payload = request("/mini-app/editor", user_id=None)
    assert status == 200 and b"/mini-app/editor.js?v=" in payload
    assert request("/mini-app/editor.js", user_id=None)[0] == 200
    assert request("/mini-app/editor.css", user_id=None)[0] == 200


def test_editor_keyboard_opens_web_app(family: int) -> None:
    assert build_editor_url("https://example.org/mini-app/") == "https://example.org/mini-app/editor"
    keyboard = build_editor_keyboard(PARENT, "https://example.org/mini-app")
    assert keyboard.inline_keyboard[0][0].web_app.url == "https://example.org/mini-app/editor"
    assert keyboard.inline_keyboard[1][0].callback_data == "editor:telegram"
