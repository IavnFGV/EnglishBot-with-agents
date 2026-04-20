from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .command_registry import SETTINGS_COMMAND
from .db import save_user
from .i18n import (
    SUPPORTED_LANGUAGE_CODES,
    get_language_label,
    translate_for_user,
)
from .runtime import router
from .user_profiles import (
    get_user_hint_language,
    get_user_language,
    set_user_hint_language,
    set_user_language,
)


SETTINGS_BOT_LANGUAGE_CALLBACK = "settings:bot-language"
SETTINGS_HINT_LANGUAGE_CALLBACK = "settings:hint-language"
SETTINGS_SET_BOT_LANGUAGE_PREFIX = "settings:set-bot-language:"
SETTINGS_SET_HINT_LANGUAGE_PREFIX = "settings:set-hint-language:"


def build_settings_keyboard(telegram_user_id: int) -> InlineKeyboardMarkup:
    current_bot_language = get_user_language(telegram_user_id)
    current_hint_language = get_user_hint_language(telegram_user_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=translate_for_user(
                        telegram_user_id,
                        "settings.bot_language_button",
                        language_name=get_language_label(current_bot_language),
                    ),
                    callback_data=SETTINGS_BOT_LANGUAGE_CALLBACK,
                )
            ],
            [
                InlineKeyboardButton(
                    text=translate_for_user(
                        telegram_user_id,
                        "settings.hint_language_button",
                        language_name=get_language_label(current_hint_language),
                    ),
                    callback_data=SETTINGS_HINT_LANGUAGE_CALLBACK,
                )
            ],
        ]
    )


def build_language_keyboard(callback_prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=get_language_label(language_code),
                    callback_data=f"{callback_prefix}{language_code}",
                )
            ]
            for language_code in SUPPORTED_LANGUAGE_CODES
        ]
    )


@router.message(Command(SETTINGS_COMMAND.name))
async def settings(message: Message) -> None:
    if message.from_user is None:
        return

    save_user(message.from_user)
    await message.answer(
        translate_for_user(message.from_user.id, "settings.title"),
        reply_markup=build_settings_keyboard(message.from_user.id),
    )


@router.callback_query(lambda callback: callback.data == SETTINGS_BOT_LANGUAGE_CALLBACK)
async def open_bot_language_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None:
        return

    await callback.message.answer(
        translate_for_user(callback.from_user.id, "settings.bot_language_title"),
        reply_markup=build_language_keyboard(SETTINGS_SET_BOT_LANGUAGE_PREFIX),
    )


@router.callback_query(
    lambda callback: callback.data is not None
    and callback.data.startswith(SETTINGS_SET_BOT_LANGUAGE_PREFIX)
)
async def set_bot_language(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None or callback.data is None:
        return

    language_code = callback.data.removeprefix(SETTINGS_SET_BOT_LANGUAGE_PREFIX)
    set_user_language(callback.from_user.id, language_code)
    await callback.message.answer(
        translate_for_user(
            callback.from_user.id,
            "settings.bot_language_changed",
            language_name=get_language_label(language_code),
        ),
        reply_markup=build_settings_keyboard(callback.from_user.id),
    )


@router.callback_query(lambda callback: callback.data == SETTINGS_HINT_LANGUAGE_CALLBACK)
async def open_hint_language_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None:
        return

    await callback.message.answer(
        translate_for_user(callback.from_user.id, "settings.hint_language_title"),
        reply_markup=build_language_keyboard(SETTINGS_SET_HINT_LANGUAGE_PREFIX),
    )


@router.callback_query(
    lambda callback: callback.data is not None
    and callback.data.startswith(SETTINGS_SET_HINT_LANGUAGE_PREFIX)
)
async def set_hint_language(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None or callback.data is None:
        return

    language_code = callback.data.removeprefix(SETTINGS_SET_HINT_LANGUAGE_PREFIX)
    set_user_hint_language(callback.from_user.id, language_code)
    await callback.message.answer(
        translate_for_user(
            callback.from_user.id,
            "settings.hint_language_changed",
            language_name=get_language_label(language_code),
        ),
        reply_markup=build_settings_keyboard(callback.from_user.id),
    )
