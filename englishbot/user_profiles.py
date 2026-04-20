import sqlite3

from .db import (
    DEFAULT_BOT_LANGUAGE,
    DEFAULT_HINT_LANGUAGE,
    DEFAULT_USER_ROLE,
    ensure_user_exists,
    get_connection,
    utc_now,
)
from .i18n import normalize_language_code


def is_supported_language(language_code: str | None) -> bool:
    return language_code in {"en", "ru", "uk", "bg"}


def _normalize_supported_language(language_code: str | None) -> str | None:
    if language_code is None:
        return None
    normalized_language = str(language_code).strip()
    if is_supported_language(normalized_language):
        return normalized_language
    return None


def get_user_profile(telegram_user_id: int) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT telegram_user_id, role, bot_language, hint_language, created_at, updated_at
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


def get_user_hint_language(telegram_user_id: int) -> str:
    profile = get_user_profile(telegram_user_id)
    if profile is None:
        return DEFAULT_HINT_LANGUAGE
    hint_language = _normalize_supported_language(profile["hint_language"])
    if hint_language is not None:
        return hint_language
    bot_language = _normalize_supported_language(profile["bot_language"])
    if bot_language is not None:
        return bot_language
    return DEFAULT_HINT_LANGUAGE


def set_user_role(telegram_user_id: int, role: str) -> None:
    timestamp = utc_now()
    normalized_role = role or DEFAULT_USER_ROLE
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO user_profiles (
                telegram_user_id,
                role,
                bot_language,
                hint_language,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                role = excluded.role,
                updated_at = excluded.updated_at
            """,
            (
                telegram_user_id,
                normalized_role,
                DEFAULT_BOT_LANGUAGE,
                DEFAULT_HINT_LANGUAGE,
                timestamp,
                timestamp,
            ),
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
                hint_language,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                bot_language = excluded.bot_language,
                hint_language = CASE
                    WHEN user_profiles.hint_language IS NULL
                      OR TRIM(user_profiles.hint_language) = ''
                      OR user_profiles.hint_language NOT IN ('en', 'ru', 'uk', 'bg')
                    THEN excluded.bot_language
                    ELSE user_profiles.hint_language
                END,
                updated_at = excluded.updated_at
            """,
            (
                telegram_user_id,
                DEFAULT_USER_ROLE,
                normalized_language,
                normalized_language,
                timestamp,
                timestamp,
            ),
        )


def set_user_hint_language(telegram_user_id: int, language_code: str) -> None:
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
                hint_language,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                hint_language = excluded.hint_language,
                updated_at = excluded.updated_at
            """,
            (
                telegram_user_id,
                DEFAULT_USER_ROLE,
                DEFAULT_BOT_LANGUAGE,
                normalized_language,
                timestamp,
                timestamp,
            ),
        )
