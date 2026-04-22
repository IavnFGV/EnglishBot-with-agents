from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery
from aiogram_dialog import Dialog, DialogManager, ShowMode, Window
from aiogram_dialog.widgets.kbd import Button, Row, ScrollingGroup, Select
from aiogram_dialog.widgets.text import Format

from .homework import (
    AssignmentNotFoundError,
    EmptyAssignmentError,
    start_assignment_training_session,
)
from .i18n import translate_for_user
from .learner_homework import (
    HOMEWORK_ACTION_CONTINUE,
    HOMEWORK_ACTION_START,
    get_learner_homework_overview,
    list_learner_homework,
)
from .training_handlers import render_started_training_session


LIST_PAGE_SIZE = 5


class HomeworkDialogSG(StatesGroup):
    assignments = State()
    overview = State()


async def _on_assignment_selected(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    assignment_id: str,
) -> None:
    dialog_manager.dialog_data["assignment_id"] = int(assignment_id)
    await dialog_manager.switch_to(HomeworkDialogSG.overview)


async def _prev_page(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    current_page = int(dialog_manager.dialog_data.get("assignment_page", 0))
    dialog_manager.dialog_data["assignment_page"] = max(current_page - 1, 0)
    await dialog_manager.update({})


async def _next_page(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    current_page = int(dialog_manager.dialog_data.get("assignment_page", 0))
    dialog_manager.dialog_data["assignment_page"] = current_page + 1
    await dialog_manager.update({})


async def _go_back_to_assignments(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    await dialog_manager.switch_to(HomeworkDialogSG.assignments)


async def _cancel_dialog(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    if callback.message is not None:
        await callback.message.delete()
    await dialog_manager.done(show_mode=ShowMode.NO_UPDATE)


async def _launch_assignment(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
) -> None:
    if callback.from_user is None or callback.message is None:
        return

    assignment_id = _get_selected_assignment_id(dialog_manager)
    try:
        result = start_assignment_training_session(callback.from_user.id, assignment_id)
    except AssignmentNotFoundError:
        await callback.message.answer(
            translate_for_user(callback.from_user.id, "homework.assignment_not_found")
        )
        return
    except EmptyAssignmentError:
        await callback.message.answer(
            translate_for_user(callback.from_user.id, "homework.assignment_empty")
        )
        return

    if result["question"] is None:
        await callback.message.answer(
            translate_for_user(callback.from_user.id, "homework.start_failed")
        )
        return

    await callback.message.delete()
    await dialog_manager.done(show_mode=ShowMode.NO_UPDATE)
    await render_started_training_session(callback.message, callback.from_user.id)


async def get_assignments_window_data(
    dialog_manager: DialogManager,
    **_: object,
) -> dict[str, object]:
    user_id = _get_user_id(dialog_manager)
    assignments = list_learner_homework(user_id)
    current_page = _clamp_page(dialog_manager, len(assignments))
    total_items = len(assignments)
    page_start = current_page * LIST_PAGE_SIZE
    page_items = assignments[page_start:page_start + LIST_PAGE_SIZE]
    if page_items:
        screen_text = translate_for_user(
            user_id,
            "homework.dialog.screen.list",
            range_start=page_start + 1,
            range_end=page_start + len(page_items),
            total_count=total_items,
            assignment_lines="\n".join(
                translate_for_user(
                    user_id,
                    "homework.dialog.line.entry",
                    index=page_start + index + 1,
                    title=_resolve_assignment_title(user_id, assignment),
                    progress=translate_for_user(
                        user_id,
                        "homework.dialog.progress.compact",
                        completed_items=assignment["completed_items"],
                        total_items=assignment["total_items"],
                    ),
                    action_label=translate_for_user(
                        user_id,
                        f"homework.dialog.action.{assignment['action_key']}",
                    ),
                )
                for index, assignment in enumerate(page_items)
            ),
        )
    else:
        screen_text = translate_for_user(user_id, "homework.dialog.screen.list.empty")

    return {
        "screen_text": screen_text,
        "assignment_items": [
            {
                **assignment,
                "index_label": str(page_start + index + 1),
            }
            for index, assignment in enumerate(page_items)
        ],
        "has_assignments": bool(page_items),
        "has_prev_page": current_page > 0,
        "has_next_page": page_start + LIST_PAGE_SIZE < total_items,
        "prev_label": translate_for_user(user_id, "homework.dialog.action.prev"),
        "next_label": translate_for_user(user_id, "homework.dialog.action.next"),
        "cancel_label": translate_for_user(user_id, "homework.dialog.action.cancel"),
    }


async def get_overview_window_data(
    dialog_manager: DialogManager,
    **_: object,
) -> dict[str, object]:
    user_id = _get_user_id(dialog_manager)
    assignment = get_learner_homework_overview(
        user_id,
        _get_selected_assignment_id(dialog_manager),
    )
    action_key = str(assignment["action_key"])
    progress = translate_for_user(
        user_id,
        "homework.dialog.progress.compact",
        completed_items=assignment["completed_items"],
        total_items=assignment["total_items"],
    )
    resume_details = ""
    current_stage = assignment["current_stage"]
    if current_stage is not None:
        resume_details = translate_for_user(
            user_id,
            "homework.dialog.overview.resume_details",
            current_item_position=assignment["current_item_position"],
            item_count=assignment["item_count"],
            stage_label=translate_for_user(user_id, f"training.stage.{current_stage}"),
        )

    return {
        "screen_text": translate_for_user(
            user_id,
            "homework.dialog.screen.overview",
            title=_resolve_assignment_title(user_id, assignment),
            item_count=assignment["item_count"],
            progress=progress,
            action_label=translate_for_user(user_id, f"homework.dialog.action.{action_key}"),
            resume_details=resume_details,
        ),
        "action_label": translate_for_user(user_id, f"homework.dialog.action.{action_key}"),
        "back_label": translate_for_user(user_id, "homework.dialog.action.back"),
        "cancel_label": translate_for_user(user_id, "homework.dialog.action.cancel"),
    }


def _resolve_assignment_title(
    telegram_user_id: int,
    assignment: dict[str, object],
) -> str:
    title = assignment["title"]
    if title is not None and str(title).strip():
        return str(title)
    return translate_for_user(
        telegram_user_id,
        "homework.assignment_fallback",
        assignment_id=assignment["assignment_id"],
    )


def _clamp_page(dialog_manager: DialogManager, total_items: int) -> int:
    if total_items <= 0:
        dialog_manager.dialog_data["assignment_page"] = 0
        return 0
    max_page = (total_items - 1) // LIST_PAGE_SIZE
    current_page = int(dialog_manager.dialog_data.get("assignment_page", 0))
    clamped_page = max(0, min(current_page, max_page))
    dialog_manager.dialog_data["assignment_page"] = clamped_page
    return clamped_page


def _get_selected_assignment_id(dialog_manager: DialogManager) -> int:
    value = dialog_manager.dialog_data.get("assignment_id")
    if value is None:
        raise AssignmentNotFoundError
    return int(value)


def _get_user_id(dialog_manager: DialogManager) -> int:
    if dialog_manager.event.from_user is None:
        raise RuntimeError("Dialog event user is missing")
    return int(dialog_manager.event.from_user.id)


homework_dialog = Dialog(
    Window(
        Format("{screen_text}"),
        ScrollingGroup(
            Select(
                Format("{item[index_label]}"),
                id="assignment_select",
                item_id_getter=lambda item: item["assignment_id"],
                items="assignment_items",
                on_click=_on_assignment_selected,
            ),
            id="assignment_scroll",
            width=LIST_PAGE_SIZE,
            height=1,
            when="has_assignments",
        ),
        Row(
            Button(Format("{prev_label}"), id="assignment_prev", on_click=_prev_page, when="has_prev_page"),
            Button(Format("{next_label}"), id="assignment_next", on_click=_next_page, when="has_next_page"),
        ),
        Row(
            Button(Format("{cancel_label}"), id="assignment_cancel", on_click=_cancel_dialog),
        ),
        state=HomeworkDialogSG.assignments,
        getter=get_assignments_window_data,
    ),
    Window(
        Format("{screen_text}"),
        Row(
            Button(Format("{action_label}"), id="overview_start", on_click=_launch_assignment),
        ),
        Row(
            Button(Format("{back_label}"), id="overview_back", on_click=_go_back_to_assignments),
            Button(Format("{cancel_label}"), id="overview_cancel", on_click=_cancel_dialog),
        ),
        state=HomeworkDialogSG.overview,
        getter=get_overview_window_data,
    ),
)


select_assignment = _on_assignment_selected
launch_selected_homework = _launch_assignment
