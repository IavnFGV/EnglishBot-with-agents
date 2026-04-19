import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from .config import load_config


logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        logger.info("Received /start without a message payload")
        return

    await message.reply_text("Привет")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled exception while processing an update", exc_info=context.error)


def build_application() -> Application:
    token = load_config()
    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_error_handler(on_error)
    return application


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    application = build_application()
    logger.info("Starting EnglishBot with long polling")
    application.run_polling()
