import logging

from aiogram import F
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, ErrorEvent, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .db import count_text_interactions, get_user, init_db, save_user
from .runtime import build_bot, dispatcher, router


logger = logging.getLogger(__name__)
start_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Нажми меня", callback_data="press_me")]
    ]
)


@router.message(CommandStart())
async def start(message: Message) -> None:
    if message.from_user is not None:
        save_user(message.from_user)
    await message.answer("Привет", reply_markup=start_keyboard)


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
        f"saved_text_messages: {message_count}"
    )


@router.callback_query(lambda callback: callback.data == "press_me")
async def press_me(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer("Кнопка нажата")


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
