import logging

from .basic_topics_seed import seed_basic_topics
from .bot import configure_bot_commands, dispatcher
from .build_info import format_startup_banner, load_build_info
from .config import load_environment
from .db import init_db
from .logging_setup import configure_logging
from .runtime import build_bot
from .status_server import (
    STATUS_SERVER_HOST,
    STATUS_SERVER_PORT,
    start_status_server,
)


logger = logging.getLogger(__name__)


async def run() -> None:
    load_environment()
    configure_logging()
    build_info = load_build_info()
    logger.info(format_startup_banner(build_info))

    init_db()
    seed_basic_topics()
    status_server = await start_status_server(build_info)
    logger.info(
        "EnglishBot status server listening on %s:%s",
        STATUS_SERVER_HOST,
        STATUS_SERVER_PORT,
    )
    bot = build_bot()
    try:
        await configure_bot_commands(bot)
        logger.info("Starting EnglishBot with long polling")
        await dispatcher.start_polling(bot)
    finally:
        status_server.close()
        await status_server.wait_closed()
