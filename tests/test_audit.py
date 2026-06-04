import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import audit


def test_save_interaction_safely_skips_locked_sqlite_errors(monkeypatch) -> None:
    calls: list[tuple[int, str, str, str]] = []
    warnings: list[str] = []

    def fake_save_interaction(
        telegram_user_id: int,
        direction: str,
        interaction_type: str,
        content: str,
    ) -> None:
        calls.append((telegram_user_id, direction, interaction_type, content))
        raise audit.sqlite3.OperationalError("database is locked")

    def fake_warning(message: str, *args: object) -> None:
        warnings.append(message % args)

    monkeypatch.setattr(audit, "save_interaction", fake_save_interaction)
    monkeypatch.setattr(audit.logger, "warning", fake_warning)

    audit._save_interaction_safely(1001, "out", "editMessageText", "hello")

    assert calls == [(1001, "out", "editMessageText", "hello")]
    assert warnings == [
        "Skipping interaction audit write because SQLite is locked: "
        "telegram_user_id=1001 direction=out interaction_type=editMessageText"
    ]


def test_save_interaction_safely_reraises_other_operational_errors(monkeypatch) -> None:
    def fake_save_interaction(*args, **kwargs) -> None:
        raise audit.sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(audit, "save_interaction", fake_save_interaction)

    try:
        audit._save_interaction_safely(1001, "out", "editMessageText", "hello")
    except audit.sqlite3.OperationalError as exc:
        assert str(exc) == "disk I/O error"
    else:
        raise AssertionError("Expected sqlite3.OperationalError to be re-raised")
