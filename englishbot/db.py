import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from aiogram.types import User


DB_PATH = Path(os.getenv("ENGLISHBOT_DB_PATH", "englishbot.sqlite3"))
DEFAULT_USER_ROLE = "student"
DEFAULT_CONTENT_WORKSPACE_NAME = "Starter Content"


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


def _ensure_default_content_workspace(connection: sqlite3.Connection) -> int:
    workspace = connection.execute(
        """
        SELECT id
        FROM workspaces
        WHERE name = ?
        ORDER BY id
        LIMIT 1
        """,
        (DEFAULT_CONTENT_WORKSPACE_NAME,),
    ).fetchone()
    if workspace is not None:
        return int(workspace["id"])

    cursor = connection.execute(
        """
        INSERT INTO workspaces (name, created_at)
        VALUES (?, ?)
        """,
        (DEFAULT_CONTENT_WORKSPACE_NAME, utc_now()),
    )
    return int(cursor.lastrowid)


def get_default_content_workspace_id() -> int:
    init_db()
    with get_connection() as connection:
        return _ensure_default_content_workspace(connection)


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
            CREATE TABLE IF NOT EXISTS workspaces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS workspace_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER NOT NULL,
                telegram_user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
                FOREIGN KEY (telegram_user_id) REFERENCES users (telegram_user_id),
                UNIQUE (workspace_id, telegram_user_id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_workspace_members_workspace_id
            ON workspace_members (workspace_id)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_workspace_members_user_id
            ON workspace_members (telegram_user_id)
            """
        )
        default_content_workspace_id = _ensure_default_content_workspace(connection)
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
                workspace_id INTEGER NOT NULL,
                lexeme_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                image_ref TEXT,
                audio_ref TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
                FOREIGN KEY (lexeme_id) REFERENCES lexemes (id)
            )
            """
        )
        learning_item_columns = get_table_columns(connection, "learning_items")
        if "workspace_id" not in learning_item_columns:
            connection.execute(
                """
                ALTER TABLE learning_items
                ADD COLUMN workspace_id INTEGER
                REFERENCES workspaces (id)
                """
            )
        connection.execute(
            """
            UPDATE learning_items
            SET workspace_id = ?
            WHERE workspace_id IS NULL
            """,
            (default_content_workspace_id,),
        )
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
            CREATE INDEX IF NOT EXISTS idx_learning_items_workspace_id
            ON learning_items (workspace_id)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_learning_item_translations_learning_item_id
            ON learning_item_translations (learning_item_id)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
            )
            """
        )
        topic_columns = get_table_columns(connection, "topics")
        if "workspace_id" not in topic_columns:
            connection.execute(
                """
                ALTER TABLE topics
                ADD COLUMN workspace_id INTEGER
                REFERENCES workspaces (id)
                """
            )
        connection.execute(
            """
            UPDATE topics
            SET workspace_id = ?
            WHERE workspace_id IS NULL
            """,
            (default_content_workspace_id,),
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS topic_learning_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_id INTEGER NOT NULL,
                learning_item_id INTEGER NOT NULL,
                FOREIGN KEY (topic_id) REFERENCES topics (id),
                FOREIGN KEY (learning_item_id) REFERENCES learning_items (id),
                UNIQUE (topic_id, learning_item_id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_topics_name
            ON topics (workspace_id, name)
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_topics_workspace_name_unique
            ON topics (workspace_id, name)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_topics_workspace_id
            ON topics (workspace_id)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_topic_learning_items_topic_id
            ON topic_learning_items (topic_id)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS student_topic_access (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER,
                student_user_id INTEGER NOT NULL,
                topic_id INTEGER NOT NULL,
                granted_by_teacher_user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
                FOREIGN KEY (student_user_id) REFERENCES users (telegram_user_id),
                FOREIGN KEY (topic_id) REFERENCES topics (id),
                FOREIGN KEY (granted_by_teacher_user_id) REFERENCES users (telegram_user_id),
                UNIQUE (student_user_id, topic_id)
            )
            """
        )
        student_topic_access_columns = get_table_columns(connection, "student_topic_access")
        if "workspace_id" not in student_topic_access_columns:
            connection.execute(
                """
                ALTER TABLE student_topic_access
                ADD COLUMN workspace_id INTEGER
                REFERENCES workspaces (id)
                """
            )
        connection.execute(
            """
            UPDATE student_topic_access
            SET workspace_id = COALESCE(
                (
                    SELECT topics.workspace_id
                    FROM topics
                    WHERE topics.id = student_topic_access.topic_id
                ),
                ?
            )
            WHERE workspace_id IS NULL
            """,
            (default_content_workspace_id,),
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_student_topic_access_student_user_id
            ON student_topic_access (student_user_id)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_student_topic_access_workspace_student
            ON student_topic_access (workspace_id, student_user_id)
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_student_topic_access_workspace_student_topic
            ON student_topic_access (workspace_id, student_user_id, topic_id)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS training_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                assignment_id INTEGER,
                current_index INTEGER NOT NULL DEFAULT 0,
                correct_answers INTEGER NOT NULL DEFAULT 0,
                total_questions INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (telegram_user_id) REFERENCES users (telegram_user_id),
                FOREIGN KEY (assignment_id) REFERENCES assignments (id)
            )
            """
        )
        training_session_columns = get_table_columns(connection, "training_sessions")
        if "assignment_id" not in training_session_columns:
            connection.execute(
                """
                ALTER TABLE training_sessions
                ADD COLUMN assignment_id INTEGER
                """
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS training_session_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                learning_item_id INTEGER NOT NULL,
                item_order INTEGER NOT NULL,
                FOREIGN KEY (session_id) REFERENCES training_sessions (id),
                FOREIGN KEY (learning_item_id) REFERENCES learning_items (id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_training_sessions_user_status
            ON training_sessions (telegram_user_id, status)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_training_session_items_session_order
            ON training_session_items (session_id, item_order)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER,
                teacher_user_id INTEGER NOT NULL,
                student_user_id INTEGER NOT NULL,
                title TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
                FOREIGN KEY (teacher_user_id) REFERENCES users (telegram_user_id),
                FOREIGN KEY (student_user_id) REFERENCES users (telegram_user_id)
            )
            """
        )
        assignment_columns = get_table_columns(connection, "assignments")
        if "completed_at" not in assignment_columns:
            connection.execute(
                """
                ALTER TABLE assignments
                ADD COLUMN completed_at TEXT
                """
            )
        if "title" not in assignment_columns:
            connection.execute(
                """
                ALTER TABLE assignments
                ADD COLUMN title TEXT
                """
            )
        if "workspace_id" not in assignment_columns:
            connection.execute(
                """
                ALTER TABLE assignments
                ADD COLUMN workspace_id INTEGER
                REFERENCES workspaces (id)
                """
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS assignment_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id INTEGER NOT NULL,
                learning_item_id INTEGER NOT NULL,
                item_order INTEGER NOT NULL,
                FOREIGN KEY (assignment_id) REFERENCES assignments (id),
                FOREIGN KEY (learning_item_id) REFERENCES learning_items (id)
            )
            """
        )
        connection.execute(
            """
            UPDATE assignments
            SET workspace_id = COALESCE(
                (
                    SELECT learning_items.workspace_id
                    FROM assignment_items
                    JOIN learning_items
                      ON learning_items.id = assignment_items.learning_item_id
                    WHERE assignment_items.assignment_id = assignments.id
                    ORDER BY assignment_items.item_order
                    LIMIT 1
                ),
                ?
            )
            WHERE workspace_id IS NULL
            """,
            (default_content_workspace_id,),
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_assignments_student_status
            ON assignments (student_user_id, status)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_assignments_workspace_student_status
            ON assignments (workspace_id, student_user_id, status)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_assignment_items_assignment_order
            ON assignment_items (assignment_id, item_order)
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


def ensure_user_exists(telegram_user_id: int) -> None:
    timestamp = utc_now()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO users (
                telegram_user_id,
                username,
                first_name,
                last_name,
                created_at,
                updated_at
            )
            VALUES (?, NULL, NULL, NULL, ?, ?)
            """,
            (telegram_user_id, timestamp, timestamp),
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
            (telegram_user_id, DEFAULT_USER_ROLE, timestamp, timestamp),
        )


def save_interaction(
    telegram_user_id: int,
    direction: str,
    interaction_type: str,
    content: str,
) -> None:
    ensure_user_exists(telegram_user_id)
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
