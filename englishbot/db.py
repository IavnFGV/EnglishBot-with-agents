import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from aiogram.types import User


DB_PATH = Path(os.getenv("ENGLISHBOT_DB_PATH", "englishbot.sqlite3"))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                telegram_user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                direction TEXT NOT NULL,
                interaction_type TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (telegram_user_id) REFERENCES users (telegram_user_id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_interactions_telegram_user_id
            ON interactions (telegram_user_id)
            """
        )
        connection.execute("DROP TABLE IF EXISTS messages")


def save_user(user: User) -> None:
    timestamp = utc_now()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO users (
                telegram_user_id,
                username,
                first_name,
                last_name,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                updated_at = excluded.updated_at
            """,
            (
                user.id,
                user.username,
                user.first_name,
                user.last_name,
                timestamp,
                timestamp,
            ),
        )


def save_interaction(
    telegram_user_id: int,
    direction: str,
    interaction_type: str,
    content: str,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO interactions (
                telegram_user_id,
                direction,
                interaction_type,
                content,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (telegram_user_id, direction, interaction_type, content, utc_now()),
        )


def get_user(telegram_user_id: int) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT telegram_user_id, username, first_name, last_name, created_at, updated_at
            FROM users
            WHERE telegram_user_id = ?
            """,
            (telegram_user_id,),
        ).fetchone()


def count_text_interactions(telegram_user_id: int) -> int:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS message_count
            FROM interactions
            WHERE telegram_user_id = ?
              AND direction = 'in'
              AND interaction_type = 'text'
            """,
            (telegram_user_id,),
        ).fetchone()
    return int(row["message_count"])
