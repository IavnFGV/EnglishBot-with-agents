import asyncio
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.assets import (
    PRIMARY_IMAGE_ROLE,
    TELEGRAM_MEDIA_KIND_AUDIO,
    TELEGRAM_MEDIA_KIND_PHOTO,
    TELEGRAM_MEDIA_KIND_VOICE,
    cache_telegram_file_id,
    create_asset,
    get_cached_telegram_file_id,
    link_asset_to_learning_item,
)
from englishbot.families import (
    add_family_member,
    create_family,
    create_family_learning_item,
    create_homework_assignment as create_family_homework_assignment,
)
from englishbot.homework import start_assignment_training_session
from englishbot.training import get_active_training_session, get_current_question, submit_training_answer
from englishbot.training_handlers import (
    TRAINING_EASY_CALLBACK_PREFIX,
    TRAINING_HARD_SKIP_CALLBACK,
    TRAINING_MEDIUM_ADD_CALLBACK_PREFIX,
    TRAINING_MEDIUM_BACKSPACE_CALLBACK,
    TRAINING_MEDIUM_CHECK_CALLBACK,
    answer_training_easy,
    answer_training_hard_skip,
    answer_training_medium_add,
    answer_training_medium_backspace,
    answer_training_medium_check,
    answer_training_question,
    learn,
    render_started_training_session,
)
from englishbot.user_profiles import set_user_hint_language
from englishbot.vocabulary import create_learning_item_translation, create_lexeme


class FakeBot:
    def __init__(self) -> None:
        self.edited_messages: list[dict[str, object]] = []
        self.edited_media: list[dict[str, object]] = []
        self.deleted_messages: list[dict[str, object]] = []
        self.fail_delete = False
        self.fail_edit_media_message: str | None = None
        self.fail_edit_media_file_ids: set[str] = set()

    async def edit_message_text(
        self,
        *,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup=None,
    ) -> None:
        self.edited_messages.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "reply_markup": reply_markup,
            }
        )

    async def edit_message_media(
        self,
        *,
        chat_id: int,
        message_id: int,
        media,
        reply_markup=None,
    ) -> None:
        if self.fail_edit_media_message is not None:
            raise RuntimeError(self.fail_edit_media_message)
        media_value = getattr(media, "media", None)
        if isinstance(media_value, str) and media_value in self.fail_edit_media_file_ids:
            raise RuntimeError("Bad Request: wrong file identifier/HTTP URL specified")
        self.edited_media.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "media": media,
                "reply_markup": reply_markup,
            }
        )

    async def delete_message(self, *, chat_id: int, message_id: int) -> None:
        self.deleted_messages.append({"chat_id": chat_id, "message_id": message_id})
        if self.fail_delete:
            raise RuntimeError("delete failed")


class FakeMessage:
    def __init__(self, user: User, text: str | None = None, bot: FakeBot | None = None) -> None:
        self.from_user = user
        self.text = text
        self.bot = bot or FakeBot()
        self.chat = SimpleNamespace(id=user.id)
        self.answers: list[dict[str, object]] = []
        self.photo_answers: list[dict[str, object]] = []
        self.photo_attempts: list[object] = []
        self.fail_photo_file_ids: set[str] = set()
        self._next_message_id = 1
        self.message_id = 0

    async def answer(self, text: str, **kwargs: object) -> SimpleNamespace:
        message = SimpleNamespace(message_id=self._next_message_id)
        self._next_message_id += 1
        self.answers.append({"text": text, "kwargs": kwargs, "message_id": message.message_id})
        return message

    async def answer_photo(self, photo, **kwargs: object) -> SimpleNamespace:
        self.photo_attempts.append(photo)
        if isinstance(photo, str) and photo in self.fail_photo_file_ids:
            raise RuntimeError("Bad Request: wrong file identifier/HTTP URL specified")
        message = SimpleNamespace(message_id=self._next_message_id)
        self._next_message_id += 1
        if isinstance(photo, str):
            file_id = photo
        else:
            file_id = f"uploaded-photo-{message.message_id}"
        message.photo = [SimpleNamespace(file_id=file_id)]
        self.photo_answers.append({"photo": photo, "kwargs": kwargs, "message_id": message.message_id})
        return message


class FakeTuplePhotoMessage(FakeMessage):
    async def answer_photo(self, photo, **kwargs: object) -> SimpleNamespace:
        self.photo_attempts.append(photo)
        if isinstance(photo, str) and photo in self.fail_photo_file_ids:
            raise RuntimeError("Bad Request: wrong file identifier/HTTP URL specified")
        message = SimpleNamespace(message_id=self._next_message_id)
        self._next_message_id += 1
        if isinstance(photo, str):
            file_id = photo
        else:
            file_id = f"uploaded-photo-{message.message_id}"
        message.photo = (SimpleNamespace(file_id=file_id),)
        self.photo_answers.append({"photo": photo, "kwargs": kwargs, "message_id": message.message_id})
        return message


class FakeCallback:
    def __init__(self, user: User, data: str, message: FakeMessage) -> None:
        self.from_user = user
        self.data = data
        self.message = message
        self.answered = False

    async def answer(self) -> None:
        self.answered = True


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "training_handlers.sqlite3"
    db.init_db()


def seed_learning_items(item_count: int, *, user: User | None = None) -> User:
    teacher = user or make_user(499, "Teacher")
    db.save_user(teacher)
    family = create_family("Home", teacher.id)
    for index in range(item_count):
        lexeme_id = create_lexeme(f"word-{index + 1}")
        learning_item_id = create_family_learning_item(
            int(family["id"]),
            lexeme_id,
            f"text-{index + 1}",
        )
        create_learning_item_translation(learning_item_id, "ru", f"слово-{index + 1}")
    return teacher


def attach_primary_image(learning_item_id: int, image_path: Path) -> None:
    asset_id = create_asset("image", local_path=str(image_path))
    link_asset_to_learning_item(learning_item_id, asset_id, PRIMARY_IMAGE_ROLE)


def seed_family_parent_and_child() -> tuple[User, User, int]:
    parent = make_user(498, "Parent")
    child = make_user(497, "Child")
    db.save_user(parent)
    db.save_user(child)
    family = create_family("Home", parent.id)
    add_family_member(int(family["id"]), child.id)
    return parent, child, int(family["id"])


def _find_keyboard_index_by_label(keyboard, label: str) -> int:
    for index, row in enumerate(keyboard.inline_keyboard):
        if row[0].text == label:
            return index
    raise AssertionError(f"Option {label!r} not found")


def test_learn_renders_one_progress_message_and_one_easy_question(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(401, "Learner")
    seed_learning_items(3, user=user)
    message = FakeMessage(user)

    asyncio.run(learn(message))

    assert [answer["text"] for answer in message.answers] == [
        "Item 1/3\nDone 0/3\nStage: easy",
        "слово-1",
    ]
    keyboard = message.answers[1]["kwargs"]["reply_markup"]
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 3
    assert sum(len(row) for row in keyboard.inline_keyboard) == 3
    session = get_active_training_session(user.id)
    assert session is not None
    assert session["progress_message_id"] == 1
    assert session["current_question_message_id"] == 2


def test_learn_renders_question_photo_when_learning_item_has_image(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(411, "Learner")
    seed_learning_items(3, user=user)
    image_path = tmp_path / "card-1.png"
    image_path.write_bytes(b"fake image")
    attach_primary_image(1, image_path)
    message = FakeMessage(user)

    asyncio.run(learn(message))

    assert [answer["text"] for answer in message.answers] == ["Item 1/3\nDone 0/3\nStage: easy"]
    assert len(message.photo_answers) == 1
    assert message.photo_answers[0]["kwargs"]["caption"] == "слово-1"
    keyboard = message.photo_answers[0]["kwargs"]["reply_markup"]
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 3
    assert get_cached_telegram_file_id(1, TELEGRAM_MEDIA_KIND_PHOTO) == "uploaded-photo-2"


def test_learn_caches_question_photo_file_id_from_tuple_shaped_telegram_photo(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    user = make_user(422, "Learner")
    seed_learning_items(1, user=user)
    image_path = tmp_path / "card-1.png"
    image_path.write_bytes(b"fake image")
    attach_primary_image(1, image_path)
    message = FakeTuplePhotoMessage(user)

    asyncio.run(learn(message))

    assert get_cached_telegram_file_id(1, TELEGRAM_MEDIA_KIND_PHOTO) == "uploaded-photo-2"


def test_second_question_send_prefers_cached_telegram_photo_file_id(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(418, "Learner")
    seed_learning_items(1, user=user)
    image_path = tmp_path / "card-1.png"
    image_path.write_bytes(b"fake image")
    attach_primary_image(1, image_path)

    first_message = FakeMessage(user)
    asyncio.run(learn(first_message))
    cached_file_id = get_cached_telegram_file_id(1, TELEGRAM_MEDIA_KIND_PHOTO)
    assert cached_file_id == "uploaded-photo-2"

    second_message = FakeMessage(user)
    asyncio.run(learn(second_message))

    assert len(second_message.photo_answers) == 1
    assert second_message.photo_attempts[0] == "uploaded-photo-2"
    assert second_message.photo_answers[0]["photo"] == "uploaded-photo-2"


def test_invalid_cached_question_photo_file_id_retries_local_upload_and_refreshes_cache(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    user = make_user(419, "Learner")
    seed_learning_items(1, user=user)
    image_path = tmp_path / "card-1.png"
    image_path.write_bytes(b"fake image")
    attach_primary_image(1, image_path)
    cache_telegram_file_id(1, TELEGRAM_MEDIA_KIND_PHOTO, "stale-photo-file-id")

    message = FakeMessage(user)
    message.fail_photo_file_ids.add("stale-photo-file-id")
    asyncio.run(learn(message))

    assert message.photo_attempts[0] == "stale-photo-file-id"
    assert len(message.photo_answers) == 1
    assert message.photo_answers[0]["photo"].__class__.__name__ == "FSInputFile"
    assert get_cached_telegram_file_id(1, TELEGRAM_MEDIA_KIND_PHOTO) == "uploaded-photo-2"


def test_invalid_cached_photo_file_id_during_edit_replaces_message_and_refreshes_cache(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    user = make_user(420, "Learner")
    seed_learning_items(1, user=user)
    image_path = tmp_path / "card-1.png"
    image_path.write_bytes(b"fake image")
    attach_primary_image(1, image_path)
    first_message = FakeMessage(user)
    asyncio.run(learn(first_message))

    submit_training_answer(user.id, "word-1")
    submit_training_answer(user.id, "word-1")
    asyncio.run(render_started_training_session(first_message, user.id))
    cache_telegram_file_id(1, TELEGRAM_MEDIA_KIND_PHOTO, "stale-photo-file-id")

    session = get_active_training_session(user.id)
    assert session is not None
    first_message.message_id = int(session["current_question_message_id"])
    first_message.bot.fail_edit_media_file_ids.add("stale-photo-file-id")

    asyncio.run(
        answer_training_medium_add(
            FakeCallback(user, f"{TRAINING_MEDIUM_ADD_CALLBACK_PREFIX}0", first_message)
        )
    )

    assert first_message.bot.deleted_messages[-1] == {"chat_id": user.id, "message_id": 4}
    assert first_message.photo_answers[-1]["message_id"] == 5
    assert get_cached_telegram_file_id(1, TELEGRAM_MEDIA_KIND_PHOTO) == "uploaded-photo-5"


def test_invalid_question_image_falls_back_to_text_only_card(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(412, "Learner")
    seed_learning_items(3, user=user)
    attach_primary_image(1, tmp_path / "missing.png")
    message = FakeMessage(user)

    asyncio.run(learn(message))

    assert len(message.photo_answers) == 0
    assert message.answers[-1]["text"] == "слово-1"


def test_telegram_photo_cache_table_stays_separate_from_assets_and_supports_future_media_kinds(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    user = make_user(421, "Teacher")
    seed_learning_items(1, user=user)
    image_path = tmp_path / "card-1.png"
    image_path.write_bytes(b"fake image")
    attach_primary_image(1, image_path)
    cache_telegram_file_id(1, TELEGRAM_MEDIA_KIND_PHOTO, "photo-file-id")
    cache_telegram_file_id(1, TELEGRAM_MEDIA_KIND_AUDIO, "audio-file-id")
    cache_telegram_file_id(1, TELEGRAM_MEDIA_KIND_VOICE, "voice-file-id")

    with sqlite3.connect(db.DB_PATH) as connection:
        asset_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(assets)").fetchall()
        }
        cache_rows = connection.execute(
            """
            SELECT telegram_media_kind, telegram_file_id
            FROM telegram_asset_file_cache
            WHERE asset_id = 1
            ORDER BY telegram_media_kind
            """
        ).fetchall()

    assert "telegram_file_id" not in asset_columns
    assert "file_id" not in asset_columns
    assert [(row[0], row[1]) for row in cache_rows] == [
        ("audio", "audio-file-id"),
        ("photo", "photo-file-id"),
        ("voice", "voice-file-id"),
    ]


def test_easy_callback_delegates_selected_option_to_training_logic(tmp_path: Path, monkeypatch) -> None:
    setup_db(tmp_path)
    user = make_user(402, "Learner")
    message = FakeMessage(user)
    callback = FakeCallback(user, f"{TRAINING_EASY_CALLBACK_PREFIX}1", message)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "englishbot.training_handlers.get_current_question",
        lambda user_id: {
            "session_id": 7,
            "prompt": "слово",
            "options": ["alpha", "beta", "gamma"],
        },
    )
    monkeypatch.setattr(
        "englishbot.training_handlers.get_active_training_session",
        lambda user_id: {
            "id": 7,
            "progress_message_id": None,
            "current_question_message_id": None,
        },
    )

    def fake_submit_training_answer(user_id: int, answer_text: str) -> dict[str, object]:
        captured["user_id"] = user_id
        captured["answer_text"] = answer_text
        return {
            "is_correct": True,
            "expected_answer": "beta",
            "status": "completed",
            "summary": {"total_questions": 1, "correct_answers": 1},
            "total_questions": 1,
        }

    monkeypatch.setattr(
        "englishbot.training_handlers.submit_training_answer",
        fake_submit_training_answer,
    )
    monkeypatch.setattr(
        "englishbot.training_handlers.set_training_session_progress_message_id",
        lambda session_id, message_id: None,
    )
    monkeypatch.setattr(
        "englishbot.training_handlers.set_training_session_current_question_message_id",
        lambda session_id, message_id: None,
    )

    asyncio.run(answer_training_easy(callback))

    assert callback.answered is True
    assert captured == {"user_id": user.id, "answer_text": "beta"}


def test_easy_callback_reuses_progress_message_and_replaces_question_message(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(403, "Learner")
    seed_learning_items(3, user=user)
    message = FakeMessage(user)

    asyncio.run(learn(message))

    keyboard = message.answers[1]["kwargs"]["reply_markup"]
    correct_index = _find_keyboard_index_by_label(keyboard, "word-1")
    callback = FakeCallback(user, f"{TRAINING_EASY_CALLBACK_PREFIX}{correct_index}", message)

    asyncio.run(answer_training_easy(callback))

    session = get_active_training_session(user.id)
    assert session is not None
    assert session["progress_message_id"] == 1
    assert session["current_question_message_id"] == 2
    assert message.bot.edited_messages[0] == {
        "chat_id": user.id,
        "message_id": 1,
        "text": "Item 2/3\nDone 0/3\nStage: easy",
        "reply_markup": None,
    }
    assert message.bot.edited_messages[1]["message_id"] == 2
    assert message.bot.edited_messages[1]["text"] == "Correct.\nслово-2"
    assert message.bot.deleted_messages == []
    assert len(message.bot.edited_messages) == 2


def test_easy_callback_image_to_image_updates_question_photo_in_place(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(413, "Learner")
    seed_learning_items(3, user=user)
    for index in range(2):
        image_path = tmp_path / f"card-{index}.png"
        image_path.write_bytes(b"fake image")
        attach_primary_image(index + 1, image_path)
    message = FakeMessage(user)

    asyncio.run(learn(message))

    keyboard = message.photo_answers[0]["kwargs"]["reply_markup"]
    correct_index = _find_keyboard_index_by_label(keyboard, "word-1")
    callback = FakeCallback(user, f"{TRAINING_EASY_CALLBACK_PREFIX}{correct_index}", message)

    asyncio.run(answer_training_easy(callback))

    session = get_active_training_session(user.id)
    assert session is not None
    assert session["current_question_message_id"] == 2
    assert len(message.photo_answers) == 1
    assert message.bot.deleted_messages == []
    assert message.bot.edited_media[-1]["message_id"] == 2
    assert message.bot.edited_media[-1]["media"].caption == "Correct.\nслово-2"


def test_easy_callback_no_image_to_image_replaces_text_question_with_photo(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(414, "Learner")
    seed_learning_items(3, user=user)
    image_path = tmp_path / "card-2.png"
    image_path.write_bytes(b"fake image")
    attach_primary_image(2, image_path)
    message = FakeMessage(user)

    asyncio.run(learn(message))

    keyboard = message.answers[1]["kwargs"]["reply_markup"]
    correct_index = _find_keyboard_index_by_label(keyboard, "word-1")
    callback = FakeCallback(user, f"{TRAINING_EASY_CALLBACK_PREFIX}{correct_index}", message)

    asyncio.run(answer_training_easy(callback))

    session = get_active_training_session(user.id)
    assert session is not None
    assert session["current_question_message_id"] == 3
    assert message.bot.deleted_messages == [{"chat_id": user.id, "message_id": 2}]
    assert len(message.photo_answers) == 1
    assert message.photo_answers[-1]["message_id"] == 3
    assert message.photo_answers[-1]["kwargs"]["caption"] == "Correct.\nслово-2"


def test_easy_callback_image_to_no_image_replaces_photo_question_with_text(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(415, "Learner")
    seed_learning_items(3, user=user)
    image_path = tmp_path / "card-1.png"
    image_path.write_bytes(b"fake image")
    attach_primary_image(1, image_path)
    message = FakeMessage(user)

    asyncio.run(learn(message))

    keyboard = message.photo_answers[0]["kwargs"]["reply_markup"]
    correct_index = _find_keyboard_index_by_label(keyboard, "word-1")
    callback = FakeCallback(user, f"{TRAINING_EASY_CALLBACK_PREFIX}{correct_index}", message)

    asyncio.run(answer_training_easy(callback))

    session = get_active_training_session(user.id)
    assert session is not None
    assert session["current_question_message_id"] == 3
    assert message.bot.deleted_messages == [{"chat_id": user.id, "message_id": 2}]
    assert message.answers[-1]["message_id"] == 3
    assert message.answers[-1]["text"] == "Correct.\nслово-2"


def test_question_deletion_failures_are_tolerated_safely(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(404, "Learner")
    seed_learning_items(3, user=user)
    message = FakeMessage(user)

    asyncio.run(learn(message))
    message.bot.fail_delete = True

    keyboard = message.answers[1]["kwargs"]["reply_markup"]
    correct_index = _find_keyboard_index_by_label(keyboard, "word-1")
    callback = FakeCallback(user, f"{TRAINING_EASY_CALLBACK_PREFIX}{correct_index}", message)

    asyncio.run(answer_training_easy(callback))

    session = get_active_training_session(user.id)
    assert session is not None
    assert session["current_question_message_id"] == 2
    assert message.answers[-1]["message_id"] == 2


def test_text_answers_are_ignored_for_medium_stage(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(405, "Learner")
    seed_learning_items(1, user=user)
    message = FakeMessage(user)

    asyncio.run(learn(message))
    submit_training_answer(user.id, "word-1")
    submit_training_answer(user.id, "word-1")

    medium_answer = FakeMessage(user, text="word-1", bot=message.bot)
    medium_answer._next_message_id = message._next_message_id
    asyncio.run(answer_training_question(medium_answer))

    assert medium_answer.answers == []


def test_medium_callbacks_assemble_and_remove_letters(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(409, "Learner")
    seed_learning_items(1, user=user)
    message = FakeMessage(user)

    asyncio.run(learn(message))
    submit_training_answer(user.id, "word-1")
    submit_training_answer(user.id, "word-1")
    asyncio.run(render_started_training_session(message, user.id))

    session = get_active_training_session(user.id)
    assert session is not None
    message.message_id = int(session["current_question_message_id"])
    question = get_current_question(user.id)
    assert question is not None
    jumbled_letters = str(question["jumbled_letters"])
    first_letter_index = 0
    callback = FakeCallback(user, f"{TRAINING_MEDIUM_ADD_CALLBACK_PREFIX}{first_letter_index}", message)

    asyncio.run(answer_training_medium_add(callback))

    assert callback.answered is True
    assert "Answer: " in message.bot.edited_messages[-1]["text"]
    
    # Check keyboard layout stability: selected letter becomes placeholder
    edited = message.bot.edited_messages[-1]
    reply_markup = edited["reply_markup"]
    assert reply_markup is not None
    keyboard = reply_markup.inline_keyboard
    letter_buttons = []
    for row in keyboard[:-1]:  # exclude backspace/check row
        for btn in row:
            if (btn.callback_data and btn.callback_data.startswith(TRAINING_MEDIUM_ADD_CALLBACK_PREFIX)) or btn.text == "·":
                letter_buttons.append(btn)
    assert len(letter_buttons) == len(jumbled_letters)
    # First letter should be placeholder
    assert letter_buttons[0].text == "·"
    assert letter_buttons[0].callback_data == "placeholder"
    
    asyncio.run(answer_training_medium_backspace(FakeCallback(user, TRAINING_MEDIUM_BACKSPACE_CALLBACK, message)))
    assert "_ _ _ _ _ _" in message.bot.edited_messages[-1]["text"]
    
    # Check keyboard after backspace: letter restored
    edited2 = message.bot.edited_messages[-1]
    reply_markup2 = edited2["reply_markup"]
    assert reply_markup2 is not None
    keyboard2 = reply_markup2.inline_keyboard
    letter_buttons2 = []
    for row in keyboard2[:-1]:
        for btn in row:
            if (btn.callback_data and btn.callback_data.startswith(TRAINING_MEDIUM_ADD_CALLBACK_PREFIX)) or btn.text == "·":
                letter_buttons2.append(btn)
    assert len(letter_buttons2) == len(jumbled_letters)
    # First letter should be restored
    assert letter_buttons2[0].text == jumbled_letters[0]
    assert letter_buttons2[0].callback_data == f"{TRAINING_MEDIUM_ADD_CALLBACK_PREFIX}0"


def test_medium_question_with_image_updates_photo_caption_and_keyboard(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(416, "Learner")
    seed_learning_items(1, user=user)
    image_path = tmp_path / "medium-card.png"
    image_path.write_bytes(b"fake image")
    attach_primary_image(1, image_path)
    message = FakeMessage(user)

    asyncio.run(learn(message))
    submit_training_answer(user.id, "word-1")
    submit_training_answer(user.id, "word-1")
    asyncio.run(render_started_training_session(message, user.id))

    session = get_active_training_session(user.id)
    assert session is not None
    message.message_id = int(session["current_question_message_id"])
    question = get_current_question(user.id)
    assert question is not None

    asyncio.run(
        answer_training_medium_add(
            FakeCallback(user, f"{TRAINING_MEDIUM_ADD_CALLBACK_PREFIX}0", message)
        )
    )

    assert message.bot.edited_media[-1]["message_id"] == int(session["current_question_message_id"])
    assert "Answer: " in message.bot.edited_media[-1]["media"].caption
    assert message.bot.edited_media[-1]["reply_markup"] is not None


def test_medium_check_uses_assembled_answer_and_advances(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(410, "Learner")
    seed_learning_items(1, user=user)
    message = FakeMessage(user)

    asyncio.run(learn(message))
    submit_training_answer(user.id, "word-1")
    submit_training_answer(user.id, "word-1")
    asyncio.run(render_started_training_session(message, user.id))
    session = get_active_training_session(user.id)
    assert session is not None
    message.message_id = int(session["current_question_message_id"])
    question = get_current_question(user.id)
    assert question is not None
    remaining_indexes = list(enumerate(str(question["jumbled_letters"])))
    for character in str(question["expected_answer"]):
        for position, candidate in remaining_indexes:
            if candidate == character:
                asyncio.run(
                    answer_training_medium_add(
                        FakeCallback(user, f"{TRAINING_MEDIUM_ADD_CALLBACK_PREFIX}{position}", message)
                    )
                )
                remaining_indexes.remove((position, candidate))
                break

    asyncio.run(answer_training_medium_check(FakeCallback(user, TRAINING_MEDIUM_CHECK_CALLBACK, message)))

    updated_question = get_current_question(user.id)
    assert updated_question is not None
    assert updated_question["current_stage"] == "medium"
    assert updated_question["medium_correct_count"] == 1


def test_text_answers_render_hint_and_first_letter_for_hard_stage(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(406, "Learner")
    seed_learning_items(1, user=user)
    start_message = FakeMessage(user)

    asyncio.run(learn(start_message))

    assert "Hint: слово-1" in start_message.answers[-1]["text"]
    assert "First letter: w" in start_message.answers[-1]["text"]


def test_hard_stage_with_image_keeps_photo_question_card_and_skip_keyboard(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(417, "Learner")
    seed_learning_items(1, user=user)
    image_path = tmp_path / "hard-card.png"
    image_path.write_bytes(b"fake image")
    attach_primary_image(1, image_path)
    start_message = FakeMessage(user)

    asyncio.run(learn(start_message))
    submit_training_answer(user.id, "word-1")
    submit_training_answer(user.id, "word-1")
    submit_training_answer(user.id, "word-1")
    submit_training_answer(user.id, "word-1")
    asyncio.run(render_started_training_session(start_message, user.id))

    assert len(start_message.photo_answers) >= 2
    hard_card = start_message.photo_answers[-1]
    assert "Hint: слово-1" in hard_card["kwargs"]["caption"]
    assert "First letter: w" in hard_card["kwargs"]["caption"]
    keyboard = hard_card["kwargs"]["reply_markup"]
    assert keyboard is not None
    assert keyboard.inline_keyboard[0][0].callback_data == TRAINING_HARD_SKIP_CALLBACK


def test_session_completion_sends_summary_and_stops_question_rendering(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(408, "Learner")
    seed_learning_items(1, user=user)
    start_message = FakeMessage(user)

    asyncio.run(learn(start_message))

    submit_training_answer(user.id, "word-1")
    submit_training_answer(user.id, "word-1")
    submit_training_answer(user.id, "word-1")
    submit_training_answer(user.id, "word-1")
    session = get_active_training_session(user.id)
    assert session is not None
    start_message.message_id = int(session["current_question_message_id"])
    callback = FakeCallback(user, TRAINING_HARD_SKIP_CALLBACK, start_message)

    asyncio.run(answer_training_hard_skip(callback))

    assert get_active_training_session(user.id) is None
    assert len(start_message.answers) == 3
    assert start_message.answers[-1]["text"] == "Hard skipped.\nResult: 1 questions, 4 correct answers."
    assert start_message.bot.edited_messages[-1]["text"] == "Item 1/1\nDone 1/1\nStage: completed"
    assert start_message.bot.deleted_messages == [
        {"chat_id": user.id, "message_id": 2},
        {"chat_id": user.id, "message_id": 1},
    ]


def test_learn_renders_hint_prompt_from_persisted_hint_language(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(407, "Learner")
    seed_learning_items(3, user=user)
    set_user_hint_language(user.id, "bg")
    create_learning_item_translation(1, "bg", "дума-1")
    message = FakeMessage(user)

    asyncio.run(learn(message))

    assert message.answers[1]["text"] == "дума-1"


def test_homework_completion_uses_homework_specific_summary(tmp_path: Path) -> None:
    setup_db(tmp_path)
    parent, child, family_id = seed_family_parent_and_child()
    lexeme_id = create_lexeme("homework-word")
    learning_item_id = create_family_learning_item(family_id, lexeme_id, "homework-word")
    create_learning_item_translation(learning_item_id, "ru", "домашка")
    assignment_id = create_family_homework_assignment(
        family_id,
        parent.id,
        child.id,
        [learning_item_id],
        title="Homework set",
    )
    start_assignment_training_session(child.id, f"family:{assignment_id}")
    start_message = FakeMessage(child)
    asyncio.run(render_started_training_session(start_message, child.id))

    submit_training_answer(child.id, "homework-word")
    submit_training_answer(child.id, "homework-word")
    submit_training_answer(child.id, "homework-word")
    submit_training_answer(child.id, "homework-word")
    session = get_active_training_session(child.id)
    assert session is not None
    answer_message = FakeMessage(child, text="homework-word", bot=start_message.bot)
    answer_message.message_id = int(session["current_question_message_id"])
    asyncio.run(answer_training_question(answer_message))

    assert answer_message.answers[-1]["text"] == (
        'Correct.\nHomework "Homework set" completed.\nResult: 1 questions, 5 correct answers.'
    )
    assert start_message.bot.deleted_messages == [
        {"chat_id": child.id, "message_id": 2},
        {"chat_id": child.id, "message_id": 1},
    ]


def test_homework_start_renders_one_progress_photo_and_one_question(tmp_path: Path) -> None:
    setup_db(tmp_path)
    parent, child, family_id = seed_family_parent_and_child()
    lexeme_id = create_lexeme("homework-word-family")
    learning_item_id = create_family_learning_item(family_id, lexeme_id, "homework-word")
    create_learning_item_translation(learning_item_id, "ru", "домашка")
    assignment_id = create_family_homework_assignment(
        family_id,
        parent.id,
        child.id,
        [learning_item_id],
        title="Homework set",
    )
    start_assignment_training_session(child.id, f"family:{assignment_id}")
    start_message = FakeMessage(child)

    asyncio.run(render_started_training_session(start_message, child.id))

    session = get_active_training_session(child.id)
    assert session is not None
    assert len(start_message.photo_answers) == 1
    assert len(start_message.answers) == 1
    assert session["progress_message_id"] == 1
    assert session["current_question_message_id"] == 2


def test_homework_progress_photo_updates_in_place_after_answer(tmp_path: Path) -> None:
    setup_db(tmp_path)
    parent, child, family_id = seed_family_parent_and_child()
    learning_item_ids: list[int] = []
    for index in range(3):
        lexeme_id = create_lexeme(f"homework-word-{index}")
        learning_item_id = create_family_learning_item(
            family_id,
            lexeme_id,
            f"homework-word-{index}",
        )
        create_learning_item_translation(learning_item_id, "ru", f"домашка-{index}")
        learning_item_ids.append(learning_item_id)
    assignment_id = create_family_homework_assignment(
        family_id,
        parent.id,
        child.id,
        learning_item_ids,
        title="Homework set",
    )
    start_assignment_training_session(child.id, f"family:{assignment_id}")
    start_message = FakeMessage(child)

    asyncio.run(render_started_training_session(start_message, child.id))

    keyboard = start_message.answers[0]["kwargs"]["reply_markup"]
    correct_answer = str(get_current_question(child.id)["expected_answer"])
    correct_index = _find_keyboard_index_by_label(keyboard, correct_answer)
    callback = FakeCallback(child, f"{TRAINING_EASY_CALLBACK_PREFIX}{correct_index}", start_message)

    asyncio.run(answer_training_easy(callback))

    session = get_active_training_session(child.id)
    assert session is not None
    assert len(start_message.photo_answers) == 1
    assert len(start_message.bot.edited_media) == 1
    assert start_message.bot.edited_media[0]["chat_id"] == child.id
    assert start_message.bot.edited_media[0]["message_id"] == 1
    assert session["progress_message_id"] == 1


def test_homework_progress_photo_not_modified_does_not_send_new_message(tmp_path: Path) -> None:
    setup_db(tmp_path)
    parent, child, family_id = seed_family_parent_and_child()
    learning_item_ids: list[int] = []
    for index in range(3):
        lexeme_id = create_lexeme(f"homework-word-{index}")
        learning_item_id = create_family_learning_item(
            family_id,
            lexeme_id,
            f"homework-word-{index}",
        )
        create_learning_item_translation(learning_item_id, "ru", f"домашка-{index}")
        learning_item_ids.append(learning_item_id)
    assignment_id = create_family_homework_assignment(
        family_id,
        parent.id,
        child.id,
        learning_item_ids,
        title="Homework set",
    )
    start_assignment_training_session(child.id, f"family:{assignment_id}")
    start_message = FakeMessage(child)

    asyncio.run(render_started_training_session(start_message, child.id))
    start_message.bot.fail_edit_media_message = "Bad Request: message is not modified"
    keyboard = start_message.answers[0]["kwargs"]["reply_markup"]
    correct_answer = str(get_current_question(child.id)["expected_answer"])
    correct_index = _find_keyboard_index_by_label(keyboard, correct_answer)

    asyncio.run(answer_training_easy(FakeCallback(child, f"{TRAINING_EASY_CALLBACK_PREFIX}{correct_index}", start_message)))

    session = get_active_training_session(child.id)
    assert session is not None
    assert len(start_message.photo_answers) == 1
    assert session["progress_message_id"] == 1
