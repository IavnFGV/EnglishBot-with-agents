import os
from dataclasses import dataclass


DEFAULT_VERSION = "dev"
DEFAULT_GIT_COMMIT = "unknown"
DEFAULT_BUILD_TIME_UTC = "unknown"
DEFAULT_BUILD_REF = "unknown"
DEFAULT_ENV_NAME = "local"


def _read_env(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


@dataclass(frozen=True)
class BuildInfo:
    version: str
    git_commit: str
    build_time_utc: str
    build_ref: str
    env_name: str


def load_build_info() -> BuildInfo:
    return BuildInfo(
        version=_read_env("ENGLISHBOT_VERSION", DEFAULT_VERSION),
        git_commit=_read_env("ENGLISHBOT_GIT_COMMIT", DEFAULT_GIT_COMMIT),
        build_time_utc=_read_env("ENGLISHBOT_BUILD_TIME_UTC", DEFAULT_BUILD_TIME_UTC),
        build_ref=_read_env("ENGLISHBOT_BUILD_REF", DEFAULT_BUILD_REF),
        env_name=_read_env("ENGLISHBOT_ENV_NAME", DEFAULT_ENV_NAME),
    )


def format_startup_banner(build_info: BuildInfo) -> str:
    return (
        "EnglishBot startup: "
        f"version={build_info.version} "
        f"commit={build_info.git_commit} "
        f"build_time_utc={build_info.build_time_utc} "
        f"build_ref={build_info.build_ref} "
        f"env={build_info.env_name}"
    )
