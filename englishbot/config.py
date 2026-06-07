import os
from pathlib import Path

from dotenv import load_dotenv


DEFAULT_TTS_TIMEOUT_SECONDS = 5.0
DEFAULT_TTS_MODEL_KEY = "internal-tts"
DEFAULT_ENV_PATH = Path(".env")
DEFAULT_INFRA_RUNTIME_ENV_PATH = Path("/srv/services/englishbot/infra-runtime.env")


def load_environment() -> None:
    load_dotenv(dotenv_path=DEFAULT_ENV_PATH)
    load_dotenv(dotenv_path=DEFAULT_INFRA_RUNTIME_ENV_PATH, override=True)


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


def get_tts_base_url() -> str | None:
    raw_value = os.getenv("ENGLISHBOT_TTS_BASE_URL")
    if raw_value is None:
        return None
    normalized = raw_value.strip().rstrip("/")
    if not normalized:
        return None
    return normalized


def get_tts_timeout_seconds() -> float:
    raw_value = os.getenv("ENGLISHBOT_TTS_TIMEOUT_SECONDS")
    if raw_value is None or not raw_value.strip():
        return DEFAULT_TTS_TIMEOUT_SECONDS
    try:
        timeout_seconds = float(raw_value)
    except ValueError:
        return DEFAULT_TTS_TIMEOUT_SECONDS
    if timeout_seconds <= 0:
        return DEFAULT_TTS_TIMEOUT_SECONDS
    return timeout_seconds


def get_tts_model_key() -> str:
    raw_value = os.getenv("ENGLISHBOT_TTS_MODEL_KEY")
    if raw_value is None:
        return DEFAULT_TTS_MODEL_KEY
    normalized = raw_value.strip()
    if not normalized:
        return DEFAULT_TTS_MODEL_KEY
    return normalized


def get_infra_static_base_url() -> str | None:
    raw_value = os.getenv("INFRA_STATIC_BASE_URL")
    if raw_value is None:
        return None
    normalized = raw_value.strip().rstrip("/")
    if not normalized:
        return None
    return normalized
