import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot.build_info import (
    DEFAULT_BUILD_REF,
    DEFAULT_BUILD_TIME_UTC,
    DEFAULT_ENV_NAME,
    DEFAULT_GIT_COMMIT,
    DEFAULT_VERSION,
    BuildInfo,
    format_startup_banner,
    load_build_info,
)


def test_load_build_info_uses_defaults_when_env_is_missing(monkeypatch) -> None:
    for env_name in (
        "ENGLISHBOT_VERSION",
        "ENGLISHBOT_GIT_COMMIT",
        "ENGLISHBOT_BUILD_TIME_UTC",
        "ENGLISHBOT_BUILD_REF",
        "ENGLISHBOT_ENV_NAME",
    ):
        monkeypatch.delenv(env_name, raising=False)

    build_info = load_build_info()

    assert build_info.version == DEFAULT_VERSION
    assert build_info.git_commit == DEFAULT_GIT_COMMIT
    assert build_info.build_time_utc == DEFAULT_BUILD_TIME_UTC
    assert build_info.build_ref == DEFAULT_BUILD_REF
    assert build_info.env_name == DEFAULT_ENV_NAME


def test_load_build_info_treats_blank_env_values_as_missing(monkeypatch) -> None:
    monkeypatch.setenv("ENGLISHBOT_VERSION", "  ")
    monkeypatch.setenv("ENGLISHBOT_GIT_COMMIT", "")
    monkeypatch.setenv("ENGLISHBOT_BUILD_TIME_UTC", " ")
    monkeypatch.setenv("ENGLISHBOT_BUILD_REF", "\t")
    monkeypatch.setenv("ENGLISHBOT_ENV_NAME", "\n")

    build_info = load_build_info()

    assert build_info.version == DEFAULT_VERSION
    assert build_info.git_commit == DEFAULT_GIT_COMMIT
    assert build_info.build_time_utc == DEFAULT_BUILD_TIME_UTC
    assert build_info.build_ref == DEFAULT_BUILD_REF
    assert build_info.env_name == DEFAULT_ENV_NAME


def test_format_startup_banner_is_compact_and_stable() -> None:
    banner = format_startup_banner(
        BuildInfo(
            version="1.2.3",
            git_commit="abc1234",
            build_time_utc="2026-04-22T10:11:12Z",
            build_ref="refs/tags/v1.2.3",
            env_name="production",
        )
    )

    assert (
        banner
        == "EnglishBot startup: "
        "version=1.2.3 "
        "commit=abc1234 "
        "build_time_utc=2026-04-22T10:11:12Z "
        "build_ref=refs/tags/v1.2.3 "
        "env=production"
    )
