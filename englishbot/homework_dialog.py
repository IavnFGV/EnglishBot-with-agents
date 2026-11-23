from __future__ import annotations

from aiogram.enums import ContentType
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery
from aiogram_dialog import Dialog, DialogManager, ShowMode, Window
from aiogram_dialog.api.entities.media import MediaAttachment
from aiogram_dialog.widgets.kbd import Button, Column, Row, ScrollingGroup, Select
from aiogram_dialog.widgets.media import DynamicMedia
from aiogram_dialog.widgets.text import Format

from .homework import (
    AssignmentNotFoundError,
    EmptyAssignmentError,
    list_assignment_tasks,
    set_assignment_task_done,
    start_assignment_training_session,
)
from .i18n import translate_for_user
from .learner_homework import (
    HOMEWORK_ACTION_CONTINUE,
    HOMEWORK_ACTION_START,
    get_learner_homework_overview,
    list_learner_homework,
)
from .learner_training_dialog import start_training_dialog


LIST_PAGE_SIZE = 5
CAPTION_LIMIT = 1000  # Telegram allows 1024 characters under a photo
BUTTON_TITLE_LIMIT = 40
DRILL_TASK_KINDS = ("words", "verbs")  # drilled in training, not ticked off


class HomeworkDialogSG(StatesGroup):
    assignments = State()
    overview = State()
    task = State()


async def _on_assignment_selected(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    assignment_id: str,
) -> None:
    dialog_manager.dialog_data["assignment_key"] = assignment_id
    dialog_manager.dialog_data["assignment_id"] = int(str(assignment_id).split(":")[-1])
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

    assignment_id = _get_selected_assignment_ref(dialog_manager)
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
    from .mini_app_handlers import offer_training_interfaces
    if await offer_training_interfaces(callback.message, callback.from_user.id):
        await dialog_manager.done(show_mode=ShowMode.NO_UPDATE)
        return
    await start_training_dialog(callback.message, dialog_manager, callback.from_user.id)


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
                    progress=_compact_progress(user_id, assignment),
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
        _get_selected_assignment_ref(dialog_manager),
    )
    action_key = str(assignment["action_key"])
    progress = translate_for_user(
        user_id,
        "homework.dialog.progress.compact",
        completed_items=assignment["completed_items"],
        total_items=assignment["total_items"],
    )
    progress += "\n" + translate_for_user(user_id, "training.mode.info", mode=translate_for_user(user_id, f"training.mode.{assignment['assignment_mode']}"))
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

    screen_text = translate_for_user(
        user_id,
        "homework.dialog.screen.overview",
        title=_resolve_assignment_title(user_id, assignment),
        item_count=assignment["item_count"],
        progress=progress,
        action_label=translate_for_user(user_id, f"homework.dialog.action.{action_key}"),
        resume_details=resume_details,
    )
    task_lines = [line for task in assignment["tasks"] if (line := _task_line(user_id, assignment, task))]
    if task_lines:
        screen_text += "\n\n" + "\n".join(task_lines)
    return {
        "screen_text": screen_text,
        "can_train": int(assignment["item_count"]) > 0 and not assignment["words_done"],
        "task_buttons": [
            {"id": str(task["id"]), "label": _task_button_label(user_id, task)}
            for task in assignment["tasks"]
            if task["kind"] not in DRILL_TASK_KINDS
        ],
        "action_label": translate_for_user(user_id, f"homework.dialog.action.{action_key}"),
        "back_label": translate_for_user(user_id, "homework.dialog.action.back"),
        "cancel_label": translate_for_user(user_id, "homework.dialog.action.cancel"),
    }


def _compact_progress(user_id: int, assignment: dict[str, object]) -> str:
    progress = translate_for_user(
        user_id,
        "homework.dialog.progress.compact",
        completed_items=assignment["completed_items"],
        total_items=assignment["total_items"],
    )
    if assignment.get("paper_total"):
        progress += " • " + translate_for_user(
            user_id, "homework.task.paper_progress", done=assignment["paper_done"], total=assignment["paper_total"]
        )
    return progress


def _task_title(user_id: int, task: dict[str, object]) -> str:
    return str(task["title"]) or translate_for_user(user_id, f"homework.task.untitled.{task['kind']}")


def _drill_line(user_id: int, assignment: dict[str, object]) -> str:
    """One line for everything drilled in training: words, verbs, or both share one progress."""
    kinds = {task["kind"] for task in assignment["tasks"] if task["kind"] in DRILL_TASK_KINDS}
    prefix = "mixed" if len(kinds) > 1 else "verbs" if kinds == {"verbs"} else "words"
    if assignment["words_done"]:
        return translate_for_user(user_id, f"homework.task.{prefix}_done_line")
    return translate_for_user(
        user_id, f"homework.task.{prefix}_line", done=assignment["completed_items"], total=assignment["total_items"]
    )


def _task_line(user_id: int, assignment: dict[str, object], task: dict[str, object]) -> str | None:
    if task["kind"] in DRILL_TASK_KINDS:
        first = next(other for other in assignment["tasks"] if other["kind"] in DRILL_TASK_KINDS)
        return _drill_line(user_id, assignment) if first is task else None
    if task["kind"] == "paper":
        return translate_for_user(user_id, "homework.task.paper_line", mark="✅" if task["done"] else "⬜", title=_task_title(user_id, task))
    return translate_for_user(user_id, "homework.task.note_line", title=_task_title(user_id, task))


def _task_button_label(user_id: int, task: dict[str, object]) -> str:
    title = _task_title(user_id, task)
    if len(title) > BUTTON_TITLE_LIMIT:
        title = title[: BUTTON_TITLE_LIMIT - 1] + "…"
    if task["kind"] == "paper":
        return translate_for_user(user_id, "homework.task.paper_line", mark="✅" if task["done"] else "⬜", title=title)
    return translate_for_user(user_id, "homework.task.note_line", title=title)


def _selected_task(dialog_manager: DialogManager) -> dict[str, object]:
    user_id = _get_user_id(dialog_manager)
    task_id = int(dialog_manager.dialog_data.get("task_id", 0))
    for task in list_assignment_tasks(user_id, _get_selected_assignment_id(dialog_manager)):
        if task["id"] == task_id:
            return task
    raise AssignmentNotFoundError


async def _on_task_selected(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    task_id: str,
) -> None:
    dialog_manager.dialog_data["task_id"] = int(task_id)
    dialog_manager.dialog_data["photo_index"] = 0
    await dialog_manager.switch_to(HomeworkDialogSG.task)


async def _shift_photo(dialog_manager: DialogManager, delta: int) -> None:
    dialog_manager.dialog_data["photo_index"] = int(dialog_manager.dialog_data.get("photo_index", 0)) + delta
    await dialog_manager.update({})


async def _prev_photo(callback: CallbackQuery, button: Button, dialog_manager: DialogManager) -> None:
    await _shift_photo(dialog_manager, -1)


async def _next_photo(callback: CallbackQuery, button: Button, dialog_manager: DialogManager) -> None:
    await _shift_photo(dialog_manager, 1)


async def _toggle_task_done(callback: CallbackQuery, button: Button, dialog_manager: DialogManager) -> None:
    if callback.from_user is None:
        return
    user_id = callback.from_user.id
    try:
        task = _selected_task(dialog_manager)
        finished = set_assignment_task_done(user_id, _get_selected_assignment_id(dialog_manager), int(task["id"]), not task["done"])
    except AssignmentNotFoundError:
        await callback.answer(translate_for_user(user_id, "homework.assignment_not_found"))
        await dialog_manager.switch_to(HomeworkDialogSG.assignments)
        return
    if finished:
        await callback.answer(translate_for_user(user_id, "homework.task.all_done"), show_alert=True)
        await dialog_manager.switch_to(HomeworkDialogSG.assignments)
        return
    await callback.answer()
    await dialog_manager.switch_to(HomeworkDialogSG.overview)


async def _back_to_overview(callback: CallbackQuery, button: Button, dialog_manager: DialogManager) -> None:
    await dialog_manager.switch_to(HomeworkDialogSG.overview)


async def get_task_window_data(
    dialog_manager: DialogManager,
    **_: object,
) -> dict[str, object]:
    user_id = _get_user_id(dialog_manager)
    task = _selected_task(dialog_manager)
    photos = list(task["photos"])
    index = int(dialog_manager.dialog_data.get("photo_index", 0)) % len(photos) if photos else 0
    dialog_manager.dialog_data["photo_index"] = index
    text = _task_button_label(user_id, task) if task["kind"] == "paper" else translate_for_user(user_id, "homework.task.note_line", title=_task_title(user_id, task))
    if task["instructions"]:
        text += "\n\n" + str(task["instructions"])
    if len(photos) > 1:
        text += "\n\n" + translate_for_user(user_id, "homework.task.photo_counter", index=index + 1, total=len(photos))
    if photos and len(text) > CAPTION_LIMIT:
        text = text[: CAPTION_LIMIT - 1] + "…"
    return {
        "screen_text": text,
        "has_media": bool(photos),
        "task_media": MediaAttachment(ContentType.PHOTO, path=photos[index]) if photos else None,
        "has_many_photos": len(photos) > 1,
        "is_paper": task["kind"] == "paper",
        "toggle_label": translate_for_user(user_id, "homework.task.mark_undone" if task["done"] else "homework.task.mark_done"),
        "back_label": translate_for_user(user_id, "homework.dialog.action.back"),
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


def _get_selected_assignment_ref(dialog_manager: DialogManager) -> str:
    value = dialog_manager.dialog_data.get("assignment_key")
    if value is not None:
        return str(value)
    return str(_get_selected_assignment_id(dialog_manager))


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
                item_id_getter=lambda item: item["assignment_key"],
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
            Button(Format("{action_label}"), id="overview_start", on_click=_launch_assignment, when="can_train"),
        ),
        Column(
            Select(
                Format("{item[label]}"),
                id="task_select",
                item_id_getter=lambda item: item["id"],
                items="task_buttons",
                on_click=_on_task_selected,
            ),
        ),
        Row(
            Button(Format("{back_label}"), id="overview_back", on_click=_go_back_to_assignments),
            Button(Format("{cancel_label}"), id="overview_cancel", on_click=_cancel_dialog),
        ),
        state=HomeworkDialogSG.overview,
        getter=get_overview_window_data,
    ),
    Window(
        DynamicMedia("task_media", when="has_media"),
        Format("{screen_text}"),
        Row(
            Button(Format("◀️"), id="task_photo_prev", on_click=_prev_photo),
            Button(Format("▶️"), id="task_photo_next", on_click=_next_photo),
            when="has_many_photos",
        ),
        Row(
            Button(Format("{toggle_label}"), id="task_toggle_done", on_click=_toggle_task_done, when="is_paper"),
        ),
        Row(
            Button(Format("{back_label}"), id="task_back", on_click=_back_to_overview),
        ),
        state=HomeworkDialogSG.task,
        getter=get_task_window_data,
    ),
)


select_assignment = _on_assignment_selected
launch_selected_homework = _launch_assignment
