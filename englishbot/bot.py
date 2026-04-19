import logging

from aiogram import F
from aiogram.filters import Command
from aiogram.types import ErrorEvent, Message

from .db import count_text_interactions, get_user, init_db
from .runtime import build_bot, dispatcher, router
from .user_profiles import get_user_role
from . import homework_handlers  # noqa: F401
from . import teacher_handlers  # noqa: F401
from . import training_handlers  # noqa: F401


logger = logging.getLogger(__name__)


@router.message(Command("me"))
async def me(message: Message) -> None:
    if message.from_user is None:
        return

    user = get_user(message.from_user.id)
    display_name = (
        (user["first_name"] if user is not None else message.from_user.first_name)
        or (user["username"] if user is not None else message.from_user.username)
        or "Без имени"
    )
    message_count = count_text_interactions(message.from_user.id)

    await message.answer(
        f"{display_name}\n"
        f"telegram_user_id: {message.from_user.id}\n"
        f"role: {get_user_role(message.from_user.id)}\n"
        f"saved_text_messages: {message_count}"
    )


@router.message(F.text)
async def echo_text(message: Message) -> None:
    if message.text is None or message.text.startswith("/"):
        return
    if message.from_user is None:
        return

    await message.answer(f"Ты написал: {message.text}")


@router.errors()
async def on_error(event: ErrorEvent) -> None:
    logger.exception(
        "Unhandled exception while processing an update",
        exc_info=event.exception,
    )


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    init_db()
    bot = build_bot()
    logger.info("Starting EnglishBot with long polling")
    await dispatcher.start_polling(bot)
