from aiogram import Bot, Dispatcher, Router

from .audit import InteractionLoggingMiddleware, OutgoingLoggingMiddleware
from .config import load_config


router = Router()
dispatcher = Dispatcher()
dispatcher.update.outer_middleware(InteractionLoggingMiddleware())
dispatcher.include_router(router)


def build_bot() -> Bot:
    token = load_config()
    bot = Bot(token=token)
    bot.session.middleware(OutgoingLoggingMiddleware())
    return bot
