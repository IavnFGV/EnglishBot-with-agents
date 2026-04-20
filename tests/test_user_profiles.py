import sys
import sqlite3
from pathlib import Path

from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.user_profiles import (
    get_user_hint_language,
    get_user_language,
    get_user_profile,
    get_user_role,
    set_user_hint_language,
    set_user_language,
    set_user_role,
)


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "user_profiles.sqlite3"
    db.init_db()


def setup_legacy_db_without_hint_language(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE users (
                telegram_user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE user_profiles (
                telegram_user_id INTEGER PRIMARY KEY,
                role TEXT NOT NULL DEFAULT 'student',
                bot_language TEXT NOT NULL DEFAULT 'en',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (telegram_user_id) REFERENCES users (telegram_user_id)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO users (
                telegram_user_id,
                username,
                first_name,
                last_name,
                created_at,
                updated_at
            )
            VALUES (401, 'legacy', 'Legacy', NULL, '2026-04-20T00:00:00+00:00', '2026-04-20T00:00:00+00:00')
            """
        )
        connection.execute(
            """
            INSERT INTO user_profiles (
                telegram_user_id,
                role,
                bot_language,
                created_at,
                updated_at
            )
            VALUES (401, 'student', 'uk', '2026-04-20T00:00:00+00:00', '2026-04-20T00:00:00+00:00')
            """
        )


def test_save_user_creates_default_profile_in_separate_table(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(301, "Student")

    db.save_user(user)

    profile = get_user_profile(user.id)
    assert profile is not None
    assert profile["telegram_user_id"] == user.id
    assert profile["role"] == "student"
    assert profile["bot_language"] == "en"
    assert profile["hint_language"] == "en"


def test_init_db_backfills_hint_language_from_legacy_bot_language(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "legacy_user_profiles.sqlite3"
    setup_legacy_db_without_hint_language(db.DB_PATH)

    db.init_db()

    profile = get_user_profile(401)
    assert profile is not None
    assert profile["bot_language"] == "uk"
    assert profile["hint_language"] == "uk"


def test_set_user_role_updates_profile_without_touching_telegram_user_row(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(302, "Teacher")

    db.save_user(user)
    set_user_role(user.id, "teacher")

    profile = get_user_profile(user.id)
    telegram_user = db.get_user(user.id)
    assert profile is not None
    assert profile["role"] == "teacher"
    assert telegram_user is not None
    assert "role" not in telegram_user.keys()
    assert get_user_role(user.id) == "teacher"


def test_set_user_language_updates_profile_preference(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(303, "Learner")

    db.save_user(user)
    set_user_language(user.id, "uk")

    profile = get_user_profile(user.id)
    assert profile is not None
    assert profile["bot_language"] == "uk"
    assert profile["hint_language"] == "en"
    assert get_user_language(user.id) == "uk"


def test_set_user_hint_language_updates_profile_preference(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(305, "Learner")

    db.save_user(user)
    set_user_hint_language(user.id, "bg")

    profile = get_user_profile(user.id)
    assert profile is not None
    assert profile["hint_language"] == "bg"
    assert get_user_hint_language(user.id) == "bg"


def test_get_user_language_falls_back_to_default_for_invalid_value(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(304, "Learner")

    db.save_user(user)
    with db.get_connection() as connection:
        connection.execute(
            """
            UPDATE user_profiles
            SET bot_language = 'invalid'
            WHERE telegram_user_id = ?
            """,
            (user.id,),
        )

    assert get_user_language(user.id) == "en"


def test_get_user_hint_language_falls_back_to_default_for_invalid_value(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(306, "Learner")

    db.save_user(user)
    with db.get_connection() as connection:
        connection.execute(
            """
            UPDATE user_profiles
            SET hint_language = 'invalid'
            WHERE telegram_user_id = ?
            """,
            (user.id,),
        )

    assert get_user_hint_language(user.id) == "en"


def test_get_user_hint_language_falls_back_to_valid_bot_language(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(307, "Learner")

    db.save_user(user)
    with db.get_connection() as connection:
        connection.execute(
            """
            UPDATE user_profiles
            SET bot_language = 'uk',
                hint_language = 'invalid'
            WHERE telegram_user_id = ?
            """,
            (user.id,),
        )

    assert get_user_hint_language(user.id) == "uk"


def test_save_interaction_creates_stub_user_for_new_telegram_user_id(tmp_path: Path) -> None:
    setup_db(tmp_path)

    db.save_interaction(999001, "in", "text", "hello")

    profile = get_user_profile(999001)
    telegram_user = db.get_user(999001)
    assert profile is not None
    assert profile["role"] == "student"
    assert profile["bot_language"] == "en"
    assert profile["hint_language"] == "en"
    assert telegram_user is not None
    assert telegram_user["telegram_user_id"] == 999001
    assert telegram_user["username"] is None
