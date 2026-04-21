import os

from dotenv import load_dotenv


def load_environment() -> None:
    load_dotenv(dotenv_path=".env")


def load_config() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. Add it to the environment or a .env file."
        )

    return token
