import logging

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, ErrorEvent, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .config import load_config


logger = logging.getLogger(__name__)
router = Router()
start_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Нажми меня", callback_data="press_me")]
    ]
)


@router.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer("Привет", reply_markup=start_keyboard)


@router.callback_query(lambda callback: callback.data == "press_me")
async def press_me(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer("Кнопка нажата")


@router.message()
async def echo_text(message: Message) -> None:
    if message.text is not None:
        await message.answer(f"Ты написал: {message.text}")


@router.errors()
async def on_error(event: ErrorEvent) -> None:
    logger.exception(
        "Unhandled exception while processing an update",
        exc_info=event.exception,
    )


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


def build_bot() -> Bot:
    token = load_config()
    return Bot(token=token)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    bot = build_bot()
    dispatcher = build_dispatcher()
    logger.info("Starting EnglishBot with long polling")
    await dispatcher.start_polling(bot)
