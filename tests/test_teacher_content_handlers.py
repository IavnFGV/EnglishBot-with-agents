import asyncio
import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from aiogram_dialog import ShowMode, StartMode
from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.families import create_family
from englishbot.teacher_content_dialog import (
    TeacherContentDialogSG,
    choose_field,
    get_browser_window_data,
    get_prompt_window_data,
    get_topics_window_data,
    get_workspaces_window_data,
    go_to_prompt_return,
    hide_show_all,
    next_item,
    on_prompt_input,
    on_topic_selected,
    on_workspace_selected,
    open_create_topic,
    open_edit_prompt,
    prev_item,
    show_all_items,
)
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
        self.deleted = False

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append(text)
        self.answer_calls.append({"text": text, "kwargs": kwargs})
        return self.bot.build_sent_message(self.from_user)

    async def delete(self) -> None:
        self.deleted = True


class FakeBot:
    def __init__(self, download_payload: bytes | None = None) -> None:
        self.download_payload = download_payload or b""
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
    workspace_id = family_id
    topic = create_teacher_topic(user.id, workspace_id, topic_title)
    for index in range(item_count):
        create_teacher_topic_item(
            user.id,
            workspace_id,
            int(topic["id"]),
            f"{item_prefix}-{index + 1}",
        )
    return workspace_id, int(topic["id"])


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
            "data": {"workspace_id": 1},
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


def test_dialog_navigation_renders_family_workspace_topic_and_item_screens(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(103, "Family")
    workspace_id, topic_id = seed_topic(user)
    manager = FakeDialogManager(user)
    topic_message = FakeMessage(user, bot=FakeBot(), message_id=manager.last_message_id)

    asyncio.run(on_workspace_selected(None, None, manager, str(workspace_id)))
    topics_view = asyncio.run(get_topics_window_data(manager))
    asyncio.run(on_topic_selected(SimpleNamespace(message=topic_message), None, manager, str(topic_id)))
    browser_view = asyncio.run(get_browser_window_data(manager))

    assert manager.switch_calls == [
        {"state": TeacherContentDialogSG.topics, "show_mode": None},
        {"state": TeacherContentDialogSG.browser, "show_mode": ShowMode.SEND},
    ]
    assert "Workspace: Home" in topics_view["screen_text"]
    assert "1. Fruits (2)" in topics_view["screen_text"]
    assert "Topic: Fruits" in browser_view["screen_text"]
    assert "Item 1/2" in browser_view["screen_text"]
    assert "👉 • 1. <b>item-1</b>" in topic_message.bot.edit_calls[0]["text"]


def test_prev_next_item_navigation_updates_family_selection_in_place(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(104, "Family")
    workspace_id, topic_id = seed_topic(user, item_count=3)
    manager = FakeDialogManager(user)
    bot = FakeBot()
    manager.dialog_data.update(
        {
            "workspace_id": workspace_id,
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
    workspace_id, topic_id = seed_topic(user)
    manager = FakeDialogManager(user)
    bot = FakeBot()
    manager.dialog_data.update(
        {
            "workspace_id": workspace_id,
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
    workspace_id, topic_id = seed_topic(user)
    manager = FakeDialogManager(user)
    bot = FakeBot(download_payload=b"fake-image-bytes")
    manager.dialog_data.update(
        {
            "workspace_id": workspace_id,
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
    assert Path(tmp_path / str(media.path)).read_bytes() == b"fake-image-bytes"
    assert image_message.deleted is True


def test_show_all_sends_plain_read_only_message_and_keeps_browser_state(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(111, "Family")
    workspace_id, topic_id = seed_topic(user, item_count=11)
    from englishbot.teacher_content import build_teacher_topic_editor_snapshot, update_teacher_topic_item_field

    snapshot = build_teacher_topic_editor_snapshot(user.id, workspace_id, topic_id)
    item_ids = [int(item["id"]) for item in snapshot["navigator_items"]]
    update_teacher_topic_item_field(user.id, workspace_id, topic_id, item_ids[0], "image_ref", "assets/images/item-1.png")
    update_teacher_topic_item_field(user.id, workspace_id, topic_id, item_ids[0], "ru", "перевод")
    manager = FakeDialogManager(user)
    manager.dialog_data.update({"workspace_id": workspace_id, "topic_id": topic_id, "item_id": item_ids[1]})
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
    workspace_id, topic_id = seed_topic(user, item_count=3)
    bot = FakeBot()
    manager = FakeDialogManager(user)
    manager.dialog_data.update(
        {
            "workspace_id": workspace_id,
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


def test_unauthorized_family_workspace_selection_falls_back_to_workspaces(tmp_path: Path) -> None:
    setup_db(tmp_path)
    owner = make_user(107, "Owner")
    outsider = make_user(108, "Outsider")
    workspace_id, _topic_id = seed_topic(owner)
    db.save_user(outsider)
    manager = FakeDialogManager(outsider)

    asyncio.run(on_workspace_selected(None, None, manager, str(workspace_id)))
    workspaces_view = asyncio.run(get_workspaces_window_data(manager))

    assert manager.switch_calls == [{"state": TeacherContentDialogSG.workspaces, "show_mode": None}]
    assert manager.dialog_data["status_text"] == "This teacher content is not available to you."
    assert "This teacher content is not available to you." in workspaces_view["screen_text"]
