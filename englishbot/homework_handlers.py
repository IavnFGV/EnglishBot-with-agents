from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram_dialog import DialogManager, StartMode

from .command_registry import LEARN_COMMAND
from .db import save_user
from .homework_dialog import HomeworkDialogSG
from .homework import (
    AssignmentNotFoundError,
    EmptyAssignmentError,
    start_assignment_training_session,
    student_has_active_homework,
)
from .i18n import translate_for_user
from .runtime import router
from .training_handlers import render_started_training_session


HOMEWORK_OPEN_CALLBACK = "homework:open"
HOMEWORK_START_PREFIX = "homework:start:"


def build_homework_button(telegram_user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=translate_for_user(telegram_user_id, "homework.button.open"),
                    callback_data=HOMEWORK_OPEN_CALLBACK,
                )
            ]
        ]
    )


@router.message(CommandStart())
async def start(message: Message) -> None:
    if message.from_user is None:
        return

    save_user(message.from_user)
    if student_has_active_homework(message.from_user.id):
        await message.answer(
            translate_for_user(message.from_user.id, "homework.has_active"),
            reply_markup=build_homework_button(message.from_user.id),
        )
        return

    await message.answer(
        translate_for_user(
            message.from_user.id,
            "homework.none",
            learn_command=LEARN_COMMAND.token,
        )
    )


@router.callback_query(lambda callback: callback.data == HOMEWORK_OPEN_CALLBACK)
async def open_homework(callback: CallbackQuery, dialog_manager: DialogManager) -> None:
    await callback.answer()
    if callback.from_user is None:
        return

    await dialog_manager.start(
        HomeworkDialogSG.assignments,
        mode=StartMode.RESET_STACK,
    )


@router.callback_query(
    lambda callback: callback.data is not None
    and callback.data.startswith(HOMEWORK_START_PREFIX)
)
async def start_homework(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None or callback.data is None:
        return

    assignment_id = int(callback.data.removeprefix(HOMEWORK_START_PREFIX))
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

    question = result["question"]
    if question is None:
        await callback.message.answer(
            translate_for_user(callback.from_user.id, "homework.start_failed")
        )
        return

    await render_started_training_session(callback.message, callback.from_user.id)
