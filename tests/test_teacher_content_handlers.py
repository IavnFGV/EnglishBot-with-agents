import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.teacher_content_handlers import (
    TEACHER_CONTENT_ADD_ITEM_PREFIX,
    TEACHER_CONTENT_ARCHIVE_PREFIX,
    TEACHER_CONTENT_EDIT_PREFIX,
    TEACHER_CONTENT_FIELD_PREFIX,
    TEACHER_CONTENT_IMAGE_PREFIX,
    TEACHER_CONTENT_PAGE_PREFIX,
    TEACHER_CONTENT_TOPIC_CREATE,
    TEACHER_CONTENT_TOPIC_PREFIX,
    TEACHER_CONTENT_WORKSPACE_BACK,
    TEACHER_CONTENT_WORKSPACE_CREATE,
    TEACHER_CONTENT_WORKSPACE_PREFIX,
    TeacherContentStates,
    archive_teacher_item,
    change_teacher_topic_page,
    open_teacher_topic,
    open_teacher_workspace,
    save_teacher_item_field_value,
    save_teacher_item_image_ref,
    save_teacher_item_text,
    save_teacher_topic_title,
    save_teacher_workspace_name,
    select_teacher_topic_item,
    show_teacher_item_edit_fields,
    start_teacher_item_field_edit,
    start_teacher_item_image_update,
    start_teacher_topic_create,
    start_teacher_workspace_create,
    teacher_content,
)
from englishbot.teacher_content import build_teacher_topic_editor_snapshot
from englishbot.user_profiles import set_user_role
from englishbot.workspaces import add_workspace_member, create_workspace


class FakeBot:
    def __init__(self) -> None:
        self.edited_messages: list[dict[str, object]] = []

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


class FakeMessage:
    def __init__(self, user: User, text: str | None = None, photo=None, bot: FakeBot | None = None) -> None:
        self.from_user = user
        self.text = text
        self.photo = photo
        self.bot = bot or FakeBot()
        self.chat = SimpleNamespace(id=user.id)
        self.answers: list[dict[str, object]] = []
        self._next_message_id = 1

    async def answer(self, text: str, **kwargs: object) -> SimpleNamespace:
        sent = SimpleNamespace(message_id=self._next_message_id)
        self._next_message_id += 1
        self.answers.append({"text": text, "kwargs": kwargs, "message_id": sent.message_id})
        return sent


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


def make_state(user: User) -> FSMContext:
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=user.id, user_id=user.id),
    )


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "teacher_content_handlers.sqlite3"
    db.init_db()


def seed_topic(
    teacher_user_id: int,
    *,
    item_count: int = 1,
) -> tuple[int, int]:
    from englishbot.teacher_content import create_teacher_topic, create_teacher_topic_item

    workspace = create_workspace("Authoring", kind="teacher")
    add_workspace_member(workspace["workspace_id"], teacher_user_id, "teacher")
    topic = create_teacher_topic(teacher_user_id, int(workspace["workspace_id"]), "Fruits")
    for index in range(item_count):
        create_teacher_topic_item(
            teacher_user_id,
            int(workspace["workspace_id"]),
            int(topic["id"]),
            f"item-{index + 1}",
        )
    return int(workspace["workspace_id"]), int(topic["id"])


def test_teacher_content_handler_lists_workspaces_and_creates_workspace(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(101, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    add_workspace_member(create_workspace("Authoring", kind="teacher")["workspace_id"], teacher.id, "teacher")
    message = FakeMessage(teacher)
    state = make_state(teacher)

    asyncio.run(teacher_content(message, state))
    callback = FakeCallback(teacher, TEACHER_CONTENT_WORKSPACE_CREATE, message)
    asyncio.run(start_teacher_workspace_create(callback, state))
    asyncio.run(save_teacher_workspace_name(FakeMessage(teacher, text="Second Space", bot=message.bot), state))

    assert message.answers[0]["text"] == "Your teacher spaces:"
    assert callback.answered is True
    latest_data = asyncio.run(state.get_data())
    assert latest_data == {}


def test_teacher_can_browse_topics_create_topic_and_open_three_message_editor(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(102, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    workspace = create_workspace("Authoring", kind="teacher")
    add_workspace_member(workspace["workspace_id"], teacher.id, "teacher")
    message = FakeMessage(teacher)
    state = make_state(teacher)

    callback = FakeCallback(teacher, f"{TEACHER_CONTENT_WORKSPACE_PREFIX}{workspace['workspace_id']}", message)
    asyncio.run(open_teacher_workspace(callback, state))
    create_callback = FakeCallback(
        teacher,
        f"{TEACHER_CONTENT_TOPIC_CREATE}{workspace['workspace_id']}",
        message,
    )
    asyncio.run(start_teacher_topic_create(create_callback, state))
    create_message = FakeMessage(teacher, text="Animals", bot=message.bot)
    asyncio.run(save_teacher_topic_title(create_message, state))

    assert callback.answered is True
    assert create_callback.answered is True
    assert [answer["text"] for answer in create_message.answers[-3:]] == [
        "Topic: Animals\nPage 1/1. Items: 0.\nThis topic has no learning items yet.",
        "No image.",
        "Animals\nNo active items in this topic yet.",
    ]
    state_data = asyncio.run(state.get_data())
    assert state_data["navigator_message_id"] == 2
    assert state_data["image_message_id"] == 3
    assert state_data["card_message_id"] == 4


def test_topic_editor_page_navigation_updates_three_message_model(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(103, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    workspace_id, topic_id = seed_topic(teacher.id, item_count=27)
    message = FakeMessage(teacher)
    state = make_state(teacher)

    callback = FakeCallback(teacher, f"{TEACHER_CONTENT_TOPIC_PREFIX}{workspace_id}:{topic_id}", message)
    asyncio.run(open_teacher_topic(callback, state))
    page_callback = FakeCallback(teacher, f"{TEACHER_CONTENT_PAGE_PREFIX}{workspace_id}:{topic_id}:1", message)
    asyncio.run(change_teacher_topic_page(page_callback, state))

    assert callback.answered is True
    assert page_callback.answered is True
    assert len(message.answers) == 3
    assert len(message.bot.edited_messages) == 3
    assert "Page 2/2. Items: 27." in message.bot.edited_messages[0]["text"]
    state_data = asyncio.run(state.get_data())
    assert state_data["page"] == 1


def test_prev_next_navigation_and_field_editing_update_db_backed_editor(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(104, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    workspace_id, topic_id = seed_topic(teacher.id, item_count=3)
    message = FakeMessage(teacher)
    state = make_state(teacher)

    asyncio.run(open_teacher_topic(FakeCallback(teacher, f"{TEACHER_CONTENT_TOPIC_PREFIX}{workspace_id}:{topic_id}", message), state))
    next_callback_data = message.answers[2]["kwargs"]["reply_markup"].inline_keyboard[0][0].callback_data
    asyncio.run(select_teacher_topic_item(FakeCallback(teacher, next_callback_data, message), state))
    edit_callback_data = message.bot.edited_messages[-1]["reply_markup"].inline_keyboard[1][0].callback_data
    asyncio.run(show_teacher_item_edit_fields(FakeCallback(teacher, edit_callback_data, message), state))
    asyncio.run(start_teacher_item_field_edit(FakeCallback(teacher, f"{TEACHER_CONTENT_FIELD_PREFIX}bg", message), state))
    asyncio.run(save_teacher_item_field_value(FakeMessage(teacher, text="ябълка", bot=message.bot), state))

    snapshot = build_teacher_topic_editor_snapshot(
        teacher.id,
        workspace_id,
        topic_id,
        selected_item_id=asyncio.run(state.get_data())["item_id"],
    )
    assert snapshot["current_item"]["translations"]["bg"] == "ябълка"


def test_add_item_archive_and_photo_image_rejection_work(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(105, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    workspace_id, topic_id = seed_topic(teacher.id, item_count=1)
    message = FakeMessage(teacher)
    state = make_state(teacher)

    asyncio.run(open_teacher_topic(FakeCallback(teacher, f"{TEACHER_CONTENT_TOPIC_PREFIX}{workspace_id}:{topic_id}", message), state))
    add_callback = FakeCallback(
        teacher,
        f"{TEACHER_CONTENT_ADD_ITEM_PREFIX}{workspace_id}:{topic_id}:0",
        message,
    )
    from englishbot.teacher_content_handlers import start_teacher_item_create

    asyncio.run(start_teacher_item_create(add_callback, state))
    asyncio.run(save_teacher_item_text(FakeMessage(teacher, text="pear", bot=message.bot), state))
    state_data = asyncio.run(state.get_data())
    archive_callback = FakeCallback(
        teacher,
        f"{TEACHER_CONTENT_ARCHIVE_PREFIX}{workspace_id}:{topic_id}:{state_data['item_id']}:0",
        message,
    )
    asyncio.run(archive_teacher_item(archive_callback, state))
    image_callback = FakeCallback(
        teacher,
        f"{TEACHER_CONTENT_IMAGE_PREFIX}{workspace_id}:{topic_id}:{build_teacher_topic_editor_snapshot(teacher.id, workspace_id, topic_id)['selected_item_id']}",
        message,
    )
    asyncio.run(start_teacher_item_image_update(image_callback, state))
    photo_message = FakeMessage(teacher, photo=[object()], bot=message.bot)
    asyncio.run(save_teacher_item_image_ref(photo_message, state))

    assert add_callback.answered is True
    assert archive_callback.answered is True
    assert image_callback.answered is True
    assert photo_message.answers[-1]["text"] == (
        "Telegram photo upload persistence is not implemented yet. Send a text image_ref instead."
    )


def test_unauthorized_teacher_content_access_is_rejected(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(106, "Teacher")
    stranger = make_user(107, "Stranger")
    db.save_user(teacher)
    db.save_user(stranger)
    set_user_role(teacher.id, "teacher")
    set_user_role(stranger.id, "teacher")
    workspace_id, topic_id = seed_topic(teacher.id, item_count=1)
    message = FakeMessage(stranger)
    state = make_state(stranger)

    callback = FakeCallback(stranger, f"{TEACHER_CONTENT_TOPIC_PREFIX}{workspace_id}:{topic_id}", message)
    asyncio.run(open_teacher_topic(callback, state))

    assert callback.answered is True
    assert message.answers == [{"text": "This teacher content is not available to you.", "kwargs": {}, "message_id": 1}]
