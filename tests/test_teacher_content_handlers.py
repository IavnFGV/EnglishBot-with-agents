import asyncio
import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from aiogram_dialog import ShowMode, StartMode
from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.teacher_content_dialog import (
    TeacherContentDialogSG,
    choose_field,
    get_browser_window_data,
    hide_show_all,
    get_publish_window_data,
    get_prompt_window_data,
    get_topics_window_data,
    get_workspaces_window_data,
    go_to_browser,
    go_to_prompt_return,
    next_item,
    on_prompt_input,
    on_topic_selected,
    on_workspace_selected,
    open_create_topic,
    open_edit_prompt,
    open_publish_targets,
    prev_item,
    show_all_items,
)
from englishbot.teacher_content_handlers import teacher_content
from englishbot.user_profiles import set_user_role
from englishbot.workspaces import add_workspace_member, create_workspace


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
        sent = SimpleNamespace(
            message_id=self.next_message_id,
            chat=SimpleNamespace(id=user.id),
        )
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


def seed_topic(
    teacher_user_id: int,
    *,
    item_count: int = 2,
    workspace_name: str = "Authoring",
    topic_title: str = "Fruits",
    item_prefix: str = "item",
) -> tuple[int, int]:
    from englishbot.teacher_content import create_teacher_topic, create_teacher_topic_item

    workspace = create_workspace(workspace_name, kind="teacher")
    add_workspace_member(workspace["workspace_id"], teacher_user_id, "teacher")
    topic = create_teacher_topic(teacher_user_id, int(workspace["workspace_id"]), topic_title)
    for index in range(item_count):
        create_teacher_topic_item(
            teacher_user_id,
            int(workspace["workspace_id"]),
            int(topic["id"]),
            f"{item_prefix}-{index + 1}",
        )
    return int(workspace["workspace_id"]), int(topic["id"])


def test_teacher_content_command_starts_dialog_without_extra_reply(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(101, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    manager = FakeDialogManager(teacher)
    message = FakeMessage(teacher)

    asyncio.run(teacher_content(message, manager))

    assert message.answers == []
    assert manager.start_calls == [
        {
            "state": TeacherContentDialogSG.workspaces,
            "mode": StartMode.RESET_STACK,
            "data": None,
            "kwargs": {},
        }
    ]


def test_teacher_content_command_rejects_non_teacher(tmp_path: Path) -> None:
    setup_db(tmp_path)
    student = make_user(102, "Student")
    db.save_user(student)
    set_user_role(student.id, "student")
    manager = FakeDialogManager(student)
    message = FakeMessage(student)

    asyncio.run(teacher_content(message, manager))

    assert manager.start_calls == []
    assert message.answers == [
        "Command /teacher_content is available only to users with the teacher role."
    ]


def test_dialog_navigation_renders_compact_workspace_topic_and_item_screens(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(103, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    workspace_id, topic_id = seed_topic(teacher.id)
    manager = FakeDialogManager(teacher)
    topic_message = FakeMessage(teacher, bot=FakeBot(), message_id=manager.last_message_id)

    asyncio.run(on_workspace_selected(None, None, manager, str(workspace_id)))
    topics_view = asyncio.run(get_topics_window_data(manager))
    asyncio.run(on_topic_selected(SimpleNamespace(message=topic_message), None, manager, str(topic_id)))
    browser_view = asyncio.run(get_browser_window_data(manager))

    assert manager.switch_calls == [
        {"state": TeacherContentDialogSG.topics, "show_mode": None},
        {"state": TeacherContentDialogSG.browser, "show_mode": ShowMode.SEND},
    ]
    assert "Workspace: Authoring" in topics_view["screen_text"]
    assert "1. Fruits (2)" in topics_view["screen_text"]
    assert "Topic: Fruits" in browser_view["screen_text"]
    assert "Item 1/2" in browser_view["screen_text"]
    assert "Headword:" not in browser_view["screen_text"]
    assert "ru: -" in browser_view["screen_text"]
    assert "audio_ref" not in browser_view["screen_text"]
    assert "image_ref" not in browser_view["screen_text"]
    assert browser_view["has_current_image"] is False
    assert str(browser_view["current_item_media"].path) == "assets/images/no-image.jpg"
    assert topic_message.bot.edit_calls[0]["message_id"] == 100
    assert "Topic: Fruits" in topic_message.bot.edit_calls[0]["text"]
    assert "👉 • 1. <b>item-1</b>" in topic_message.bot.edit_calls[0]["text"]


def test_prev_next_item_navigation_updates_selected_item_in_place(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(104, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    workspace_id, topic_id = seed_topic(teacher.id, item_count=3)
    manager = FakeDialogManager(teacher)
    bot = FakeBot()
    manager.dialog_data.update(
        {
            "workspace_id": workspace_id,
            "topic_id": topic_id,
            "browser_overview_message_id": 77,
            "browser_overview_chat_id": teacher.id,
        }
    )
    callback_message = FakeMessage(teacher, bot=bot, message_id=manager.last_message_id)

    first_view = asyncio.run(get_browser_window_data(manager))
    asyncio.run(next_item(SimpleNamespace(message=callback_message), None, manager))
    second_view = asyncio.run(get_browser_window_data(manager))
    asyncio.run(prev_item(SimpleNamespace(message=callback_message), None, manager))
    third_view = asyncio.run(get_browser_window_data(manager))

    assert "Item 1/3" in first_view["screen_text"]
    assert "Item 2/3" in second_view["screen_text"]
    assert "Item 1/3" in third_view["screen_text"]
    assert len(manager.update_calls) == 2
    assert manager.update_calls[0]["kwargs"] == {}
    assert manager.update_calls[1]["kwargs"] == {}
    assert len(bot.edit_calls) == 2
    assert "👉 • 2. <b>item-2</b>" in bot.edit_calls[0]["text"]


def test_next_from_last_item_wraps_to_first_and_overview_wraps_too(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(114, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    workspace_id, topic_id = seed_topic(teacher.id, item_count=11)
    from englishbot.teacher_content import build_teacher_topic_editor_snapshot

    initial_snapshot = build_teacher_topic_editor_snapshot(teacher.id, workspace_id, topic_id)
    item_ids = [int(item["id"]) for item in initial_snapshot["navigator_items"]]
    manager = FakeDialogManager(teacher)
    bot = FakeBot()
    manager.dialog_data.update(
        {
            "workspace_id": workspace_id,
            "topic_id": topic_id,
            "item_id": item_ids[-1],
            "browser_overview_message_id": 77,
            "browser_overview_chat_id": teacher.id,
        }
    )
    callback_message = FakeMessage(teacher, bot=bot, message_id=manager.last_message_id)

    last_view = asyncio.run(get_browser_window_data(manager))
    asyncio.run(next_item(SimpleNamespace(message=callback_message), None, manager))
    first_view = asyncio.run(get_browser_window_data(manager))

    assert "Item 11/11" in last_view["screen_text"]
    assert "Item 1/11" in first_view["screen_text"]
    assert manager.dialog_data["item_id"] == item_ids[0]
    assert manager.update_calls[-1]["kwargs"] == {}
    assert "👉 • 1. <b>item-1</b>" in bot.edit_calls[0]["text"]
    assert "• 11. item-11" in bot.edit_calls[0]["text"]


def test_next_from_item_with_image_to_item_without_image_recreates_browser_message(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(116, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    workspace_id, topic_id = seed_topic(teacher.id, item_count=6)
    from englishbot.teacher_content import (
        build_teacher_topic_editor_snapshot,
        update_teacher_topic_item_field,
    )

    snapshot = build_teacher_topic_editor_snapshot(teacher.id, workspace_id, topic_id)
    item_ids = [int(item["id"]) for item in snapshot["navigator_items"]]
    update_teacher_topic_item_field(
        teacher.id,
        workspace_id,
        topic_id,
        item_ids[4],
        "image_ref",
        "assets/images/teacher-content/may.jpg",
    )

    manager = FakeDialogManager(teacher)
    bot = FakeBot()
    manager.dialog_data.update(
        {
            "workspace_id": workspace_id,
            "topic_id": topic_id,
            "item_id": item_ids[4],
            "browser_overview_message_id": 77,
            "browser_overview_chat_id": teacher.id,
        }
    )
    callback_message = FakeMessage(teacher, bot=bot, message_id=manager.last_message_id)

    may_view = asyncio.run(get_browser_window_data(manager))
    asyncio.run(next_item(SimpleNamespace(message=callback_message), None, manager))
    june_view = asyncio.run(get_browser_window_data(manager))

    assert may_view["has_current_image"] is True
    assert june_view["has_current_image"] is False
    assert manager.dialog_data["item_id"] == item_ids[5]
    assert str(june_view["current_item_media"].path) == "assets/images/no-image.jpg"
    assert manager.update_calls[-1]["kwargs"] == {}
    assert "👉 • 6. <b>item-6</b>" in bot.edit_calls[0]["text"]


def test_field_edit_prompt_entry_save_and_back_flow(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(105, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    workspace_id, topic_id = seed_topic(teacher.id)
    manager = FakeDialogManager(teacher)
    bot = FakeBot()
    manager.dialog_data.update(
        {
            "workspace_id": workspace_id,
            "topic_id": topic_id,
            "browser_overview_message_id": 77,
            "browser_overview_chat_id": teacher.id,
        }
    )
    asyncio.run(get_browser_window_data(manager))

    asyncio.run(open_edit_prompt(None, None, manager))
    prompt_picker = asyncio.run(get_prompt_window_data(manager))
    asyncio.run(choose_field(None, None, manager, "audio_ref"))
    prompt_input = asyncio.run(get_prompt_window_data(manager))
    asyncio.run(on_prompt_input(FakeMessage(teacher, text="audio://clip.mp3", bot=bot), None, manager))
    browser_view = asyncio.run(get_browser_window_data(manager))

    assert manager.switch_calls[-2:] == [
        {"state": TeacherContentDialogSG.prompt, "show_mode": None},
        {"state": TeacherContentDialogSG.browser, "show_mode": ShowMode.EDIT},
    ]
    assert "Choose a field to edit." in prompt_picker["screen_text"]
    assert prompt_input["screen_text"] == "Send the new value for Audio."
    assert "audio_ref" not in browser_view["screen_text"]
    assert bot.edit_calls[-1]["message_id"] == 77

    asyncio.run(open_create_topic(None, None, manager))
    asyncio.run(go_to_prompt_return(SimpleNamespace(message=FakeMessage(teacher, bot=bot)), None, manager))
    assert manager.switch_calls[-2:] == [
        {"state": TeacherContentDialogSG.prompt, "show_mode": None},
        {"state": TeacherContentDialogSG.topics, "show_mode": None},
    ]


def test_image_field_upload_persists_local_image_and_saves_local_ref(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(109, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    workspace_id, topic_id = seed_topic(teacher.id)
    manager = FakeDialogManager(teacher)
    bot = FakeBot(download_payload=b"fake-image-bytes")
    manager.dialog_data.update(
        {
            "workspace_id": workspace_id,
            "topic_id": topic_id,
            "browser_overview_message_id": 77,
            "browser_overview_chat_id": teacher.id,
        }
    )
    asyncio.run(get_browser_window_data(manager))

    asyncio.run(open_edit_prompt(None, None, manager))
    asyncio.run(choose_field(None, None, manager, "image_ref"))
    image_message = FakeMessage(
        teacher,
        photo=[SimpleNamespace(file_id="small-file"), SimpleNamespace(file_id="real-photo-file")],
        bot=bot,
    )
    asyncio.run(
        on_prompt_input(
            image_message,
            None,
            manager,
        )
    )
    browser_view = asyncio.run(get_browser_window_data(manager))

    assert manager.switch_calls[-2:] == [
        {"state": TeacherContentDialogSG.prompt, "show_mode": None},
        {"state": TeacherContentDialogSG.browser, "show_mode": ShowMode.EDIT},
    ]
    assert manager.dialog_data["status_text"] == "Image reference saved."
    media = browser_view["current_item_media"]
    assert media is not None
    assert str(media.path).startswith("assets/images/teacher-content/learning-item-")
    assert Path(tmp_path / str(media.path)).read_bytes() == b"fake-image-bytes"
    assert image_message.deleted is True


def test_image_field_url_downloads_local_copy_and_deletes_user_message(tmp_path: Path, monkeypatch) -> None:
    setup_db(tmp_path)
    teacher = make_user(115, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    workspace_id, topic_id = seed_topic(teacher.id)
    manager = FakeDialogManager(teacher)
    bot = FakeBot()
    manager.dialog_data.update(
        {
            "workspace_id": workspace_id,
            "topic_id": topic_id,
            "browser_overview_message_id": 77,
            "browser_overview_chat_id": teacher.id,
        }
    )
    asyncio.run(get_browser_window_data(manager))

    stored_paths: list[tuple[int, str]] = []

    def fake_store_from_url(learning_item_id: int, source_url: str) -> str:
        stored_paths.append((learning_item_id, source_url))
        return "assets/images/teacher-content/downloaded-image.jpg"

    monkeypatch.setattr(
        "englishbot.teacher_content_dialog.store_teacher_content_image_from_url",
        fake_store_from_url,
    )

    asyncio.run(open_edit_prompt(None, None, manager))
    asyncio.run(choose_field(None, None, manager, "image_ref"))
    url_message = FakeMessage(teacher, text="https://example.com/may.jpg", bot=bot)

    asyncio.run(on_prompt_input(url_message, None, manager))
    browser_view = asyncio.run(get_browser_window_data(manager))

    assert manager.switch_calls[-2:] == [
        {"state": TeacherContentDialogSG.prompt, "show_mode": None},
        {"state": TeacherContentDialogSG.browser, "show_mode": ShowMode.EDIT},
    ]
    assert stored_paths == [(manager.dialog_data["item_id"], "https://example.com/may.jpg")]
    assert browser_view["current_item_media"] is not None
    assert str(browser_view["current_item_media"].path) == "assets/images/teacher-content/downloaded-image.jpg"
    assert url_message.deleted is True


def test_publish_screen_and_back_do_not_spray_extra_messages(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(106, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    workspace_id, topic_id = seed_topic(teacher.id)
    student_workspace = create_workspace("Runtime", kind="student")
    add_workspace_member(student_workspace["workspace_id"], teacher.id, "teacher")
    manager = FakeDialogManager(teacher)
    bot = FakeBot()
    manager.dialog_data.update(
        {
            "workspace_id": workspace_id,
            "topic_id": topic_id,
            "browser_overview_message_id": 77,
            "browser_overview_chat_id": teacher.id,
        }
    )

    asyncio.run(open_publish_targets(None, None, manager))
    publish_view = asyncio.run(get_publish_window_data(manager))
    asyncio.run(go_to_browser(SimpleNamespace(message=FakeMessage(teacher, bot=bot)), None, manager))

    assert "Publish topic" in publish_view["screen_text"]
    assert "1. Runtime" in publish_view["screen_text"]
    assert manager.switch_calls[-2:] == [
        {"state": TeacherContentDialogSG.publish, "show_mode": None},
        {"state": TeacherContentDialogSG.browser, "show_mode": None},
    ]


def test_show_all_button_appears_only_for_topics_with_more_than_ten_items(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(110, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    large_workspace_id, large_topic_id = seed_topic(teacher.id, item_count=11)
    small_workspace_id, small_topic_id = seed_topic(
        teacher.id,
        item_count=10,
        workspace_name="Authoring Small",
        topic_title="Vegetables",
        item_prefix="veg",
    )
    manager = FakeDialogManager(teacher)

    manager.dialog_data.update({"workspace_id": large_workspace_id, "topic_id": large_topic_id})
    large_view = asyncio.run(get_browser_window_data(manager))
    manager.dialog_data.update({"workspace_id": small_workspace_id, "topic_id": small_topic_id, "item_id": None})
    small_view = asyncio.run(get_browser_window_data(manager))

    assert large_view["show_all_available"] is True
    assert large_view["show_all_label"] == "📄 Show all"
    assert small_view["show_all_available"] is False


def test_show_all_sends_plain_read_only_message_and_keeps_browser_state(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(111, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    workspace_id, topic_id = seed_topic(teacher.id, item_count=11)
    from englishbot.teacher_content import (
        build_teacher_topic_editor_snapshot,
        update_teacher_topic_item_field,
    )

    snapshot = build_teacher_topic_editor_snapshot(teacher.id, workspace_id, topic_id)
    item_ids = [int(item["id"]) for item in snapshot["navigator_items"]]

    update_teacher_topic_item_field(
        teacher.id,
        workspace_id,
        topic_id,
        item_ids[0],
        "image_ref",
        "assets/images/item-1.png",
    )
    update_teacher_topic_item_field(teacher.id, workspace_id, topic_id, item_ids[0], "ru", "перевод")
    update_teacher_topic_item_field(teacher.id, workspace_id, topic_id, item_ids[1], "audio_ref", "audio://clip.mp3")

    manager = FakeDialogManager(teacher)
    manager.dialog_data.update({"workspace_id": workspace_id, "topic_id": topic_id, "item_id": item_ids[1]})
    browser_before = asyncio.run(get_browser_window_data(manager))
    callback_message = FakeMessage(teacher, bot=FakeBot())
    callback = SimpleNamespace(message=callback_message)

    asyncio.run(show_all_items(callback, None, manager))
    browser_after = asyncio.run(get_browser_window_data(manager))
    show_all_text = callback_message.answers[0]

    assert "Topic: Fruits" in show_all_text
    assert "Items: 11" in show_all_text
    assert "🖼 item-1" in show_all_text
    assert "• item-2" in show_all_text
    assert "перевод" not in show_all_text
    assert "audio://" not in show_all_text
    assert "image_ref" not in show_all_text
    assert "id" not in show_all_text.lower()
    assert manager.switch_calls == []
    assert manager.update_calls == []
    assert manager.dialog_data["item_id"] == item_ids[1]
    assert browser_before["screen_text"] == browser_after["screen_text"]
    reply_markup = callback_message.answer_calls[0]["kwargs"]["reply_markup"]
    assert reply_markup.inline_keyboard[0][0].text == "OK"


def test_hide_show_all_deletes_temporary_message(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(112, "Teacher")
    callback_message = FakeMessage(teacher)
    answered = {"value": False}

    async def answer() -> None:
        answered["value"] = True

    asyncio.run(hide_show_all(SimpleNamespace(message=callback_message, answer=answer)))

    assert callback_message.deleted is True
    assert answered["value"] is True


def test_cancel_deletes_browser_card_and_overview_message(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(113, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    workspace_id, topic_id = seed_topic(teacher.id, item_count=3)
    bot = FakeBot()
    manager = FakeDialogManager(teacher)
    manager.dialog_data.update(
        {
            "workspace_id": workspace_id,
            "topic_id": topic_id,
            "browser_overview_message_id": 77,
            "browser_overview_chat_id": teacher.id,
        }
    )
    callback_message = FakeMessage(teacher, bot=bot, message_id=manager.last_message_id)

    from englishbot.teacher_content_dialog import _cancel_dialog

    asyncio.run(_cancel_dialog(SimpleNamespace(message=callback_message), None, manager))

    assert callback_message.deleted is True
    assert bot.delete_calls == [{"chat_id": teacher.id, "message_id": 77}]
    assert manager.done_calls == [{"result": None, "show_mode": ShowMode.NO_UPDATE}]


def test_unauthorized_workspace_selection_falls_back_to_workspaces(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(107, "Teacher")
    outsider = make_user(108, "Outsider")
    db.save_user(teacher)
    db.save_user(outsider)
    set_user_role(teacher.id, "teacher")
    set_user_role(outsider.id, "teacher")
    workspace_id, _topic_id = seed_topic(teacher.id)
    manager = FakeDialogManager(outsider)

    asyncio.run(on_workspace_selected(None, None, manager, str(workspace_id)))
    workspaces_view = asyncio.run(get_workspaces_window_data(manager))

    assert manager.switch_calls == [{"state": TeacherContentDialogSG.workspaces, "show_mode": None}]
    assert manager.dialog_data["status_text"] == "This teacher content is not available to you."
    assert "This teacher content is not available to you." in workspaces_view["screen_text"]
