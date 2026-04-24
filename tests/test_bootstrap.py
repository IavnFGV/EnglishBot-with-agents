import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import bootstrap
from englishbot.build_info import BuildInfo


class FakeBot:
    pass


def test_bootstrap_run_uses_one_central_startup_order(monkeypatch) -> None:
    calls: list[str] = []
    fake_bot = FakeBot()
    closed_servers: list[str] = []

    def fake_load_environment() -> None:
        calls.append("load_environment")

    def fake_configure_logging() -> None:
        calls.append("configure_logging")

    def fake_load_build_info() -> BuildInfo:
        calls.append("load_build_info")
        return BuildInfo(
            version="1.0.0",
            git_commit="abc1234",
            build_time_utc="2026-04-22T00:00:00Z",
            build_ref="refs/heads/main",
            env_name="test",
        )

    def fake_init_db() -> None:
        calls.append("init_db")

    def fake_seed_basic_topics() -> None:
        calls.append("seed_basic_topics")

    class FakeStatusServer:
        def close(self) -> None:
            closed_servers.append("close")

        async def wait_closed(self) -> None:
            closed_servers.append("wait_closed")

    async def fake_start_status_server(build_info: BuildInfo) -> FakeStatusServer:
        assert build_info.version == "1.0.0"
        calls.append("start_status_server")
        return FakeStatusServer()

    def fake_build_bot() -> FakeBot:
        calls.append("build_bot")
        return fake_bot

    async def fake_configure_bot_commands(bot) -> None:
        assert bot is fake_bot
        calls.append("configure_bot_commands")

    async def fake_start_polling(bot) -> None:
        assert bot is fake_bot
        calls.append("start_polling")

    monkeypatch.setattr(bootstrap, "load_environment", fake_load_environment)
    monkeypatch.setattr(bootstrap, "configure_logging", fake_configure_logging)
    monkeypatch.setattr(bootstrap, "load_build_info", fake_load_build_info)
    monkeypatch.setattr(bootstrap, "init_db", fake_init_db)
    monkeypatch.setattr(bootstrap, "seed_basic_topics", fake_seed_basic_topics)
    monkeypatch.setattr(bootstrap, "start_status_server", fake_start_status_server)
    monkeypatch.setattr(bootstrap, "build_bot", fake_build_bot)
    monkeypatch.setattr(bootstrap, "configure_bot_commands", fake_configure_bot_commands)
    monkeypatch.setattr(bootstrap.dispatcher, "start_polling", fake_start_polling)

    asyncio.run(bootstrap.run())

    assert calls == [
        "load_environment",
        "configure_logging",
        "load_build_info",
        "init_db",
        "seed_basic_topics",
        "start_status_server",
        "build_bot",
        "configure_bot_commands",
        "start_polling",
    ]
    assert closed_servers == ["close", "wait_closed"]


def test_bootstrap_run_logs_compact_startup_banner(monkeypatch) -> None:
    banner_messages: list[str] = []
    fake_bot = FakeBot()
    build_info = BuildInfo(
        version="2.0.0",
        git_commit="deadbeef",
        build_time_utc="2026-04-22T12:34:56Z",
        build_ref="refs/tags/v2.0.0",
        env_name="staging",
    )

    def fake_load_environment() -> None:
        return None

    def fake_configure_logging() -> None:
        return None

    def fake_load_build_info() -> BuildInfo:
        return build_info

    def fake_init_db() -> None:
        return None

    def fake_seed_basic_topics() -> None:
        return None

    class FakeStatusServer:
        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    async def fake_start_status_server(_: BuildInfo) -> FakeStatusServer:
        return FakeStatusServer()

    def fake_build_bot() -> FakeBot:
        return fake_bot

    async def fake_configure_bot_commands(bot) -> None:
        assert bot is fake_bot

    async def fake_start_polling(bot) -> None:
        assert bot is fake_bot

    def fake_logger_info(message: str, *args: object) -> None:
        if args:
            message = message % args
        banner_messages.append(message)

    monkeypatch.setattr(bootstrap, "load_environment", fake_load_environment)
    monkeypatch.setattr(bootstrap, "configure_logging", fake_configure_logging)
    monkeypatch.setattr(bootstrap, "load_build_info", fake_load_build_info)
    monkeypatch.setattr(bootstrap, "init_db", fake_init_db)
    monkeypatch.setattr(bootstrap, "seed_basic_topics", fake_seed_basic_topics)
    monkeypatch.setattr(bootstrap, "start_status_server", fake_start_status_server)
    monkeypatch.setattr(bootstrap, "build_bot", fake_build_bot)
    monkeypatch.setattr(bootstrap, "configure_bot_commands", fake_configure_bot_commands)
    monkeypatch.setattr(bootstrap.dispatcher, "start_polling", fake_start_polling)
    monkeypatch.setattr(bootstrap.logger, "info", fake_logger_info)

    asyncio.run(bootstrap.run())

    assert banner_messages[0] == (
        "EnglishBot startup: "
        "version=2.0.0 "
        "commit=deadbeef "
        "build_time_utc=2026-04-22T12:34:56Z "
        "build_ref=refs/tags/v2.0.0 "
        "env=staging"
    )


def test_bootstrap_run_logs_status_server_startup(monkeypatch) -> None:
    log_messages: list[str] = []
    fake_bot = FakeBot()

    def fake_load_environment() -> None:
        return None

    def fake_configure_logging() -> None:
        return None

    def fake_load_build_info() -> BuildInfo:
        return BuildInfo(
            version="3.0.0",
            git_commit="cafebabe",
            build_time_utc="2026-04-24T08:00:00Z",
            build_ref="refs/heads/main",
            env_name="production",
        )

    def fake_init_db() -> None:
        return None

    def fake_seed_basic_topics() -> None:
        return None

    class FakeStatusServer:
        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    async def fake_start_status_server(_: BuildInfo) -> FakeStatusServer:
        return FakeStatusServer()

    def fake_build_bot() -> FakeBot:
        return fake_bot

    async def fake_configure_bot_commands(bot) -> None:
        assert bot is fake_bot

    async def fake_start_polling(bot) -> None:
        assert bot is fake_bot

    def fake_logger_info(message: str, *args: object) -> None:
        if args:
            message = message % args
        log_messages.append(message)

    monkeypatch.setattr(bootstrap, "load_environment", fake_load_environment)
    monkeypatch.setattr(bootstrap, "configure_logging", fake_configure_logging)
    monkeypatch.setattr(bootstrap, "load_build_info", fake_load_build_info)
    monkeypatch.setattr(bootstrap, "init_db", fake_init_db)
    monkeypatch.setattr(bootstrap, "seed_basic_topics", fake_seed_basic_topics)
    monkeypatch.setattr(bootstrap, "start_status_server", fake_start_status_server)
    monkeypatch.setattr(bootstrap, "build_bot", fake_build_bot)
    monkeypatch.setattr(bootstrap, "configure_bot_commands", fake_configure_bot_commands)
    monkeypatch.setattr(bootstrap.dispatcher, "start_polling", fake_start_polling)
    monkeypatch.setattr(bootstrap.logger, "info", fake_logger_info)

    asyncio.run(bootstrap.run())

    assert "EnglishBot status server listening on 0.0.0.0:8080" in log_messages
