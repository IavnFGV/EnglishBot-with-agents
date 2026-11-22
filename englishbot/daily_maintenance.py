"""Daily SQLite backup and size-bounded interaction log for a small home deployment."""

import asyncio
import logging
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from . import db


logger = logging.getLogger(__name__)

DAILY_BACKUP_PREFIX = "daily__"
# The interaction log is kept for debugging until it grows past the limit;
# then the oldest rows are removed down to the target size.
INTERACTION_LOG_LIMIT_BYTES = 200 * 1024 * 1024
INTERACTION_LOG_TARGET_BYTES = 150 * 1024 * 1024
# Approximate per-row storage beyond the message text (columns, rowid, index entry).
INTERACTION_ROW_OVERHEAD_BYTES = 100
CHECK_INTERVAL_SECONDS = 3600


def get_backup_dir() -> Path:
    raw_dir = os.getenv("ENGLISHBOT_BACKUP_DIR", "./backups").strip() or "./backups"
    backup_dir = Path(raw_dir)
    if not backup_dir.is_absolute():
        backup_dir = Path.cwd() / backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def daily_backup_path(day: datetime) -> Path:
    return get_backup_dir() / f"{DAILY_BACKUP_PREFIX}{day.strftime('%Y-%m-%d')}.sqlite3"


def create_daily_backup_if_missing(now: datetime | None = None) -> Path | None:
    """Create today's backup once; return its path, or None if it already exists."""
    current = now or datetime.now(timezone.utc)
    target = daily_backup_path(current)
    if target.exists():
        return None
    # The host task copies only top-level files, so a partial copy stays invisible.
    partial_dir = get_backup_dir() / ".partial"
    partial_dir.mkdir(exist_ok=True)
    partial = partial_dir / target.name
    partial.unlink(missing_ok=True)
    with closing(sqlite3.connect(db.DB_PATH)) as source:
        with closing(sqlite3.connect(partial)) as destination:
            source.backup(destination)
    os.replace(partial, target)
    return target


def estimate_interaction_log_bytes(connection) -> tuple[int, int]:
    row_count, text_bytes = connection.execute(
        "SELECT COUNT(*), COALESCE(SUM(LENGTH(CAST(content AS BLOB))), 0) FROM interactions"
    ).fetchone()
    return int(row_count), int(text_bytes) + int(row_count) * INTERACTION_ROW_OVERHEAD_BYTES


def trim_interaction_log(
    *,
    limit_bytes: int = INTERACTION_LOG_LIMIT_BYTES,
    target_bytes: int = INTERACTION_LOG_TARGET_BYTES,
) -> int:
    """Delete the oldest interaction rows once the log exceeds limit_bytes; return rows removed."""
    with closing(db.get_connection()) as connection:
        with connection:
            row_count, size_bytes = estimate_interaction_log_bytes(connection)
            if size_bytes <= limit_bytes or row_count == 0:
                return 0
            rows_to_delete = row_count - int(row_count * target_bytes / size_bytes)
            boundary = connection.execute(
                "SELECT id FROM interactions ORDER BY id LIMIT 1 OFFSET ?",
                (rows_to_delete - 1,),
            ).fetchone()
            cursor = connection.execute("DELETE FROM interactions WHERE id <= ?", (int(boundary[0]),))
    return int(cursor.rowcount)


def run_daily_maintenance_once(now: datetime | None = None) -> None:
    backup_path = create_daily_backup_if_missing(now)
    if backup_path is not None:
        logger.info("Daily SQLite backup created: %s", backup_path)
        removed = trim_interaction_log()
        if removed:
            logger.info("Trimmed %d oldest interaction log rows to stay under %d bytes", removed, INTERACTION_LOG_LIMIT_BYTES)


async def run_daily_maintenance_loop(*, interval_seconds: int = CHECK_INTERVAL_SECONDS) -> None:
    while True:
        try:
            await asyncio.to_thread(run_daily_maintenance_once)
        except Exception:
            logger.exception("Daily maintenance failed")
        await asyncio.sleep(interval_seconds)
