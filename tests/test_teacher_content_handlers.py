import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from aiogram_dialog import StartMode
from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.teacher_content_dialog import (
    TeacherContentDialogSG,
    choose_field,
    get_browser_window_data,
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
)
from englishbot.teacher_content_handlers import teacher_content
from englishbot.user_profiles import set_user_role
from englishbot.workspaces import add_workspace_member, create_workspace


class FakeDialogManager:
    def __init__(self, user: User) -> None:
        self.event = SimpleNamespace(from_user=user)
        self.dialog_data: dict[str, object] = {}
        self.start_calls: list[dict[str, object]] = []
        self.switch_calls: list[object] = []
        self.update_calls: list[dict[str, object] | None] = []

    async def start(self, state, mode=None, data=None, **kwargs) -> None:
        self.start_calls.append({"state": state, "mode": mode, "data": data, "kwargs": kwargs})

    async def switch_to(self, state) -> None:
        self.switch_calls.append(state)

    async def update(self, data=None, **kwargs) -> None:
        if data:
            self.dialog_data.update(data)
        self.update_calls.append(data)


class FakeMessage:
    def __init__(self, user: User, text: str | None = None, photo=None) -> None:
        self.from_user = user
        self.text = text
        self.photo = photo
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append(text)


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "teacher_content_dialog.sqlite3"
    db.init_db()


def seed_topic(teacher_user_id: int, *, item_count: int = 2) -> tuple[int, int]:
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

    asyncio.run(on_workspace_selected(None, None, manager, str(workspace_id)))
    topics_view = asyncio.run(get_topics_window_data(manager))
    asyncio.run(on_topic_selected(None, None, manager, str(topic_id)))
    browser_view = asyncio.run(get_browser_window_data(manager))

    assert manager.switch_calls == [TeacherContentDialogSG.topics, TeacherContentDialogSG.browser]
    assert "Workspace: Authoring" in topics_view["screen_text"]
    assert "1. Fruits (2)" in topics_view["screen_text"]
    assert "Topic: Fruits" in browser_view["screen_text"]
    assert "Item 1/2" in browser_view["screen_text"]
    assert "ru: -" in browser_view["screen_text"]
    assert "audio_ref: -" in browser_view["screen_text"]


def test_prev_next_item_navigation_updates_selected_item_in_place(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(104, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    workspace_id, topic_id = seed_topic(teacher.id, item_count=3)
    manager = FakeDialogManager(teacher)
    manager.dialog_data.update({"workspace_id": workspace_id, "topic_id": topic_id})

    first_view = asyncio.run(get_browser_window_data(manager))
    asyncio.run(next_item(None, None, manager))
    second_view = asyncio.run(get_browser_window_data(manager))
    asyncio.run(prev_item(None, None, manager))
    third_view = asyncio.run(get_browser_window_data(manager))

    assert "Item 1/3" in first_view["screen_text"]
    assert "Item 2/3" in second_view["screen_text"]
    assert "Item 1/3" in third_view["screen_text"]
    assert len(manager.update_calls) == 2


def test_field_edit_prompt_entry_save_and_back_flow(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(105, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    workspace_id, topic_id = seed_topic(teacher.id)
    manager = FakeDialogManager(teacher)
    manager.dialog_data.update({"workspace_id": workspace_id, "topic_id": topic_id})
    asyncio.run(get_browser_window_data(manager))

    asyncio.run(open_edit_prompt(None, None, manager))
    prompt_picker = asyncio.run(get_prompt_window_data(manager))
    asyncio.run(choose_field(None, None, manager, "audio_ref"))
    prompt_input = asyncio.run(get_prompt_window_data(manager))
    asyncio.run(on_prompt_input(FakeMessage(teacher, text="audio://clip.mp3"), None, manager))
    browser_view = asyncio.run(get_browser_window_data(manager))

    assert manager.switch_calls[-2:] == [TeacherContentDialogSG.prompt, TeacherContentDialogSG.browser]
    assert "Choose a field to edit." in prompt_picker["screen_text"]
    assert "Send the new value for audio_ref." in prompt_input["screen_text"]
    assert "audio_ref: audio://clip.mp3" in browser_view["screen_text"]

    asyncio.run(open_create_topic(None, None, manager))
    asyncio.run(go_to_prompt_return(None, None, manager))
    assert manager.switch_calls[-2:] == [TeacherContentDialogSG.prompt, TeacherContentDialogSG.topics]


def test_publish_screen_and_back_do_not_spray_extra_messages(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher = make_user(106, "Teacher")
    db.save_user(teacher)
    set_user_role(teacher.id, "teacher")
    workspace_id, topic_id = seed_topic(teacher.id)
    student_workspace = create_workspace("Runtime", kind="student")
    add_workspace_member(student_workspace["workspace_id"], teacher.id, "teacher")
    manager = FakeDialogManager(teacher)
    manager.dialog_data.update({"workspace_id": workspace_id, "topic_id": topic_id})

    asyncio.run(open_publish_targets(None, None, manager))
    publish_view = asyncio.run(get_publish_window_data(manager))
    asyncio.run(go_to_browser(None, None, manager))

    assert "Publish topic" in publish_view["screen_text"]
    assert "1. Runtime" in publish_view["screen_text"]
    assert manager.switch_calls[-2:] == [TeacherContentDialogSG.publish, TeacherContentDialogSG.browser]


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

    assert manager.switch_calls == [TeacherContentDialogSG.workspaces]
    assert manager.dialog_data["status_text"] == "This teacher content is not available to you."
    assert "This teacher content is not available to you." in workspaces_view["screen_text"]
