from aiogram import Bot, Dispatcher, Router
from aiogram.fsm.storage.memory import MemoryStorage

from .audit import InteractionLoggingMiddleware, OutgoingLoggingMiddleware
from .config import load_config


router = Router()
dispatcher = Dispatcher(storage=MemoryStorage())
dispatcher.update.outer_middleware(InteractionLoggingMiddleware())
dispatcher.include_router(router)


def build_bot() -> Bot:
    token = load_config()
    bot = Bot(token=token)
    bot.session.middleware(OutgoingLoggingMiddleware())
    return bot
