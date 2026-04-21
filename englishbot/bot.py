import logging

from aiogram import F
from aiogram.filters import Command
from aiogram.types import ErrorEvent, Message

from .basic_topics_seed import seed_basic_topics
from .command_registry import BOT_COMMANDS, ME_COMMAND
from .db import count_text_interactions, get_user, init_db
from .i18n import translate_for_user
from .runtime import build_bot, dispatcher, router
from .user_profiles import get_user_role
from . import cancel_handlers  # noqa: F401
from . import homework_handlers  # noqa: F401
from . import settings_handlers  # noqa: F401
from . import teacher_content_handlers  # noqa: F401
from . import teacher_handlers  # noqa: F401
from . import topic_access_handlers  # noqa: F401
from . import training_handlers  # noqa: F401
from . import workbook_handlers  # noqa: F401


logger = logging.getLogger(__name__)


async def configure_bot_commands(bot) -> None:
    await bot.set_my_commands(BOT_COMMANDS)


@router.message(Command(ME_COMMAND.name))
async def me(message: Message) -> None:
    if message.from_user is None:
        return

    user = get_user(message.from_user.id)
    display_name = (
        (user["first_name"] if user is not None else message.from_user.first_name)
        or (user["username"] if user is not None else message.from_user.username)
        or translate_for_user(message.from_user.id, "common.unnamed_user")
    )
    message_count = count_text_interactions(message.from_user.id)

    await message.answer(
        translate_for_user(
            message.from_user.id,
            "bot.profile",
            display_name=display_name,
            telegram_user_id=message.from_user.id,
            role=get_user_role(message.from_user.id),
            message_count=message_count,
        )
    )


@router.message(F.text)
async def echo_text(message: Message) -> None:
    if message.text is None or message.text.startswith("/"):
        return
    if message.from_user is None:
        return

    await message.answer(
        translate_for_user(message.from_user.id, "bot.echo", text=message.text)
    )


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
    seed_basic_topics()
    bot = build_bot()
    await configure_bot_commands(bot)
    logger.info("Starting EnglishBot with long polling")
    await dispatcher.start_polling(bot)
