from aiogram import F
from aiogram.filters import Command
from aiogram.types import Message

from .db import save_user
from .runtime import router
from .training import (
    NoLearningItemsError,
    create_training_session,
    get_active_training_session,
    submit_training_answer,
)


@router.message(Command("learn"))
async def learn(message: Message) -> None:
    if message.from_user is None:
        return

    save_user(message.from_user)
    try:
        result = create_training_session(message.from_user.id)
    except NoLearningItemsError:
        await message.answer("Нет слов для тренировки.")
        return

    question = result["question"]
    if question is None:
        await message.answer("Не удалось начать тренировку.")
        return

    await message.answer(
        f"Тренировка началась.\n"
        f"Вопрос {question['question_number']}/{question['total_questions']}: "
        f"{question['prompt']}"
    )


@router.message(
    F.text,
    lambda message: (
        message.from_user is not None and get_active_training_session(message.from_user.id) is not None
    ),
)
async def answer_training_question(message: Message) -> None:
    if message.from_user is None or message.text is None or message.text.startswith("/"):
        return

    result = submit_training_answer(message.from_user.id, message.text)
    if result is None:
        return

    if result["is_correct"]:
        feedback = "Верно."
    else:
        feedback = f"Неверно. Правильный ответ: {result['expected_answer']}."

    if result["status"] == "completed":
        summary = result["summary"]
        await message.answer(
            f"{feedback}\n"
            f"Итог: {summary['total_questions']} вопросов, "
            f"{summary['correct_answers']} правильных ответов."
        )
        return

    next_question = result["next_question"]
    await message.answer(
        f"{feedback}\n"
        f"Вопрос {next_question['question_number']}/{next_question['total_questions']}: "
        f"{next_question['prompt']}"
    )
