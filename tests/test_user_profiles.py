import sys
from pathlib import Path

from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.user_profiles import (
    get_user_language,
    get_user_profile,
    get_user_role,
    set_user_language,
    set_user_role,
)


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "user_profiles.sqlite3"
    db.init_db()


def test_save_user_creates_default_profile_in_separate_table(tmp_path: Path) -> None:
    setup_db(tmp_path)
    user = make_user(301, "Student")

    db.save_user(user)

    profile = get_user_profile(user.id)
    assert profile is not None
    assert profile["telegram_user_id"] == user.id
    assert profile["role"] == "student"
    assert profile["bot_language"] == "en"


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
    assert get_user_language(user.id) == "uk"


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


def test_save_interaction_creates_stub_user_for_new_telegram_user_id(tmp_path: Path) -> None:
    setup_db(tmp_path)

    db.save_interaction(999001, "in", "text", "hello")

    profile = get_user_profile(999001)
    telegram_user = db.get_user(999001)
    assert profile is not None
    assert profile["role"] == "student"
    assert profile["bot_language"] == "en"
    assert telegram_user is not None
    assert telegram_user["telegram_user_id"] == 999001
    assert telegram_user["username"] is None
