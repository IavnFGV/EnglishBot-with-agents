"""Daily SQLite backup and audit-log retention for a small home deployment."""

import asyncio
import logging
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db


logger = logging.getLogger(__name__)

DAILY_BACKUP_PREFIX = "daily__"
INTERACTION_RETENTION_DAYS = 90
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


def prune_old_interactions(now: datetime | None = None) -> int:
    current = now or datetime.now(timezone.utc)
    cutoff = (current - timedelta(days=INTERACTION_RETENTION_DAYS)).isoformat(timespec="seconds")
    with closing(db.get_connection()) as connection:
        with connection:
            cursor = connection.execute("DELETE FROM interactions WHERE created_at < ?", (cutoff,))
    return int(cursor.rowcount)


def run_daily_maintenance_once(now: datetime | None = None) -> None:
    backup_path = create_daily_backup_if_missing(now)
    if backup_path is not None:
        logger.info("Daily SQLite backup created: %s", backup_path)
        removed = prune_old_interactions(now)
        if removed:
            logger.info("Pruned %d interaction log rows older than %d days", removed, INTERACTION_RETENTION_DAYS)


async def run_daily_maintenance_loop(*, interval_seconds: int = CHECK_INTERVAL_SECONDS) -> None:
    while True:
        try:
            await asyncio.to_thread(run_daily_maintenance_once)
        except Exception:
            logger.exception("Daily maintenance failed")
        await asyncio.sleep(interval_seconds)
