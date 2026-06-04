import logging
from typing import Any

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import BotCommandScopeChat, BotCommandScopeDefault, CallbackQuery, ErrorEvent, Message
from aiogram_dialog import setup_dialogs
from aiogram_dialog.api.exceptions import UnknownIntent

from .command_registry import BOT_COMMANDS, HELP_COMMAND, ME_COMMAND, START_COMMAND, build_bot_commands
from .config import get_owner_telegram_user_id
from .db import count_text_interactions, get_user, save_user
from .families import ensure_user_family, get_user_family
from .homework_dialog import homework_dialog
from .i18n import translate_for_user
from .runtime import dispatcher, router
from .teacher_assignment_dialog import teacher_assignment_dialog
from .teacher_content_dialog import teacher_content_dialog
from .telegram_media_storage import telegram_media_id_storage
from .user_profiles import get_user_role
from . import cancel_handlers  # noqa: F401
from . import bulk_edit_handlers  # noqa: F401
from . import homework_handlers  # noqa: F401
from . import owner_handlers  # noqa: F401
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
setup_dialogs(dispatcher, media_id_storage=telegram_media_id_storage)


async def configure_bot_commands(bot) -> None:
    owner_user_id = get_owner_telegram_user_id()
    await bot.set_my_commands(
        build_bot_commands(),
        scope=BotCommandScopeDefault(),
    )
    if owner_user_id is not None:
        await bot.set_my_commands(
            build_bot_commands(include_owner_commands=True),
            scope=BotCommandScopeChat(chat_id=owner_user_id),
        )


def _is_owner_user(user_id: int) -> bool:
    owner_user_id = get_owner_telegram_user_id()
    return owner_user_id is None or user_id == owner_user_id


def _is_message_not_modified_error(exception: BaseException) -> bool:
    return isinstance(exception, TelegramBadRequest) and "message is not modified" in str(exception)


def _extract_callback_context(event: ErrorEvent) -> tuple[int | None, int | None, Any | None]:
    callback_query: CallbackQuery | None = event.update.callback_query
    if callback_query is None:
        return None, None, None
    user_id = callback_query.from_user.id if callback_query.from_user is not None else None
    message = callback_query.message
    chat_id = message.chat.id if message is not None and message.chat is not None else user_id
    bot = message.bot if message is not None else getattr(callback_query, "bot", None)
    return user_id, chat_id, bot


async def _notify_unknown_intent_user(event: ErrorEvent) -> None:
    user_id, chat_id, bot = _extract_callback_context(event)
    if user_id is None or chat_id is None or bot is None:
        return
    await bot.send_message(
        chat_id=chat_id,
        text=translate_for_user(user_id, "flow.session_expired"),
    )


@router.message(Command(START_COMMAND.name))
async def start_command(message: Message) -> None:
    if message.from_user is None:
        return

    save_user(message.from_user)
    family = get_user_family(message.from_user.id)
    owner_user_id = get_owner_telegram_user_id()
    created_family = False
    if family is None:
        if owner_user_id is not None and message.from_user.id != owner_user_id:
            await message.answer(
                translate_for_user(
                    message.from_user.id,
                    "bot.start.pending_access",
                    telegram_user_id=message.from_user.id,
                )
            )
            return
        family = ensure_user_family(message.from_user.id)
        created_family = True

    await message.answer(
        translate_for_user(
            message.from_user.id,
            "bot.start.owner" if _is_owner_user(message.from_user.id) else "bot.start",
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
            "bot.help.owner" if _is_owner_user(message.from_user.id) else "bot.help",
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
        user_id = event.update.callback_query.from_user.id if event.update.callback_query else "Unknown"
        logger.warning("Unknown dialog intent detected for user %s", user_id)
        try:
            await _notify_unknown_intent_user(event)
        except Exception:
            logger.exception("Failed to notify user about expired dialog intent")
        return

    if _is_message_not_modified_error(event.exception):
        logger.debug("Ignoring Telegram no-op edit: %s", event.exception)
        return

    logger.exception(
        "Unhandled exception while processing an update",
        exc_info=event.exception,
    )
