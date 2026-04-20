from aiogram import F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .command_registry import LEARN_COMMAND
from .db import save_user
from .i18n import translate_for_user
from .runtime import router
from .training import (
    NoLearningItemsError,
    create_training_session,
    get_active_training_session,
    get_current_question,
    set_training_session_current_question_message_id,
    set_training_session_progress_message_id,
    submit_training_answer,
)


TRAINING_EASY_CALLBACK_PREFIX = "training:easy:"


def _build_easy_options_keyboard(question: dict[str, object]) -> InlineKeyboardMarkup | None:
    options = question.get("options")
    if question.get("exercise_type") != "multiple_choice" or not isinstance(options, list):
        return None
    if len(options) != 3:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=str(option),
                    callback_data=f"{TRAINING_EASY_CALLBACK_PREFIX}{index}",
                )
            ]
            for index, option in enumerate(options)
        ]
    )


def _render_progress_text(
    telegram_user_id: int,
    *,
    question_number: int,
    total_questions: int,
    completed_items: int,
    stage_key: str,
    hard_unlocked: bool,
) -> str:
    hard_unlocked_suffix = (
        translate_for_user(telegram_user_id, "training.hard_unlocked_suffix")
        if hard_unlocked
        else ""
    )
    return translate_for_user(
        telegram_user_id,
        "training.progress",
        question_number=question_number,
        total_questions=total_questions,
        completed_items=completed_items,
        stage_label=translate_for_user(telegram_user_id, f"training.stage.{stage_key}"),
        hard_unlocked_suffix=hard_unlocked_suffix,
    )


def _render_question_text(
    telegram_user_id: int,
    question: dict[str, object],
    *,
    feedback: str | None = None,
) -> str:
    prompt = str(question["prompt"])
    hint_text = str(question.get("hint_text") or prompt)
    question_text = prompt
    if question.get("exercise_type") == "multiple_choice":
        question_text = translate_for_user(
            telegram_user_id,
            "training.question.easy",
            prompt=prompt,
        )
    elif question.get("exercise_type") == "jumbled_letters":
        question_text = translate_for_user(
            telegram_user_id,
            "training.question.medium",
            hint_text=hint_text,
            jumbled_letters=question["jumbled_letters"],
        )
    elif question.get("exercise_type") == "typed_answer" and question.get("first_letter"):
        question_text = translate_for_user(
            telegram_user_id,
            "training.question.hard",
            hint_text=hint_text,
            first_letter=question["first_letter"],
        )
    if not feedback:
        return question_text
    return f"{feedback}\n{question_text}"


async def render_started_training_session(message: Message, telegram_user_id: int) -> None:
    question = get_current_question(telegram_user_id)
    if question is None:
        return

    progress_message = await message.answer(
        _render_progress_text(
            telegram_user_id,
            question_number=int(question["question_number"]),
            total_questions=int(question["total_questions"]),
            completed_items=int(question["completed_items"]),
            stage_key=str(question["current_stage"]),
            hard_unlocked=bool(question["hard_unlocked"]),
        )
    )
    set_training_session_progress_message_id(
        int(question["session_id"]),
        getattr(progress_message, "message_id", None),
    )

    question_message = await message.answer(
        _render_question_text(telegram_user_id, question),
        reply_markup=_build_easy_options_keyboard(question),
    )
    set_training_session_current_question_message_id(
        int(question["session_id"]),
        getattr(question_message, "message_id", None),
    )


async def _edit_progress_message(
    anchor_message: Message,
    telegram_user_id: int,
    session: object,
    *,
    question_number: int,
    total_questions: int,
    completed_items: int,
    stage_key: str,
    hard_unlocked: bool,
) -> None:
    progress_message_id = session["progress_message_id"]
    progress_text = _render_progress_text(
        telegram_user_id,
        question_number=question_number,
        total_questions=total_questions,
        completed_items=completed_items,
        stage_key=stage_key,
        hard_unlocked=hard_unlocked,
    )
    if progress_message_id is None:
        progress_message = await anchor_message.answer(progress_text)
        set_training_session_progress_message_id(
            int(session["id"]),
            getattr(progress_message, "message_id", None),
        )
        return

    try:
        await anchor_message.bot.edit_message_text(
            chat_id=anchor_message.chat.id,
            message_id=int(progress_message_id),
            text=progress_text,
        )
    except Exception:
        progress_message = await anchor_message.answer(progress_text)
        set_training_session_progress_message_id(
            int(session["id"]),
            getattr(progress_message, "message_id", None),
        )


async def _delete_previous_question_message(anchor_message: Message, session: object) -> None:
    question_message_id = session["current_question_message_id"]
    if question_message_id is None:
        return
    try:
        await anchor_message.bot.delete_message(
            chat_id=anchor_message.chat.id,
            message_id=int(question_message_id),
        )
    except Exception:
        return


async def _send_next_question_message(
    anchor_message: Message,
    telegram_user_id: int,
    question: dict[str, object],
    *,
    feedback: str | None = None,
) -> None:
    question_message = await anchor_message.answer(
        _render_question_text(telegram_user_id, question, feedback=feedback),
        reply_markup=_build_easy_options_keyboard(question),
    )
    set_training_session_current_question_message_id(
        int(question["session_id"]),
        getattr(question_message, "message_id", None),
    )


async def _process_training_answer(
    anchor_message: Message,
    telegram_user_id: int,
    answer_text: str,
) -> None:
    session = get_active_training_session(telegram_user_id)
    if session is None:
        return

    result = submit_training_answer(telegram_user_id, answer_text)
    if result is None:
        return

    if result["is_correct"]:
        feedback = translate_for_user(telegram_user_id, "training.correct")
    else:
        feedback = translate_for_user(
            telegram_user_id,
            "training.incorrect",
            expected_answer=result["expected_answer"],
        )

    if result["status"] == "completed":
        await _edit_progress_message(
            anchor_message,
            telegram_user_id,
            session,
            question_number=int(result["summary"]["total_questions"]),
            total_questions=int(result["summary"]["total_questions"]),
            completed_items=int(result["summary"]["total_questions"]),
            stage_key="completed",
            hard_unlocked=False,
        )
        await _delete_previous_question_message(anchor_message, session)
        set_training_session_current_question_message_id(int(session["id"]), None)
        summary = result["summary"]
        await anchor_message.answer(
            translate_for_user(
                telegram_user_id,
                "training.summary",
                feedback=feedback,
                total_questions=summary["total_questions"],
                correct_answers=summary["correct_answers"],
            )
        )
        return

    next_question = result["next_question"]
    await _edit_progress_message(
        anchor_message,
        telegram_user_id,
        session,
        question_number=int(next_question["question_number"]),
        total_questions=int(next_question["total_questions"]),
        completed_items=int(next_question["completed_items"]),
        stage_key=str(next_question["current_stage"]),
        hard_unlocked=bool(next_question["hard_unlocked"]),
    )
    await _delete_previous_question_message(anchor_message, session)
    await _send_next_question_message(
        anchor_message,
        telegram_user_id,
        next_question,
        feedback=feedback,
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

    await render_started_training_session(message, message.from_user.id)


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

    await _process_training_answer(message, message.from_user.id, message.text)


@router.callback_query(
    lambda callback: callback.data is not None
    and callback.data.startswith(TRAINING_EASY_CALLBACK_PREFIX)
)
async def answer_training_easy(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None or callback.data is None:
        return

    question = get_current_question(callback.from_user.id)
    if question is None:
        return

    options = question.get("options")
    if not isinstance(options, list):
        return
    option_index = callback.data.removeprefix(TRAINING_EASY_CALLBACK_PREFIX)
    if not option_index.isdigit():
        return
    index = int(option_index)
    if index < 0 or index >= len(options):
        return

    await _process_training_answer(callback.message, callback.from_user.id, str(options[index]))
