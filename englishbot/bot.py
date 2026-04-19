import logging

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import CommandStart
from aiogram.types import ErrorEvent, Message

from .config import load_config


logger = logging.getLogger(__name__)
router = Router()


@router.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer("Привет")


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
