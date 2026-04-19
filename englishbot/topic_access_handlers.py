from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .db import save_user
from .runtime import router
from .topic_access import (
    EmptyTopicError,
    TopicAccessDeniedError,
    TopicNotFoundError,
    list_accessible_topics,
    start_topic_training_session,
)


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


@router.message(Command("topics"))
async def topics(message: Message) -> None:
    if message.from_user is None:
        return

    save_user(message.from_user)
    accessible_topics = list_accessible_topics(message.from_user.id)
    if not accessible_topics:
        await message.answer("Доступных тем пока нет.")
        return

    await message.answer(
        "Доступные темы:",
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
        await callback.message.answer("Тема не найдена.")
        return
    except TopicAccessDeniedError:
        await callback.message.answer("Эта тема вам пока недоступна.")
        return
    except EmptyTopicError:
        await callback.message.answer("В этой теме пока нет слов.")
        return

    question = result["question"]
    if question is None:
        await callback.message.answer("Не удалось начать тренировку по теме.")
        return

    await callback.message.answer(
        f"Тема «{result['topic_title']}» открыта.\n"
        f"Вопрос {question['question_number']}/{question['total_questions']}: "
        f"{question['prompt']}"
    )
