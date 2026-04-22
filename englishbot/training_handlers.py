from aiogram import F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .command_registry import LEARN_COMMAND
from .db import save_user
from .homework import (
    get_assignment_progress_snapshot,
    get_assignment,
)
from .i18n import translate_for_user
from .runtime import router
from .training import (
    NoLearningItemsError,
    append_medium_answer_letter,
    create_training_session,
    get_active_training_session,
    get_current_question,
    pop_medium_answer_letter,
    set_training_session_current_question_message_id,
    set_training_session_progress_message_id,
    skip_optional_hard,
    submit_training_answer,
)


TRAINING_EASY_CALLBACK_PREFIX = "training:easy:"
TRAINING_MEDIUM_ADD_CALLBACK_PREFIX = "training:medium:add:"
TRAINING_MEDIUM_BACKSPACE_CALLBACK = "training:medium:backspace"
TRAINING_MEDIUM_CHECK_CALLBACK = "training:medium:check"
TRAINING_HARD_SKIP_CALLBACK = "training:hard:skip"


def _get_session_assignment_id(session: object) -> int | None:
    if hasattr(session, "keys") and "assignment_id" in session.keys():
        assignment_id = session["assignment_id"]
        return None if assignment_id is None else int(assignment_id)
    if isinstance(session, dict):
        assignment_id = session.get("assignment_id")
        return None if assignment_id is None else int(assignment_id)
    return None


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


def _build_medium_keyboard(
    telegram_user_id: int,
    question: dict[str, object],
) -> InlineKeyboardMarkup | None:
    if question.get("exercise_type") != "jumbled_letters":
        return None
    jumbled_letters = str(question.get("jumbled_letters") or "")
    selected_letter_indexes = {
        int(index) for index in question.get("selected_letter_indexes", []) if isinstance(index, int)
    }
    rows: list[list[InlineKeyboardButton]] = []
    current_row: list[InlineKeyboardButton] = []
    for index, letter in enumerate(jumbled_letters):
        if index in selected_letter_indexes:
            button = InlineKeyboardButton(text="·", callback_data="placeholder")
        else:
            button = InlineKeyboardButton(
                text=letter,
                callback_data=f"{TRAINING_MEDIUM_ADD_CALLBACK_PREFIX}{index}",
            )
        current_row.append(button)
        if len(current_row) == 4:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    rows.append(
        [
            InlineKeyboardButton(
                text=translate_for_user(telegram_user_id, "training.action.backspace"),
                callback_data=TRAINING_MEDIUM_BACKSPACE_CALLBACK,
            ),
            InlineKeyboardButton(
                text=translate_for_user(telegram_user_id, "training.action.check"),
                callback_data=TRAINING_MEDIUM_CHECK_CALLBACK,
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _build_hard_keyboard(
    telegram_user_id: int,
    question: dict[str, object],
) -> InlineKeyboardMarkup | None:
    if not bool(question.get("can_skip_hard")):
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=translate_for_user(telegram_user_id, "training.action.skip_hard"),
                    callback_data=TRAINING_HARD_SKIP_CALLBACK,
                )
            ]
        ]
    )


def _build_question_keyboard(
    telegram_user_id: int,
    question: dict[str, object],
) -> InlineKeyboardMarkup | None:
    return (
        _build_easy_options_keyboard(question)
        or _build_medium_keyboard(telegram_user_id, question)
        or _build_hard_keyboard(telegram_user_id, question)
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


def _resolve_assignment_title(telegram_user_id: int, assignment_id: int) -> str:
    assignment = get_assignment(assignment_id)
    if assignment is not None and assignment["title"] is not None and str(assignment["title"]).strip():
        return str(assignment["title"])
    return translate_for_user(
        telegram_user_id,
        "homework.assignment_fallback",
        assignment_id=assignment_id,
    )


def _render_homework_progress_text(
    telegram_user_id: int,
    assignment_id: int,
    session_id: int,
) -> str:
    snapshot = get_assignment_progress_snapshot(assignment_id, session_id)
    item_statuses = " | ".join(
        translate_for_user(
            telegram_user_id,
            "homework.item_status.entry",
            item_number=item_number,
            status_label=translate_for_user(
                telegram_user_id,
                f"homework.item_status.{status_key}",
            ),
        )
        for item_number, status_key in enumerate(snapshot["item_statuses"], start=1)
    )
    return translate_for_user(
        telegram_user_id,
        "homework.progress",
        assignment_title=_resolve_assignment_title(telegram_user_id, assignment_id),
        completed_items=snapshot["completed_items"],
        total_items=snapshot["total_items"],
        current_item_position=snapshot["current_item_position"],
        stage_label=translate_for_user(
            telegram_user_id,
            f"training.stage.{snapshot['current_stage']}",
        ),
        item_statuses=item_statuses,
    )


def _render_session_progress_text(
    telegram_user_id: int,
    session: object,
    *,
    question_number: int,
    total_questions: int,
    completed_items: int,
    stage_key: str,
    hard_unlocked: bool,
) -> str:
    assignment_id = _get_session_assignment_id(session)
    if assignment_id is not None:
        return _render_homework_progress_text(
            telegram_user_id,
            assignment_id,
            int(session["id"]),
        )
    return _render_progress_text(
        telegram_user_id,
        question_number=question_number,
        total_questions=total_questions,
        completed_items=completed_items,
        stage_key=stage_key,
        hard_unlocked=hard_unlocked,
    )


def _render_session_summary_text(
    telegram_user_id: int,
    session: object,
    *,
    feedback: str,
    total_questions: int,
    correct_answers: int,
) -> str:
    assignment_id = _get_session_assignment_id(session)
    if assignment_id is not None:
        return translate_for_user(
            telegram_user_id,
            "homework.summary",
            feedback=feedback,
            assignment_title=_resolve_assignment_title(telegram_user_id, assignment_id),
            total_questions=total_questions,
            correct_answers=correct_answers,
        )
    return translate_for_user(
        telegram_user_id,
        "training.summary",
        feedback=feedback,
        total_questions=total_questions,
        correct_answers=correct_answers,
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
            answer_mask=question["medium_answer_mask"],
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
    session = get_active_training_session(telegram_user_id)
    question = get_current_question(telegram_user_id)
    if session is None or question is None:
        return

    progress_message = await message.answer(
        _render_session_progress_text(
            telegram_user_id,
            session,
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
        reply_markup=_build_question_keyboard(telegram_user_id, question),
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
    progress_text = _render_session_progress_text(
        telegram_user_id,
        session,
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
        reply_markup=_build_question_keyboard(telegram_user_id, question),
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

    if result.get("skipped_hard"):
        feedback = translate_for_user(telegram_user_id, "training.hard_skipped")
    elif result["is_correct"]:
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
            _render_session_summary_text(
                telegram_user_id,
                session,
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
    question = get_current_question(message.from_user.id)
    if question is None or str(question.get("exercise_type")) != "typed_answer":
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


async def _refresh_current_question_message(
    callback: CallbackQuery,
    telegram_user_id: int,
    question: dict[str, object],
) -> None:
    if callback.message is None:
        return
    try:
        await callback.message.bot.edit_message_text(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            text=_render_question_text(telegram_user_id, question),
            reply_markup=_build_question_keyboard(telegram_user_id, question),
        )
    except Exception:
        return


@router.callback_query(
    lambda callback: callback.data is not None
    and callback.data.startswith(TRAINING_MEDIUM_ADD_CALLBACK_PREFIX)
)
async def answer_training_medium_add(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None or callback.data is None:
        return
    letter_index = callback.data.removeprefix(TRAINING_MEDIUM_ADD_CALLBACK_PREFIX)
    if not letter_index.isdigit():
        return
    question = append_medium_answer_letter(callback.from_user.id, int(letter_index))
    if question is None:
        return
    await _refresh_current_question_message(callback, callback.from_user.id, question)


@router.callback_query(lambda callback: callback.data == TRAINING_MEDIUM_BACKSPACE_CALLBACK)
async def answer_training_medium_backspace(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None:
        return
    question = pop_medium_answer_letter(callback.from_user.id)
    if question is None:
        return
    await _refresh_current_question_message(callback, callback.from_user.id, question)


@router.callback_query(lambda callback: callback.data == TRAINING_MEDIUM_CHECK_CALLBACK)
async def answer_training_medium_check(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None:
        return
    question = get_current_question(callback.from_user.id)
    if question is None or str(question.get("exercise_type")) != "jumbled_letters":
        return
    await _process_training_answer(
        callback.message,
        callback.from_user.id,
        str(question["medium_answer"]),
    )


@router.callback_query(lambda callback: callback.data == TRAINING_HARD_SKIP_CALLBACK)
async def answer_training_hard_skip(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None:
        return

    session = get_active_training_session(callback.from_user.id)
    if session is None:
        return
    result = skip_optional_hard(callback.from_user.id)
    if result is None:
        return

    if result["status"] == "completed":
        await _edit_progress_message(
            callback.message,
            callback.from_user.id,
            session,
            question_number=int(result["summary"]["total_questions"]),
            total_questions=int(result["summary"]["total_questions"]),
            completed_items=int(result["summary"]["total_questions"]),
            stage_key="completed",
            hard_unlocked=False,
        )
        await _delete_previous_question_message(callback.message, session)
        set_training_session_current_question_message_id(int(session["id"]), None)
        await callback.message.answer(
            _render_session_summary_text(
                callback.from_user.id,
                session,
                feedback=translate_for_user(callback.from_user.id, "training.hard_skipped"),
                total_questions=int(result["summary"]["total_questions"]),
                correct_answers=int(result["summary"]["correct_answers"]),
            )
        )
        return

    next_question = result["next_question"]
    await _edit_progress_message(
        callback.message,
        callback.from_user.id,
        session,
        question_number=int(next_question["question_number"]),
        total_questions=int(next_question["total_questions"]),
        completed_items=int(next_question["completed_items"]),
        stage_key=str(next_question["current_stage"]),
        hard_unlocked=bool(next_question["hard_unlocked"]),
    )
    await _delete_previous_question_message(callback.message, session)
    await _send_next_question_message(
        callback.message,
        callback.from_user.id,
        next_question,
        feedback=translate_for_user(callback.from_user.id, "training.hard_skipped"),
    )
