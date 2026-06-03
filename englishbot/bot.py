import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import ErrorEvent, Message
from aiogram_dialog import setup_dialogs
from aiogram_dialog.api.exceptions import UnknownIntent

from .command_registry import BOT_COMMANDS, HELP_COMMAND, ME_COMMAND, START_COMMAND
from .db import count_text_interactions, get_user, save_user
from .families import create_family, get_user_family
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
from . import topic_access_handlers  # noqa: F401
from . import training_handlers  # noqa: F401


logger = logging.getLogger(__name__)
unhandled_router = Router()

dispatcher.include_router(teacher_assignment_dialog)
dispatcher.include_router(homework_dialog)
dispatcher.include_router(teacher_content_dialog)
dispatcher.include_router(unhandled_router)
setup_dialogs(dispatcher)


async def configure_bot_commands(bot) -> None:
    await bot.set_my_commands(BOT_COMMANDS)


@router.message(Command(START_COMMAND.name))
async def start_command(message: Message) -> None:
    if message.from_user is None:
        return

    save_user(message.from_user)
    family = get_user_family(message.from_user.id)
    created_family = False
    if family is None:
        family = create_family("Home", message.from_user.id)
        created_family = True

    await message.answer(
        translate_for_user(
            message.from_user.id,
            "bot.start",
            family_name=str(family["name"] or "Home"),
            created_family_suffix=(
                "\n\n" + translate_for_user(message.from_user.id, "bot.start.family_created")
                if created_family
                else ""
            ),
        )
    )


@router.message(Command(HELP_COMMAND.name))
async def help_command(message: Message) -> None:
    if message.from_user is None:
        return

    await message.answer(
        translate_for_user(
            message.from_user.id,
            "bot.help",
        )
    )


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

@unhandled_router.message()
async def unhandled_message(message: Message) -> None:
    """
    Catches any messages or commands that were not handled by other routers.
    Logs them as a warning for visibility.
    """
    user_id = message.from_user.id if message.from_user else "Unknown"
    text = message.text or message.caption or "[No text]"
    logger.warning("Unhandled message or command from user %s: %s", user_id, text)

@dispatcher.errors()
async def on_error(event: ErrorEvent) -> None:
    """
    Global error handler. Specifically catches UnknownIntent (often due to expired 
    aiogram-dialog sessions) and logs them as a warning.
    """
    if isinstance(event.exception, UnknownIntent):
        user_id = (
            event.update.callback_query.from_user.id 
            if event.update.callback_query 
            else "Unknown"
        )
        logger.warning("Unknown dialog intent detected for user %s", user_id)
        return

    logger.exception(
        "Unhandled exception while processing an update",
        exc_info=event.exception,
    )
