import logging

from aiogram.filters import Command
from aiogram.types import ErrorEvent, Message
from aiogram_dialog import setup_dialogs

from .command_registry import BOT_COMMANDS, ME_COMMAND
from .db import count_text_interactions, get_user
from .homework_dialog import homework_dialog
from .i18n import translate_for_user
from .runtime import dispatcher, router
from .teacher_assignment_dialog import teacher_assignment_dialog
from .teacher_content_dialog import teacher_content_dialog
from .user_profiles import get_user_role
from . import cancel_handlers  # noqa: F401
from . import homework_handlers  # noqa: F401
from . import settings_handlers  # noqa: F401
from . import teacher_assignment_handlers  # noqa: F401
from . import teacher_content_handlers  # noqa: F401
from . import teacher_handlers  # noqa: F401
from . import topic_access_handlers  # noqa: F401
from . import training_handlers  # noqa: F401
from . import workbook_handlers  # noqa: F401


logger = logging.getLogger(__name__)

dispatcher.include_router(teacher_assignment_dialog)
dispatcher.include_router(homework_dialog)
dispatcher.include_router(teacher_content_dialog)
setup_dialogs(dispatcher)


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

@router.errors()
async def on_error(event: ErrorEvent) -> None:
    logger.exception(
        "Unhandled exception while processing an update",
        exc_info=event.exception,
    )
