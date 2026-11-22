import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aiogram.types import User

from englishbot import db
from englishbot.daily_maintenance import (
    create_daily_backup_if_missing,
    prune_old_interactions,
    run_daily_maintenance_once,
)


NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)


def seed(tmp_path: Path, monkeypatch) -> Path:
    db.DB_PATH = tmp_path / "data.sqlite3"
    backup_dir = tmp_path / "backups"
    monkeypatch.setenv("ENGLISHBOT_BACKUP_DIR", str(backup_dir))
    db.init_db()
    db.save_user(User(id=5, is_bot=False, first_name="Kid"))
    return backup_dir


def insert_interaction(created_at: datetime) -> None:
    with db.get_connection() as connection:
        connection.execute(
            "INSERT INTO interactions (telegram_user_id, direction, interaction_type, content, created_at)"
            " VALUES (5, 'in', 'text', 'hi', ?)",
            (created_at.isoformat(timespec="seconds"),),
        )


def test_daily_backup_is_created_once_per_day_and_is_readable(tmp_path: Path, monkeypatch) -> None:
    backup_dir = seed(tmp_path, monkeypatch)

    first = create_daily_backup_if_missing(NOW)
    assert first == backup_dir / "daily__2026-11-22.sqlite3"
    assert create_daily_backup_if_missing(NOW + timedelta(hours=5)) is None
    assert create_daily_backup_if_missing(NOW + timedelta(days=1)).name == "daily__2026-11-23.sqlite3"

    with sqlite3.connect(first) as connection:
        assert connection.execute("SELECT telegram_user_id FROM users").fetchall() == [(5,)]
    assert sorted(path.name for path in backup_dir.iterdir() if path.is_file()) == [
        "daily__2026-11-22.sqlite3",
        "daily__2026-11-23.sqlite3",
    ]


def test_old_interactions_are_pruned_and_recent_ones_kept(tmp_path: Path, monkeypatch) -> None:
    seed(tmp_path, monkeypatch)
    insert_interaction(NOW - timedelta(days=91))
    insert_interaction(NOW - timedelta(days=10))

    assert prune_old_interactions(NOW) == 1
    with db.get_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM interactions").fetchone()[0] == 1


def test_maintenance_prunes_only_when_it_creates_the_daily_backup(tmp_path: Path, monkeypatch) -> None:
    backup_dir = seed(tmp_path, monkeypatch)
    run_daily_maintenance_once(NOW)
    insert_interaction(NOW - timedelta(days=200))

    run_daily_maintenance_once(NOW + timedelta(hours=1))

    assert (backup_dir / "daily__2026-11-22.sqlite3").exists()
    with db.get_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM interactions").fetchone()[0] == 1
