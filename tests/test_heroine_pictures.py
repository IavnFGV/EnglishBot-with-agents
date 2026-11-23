import importlib.util
import json
import os
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import pytest
from aiogram.types import User
from PIL import Image

from englishbot import db, heroine_pictures as hp
from englishbot.dictionary_editor import create_topic, create_word, route_editor_request, set_word_image
from englishbot.families import add_family_member, create_family
from englishbot.mini_app import MiniAppError


PARENT = 901
CHILD = 902
STRANGER = 903
WORKER_PATH = Path(__file__).resolve().parents[1] / "infra" / "heroine-artist" / "worker.py"


def load_worker(root: Path):
    spec = importlib.util.spec_from_file_location("heroine_worker", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = root
    return module


def png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (1254, 1254), (200, 120, 40)).save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def root(tmp_path: Path, monkeypatch) -> Path:
    db.DB_PATH = tmp_path / "data" / "heroine.sqlite3"
    db.DB_PATH.parent.mkdir()
    db.init_db()
    for user_id in (PARENT, CHILD, STRANGER):
        db.save_user(User(id=user_id, is_bot=False, first_name=f"user-{user_id}"))
    family = create_family("Home", PARENT)
    add_family_member(int(family["id"]), CHILD)
    create_family("Other", STRANGER)
    heroine_root = tmp_path / "heroine"
    monkeypatch.setenv("ENGLISHBOT_HEROINE_DIR", str(heroine_root))
    monkeypatch.setenv("ENGLISHBOT_OWNER_TELEGRAM_USER_ID", str(PARENT))
    return heroine_root


def new_word(text: str = "eel") -> int:
    topic = create_topic(PARENT, "Fishes")
    return int(create_word(PARENT, int(topic["id"]), text, {"ru": "угорь"})["id"])


def finish(root: Path, picture_id: int, result: dict, card: bytes | None = None) -> None:
    folder = root / "results" / str(picture_id)
    folder.mkdir(parents=True)
    if card is not None:
        (folder / "card.png").write_bytes(card)
    (folder / "result.json").write_text(json.dumps(result))


def later() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=1)


def test_request_writes_job_and_replaces_open_picture(root: Path) -> None:
    word_id = new_word()
    first = hp.request_picture(PARENT, word_id)
    job = json.loads((root / "jobs" / f"{first['id']}.json").read_text())
    assert job == {"id": first["id"], "word": "eel", "translation": "угорь", "scene": None}

    second = hp.request_picture(CHILD, word_id, "  eel   winks  ")
    assert second["scene_request"] == "eel winks"
    assert not (root / "jobs" / f"{first['id']}.json").exists()
    assert [p["id"] for p in hp.list_pictures(PARENT)["pictures"]] == [second["id"]]


def test_request_checks_family_and_configuration(root: Path, monkeypatch) -> None:
    word_id = new_word()
    with pytest.raises(MiniAppError) as caught:
        hp.request_picture(STRANGER, word_id)
    assert caught.value.code == "word_not_found"
    monkeypatch.delenv("ENGLISHBOT_HEROINE_DIR")
    with pytest.raises(MiniAppError) as caught:
        hp.request_picture(PARENT, word_id)
    assert caught.value.code == "heroine_unavailable"


def test_missing_pictures_are_requested_once_after_a_delay(root: Path) -> None:
    eel = new_word("eel")
    pictured = new_word("cod")
    set_word_image(PARENT, pictured, png_bytes())

    assert hp.enqueue_missing_pictures() == 0  # too fresh: the parent may still add a picture
    assert hp.enqueue_missing_pictures(later()) == 1
    assert hp.enqueue_missing_pictures(later()) == 0
    [picture] = hp.list_pictures(PARENT)["pictures"]
    assert picture["word_id"] == eel
    hp.skip_picture(PARENT, picture["id"])
    assert hp.enqueue_missing_pictures(later()) == 0  # a skipped word is not asked again


def test_results_become_candidates_and_approval_sets_the_word_picture(root: Path) -> None:
    word_id = new_word()
    picture = hp.request_picture(PARENT, word_id)
    finish(root, picture["id"], {"status": "ok", "scene": "Девочка ест суши"}, png_bytes())

    assert hp.collect_results() == 1
    assert not (root / "results" / str(picture["id"])).exists()
    [ready] = hp.list_pictures(PARENT)["pictures"]
    assert ready["status"] == "ready" and ready["scene"] == "Девочка ест суши"
    with Image.open(hp.candidate_path(PARENT, ready["id"])) as image:
        assert image.format == "JPEG" and max(image.size) == 1024

    candidate = hp.candidate_path(PARENT, ready["id"])
    assert hp.approve_picture(PARENT, ready["id"])["status"] == "approved"
    assert not candidate.exists()
    assert route_editor_request("GET", ["words", str(word_id), "image"], PARENT, b"")[1] == "image/jpeg"
    assert hp.list_pictures(PARENT)["pictures"] == []


def test_failed_unsafe_and_stale_results(root: Path) -> None:
    failed = hp.request_picture(PARENT, new_word("eel"))
    finish(root, failed["id"], {"status": "failed", "error": "timed out"})
    linked = hp.request_picture(PARENT, new_word("cod"))
    finish(root, linked["id"], {"status": "ok"})
    os.symlink(db.DB_PATH, root / "results" / str(linked["id"]) / "card.png")
    skipped = hp.request_picture(PARENT, new_word("pike"))
    hp.skip_picture(PARENT, skipped["id"])
    finish(root, skipped["id"], {"status": "ok"}, png_bytes())

    assert hp.collect_results() == 2
    pictures = {p["id"]: p for p in hp.list_pictures(PARENT)["pictures"]}
    assert pictures[failed["id"]]["error"] == "timed out"
    assert pictures[linked["id"]]["status"] == "failed"
    assert skipped["id"] not in pictures
    assert list((root / "results").iterdir()) == []


def test_worker_state_reads_heartbeat(root: Path) -> None:
    assert hp.worker_state() == "offline"
    root.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc)
    (root / "status.json").write_text(json.dumps({"state": "auth_required", "updated_at": now.isoformat()}))
    assert hp.worker_state() == "auth_required"
    assert hp.worker_state(now + timedelta(minutes=30)) == "offline"


def test_notifications_are_grouped_and_sent_once(root: Path) -> None:
    auto = hp.request_picture(PARENT, new_word("eel"))
    asked = hp.request_picture(CHILD, new_word("cod"))
    finish(root, auto["id"], {"status": "ok"}, png_bytes())
    finish(root, asked["id"], {"status": "failed", "error": "no picture"})
    hp.collect_results()

    assert hp.claim_notifications() == {
        PARENT: {"ready": ["eel"], "failed": []},
        CHILD: {"ready": [], "failed": ["cod"]},
    }
    assert hp.claim_notifications() == {}
    assert hp.claim_auth_alert("auth_required") is True
    assert hp.claim_auth_alert("auth_required") is False
    assert hp.claim_auth_alert("ready") is False
    assert hp.claim_auth_alert("auth_required") is True


def test_editor_routes(root: Path) -> None:
    word_id = new_word()
    assert route_editor_request("GET", ["topics"], PARENT, b"")["heroine"] == {"drawing": 0, "open": 0}
    picture = route_editor_request("POST", ["words", str(word_id), "heroine"], PARENT, json.dumps({"scene": "орёл"}).encode())
    assert route_editor_request("GET", ["topics"], PARENT, b"")["heroine"] == {"drawing": 1, "open": 0}
    listing = route_editor_request("GET", ["heroine"], CHILD, b"")
    assert listing["pictures"][0]["id"] == picture["id"] and "heroine_use" in listing["labels"]
    redrawn = route_editor_request("POST", ["heroine", str(picture["id"]), "redraw"], PARENT, b"{}")
    assert redrawn["id"] != picture["id"] and redrawn["scene_request"] is None
    with pytest.raises(MiniAppError):
        route_editor_request("POST", ["heroine", str(redrawn["id"]), "skip"], STRANGER, b"")


def test_worker_prompt_and_failure_detection(tmp_path: Path) -> None:
    worker = load_worker(tmp_path)
    assert "Examples:" in worker.build_prompt({"word": "eel", "translation": "угорь"})
    prompt = worker.build_prompt({"word": "eagle", "scene": "орёл несёт девочку"})
    assert "орёл несёт девочку" in prompt and "Examples:" not in prompt
    with pytest.raises(worker.AuthRequired):
        worker.classify_failure("error: 401 Unauthorized")
    with pytest.raises(worker.LimitReached):
        worker.classify_failure("You've hit your usage limit")
    worker.classify_failure("something else")


def test_worker_round_trip_with_fake_codex(root: Path, tmp_path: Path) -> None:
    fake = tmp_path / "fake-codex"
    source = tmp_path / "source.png"
    source.write_bytes(png_bytes())
    fake.write_text(
        "#!/bin/sh\n"
        'while [ "$1" != "-C" ]; do shift; done\n'
        f'cp {source} "$2/card.png"\n'
        'printf "Девочка и угорь" > "$2/scene.txt"\n'
    )
    fake.chmod(0o755)
    worker = load_worker(root)
    worker.CODEX = str(fake)
    picture = hp.request_picture(PARENT, new_word())

    job_id, job = worker.next_job()
    worker.process(job_id, job)

    assert not (root / "jobs" / f"{job_id}.json").exists()
    assert hp.collect_results() == 1
    [ready] = hp.list_pictures(PARENT)["pictures"]
    assert ready["id"] == picture["id"] and ready["scene"] == "Девочка и угорь"
