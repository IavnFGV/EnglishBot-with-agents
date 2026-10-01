from aiogram_dialog import DialogManager
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .command_registry import TOPICS_COMMAND
from .db import save_user
from .i18n import translate_for_user
from .runtime import router
from .topic_access import (
    EmptyTopicError,
    TopicAccessDeniedError,
    TopicNotFoundError,
    list_accessible_topics,
    start_topic_training_session,
)
from .training_handlers import render_started_training_session


TOPICS_START_PREFIX = "topics:start:"


def build_accessible_topics_keyboard(
    topics: list[dict[str, object]],
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=str(topic["title"]),
                    callback_data=f"{TOPICS_START_PREFIX}{topic['id']}",
                )
            ]
            for topic in topics
        ]
    )


@router.message(Command(TOPICS_COMMAND.name))
async def topics(message: Message) -> None:
    if message.from_user is None:
        return

    save_user(message.from_user)
    accessible_topics = list_accessible_topics(message.from_user.id)
    if not accessible_topics:
        await message.answer(translate_for_user(message.from_user.id, "topics.empty"))
        return

    await message.answer(
        translate_for_user(message.from_user.id, "topics.title"),
        reply_markup=build_accessible_topics_keyboard(accessible_topics),
    )


@router.callback_query(
    lambda callback: callback.data is not None
    and callback.data.startswith(TOPICS_START_PREFIX)
)
async def start_topic_training(callback: CallbackQuery, dialog_manager: DialogManager | None = None) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None or callback.data is None:
        return

    topic_id = int(callback.data.removeprefix(TOPICS_START_PREFIX))
    from .training import get_active_training_session
    session = get_active_training_session(callback.from_user.id)
    if session is None or session["source_topic_id"] != topic_id:
        from .topic_access import student_has_topic_access
        if not student_has_topic_access(callback.from_user.id, topic_id):
            await callback.message.answer(translate_for_user(callback.from_user.id, "topics.denied"))
            return
        if dialog_manager is not None:
            from .learner_training_dialog import start_training_mode_dialog
            await start_training_mode_dialog(callback.message, dialog_manager, topic_id)
        else:
            from .training_handlers import build_training_modes_keyboard
            await callback.message.edit_text(translate_for_user(callback.from_user.id, "training.mode.choose"),
                                             reply_markup=build_training_modes_keyboard(callback.from_user.id, topic_id))
        return
    try:
        result = start_topic_training_session(callback.from_user.id, topic_id)
    except TopicNotFoundError:
        await callback.message.answer(
            translate_for_user(callback.from_user.id, "topics.not_found")
        )
        return
    except TopicAccessDeniedError:
        await callback.message.answer(
            translate_for_user(callback.from_user.id, "topics.denied")
        )
        return
    except EmptyTopicError:
        await callback.message.answer(
            translate_for_user(callback.from_user.id, "topics.empty_topic")
        )
        return

    question = result["question"]
    if question is None:
        await callback.message.answer(
            translate_for_user(callback.from_user.id, "topics.start_failed")
        )
        return

    from .mini_app_handlers import offer_training_interfaces
    if not await offer_training_interfaces(callback.message, callback.from_user.id):
        await render_started_training_session(callback.message, callback.from_user.id)
