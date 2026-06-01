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
def is_simple_mode_enabled() -> bool:
    raw_value = os.getenv("ENGLISHBOT_SIMPLE_MODE", "").strip().lower()
    return raw_value in {"1", "true", "yes", "on"}
