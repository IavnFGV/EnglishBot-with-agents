from __future__ import annotations

from html import escape

from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram_dialog import Dialog, DialogManager, ShowMode, Window
from aiogram_dialog.widgets.kbd import Button, Row, ScrollingGroup, Select
from aiogram_dialog.widgets.text import Format

from .homework import ASSIGNMENT_KIND_HOMEWORK, ASSIGNMENT_MODE_STAGED_DEFAULT
from .homework_handlers import build_homework_button
from .i18n import translate_for_user
from .teacher_assignments import (
    SOURCE_MODE_TOPIC,
    SOURCE_MODE_WORDS,
    TeacherAssignmentDraftError,
    TeacherAssignmentRecipientsRequiredError,
    build_assignment_confirm_snapshot,
    build_topic_selection_summary,
    build_word_selection_snapshot,
    list_assignment_recipients,
    list_assignment_topics,
    list_assignment_workspaces,
    persist_assignment_draft,
)


LIST_PAGE_SIZE = 8


class TeacherAssignmentDialogSG(StatesGroup):
    source_mode = State()
    workspace = State()
    topic = State()
    words = State()
    recipients = State()
    confirm = State()


async def _choose_topic_mode(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    _reset_content_state(dialog_manager)
    dialog_manager.dialog_data["source_mode"] = SOURCE_MODE_TOPIC
    await dialog_manager.switch_to(TeacherAssignmentDialogSG.workspace)


async def _choose_words_mode(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    _reset_content_state(dialog_manager)
    dialog_manager.dialog_data["source_mode"] = SOURCE_MODE_WORDS
    await dialog_manager.switch_to(TeacherAssignmentDialogSG.workspace)


async def _on_workspace_selected(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    workspace_id: str,
) -> None:
    dialog_manager.dialog_data["workspace_id"] = int(workspace_id)
    dialog_manager.dialog_data["topic_page"] = 0
    dialog_manager.dialog_data["recipient_page"] = 0
    source_mode = str(dialog_manager.dialog_data.get("source_mode", ""))
    if source_mode == SOURCE_MODE_TOPIC:
        dialog_manager.dialog_data.pop("topic_id", None)
        await _delete_summary_message(dialog_manager, callback.message)
        await dialog_manager.switch_to(TeacherAssignmentDialogSG.topic)
        return

    snapshot = build_word_selection_snapshot(
        _get_user_id(dialog_manager),
        int(workspace_id),
        _get_selected_learning_item_ids(dialog_manager),
    )
    current_item = snapshot["current_item"]
    dialog_manager.dialog_data["current_learning_item_id"] = (
        int(current_item["id"]) if current_item is not None else None
    )
    await _sync_summary_message(dialog_manager, callback.message)
    await dialog_manager.switch_to(TeacherAssignmentDialogSG.words, show_mode=ShowMode.SEND)


async def _on_topic_selected(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    topic_id: str,
) -> None:
    dialog_manager.dialog_data["topic_id"] = int(topic_id)
    await _sync_summary_message(dialog_manager, callback.message)
    await dialog_manager.switch_to(TeacherAssignmentDialogSG.recipients, show_mode=ShowMode.SEND)


async def _prev_page(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    page_key = str(button.widget_id)
    current_page = int(dialog_manager.dialog_data.get(page_key, 0))
    dialog_manager.dialog_data[page_key] = max(current_page - 1, 0)
    await dialog_manager.update({})


async def _next_page(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    page_key = str(button.widget_id)
    current_page = int(dialog_manager.dialog_data.get(page_key, 0))
    dialog_manager.dialog_data[page_key] = current_page + 1
    await dialog_manager.update({})


async def _prev_word(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    snapshot = _load_words_snapshot(dialog_manager)
    previous_item_id = snapshot["prev_item_id"]
    if previous_item_id is None:
        return
    dialog_manager.dialog_data["current_learning_item_id"] = int(previous_item_id)
    await dialog_manager.update({})


async def _next_word(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    snapshot = _load_words_snapshot(dialog_manager)
    next_item_id = snapshot["next_item_id"]
    if next_item_id is None:
        return
    dialog_manager.dialog_data["current_learning_item_id"] = int(next_item_id)
    await dialog_manager.update({})


async def _toggle_current_word(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    snapshot = _load_words_snapshot(dialog_manager)
    current_item = snapshot["current_item"]
    if current_item is None:
        return
    selected_ids = _get_selected_learning_item_ids(dialog_manager)
    learning_item_id = int(current_item["id"])
    if learning_item_id in selected_ids:
        selected_ids = [
            selected_item_id
            for selected_item_id in selected_ids
            if selected_item_id != learning_item_id
        ]
    else:
        selected_ids.append(learning_item_id)
    dialog_manager.dialog_data["selected_learning_item_ids"] = selected_ids
    await _sync_summary_message(dialog_manager, callback.message)
    await dialog_manager.update({})


async def _go_to_recipients_from_words(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    if not _get_selected_learning_item_ids(dialog_manager):
        return
    await _sync_summary_message(dialog_manager, callback.message)
    await dialog_manager.switch_to(TeacherAssignmentDialogSG.recipients)


async def _toggle_recipient(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    recipient_user_id: str,
) -> None:
    selected_recipient_ids = _get_selected_recipient_ids(dialog_manager)
    student_user_id = int(recipient_user_id)
    if student_user_id in selected_recipient_ids:
        selected_recipient_ids = [
            recipient_id
            for recipient_id in selected_recipient_ids
            if recipient_id != student_user_id
        ]
    else:
        selected_recipient_ids.append(student_user_id)
    dialog_manager.dialog_data["selected_recipient_user_ids"] = selected_recipient_ids
    await dialog_manager.update({})


async def _go_to_confirm(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    await dialog_manager.switch_to(TeacherAssignmentDialogSG.confirm)


async def _go_back_to_workspace(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    await _delete_summary_message(dialog_manager, callback.message)
    dialog_manager.dialog_data.pop("workspace_id", None)
    dialog_manager.dialog_data.pop("topic_id", None)
    dialog_manager.dialog_data.pop("current_learning_item_id", None)
    await dialog_manager.switch_to(TeacherAssignmentDialogSG.workspace)


async def _go_back_to_source_mode(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    await _delete_summary_message(dialog_manager, callback.message)
    await dialog_manager.switch_to(TeacherAssignmentDialogSG.source_mode)


async def _go_back_to_content_selection(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    source_mode = str(dialog_manager.dialog_data.get("source_mode", ""))
    if source_mode == SOURCE_MODE_TOPIC:
        await _delete_summary_message(dialog_manager, callback.message)
        dialog_manager.dialog_data.pop("topic_id", None)
        await dialog_manager.switch_to(TeacherAssignmentDialogSG.topic)
        return
    await dialog_manager.switch_to(TeacherAssignmentDialogSG.words)


async def _go_back_to_recipients(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    await dialog_manager.switch_to(TeacherAssignmentDialogSG.recipients)


async def _confirm_assignment(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    try:
        results = persist_assignment_draft(
            _get_user_id(dialog_manager),
            source_mode=str(dialog_manager.dialog_data.get("source_mode", "")),
            workspace_id=int(dialog_manager.dialog_data["workspace_id"]),
            topic_id=_get_optional_int(dialog_manager.dialog_data.get("topic_id")),
            selected_learning_item_ids=_get_selected_learning_item_ids(dialog_manager),
            recipient_user_ids=_get_selected_recipient_ids(dialog_manager),
            assignment_kind=ASSIGNMENT_KIND_HOMEWORK,
            assignment_mode=ASSIGNMENT_MODE_STAGED_DEFAULT,
        )
    except (TeacherAssignmentDraftError, TeacherAssignmentRecipientsRequiredError):
        await dialog_manager.update({})
        return

    await _delete_summary_message(dialog_manager, callback.message)
    for result in results:
        student_user_id = int(result["student_user_id"])
        title = (
            str(result["title"])
            if result.get("title")
            else translate_for_user(student_user_id, "homework.default_title")
        )
        await callback.message.bot.send_message(
            chat_id=student_user_id,
            text=translate_for_user(
                student_user_id,
                "homework.notification.assigned",
                title=title,
            ),
            reply_markup=build_homework_button(student_user_id),
        )
    await dialog_manager.done(
        result={"assignment_count": len(results)},
        show_mode=ShowMode.SEND,
    )
    await callback.message.answer(
        translate_for_user(
            _get_user_id(dialog_manager),
            "teacher.assignment.created",
            assignment_count=len(results),
        )
    )


async def _cancel_dialog(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    await _delete_summary_message(dialog_manager, callback.message)
    await dialog_manager.done(show_mode=ShowMode.SEND)
    await callback.message.answer(
        translate_for_user(_get_user_id(dialog_manager), "flow.cancelled")
    )


async def get_source_mode_window_data(dialog_manager: DialogManager, **_: object) -> dict[str, object]:
    user_id = _get_user_id(dialog_manager)
    return {
        "screen_text": translate_for_user(user_id, "teacher.assignment.screen.source_mode"),
        "topic_label": translate_for_user(user_id, "teacher.assignment.action.topic"),
        "words_label": translate_for_user(user_id, "teacher.assignment.action.words"),
        "cancel_label": translate_for_user(user_id, "teacher.assignment.action.cancel"),
    }


async def get_workspace_window_data(dialog_manager: DialogManager, **_: object) -> dict[str, object]:
    user_id = _get_user_id(dialog_manager)
    workspace_items = list_assignment_workspaces(user_id)
    current_page = _clamp_page(dialog_manager, "workspace_page", len(workspace_items))
    paged_items = _slice_page(workspace_items, current_page)
    source_mode = str(dialog_manager.dialog_data.get("source_mode", ""))
    return {
        "screen_text": translate_for_user(
            user_id,
            "teacher.assignment.screen.workspace",
            source_mode_label=translate_for_user(user_id, f"teacher.assignment.source_mode.{source_mode}"),
        ),
        "workspace_items": paged_items,
        "has_prev_page": current_page > 0,
        "has_next_page": (current_page + 1) * LIST_PAGE_SIZE < len(workspace_items),
        "workspace_page": "workspace_page",
        "prev_label": translate_for_user(user_id, "teacher.assignment.action.prev"),
        "next_label": translate_for_user(user_id, "teacher.assignment.action.next"),
        "back_label": translate_for_user(user_id, "teacher.assignment.action.back"),
        "cancel_label": translate_for_user(user_id, "teacher.assignment.action.cancel"),
    }


async def get_topic_window_data(dialog_manager: DialogManager, **_: object) -> dict[str, object]:
    user_id = _get_user_id(dialog_manager)
    workspace_id = int(dialog_manager.dialog_data["workspace_id"])
    topic_items = list_assignment_topics(user_id, workspace_id)
    current_page = _clamp_page(dialog_manager, "topic_page", len(topic_items))
    paged_items = _slice_page(topic_items, current_page)
    return {
        "screen_text": translate_for_user(user_id, "teacher.assignment.screen.topic"),
        "topic_items": paged_items,
        "has_prev_page": current_page > 0,
        "has_next_page": (current_page + 1) * LIST_PAGE_SIZE < len(topic_items),
        "topic_page": "topic_page",
        "prev_label": translate_for_user(user_id, "teacher.assignment.action.prev"),
        "next_label": translate_for_user(user_id, "teacher.assignment.action.next"),
        "back_label": translate_for_user(user_id, "teacher.assignment.action.back"),
        "cancel_label": translate_for_user(user_id, "teacher.assignment.action.cancel"),
    }


async def get_words_window_data(dialog_manager: DialogManager, **_: object) -> dict[str, object]:
    user_id = _get_user_id(dialog_manager)
    snapshot = _load_words_snapshot(dialog_manager)
    current_item = snapshot["current_item"]
    if current_item is None:
        screen_text = translate_for_user(user_id, "teacher.assignment.words.empty")
        return {
            "screen_text": screen_text,
            "toggle_label": translate_for_user(user_id, "teacher.assignment.action.add_item"),
            "prev_label": translate_for_user(user_id, "teacher.assignment.action.prev"),
            "next_label": translate_for_user(user_id, "teacher.assignment.action.next"),
            "done_label": translate_for_user(user_id, "teacher.assignment.action.done"),
            "back_label": translate_for_user(user_id, "teacher.assignment.action.back"),
            "cancel_label": translate_for_user(user_id, "teacher.assignment.action.cancel"),
            "has_prev_item": False,
            "has_next_item": False,
            "has_selected_items": False,
        }

    selected_ids = set(_get_selected_learning_item_ids(dialog_manager))
    translation_lines = []
    for language_code in ("ru", "uk", "bg"):
        translation_lines.append(
            translate_for_user(
                user_id,
                "teacher.assignment.words.translation",
                language_label=language_code.upper(),
                value=current_item["translations"].get(language_code, "-"),
            )
        )
    screen_text = translate_for_user(
        user_id,
        "teacher.assignment.screen.words",
        workspace_name=escape(str(snapshot["workspace_name"])),
        item_position=int(snapshot["current_index"]) + 1,
        item_count=int(snapshot["item_count"]),
        text=escape(str(current_item["text"])),
        translations="\n".join(translation_lines),
        selected_state=translate_for_user(
            user_id,
            "teacher.assignment.words.selected.yes"
            if int(current_item["id"]) in selected_ids
            else "teacher.assignment.words.selected.no",
        ),
    )
    return {
        "screen_text": screen_text,
        "toggle_label": translate_for_user(
            user_id,
            "teacher.assignment.action.remove_item"
            if int(current_item["id"]) in selected_ids
            else "teacher.assignment.action.add_item",
        ),
        "prev_label": translate_for_user(user_id, "teacher.assignment.action.prev"),
        "next_label": translate_for_user(user_id, "teacher.assignment.action.next"),
        "done_label": translate_for_user(user_id, "teacher.assignment.action.done"),
        "back_label": translate_for_user(user_id, "teacher.assignment.action.back"),
        "cancel_label": translate_for_user(user_id, "teacher.assignment.action.cancel"),
        "has_prev_item": snapshot["prev_item_id"] is not None,
        "has_next_item": snapshot["next_item_id"] is not None,
        "has_selected_items": bool(snapshot["selected_learning_item_ids"]),
    }


async def get_recipients_window_data(dialog_manager: DialogManager, **_: object) -> dict[str, object]:
    user_id = _get_user_id(dialog_manager)
    recipients = list_assignment_recipients(user_id)
    selected_recipient_ids = set(_get_selected_recipient_ids(dialog_manager))
    current_page = _clamp_page(dialog_manager, "recipient_page", len(recipients))
    paged_recipients = _slice_page(recipients, current_page)
    recipient_items = [
        {
            "student_user_id": recipient["student_user_id"],
            "label": (
                f"✓ {recipient['display_name']}"
                if recipient["student_user_id"] in selected_recipient_ids
                else str(recipient["display_name"])
            ),
        }
        for recipient in paged_recipients
    ]
    return {
        "screen_text": translate_for_user(
            user_id,
            "teacher.assignment.screen.recipients",
            selected_count=len(selected_recipient_ids),
        ),
        "recipient_items": recipient_items,
        "has_prev_page": current_page > 0,
        "has_next_page": (current_page + 1) * LIST_PAGE_SIZE < len(recipients),
        "recipient_page": "recipient_page",
        "prev_label": translate_for_user(user_id, "teacher.assignment.action.prev"),
        "next_label": translate_for_user(user_id, "teacher.assignment.action.next"),
        "done_label": translate_for_user(user_id, "teacher.assignment.action.done"),
        "skip_label": translate_for_user(user_id, "teacher.assignment.action.skip"),
        "back_label": translate_for_user(user_id, "teacher.assignment.action.back"),
        "cancel_label": translate_for_user(user_id, "teacher.assignment.action.cancel"),
    }


async def get_confirm_window_data(dialog_manager: DialogManager, **_: object) -> dict[str, object]:
    user_id = _get_user_id(dialog_manager)
    snapshot = build_assignment_confirm_snapshot(
        user_id,
        source_mode=str(dialog_manager.dialog_data.get("source_mode", "")),
        workspace_id=int(dialog_manager.dialog_data["workspace_id"]),
        topic_id=_get_optional_int(dialog_manager.dialog_data.get("topic_id")),
        selected_learning_item_ids=_get_selected_learning_item_ids(dialog_manager),
        recipient_user_ids=_get_selected_recipient_ids(dialog_manager),
        assignment_kind=ASSIGNMENT_KIND_HOMEWORK,
        assignment_mode=ASSIGNMENT_MODE_STAGED_DEFAULT,
    )
    content_summary = snapshot["content_summary"]
    if snapshot["source_mode"] == SOURCE_MODE_TOPIC:
        content_text = translate_for_user(
            user_id,
            "teacher.assignment.confirm.content.topic",
            topic_title=escape(str(content_summary["topic_title"])),
            item_count=int(content_summary["selected_count"]),
        )
    else:
        content_text = translate_for_user(
            user_id,
            "teacher.assignment.confirm.content.words",
            item_count=int(content_summary["selected_count"]),
            preview=_format_preview_items(content_summary["preview_items"]),
        )
    recipients_text = (
        ", ".join(escape(str(recipient["display_name"])) for recipient in snapshot["recipients"])
        if snapshot["recipients"]
        else translate_for_user(user_id, "teacher.assignment.confirm.recipients.empty")
    )
    return {
        "screen_text": translate_for_user(
            user_id,
            "teacher.assignment.screen.confirm",
            content_text=content_text,
            assignment_kind=translate_for_user(user_id, "teacher.assignment.kind.homework"),
            assignment_mode=translate_for_user(user_id, "teacher.assignment.mode.staged_default"),
            recipients_text=recipients_text,
            can_confirm_note=""
            if snapshot["has_recipients"]
            else "\n" + translate_for_user(user_id, "teacher.assignment.confirm.recipients.required"),
        ),
        "back_label": translate_for_user(user_id, "teacher.assignment.action.back"),
        "recipients_label": translate_for_user(user_id, "teacher.assignment.action.recipients"),
        "confirm_label": translate_for_user(user_id, "teacher.assignment.action.confirm"),
        "cancel_label": translate_for_user(user_id, "teacher.assignment.action.cancel"),
        "can_confirm": snapshot["has_recipients"],
    }


def _load_words_snapshot(dialog_manager: DialogManager) -> dict[str, object]:
    workspace_id = int(dialog_manager.dialog_data["workspace_id"])
    return build_word_selection_snapshot(
        _get_user_id(dialog_manager),
        workspace_id,
        _get_selected_learning_item_ids(dialog_manager),
        current_learning_item_id=_get_optional_int(dialog_manager.dialog_data.get("current_learning_item_id")),
    )


async def _sync_summary_message(
    dialog_manager: DialogManager,
    source_message: Message,
) -> None:
    summary_text = _build_summary_text(dialog_manager)
    previous_summary_text = dialog_manager.dialog_data.get("summary_text")
    summary_message_id = _get_optional_int(dialog_manager.dialog_data.get("summary_message_id"))
    chat_id = _get_optional_int(dialog_manager.dialog_data.get("summary_chat_id")) or _get_chat_id(dialog_manager, source_message)
    if chat_id is None:
        return
    if summary_message_id is not None and previous_summary_text == summary_text:
        return
    if summary_message_id is None:
        await source_message.bot.edit_message_text(
            text=summary_text,
            chat_id=chat_id,
            message_id=source_message.message_id,
            parse_mode="HTML",
        )
        dialog_manager.dialog_data["summary_message_id"] = source_message.message_id
        dialog_manager.dialog_data["summary_chat_id"] = chat_id
        dialog_manager.dialog_data["summary_text"] = summary_text
        return
    await source_message.bot.edit_message_text(
        text=summary_text,
        chat_id=chat_id,
        message_id=summary_message_id,
        parse_mode="HTML",
    )
    dialog_manager.dialog_data["summary_text"] = summary_text


async def _delete_summary_message(
    dialog_manager: DialogManager,
    source_message: Message | None = None,
) -> None:
    summary_message_id = _get_optional_int(dialog_manager.dialog_data.get("summary_message_id"))
    chat_id = _get_optional_int(dialog_manager.dialog_data.get("summary_chat_id"))
    if summary_message_id is None:
        return
    bot = source_message.bot if source_message is not None else getattr(dialog_manager.event, "bot", None)
    if bot is not None and chat_id is not None:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=summary_message_id)
        except Exception:
            pass
    dialog_manager.dialog_data.pop("summary_message_id", None)
    dialog_manager.dialog_data.pop("summary_chat_id", None)
    dialog_manager.dialog_data.pop("summary_text", None)


def _build_summary_text(dialog_manager: DialogManager) -> str:
    user_id = _get_user_id(dialog_manager)
    source_mode = str(dialog_manager.dialog_data.get("source_mode", ""))
    workspace_id = _get_optional_int(dialog_manager.dialog_data.get("workspace_id"))
    if workspace_id is None:
        return translate_for_user(user_id, "teacher.assignment.summary.empty")
    if source_mode == SOURCE_MODE_TOPIC:
        topic_id = _get_optional_int(dialog_manager.dialog_data.get("topic_id"))
        if topic_id is None:
            return translate_for_user(user_id, "teacher.assignment.summary.empty")
        summary = build_topic_selection_summary(user_id, workspace_id, topic_id)
        return translate_for_user(
            user_id,
            "teacher.assignment.summary.topic",
            workspace_name=escape(str(summary["workspace_name"])),
            topic_title=escape(str(summary["topic_title"])),
            item_count=int(summary["selected_count"]),
            preview=_format_preview_items(summary["preview_items"]),
        )
    summary = _load_words_snapshot(dialog_manager)
    return translate_for_user(
        user_id,
        "teacher.assignment.summary.words",
        workspace_name=escape(str(summary["workspace_name"])),
        selected_count=int(summary["selected_count"]),
        preview=_format_preview_items(summary["preview_items"]),
    )


def _format_preview_items(items: list[dict[str, object]]) -> str:
    if not items:
        return "-"
    return ", ".join(escape(str(item["text"])) for item in items)


def _clamp_page(dialog_manager: DialogManager, key: str, total_items: int) -> int:
    if total_items <= 0:
        dialog_manager.dialog_data[key] = 0
        return 0
    current_page = int(dialog_manager.dialog_data.get(key, 0))
    max_page = (total_items - 1) // LIST_PAGE_SIZE
    clamped_page = min(max(current_page, 0), max_page)
    dialog_manager.dialog_data[key] = clamped_page
    return clamped_page


def _slice_page(items: list[dict[str, object]], current_page: int) -> list[dict[str, object]]:
    start_index = current_page * LIST_PAGE_SIZE
    return items[start_index:start_index + LIST_PAGE_SIZE]


def _reset_content_state(dialog_manager: DialogManager) -> None:
    for key in (
        "workspace_id",
        "topic_id",
        "current_learning_item_id",
        "selected_learning_item_ids",
        "selected_recipient_user_ids",
        "summary_message_id",
        "summary_chat_id",
        "summary_text",
        "workspace_page",
        "topic_page",
        "recipient_page",
    ):
        dialog_manager.dialog_data.pop(key, None)


def _get_selected_learning_item_ids(dialog_manager: DialogManager) -> list[int]:
    return [
        int(learning_item_id)
        for learning_item_id in dialog_manager.dialog_data.get("selected_learning_item_ids", [])
    ]


def _get_selected_recipient_ids(dialog_manager: DialogManager) -> list[int]:
    return [
        int(recipient_user_id)
        for recipient_user_id in dialog_manager.dialog_data.get("selected_recipient_user_ids", [])
    ]


def _get_optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _get_user_id(dialog_manager: DialogManager) -> int:
    return int(dialog_manager.event.from_user.id)


def _get_chat_id(dialog_manager: DialogManager, source_message: Message) -> int | None:
    if getattr(source_message, "chat", None) is not None and getattr(source_message.chat, "id", None) is not None:
        return int(source_message.chat.id)
    event_chat = getattr(dialog_manager.event, "chat", None)
    if event_chat is not None and getattr(event_chat, "id", None) is not None:
        return int(event_chat.id)
    return _get_user_id(dialog_manager)


teacher_assignment_dialog = Dialog(
    Window(
        Format("{screen_text}"),
        Row(
            Button(Format("{topic_label}"), id="source_topic", on_click=_choose_topic_mode),
            Button(Format("{words_label}"), id="source_words", on_click=_choose_words_mode),
        ),
        Row(
            Button(Format("{cancel_label}"), id="source_cancel", on_click=_cancel_dialog),
        ),
        state=TeacherAssignmentDialogSG.source_mode,
        getter=get_source_mode_window_data,
    ),
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
            Button(Format("{prev_label}"), id="workspace_page", on_click=_prev_page, when="has_prev_page"),
            Button(Format("{next_label}"), id="workspace_page", on_click=_next_page, when="has_next_page"),
        ),
        Row(
            Button(Format("{back_label}"), id="workspace_back", on_click=_go_back_to_source_mode),
            Button(Format("{cancel_label}"), id="workspace_cancel", on_click=_cancel_dialog),
        ),
        state=TeacherAssignmentDialogSG.workspace,
        getter=get_workspace_window_data,
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
            Button(Format("{prev_label}"), id="topic_page", on_click=_prev_page, when="has_prev_page"),
            Button(Format("{next_label}"), id="topic_page", on_click=_next_page, when="has_next_page"),
        ),
        Row(
            Button(Format("{back_label}"), id="topic_back", on_click=_go_back_to_workspace),
            Button(Format("{cancel_label}"), id="topic_cancel", on_click=_cancel_dialog),
        ),
        state=TeacherAssignmentDialogSG.topic,
        getter=get_topic_window_data,
    ),
    Window(
        Format("{screen_text}"),
        Row(
            Button(Format("{toggle_label}"), id="toggle_word", on_click=_toggle_current_word),
        ),
        Row(
            Button(Format("{prev_label}"), id="prev_word", on_click=_prev_word, when="has_prev_item"),
            Button(Format("{next_label}"), id="next_word", on_click=_next_word, when="has_next_item"),
        ),
        Row(
            Button(Format("{done_label}"), id="words_done", on_click=_go_to_recipients_from_words, when="has_selected_items"),
            Button(Format("{back_label}"), id="words_back", on_click=_go_back_to_workspace),
            Button(Format("{cancel_label}"), id="words_cancel", on_click=_cancel_dialog),
        ),
        state=TeacherAssignmentDialogSG.words,
        getter=get_words_window_data,
    ),
    Window(
        Format("{screen_text}"),
        ScrollingGroup(
            Select(
                Format("{item[label]}"),
                id="recipient_select",
                item_id_getter=lambda item: item["student_user_id"],
                items="recipient_items",
                on_click=_toggle_recipient,
            ),
            id="recipient_scroll",
            width=1,
            height=LIST_PAGE_SIZE,
        ),
        Row(
            Button(Format("{prev_label}"), id="recipient_page", on_click=_prev_page, when="has_prev_page"),
            Button(Format("{next_label}"), id="recipient_page", on_click=_next_page, when="has_next_page"),
        ),
        Row(
            Button(Format("{done_label}"), id="recipient_done", on_click=_go_to_confirm),
            Button(Format("{skip_label}"), id="recipient_skip", on_click=_go_to_confirm),
        ),
        Row(
            Button(Format("{back_label}"), id="recipient_back", on_click=_go_back_to_content_selection),
            Button(Format("{cancel_label}"), id="recipient_cancel", on_click=_cancel_dialog),
        ),
        state=TeacherAssignmentDialogSG.recipients,
        getter=get_recipients_window_data,
    ),
    Window(
        Format("{screen_text}"),
        Row(
            Button(Format("{recipients_label}"), id="confirm_recipients", on_click=_go_back_to_recipients),
            Button(Format("{confirm_label}"), id="confirm_submit", on_click=_confirm_assignment, when="can_confirm"),
        ),
        Row(
            Button(Format("{back_label}"), id="confirm_back", on_click=_go_back_to_recipients),
            Button(Format("{cancel_label}"), id="confirm_cancel", on_click=_cancel_dialog),
        ),
        state=TeacherAssignmentDialogSG.confirm,
        getter=get_confirm_window_data,
    ),
)


on_workspace_selected = _on_workspace_selected
on_topic_selected = _on_topic_selected
prev_word = _prev_word
next_word = _next_word
toggle_current_word = _toggle_current_word
toggle_recipient = _toggle_recipient
go_to_confirm = _go_to_confirm
confirm_assignment = _confirm_assignment
cancel_assignment_dialog = _cancel_dialog
