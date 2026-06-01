import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.families import (
    add_family_member,
    create_family,
    create_family_learning_item,
    create_homework_assignment as create_family_homework_assignment,
)
from englishbot.learner_homework import (
    HOMEWORK_ACTION_CONTINUE,
    HOMEWORK_ACTION_START,
    get_learner_homework_overview,
    list_learner_homework,
)
from englishbot.training import create_training_session, submit_training_answer
from englishbot.vocabulary import (
    create_learning_item_translation,
    create_lexeme,
)
from aiogram.types import User


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "learner_homework.sqlite3"
    db.init_db()


def seed_family_parent_and_child() -> tuple[User, User, int]:
    parent = make_user(901, "Parent")
    child = make_user(902, "Child")
    db.save_user(parent)
    db.save_user(child)
    family = create_family("Home", parent.id)
    add_family_member(int(family["id"]), child.id)
    return parent, child, int(family["id"])


def seed_family_learning_items(family_id: int, count: int, *, prefix: str) -> list[int]:
    learning_item_ids: list[int] = []
    for index in range(count):
        lexeme_id = create_lexeme(f"{prefix}-{index + 1}")
        learning_item_id = create_family_learning_item(family_id, lexeme_id, f"text-{index + 1}")
        create_learning_item_translation(learning_item_id, "ru", f"слово-{index + 1}")
        learning_item_ids.append(learning_item_id)
    return learning_item_ids


def test_list_learner_homework_reports_compact_progress_for_new_and_resumable_assignments(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    parent, child, family_id = seed_family_parent_and_child()
    first_assignment_id = create_family_homework_assignment(
        family_id,
        parent.id,
        child.id,
        seed_family_learning_items(family_id, 2, prefix="fresh-homework"),
        title="Fresh homework",
    )
    second_assignment_id = create_family_homework_assignment(
        family_id,
        parent.id,
        child.id,
        seed_family_learning_items(family_id, 1, prefix="resume-homework"),
        title="Resume homework",
    )

    from englishbot.homework import start_assignment_training_session

    start_assignment_training_session(child.id, f"family:{second_assignment_id}")
    submit_training_answer(child.id, "resume-homework-1")
    snapshots = list_learner_homework(child.id)

    assert [snapshot["assignment_id"] for snapshot in snapshots] == [
        first_assignment_id,
        second_assignment_id,
    ]
    assert snapshots[0]["action_key"] == HOMEWORK_ACTION_START
    assert snapshots[0]["completed_items"] == 0
    assert snapshots[0]["total_items"] == 2
    assert snapshots[1]["action_key"] == HOMEWORK_ACTION_CONTINUE
    assert snapshots[1]["completed_items"] == 0
    assert snapshots[1]["total_items"] == 1
    assert snapshots[1]["current_item_position"] == 1
    assert snapshots[1]["current_stage"] == "easy"


def test_get_learner_homework_overview_reuses_unfinished_assignment_session_after_switching_flows(
    tmp_path: Path,
) -> None:
    setup_db(tmp_path)
    parent, child, family_id = seed_family_parent_and_child()
    assignment_id = create_family_homework_assignment(
        family_id,
        parent.id,
        child.id,
        seed_family_learning_items(family_id, 1, prefix="resume-later"),
        title="Resume later",
    )

    from englishbot.homework import start_assignment_training_session

    start_assignment_training_session(child.id, f"family:{assignment_id}")
    submit_training_answer(child.id, "resume-later-1")
    create_training_session(child.id, limit=1)

    overview = get_learner_homework_overview(child.id, f"family:{assignment_id}")

    assert overview["action_key"] == HOMEWORK_ACTION_CONTINUE
    assert overview["completed_items"] == 0
    assert overview["current_item_position"] == 1
    assert overview["current_stage"] == "easy"
