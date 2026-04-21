import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from aiogram.types import User


DB_PATH = Path(os.getenv("ENGLISHBOT_DB_PATH", "englishbot.sqlite3"))
DEFAULT_USER_ROLE = "student"
DEFAULT_BOT_LANGUAGE = "en"
DEFAULT_HINT_LANGUAGE = DEFAULT_BOT_LANGUAGE
DEFAULT_CONTENT_WORKSPACE_NAME = "Starter Content"
WORKSPACE_KIND_TEACHER = "teacher"
WORKSPACE_KIND_STUDENT = "student"
TOPIC_WORKBOOK_KEY_PREFIX = "topic"
LEARNING_ITEM_WORKBOOK_KEY_PREFIX = "learning-item"
ASSET_WORKBOOK_KEY_PREFIX = "asset"


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


def build_workbook_key(prefix: str, row_id: int) -> str:
    return f"{prefix}-{int(row_id)}"


def _is_url_like_asset_ref(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized.startswith("http://") or normalized.startswith("https://")


def _ensure_assets_schema(
    connection: sqlite3.Connection,
    *,
    include_learning_item_links: bool = True,
) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workbook_key TEXT,
            asset_type TEXT NOT NULL,
            source_url TEXT,
            local_path TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    asset_columns = get_table_columns(connection, "assets")
    if "workbook_key" not in asset_columns:
        connection.execute(
            """
            ALTER TABLE assets
            ADD COLUMN workbook_key TEXT
            """
        )
    legacy_assets = connection.execute(
        """
        SELECT id
        FROM assets
        WHERE workbook_key IS NULL OR TRIM(workbook_key) = ''
        ORDER BY id
        """
    ).fetchall()
    for row in legacy_assets:
        connection.execute(
            """
            UPDATE assets
            SET workbook_key = ?
            WHERE id = ?
            """,
            (
                build_workbook_key(ASSET_WORKBOOK_KEY_PREFIX, int(row["id"])),
                int(row["id"]),
            ),
        )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_assets_workbook_key_unique
        ON assets (workbook_key)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_assets_asset_type
        ON assets (asset_type)
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_assets_set_workbook_key
        AFTER INSERT ON assets
        FOR EACH ROW
        WHEN NEW.workbook_key IS NULL OR TRIM(NEW.workbook_key) = ''
        BEGIN
            UPDATE assets
            SET workbook_key = 'asset-' || NEW.id
            WHERE id = NEW.id;
        END
        """
    )
    if include_learning_item_links:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_item_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                learning_item_id INTEGER NOT NULL,
                asset_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (learning_item_id) REFERENCES learning_items (id),
                FOREIGN KEY (asset_id) REFERENCES assets (id),
                UNIQUE (learning_item_id, role, sort_order)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_learning_item_assets_learning_item_sort
            ON learning_item_assets (learning_item_id, sort_order)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_learning_item_assets_learning_item_role
            ON learning_item_assets (learning_item_id, role)
            """
        )


def _collect_legacy_learning_item_assets(
    connection: sqlite3.Connection,
) -> list[tuple[int, str, str]]:
    learning_item_columns = get_table_columns(connection, "learning_items")
    if "image_ref" not in learning_item_columns and "audio_ref" not in learning_item_columns:
        return []

    pending_links: list[tuple[int, str, str]] = []
    for column_name, asset_type, role in (
        ("image_ref", "image", "primary_image"),
        ("audio_ref", "audio", "primary_audio"),
    ):
        if column_name not in learning_item_columns:
            continue
        rows = connection.execute(
            f"""
            SELECT id, {column_name} AS asset_ref
            FROM learning_items
            WHERE {column_name} IS NOT NULL
              AND TRIM({column_name}) != ''
            ORDER BY id
            """,
        ).fetchall()
        for row in rows:
            pending_links.append((int(row["id"]), asset_type, str(row["asset_ref"]).strip(), role))
    return pending_links


def _insert_migrated_learning_item_assets(
    connection: sqlite3.Connection,
    pending_links: list[tuple[int, str, str, str]],
) -> None:
    for learning_item_id, asset_type, asset_ref, role in pending_links:
        existing = connection.execute(
            """
            SELECT 1
            FROM learning_item_assets
            WHERE learning_item_id = ? AND role = ?
            LIMIT 1
            """,
            (learning_item_id, role),
        ).fetchone()
        if existing is not None:
            continue
        source_url = asset_ref if _is_url_like_asset_ref(asset_ref) else None
        local_path = None if source_url is not None else asset_ref
        cursor = connection.execute(
            """
            INSERT INTO assets (
                workbook_key,
                asset_type,
                source_url,
                local_path,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                None,
                asset_type,
                source_url,
                local_path,
                utc_now(),
            ),
        )
        connection.execute(
            """
            INSERT INTO learning_item_assets (
                learning_item_id,
                asset_id,
                role,
                sort_order
            )
            VALUES (?, ?, ?, 0)
            """,
            (learning_item_id, int(cursor.lastrowid), role),
        )


def _rebuild_learning_items_without_legacy_media_columns(connection: sqlite3.Connection) -> None:
    learning_item_columns = get_table_columns(connection, "learning_items")
    if "image_ref" not in learning_item_columns and "audio_ref" not in learning_item_columns:
        return

    connection.execute("DROP TRIGGER IF EXISTS trg_learning_items_set_workbook_key")
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("ALTER TABLE learning_items RENAME TO learning_items_legacy")
    connection.execute(
        """
        CREATE TABLE learning_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER NOT NULL,
            workbook_key TEXT,
            source_learning_item_id INTEGER,
            lexeme_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            is_archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
            FOREIGN KEY (source_learning_item_id) REFERENCES learning_items (id),
            FOREIGN KEY (lexeme_id) REFERENCES lexemes (id)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO learning_items (
            id,
            workspace_id,
            workbook_key,
            source_learning_item_id,
            lexeme_id,
            text,
            is_archived,
            created_at,
            updated_at
        )
        SELECT
            id,
            workspace_id,
            workbook_key,
            source_learning_item_id,
            lexeme_id,
            text,
            is_archived,
            created_at,
            updated_at
        FROM learning_items_legacy
        ORDER BY id
        """
    )
    connection.execute("DROP TABLE learning_items_legacy")
    connection.execute("PRAGMA foreign_keys = ON")


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
        connection.execute(
            """
            UPDATE workspaces
            SET kind = ?
            WHERE id = ?
            """,
            (WORKSPACE_KIND_TEACHER, int(workspace["id"])),
        )
        return int(workspace["id"])

    cursor = connection.execute(
        """
        INSERT INTO workspaces (name, kind, created_at)
        VALUES (?, ?, ?)
        """,
        (DEFAULT_CONTENT_WORKSPACE_NAME, WORKSPACE_KIND_TEACHER, utc_now()),
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
                bot_language TEXT NOT NULL DEFAULT 'en',
                hint_language TEXT NOT NULL DEFAULT 'en',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (telegram_user_id) REFERENCES users (telegram_user_id)
            )
            """
        )
        user_profile_columns = get_table_columns(connection, "user_profiles")
        added_hint_language = False
        if "bot_language" not in user_profile_columns:
            connection.execute(
                """
                ALTER TABLE user_profiles
                ADD COLUMN bot_language TEXT NOT NULL DEFAULT 'en'
                """
            )
        if "hint_language" not in user_profile_columns:
            added_hint_language = True
            connection.execute(
                """
                ALTER TABLE user_profiles
                ADD COLUMN hint_language TEXT NOT NULL DEFAULT 'en'
                """
            )
        if added_hint_language:
            connection.execute(
                """
                UPDATE user_profiles
                SET hint_language = CASE
                    WHEN bot_language IN ('en', 'ru', 'uk', 'bg') THEN bot_language
                    ELSE ?
                END
                """,
                (DEFAULT_HINT_LANGUAGE,),
            )
        else:
            connection.execute(
                """
                UPDATE user_profiles
                SET hint_language = CASE
                    WHEN bot_language IN ('en', 'ru', 'uk', 'bg') THEN bot_language
                    ELSE ?
                END
                WHERE hint_language IS NULL
                   OR TRIM(hint_language) = ''
                   OR hint_language NOT IN ('en', 'ru', 'uk', 'bg')
                """,
                (DEFAULT_HINT_LANGUAGE,),
            )
        user_columns = get_table_columns(connection, "users")
        if "role" in user_columns:
            connection.execute(
                """
                INSERT OR IGNORE INTO user_profiles (
                    telegram_user_id,
                    role,
                    bot_language,
                    hint_language,
                    created_at,
                    updated_at
                )
                SELECT
                    telegram_user_id,
                    COALESCE(NULLIF(role, ''), ?),
                    ?,
                    ?,
                    created_at,
                    updated_at
                FROM users
                """,
                (DEFAULT_USER_ROLE, DEFAULT_BOT_LANGUAGE, DEFAULT_BOT_LANGUAGE),
            )
        connection.execute(
            """
            INSERT OR IGNORE INTO user_profiles (
                telegram_user_id,
                role,
                bot_language,
                hint_language,
                created_at,
                updated_at
            )
            SELECT
                telegram_user_id,
                ?,
                ?,
                ?,
                created_at,
                updated_at
            FROM users
            """,
            (DEFAULT_USER_ROLE, DEFAULT_BOT_LANGUAGE, DEFAULT_BOT_LANGUAGE),
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS workspaces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                kind TEXT NOT NULL DEFAULT 'teacher',
                created_at TEXT NOT NULL
            )
            """
        )
        workspace_columns = get_table_columns(connection, "workspaces")
        if "kind" not in workspace_columns:
            connection.execute(
                """
                ALTER TABLE workspaces
                ADD COLUMN kind TEXT NOT NULL DEFAULT 'teacher'
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
                workbook_key TEXT,
                source_learning_item_id INTEGER,
                lexeme_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                is_archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
                FOREIGN KEY (source_learning_item_id) REFERENCES learning_items (id),
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
        if "workbook_key" not in learning_item_columns:
            connection.execute(
                """
                ALTER TABLE learning_items
                ADD COLUMN workbook_key TEXT
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
        legacy_learning_items = connection.execute(
            """
            SELECT id
            FROM learning_items
            WHERE workbook_key IS NULL OR TRIM(workbook_key) = ''
            ORDER BY id
            """
        ).fetchall()
        for row in legacy_learning_items:
            connection.execute(
                """
                UPDATE learning_items
                SET workbook_key = ?
                WHERE id = ?
                """,
                (
                    build_workbook_key(LEARNING_ITEM_WORKBOOK_KEY_PREFIX, int(row["id"])),
                    int(row["id"]),
                ),
            )
        if "is_archived" not in learning_item_columns:
            connection.execute(
                """
                ALTER TABLE learning_items
                ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0
                """
            )
        if "source_learning_item_id" not in learning_item_columns:
            connection.execute(
                """
                ALTER TABLE learning_items
                ADD COLUMN source_learning_item_id INTEGER
                REFERENCES learning_items (id)
                """
            )
        _ensure_assets_schema(connection, include_learning_item_links=False)
        pending_asset_links = _collect_legacy_learning_item_assets(connection)
        _rebuild_learning_items_without_legacy_media_columns(connection)
        _ensure_assets_schema(connection)
        _insert_migrated_learning_item_assets(connection, pending_asset_links)
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
            CREATE INDEX IF NOT EXISTS idx_learning_items_workspace_source
            ON learning_items (workspace_id, source_learning_item_id)
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_learning_items_workspace_workbook_key_unique
            ON learning_items (workspace_id, workbook_key)
            """
        )
        connection.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_learning_items_set_workbook_key
            AFTER INSERT ON learning_items
            FOR EACH ROW
            WHEN NEW.workbook_key IS NULL OR TRIM(NEW.workbook_key) = ''
            BEGIN
                UPDATE learning_items
                SET workbook_key = 'learning-item-' || NEW.id
                WHERE id = NEW.id;
            END
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
                workbook_key TEXT,
                source_topic_id INTEGER,
                name TEXT NOT NULL,
                title TEXT NOT NULL,
                is_archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
                FOREIGN KEY (source_topic_id) REFERENCES topics (id)
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
        if "workbook_key" not in topic_columns:
            connection.execute(
                """
                ALTER TABLE topics
                ADD COLUMN workbook_key TEXT
                """
            )
        if "is_archived" not in topic_columns:
            connection.execute(
                """
                ALTER TABLE topics
                ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0
                """
            )
        if "updated_at" not in topic_columns:
            connection.execute(
                """
                ALTER TABLE topics
                ADD COLUMN updated_at TEXT
                """
            )
        if "source_topic_id" not in topic_columns:
            connection.execute(
                """
                ALTER TABLE topics
                ADD COLUMN source_topic_id INTEGER
                REFERENCES topics (id)
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
        legacy_topics = connection.execute(
            """
            SELECT id
            FROM topics
            WHERE workbook_key IS NULL OR TRIM(workbook_key) = ''
            ORDER BY id
            """
        ).fetchall()
        for row in legacy_topics:
            connection.execute(
                """
                UPDATE topics
                SET workbook_key = ?
                WHERE id = ?
                """,
                (
                    build_workbook_key(TOPIC_WORKBOOK_KEY_PREFIX, int(row["id"])),
                    int(row["id"]),
                ),
            )
        connection.execute(
            """
            UPDATE topics
            SET updated_at = COALESCE(updated_at, created_at)
            WHERE updated_at IS NULL
            """,
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
            CREATE INDEX IF NOT EXISTS idx_topics_workspace_source
            ON topics (workspace_id, source_topic_id)
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_topics_workspace_workbook_key_unique
            ON topics (workspace_id, workbook_key)
            """
        )
        connection.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_topics_set_workbook_key
            AFTER INSERT ON topics
            FOR EACH ROW
            WHEN NEW.workbook_key IS NULL OR TRIM(NEW.workbook_key) = ''
            BEGIN
                UPDATE topics
                SET workbook_key = 'topic-' || NEW.id
                WHERE id = NEW.id;
            END
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
                progress_message_id INTEGER,
                current_question_message_id INTEGER,
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
        if "progress_message_id" not in training_session_columns:
            connection.execute(
                """
                ALTER TABLE training_sessions
                ADD COLUMN progress_message_id INTEGER
                """
            )
        if "current_question_message_id" not in training_session_columns:
            connection.execute(
                """
                ALTER TABLE training_sessions
                ADD COLUMN current_question_message_id INTEGER
                """
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS training_session_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                learning_item_id INTEGER NOT NULL,
                prompt_text TEXT NOT NULL,
                expected_answer TEXT NOT NULL,
                item_order INTEGER NOT NULL,
                current_stage TEXT NOT NULL DEFAULT 'easy',
                easy_correct_count INTEGER NOT NULL DEFAULT 0,
                medium_correct_count INTEGER NOT NULL DEFAULT 0,
                correct_streak INTEGER NOT NULL DEFAULT 0,
                hard_unlocked INTEGER NOT NULL DEFAULT 0,
                is_completed INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (session_id) REFERENCES training_sessions (id),
                FOREIGN KEY (learning_item_id) REFERENCES learning_items (id)
            )
            """
        )
        training_session_item_columns = get_table_columns(connection, "training_session_items")
        if "prompt_text" not in training_session_item_columns:
            connection.execute(
                """
                ALTER TABLE training_session_items
                ADD COLUMN prompt_text TEXT
                """
            )
        if "expected_answer" not in training_session_item_columns:
            connection.execute(
                """
                ALTER TABLE training_session_items
                ADD COLUMN expected_answer TEXT
                """
            )
        if "current_stage" not in training_session_item_columns:
            connection.execute(
                """
                ALTER TABLE training_session_items
                ADD COLUMN current_stage TEXT NOT NULL DEFAULT 'easy'
                """
            )
        if "easy_correct_count" not in training_session_item_columns:
            connection.execute(
                """
                ALTER TABLE training_session_items
                ADD COLUMN easy_correct_count INTEGER NOT NULL DEFAULT 0
                """
            )
        if "medium_correct_count" not in training_session_item_columns:
            connection.execute(
                """
                ALTER TABLE training_session_items
                ADD COLUMN medium_correct_count INTEGER NOT NULL DEFAULT 0
                """
            )
        if "correct_streak" not in training_session_item_columns:
            connection.execute(
                """
                ALTER TABLE training_session_items
                ADD COLUMN correct_streak INTEGER NOT NULL DEFAULT 0
                """
            )
        if "hard_unlocked" not in training_session_item_columns:
            connection.execute(
                """
                ALTER TABLE training_session_items
                ADD COLUMN hard_unlocked INTEGER NOT NULL DEFAULT 0
                """
            )
        if "is_completed" not in training_session_item_columns:
            connection.execute(
                """
                ALTER TABLE training_session_items
                ADD COLUMN is_completed INTEGER NOT NULL DEFAULT 0
                """
            )
        connection.execute(
            """
            UPDATE training_session_items
            SET prompt_text = COALESCE(prompt_text, ''),
                expected_answer = COALESCE(expected_answer, ''),
                current_stage = COALESCE(NULLIF(TRIM(current_stage), ''), 'easy'),
                easy_correct_count = COALESCE(easy_correct_count, 0),
                medium_correct_count = COALESCE(medium_correct_count, 0),
                correct_streak = COALESCE(correct_streak, 0),
                hard_unlocked = COALESCE(hard_unlocked, 0),
                is_completed = COALESCE(is_completed, 0)
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
                bot_language,
                hint_language,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user.id,
                DEFAULT_USER_ROLE,
                DEFAULT_BOT_LANGUAGE,
                DEFAULT_HINT_LANGUAGE,
                timestamp,
                timestamp,
            ),
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
                bot_language,
                hint_language,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                telegram_user_id,
                DEFAULT_USER_ROLE,
                DEFAULT_BOT_LANGUAGE,
                DEFAULT_HINT_LANGUAGE,
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
