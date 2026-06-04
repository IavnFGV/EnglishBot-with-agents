import asyncio
import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from aiogram.enums.content_type import ContentType
from aiogram.exceptions import TelegramBadRequest
from aiogram_dialog import ShowMode, StartMode
from aiogram_dialog.api.entities import MediaId
from aiogram.types import User
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.assets import PRIMARY_IMAGE_ROLE, create_asset, get_cached_telegram_file_id, link_asset_to_learning_item
from englishbot.families import create_family
from englishbot.teacher_content_dialog import (
    TeacherContentDialogSG,
    choose_field,
    get_browser_window_data,
    get_prompt_window_data,
    get_topics_window_data,
    next_topic_page,
    prev_topic_page,
    go_to_prompt_return,
    hide_show_all,
    next_item,
    _open_bulk_edit,
    on_prompt_input,
    on_topic_selected,
    open_create_topic,
    open_edit_prompt,
    prev_item,
    show_all_items,
)
from englishbot.telegram_media_storage import telegram_media_id_storage
from englishbot.teacher_content_handlers import teacher_content


class FakeDialogManager:
    def __init__(self, user: User) -> None:
        self.event = SimpleNamespace(from_user=user, chat=SimpleNamespace(id=user.id))
        self.dialog_data: dict[str, object] = {}
        self.start_calls: list[dict[str, object]] = []
        self.switch_calls: list[dict[str, object]] = []
        self.update_calls: list[dict[str, object] | None] = []
        self.done_calls: list[dict[str, object]] = []
        self.last_message_id = 100

    async def start(self, state, mode=None, data=None, **kwargs) -> None:
        self.start_calls.append({"state": state, "mode": mode, "data": data, "kwargs": kwargs})

    async def switch_to(self, state, show_mode=None) -> None:
        self.switch_calls.append({"state": state, "show_mode": show_mode})
        if show_mode == ShowMode.SEND:
            self.last_message_id += 1

    async def update(self, data=None, **kwargs) -> None:
        if data:
            self.dialog_data.update(data)
        self.update_calls.append({"data": data, "kwargs": kwargs})

    async def done(self, result=None, show_mode=None) -> None:
        self.done_calls.append({"result": result, "show_mode": show_mode})

    def current_stack(self):
        return SimpleNamespace(last_message_id=self.last_message_id)


class FakeMessage:
    def __init__(self, user: User, text: str | None = None, photo=None, bot=None, message_id: int = 1) -> None:
        self.from_user = user
        self.text = text
        self.photo = photo
        self.bot = bot or FakeBot()
        self.chat = SimpleNamespace(id=user.id)
        self.message_id = message_id
        self.answers: list[str] = []
        self.answer_calls: list[dict[str, object]] = []
        self.document_calls: list[dict[str, object]] = []
        self.deleted = False

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append(text)
        self.answer_calls.append({"text": text, "kwargs": kwargs})
        return self.bot.build_sent_message(self.from_user)

    async def answer_document(self, document, **kwargs):
        self.document_calls.append({"document": document, "kwargs": kwargs})
        return self.bot.build_sent_message(self.from_user)

    async def delete(self) -> None:
        self.deleted = True


class FakeBot:
    def __init__(self, download_payload: bytes | None = None, *, reject_unchanged_edit: bool = False) -> None:
        self.download_payload = download_payload or b""
        self.reject_unchanged_edit = reject_unchanged_edit
        self.sent_messages: list[SimpleNamespace] = []
        self.edit_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []
        self.next_message_id = 1000

    async def download(self, file: object, destination: BytesIO) -> BytesIO:
        destination.write(self.download_payload)
        destination.seek(0)
        return destination

    def build_sent_message(self, user: User) -> SimpleNamespace:
        self.next_message_id += 1
        sent = SimpleNamespace(message_id=self.next_message_id, chat=SimpleNamespace(id=user.id))
        self.sent_messages.append(sent)
        return sent

    async def edit_message_text(self, *, text: str, chat_id: int, message_id: int, parse_mode=None, reply_markup=None):
        if self.reject_unchanged_edit and self.edit_calls:
            previous_call = self.edit_calls[-1]
            if (
                previous_call["text"] == text
                and previous_call["chat_id"] == chat_id
                and previous_call["message_id"] == message_id
                and previous_call["reply_markup"] == reply_markup
            ):
                raise TelegramBadRequest(
                    method="editMessageText",
                    message="Telegram server says - Bad Request: message is not modified: specified new message content and reply markup are exactly the same as a current content and reply markup of the message",
                )
        self.edit_calls.append(
            {
                "text": text,
                "chat_id": chat_id,
                "message_id": message_id,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
            }
        )

    async def delete_message(self, *, chat_id: int, message_id: int):
        self.delete_calls.append({"chat_id": chat_id, "message_id": message_id})


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "teacher_content_dialog.sqlite3"
    db.init_db()


def seed_family_user(user: User, family_name: str = "Home") -> int:
    db.save_user(user)
    family = create_family(family_name, user.id)
    return int(family["id"])


def seed_topic(
    user: User,
    *,
    item_count: int = 2,
    topic_title: str = "Fruits",
    item_prefix: str = "item",
) -> tuple[int, int]:
    from englishbot.teacher_content import create_teacher_topic, create_teacher_topic_item

    family_id = seed_family_user(user)
    topic = create_teacher_topic(user.id, family_id, topic_title)
    for index in range(item_count):
        create_teacher_topic_item(
            user.id,
            family_id,
            int(topic["id"]),
            f"{item_prefix}-{index + 1}",
        )
    return family_id, int(topic["id"])


def attach_primary_image(learning_item_id: int, image_path: Path) -> None:
    asset_id = create_asset("image", local_path=str(image_path.as_posix()))
    link_asset_to_learning_item(learning_item_id, asset_id, PRIMARY_IMAGE_ROLE)


def seed_topics(user: User, topic_count: int) -> int:
    from englishbot.teacher_content import create_teacher_topic

    family_id = seed_family_user(user)
    for index in range(topic_count):
        create_teacher_topic(user.id, family_id, f"Topic {index + 1:02d}")
    return family_id


def test_teacher_content_command_starts_dialog_for_family_member(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(101, "Family")
    seed_family_user(user)
    manager = FakeDialogManager(user)
    message = FakeMessage(user)

    asyncio.run(teacher_content(message, manager))

    assert message.answers == []
    assert manager.start_calls == [
        {
            "state": TeacherContentDialogSG.topics,
            "mode": StartMode.RESET_STACK,
            "data": {"family_id": 1},
            "kwargs": {},
        }
    ]


def test_teacher_content_command_rejects_user_without_family(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(102, "NoFamily")
    db.save_user(user)
    manager = FakeDialogManager(user)
    message = FakeMessage(user)

    asyncio.run(teacher_content(message, manager))

    assert manager.start_calls == []
    assert message.answers == ["Command /teacher_content is available only inside a family setup."]


def test_dialog_navigation_renders_family_topic_and_item_screens(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(103, "Family")
    family_id, topic_id = seed_topic(user)
    manager = FakeDialogManager(user)
    topic_message = FakeMessage(user, bot=FakeBot(), message_id=manager.last_message_id)

    manager.dialog_data["family_id"] = family_id
    topics_view = asyncio.run(get_topics_window_data(manager))
    asyncio.run(on_topic_selected(SimpleNamespace(message=topic_message), None, manager, str(topic_id)))
    browser_view = asyncio.run(get_browser_window_data(manager))

    assert manager.switch_calls == [{"state": TeacherContentDialogSG.browser, "show_mode": ShowMode.SEND}]
    assert "Family: Home" in topics_view["screen_text"]
    assert "Choose a topic." in topics_view["screen_text"]
    assert "1. Fruits (2)" not in topics_view["screen_text"]
    assert topics_view["topic_items"] == [{"id": topic_id, "name": "fruits", "title": "Fruits", "item_count": 2, "label": "1. Fruits (2)"}]
    assert "Topic: Fruits" in browser_view["screen_text"]
    assert "Item 1/2" in browser_view["screen_text"]
    assert "👉 • 1. <b>item-1</b>" in topic_message.bot.edit_calls[0]["text"]


def test_dialog_media_storage_uses_project_cache_table_for_teacher_item_images(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    user = make_user(130, "Family")
    seed_topic(user, item_count=1)
    image_path = tmp_path / "teacher-item.png"
    image_path.write_bytes(b"fake image")
    attach_primary_image(1, image_path)

    asyncio.run(
        telegram_media_id_storage.save_media_id(
            path="assets/images/no-image.png",
            url=None,
            type=ContentType.PHOTO,
            media_id=MediaId(file_id="ignored-placeholder-id"),
        )
    )
    assert get_cached_telegram_file_id(1, "photo") is None

    asyncio.run(
        telegram_media_id_storage.save_media_id(
            path=str(image_path.as_posix()),
            url=None,
            type=ContentType.PHOTO,
            media_id=MediaId(file_id="teacher-photo-id", file_unique_id="teacher-photo-uniq"),
        )
    )

    cached_media_id = asyncio.run(
        telegram_media_id_storage.get_media_id(
            path=str(image_path.as_posix()),
            url=None,
            type=ContentType.PHOTO,
        )
    )

    assert cached_media_id is not None
    assert cached_media_id.file_id == "teacher-photo-id"
    assert get_cached_telegram_file_id(1, "photo") == "teacher-photo-id"


def test_topics_window_uses_single_compact_list_without_scrolling_group(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(120, "Family")
    family_id = seed_topics(user, 3)
    manager = FakeDialogManager(user)
    manager.dialog_data["family_id"] = family_id

    topics_view = asyncio.run(get_topics_window_data(manager))
    assert "Topic 1" not in topics_view["screen_text"]
    assert topics_view["screen_text"].endswith("Page 1/1 • total 3")
    assert [item["label"] for item in topics_view["topic_items"]] == [
        "1. Topic 01 (0)",
        "2. Topic 02 (0)",
        "3. Topic 03 (0)",
    ]


def test_topics_window_next_page_shows_next_slice(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(121, "Family")
    family_id = seed_topics(user, 10)
    manager = FakeDialogManager(user)
    manager.dialog_data["family_id"] = family_id

    first_view = asyncio.run(get_topics_window_data(manager))
    asyncio.run(next_topic_page(SimpleNamespace(message=None), SimpleNamespace(widget_id="topic_next_page"), manager))
    second_view = asyncio.run(get_topics_window_data(manager))

    assert [item["label"] for item in first_view["topic_items"]] == [
        "1. Topic 01 (0)",
        "2. Topic 02 (0)",
        "3. Topic 03 (0)",
        "4. Topic 04 (0)",
        "5. Topic 05 (0)",
        "6. Topic 06 (0)",
        "7. Topic 07 (0)",
        "8. Topic 08 (0)",
    ]
    assert second_view["screen_text"].endswith("Page 2/2 • total 10")
    assert [item["label"] for item in second_view["topic_items"]] == [
        "9. Topic 09 (0)",
        "10. Topic 10 (0)",
    ]


def test_topics_window_prev_page_returns_to_previous_slice(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(122, "Family")
    family_id = seed_topics(user, 10)
    manager = FakeDialogManager(user)
    manager.dialog_data.update({"family_id": family_id, "topic_page": 1})

    second_view = asyncio.run(get_topics_window_data(manager))
    asyncio.run(prev_topic_page(SimpleNamespace(message=None), SimpleNamespace(widget_id="topic_prev_page"), manager))
    first_view = asyncio.run(get_topics_window_data(manager))

    assert [item["label"] for item in second_view["topic_items"]] == [
        "9. Topic 09 (0)",
        "10. Topic 10 (0)",
    ]
    assert first_view["screen_text"].endswith("Page 1/2 • total 10")
    assert [item["label"] for item in first_view["topic_items"]][:2] == [
        "1. Topic 01 (0)",
        "2. Topic 02 (0)",
    ]


def test_topic_selection_from_second_page_opens_matching_browser(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(123, "Family")
    family_id = seed_topics(user, 9)
    from englishbot.teacher_content import create_teacher_topic_item, list_teacher_workspace_topics

    topics = list_teacher_workspace_topics(user.id, family_id)
    target_topic = topics[-1]
    create_teacher_topic_item(user.id, family_id, int(target_topic["id"]), "late-item")
    manager = FakeDialogManager(user)
    manager.dialog_data["family_id"] = family_id
    topic_message = FakeMessage(user, bot=FakeBot(), message_id=manager.last_message_id)

    asyncio.run(next_topic_page(SimpleNamespace(message=None), SimpleNamespace(widget_id="topic_next_page"), manager))
    topics_view = asyncio.run(get_topics_window_data(manager))
    asyncio.run(on_topic_selected(SimpleNamespace(message=topic_message), None, manager, str(target_topic["id"])))
    browser_view = asyncio.run(get_browser_window_data(manager))

    assert [item["label"] for item in topics_view["topic_items"]] == ["9. Topic 09 (1)"]
    assert manager.dialog_data["topic_id"] == int(target_topic["id"])
    assert "Topic: Topic 09" in browser_view["screen_text"]
    assert "Item 1/1" in browser_view["screen_text"]
    assert "Topic: Topic 09" in topic_message.bot.edit_calls[0]["text"]


def test_topics_window_empty_and_single_page_states_stay_compact(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(124, "Family")
    empty_family_id = seed_family_user(user)
    empty_manager = FakeDialogManager(user)
    empty_manager.dialog_data["family_id"] = empty_family_id

    empty_view = asyncio.run(get_topics_window_data(empty_manager))

    assert empty_view["topic_items"] == []
    assert empty_view["has_prev_page"] is False
    assert empty_view["has_next_page"] is False
    assert "No topics are available in this family yet." in empty_view["screen_text"]

    single_user = make_user(125, "Single")
    single_family_id = seed_topics(single_user, 1)
    single_manager = FakeDialogManager(single_user)
    single_manager.dialog_data["family_id"] = single_family_id

    single_view = asyncio.run(get_topics_window_data(single_manager))

    assert single_view["has_prev_page"] is False
    assert single_view["has_next_page"] is False
    assert single_view["screen_text"].endswith("Page 1/1 • total 1")
    assert len(single_view["topic_items"]) == 1
    assert single_view["topic_items"][0]["title"] == "Topic 01"
    assert single_view["topic_items"][0]["label"] == "1. Topic 01 (0)"


def test_topics_screen_exposes_bulk_edit_entrypoint(tmp_path: Path, monkeypatch) -> None:
    setup_db(tmp_path)
    user = make_user(118, "Family")
    family_id, _ = seed_topic(user)
    manager = FakeDialogManager(user)
    manager.dialog_data["family_id"] = family_id
    bot_user = User(id=999999, is_bot=True, first_name="EnglishBot", username="englishbot")
    topic_message = FakeMessage(bot_user, bot=FakeBot(), message_id=manager.last_message_id)
    topic_message.chat = SimpleNamespace(id=user.id)

    topics_view = asyncio.run(get_topics_window_data(manager))
    asyncio.run(_open_bulk_edit(SimpleNamespace(message=topic_message, from_user=user), None, manager))

    assert topics_view["bulk_edit_label"] == "📄 Bulk edit"
    assert len(topic_message.document_calls) == 1
    assert topic_message.answers[-1].startswith("Edit the workbook locally")


def test_prev_next_item_navigation_updates_family_selection_in_place(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(104, "Family")
    family_id, topic_id = seed_topic(user, item_count=3)
    manager = FakeDialogManager(user)
    bot = FakeBot()
    manager.dialog_data.update(
        {
            "family_id": family_id,
            "topic_id": topic_id,
            "browser_overview_message_id": 77,
            "browser_overview_chat_id": user.id,
        }
    )
    callback_message = FakeMessage(user, bot=bot, message_id=manager.last_message_id)

    first_view = asyncio.run(get_browser_window_data(manager))
    asyncio.run(next_item(SimpleNamespace(message=callback_message), None, manager))
    second_view = asyncio.run(get_browser_window_data(manager))
    asyncio.run(prev_item(SimpleNamespace(message=callback_message), None, manager))
    third_view = asyncio.run(get_browser_window_data(manager))

    assert "Item 1/3" in first_view["screen_text"]
    assert "Item 2/3" in second_view["screen_text"]
    assert "Item 1/3" in third_view["screen_text"]
    assert len(bot.edit_calls) == 2


def test_field_edit_prompt_entry_save_and_back_flow(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(105, "Family")
    family_id, topic_id = seed_topic(user)
    manager = FakeDialogManager(user)
    bot = FakeBot()
    manager.dialog_data.update(
        {
            "family_id": family_id,
            "topic_id": topic_id,
            "browser_overview_message_id": 77,
            "browser_overview_chat_id": user.id,
        }
    )
    asyncio.run(get_browser_window_data(manager))

    asyncio.run(open_edit_prompt(None, None, manager))
    prompt_picker = asyncio.run(get_prompt_window_data(manager))
    asyncio.run(choose_field(None, None, manager, "audio_ref"))
    prompt_input = asyncio.run(get_prompt_window_data(manager))
    asyncio.run(on_prompt_input(FakeMessage(user, text="audio://clip.mp3", bot=bot), None, manager))
    browser_view = asyncio.run(get_browser_window_data(manager))

    assert "Choose a field to edit." in prompt_picker["screen_text"]
    assert prompt_input["screen_text"] == "Send the new value for Audio."
    assert "audio_ref" not in browser_view["screen_text"]

    asyncio.run(open_create_topic(None, None, manager))
    asyncio.run(go_to_prompt_return(SimpleNamespace(message=FakeMessage(user, bot=bot)), None, manager))
    assert manager.switch_calls[-2:] == [
        {"state": TeacherContentDialogSG.prompt, "show_mode": None},
        {"state": TeacherContentDialogSG.topics, "show_mode": None},
    ]


def test_image_field_upload_persists_local_image_and_saves_local_ref(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(109, "Family")
    family_id, topic_id = seed_topic(user)
    manager = FakeDialogManager(user)
    buffer = BytesIO()
    Image.new("RGB", (1, 1), color=(255, 0, 0)).save(buffer, format="PNG")
    png_payload = buffer.getvalue()
    bot = FakeBot(download_payload=png_payload)
    manager.dialog_data.update(
        {
            "family_id": family_id,
            "topic_id": topic_id,
            "browser_overview_message_id": 77,
            "browser_overview_chat_id": user.id,
        }
    )
    asyncio.run(get_browser_window_data(manager))

    asyncio.run(open_edit_prompt(None, None, manager))
    asyncio.run(choose_field(None, None, manager, "image_ref"))
    image_message = FakeMessage(
        user,
        photo=[SimpleNamespace(file_id="small-file"), SimpleNamespace(file_id="real-photo-file")],
        bot=bot,
    )
    asyncio.run(on_prompt_input(image_message, None, manager))
    browser_view = asyncio.run(get_browser_window_data(manager))

    media = browser_view["current_item_media"]
    assert media is not None
    assert str(media.path).startswith("assets/images/teacher-content/learning-item-")
    assert Path(tmp_path / str(media.path)).read_bytes() == png_payload
    assert image_message.deleted is True


def test_invalid_local_image_falls_back_to_placeholder_media(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(119, "Family")
    family_id, topic_id = seed_topic(user)
    from englishbot.teacher_content import update_teacher_topic_item_field

    manager = FakeDialogManager(user)
    manager.dialog_data.update({"family_id": family_id, "topic_id": topic_id})
    snapshot = asyncio.run(get_browser_window_data(manager))
    item_id = int(manager.dialog_data["item_id"])
    update_teacher_topic_item_field(
        user.id,
        family_id,
        topic_id,
        item_id,
        "image_ref",
        "assets/images/not-a-real-image.jpg",
    )

    browser_view = asyncio.run(get_browser_window_data(manager))
    media = browser_view["current_item_media"]

    assert snapshot["current_item_media"] is not None
    assert media is not None
    assert str(media.path) == "assets/images/no-image.png"


def test_show_all_sends_plain_read_only_message_and_keeps_browser_state(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(111, "Family")
    family_id, topic_id = seed_topic(user, item_count=11)
    from englishbot.teacher_content import build_teacher_topic_editor_snapshot, update_teacher_topic_item_field

    snapshot = build_teacher_topic_editor_snapshot(user.id, family_id, topic_id)
    item_ids = [int(item["id"]) for item in snapshot["navigator_items"]]
    update_teacher_topic_item_field(user.id, family_id, topic_id, item_ids[0], "image_ref", "assets/images/item-1.png")
    update_teacher_topic_item_field(user.id, family_id, topic_id, item_ids[0], "ru", "перевод")
    manager = FakeDialogManager(user)
    manager.dialog_data.update({"family_id": family_id, "topic_id": topic_id, "item_id": item_ids[1]})
    browser_before = asyncio.run(get_browser_window_data(manager))
    callback_message = FakeMessage(user, bot=FakeBot())

    asyncio.run(show_all_items(SimpleNamespace(message=callback_message), None, manager))
    browser_after = asyncio.run(get_browser_window_data(manager))
    show_all_text = callback_message.answers[0]

    assert "Topic: Fruits" in show_all_text
    assert "Items: 11" in show_all_text
    assert "🖼 item-1" in show_all_text
    assert "перевод" not in show_all_text
    assert browser_before["screen_text"] == browser_after["screen_text"]


def test_prompt_return_ignores_unchanged_overview_edit_error(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(114, "Family")
    family_id, topic_id = seed_topic(user, item_count=2)
    bot = FakeBot(reject_unchanged_edit=True)
    manager = FakeDialogManager(user)
    manager.dialog_data.update({"family_id": family_id})
    callback_message = FakeMessage(user, bot=bot, message_id=manager.last_message_id)

    asyncio.run(on_topic_selected(SimpleNamespace(message=callback_message), None, manager, str(topic_id)))
    manager.dialog_data.update({"prompt_kind": "edit_field", "edit_field": "ru"})
    asyncio.run(go_to_prompt_return(SimpleNamespace(message=callback_message), None, manager))

    assert manager.switch_calls[-1] == {"state": TeacherContentDialogSG.browser, "show_mode": None}


def test_hide_show_all_deletes_temporary_message(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(112, "Family")
    callback_message = FakeMessage(user)
    answered = {"value": False}

    async def answer() -> None:
        answered["value"] = True

    asyncio.run(hide_show_all(SimpleNamespace(message=callback_message, answer=answer)))

    assert callback_message.deleted is True
    assert answered["value"] is True


def test_cancel_deletes_browser_card_and_overview_message(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(113, "Family")
    family_id, topic_id = seed_topic(user, item_count=3)
    bot = FakeBot()
    manager = FakeDialogManager(user)
    manager.dialog_data.update(
        {
            "family_id": family_id,
            "topic_id": topic_id,
            "browser_overview_message_id": 77,
            "browser_overview_chat_id": user.id,
        }
    )
    callback_message = FakeMessage(user, bot=bot, message_id=manager.last_message_id)
    from englishbot.teacher_content_dialog import _cancel_dialog

    asyncio.run(_cancel_dialog(SimpleNamespace(message=callback_message), None, manager))

    assert callback_message.deleted is True
    assert bot.delete_calls == [{"chat_id": user.id, "message_id": 77}]
    assert manager.done_calls == [{"result": None, "show_mode": ShowMode.NO_UPDATE}]


def test_unauthorized_family_topics_view_stays_blocked(tmp_path: Path) -> None:
    setup_db(tmp_path)
    owner = make_user(107, "Owner")
    outsider = make_user(108, "Outsider")
    family_id, _topic_id = seed_topic(owner)
    db.save_user(outsider)
    manager = FakeDialogManager(outsider)

    manager.dialog_data["family_id"] = family_id
    topics_view = asyncio.run(get_topics_window_data(manager))

    assert manager.switch_calls == []
    assert manager.dialog_data["status_text"] == "This teacher content is not available to you."
    assert "This teacher content is not available to you." in topics_view["screen_text"]
