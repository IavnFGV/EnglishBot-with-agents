import logging

from .basic_topics_seed import seed_basic_topics
from .bot import configure_bot_commands, dispatcher
from .build_info import format_startup_banner, load_build_info
from .config import load_environment
from .db import init_db
from .logging_setup import configure_logging
from .runtime import build_bot


logger = logging.getLogger(__name__)


async def run() -> None:
    load_environment()
    configure_logging()
    logger.info(format_startup_banner(load_build_info()))

    init_db()
    seed_basic_topics()
    bot = build_bot()
    await configure_bot_commands(bot)
    logger.info("Starting EnglishBot with long polling")
    await dispatcher.start_polling(bot)
