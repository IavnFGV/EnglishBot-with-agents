import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from aiogram.types import User


DB_PATH = Path(os.getenv("ENGLISHBOT_DB_PATH", "englishbot.sqlite3"))
DEFAULT_USER_ROLE = "student"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def get_table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_profiles (
                telegram_user_id INTEGER PRIMARY KEY,
                role TEXT NOT NULL DEFAULT 'student',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (telegram_user_id) REFERENCES users (telegram_user_id)
            )
            """
        )
        user_columns = get_table_columns(connection, "users")
        if "role" in user_columns:
            connection.execute(
                """
                INSERT OR IGNORE INTO user_profiles (
                    telegram_user_id,
                    role,
                    created_at,
                    updated_at
                )
                SELECT
                    telegram_user_id,
                    COALESCE(NULLIF(role, ''), ?),
                    created_at,
                    updated_at
                FROM users
                """,
                (DEFAULT_USER_ROLE,),
            )
        connection.execute(
            """
            INSERT OR IGNORE INTO user_profiles (
                telegram_user_id,
                role,
                created_at,
                updated_at
            )
            SELECT
                telegram_user_id,
                ?,
                created_at,
                updated_at
            FROM users
            """,
            (DEFAULT_USER_ROLE,),
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS invites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                teacher_user_id INTEGER NOT NULL,
                used_by_user_id INTEGER,
                created_at TEXT NOT NULL,
                used_at TEXT,
                FOREIGN KEY (teacher_user_id) REFERENCES users (telegram_user_id),
                FOREIGN KEY (used_by_user_id) REFERENCES users (telegram_user_id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_invites_teacher_user_id
            ON invites (teacher_user_id)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS teacher_student_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                teacher_user_id INTEGER NOT NULL,
                student_user_id INTEGER NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                FOREIGN KEY (teacher_user_id) REFERENCES users (telegram_user_id),
                FOREIGN KEY (student_user_id) REFERENCES users (telegram_user_id),
                UNIQUE (teacher_user_id, student_user_id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_teacher_student_links_teacher_user_id
            ON teacher_student_links (teacher_user_id)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS lexemes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lemma TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lexeme_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                image_ref TEXT,
                audio_ref TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (lexeme_id) REFERENCES lexemes (id)
            )
            """
        )
        learning_item_columns = get_table_columns(connection, "learning_items")
        if "image_ref" not in learning_item_columns:
            connection.execute(
                """
                ALTER TABLE learning_items
                ADD COLUMN image_ref TEXT
                """
            )
        if "audio_ref" not in learning_item_columns:
            connection.execute(
                """
                ALTER TABLE learning_items
                ADD COLUMN audio_ref TEXT
                """
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_item_translations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                learning_item_id INTEGER NOT NULL,
                language_code TEXT NOT NULL,
                translation_text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (learning_item_id) REFERENCES learning_items (id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_learning_items_lexeme_id
            ON learning_items (lexeme_id)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_learning_item_translations_learning_item_id
            ON learning_item_translations (learning_item_id)
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
        connection.execute(
            """
            INSERT OR IGNORE INTO user_profiles (
                telegram_user_id,
                role,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (user.id, DEFAULT_USER_ROLE, timestamp, timestamp),
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
