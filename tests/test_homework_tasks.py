"""Learner side of homework built from a set: paper tasks, notes, photos, and completion."""

import asyncio
import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiogram.types import User
from PIL import Image

from englishbot import db
from englishbot.families import add_family_member, create_family
from englishbot.homework import (
    AssignmentNotFoundError,
    EmptyAssignmentError,
    list_assignment_tasks,
    mark_assignment_completed,
    set_assignment_task_done,
    start_assignment_training_session,
)
from englishbot.homework_dialog import (
    HomeworkDialogSG,
    get_overview_window_data,
    get_task_window_data,
)
from englishbot.homework_sets import (
    add_source,
    assign_set,
    begin_processing,
    list_assignments,
    save_draft,
    store_manual_draft,
    store_source_photos,
)
from englishbot import homework_dialog


MOM = 911
KID = 912


@pytest.fixture
def family(tmp_path: Path) -> int:
    db.DB_PATH = tmp_path / "data" / "tasks.sqlite3"
    db.DB_PATH.parent.mkdir()
    db.init_db()
    for user_id, name in ((MOM, "Mom"), (KID, "Teia")):
        db.save_user(User(id=user_id, is_bot=False, first_name=name))
    family_row = create_family("Home", MOM)
    add_family_member(int(family_row["id"]), KID)
    return int(family_row["id"])


def png_bytes(color: str = "white") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(output, format="PNG")
    return output.getvalue()


def draft_with_photos(count: int = 2) -> tuple[int, list[int]]:
    row = add_source(MOM, text="НТ: crossword")
    set_id = int(row["id"])
    begin_processing(MOM, set_id, "manual")
    photos = store_source_photos(set_id, [png_bytes() for _ in range(count)])
    store_manual_draft(set_id)
    return set_id, photos


def assignment_id_of(set_id: int) -> int:
    with db.get_connection() as connection:
        return int(connection.execute(
            "SELECT id FROM homework_assignments WHERE homework_set_id = ? ORDER BY id DESC", (set_id,)
        ).fetchone()[0])


def status_of(assignment_id: int) -> str:
    with db.get_connection() as connection:
        return str(connection.execute("SELECT status FROM homework_assignments WHERE id = ?", (assignment_id,)).fetchone()[0])


def test_paper_only_homework_completes_when_every_paper_task_is_ticked(family: int) -> None:
    set_id, photos = draft_with_photos()
    save_draft(MOM, set_id, {"assign_to": KID, "tasks": [
        {"kind": "paper", "title": "Crossword", "instructions": "Fill it in", "photos": photos},
        {"kind": "paper", "title": "Copybook"},
        {"kind": "note", "title": "Rule", "instructions": "a before consonants, an before vowels"},
    ]})
    assignment_id = assignment_id_of(set_id)

    tasks = list_assignment_tasks(KID, assignment_id)
    assert [(task["kind"], task["title"], task["done"]) for task in tasks] == [
        ("paper", "Crossword", False), ("paper", "Copybook", False), ("note", "Rule", False),
    ]
    assert len(tasks[0]["photos"]) == 2 and all(Path(path).is_file() for path in tasks[0]["photos"])
    with pytest.raises(EmptyAssignmentError):
        start_assignment_training_session(KID, assignment_id)  # nothing to drill

    assert set_assignment_task_done(KID, assignment_id, tasks[0]["id"], True) is False
    assert set_assignment_task_done(KID, assignment_id, tasks[0]["id"], False) is False  # unticked again
    assert set_assignment_task_done(KID, assignment_id, tasks[0]["id"], True) is False
    with pytest.raises(AssignmentNotFoundError):
        set_assignment_task_done(KID, assignment_id, tasks[2]["id"], True)  # notes are not ticked
    with pytest.raises(AssignmentNotFoundError):
        set_assignment_task_done(MOM, assignment_id, tasks[1]["id"], True)  # only the learner ticks
    assert set_assignment_task_done(KID, assignment_id, tasks[1]["id"], True) is True
    assert status_of(assignment_id) == "completed"


def test_words_and_paper_homework_waits_for_both(family: int) -> None:
    set_id, _ = draft_with_photos(0)
    save_draft(MOM, set_id, {"assign_to": KID, "tasks": [
        {"kind": "words", "items": [{"en": "owl", "ru": "сова", "topic": "Birds"}]},
        {"kind": "paper", "title": "Crossword"},
    ]})
    assignment_id = assignment_id_of(set_id)
    paper = next(task for task in list_assignment_tasks(KID, assignment_id) if task["kind"] == "paper")

    set_assignment_task_done(KID, assignment_id, paper["id"], True)
    assert status_of(assignment_id) == "active"  # words not drilled yet

    mark_assignment_completed(assignment_id)  # what training calls when every word is done
    assert status_of(assignment_id) == "completed"


def test_drilled_words_keep_homework_open_until_paper_is_ticked(family: int) -> None:
    set_id, _ = draft_with_photos(0)
    save_draft(MOM, set_id, {"assign_to": KID, "tasks": [
        {"kind": "words", "items": [{"en": "owl", "ru": "сова", "topic": "Birds"}]},
        {"kind": "paper", "title": "Crossword"},
    ]})
    assignment_id = assignment_id_of(set_id)
    mark_assignment_completed(assignment_id)
    assert status_of(assignment_id) == "active"
    with pytest.raises(EmptyAssignmentError):
        start_assignment_training_session(KID, assignment_id)  # no second round of the same words

    overview = list_assignments(MOM)["active"][0]
    assert (overview["done"], overview["total"], overview["paper_done"], overview["paper_total"]) == (1, 1, 0, 1)


def test_word_only_homework_still_completes_with_its_words(family: int) -> None:
    set_id, _ = draft_with_photos(0)
    save_draft(MOM, set_id, {"assign_to": KID, "tasks": [{"kind": "words", "items": [{"en": "owl", "ru": "сова", "topic": "Birds"}]}]})
    assignment_id = assignment_id_of(set_id)
    mark_assignment_completed(assignment_id)
    assert status_of(assignment_id) == "completed"


def test_notes_alone_are_saved_but_not_assigned(family: int) -> None:
    set_id, _ = draft_with_photos(0)
    result = save_draft(MOM, set_id, {"assign_to": KID, "tasks": [{"kind": "note", "title": "Rule", "instructions": "x"}]})
    assert result["saved"] and result["assignment_id"] is None
    paper_set, _ = draft_with_photos(0)
    save_draft(MOM, paper_set, {"tasks": [{"kind": "paper", "title": "Crossword"}]})
    assert assign_set(MOM, paper_set, KID, "easy")["word_count"] == 0


# Telegram dialog


class FakeDialogManager:
    def __init__(self, user_id: int) -> None:
        self.event = SimpleNamespace(from_user=SimpleNamespace(id=user_id))
        self.dialog_data: dict[str, object] = {}
        self.switched: list[object] = []

    async def switch_to(self, state, show_mode=None) -> None:
        self.switched.append(state)

    async def update(self, data=None, **kwargs) -> None:
        return None


class FakeCallback:
    def __init__(self, user_id: int) -> None:
        self.from_user = SimpleNamespace(id=user_id)
        self.alerts: list[tuple[str, bool]] = []

    async def answer(self, text: str = "", show_alert: bool = False) -> None:
        self.alerts.append((text, show_alert))


def test_dialog_lists_tasks_shows_photos_and_ticks_paper_work(family: int) -> None:
    set_id, photos = draft_with_photos(2)
    save_draft(MOM, set_id, {"assign_to": KID, "tasks": [
        {"kind": "paper", "title": "Crossword", "instructions": "x" * 3000, "photos": photos},
        {"kind": "note", "title": "Rule", "instructions": "an apple"},
    ]})
    assignment_id = assignment_id_of(set_id)
    manager = FakeDialogManager(KID)
    manager.dialog_data.update(assignment_id=assignment_id, assignment_key=f"family:{assignment_id}")

    overview = asyncio.run(get_overview_window_data(manager))
    assert overview["can_train"] is False
    assert "⬜ 📄 Crossword" in overview["screen_text"] and "📖 Rule" in overview["screen_text"]
    assert [button["label"] for button in overview["task_buttons"]] == ["⬜ 📄 Crossword", "📖 Rule"]

    paper_id = int(overview["task_buttons"][0]["id"])
    asyncio.run(homework_dialog._on_task_selected(None, None, manager, str(paper_id)))
    assert manager.switched[-1] == HomeworkDialogSG.task
    window = asyncio.run(get_task_window_data(manager))
    assert window["has_media"] and window["has_many_photos"] and window["is_paper"]
    assert len(window["screen_text"]) <= 1000  # fits a photo caption
    first_photo = window["task_media"].path
    asyncio.run(homework_dialog._next_photo(None, None, manager))
    assert asyncio.run(get_task_window_data(manager))["task_media"].path != first_photo

    callback = FakeCallback(KID)
    asyncio.run(homework_dialog._toggle_task_done(callback, None, manager))
    assert callback.alerts and callback.alerts[-1][1] is True  # the only paper task: homework done
    assert manager.switched[-1] == HomeworkDialogSG.assignments
    assert status_of(assignment_id) == "completed"


def test_round_summary_reminds_about_paper_work(family: int) -> None:
    from englishbot.homework import pending_paper_task_count

    set_id, _ = draft_with_photos(0)
    save_draft(MOM, set_id, {"assign_to": KID, "tasks": [
        {"kind": "words", "items": [{"en": "owl", "ru": "сова", "topic": "Birds"}]},
        {"kind": "paper", "title": "Crossword"},
        {"kind": "paper", "title": "Copybook"},
    ]})
    assignment_id = assignment_id_of(set_id)
    assert pending_paper_task_count(f"family:{assignment_id}") == 2
    paper = [task for task in list_assignment_tasks(KID, assignment_id) if task["kind"] == "paper"]
    set_assignment_task_done(KID, assignment_id, paper[0]["id"], True)
    assert pending_paper_task_count(assignment_id) == 1
