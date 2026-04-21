from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .command_registry import TEACHER_CONTENT_COMMAND
from .db import save_user
from .i18n import translate_for_user
from .runtime import router
from .teacher_content import (
    TeacherContentAccessError,
    TeacherContentPublishTargetError,
    build_teacher_topic_editor_snapshot,
    create_teacher_topic,
    create_teacher_topic_item,
    create_teacher_workspace_for_user,
    list_teacher_browsable_workspaces,
    list_teacher_publish_targets,
    list_teacher_workspace_topics,
    publish_teacher_topic_to_workspace,
    update_teacher_topic_item_field,
    update_teacher_topic_item_image_ref,
    archive_teacher_topic_item,
)
from .user_profiles import get_user_role

TEACHER_CONTENT_WORKSPACE_PREFIX = "tcw:"
TEACHER_CONTENT_WORKSPACE_CREATE = "tcwc"
TEACHER_CONTENT_WORKSPACE_BACK = "tcbw"
TEACHER_CONTENT_TOPIC_PREFIX = "tct:"
TEACHER_CONTENT_TOPIC_CREATE = "tcn:"
TEACHER_CONTENT_TOPIC_BACK = "tcbt:"
TEACHER_CONTENT_ITEM_PREFIX = "tci:"
TEACHER_CONTENT_PAGE_PREFIX = "tcp:"
TEACHER_CONTENT_EDIT_PREFIX = "tce:"
TEACHER_CONTENT_FIELD_PREFIX = "tcf:"
TEACHER_CONTENT_ARCHIVE_PREFIX = "tca:"
TEACHER_CONTENT_ADD_ITEM_PREFIX = "tcai:"
TEACHER_CONTENT_IMAGE_PREFIX = "tcim:"
TEACHER_CONTENT_PUBLISH_PREFIX = "tcpu:"
TEACHER_CONTENT_PUBLISH_TARGET_PREFIX = "tcpt:"

EDITABLE_FIELD_LABEL_KEYS = {
    "text": "teacher.content.field.text",
    "ru": "teacher.content.field.ru",
    "uk": "teacher.content.field.uk",
    "bg": "teacher.content.field.bg",
}


class TeacherContentStates(StatesGroup):
    awaiting_workspace_name = State()
    awaiting_topic_title = State()
    awaiting_item_text = State()
    awaiting_item_field_value = State()
    awaiting_item_image_input = State()


def build_teacher_workspaces_keyboard(
    telegram_user_id: int,
    workspaces: list[dict[str, object]],
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=str(workspace["name"]),
                callback_data=f"{TEACHER_CONTENT_WORKSPACE_PREFIX}{workspace['id']}",
            )
        ]
        for workspace in workspaces
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text=translate_for_user(
                    telegram_user_id,
                    "teacher.content.action.create_workspace",
                ),
                callback_data=TEACHER_CONTENT_WORKSPACE_CREATE,
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_teacher_topics_keyboard(
    telegram_user_id: int,
    workspace_id: int,
    topics: list[dict[str, object]],
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{topic['title']} ({topic['item_count']})",
                callback_data=f"{TEACHER_CONTENT_TOPIC_PREFIX}{workspace_id}:{topic['id']}",
            )
        ]
        for topic in topics
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text=translate_for_user(
                    telegram_user_id,
                    "teacher.content.action.create_topic",
                ),
                callback_data=f"{TEACHER_CONTENT_TOPIC_CREATE}{workspace_id}",
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=translate_for_user(
                    telegram_user_id,
                    "teacher.content.action.back_to_workspaces",
                ),
                callback_data=TEACHER_CONTENT_WORKSPACE_BACK,
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_teacher_item_field_keyboard(telegram_user_id: int) -> InlineKeyboardMarkup:
    rows = []
    for field_name in ("text", "ru", "uk", "bg"):
        rows.append(
            [
                InlineKeyboardButton(
                    text=translate_for_user(
                        telegram_user_id,
                        EDITABLE_FIELD_LABEL_KEYS[field_name],
                    ),
                    callback_data=f"{TEACHER_CONTENT_FIELD_PREFIX}{field_name}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_teacher_publish_targets_keyboard(
    targets: list[dict[str, object]],
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=str(target["name"]),
                    callback_data=f"{TEACHER_CONTENT_PUBLISH_TARGET_PREFIX}{target['id']}",
                )
            ]
            for target in targets
        ]
    )


@router.message(Command(TEACHER_CONTENT_COMMAND.name))
async def teacher_content(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    save_user(message.from_user)
    if get_user_role(message.from_user.id) != "teacher":
        await message.answer(
            translate_for_user(
                message.from_user.id,
                "teacher.command_teacher_only",
                command=TEACHER_CONTENT_COMMAND.token,
            )
        )
        return
    await state.clear()
    await _render_teacher_workspaces(message, message.from_user.id)


@router.callback_query(lambda callback: callback.data == TEACHER_CONTENT_WORKSPACE_CREATE)
async def start_teacher_workspace_create(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None:
        return
    await state.clear()
    await state.set_state(TeacherContentStates.awaiting_workspace_name)
    await callback.message.answer(
        translate_for_user(
            callback.from_user.id,
            "teacher.content.prompt.workspace_name",
        )
    )


@router.message(TeacherContentStates.awaiting_workspace_name)
async def save_teacher_workspace_name(message: Message, state: FSMContext) -> None:
    if message.from_user is None or message.text is None:
        return
    try:
        workspace = create_teacher_workspace_for_user(message.from_user.id, message.text)
    except ValueError:
        await message.answer(
            translate_for_user(
                message.from_user.id,
                "teacher.content.prompt.workspace_name",
            )
        )
        return
    await state.clear()
    await message.answer(
        translate_for_user(
            message.from_user.id,
            "teacher.content.workspace.created",
            workspace_name=str(workspace["name"]),
        )
    )
    await _render_teacher_workspaces(message, message.from_user.id)


@router.callback_query(lambda callback: callback.data == TEACHER_CONTENT_WORKSPACE_BACK)
async def back_to_teacher_workspaces(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None:
        return
    await state.clear()
    await _render_teacher_workspaces(callback.message, callback.from_user.id)


@router.callback_query(
    lambda callback: callback.data is not None
    and callback.data.startswith(TEACHER_CONTENT_WORKSPACE_PREFIX)
)
async def open_teacher_workspace(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None or callback.data is None:
        return
    try:
        workspace_id = int(callback.data.removeprefix(TEACHER_CONTENT_WORKSPACE_PREFIX))
        topics = list_teacher_workspace_topics(callback.from_user.id, workspace_id)
    except (TeacherContentAccessError, ValueError):
        await _answer_teacher_content_unavailable(callback.message, callback.from_user.id, state)
        return

    await state.update_data(workspace_id=workspace_id)
    await callback.message.answer(
        translate_for_user(
            callback.from_user.id,
            "teacher.content.topics.title",
            workspace_name=_resolve_workspace_name(callback.from_user.id, workspace_id),
        ),
        reply_markup=build_teacher_topics_keyboard(
            callback.from_user.id,
            workspace_id,
            topics,
        ),
    )


@router.callback_query(
    lambda callback: callback.data is not None
    and callback.data.startswith(TEACHER_CONTENT_TOPIC_CREATE)
)
async def start_teacher_topic_create(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None or callback.data is None:
        return
    try:
        workspace_id = int(callback.data.removeprefix(TEACHER_CONTENT_TOPIC_CREATE))
        list_teacher_workspace_topics(callback.from_user.id, workspace_id)
    except (TeacherContentAccessError, ValueError):
        await _answer_teacher_content_unavailable(callback.message, callback.from_user.id, state)
        return
    await state.update_data(workspace_id=workspace_id)
    await state.set_state(TeacherContentStates.awaiting_topic_title)
    await callback.message.answer(
        translate_for_user(
            callback.from_user.id,
            "teacher.content.prompt.topic_title",
        )
    )


@router.message(TeacherContentStates.awaiting_topic_title)
async def save_teacher_topic_title(message: Message, state: FSMContext) -> None:
    if message.from_user is None or message.text is None:
        return
    data = await state.get_data()
    workspace_id = data.get("workspace_id")
    if workspace_id is None:
        await state.clear()
        return
    try:
        topic = create_teacher_topic(message.from_user.id, int(workspace_id), message.text)
    except TeacherContentAccessError:
        await _answer_teacher_content_unavailable(message, message.from_user.id, state)
        return
    except ValueError:
        await message.answer(
            translate_for_user(
                message.from_user.id,
                "teacher.content.prompt.topic_title",
            )
        )
        return

    await state.set_state(None)
    await message.answer(
        translate_for_user(
            message.from_user.id,
            "teacher.content.topic.created",
            topic_title=str(topic["title"]),
        )
    )
    await refresh_teacher_topic_editor(
        message,
        message.from_user.id,
        state,
        int(topic["workspace_id"]),
        int(topic["id"]),
    )


@router.callback_query(
    lambda callback: callback.data is not None
    and callback.data.startswith(TEACHER_CONTENT_TOPIC_PREFIX)
)
async def open_teacher_topic(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None or callback.data is None:
        return
    payload = callback.data.removeprefix(TEACHER_CONTENT_TOPIC_PREFIX)
    try:
        workspace_id_text, topic_id_text = payload.split(":", maxsplit=1)
        await state.set_state(None)
        await refresh_teacher_topic_editor(
            callback.message,
            callback.from_user.id,
            state,
            int(workspace_id_text),
            int(topic_id_text),
        )
    except (TeacherContentAccessError, ValueError):
        await _answer_teacher_content_unavailable(callback.message, callback.from_user.id, state)


@router.callback_query(
    lambda callback: callback.data is not None
    and callback.data.startswith(TEACHER_CONTENT_PAGE_PREFIX)
)
async def change_teacher_topic_page(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None or callback.data is None:
        return
    payload = callback.data.removeprefix(TEACHER_CONTENT_PAGE_PREFIX)
    try:
        workspace_id_text, topic_id_text, page_text = payload.split(":", maxsplit=2)
        await refresh_teacher_topic_editor(
            callback.message,
            callback.from_user.id,
            state,
            int(workspace_id_text),
            int(topic_id_text),
            page=int(page_text),
        )
    except (TeacherContentAccessError, ValueError):
        await _answer_teacher_content_unavailable(callback.message, callback.from_user.id, state)


@router.callback_query(
    lambda callback: callback.data is not None
    and callback.data.startswith(TEACHER_CONTENT_ITEM_PREFIX)
)
async def select_teacher_topic_item(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None or callback.data is None:
        return
    payload = callback.data.removeprefix(TEACHER_CONTENT_ITEM_PREFIX)
    try:
        workspace_id_text, topic_id_text, item_id_text = payload.split(":", maxsplit=2)
        await refresh_teacher_topic_editor(
            callback.message,
            callback.from_user.id,
            state,
            int(workspace_id_text),
            int(topic_id_text),
            selected_item_id=int(item_id_text),
        )
    except (TeacherContentAccessError, ValueError):
        await _answer_teacher_content_unavailable(callback.message, callback.from_user.id, state)


@router.callback_query(
    lambda callback: callback.data is not None
    and callback.data.startswith(TEACHER_CONTENT_EDIT_PREFIX)
)
async def show_teacher_item_edit_fields(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None or callback.data is None:
        return
    payload = callback.data.removeprefix(TEACHER_CONTENT_EDIT_PREFIX)
    try:
        workspace_id_text, topic_id_text, item_id_text = payload.split(":", maxsplit=2)
        snapshot = build_teacher_topic_editor_snapshot(
            callback.from_user.id,
            int(workspace_id_text),
            int(topic_id_text),
            selected_item_id=int(item_id_text),
        )
    except (TeacherContentAccessError, ValueError):
        await _answer_teacher_content_unavailable(callback.message, callback.from_user.id, state)
        return
    if snapshot["current_item"] is None:
        return
    await state.update_data(
        workspace_id=int(workspace_id_text),
        topic_id=int(topic_id_text),
        item_id=int(item_id_text),
        page=int(snapshot["page"]),
    )
    await callback.message.answer(
        translate_for_user(
            callback.from_user.id,
            "teacher.content.prompt.edit_field",
        ),
        reply_markup=build_teacher_item_field_keyboard(callback.from_user.id),
    )


@router.callback_query(
    lambda callback: callback.data is not None
    and callback.data.startswith(TEACHER_CONTENT_FIELD_PREFIX)
)
async def start_teacher_item_field_edit(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None or callback.data is None:
        return
    field_name = callback.data.removeprefix(TEACHER_CONTENT_FIELD_PREFIX)
    if field_name not in EDITABLE_FIELD_LABEL_KEYS:
        return
    data = await state.get_data()
    workspace_id = data.get("workspace_id")
    topic_id = data.get("topic_id")
    item_id = data.get("item_id")
    if workspace_id is None or topic_id is None or item_id is None:
        await _answer_teacher_content_unavailable(callback.message, callback.from_user.id, state)
        return
    try:
        build_teacher_topic_editor_snapshot(
            callback.from_user.id,
            int(workspace_id),
            int(topic_id),
            selected_item_id=int(item_id),
        )
    except TeacherContentAccessError:
        await _answer_teacher_content_unavailable(callback.message, callback.from_user.id, state)
        return
    await state.update_data(edit_field=field_name)
    await state.set_state(TeacherContentStates.awaiting_item_field_value)
    await callback.message.answer(
        translate_for_user(
            callback.from_user.id,
            "teacher.content.prompt.field_value",
            field_name=translate_for_user(
                callback.from_user.id,
                EDITABLE_FIELD_LABEL_KEYS[field_name],
            ),
        )
    )


@router.message(TeacherContentStates.awaiting_item_field_value)
async def save_teacher_item_field_value(message: Message, state: FSMContext) -> None:
    if message.from_user is None or message.text is None:
        return
    data = await state.get_data()
    workspace_id = data.get("workspace_id")
    topic_id = data.get("topic_id")
    item_id = data.get("item_id")
    field_name = data.get("edit_field")
    if None in (workspace_id, topic_id, item_id, field_name):
        await state.clear()
        return
    try:
        update_teacher_topic_item_field(
            message.from_user.id,
            int(workspace_id),
            int(topic_id),
            int(item_id),
            str(field_name),
            message.text,
        )
    except TeacherContentAccessError:
        await _answer_teacher_content_unavailable(message, message.from_user.id, state)
        return
    except ValueError:
        await message.answer(
            translate_for_user(
                message.from_user.id,
                "teacher.content.prompt.field_value",
                field_name=translate_for_user(
                    message.from_user.id,
                    EDITABLE_FIELD_LABEL_KEYS[str(field_name)],
                ),
            )
        )
        return

    await state.update_data(edit_field=None)
    await state.set_state(None)
    await refresh_teacher_topic_editor(
        message,
        message.from_user.id,
        state,
        int(workspace_id),
        int(topic_id),
        selected_item_id=int(item_id),
        notice_key="teacher.content.item.saved",
    )


@router.callback_query(
    lambda callback: callback.data is not None
    and callback.data.startswith(TEACHER_CONTENT_ADD_ITEM_PREFIX)
)
async def start_teacher_item_create(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None or callback.data is None:
        return
    payload = callback.data.removeprefix(TEACHER_CONTENT_ADD_ITEM_PREFIX)
    try:
        workspace_id_text, topic_id_text, page_text = payload.split(":", maxsplit=2)
        build_teacher_topic_editor_snapshot(
            callback.from_user.id,
            int(workspace_id_text),
            int(topic_id_text),
            page=int(page_text),
        )
    except (TeacherContentAccessError, ValueError):
        await _answer_teacher_content_unavailable(callback.message, callback.from_user.id, state)
        return
    await state.update_data(
        workspace_id=int(workspace_id_text),
        topic_id=int(topic_id_text),
        page=int(page_text),
    )
    await state.set_state(TeacherContentStates.awaiting_item_text)
    await callback.message.answer(
        translate_for_user(
            callback.from_user.id,
            "teacher.content.prompt.item_text",
        )
    )


@router.message(TeacherContentStates.awaiting_item_text)
async def save_teacher_item_text(message: Message, state: FSMContext) -> None:
    if message.from_user is None or message.text is None:
        return
    data = await state.get_data()
    workspace_id = data.get("workspace_id")
    topic_id = data.get("topic_id")
    if workspace_id is None or topic_id is None:
        await state.clear()
        return
    try:
        result = create_teacher_topic_item(
            message.from_user.id,
            int(workspace_id),
            int(topic_id),
            message.text,
        )
    except TeacherContentAccessError:
        await _answer_teacher_content_unavailable(message, message.from_user.id, state)
        return
    except ValueError:
        await message.answer(
            translate_for_user(
                message.from_user.id,
                "teacher.content.prompt.item_text",
            )
        )
        return

    await state.set_state(None)
    await refresh_teacher_topic_editor(
        message,
        message.from_user.id,
        state,
        int(workspace_id),
        int(topic_id),
        selected_item_id=int(result["learning_item_id"]),
        notice_key="teacher.content.item.created",
    )


@router.callback_query(
    lambda callback: callback.data is not None
    and callback.data.startswith(TEACHER_CONTENT_ARCHIVE_PREFIX)
)
async def archive_teacher_item(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None or callback.data is None:
        return
    payload = callback.data.removeprefix(TEACHER_CONTENT_ARCHIVE_PREFIX)
    try:
        workspace_id_text, topic_id_text, item_id_text, page_text = payload.split(":", maxsplit=3)
        archive_teacher_topic_item(
            callback.from_user.id,
            int(workspace_id_text),
            int(topic_id_text),
            int(item_id_text),
        )
        await refresh_teacher_topic_editor(
            callback.message,
            callback.from_user.id,
            state,
            int(workspace_id_text),
            int(topic_id_text),
            page=int(page_text),
            notice_key="teacher.content.item.archived",
        )
    except (TeacherContentAccessError, ValueError):
        await _answer_teacher_content_unavailable(callback.message, callback.from_user.id, state)


@router.callback_query(
    lambda callback: callback.data is not None
    and callback.data.startswith(TEACHER_CONTENT_IMAGE_PREFIX)
)
async def start_teacher_item_image_update(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None or callback.data is None:
        return
    payload = callback.data.removeprefix(TEACHER_CONTENT_IMAGE_PREFIX)
    try:
        workspace_id_text, topic_id_text, item_id_text = payload.split(":", maxsplit=2)
        build_teacher_topic_editor_snapshot(
            callback.from_user.id,
            int(workspace_id_text),
            int(topic_id_text),
            selected_item_id=int(item_id_text),
        )
    except (TeacherContentAccessError, ValueError):
        await _answer_teacher_content_unavailable(callback.message, callback.from_user.id, state)
        return
    await state.update_data(
        workspace_id=int(workspace_id_text),
        topic_id=int(topic_id_text),
        item_id=int(item_id_text),
    )
    await state.set_state(TeacherContentStates.awaiting_item_image_input)
    await callback.message.answer(
        translate_for_user(
            callback.from_user.id,
            "teacher.content.prompt.image_ref",
        )
    )


@router.message(TeacherContentStates.awaiting_item_image_input)
async def save_teacher_item_image_ref(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    data = await state.get_data()
    workspace_id = data.get("workspace_id")
    topic_id = data.get("topic_id")
    item_id = data.get("item_id")
    if None in (workspace_id, topic_id, item_id):
        await state.clear()
        return
    if getattr(message, "photo", None):
        await message.answer(
            translate_for_user(
                message.from_user.id,
                "teacher.content.image.upload_not_supported",
            )
        )
        return
    if message.text is None:
        return
    try:
        update_teacher_topic_item_image_ref(
            message.from_user.id,
            int(workspace_id),
            int(topic_id),
            int(item_id),
            message.text,
        )
    except TeacherContentAccessError:
        await _answer_teacher_content_unavailable(message, message.from_user.id, state)
        return
    except ValueError:
        await message.answer(
            translate_for_user(
                message.from_user.id,
                "teacher.content.prompt.image_ref",
            )
        )
        return

    await state.set_state(None)
    await refresh_teacher_topic_editor(
        message,
        message.from_user.id,
        state,
        int(workspace_id),
        int(topic_id),
        selected_item_id=int(item_id),
        notice_key="teacher.content.image.saved",
    )


@router.callback_query(
    lambda callback: callback.data is not None
    and callback.data.startswith(TEACHER_CONTENT_TOPIC_BACK)
)
async def back_to_teacher_topics(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None or callback.data is None:
        return
    try:
        workspace_id = int(callback.data.removeprefix(TEACHER_CONTENT_TOPIC_BACK))
        topics = list_teacher_workspace_topics(callback.from_user.id, workspace_id)
    except (TeacherContentAccessError, ValueError):
        await _answer_teacher_content_unavailable(callback.message, callback.from_user.id, state)
        return
    await state.update_data(
        workspace_id=workspace_id,
        topic_id=None,
        item_id=None,
        page=0,
        navigator_message_id=None,
        image_message_id=None,
        card_message_id=None,
    )
    await callback.message.answer(
        translate_for_user(
            callback.from_user.id,
            "teacher.content.topics.title",
            workspace_name=_resolve_workspace_name(callback.from_user.id, workspace_id),
        ),
        reply_markup=build_teacher_topics_keyboard(
            callback.from_user.id,
            workspace_id,
            topics,
        ),
    )


@router.callback_query(
    lambda callback: callback.data is not None
    and callback.data.startswith(TEACHER_CONTENT_PUBLISH_PREFIX)
)
async def publish_teacher_topic(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None or callback.data is None:
        return
    payload = callback.data.removeprefix(TEACHER_CONTENT_PUBLISH_PREFIX)
    try:
        workspace_id_text, topic_id_text = payload.split(":", maxsplit=1)
        workspace_id = int(workspace_id_text)
        topic_id = int(topic_id_text)
        targets = list_teacher_publish_targets(callback.from_user.id)
        if not targets:
            await callback.message.answer(
                translate_for_user(
                    callback.from_user.id,
                    "teacher.content.publish.no_targets",
                )
            )
            return
        if len(targets) == 1:
            result = publish_teacher_topic_to_workspace(
                callback.from_user.id,
                workspace_id,
                topic_id,
                int(targets[0]["id"]),
            )
            await refresh_teacher_topic_editor(
                callback.message,
                callback.from_user.id,
                state,
                workspace_id,
                topic_id,
                notice_key="teacher.content.publish.success",
                notice_params={
                    "workspace_name": str(result["target_workspace_name"]),
                    "learning_item_count": int(result["learning_item_count"]),
                },
            )
            return
        await state.update_data(workspace_id=workspace_id, topic_id=topic_id)
        await callback.message.answer(
            translate_for_user(
                callback.from_user.id,
                "teacher.content.publish.choose_target",
            ),
            reply_markup=build_teacher_publish_targets_keyboard(targets),
        )
    except (TeacherContentAccessError, TeacherContentPublishTargetError, ValueError):
        await _answer_teacher_content_unavailable(callback.message, callback.from_user.id, state)


@router.callback_query(
    lambda callback: callback.data is not None
    and callback.data.startswith(TEACHER_CONTENT_PUBLISH_TARGET_PREFIX)
)
async def publish_teacher_topic_to_target(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None or callback.data is None:
        return
    data = await state.get_data()
    workspace_id = data.get("workspace_id")
    topic_id = data.get("topic_id")
    if workspace_id is None or topic_id is None:
        await _answer_teacher_content_unavailable(callback.message, callback.from_user.id, state)
        return
    try:
        target_workspace_id = int(
            callback.data.removeprefix(TEACHER_CONTENT_PUBLISH_TARGET_PREFIX)
        )
        result = publish_teacher_topic_to_workspace(
            callback.from_user.id,
            int(workspace_id),
            int(topic_id),
            target_workspace_id,
        )
        await refresh_teacher_topic_editor(
            callback.message,
            callback.from_user.id,
            state,
            int(workspace_id),
            int(topic_id),
            notice_key="teacher.content.publish.success",
            notice_params={
                "workspace_name": str(result["target_workspace_name"]),
                "learning_item_count": int(result["learning_item_count"]),
            },
        )
    except (TeacherContentAccessError, TeacherContentPublishTargetError, ValueError):
        await _answer_teacher_content_unavailable(callback.message, callback.from_user.id, state)


async def refresh_teacher_topic_editor(
    anchor_message: Message,
    telegram_user_id: int,
    state: FSMContext,
    workspace_id: int,
    topic_id: int,
    *,
    selected_item_id: int | None = None,
    page: int = 0,
    notice_key: str | None = None,
    notice_params: dict[str, object] | None = None,
) -> None:
    snapshot = build_teacher_topic_editor_snapshot(
        telegram_user_id,
        workspace_id,
        topic_id,
        selected_item_id=selected_item_id,
        page=page,
    )
    stored = await state.get_data()
    navigator_message_id = await _render_or_replace_message(
        anchor_message,
        stored.get("navigator_message_id"),
        _format_teacher_topic_navigator(telegram_user_id, snapshot),
        _build_teacher_topic_navigator_keyboard(telegram_user_id, snapshot),
    )
    image_message_id = await _render_or_replace_message(
        anchor_message,
        stored.get("image_message_id"),
        _format_teacher_topic_image(telegram_user_id, snapshot),
        _build_teacher_topic_image_keyboard(telegram_user_id, snapshot),
    )
    card_message_id = await _render_or_replace_message(
        anchor_message,
        stored.get("card_message_id"),
        _format_teacher_topic_card(telegram_user_id, snapshot),
        _build_teacher_topic_card_keyboard(telegram_user_id, snapshot),
    )
    await state.update_data(
        workspace_id=int(snapshot["workspace_id"]),
        topic_id=int(snapshot["topic_id"]),
        item_id=snapshot["selected_item_id"],
        page=int(snapshot["page"]),
        navigator_message_id=navigator_message_id,
        image_message_id=image_message_id,
        card_message_id=card_message_id,
    )
    if notice_key is not None:
        await anchor_message.answer(
            translate_for_user(
                telegram_user_id,
                notice_key,
                **(notice_params or {}),
            )
        )


async def _render_teacher_workspaces(message: Message, telegram_user_id: int) -> None:
    workspaces = list_teacher_browsable_workspaces(telegram_user_id)
    if not workspaces:
        await message.answer(
            translate_for_user(
                telegram_user_id,
                "teacher.content.workspaces.empty",
            ),
            reply_markup=build_teacher_workspaces_keyboard(telegram_user_id, []),
        )
        return
    await message.answer(
        translate_for_user(
            telegram_user_id,
            "teacher.content.workspaces.title",
        ),
        reply_markup=build_teacher_workspaces_keyboard(telegram_user_id, workspaces),
    )


async def _render_or_replace_message(
    anchor_message: Message,
    existing_message_id: int | None,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
) -> int:
    if existing_message_id is not None:
        try:
            await anchor_message.bot.edit_message_text(
                chat_id=anchor_message.chat.id,
                message_id=int(existing_message_id),
                text=text,
                reply_markup=reply_markup,
            )
            return int(existing_message_id)
        except Exception:
            pass
    sent_message = await anchor_message.answer(text, reply_markup=reply_markup)
    return int(sent_message.message_id)


async def _answer_teacher_content_unavailable(
    message: Message,
    telegram_user_id: int,
    state: FSMContext,
) -> None:
    await state.clear()
    await message.answer(
        translate_for_user(telegram_user_id, "teacher.content.unavailable")
    )


def _build_teacher_topic_navigator_keyboard(
    telegram_user_id: int,
    snapshot: dict[str, object],
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=(
                    f"> {item['label']}"
                    if item["is_selected"]
                    else str(item["label"])
                ),
                callback_data=(
                    f"{TEACHER_CONTENT_ITEM_PREFIX}"
                    f"{snapshot['workspace_id']}:{snapshot['topic_id']}:{item['id']}"
                ),
            )
        ]
        for item in snapshot["navigator_items"]
    ]
    page_buttons: list[InlineKeyboardButton] = []
    if snapshot["has_prev_page"]:
        page_buttons.append(
            InlineKeyboardButton(
                text=translate_for_user(
                    telegram_user_id,
                    "teacher.content.action.page_prev",
                ),
                callback_data=(
                    f"{TEACHER_CONTENT_PAGE_PREFIX}"
                    f"{snapshot['workspace_id']}:{snapshot['topic_id']}:{int(snapshot['page']) - 1}"
                ),
            )
        )
    if snapshot["has_next_page"]:
        page_buttons.append(
            InlineKeyboardButton(
                text=translate_for_user(
                    telegram_user_id,
                    "teacher.content.action.page_next",
                ),
                callback_data=(
                    f"{TEACHER_CONTENT_PAGE_PREFIX}"
                    f"{snapshot['workspace_id']}:{snapshot['topic_id']}:{int(snapshot['page']) + 1}"
                ),
            )
        )
    if page_buttons:
        rows.append(page_buttons)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _build_teacher_topic_image_keyboard(
    telegram_user_id: int,
    snapshot: dict[str, object],
) -> InlineKeyboardMarkup:
    current_item = snapshot["current_item"]
    if current_item is None:
        return InlineKeyboardMarkup(inline_keyboard=[])
    callback_data = (
        f"{TEACHER_CONTENT_IMAGE_PREFIX}"
        f"{snapshot['workspace_id']}:{snapshot['topic_id']}:{current_item['id']}"
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=translate_for_user(
                        telegram_user_id,
                        "teacher.content.action.set_image",
                    ),
                    callback_data=callback_data,
                )
            ]
        ]
    )


def _build_teacher_topic_card_keyboard(
    telegram_user_id: int,
    snapshot: dict[str, object],
) -> InlineKeyboardMarkup:
    current_item = snapshot["current_item"]
    rows: list[list[InlineKeyboardButton]] = []
    navigation_buttons: list[InlineKeyboardButton] = []
    if snapshot["prev_item_id"] is not None:
        navigation_buttons.append(
            InlineKeyboardButton(
                text=translate_for_user(
                    telegram_user_id,
                    "teacher.content.action.previous_item",
                ),
                callback_data=(
                    f"{TEACHER_CONTENT_ITEM_PREFIX}"
                    f"{snapshot['workspace_id']}:{snapshot['topic_id']}:{snapshot['prev_item_id']}"
                ),
            )
        )
    if snapshot["next_item_id"] is not None:
        navigation_buttons.append(
            InlineKeyboardButton(
                text=translate_for_user(
                    telegram_user_id,
                    "teacher.content.action.next_item",
                ),
                callback_data=(
                    f"{TEACHER_CONTENT_ITEM_PREFIX}"
                    f"{snapshot['workspace_id']}:{snapshot['topic_id']}:{snapshot['next_item_id']}"
                ),
            )
        )
    if navigation_buttons:
        rows.append(navigation_buttons)
    if current_item is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    text=translate_for_user(
                        telegram_user_id,
                        "teacher.content.action.edit_item",
                    ),
                    callback_data=(
                        f"{TEACHER_CONTENT_EDIT_PREFIX}"
                        f"{snapshot['workspace_id']}:{snapshot['topic_id']}:{current_item['id']}"
                    ),
                ),
                InlineKeyboardButton(
                    text=translate_for_user(
                        telegram_user_id,
                        "teacher.content.action.archive_item",
                    ),
                    callback_data=(
                        f"{TEACHER_CONTENT_ARCHIVE_PREFIX}"
                        f"{snapshot['workspace_id']}:{snapshot['topic_id']}:"
                        f"{current_item['id']}:{snapshot['page']}"
                    ),
                ),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=translate_for_user(
                    telegram_user_id,
                    "teacher.content.action.add_item",
                ),
                callback_data=(
                    f"{TEACHER_CONTENT_ADD_ITEM_PREFIX}"
                    f"{snapshot['workspace_id']}:{snapshot['topic_id']}:{snapshot['page']}"
                ),
            ),
            InlineKeyboardButton(
                text=translate_for_user(
                    telegram_user_id,
                    "teacher.content.action.publish_topic",
                ),
                callback_data=(
                    f"{TEACHER_CONTENT_PUBLISH_PREFIX}"
                    f"{snapshot['workspace_id']}:{snapshot['topic_id']}"
                ),
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=translate_for_user(
                    telegram_user_id,
                    "teacher.content.action.back_to_topics",
                ),
                callback_data=f"{TEACHER_CONTENT_TOPIC_BACK}{snapshot['workspace_id']}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_teacher_topic_navigator(
    telegram_user_id: int,
    snapshot: dict[str, object],
) -> str:
    lines = [
        translate_for_user(
            telegram_user_id,
            "teacher.content.editor.navigator.title",
            topic_title=str(snapshot["topic_title"]),
        ),
        translate_for_user(
            telegram_user_id,
            "teacher.content.editor.navigator.page",
            current_page=int(snapshot["page"]) + 1,
            page_count=int(snapshot["page_count"]),
            item_count=int(snapshot["item_count"]),
        ),
    ]
    if not snapshot["navigator_items"]:
        lines.append(
            translate_for_user(
                telegram_user_id,
                "teacher.content.topic.empty",
            )
        )
    return "\n".join(lines)


def _format_teacher_topic_image(
    telegram_user_id: int,
    snapshot: dict[str, object],
) -> str:
    current_item = snapshot["current_item"]
    if current_item is None or current_item["image_ref"] is None:
        return translate_for_user(
            telegram_user_id,
            "teacher.content.editor.image.empty",
        )
    return translate_for_user(
        telegram_user_id,
        "teacher.content.editor.image.value",
        image_ref=str(current_item["image_ref"]),
    )


def _format_teacher_topic_card(
    telegram_user_id: int,
    snapshot: dict[str, object],
) -> str:
    current_item = snapshot["current_item"]
    if current_item is None:
        return "\n".join(
            [
                str(snapshot["topic_title"]),
                translate_for_user(
                    telegram_user_id,
                    "teacher.content.editor.card.empty",
                ),
            ]
        )
    translations = current_item["translations"]
    item_number = int(snapshot["selected_item_index"]) + 1
    return "\n".join(
        [
            str(snapshot["topic_title"]),
            translate_for_user(
                telegram_user_id,
                "teacher.content.editor.card.position",
                item_number=item_number,
                item_count=int(snapshot["item_count"]),
            ),
            translate_for_user(
                telegram_user_id,
                "teacher.content.editor.card.headword",
                value=str(current_item["headword"]),
            ),
            translate_for_user(
                telegram_user_id,
                "teacher.content.editor.card.text",
                value=str(current_item["text"]),
            ),
            translate_for_user(
                telegram_user_id,
                "teacher.content.editor.card.translation",
                label="RU",
                value=str(translations["ru"] or "-"),
            ),
            translate_for_user(
                telegram_user_id,
                "teacher.content.editor.card.translation",
                label="UK",
                value=str(translations["uk"] or "-"),
            ),
            translate_for_user(
                telegram_user_id,
                "teacher.content.editor.card.translation",
                label="BG",
                value=str(translations["bg"] or "-"),
            ),
            translate_for_user(
                telegram_user_id,
                "teacher.content.editor.card.image_ref",
                value=str(current_item["image_ref"] or "-"),
            ),
            translate_for_user(
                telegram_user_id,
                "teacher.content.editor.card.audio_ref",
                value=str(current_item["audio_ref"] or "-"),
            ),
            translate_for_user(
                telegram_user_id,
                "teacher.content.editor.card.archive_status",
                value=translate_for_user(
                    telegram_user_id,
                    (
                        "teacher.content.archive_status.archived"
                        if current_item["is_archived"]
                        else "teacher.content.archive_status.active"
                    ),
                ),
            ),
        ]
    )


def _resolve_workspace_name(telegram_user_id: int, workspace_id: int) -> str:
    for workspace in list_teacher_browsable_workspaces(telegram_user_id):
        if int(workspace["id"]) == workspace_id:
            return str(workspace["name"])
    return str(workspace_id)
