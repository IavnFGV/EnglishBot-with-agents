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
from .user_profiles import get_user_language, set_user_language


SETTINGS_LANGUAGE_CALLBACK = "settings:language"
SETTINGS_SET_LANGUAGE_PREFIX = "settings:set-language:"


def build_settings_keyboard(telegram_user_id: int) -> InlineKeyboardMarkup:
    current_language = get_user_language(telegram_user_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=translate_for_user(
                        telegram_user_id,
                        "settings.language_button",
                        language_name=get_language_label(current_language),
                    ),
                    callback_data=SETTINGS_LANGUAGE_CALLBACK,
                )
            ]
        ]
    )


def build_language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=get_language_label(language_code),
                    callback_data=f"{SETTINGS_SET_LANGUAGE_PREFIX}{language_code}",
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


@router.callback_query(lambda callback: callback.data == SETTINGS_LANGUAGE_CALLBACK)
async def open_language_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None:
        return

    await callback.message.answer(
        translate_for_user(callback.from_user.id, "settings.language_title"),
        reply_markup=build_language_keyboard(),
    )


@router.callback_query(
    lambda callback: callback.data is not None
    and callback.data.startswith(SETTINGS_SET_LANGUAGE_PREFIX)
)
async def set_language(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None or callback.data is None:
        return

    language_code = callback.data.removeprefix(SETTINGS_SET_LANGUAGE_PREFIX)
    set_user_language(callback.from_user.id, language_code)
    await callback.message.answer(
        translate_for_user(
            callback.from_user.id,
            "settings.language_changed",
            language_name=get_language_label(language_code),
        ),
        reply_markup=build_settings_keyboard(callback.from_user.id),
    )
