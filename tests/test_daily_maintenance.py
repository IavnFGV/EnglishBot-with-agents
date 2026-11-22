import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aiogram.types import User

from englishbot import db
from englishbot.daily_maintenance import (
    create_daily_backup_if_missing,
    run_daily_maintenance_once,
    trim_interaction_log,
)


NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)


def seed(tmp_path: Path, monkeypatch) -> Path:
    db.DB_PATH = tmp_path / "data.sqlite3"
    backup_dir = tmp_path / "backups"
    monkeypatch.setenv("ENGLISHBOT_BACKUP_DIR", str(backup_dir))
    db.init_db()
    db.save_user(User(id=5, is_bot=False, first_name="Kid"))
    return backup_dir


def insert_interactions(count: int, content: str = "x" * 900) -> None:
    with db.get_connection() as connection:
        connection.executemany(
            "INSERT INTO interactions (telegram_user_id, direction, interaction_type, content, created_at)"
            " VALUES (5, 'in', 'text', ?, ?)",
            [(content, NOW.isoformat(timespec="seconds")) for _ in range(count)],
        )


def interaction_ids() -> list[int]:
    with db.get_connection() as connection:
        return [row[0] for row in connection.execute("SELECT id FROM interactions ORDER BY id")]


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


def test_interaction_log_is_kept_while_under_the_size_limit(tmp_path: Path, monkeypatch) -> None:
    seed(tmp_path, monkeypatch)
    insert_interactions(10)
    assert trim_interaction_log(limit_bytes=100_000, target_bytes=50_000) == 0
    assert len(interaction_ids()) == 10


def test_oldest_interactions_are_trimmed_down_to_the_target_size(tmp_path: Path, monkeypatch) -> None:
    seed(tmp_path, monkeypatch)
    insert_interactions(100)  # 900 text bytes + 100 overhead = 1000 bytes per row
    newest = interaction_ids()[-40:]

    removed = trim_interaction_log(limit_bytes=80_000, target_bytes=40_000)

    assert removed == 60
    assert interaction_ids() == newest


def test_maintenance_runs_once_per_day(tmp_path: Path, monkeypatch) -> None:
    backup_dir = seed(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr("englishbot.daily_maintenance.trim_interaction_log", lambda: calls.append(1) or 0)

    run_daily_maintenance_once(NOW)
    run_daily_maintenance_once(NOW + timedelta(hours=1))

    assert (backup_dir / "daily__2026-11-22.sqlite3").exists()
    assert calls == [1]
