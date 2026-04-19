from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .db import save_user
from .homework import (
    AssignmentNotFoundError,
    EmptyAssignmentError,
    list_active_assignments,
    start_assignment_training_session,
    student_has_active_homework,
)
from .runtime import router


HOMEWORK_OPEN_CALLBACK = "homework:open"
HOMEWORK_START_PREFIX = "homework:start:"


def build_homework_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Домашка", callback_data=HOMEWORK_OPEN_CALLBACK)]
        ]
    )


def build_assignments_keyboard(assignments: list[dict[str, object]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=str(assignment["title"] or f"Задание #{assignment['id']}"),
                    callback_data=f"{HOMEWORK_START_PREFIX}{assignment['id']}",
                )
            ]
            for assignment in assignments
        ]
    )


@router.message(CommandStart())
async def start(message: Message) -> None:
    if message.from_user is None:
        return

    save_user(message.from_user)
    if student_has_active_homework(message.from_user.id):
        await message.answer(
            "У вас есть назначенная домашка.",
            reply_markup=build_homework_button(),
        )
        return

    await message.answer("Домашки пока нет. Для тренировки можно использовать /learn.")


@router.callback_query(lambda callback: callback.data == HOMEWORK_OPEN_CALLBACK)
async def open_homework(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None:
        return

    assignments = list_active_assignments(callback.from_user.id)
    if not assignments:
        await callback.message.answer("Активных заданий пока нет.")
        return

    await callback.message.answer(
        "Ваши задания:",
        reply_markup=build_assignments_keyboard(assignments),
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
        await callback.message.answer("Задание не найдено.")
        return
    except EmptyAssignmentError:
        await callback.message.answer("В задании пока нет слов.")
        return

    question = result["question"]
    if question is None:
        await callback.message.answer("Не удалось начать домашку.")
        return

    assignment_title = str(result.get("assignment_title") or "Домашка")
    await callback.message.answer(
        f"Домашка «{assignment_title}» началась.\n"
        f"Вопрос {question['question_number']}/{question['total_questions']}: "
        f"{question['prompt']}"
    )
