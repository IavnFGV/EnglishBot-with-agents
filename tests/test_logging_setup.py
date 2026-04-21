import gzip
import logging
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot.logging_setup import (
    APP_NAME,
    DEFAULT_BACKUP_COUNT,
    DEFAULT_LOG_LEVEL,
    DEFAULT_MAX_SIZE_BYTES,
    DEFAULT_RETENTION_DAYS,
    MAINTENANCE_LOGGER_NAME,
    EnglishBotTimedRotatingFileHandler,
    configure_logging,
)


def _reset_logger(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


@pytest.fixture(autouse=True)
def reset_logging_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for env_name in (
        "ENGLISHBOT_LOG_DIR",
        "ENGLISHBOT_LOG_LEVEL",
        "ENGLISHBOT_LOG_BACKUP_COUNT",
        "ENGLISHBOT_LOG_MAX_SIZE_BYTES",
        "ENGLISHBOT_LOG_RETENTION_DAYS",
    ):
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.chdir(tmp_path)
    _reset_logger(logging.getLogger())
    _reset_logger(logging.getLogger(MAINTENANCE_LOGGER_NAME))
    yield
    _reset_logger(logging.getLogger())
    _reset_logger(logging.getLogger(MAINTENANCE_LOGGER_NAME))


def _get_runtime_handler() -> EnglishBotTimedRotatingFileHandler:
    for handler in logging.getLogger().handlers:
        if isinstance(handler, EnglishBotTimedRotatingFileHandler):
            return handler
    raise AssertionError("Runtime file handler was not configured")


def test_configure_logging_defaults_to_console_only() -> None:
    config = configure_logging()

    root_logger = logging.getLogger()
    assert config.file_logging_enabled is False
    assert config.log_dir is None
    assert len(root_logger.handlers) == 1
    assert type(root_logger.handlers[0]) is logging.StreamHandler


def test_configure_logging_creates_log_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_dir = tmp_path / "var" / "log" / "englishbot"
    monkeypatch.setenv("ENGLISHBOT_LOG_DIR", str(log_dir))
    monkeypatch.setattr("englishbot.logging_setup.socket.gethostname", lambda: "server-01")

    config = configure_logging()

    assert config.file_logging_enabled is True
    assert log_dir.is_dir()
    assert config.main_log_path == log_dir / "englishbot.log"
    assert config.maintenance_log_path == log_dir / "englishbot_maintenance.log"


def test_configure_logging_attaches_timed_rotating_file_handler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENGLISHBOT_LOG_DIR", str(tmp_path))

    configure_logging()

    handler = _get_runtime_handler()
    assert isinstance(handler, EnglishBotTimedRotatingFileHandler)
    assert handler.when == "MIDNIGHT"
    assert handler.utc is True
    assert handler.encoding == "utf-8"


def test_archive_name_includes_app_name_and_hostname(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENGLISHBOT_LOG_DIR", str(tmp_path))
    monkeypatch.setattr("englishbot.logging_setup.socket.gethostname", lambda: "server-01")

    configure_logging()
    logger = logging.getLogger("englishbot.tests.logging")
    logger.info("first line before rollover")

    handler = _get_runtime_handler()
    handler.doRollover()

    archives = sorted(tmp_path.glob("*.log.gz"))
    assert len(archives) == 1
    assert archives[0].name.startswith(f"{APP_NAME}__server-01__")
    assert archives[0].suffixes == [".log", ".gz"]


def test_rollover_creates_gzip_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENGLISHBOT_LOG_DIR", str(tmp_path))

    configure_logging()
    logger = logging.getLogger("englishbot.tests.logging")
    logger.info("compress me")

    handler = _get_runtime_handler()
    handler.doRollover()

    archives = sorted(tmp_path.glob("*.log.gz"))
    assert len(archives) == 1
    with gzip.open(archives[0], "rt", encoding="utf-8") as archive_stream:
        archive_text = archive_stream.read()
    assert "compress me" in archive_text


def test_retention_cleanup_removes_old_archives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENGLISHBOT_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("ENGLISHBOT_LOG_RETENTION_DAYS", "1")
    monkeypatch.setattr("englishbot.logging_setup.socket.gethostname", lambda: "server-01")

    stale_archive = tmp_path / f"{APP_NAME}__server-01__2026-04-01_00-00-00.log.gz"
    with gzip.open(stale_archive, "wt", encoding="utf-8") as archive_stream:
        archive_stream.write("old archive")
    stale_time = time.time() - (2 * 24 * 60 * 60)
    os.utime(stale_archive, (stale_time, stale_time))

    configure_logging()
    logging.getLogger("englishbot.tests.logging").info("fresh line")
    handler = _get_runtime_handler()
    handler.doRollover()

    assert stale_archive.exists() is False


def test_maintenance_log_receives_archive_and_delete_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENGLISHBOT_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("ENGLISHBOT_LOG_RETENTION_DAYS", "1")
    monkeypatch.setenv("ENGLISHBOT_LOG_BACKUP_COUNT", "1")
    monkeypatch.setattr("englishbot.logging_setup.socket.gethostname", lambda: "server-01")

    stale_archive = tmp_path / f"{APP_NAME}__server-01__2026-04-01_00-00-00.log.gz"
    with gzip.open(stale_archive, "wt", encoding="utf-8") as archive_stream:
        archive_stream.write("old archive")
    stale_time = time.time() - (2 * 24 * 60 * 60)
    os.utime(stale_archive, (stale_time, stale_time))

    configure_logging()
    logging.getLogger("englishbot.tests.logging").info("maintenance event")
    handler = _get_runtime_handler()
    handler.doRollover()

    maintenance_log = (tmp_path / "englishbot_maintenance.log").read_text(encoding="utf-8")
    assert "Archived log file created:" in maintenance_log
    assert "Archived log file deleted:" in maintenance_log


def test_invalid_env_values_fall_back_safely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENGLISHBOT_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("ENGLISHBOT_LOG_LEVEL", "not-a-level")
    monkeypatch.setenv("ENGLISHBOT_LOG_BACKUP_COUNT", "0")
    monkeypatch.setenv("ENGLISHBOT_LOG_MAX_SIZE_BYTES", "invalid")
    monkeypatch.setenv("ENGLISHBOT_LOG_RETENTION_DAYS", "-5")

    config = configure_logging()

    assert config.level_name == DEFAULT_LOG_LEVEL
    assert config.level == logging.INFO
    assert config.backup_count == DEFAULT_BACKUP_COUNT
    assert config.max_size_bytes == DEFAULT_MAX_SIZE_BYTES
    assert config.retention_days == DEFAULT_RETENTION_DAYS


def test_configure_logging_does_not_load_dotenv_implicitly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                "ENGLISHBOT_LOG_DIR=./logs",
                "ENGLISHBOT_LOG_LEVEL=DEBUG",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ENGLISHBOT_LOG_DIR", raising=False)
    monkeypatch.delenv("ENGLISHBOT_LOG_LEVEL", raising=False)

    config = configure_logging()

    assert config.file_logging_enabled is False
    assert config.log_dir is None
    assert config.level == logging.INFO
    assert (tmp_path / "logs").exists() is False
