import sqlite3

from .db import DEFAULT_BOT_LANGUAGE, DEFAULT_USER_ROLE, ensure_user_exists, get_connection, utc_now
from .i18n import normalize_language_code


def get_user_profile(telegram_user_id: int) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT telegram_user_id, role, bot_language, created_at, updated_at
            FROM user_profiles
            WHERE telegram_user_id = ?
            """,
            (telegram_user_id,),
        ).fetchone()


def get_user_role(telegram_user_id: int) -> str:
    profile = get_user_profile(telegram_user_id)
    if profile is None:
        return DEFAULT_USER_ROLE
    return str(profile["role"])


def get_user_language(telegram_user_id: int) -> str:
    profile = get_user_profile(telegram_user_id)
    if profile is None:
        return DEFAULT_BOT_LANGUAGE
    return normalize_language_code(str(profile["bot_language"]))


def set_user_role(telegram_user_id: int, role: str) -> None:
    timestamp = utc_now()
    normalized_role = role or DEFAULT_USER_ROLE
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO user_profiles (
                telegram_user_id,
                role,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                role = excluded.role,
                updated_at = excluded.updated_at
            """,
            (telegram_user_id, normalized_role, timestamp, timestamp),
        )


def set_user_language(telegram_user_id: int, language_code: str) -> None:
    timestamp = utc_now()
    normalized_language = normalize_language_code(language_code)
    ensure_user_exists(telegram_user_id)
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO user_profiles (
                telegram_user_id,
                role,
                bot_language,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                bot_language = excluded.bot_language,
                updated_at = excluded.updated_at
            """,
            (
                telegram_user_id,
                DEFAULT_USER_ROLE,
                normalized_language,
                timestamp,
                timestamp,
            ),
        )
