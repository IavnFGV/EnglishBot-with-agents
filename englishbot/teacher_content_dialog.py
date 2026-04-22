from __future__ import annotations

from enum import StrEnum
from html import escape
from io import BytesIO
from pathlib import Path

from aiogram import F
from aiogram.enums import ContentType
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram_dialog import Dialog, DialogManager, ShowMode, StartMode, Window
from aiogram_dialog.api.entities.media import MediaAttachment
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Column, Row, ScrollingGroup, Select
from aiogram_dialog.widgets.media import DynamicMedia
from aiogram_dialog.widgets.text import Format

from .command_registry import TEACHER_CONTENT_COMMAND
from .assets import NO_IMAGE_PLACEHOLDER_PATH, store_teacher_content_image, store_teacher_content_image_from_url
from .db import save_user
from .i18n import translate_for_user
from .runtime import router
from .teacher_content import (
    TeacherContentAccessError,
    TeacherContentPublishTargetError,
    archive_teacher_topic_item,
    build_teacher_topic_full_list_overview,
    build_teacher_topic_editor_snapshot,
    create_teacher_topic,
    create_teacher_topic_item,
    create_teacher_workspace_for_user,
    list_teacher_browsable_workspaces,
    list_teacher_publish_targets,
    list_teacher_workspace_topics,
    publish_teacher_topic_to_workspace,
    update_teacher_topic_item_field,
)

LIST_PAGE_SIZE = 8
TRANSLATION_LANGUAGE_CODES = ("ru", "uk", "bg")
EDITABLE_FIELDS = ("text", "ru", "uk", "bg", "image_ref", "audio_ref")
SHOW_ALL_HIDE_CALLBACK = "teacher_content:hide_show_all"


class TeacherContentDialogSG(StatesGroup):
    workspaces = State()
    topics = State()
    browser = State()
    prompt = State()
    publish = State()


class PromptKind(StrEnum):
    CREATE_WORKSPACE = "create_workspace"
    CREATE_TOPIC = "create_topic"
    CREATE_ITEM = "create_item"
    EDIT_FIELD = "edit_field"


async def start_teacher_content_dialog(message: Message, dialog_manager: DialogManager) -> None:
    if message.from_user is None:
        return
    save_user(message.from_user)
    await dialog_manager.start(
        TeacherContentDialogSG.workspaces,
        mode=StartMode.RESET_STACK,
    )


@router.message(Command(TEACHER_CONTENT_COMMAND.name))
async def teacher_content_command(message: Message, dialog_manager: DialogManager) -> None:
    if message.from_user is None:
        return
    save_user(message.from_user)
    from .user_profiles import get_user_role

    if get_user_role(message.from_user.id) != "teacher":
        await message.answer(
            translate_for_user(
                message.from_user.id,
                "teacher.command_teacher_only",
                command=TEACHER_CONTENT_COMMAND.token,
            )
        )
        return
    await start_teacher_content_dialog(message, dialog_manager)


async def _on_workspace_selected(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    workspace_id: str,
) -> None:
    user_id = _get_user_id(dialog_manager)
    try:
        list_teacher_workspace_topics(user_id, int(workspace_id))
    except TeacherContentAccessError:
        await _handle_unavailable(dialog_manager)
        return
    await _reset_prompt_state(dialog_manager)
    dialog_manager.dialog_data["workspace_id"] = int(workspace_id)
    dialog_manager.dialog_data["workspace_page"] = 0
    dialog_manager.dialog_data["topic_page"] = 0
    dialog_manager.dialog_data.pop("topic_id", None)
    dialog_manager.dialog_data.pop("item_id", None)
    await dialog_manager.switch_to(TeacherContentDialogSG.topics)


async def _on_topic_selected(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    topic_id: str,
) -> None:
    await _reset_prompt_state(dialog_manager)
    dialog_manager.dialog_data["topic_id"] = int(topic_id)
    try:
        snapshot = _load_browser_snapshot(dialog_manager)
    except TeacherContentAccessError:
        await _handle_unavailable(dialog_manager)
        return
    dialog_manager.dialog_data["item_id"] = snapshot.get("selected_item_id")
    await _show_browser_with_overview(dialog_manager, callback.message)


async def _on_publish_target_selected(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    target_workspace_id: str,
) -> None:
    user_id = _get_user_id(dialog_manager)
    workspace_id = int(dialog_manager.dialog_data["workspace_id"])
    topic_id = int(dialog_manager.dialog_data["topic_id"])
    try:
        result = publish_teacher_topic_to_workspace(
            user_id,
            workspace_id,
            topic_id,
            int(target_workspace_id),
        )
    except (TeacherContentAccessError, TeacherContentPublishTargetError, ValueError):
        await _handle_unavailable(dialog_manager)
        return
    dialog_manager.dialog_data["status_text"] = translate_for_user(
        user_id,
        "teacher.content.publish.success",
        workspace_name=result["target_workspace_name"],
        learning_item_count=result["learning_item_count"],
    )
    await dialog_manager.switch_to(TeacherContentDialogSG.browser)


async def _open_create_workspace(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    await _enter_prompt(dialog_manager, PromptKind.CREATE_WORKSPACE)


async def _open_create_topic(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    await _enter_prompt(dialog_manager, PromptKind.CREATE_TOPIC)


async def _open_create_item(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    await _enter_prompt(dialog_manager, PromptKind.CREATE_ITEM)


async def _open_edit_prompt(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    await _enter_prompt(dialog_manager, PromptKind.EDIT_FIELD)


async def _open_publish_targets(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    await _reset_prompt_state(dialog_manager)
    await dialog_manager.switch_to(TeacherContentDialogSG.publish)


async def _go_to_browser(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    await _reset_prompt_state(dialog_manager)
    await dialog_manager.switch_to(TeacherContentDialogSG.browser)


async def _go_to_topics(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    await _delete_browser_overview_message(dialog_manager, callback.message)
    await _reset_prompt_state(dialog_manager)
    await dialog_manager.switch_to(TeacherContentDialogSG.topics)


async def _go_to_workspaces(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    await _delete_browser_overview_message(dialog_manager, callback.message)
    await _reset_prompt_state(dialog_manager)
    await dialog_manager.switch_to(TeacherContentDialogSG.workspaces)


async def _go_to_prompt_return(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    prompt_kind = _get_prompt_kind(dialog_manager)
    await _reset_prompt_state(dialog_manager)
    if prompt_kind == PromptKind.CREATE_TOPIC:
        await dialog_manager.switch_to(TeacherContentDialogSG.topics)
        return
    if prompt_kind in {PromptKind.CREATE_ITEM, PromptKind.EDIT_FIELD}:
        await _sync_browser_overview_message(dialog_manager, callback.message)
        await dialog_manager.switch_to(TeacherContentDialogSG.browser)
        return
    await dialog_manager.switch_to(TeacherContentDialogSG.workspaces)


async def _choose_field(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    field_name: str,
) -> None:
    dialog_manager.dialog_data["edit_field"] = field_name
    dialog_manager.dialog_data.pop("prompt_error", None)
    await dialog_manager.update({})


async def _prev_list_page(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    page_key = str(button.widget_id)
    current_page = int(dialog_manager.dialog_data.get(page_key, 0))
    dialog_manager.dialog_data[page_key] = max(current_page - 1, 0)
    await dialog_manager.update({})


async def _next_list_page(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    page_key = str(button.widget_id)
    current_page = int(dialog_manager.dialog_data.get(page_key, 0))
    dialog_manager.dialog_data[page_key] = current_page + 1
    await dialog_manager.update({})


async def _prev_item(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    snapshot = _load_browser_snapshot(dialog_manager)
    previous_item_id = snapshot.get("prev_item_id")
    if previous_item_id is None:
        return
    dialog_manager.dialog_data["item_id"] = previous_item_id
    dialog_manager.dialog_data.pop("status_text", None)
    await _sync_browser_overview_message(dialog_manager, callback.message)
    await dialog_manager.update({})


async def _next_item(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    snapshot = _load_browser_snapshot(dialog_manager)
    next_item_id = snapshot.get("next_item_id")
    if next_item_id is None:
        return
    dialog_manager.dialog_data["item_id"] = next_item_id
    dialog_manager.dialog_data.pop("status_text", None)
    await _sync_browser_overview_message(dialog_manager, callback.message)
    await dialog_manager.update({})


async def _archive_item(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    user_id = _get_user_id(dialog_manager)
    snapshot = _load_browser_snapshot(dialog_manager)
    selected_item_id = snapshot.get("selected_item_id")
    if selected_item_id is None:
        return
    try:
        archive_teacher_topic_item(
            user_id,
            int(dialog_manager.dialog_data["workspace_id"]),
            int(dialog_manager.dialog_data["topic_id"]),
            int(selected_item_id),
        )
    except TeacherContentAccessError:
        await _handle_unavailable(dialog_manager)
        return
    updated_snapshot = _load_browser_snapshot(dialog_manager)
    dialog_manager.dialog_data["item_id"] = updated_snapshot.get("selected_item_id")
    dialog_manager.dialog_data["status_text"] = translate_for_user(
        user_id,
        "teacher.content.item.archived",
    )
    await _sync_browser_overview_message(dialog_manager, callback.message)
    await dialog_manager.update({})


async def _show_all_items(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    user_id = _get_user_id(dialog_manager)
    try:
        overview = build_teacher_topic_full_list_overview(
            user_id,
            int(dialog_manager.dialog_data["workspace_id"]),
            int(dialog_manager.dialog_data["topic_id"]),
        )
        snapshot = _load_browser_snapshot(dialog_manager)
    except TeacherContentAccessError:
        await _handle_unavailable(dialog_manager)
        return
    if not snapshot.get("show_all_available"):
        return
    if callback.message is None:
        return
    await callback.message.answer(
        _build_full_list_message_text(
            user_id=user_id,
            overview=overview,
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=translate_for_user(user_id, "teacher.content.action.ok"),
                        callback_data=SHOW_ALL_HIDE_CALLBACK,
                    )
                ]
            ]
        ),
    )


@router.callback_query(F.data == SHOW_ALL_HIDE_CALLBACK)
async def hide_show_all_message(callback: CallbackQuery) -> None:
    if callback.message is not None:
        await callback.message.delete()
    await callback.answer()


async def _on_prompt_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
) -> None:
    user_id = _get_user_id(dialog_manager)
    prompt_kind = _get_prompt_kind(dialog_manager)
    if prompt_kind is None:
        return
    if prompt_kind == PromptKind.EDIT_FIELD and dialog_manager.dialog_data.get("edit_field") is None:
        return
    if prompt_kind == PromptKind.EDIT_FIELD and message.photo:
        field_name = str(dialog_manager.dialog_data["edit_field"])
        if field_name != "image_ref":
            dialog_manager.dialog_data["prompt_error"] = translate_for_user(
                user_id,
                "teacher.content.image.upload_not_supported",
            )
            await dialog_manager.update({})
            return
        buffer = BytesIO()
        await message.bot.download(message.photo[-1], destination=buffer)
        image_ref = store_teacher_content_image(
            int(dialog_manager.dialog_data["item_id"]),
            buffer.getvalue(),
        )
        update_teacher_topic_item_field(
            user_id,
            int(dialog_manager.dialog_data["workspace_id"]),
            int(dialog_manager.dialog_data["topic_id"]),
            int(dialog_manager.dialog_data["item_id"]),
            field_name,
            image_ref,
        )
        dialog_manager.dialog_data["status_text"] = translate_for_user(
            user_id,
            "teacher.content.image.saved",
        )
        await _reset_prompt_state(dialog_manager)
        await _sync_browser_overview_message(dialog_manager, message)
        await dialog_manager.switch_to(TeacherContentDialogSG.browser, show_mode=ShowMode.EDIT)
        await _delete_user_message(message)
        return
    if message.text is None:
        return

    try:
        if prompt_kind == PromptKind.CREATE_WORKSPACE:
            workspace = create_teacher_workspace_for_user(user_id, message.text)
            dialog_manager.dialog_data["status_text"] = translate_for_user(
                user_id,
                "teacher.content.workspace.created",
                workspace_name=workspace["name"],
            )
            dialog_manager.dialog_data["workspace_id"] = workspace["id"]
            dialog_manager.dialog_data["workspace_page"] = 0
            await _reset_prompt_state(dialog_manager)
            await dialog_manager.switch_to(TeacherContentDialogSG.workspaces)
            return
        if prompt_kind == PromptKind.CREATE_TOPIC:
            topic = create_teacher_topic(
                user_id,
                int(dialog_manager.dialog_data["workspace_id"]),
                message.text,
            )
            dialog_manager.dialog_data["status_text"] = translate_for_user(
                user_id,
                "teacher.content.topic.created",
                topic_title=topic["title"],
            )
            dialog_manager.dialog_data["topic_id"] = topic["id"]
            dialog_manager.dialog_data["item_id"] = None
            await _reset_prompt_state(dialog_manager)
            await _show_browser_with_overview(dialog_manager, message)
            return
        if prompt_kind == PromptKind.CREATE_ITEM:
            item = create_teacher_topic_item(
                user_id,
                int(dialog_manager.dialog_data["workspace_id"]),
                int(dialog_manager.dialog_data["topic_id"]),
                message.text,
            )
            dialog_manager.dialog_data["status_text"] = translate_for_user(
                user_id,
                "teacher.content.item.created",
            )
            dialog_manager.dialog_data["item_id"] = int(item["learning_item_id"])
            await _reset_prompt_state(dialog_manager)
            await _sync_browser_overview_message(dialog_manager, message)
            await dialog_manager.switch_to(TeacherContentDialogSG.browser, show_mode=ShowMode.EDIT)
            return
        if prompt_kind == PromptKind.EDIT_FIELD:
            field_name = str(dialog_manager.dialog_data["edit_field"])
            value = message.text
            if field_name == "image_ref" and value.startswith(("http://", "https://")):
                value = store_teacher_content_image_from_url(
                    int(dialog_manager.dialog_data["item_id"]),
                    value,
                )
            update_teacher_topic_item_field(
                user_id,
                int(dialog_manager.dialog_data["workspace_id"]),
                int(dialog_manager.dialog_data["topic_id"]),
                int(dialog_manager.dialog_data["item_id"]),
                field_name,
                value,
            )
            dialog_manager.dialog_data["status_text"] = translate_for_user(
                user_id,
                "teacher.content.item.saved",
            )
            await _reset_prompt_state(dialog_manager)
            await _sync_browser_overview_message(dialog_manager, message)
            await dialog_manager.switch_to(TeacherContentDialogSG.browser, show_mode=ShowMode.EDIT)
            if field_name == "image_ref":
                await _delete_user_message(message)
            return
    except TeacherContentAccessError:
        await _handle_unavailable(dialog_manager)
        return
    except ValueError:
        dialog_manager.dialog_data["prompt_error"] = translate_for_user(
            user_id,
            "teacher.content.validation.required",
        )
        await dialog_manager.update({})


async def get_workspaces_window_data(
    dialog_manager: DialogManager,
    **_: object,
) -> dict[str, object]:
    user_id = _get_user_id(dialog_manager)
    workspaces = list_teacher_browsable_workspaces(user_id)
    page = _clamp_list_page(dialog_manager, "workspace_page", len(workspaces))
    page_items = _slice_page(workspaces, page)
    return {
        "screen_text": _build_workspace_screen_text(
            user_id=user_id,
            workspaces=page_items,
            total_count=len(workspaces),
            current_page=page,
            status_text=_get_status_text(dialog_manager),
        ),
        "workspace_items": page_items,
        "create_label": translate_for_user(user_id, "teacher.content.action.create"),
        "cancel_label": translate_for_user(user_id, "teacher.content.action.cancel"),
        "prev_label": translate_for_user(user_id, "teacher.content.action.prev"),
        "next_label": translate_for_user(user_id, "teacher.content.action.next"),
        "has_prev_page": page > 0,
        "has_next_page": (page + 1) * LIST_PAGE_SIZE < len(workspaces),
    }


async def get_topics_window_data(
    dialog_manager: DialogManager,
    **_: object,
) -> dict[str, object]:
    user_id = _get_user_id(dialog_manager)
    workspace_id = dialog_manager.dialog_data.get("workspace_id")
    if workspace_id is None:
        return await get_workspaces_window_data(dialog_manager)
    try:
        topics = list_teacher_workspace_topics(user_id, int(workspace_id))
        workspace_name = _get_workspace_name(user_id, int(workspace_id))
    except TeacherContentAccessError:
        return _build_unavailable_view(user_id)
    page = _clamp_list_page(dialog_manager, "topic_page", len(topics))
    page_items = _slice_page(topics, page)
    return {
        "screen_text": _build_topics_screen_text(
            user_id=user_id,
            workspace_name=workspace_name,
            topics=page_items,
            total_count=len(topics),
            current_page=page,
            status_text=_get_status_text(dialog_manager),
        ),
        "topic_items": page_items,
        "create_label": translate_for_user(user_id, "teacher.content.action.create"),
        "back_label": translate_for_user(user_id, "teacher.content.action.back"),
        "cancel_label": translate_for_user(user_id, "teacher.content.action.cancel"),
        "prev_label": translate_for_user(user_id, "teacher.content.action.prev"),
        "next_label": translate_for_user(user_id, "teacher.content.action.next"),
        "has_prev_page": page > 0,
        "has_next_page": (page + 1) * LIST_PAGE_SIZE < len(topics),
    }


async def get_browser_window_data(
    dialog_manager: DialogManager,
    **_: object,
) -> dict[str, object]:
    user_id = _get_user_id(dialog_manager)
    try:
        snapshot = _load_browser_snapshot(dialog_manager)
    except TeacherContentAccessError:
        return _build_unavailable_view(user_id)
    current_item = snapshot.get("current_item")
    return {
        "screen_text": _build_browser_screen_text(
            user_id=user_id,
            snapshot=snapshot,
            status_text=_get_status_text(dialog_manager),
        ),
        "current_item_media": _build_current_item_media(snapshot),
        "prev_label": translate_for_user(user_id, "teacher.content.action.prev"),
        "next_label": translate_for_user(user_id, "teacher.content.action.next"),
        "edit_label": translate_for_user(user_id, "teacher.content.action.edit"),
        "archive_label": translate_for_user(user_id, "teacher.content.action.archive"),
        "create_label": translate_for_user(user_id, "teacher.content.action.create"),
        "publish_label": translate_for_user(user_id, "teacher.content.action.publish"),
        "show_all_label": translate_for_user(user_id, "teacher.content.action.show_all"),
        "topics_label": translate_for_user(user_id, "teacher.content.action.topics"),
        "workspaces_label": translate_for_user(user_id, "teacher.content.action.workspaces"),
        "cancel_label": translate_for_user(user_id, "teacher.content.action.cancel"),
        "has_prev_item": snapshot.get("prev_item_id") is not None,
        "has_next_item": snapshot.get("next_item_id") is not None,
        "has_current_item": current_item is not None,
        "has_current_image": _current_item_has_real_image(snapshot),
        "show_all_available": bool(snapshot.get("show_all_available")),
    }


async def get_prompt_window_data(
    dialog_manager: DialogManager,
    **_: object,
) -> dict[str, object]:
    user_id = _get_user_id(dialog_manager)
    prompt_kind = _get_prompt_kind(dialog_manager)
    if prompt_kind is None:
        return _build_unavailable_view(user_id)
    edit_field = dialog_manager.dialog_data.get("edit_field")
    field_name = (
        translate_for_user(user_id, f"teacher.content.field.{edit_field}")
        if edit_field is not None
        else ""
    )
    prompt_key = (
        (
            "teacher.content.prompt.image_ref"
            if edit_field == "image_ref"
            else "teacher.content.prompt.field_value"
        )
        if prompt_kind == PromptKind.EDIT_FIELD and edit_field is not None
        else {
            PromptKind.CREATE_WORKSPACE: "teacher.content.prompt.workspace_name",
            PromptKind.CREATE_TOPIC: "teacher.content.prompt.topic_title",
            PromptKind.CREATE_ITEM: "teacher.content.prompt.item_text",
            PromptKind.EDIT_FIELD: "teacher.content.prompt.edit_field",
        }[prompt_kind]
    )
    lines = [translate_for_user(user_id, prompt_key, field_name=field_name)]
    prompt_error = dialog_manager.dialog_data.get("prompt_error")
    if prompt_error:
        lines.extend(("", str(prompt_error)))
    return {
        "screen_text": "\n".join(lines),
        "back_label": translate_for_user(user_id, "teacher.content.action.back"),
        "cancel_label": translate_for_user(user_id, "teacher.content.action.cancel"),
        "field_items": [
            {
                "id": field_name,
                "label": translate_for_user(user_id, f"teacher.content.field.{field_name}"),
            }
            for field_name in EDITABLE_FIELDS
        ],
        "show_field_picker": prompt_kind == PromptKind.EDIT_FIELD and edit_field is None,
    }


async def get_publish_window_data(
    dialog_manager: DialogManager,
    **_: object,
) -> dict[str, object]:
    user_id = _get_user_id(dialog_manager)
    try:
        targets = list_teacher_publish_targets(user_id)
    except TeacherContentAccessError:
        return _build_unavailable_view(user_id)
    return {
        "screen_text": _build_publish_screen_text(
            user_id=user_id,
            targets=targets,
            status_text=_get_status_text(dialog_manager),
        ),
        "target_items": targets,
        "back_label": translate_for_user(user_id, "teacher.content.action.back"),
        "cancel_label": translate_for_user(user_id, "teacher.content.action.cancel"),
    }


def _load_browser_snapshot(dialog_manager: DialogManager) -> dict[str, object]:
    user_id = _get_user_id(dialog_manager)
    snapshot = build_teacher_topic_editor_snapshot(
        user_id,
        int(dialog_manager.dialog_data["workspace_id"]),
        int(dialog_manager.dialog_data["topic_id"]),
        selected_item_id=dialog_manager.dialog_data.get("item_id"),
    )
    dialog_manager.dialog_data["item_id"] = snapshot.get("selected_item_id")
    return snapshot


def _build_workspace_screen_text(
    *,
    user_id: int,
    workspaces: list[dict[str, object]],
    total_count: int,
    current_page: int,
    status_text: str | None,
) -> str:
    lines = [translate_for_user(user_id, "teacher.content.screen.workspaces")]
    if status_text:
        lines.extend(("", status_text))
    lines.append(
        translate_for_user(
            user_id,
            "teacher.content.list.position",
            current_page=current_page + 1,
            total_pages=_list_page_count(total_count),
            total_items=total_count,
        )
    )
    if not workspaces:
        lines.append(translate_for_user(user_id, "teacher.content.workspaces.empty"))
        return "\n".join(lines)
    for index, workspace in enumerate(workspaces, start=current_page * LIST_PAGE_SIZE + 1):
        lines.append(f"{index}. {workspace['name']}")
    return "\n".join(lines)


def _build_topics_screen_text(
    *,
    user_id: int,
    workspace_name: str,
    topics: list[dict[str, object]],
    total_count: int,
    current_page: int,
    status_text: str | None,
) -> str:
    lines = [
        translate_for_user(
            user_id,
            "teacher.content.screen.topics",
            workspace_name=workspace_name,
        )
    ]
    if status_text:
        lines.extend(("", status_text))
    lines.append(
        translate_for_user(
            user_id,
            "teacher.content.list.position",
            current_page=current_page + 1,
            total_pages=_list_page_count(total_count),
            total_items=total_count,
        )
    )
    if not topics:
        lines.append(translate_for_user(user_id, "teacher.content.topics.empty"))
        return "\n".join(lines)
    for index, topic in enumerate(topics, start=current_page * LIST_PAGE_SIZE + 1):
        lines.append(f"{index}. {topic['title']} ({topic['item_count']})")
    return "\n".join(lines)


def _build_browser_screen_text(
    *,
    user_id: int,
    snapshot: dict[str, object],
    status_text: str | None,
) -> str:
    lines = [
        translate_for_user(
            user_id,
            "teacher.content.screen.browser",
            topic_title=str(snapshot["topic_title"]),
        )
    ]
    if status_text:
        lines.extend(("", status_text))
    current_item = snapshot.get("current_item")
    if current_item is None:
        lines.extend(
            (
                "",
                translate_for_user(
                    user_id,
                    "teacher.content.browser.position.empty",
                    item_count=int(snapshot["item_count"]),
                ),
                translate_for_user(user_id, "teacher.content.topic.empty"),
            )
        )
        return "\n".join(lines)

    lines.extend(
        (
            "",
            translate_for_user(
                user_id,
                "teacher.content.browser.position",
                item_number=int(snapshot["selected_item_index"] or 0) + 1,
                item_count=int(snapshot["item_count"]),
            ),
            translate_for_user(
                user_id,
                "teacher.content.browser.text",
                value=str(current_item["text"]),
            ),
        )
    )
    for language_code in TRANSLATION_LANGUAGE_CODES:
        lines.append(
            translate_for_user(
                user_id,
                "teacher.content.browser.translation",
                label=language_code,
                value=str(current_item["translations"].get(language_code) or "-"),
            )
        )
    return "\n".join(lines)


def _build_full_list_message_text(
    *,
    user_id: int,
    overview: dict[str, object],
) -> str:
    lines = [
        translate_for_user(
            user_id,
            "teacher.content.full_list.title",
            topic_title=str(overview["topic_title"]),
        ),
        translate_for_user(
            user_id,
            "teacher.content.full_list.count",
            item_count=int(overview["item_count"]),
        ),
        "",
    ]
    for row in overview["rows"]:
        lines.append(
            translate_for_user(
                user_id,
                (
                    "teacher.content.full_list.row.with_image"
                    if bool(row["has_image"])
                    else "teacher.content.full_list.row.no_image"
                ),
                headword=str(row["headword"]),
            )
        )
    return "\n".join(lines)


def _build_publish_screen_text(
    *,
    user_id: int,
    targets: list[dict[str, object]],
    status_text: str | None,
) -> str:
    lines = [translate_for_user(user_id, "teacher.content.screen.publish")]
    if status_text:
        lines.extend(("", status_text))
    if not targets:
        lines.extend(("", translate_for_user(user_id, "teacher.content.publish.no_targets")))
        return "\n".join(lines)
    lines.extend(("", translate_for_user(user_id, "teacher.content.publish.choose_target")))
    for index, target in enumerate(targets, start=1):
        lines.append(f"{index}. {target['name']}")
    return "\n".join(lines)


def _build_unavailable_view(user_id: int) -> dict[str, object]:
    return {
        "screen_text": translate_for_user(user_id, "teacher.content.unavailable"),
        "current_item_media": None,
        "workspace_items": [],
        "topic_items": [],
        "target_items": [],
        "field_items": [],
        "create_label": translate_for_user(user_id, "teacher.content.action.create"),
        "back_label": translate_for_user(user_id, "teacher.content.action.back"),
        "cancel_label": translate_for_user(user_id, "teacher.content.action.cancel"),
        "prev_label": translate_for_user(user_id, "teacher.content.action.prev"),
        "next_label": translate_for_user(user_id, "teacher.content.action.next"),
        "edit_label": translate_for_user(user_id, "teacher.content.action.edit"),
        "archive_label": translate_for_user(user_id, "teacher.content.action.archive"),
        "publish_label": translate_for_user(user_id, "teacher.content.action.publish"),
        "show_all_label": translate_for_user(user_id, "teacher.content.action.show_all"),
        "topics_label": translate_for_user(user_id, "teacher.content.action.topics"),
        "workspaces_label": translate_for_user(user_id, "teacher.content.action.workspaces"),
        "has_prev_page": False,
        "has_next_page": False,
        "has_prev_item": False,
        "has_next_item": False,
        "has_current_item": False,
        "has_current_image": False,
        "show_all_available": False,
        "show_field_picker": False,
    }


def _build_browser_overview_text(
    *,
    user_id: int,
    snapshot: dict[str, object],
) -> str:
    lines = [
        translate_for_user(
            user_id,
            "teacher.content.overview.title",
            topic_title=escape(str(snapshot["topic_title"])),
        )
    ]
    visible_items = list(snapshot.get("visible_items") or [])
    if not visible_items:
        lines.extend(
            (
                translate_for_user(
                    user_id,
                    "teacher.content.overview.window",
                    start=0,
                    end=0,
                    item_count=int(snapshot["item_count"]),
                ),
                "",
                translate_for_user(user_id, "teacher.content.topic.empty"),
            )
        )
        return "\n".join(lines)
    lines.append(
        translate_for_user(
            user_id,
            "teacher.content.overview.window",
            start=int(visible_items[0]["position"]),
            end=int(visible_items[-1]["position"]),
            item_count=int(snapshot["item_count"]),
        )
    )
    lines.append("")
    for item in visible_items:
        marker_key = (
            "teacher.content.overview.item.selected.with_image"
            if bool(item["is_selected"]) and bool(item["has_image"])
            else "teacher.content.overview.item.selected.no_image"
            if bool(item["is_selected"])
            else "teacher.content.overview.item.default.with_image"
            if bool(item["has_image"])
            else "teacher.content.overview.item.default.no_image"
        )
        lines.append(
            translate_for_user(
                user_id,
                marker_key,
                position=int(item["position"]),
                headword=escape(str(item["headword"])),
            )
        )
    return "\n".join(lines)


def _build_current_item_media(snapshot: dict[str, object]) -> MediaAttachment | None:
    current_item = snapshot.get("current_item")
    if current_item is None:
        return None
    image_ref = current_item.get("image_ref")
    if not image_ref:
        return MediaAttachment(ContentType.PHOTO, path=NO_IMAGE_PLACEHOLDER_PATH)
    image_ref = str(image_ref)
    if image_ref.startswith(("http://", "https://")):
        return MediaAttachment(ContentType.PHOTO, url=image_ref)
    return MediaAttachment(ContentType.PHOTO, path=Path(image_ref))


def _current_item_has_real_image(snapshot: dict[str, object]) -> bool:
    current_item = snapshot.get("current_item")
    if current_item is None:
        return False
    return bool(current_item.get("image_ref"))


async def _show_browser_with_overview(
    dialog_manager: DialogManager,
    source_message: Message | None,
) -> None:
    if source_message is None:
        await dialog_manager.switch_to(TeacherContentDialogSG.browser)
        return
    user_id = _get_user_id(dialog_manager)
    snapshot = _load_browser_snapshot(dialog_manager)
    chat_id = _get_chat_id(source_message, dialog_manager)
    current_message_id = dialog_manager.current_stack().last_message_id
    if current_message_id is not None and chat_id is not None:
        await source_message.bot.edit_message_text(
            text=_build_browser_overview_text(user_id=user_id, snapshot=snapshot),
            chat_id=chat_id,
            message_id=current_message_id,
            parse_mode="HTML",
            reply_markup=None,
        )
        dialog_manager.dialog_data["browser_overview_message_id"] = int(current_message_id)
        dialog_manager.dialog_data["browser_overview_chat_id"] = int(chat_id)
    await dialog_manager.switch_to(TeacherContentDialogSG.browser, show_mode=ShowMode.SEND)


async def _sync_browser_overview_message(
    dialog_manager: DialogManager,
    source_message: Message | None,
) -> None:
    if source_message is None:
        return
    overview_message_id = dialog_manager.dialog_data.get("browser_overview_message_id")
    chat_id = dialog_manager.dialog_data.get("browser_overview_chat_id")
    if overview_message_id is None or chat_id is None:
        return
    user_id = _get_user_id(dialog_manager)
    snapshot = _load_browser_snapshot(dialog_manager)
    await source_message.bot.edit_message_text(
        text=_build_browser_overview_text(user_id=user_id, snapshot=snapshot),
        chat_id=int(chat_id),
        message_id=int(overview_message_id),
        parse_mode="HTML",
        reply_markup=None,
    )


async def _delete_browser_overview_message(
    dialog_manager: DialogManager,
    source_message: Message | None,
) -> None:
    overview_message_id = dialog_manager.dialog_data.pop("browser_overview_message_id", None)
    chat_id = dialog_manager.dialog_data.pop("browser_overview_chat_id", None)
    if source_message is None or overview_message_id is None or chat_id is None:
        return
    await source_message.bot.delete_message(
        chat_id=int(chat_id),
        message_id=int(overview_message_id),
    )


async def _delete_user_message(message: Message) -> None:
    try:
        await message.delete()
    except Exception:
        return


async def _cancel_dialog(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    await _delete_browser_overview_message(dialog_manager, callback.message)
    if callback.message is not None:
        await callback.message.delete()
    await dialog_manager.done(show_mode=ShowMode.NO_UPDATE)


async def _enter_prompt(dialog_manager: DialogManager, prompt_kind: PromptKind) -> None:
    dialog_manager.dialog_data["prompt_kind"] = prompt_kind.value
    dialog_manager.dialog_data.pop("prompt_error", None)
    dialog_manager.dialog_data.pop("status_text", None)
    if prompt_kind == PromptKind.EDIT_FIELD:
        dialog_manager.dialog_data["edit_field"] = None
    else:
        dialog_manager.dialog_data.pop("edit_field", None)
    await dialog_manager.switch_to(TeacherContentDialogSG.prompt)


async def _reset_prompt_state(dialog_manager: DialogManager) -> None:
    dialog_manager.dialog_data.pop("prompt_kind", None)
    dialog_manager.dialog_data.pop("prompt_error", None)
    dialog_manager.dialog_data.pop("edit_field", None)


async def _handle_unavailable(dialog_manager: DialogManager) -> None:
    user_id = _get_user_id(dialog_manager)
    dialog_manager.dialog_data["status_text"] = translate_for_user(
        user_id,
        "teacher.content.unavailable",
    )
    await _reset_prompt_state(dialog_manager)
    await dialog_manager.switch_to(TeacherContentDialogSG.workspaces)


def _slice_page(items: list[dict[str, object]], page: int) -> list[dict[str, object]]:
    start = page * LIST_PAGE_SIZE
    return items[start:start + LIST_PAGE_SIZE]


def _clamp_list_page(dialog_manager: DialogManager, key: str, total_count: int) -> int:
    page = int(dialog_manager.dialog_data.get(key, 0))
    max_page = max(_list_page_count(total_count) - 1, 0)
    page = min(max(page, 0), max_page)
    dialog_manager.dialog_data[key] = page
    return page


def _list_page_count(total_count: int) -> int:
    if total_count <= 0:
        return 1
    return ((total_count - 1) // LIST_PAGE_SIZE) + 1


def _get_workspace_name(user_id: int, workspace_id: int) -> str:
    for workspace in list_teacher_browsable_workspaces(user_id):
        if int(workspace["id"]) == workspace_id:
            return str(workspace["name"])
    raise TeacherContentAccessError


def _get_status_text(dialog_manager: DialogManager) -> str | None:
    status_text = dialog_manager.dialog_data.get("status_text")
    return str(status_text) if status_text else None


def _get_prompt_kind(dialog_manager: DialogManager) -> PromptKind | None:
    prompt_kind = dialog_manager.dialog_data.get("prompt_kind")
    if prompt_kind is None:
        return None
    return PromptKind(str(prompt_kind))


def _get_user_id(dialog_manager: DialogManager) -> int:
    event = dialog_manager.event
    user = getattr(event, "from_user", None)
    if user is None:
        raise RuntimeError("Dialog event user is missing")
    return int(user.id)


def _get_chat_id(source_message: Message, dialog_manager: DialogManager) -> int | None:
    chat = getattr(source_message, "chat", None)
    if chat is not None and getattr(chat, "id", None) is not None:
        return int(chat.id)
    event_chat = getattr(dialog_manager.event, "chat", None)
    if event_chat is not None and getattr(event_chat, "id", None) is not None:
        return int(event_chat.id)
    return _get_user_id(dialog_manager)


teacher_content_dialog = Dialog(
    Window(
        Format("{screen_text}"),
        ScrollingGroup(
            Select(
                Format("{item[name]}"),
                id="workspace_select",
                item_id_getter=lambda item: item["id"],
                items="workspace_items",
                on_click=_on_workspace_selected,
            ),
            id="workspace_scroll",
            width=1,
            height=LIST_PAGE_SIZE,
        ),
        Row(
            Button(Format("{prev_label}"), id="workspace_page", on_click=_prev_list_page, when="has_prev_page"),
            Button(Format("{next_label}"), id="workspace_page", on_click=_next_list_page, when="has_next_page"),
        ),
        Row(
            Button(Format("{create_label}"), id="create_workspace", on_click=_open_create_workspace),
            Button(Format("{cancel_label}"), id="workspaces_cancel", on_click=_cancel_dialog),
        ),
        state=TeacherContentDialogSG.workspaces,
        getter=get_workspaces_window_data,
    ),
    Window(
        Format("{screen_text}"),
        ScrollingGroup(
            Select(
                Format("{item[title]} ({item[item_count]})"),
                id="topic_select",
                item_id_getter=lambda item: item["id"],
                items="topic_items",
                on_click=_on_topic_selected,
            ),
            id="topic_scroll",
            width=1,
            height=LIST_PAGE_SIZE,
        ),
        Row(
            Button(Format("{prev_label}"), id="topic_page", on_click=_prev_list_page, when="has_prev_page"),
            Button(Format("{next_label}"), id="topic_page", on_click=_next_list_page, when="has_next_page"),
        ),
        Row(
            Button(Format("{create_label}"), id="create_topic", on_click=_open_create_topic),
            Button(Format("{back_label}"), id="back_to_workspaces", on_click=_go_to_workspaces),
            Button(Format("{cancel_label}"), id="topics_cancel", on_click=_cancel_dialog),
        ),
        state=TeacherContentDialogSG.topics,
        getter=get_topics_window_data,
    ),
    Window(
        DynamicMedia("current_item_media", when="has_current_item"),
        Format("{screen_text}"),
        Row(
            Button(Format("{prev_label}"), id="prev_item", on_click=_prev_item, when="has_prev_item"),
            Button(Format("{next_label}"), id="next_item", on_click=_next_item, when="has_next_item"),
        ),
        Row(
            Button(Format("{edit_label}"), id="edit_item", on_click=_open_edit_prompt, when="has_current_item"),
            Button(Format("{archive_label}"), id="archive_item", on_click=_archive_item, when="has_current_item"),
        ),
        Row(
            Button(Format("{create_label}"), id="create_item", on_click=_open_create_item),
            Button(Format("{publish_label}"), id="publish_topic", on_click=_open_publish_targets),
        ),
        Row(
            Button(Format("{show_all_label}"), id="show_all_items", on_click=_show_all_items, when="show_all_available"),
        ),
        Row(
            Button(Format("{topics_label}"), id="back_to_topics", on_click=_go_to_topics),
            Button(Format("{workspaces_label}"), id="back_to_workspaces", on_click=_go_to_workspaces),
            Button(Format("{cancel_label}"), id="browser_cancel", on_click=_cancel_dialog),
        ),
        state=TeacherContentDialogSG.browser,
        getter=get_browser_window_data,
    ),
    Window(
        Format("{screen_text}"),
        Column(
            Select(
                Format("{item[label]}"),
                id="field_select",
                item_id_getter=lambda item: item["id"],
                items="field_items",
                on_click=_choose_field,
                when="show_field_picker",
            ),
            when="show_field_picker",
        ),
        MessageInput(_on_prompt_input),
        Row(
            Button(Format("{back_label}"), id="prompt_back", on_click=_go_to_prompt_return),
            Button(Format("{cancel_label}"), id="prompt_cancel", on_click=_cancel_dialog),
        ),
        state=TeacherContentDialogSG.prompt,
        getter=get_prompt_window_data,
    ),
    Window(
        Format("{screen_text}"),
        ScrollingGroup(
            Select(
                Format("{item[name]}"),
                id="publish_select",
                item_id_getter=lambda item: item["id"],
                items="target_items",
                on_click=_on_publish_target_selected,
            ),
            id="publish_scroll",
            width=1,
            height=LIST_PAGE_SIZE,
        ),
        Row(
            Button(Format("{back_label}"), id="publish_back", on_click=_go_to_browser),
            Button(Format("{cancel_label}"), id="publish_cancel", on_click=_cancel_dialog),
        ),
        state=TeacherContentDialogSG.publish,
        getter=get_publish_window_data,
    ),
)


choose_field = _choose_field
go_to_browser = _go_to_browser
go_to_prompt_return = _go_to_prompt_return
hide_show_all = hide_show_all_message
next_item = _next_item
on_prompt_input = _on_prompt_input
on_topic_selected = _on_topic_selected
on_workspace_selected = _on_workspace_selected
open_create_topic = _open_create_topic
open_edit_prompt = _open_edit_prompt
open_publish_targets = _open_publish_targets
prev_item = _prev_item
show_all_items = _show_all_items
