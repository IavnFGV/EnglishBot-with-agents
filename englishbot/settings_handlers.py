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
from .tts import TTSClientError, build_tts_client, is_tts_enabled
from .user_profiles import (
    get_user_hint_language,
    get_user_language,
    get_user_tts_voice_id,
    set_user_hint_language,
    set_user_language,
    set_user_tts_voice_id,
)


SETTINGS_BOT_LANGUAGE_CALLBACK = "settings:bot-language"
SETTINGS_HINT_LANGUAGE_CALLBACK = "settings:hint-language"
SETTINGS_SET_BOT_LANGUAGE_PREFIX = "settings:set-bot-language:"
SETTINGS_SET_HINT_LANGUAGE_PREFIX = "settings:set-hint-language:"
SETTINGS_TTS_VOICE_CALLBACK = "settings:tts-voice"
SETTINGS_SET_TTS_VOICE_PREFIX = "settings:set-tts-voice:"
SETTINGS_SET_TTS_DEFAULT_CALLBACK = "settings:set-tts-default"


def _get_saved_voice_button_label(telegram_user_id: int) -> str:
    saved_voice_id = get_user_tts_voice_id(telegram_user_id)
    if saved_voice_id is None:
        return translate_for_user(telegram_user_id, "settings.tts_voice_default")
    client = build_tts_client()
    if client is None:
        return saved_voice_id
    try:
        voice = client.fetch_voices().find_voice(saved_voice_id)
    except TTSClientError:
        return saved_voice_id
    if voice is None:
        return saved_voice_id
    return voice.display_name


def build_settings_keyboard(telegram_user_id: int) -> InlineKeyboardMarkup:
    current_bot_language = get_user_language(telegram_user_id)
    current_hint_language = get_user_hint_language(telegram_user_id)
    rows = [
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
    if is_tts_enabled():
        rows.append(
            [
                InlineKeyboardButton(
                    text=translate_for_user(
                        telegram_user_id,
                        "settings.tts_voice_button",
                        voice_name=_get_saved_voice_button_label(telegram_user_id),
                    ),
                    callback_data=SETTINGS_TTS_VOICE_CALLBACK,
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


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


def _build_tts_voice_keyboard(
    telegram_user_id: int,
    voice_rows: list[tuple[str, str]],
) -> InlineKeyboardMarkup:
    saved_voice_id = get_user_tts_voice_id(telegram_user_id)
    rows = [
        [
            InlineKeyboardButton(
                text=translate_for_user(
                    telegram_user_id,
                    "settings.tts_voice_default_option.selected"
                    if saved_voice_id is None
                    else "settings.tts_voice_default_option",
                ),
                callback_data=SETTINGS_SET_TTS_DEFAULT_CALLBACK,
            )
        ]
    ]
    for voice_id, button_label in voice_rows:
        translation_key = (
            "settings.tts_voice_option.selected"
            if saved_voice_id == voice_id
            else "settings.tts_voice_option"
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=translate_for_user(
                        telegram_user_id,
                        translation_key,
                        voice_name=button_label,
                    ),
                    callback_data=f"{SETTINGS_SET_TTS_VOICE_PREFIX}{voice_id}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


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


@router.callback_query(lambda callback: callback.data == SETTINGS_TTS_VOICE_CALLBACK)
async def open_tts_voice_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None:
        return
    client = build_tts_client()
    if client is None:
        return
    try:
        catalog = client.fetch_voices()
    except TTSClientError:
        await callback.message.answer(
            translate_for_user(callback.from_user.id, "settings.tts_voice_unavailable")
        )
        return

    voice_rows = [(voice.voice_id, voice.button_label) for voice in catalog.voices]
    await callback.message.answer(
        translate_for_user(callback.from_user.id, "settings.tts_voice_title"),
        reply_markup=_build_tts_voice_keyboard(callback.from_user.id, voice_rows),
    )


@router.callback_query(lambda callback: callback.data == SETTINGS_SET_TTS_DEFAULT_CALLBACK)
async def set_tts_default_voice(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None:
        return
    set_user_tts_voice_id(callback.from_user.id, None)
    await callback.message.answer(
        translate_for_user(
            callback.from_user.id,
            "settings.tts_voice_changed",
            voice_name=translate_for_user(callback.from_user.id, "settings.tts_voice_default"),
        ),
        reply_markup=build_settings_keyboard(callback.from_user.id),
    )


@router.callback_query(
    lambda callback: callback.data is not None
    and callback.data.startswith(SETTINGS_SET_TTS_VOICE_PREFIX)
)
async def set_tts_voice(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None or callback.data is None:
        return

    voice_id = callback.data.removeprefix(SETTINGS_SET_TTS_VOICE_PREFIX)
    client = build_tts_client()
    if client is None:
        return
    try:
        catalog = client.fetch_voices()
    except TTSClientError:
        await callback.message.answer(
            translate_for_user(callback.from_user.id, "settings.tts_voice_unavailable")
        )
        return
    voice = catalog.find_voice(voice_id)
    if voice is None:
        await callback.message.answer(
            translate_for_user(callback.from_user.id, "settings.tts_voice_unavailable")
        )
        return

    set_user_tts_voice_id(callback.from_user.id, voice.voice_id)
    await callback.message.answer(
        translate_for_user(
            callback.from_user.id,
            "settings.tts_voice_changed",
            voice_name=voice.display_name,
        ),
        reply_markup=build_settings_keyboard(callback.from_user.id),
    )
