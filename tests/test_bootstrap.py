import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import bootstrap


class FakeBot:
    pass


def test_bootstrap_run_uses_one_central_startup_order(monkeypatch) -> None:
    calls: list[str] = []
    fake_bot = FakeBot()

    def fake_load_environment() -> None:
        calls.append("load_environment")

    def fake_configure_logging() -> None:
        calls.append("configure_logging")

    def fake_init_db() -> None:
        calls.append("init_db")

    def fake_seed_basic_topics() -> None:
        calls.append("seed_basic_topics")

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
    monkeypatch.setattr(bootstrap, "init_db", fake_init_db)
    monkeypatch.setattr(bootstrap, "seed_basic_topics", fake_seed_basic_topics)
    monkeypatch.setattr(bootstrap, "build_bot", fake_build_bot)
    monkeypatch.setattr(bootstrap, "configure_bot_commands", fake_configure_bot_commands)
    monkeypatch.setattr(bootstrap.dispatcher, "start_polling", fake_start_polling)

    asyncio.run(bootstrap.run())

    assert calls == [
        "load_environment",
        "configure_logging",
        "init_db",
        "seed_basic_topics",
        "build_bot",
        "configure_bot_commands",
        "start_polling",
    ]
