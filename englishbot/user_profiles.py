import sqlite3

from .db import DEFAULT_USER_ROLE, get_connection, utc_now


def get_user_profile(telegram_user_id: int) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT telegram_user_id, role, created_at, updated_at
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
