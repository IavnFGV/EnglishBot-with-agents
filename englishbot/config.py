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


def get_owner_telegram_user_id() -> int | None:
    raw_value = os.getenv("ENGLISHBOT_OWNER_TELEGRAM_USER_ID")
    if raw_value is None or not raw_value.strip():
        return None
    try:
        return int(raw_value)
    except ValueError as exc:
        raise RuntimeError(
            "ENGLISHBOT_OWNER_TELEGRAM_USER_ID must be an integer Telegram user id."
        ) from exc
