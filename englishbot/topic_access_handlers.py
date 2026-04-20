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
async def start_topic_training(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None or callback.data is None:
        return

    topic_id = int(callback.data.removeprefix(TOPICS_START_PREFIX))
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

    await render_started_training_session(callback.message, callback.from_user.id)
