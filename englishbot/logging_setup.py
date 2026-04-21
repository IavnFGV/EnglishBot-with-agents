import gzip
import logging
import logging.handlers
import os
import shutil
import socket
import time
from dataclasses import dataclass
from pathlib import Path


APP_NAME = "englishbot"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_BACKUP_COUNT = 7
DEFAULT_MAX_SIZE_BYTES = 0
DEFAULT_RETENTION_DAYS = 14
MAINTENANCE_LOGGER_NAME = "englishbot.maintenance"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


@dataclass(frozen=True)
class LoggingConfig:
    log_dir: Path | None
    level_name: str
    level: int
    backup_count: int
    max_size_bytes: int
    retention_days: int
    hostname: str
    main_log_path: Path | None
    maintenance_log_path: Path | None
    file_logging_enabled: bool


def _parse_log_level(raw_value: str | None) -> tuple[str, int]:
    candidate = (raw_value or DEFAULT_LOG_LEVEL).strip().upper() or DEFAULT_LOG_LEVEL
    level = logging.getLevelName(candidate)
    if isinstance(level, int):
        return candidate, level
    return DEFAULT_LOG_LEVEL, logging.INFO


def _parse_positive_int(raw_value: str | None, default: int) -> int:
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default
    if value <= 0:
        return default
    return value


def _parse_non_negative_int(raw_value: str | None, default: int) -> int:
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default
    if value < 0:
        return default
    return value


def _sanitize_component(value: str) -> str:
    sanitized = [
        character if character.isalnum() or character in {"-", "_", "."} else "-"
        for character in value.strip()
    ]
    result = "".join(sanitized).strip("-_.")
    return result or "unknown-host"


def _load_logging_config() -> LoggingConfig:
    level_name, level = _parse_log_level(os.getenv("ENGLISHBOT_LOG_LEVEL"))
    backup_count = _parse_positive_int(
        os.getenv("ENGLISHBOT_LOG_BACKUP_COUNT"),
        DEFAULT_BACKUP_COUNT,
    )
    max_size_bytes = _parse_non_negative_int(
        os.getenv("ENGLISHBOT_LOG_MAX_SIZE_BYTES"),
        DEFAULT_MAX_SIZE_BYTES,
    )
    retention_days = _parse_positive_int(
        os.getenv("ENGLISHBOT_LOG_RETENTION_DAYS"),
        DEFAULT_RETENTION_DAYS,
    )
    raw_log_dir = (os.getenv("ENGLISHBOT_LOG_DIR") or "").strip()
    log_dir = Path(raw_log_dir) if raw_log_dir else None
    hostname = _sanitize_component(socket.gethostname())
    main_log_path = log_dir / f"{APP_NAME}.log" if log_dir is not None else None
    maintenance_log_path = (
        log_dir / f"{APP_NAME}_maintenance.log" if log_dir is not None else None
    )
    return LoggingConfig(
        log_dir=log_dir,
        level_name=level_name,
        level=level,
        backup_count=backup_count,
        max_size_bytes=max_size_bytes,
        retention_days=retention_days,
        hostname=hostname,
        main_log_path=main_log_path,
        maintenance_log_path=maintenance_log_path,
        file_logging_enabled=False,
    )


def _reset_logger(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass


def _build_formatter() -> logging.Formatter:
    return logging.Formatter(LOG_FORMAT)


def get_maintenance_logger() -> logging.Logger:
    return logging.getLogger(MAINTENANCE_LOGGER_NAME)


class EnglishBotTimedRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    def __init__(
        self,
        *,
        filename: str,
        maintenance_logger: logging.Logger,
        hostname: str,
        backup_count: int,
        retention_days: int,
    ) -> None:
        super().__init__(
            filename=filename,
            when="midnight",
            interval=1,
            backupCount=backup_count,
            encoding="utf-8",
            utc=True,
        )
        self.maintenance_logger = maintenance_logger
        self.hostname = hostname
        self.retention_days = retention_days
        self._rollover_completed_at = int(time.time())

    def _archive_directory(self) -> Path:
        return Path(self.baseFilename).resolve().parent

    def _build_archive_path(self) -> Path:
        timestamp = time.strftime(
            "%Y-%m-%d_%H-%M-%S",
            time.gmtime(self._rollover_completed_at),
        )
        archive_name = f"{APP_NAME}__{self.hostname}__{timestamp}.log.gz"
        archive_path = self._archive_directory() / archive_name
        if not archive_path.exists():
            return archive_path

        suffix = 1
        while True:
            candidate = (
                self._archive_directory()
                / f"{APP_NAME}__{self.hostname}__{timestamp}__{suffix}.log.gz"
            )
            if not candidate.exists():
                return candidate
            suffix += 1

    def rotate(self, source: str, dest: str) -> None:
        del dest
        if not os.path.exists(source):
            return

        archive_path = self._build_archive_path()
        with open(source, "rb") as source_stream:
            with gzip.open(archive_path, "wb") as archive_stream:
                shutil.copyfileobj(source_stream, archive_stream)
        os.remove(source)
        self.maintenance_logger.info("Archived log file created: %s", archive_path.name)

    def _iter_archives(self) -> list[Path]:
        archive_dir = self._archive_directory()
        return sorted(
            archive_dir.glob(f"{APP_NAME}__*.log.gz"),
            key=lambda path: path.stat().st_mtime,
        )

    def _cleanup_archives(self) -> None:
        archives = self._iter_archives()
        cutoff_seconds = self.retention_days * 24 * 60 * 60
        now = time.time()
        kept_archives: list[Path] = []

        for archive_path in archives:
            age_seconds = now - archive_path.stat().st_mtime
            if age_seconds > cutoff_seconds:
                archive_path.unlink(missing_ok=True)
                self.maintenance_logger.info(
                    "Archived log file deleted: %s",
                    archive_path.name,
                )
                continue
            kept_archives.append(archive_path)

        if len(kept_archives) <= self.backupCount:
            return

        overflow = len(kept_archives) - self.backupCount
        for archive_path in kept_archives[:overflow]:
            archive_path.unlink(missing_ok=True)
            self.maintenance_logger.info(
                "Archived log file deleted: %s",
                archive_path.name,
            )

    def doRollover(self) -> None:
        self._rollover_completed_at = int(time.time())
        super().doRollover()
        self._cleanup_archives()


def _build_console_handler(level: int) -> logging.Handler:
    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(_build_formatter())
    return handler


def _build_maintenance_logger(
    maintenance_log_path: Path,
    level: int,
) -> logging.Logger:
    maintenance_logger = get_maintenance_logger()
    _reset_logger(maintenance_logger)
    maintenance_logger.setLevel(level)
    maintenance_logger.propagate = False

    handler = logging.FileHandler(maintenance_log_path, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(_build_formatter())
    maintenance_logger.addHandler(handler)
    return maintenance_logger


def build_runtime_file_handler(config: LoggingConfig) -> logging.Handler | None:
    if config.log_dir is None or config.main_log_path is None:
        return None

    config.log_dir.mkdir(parents=True, exist_ok=True)
    maintenance_logger = _build_maintenance_logger(
        config.maintenance_log_path,
        config.level,
    )
    handler = EnglishBotTimedRotatingFileHandler(
        filename=str(config.main_log_path),
        maintenance_logger=maintenance_logger,
        hostname=config.hostname,
        backup_count=config.backup_count,
        retention_days=config.retention_days,
    )
    handler.setLevel(config.level)
    handler.setFormatter(_build_formatter())
    return handler


def configure_logging() -> LoggingConfig:
    config = _load_logging_config()
    root_logger = logging.getLogger()
    _reset_logger(root_logger)
    root_logger.setLevel(config.level)
    root_logger.addHandler(_build_console_handler(config.level))

    maintenance_logger = get_maintenance_logger()
    _reset_logger(maintenance_logger)
    maintenance_logger.setLevel(config.level)
    maintenance_logger.propagate = False

    if config.log_dir is None:
        return config

    try:
        file_handler = build_runtime_file_handler(config)
    except Exception:
        logging.getLogger(__name__).exception(
            "File logging setup failed; continuing with console logging only"
        )
        return config

    if file_handler is None:
        return config

    root_logger.addHandler(file_handler)
    return LoggingConfig(
        log_dir=config.log_dir,
        level_name=config.level_name,
        level=config.level,
        backup_count=config.backup_count,
        max_size_bytes=config.max_size_bytes,
        retention_days=config.retention_days,
        hostname=config.hostname,
        main_log_path=config.main_log_path,
        maintenance_log_path=config.maintenance_log_path,
        file_logging_enabled=True,
    )
