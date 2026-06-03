import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from aiogram.types import User


DB_PATH = Path(os.getenv("ENGLISHBOT_DB_PATH", "englishbot.sqlite3"))
WORKBOOK_IMPORT_BACKUP_DIRNAME = "workbook_import_backups"
WORKBOOK_IMPORT_BACKUP_LIMIT = 500
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


def get_workbook_import_backup_dir() -> Path:
    return DB_PATH.parent / WORKBOOK_IMPORT_BACKUP_DIRNAME


def create_workbook_import_backup() -> Path:
    backup_dir = get_workbook_import_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / (
        f"{DB_PATH.stem}__workbook_import__"
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.sqlite3"
    )
    with sqlite3.connect(DB_PATH) as source_connection:
        with sqlite3.connect(backup_path) as backup_connection:
            source_connection.backup(backup_connection)
    prune_workbook_import_backups()
    return backup_path


def prune_workbook_import_backups(limit: int = WORKBOOK_IMPORT_BACKUP_LIMIT) -> list[Path]:
    backup_dir = get_workbook_import_backup_dir()
    if not backup_dir.exists():
        return []
    backups = sorted(
        backup_dir.glob("*.sqlite3"),
        key=lambda path: path.name,
        reverse=True,
    )
    pruned: list[Path] = []
    for backup_path in backups[limit:]:
        backup_path.unlink(missing_ok=True)
        pruned.append(backup_path)
    return pruned


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

    has_family_id = "family_id" in learning_item_columns
    connection.execute("DROP TRIGGER IF EXISTS trg_learning_items_set_workbook_key")
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("ALTER TABLE learning_items RENAME TO learning_items_legacy")
    connection.execute(
        """
        CREATE TABLE learning_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER NOT NULL,
            family_id INTEGER,
            workbook_key TEXT,
            source_learning_item_id INTEGER,
            lexeme_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            is_archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (workspace_id) REFERENCES workspaces (id),
            FOREIGN KEY (family_id) REFERENCES families (id),
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
            family_id,
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
            %s,
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
        % ("family_id" if has_family_id else "NULL"),
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
            CREATE TABLE IF NOT EXISTS families (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_by_user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (created_by_user_id) REFERENCES users (telegram_user_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS family_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                family_id INTEGER NOT NULL,
                telegram_user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (family_id) REFERENCES families (id),
                FOREIGN KEY (telegram_user_id) REFERENCES users (telegram_user_id),
                UNIQUE (family_id, telegram_user_id)
            )
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_family_members_user_unique
            ON family_members (telegram_user_id)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_family_members_family_id
            ON family_members (family_id)
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
            DROP TABLE IF EXISTS teacher_student_links
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
        if "family_id" not in learning_item_columns:
            connection.execute(
                """
                ALTER TABLE learning_items
                ADD COLUMN family_id INTEGER
                REFERENCES families (id)
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
            CREATE INDEX IF NOT EXISTS idx_learning_items_family_id
            ON learning_items (family_id)
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
        if "family_id" not in topic_columns:
            connection.execute(
                """
                ALTER TABLE topics
                ADD COLUMN family_id INTEGER
                REFERENCES families (id)
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
            CREATE INDEX IF NOT EXISTS idx_topics_family_id
            ON topics (family_id)
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
            CREATE TABLE IF NOT EXISTS topic_items (
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
            CREATE INDEX IF NOT EXISTS idx_topic_items_topic_id
            ON topic_items (topic_id)
            """
        )
        connection.execute("DROP TABLE IF EXISTS student_topic_access")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                learning_item_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'new',
                correct_streak INTEGER NOT NULL DEFAULT 0,
                last_answered_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (telegram_user_id) REFERENCES users (telegram_user_id),
                FOREIGN KEY (learning_item_id) REFERENCES learning_items (id),
                UNIQUE (telegram_user_id, learning_item_id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_progress_user_id
            ON user_progress (telegram_user_id)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS training_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                family_homework_assignment_id INTEGER,
                current_index INTEGER NOT NULL DEFAULT 0,
                correct_answers INTEGER NOT NULL DEFAULT 0,
                homework_correct_streak INTEGER NOT NULL DEFAULT 0,
                homework_hard_mode INTEGER NOT NULL DEFAULT 0,
                total_questions INTEGER NOT NULL,
                progress_message_id INTEGER,
                current_question_message_id INTEGER,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (telegram_user_id) REFERENCES users (telegram_user_id),
                FOREIGN KEY (family_homework_assignment_id) REFERENCES homework_assignments (id)
            )
            """
        )
        training_session_columns = get_table_columns(connection, "training_sessions")
        if "assignment_id" in training_session_columns:
            connection.execute(
                """
                CREATE TABLE training_sessions_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_user_id INTEGER NOT NULL,
                    family_homework_assignment_id INTEGER,
                    current_index INTEGER NOT NULL DEFAULT 0,
                    correct_answers INTEGER NOT NULL DEFAULT 0,
                    homework_correct_streak INTEGER NOT NULL DEFAULT 0,
                    homework_hard_mode INTEGER NOT NULL DEFAULT 0,
                    total_questions INTEGER NOT NULL,
                    progress_message_id INTEGER,
                    current_question_message_id INTEGER,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (telegram_user_id) REFERENCES users (telegram_user_id),
                    FOREIGN KEY (family_homework_assignment_id) REFERENCES homework_assignments (id)
                )
                """
            )
            connection.execute(
                """
                INSERT INTO training_sessions_new (
                    id,
                    telegram_user_id,
                    family_homework_assignment_id,
                    current_index,
                    correct_answers,
                    homework_correct_streak,
                    homework_hard_mode,
                    total_questions,
                    progress_message_id,
                    current_question_message_id,
                    status,
                    created_at,
                    updated_at
                )
                SELECT
                    id,
                    telegram_user_id,
                    family_homework_assignment_id,
                    current_index,
                    correct_answers,
                    homework_correct_streak,
                    homework_hard_mode,
                    total_questions,
                    progress_message_id,
                    current_question_message_id,
                    status,
                    created_at,
                    updated_at
                FROM training_sessions
                """
            )
            connection.execute("DROP TABLE training_sessions")
            connection.execute("ALTER TABLE training_sessions_new RENAME TO training_sessions")
            training_session_columns = get_table_columns(connection, "training_sessions")
        if "family_homework_assignment_id" not in training_session_columns:
            connection.execute(
                """
                ALTER TABLE training_sessions
                ADD COLUMN family_homework_assignment_id INTEGER
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
        if "homework_correct_streak" not in training_session_columns:
            connection.execute(
                """
                ALTER TABLE training_sessions
                ADD COLUMN homework_correct_streak INTEGER NOT NULL DEFAULT 0
                """
            )
        if "homework_hard_mode" not in training_session_columns:
            connection.execute(
                """
                ALTER TABLE training_sessions
                ADD COLUMN homework_hard_mode INTEGER NOT NULL DEFAULT 0
                """
            )
        connection.execute(
            """
            UPDATE training_sessions
            SET homework_correct_streak = COALESCE(homework_correct_streak, 0),
                homework_hard_mode = COALESCE(homework_hard_mode, 0)
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
                hard_completed INTEGER NOT NULL DEFAULT 0,
                answer_state TEXT NOT NULL DEFAULT '',
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
        if "hard_completed" not in training_session_item_columns:
            connection.execute(
                """
                ALTER TABLE training_session_items
                ADD COLUMN hard_completed INTEGER NOT NULL DEFAULT 0
                """
            )
        if "answer_state" not in training_session_item_columns:
            connection.execute(
                """
                ALTER TABLE training_session_items
                ADD COLUMN answer_state TEXT NOT NULL DEFAULT ''
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
                hard_completed = COALESCE(hard_completed, 0),
                answer_state = COALESCE(answer_state, ''),
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
            CREATE TABLE IF NOT EXISTS homework_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                family_id INTEGER NOT NULL,
                assigned_by_user_id INTEGER NOT NULL,
                assigned_to_user_id INTEGER NOT NULL,
                title TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (family_id) REFERENCES families (id),
                FOREIGN KEY (assigned_by_user_id) REFERENCES users (telegram_user_id),
                FOREIGN KEY (assigned_to_user_id) REFERENCES users (telegram_user_id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_homework_assignments_assigned_to_status
            ON homework_assignments (assigned_to_user_id, status)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_homework_assignments_family_id
            ON homework_assignments (family_id)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS homework_assignment_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                homework_assignment_id INTEGER NOT NULL,
                learning_item_id INTEGER NOT NULL,
                item_order INTEGER NOT NULL,
                FOREIGN KEY (homework_assignment_id) REFERENCES homework_assignments (id),
                FOREIGN KEY (learning_item_id) REFERENCES learning_items (id),
                UNIQUE (homework_assignment_id, item_order)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_homework_assignment_items_assignment_order
            ON homework_assignment_items (homework_assignment_id, item_order)
            """
        )
        connection.execute("DROP TABLE IF EXISTS assignment_items")
        connection.execute("DROP TABLE IF EXISTS assignments")
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
