from __future__ import annotations

from aiogram.enums.content_type import ContentType
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram_dialog import Dialog, DialogManager, ShowMode, StartMode, Window
from aiogram_dialog.api.entities.media import MediaAttachment
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Group, Row, ScrollingGroup, Select
from aiogram_dialog.widgets.media import DynamicMedia
from aiogram_dialog.widgets.text import Const, Format

from .i18n import translate_for_user
from .training import (
    append_medium_answer_letter,
    get_active_training_session,
    get_current_question,
    pop_medium_answer_letter,
    set_training_session_current_question_message_id,
    set_training_session_voice_message_id,
    skip_optional_hard,
    submit_medium_answer,
    submit_training_answer,
)
from .training_handlers import (
    delete_progress_message,
    delete_training_voice_message,
    edit_progress_message,
    ensure_training_progress_message,
    render_question_text,
    render_session_summary_text,
    resolve_question_photo_path,
)
from .tts import TTSClientError, TTSVoiceCatalog, build_tts_client, is_tts_enabled
from .user_profiles import get_user_tts_voice_id, set_user_tts_voice_id


DEFAULT_VOICE_OPTION_ID = "__default__"


class LearnerTrainingDialogSG(StatesGroup):
    quiz = State()
    voice = State()


def _get_user_id(dialog_manager: DialogManager) -> int:
    if dialog_manager.event.from_user is None:
        raise RuntimeError("Dialog event user is missing")
    return int(dialog_manager.event.from_user.id)


def _build_question_media(question: dict[str, object] | None) -> MediaAttachment | None:
    if question is None:
        return None
    photo_path = resolve_question_photo_path(question)
    if photo_path is None:
        return None
    return MediaAttachment(ContentType.PHOTO, path=photo_path)


async def start_training_dialog(
    message: Message,
    dialog_manager: DialogManager,
    telegram_user_id: int,
) -> bool:
    session, _question = await ensure_training_progress_message(message, telegram_user_id)
    if session is None:
        return False
    await _delete_legacy_question_message(message, session)
    set_training_session_current_question_message_id(int(session["id"]), None)
    await dialog_manager.start(
        LearnerTrainingDialogSG.quiz,
        mode=StartMode.RESET_STACK,
        show_mode=ShowMode.SEND,
    )
    return True


async def _delete_legacy_question_message(message: Message, session: object) -> None:
    question_message_id = session["current_question_message_id"]
    if question_message_id is None:
        return
    try:
        await message.bot.delete_message(
            chat_id=message.chat.id,
            message_id=int(question_message_id),
        )
    except Exception:
        return


def _build_easy_option_items(question: dict[str, object]) -> list[dict[str, str]]:
    options = question.get("options")
    if question.get("exercise_type") != "multiple_choice" or not isinstance(options, list):
        return []
    return [
        {"id": str(index), "label": str(option)}
        for index, option in enumerate(options)
    ]


def _build_medium_letter_items(question: dict[str, object]) -> list[dict[str, str | bool]]:
    if question.get("exercise_type") != "jumbled_letters":
        return []
    jumbled_letters = str(question.get("jumbled_letters") or "")
    selected_letter_indexes = {
        int(index)
        for index in question.get("selected_letter_indexes", [])
        if isinstance(index, int)
    }
    return [
        {
            "id": str(index),
            "label": "·" if index in selected_letter_indexes else letter,
            "is_placeholder": index in selected_letter_indexes,
        }
        for index, letter in enumerate(jumbled_letters)
    ]


def _build_voice_items(
    telegram_user_id: int,
    catalog: TTSVoiceCatalog,
) -> list[dict[str, str]]:
    saved_voice_id = get_user_tts_voice_id(telegram_user_id)
    items = [
        {
            "id": DEFAULT_VOICE_OPTION_ID,
            "label": translate_for_user(
                telegram_user_id,
                "settings.tts_voice_default_option.selected"
                if saved_voice_id is None
                else "settings.tts_voice_default_option",
            ),
        }
    ]
    for voice in catalog.voices:
        items.append(
            {
                "id": voice.voice_id,
                "label": translate_for_user(
                    telegram_user_id,
                    "settings.tts_voice_option.selected"
                    if saved_voice_id == voice.voice_id
                    else "settings.tts_voice_option",
                    voice_name=voice.button_label,
                ),
            }
        )
    return items


def _build_voice_screen_text(
    telegram_user_id: int,
    catalog: TTSVoiceCatalog | None,
) -> str:
    if catalog is None:
        return translate_for_user(telegram_user_id, "settings.tts_voice_unavailable")
    current_voice_id = catalog.resolve_voice_id(get_user_tts_voice_id(telegram_user_id))
    current_voice = catalog.find_voice(current_voice_id)
    voice_name = current_voice.display_name if current_voice is not None else current_voice_id
    return "\n".join(
        [
            translate_for_user(telegram_user_id, "settings.tts_voice_title"),
            translate_for_user(
                telegram_user_id,
                "settings.tts_voice_button",
                voice_name=voice_name,
            ),
        ]
    )


async def get_quiz_window_data(
    dialog_manager: DialogManager,
    **_: object,
) -> dict[str, object]:
    telegram_user_id = _get_user_id(dialog_manager)
    question = get_current_question(telegram_user_id)
    feedback = dialog_manager.dialog_data.get("feedback_text")
    if question is None:
        return {
            "screen_text": translate_for_user(telegram_user_id, "training.start_failed"),
            "question_media": None,
            "has_media": False,
            "easy_options": [],
            "medium_letters": [],
            "is_easy": False,
            "is_medium": False,
            "is_hard": False,
            "show_tts_controls": False,
            "listen_label": "",
            "voice_label": "",
            "backspace_label": "",
            "check_label": "",
            "skip_hard_label": "",
        }

    exercise_type = str(question.get("exercise_type") or "")
    return {
        "screen_text": render_question_text(
            telegram_user_id,
            question,
            feedback=str(feedback) if isinstance(feedback, str) and feedback else None,
        ),
        "question_media": _build_question_media(question),
        "has_media": _build_question_media(question) is not None,
        "easy_options": _build_easy_option_items(question),
        "medium_letters": _build_medium_letter_items(question),
        "is_easy": exercise_type == "multiple_choice",
        "is_medium": exercise_type == "jumbled_letters",
        "is_hard": exercise_type == "typed_answer" and bool(question.get("can_skip_hard")),
        "show_tts_controls": is_tts_enabled(),
        "listen_label": translate_for_user(telegram_user_id, "training.action.listen"),
        "voice_label": translate_for_user(telegram_user_id, "training.action.voice"),
        "backspace_label": translate_for_user(telegram_user_id, "training.action.backspace"),
        "check_label": translate_for_user(telegram_user_id, "training.action.check"),
        "skip_hard_label": translate_for_user(telegram_user_id, "training.action.skip_hard"),
    }


async def get_voice_window_data(
    dialog_manager: DialogManager,
    **_: object,
) -> dict[str, object]:
    telegram_user_id = _get_user_id(dialog_manager)
    client = build_tts_client()
    catalog = None
    if client is not None:
        try:
            catalog = client.fetch_voices()
        except TTSClientError:
            catalog = None
    return {
        "screen_text": _build_voice_screen_text(telegram_user_id, catalog),
        "voice_items": [] if catalog is None else _build_voice_items(telegram_user_id, catalog),
        "has_voices": catalog is not None,
        "back_label": translate_for_user(telegram_user_id, "homework.dialog.action.back"),
    }


def _build_feedback(telegram_user_id: int, result: dict[str, object]) -> str:
    if result.get("skipped_hard"):
        return translate_for_user(telegram_user_id, "training.hard_skipped")
    if bool(result.get("is_correct")):
        return translate_for_user(telegram_user_id, "training.correct")
    return translate_for_user(
        telegram_user_id,
        "training.incorrect",
        expected_answer=result["expected_answer"],
    )


async def _handle_result_transition(
    dialog_manager: DialogManager,
    anchor_message: Message,
    telegram_user_id: int,
    session: object,
    result: dict[str, object],
) -> None:
    feedback = _build_feedback(telegram_user_id, result)
    if result["status"] == "completed":
        summary = result["summary"]
        await edit_progress_message(
            anchor_message,
            telegram_user_id,
            session,
            question_number=int(summary["total_questions"]),
            total_questions=int(summary["total_questions"]),
            completed_items=int(summary["total_questions"]),
            stage_key="completed",
            hard_unlocked=False,
        )
        await delete_training_voice_message(anchor_message, session)
        await delete_progress_message(anchor_message, session)
        set_training_session_voice_message_id(int(session["id"]), None)
        dialog_manager.dialog_data.pop("feedback_text", None)
        await dialog_manager.done(show_mode=ShowMode.DELETE_AND_SEND)
        await anchor_message.answer(
            render_session_summary_text(
                telegram_user_id,
                session,
                feedback=feedback,
                total_questions=int(summary["total_questions"]),
                correct_answers=int(summary["correct_answers"]),
            )
        )
        return

    next_question = result["next_question"]
    await delete_training_voice_message(anchor_message, session)
    await edit_progress_message(
        anchor_message,
        telegram_user_id,
        session,
        question_number=int(next_question["question_number"]),
        total_questions=int(next_question["total_questions"]),
        completed_items=int(next_question["completed_items"]),
        stage_key=str(next_question["current_stage"]),
        hard_unlocked=bool(next_question["hard_unlocked"]),
    )
    dialog_manager.dialog_data["feedback_text"] = feedback
    await dialog_manager.switch_to(LearnerTrainingDialogSG.quiz, show_mode=ShowMode.EDIT)


async def _submit_easy_answer(
    callback: CallbackQuery,
    _widget: Select,
    dialog_manager: DialogManager,
    option_id: str,
) -> None:
    if callback.from_user is None or callback.message is None:
        return
    session = get_active_training_session(callback.from_user.id)
    question = get_current_question(callback.from_user.id)
    if session is None or question is None:
        return
    options = question.get("options")
    if not isinstance(options, list) or not option_id.isdigit():
        return
    index = int(option_id)
    if index < 0 or index >= len(options):
        return
    result = submit_training_answer(callback.from_user.id, str(options[index]))
    if result is None:
        return
    await _handle_result_transition(
        dialog_manager,
        callback.message,
        callback.from_user.id,
        session,
        result,
    )


async def _add_medium_letter(
    callback: CallbackQuery,
    _widget: Select,
    dialog_manager: DialogManager,
    letter_index: str,
) -> None:
    if callback.from_user is None or callback.message is None or not letter_index.isdigit():
        return
    question = get_current_question(callback.from_user.id)
    if question is None:
        return
    selected_letter_indexes = {
        int(index)
        for index in question.get("selected_letter_indexes", [])
        if isinstance(index, int)
    }
    if int(letter_index) in selected_letter_indexes:
        return
    refreshed_question = append_medium_answer_letter(callback.from_user.id, int(letter_index))
    if refreshed_question is None:
        return
    dialog_manager.dialog_data.pop("feedback_text", None)
    await dialog_manager.update({})


async def _backspace_medium_answer(
    callback: CallbackQuery,
    _button: Button,
    dialog_manager: DialogManager,
) -> None:
    if callback.from_user is None:
        return
    refreshed_question = pop_medium_answer_letter(callback.from_user.id)
    if refreshed_question is None:
        return
    dialog_manager.dialog_data.pop("feedback_text", None)
    await dialog_manager.update({})


async def _check_medium_answer(
    callback: CallbackQuery,
    _button: Button,
    dialog_manager: DialogManager,
) -> None:
    if callback.from_user is None or callback.message is None:
        return
    session = get_active_training_session(callback.from_user.id)
    question = get_current_question(callback.from_user.id)
    if session is None or question is None or str(question.get("exercise_type")) != "jumbled_letters":
        return
    result = submit_medium_answer(callback.from_user.id)
    if result is None:
        return
    await _handle_result_transition(
        dialog_manager,
        callback.message,
        callback.from_user.id,
        session,
        result,
    )


async def _skip_hard_answer(
    callback: CallbackQuery,
    _button: Button,
    dialog_manager: DialogManager,
) -> None:
    if callback.from_user is None or callback.message is None:
        return
    session = get_active_training_session(callback.from_user.id)
    if session is None:
        return
    result = skip_optional_hard(callback.from_user.id)
    if result is None:
        return
    await _handle_result_transition(
        dialog_manager,
        callback.message,
        callback.from_user.id,
        session,
        result,
    )


async def _submit_typed_answer(
    message: Message,
    _widget: MessageInput,
    dialog_manager: DialogManager,
) -> None:
    if message.from_user is None or message.text is None or message.text.startswith("/"):
        return
    session = get_active_training_session(message.from_user.id)
    question = get_current_question(message.from_user.id)
    if session is None or question is None or str(question.get("exercise_type")) != "typed_answer":
        return
    result = submit_training_answer(message.from_user.id, message.text)
    if result is None:
        return
    await _handle_result_transition(
        dialog_manager,
        message,
        message.from_user.id,
        session,
        result,
    )


async def _listen_to_current_word(
    callback: CallbackQuery,
    _button: Button,
    dialog_manager: DialogManager,
) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None:
        return
    question = get_current_question(callback.from_user.id)
    session = get_active_training_session(callback.from_user.id)
    if question is None or session is None:
        return
    client = build_tts_client()
    if client is None:
        return
    text_to_speak = str(question.get("expected_answer") or "").strip()
    if not text_to_speak:
        return
    try:
        catalog = client.fetch_voices()
        voice_id = catalog.resolve_voice_id(get_user_tts_voice_id(callback.from_user.id))
        audio_bytes = client.synthesize(text=text_to_speak, voice_id=voice_id)
        await delete_training_voice_message(callback.message, session)
        voice_message = await callback.message.answer_voice(
            BufferedInputFile(audio_bytes, filename="tts.ogg"),
        )
        set_training_session_voice_message_id(
            int(session["id"]),
            getattr(voice_message, "message_id", None),
        )
    except TTSClientError:
        await callback.message.answer(
            translate_for_user(callback.from_user.id, "training.audio_unavailable")
        )
    except Exception:
        await callback.message.answer(
            translate_for_user(callback.from_user.id, "training.audio_unavailable")
        )


async def _open_voice_picker(
    callback: CallbackQuery,
    _button: Button,
    dialog_manager: DialogManager,
) -> None:
    await callback.answer()
    await dialog_manager.switch_to(LearnerTrainingDialogSG.voice)


async def _select_voice(
    callback: CallbackQuery,
    _widget: Select,
    dialog_manager: DialogManager,
    voice_id: str,
) -> None:
    await callback.answer()
    if callback.from_user is None:
        return
    set_user_tts_voice_id(
        callback.from_user.id,
        None if voice_id == DEFAULT_VOICE_OPTION_ID else voice_id,
    )
    await dialog_manager.switch_to(LearnerTrainingDialogSG.quiz, show_mode=ShowMode.EDIT)


async def _return_to_quiz(
    callback: CallbackQuery,
    _button: Button,
    dialog_manager: DialogManager,
) -> None:
    await callback.answer()
    await dialog_manager.switch_to(LearnerTrainingDialogSG.quiz, show_mode=ShowMode.EDIT)


learner_training_dialog = Dialog(
    Window(
        DynamicMedia("question_media", when="has_media"),
        Format("{screen_text}"),
        Group(
            Select(
                Format("{item[label]}"),
                id="easy_option",
                item_id_getter=lambda item: item["id"],
                items="easy_options",
                on_click=_submit_easy_answer,
            ),
            width=1,
            when="is_easy",
        ),
        Group(
            Select(
                Format("{item[label]}"),
                id="medium_letter",
                item_id_getter=lambda item: item["id"],
                items="medium_letters",
                on_click=_add_medium_letter,
            ),
            width=4,
            when="is_medium",
        ),
        Row(
            Button(Format("{backspace_label}"), id="medium_backspace", on_click=_backspace_medium_answer),
            Button(Format("{check_label}"), id="medium_check", on_click=_check_medium_answer),
            when="is_medium",
        ),
        Row(
            Button(Format("{skip_hard_label}"), id="hard_skip", on_click=_skip_hard_answer, when="is_hard"),
        ),
        Row(
            Button(Format("{listen_label}"), id="tts_listen", on_click=_listen_to_current_word),
            Button(Format("{voice_label}"), id="tts_voice", on_click=_open_voice_picker),
            when="show_tts_controls",
        ),
        MessageInput(_submit_typed_answer, content_types=ContentType.TEXT),
        state=LearnerTrainingDialogSG.quiz,
        getter=get_quiz_window_data,
    ),
    Window(
        Format("{screen_text}"),
        ScrollingGroup(
            Select(
                Format("{item[label]}"),
                id="voice_select",
                item_id_getter=lambda item: item["id"],
                items="voice_items",
                on_click=_select_voice,
            ),
            id="voice_scroll",
            width=1,
            height=6,
            when="has_voices",
        ),
        Row(
            Button(Format("{back_label}"), id="voice_back", on_click=_return_to_quiz),
        ),
        state=LearnerTrainingDialogSG.voice,
        getter=get_voice_window_data,
    ),
)
