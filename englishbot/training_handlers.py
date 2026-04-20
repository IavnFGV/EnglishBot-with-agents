from aiogram import F
from aiogram.filters import Command
from aiogram.types import Message

from .command_registry import LEARN_COMMAND
from .db import save_user
from .i18n import translate_for_user
from .runtime import router
from .training import (
    NoLearningItemsError,
    create_training_session,
    get_active_training_session,
    submit_training_answer,
)


@router.message(Command(LEARN_COMMAND.name))
async def learn(message: Message) -> None:
    if message.from_user is None:
        return

    save_user(message.from_user)
    try:
        result = create_training_session(message.from_user.id)
    except NoLearningItemsError:
        await message.answer(translate_for_user(message.from_user.id, "training.no_items"))
        return

    question = result["question"]
    if question is None:
        await message.answer(translate_for_user(message.from_user.id, "training.start_failed"))
        return

    await message.answer(
        translate_for_user(
            message.from_user.id,
            "training.started",
            question_number=question["question_number"],
            total_questions=question["total_questions"],
            prompt=question["prompt"],
        )
    )


@router.message(
    F.text,
    ~F.text.startswith("/"),
    lambda message: (
        message.from_user is not None and get_active_training_session(message.from_user.id) is not None
    ),
)
async def answer_training_question(message: Message) -> None:
    if message.from_user is None or message.text is None:
        return

    result = submit_training_answer(message.from_user.id, message.text)
    if result is None:
        return

    if result["is_correct"]:
        feedback = translate_for_user(message.from_user.id, "training.correct")
    else:
        feedback = translate_for_user(
            message.from_user.id,
            "training.incorrect",
            expected_answer=result["expected_answer"],
        )

    if result["status"] == "completed":
        summary = result["summary"]
        await message.answer(
            translate_for_user(
                message.from_user.id,
                "training.summary",
                feedback=feedback,
                total_questions=summary["total_questions"],
                correct_answers=summary["correct_answers"],
            )
        )
        return

    next_question = result["next_question"]
    await message.answer(
        translate_for_user(
            message.from_user.id,
            "training.next_question",
            feedback=feedback,
            question_number=next_question["question_number"],
            total_questions=next_question["total_questions"],
            prompt=next_question["prompt"],
        )
    )
