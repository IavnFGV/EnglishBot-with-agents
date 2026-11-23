"""Heroine artist: draws word pictures with the Codex CLI for EnglishBot.

Runs in its own container with no bot secrets and no database. It shares one folder
with the bot (see englishbot/heroine_pictures.py for the protocol):
  jobs/<id>.json -> results/<id>/card.png + result.json, plus status.json as a heartbeat.
Reference cards of the heroine live in refs/. Standard library only.
"""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(os.environ.get("HEROINE_DIR", "/work"))
CODEX = os.environ.get("CODEX_BIN", "codex")
JOB_TIMEOUT_SECONDS = int(os.environ.get("HEROINE_JOB_TIMEOUT_SECONDS", "600"))
IDLE_SECONDS = 10
AUTH_RETRY_SECONDS = 60
LIMIT_RETRY_SECONDS = 30 * 60
HEARTBEAT_SECONDS = 60
# More varied references keep the face steadier, but each one costs Codex usage.
MAX_REFS = int(os.environ.get("HEROINE_MAX_REFS", "5"))
AUTH_MARKERS = ("unauthorized", "401", "not logged in", "sign in again", "log in again", "refresh token", "login required")
LIMIT_MARKERS = ("usage limit", "rate limit", "429", "too many requests")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")

SCENE_EXAMPLES = (
    "eel: the girl eats sushi and an eel winks at her from the plate",
    "eagle: an eagle carries the girl up a mountain by the straps of her overalls",
    "sour: the girl bites a lemon and her whole face wrinkles up",
    "umbrella: the girl holds an umbrella while a tiny cloud rains only on her cat",
)


class AuthRequired(Exception):
    pass


class LimitReached(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial")
    partial.write_bytes(content)
    os.replace(partial, path)


class Heartbeat:
    """Keeps status.json fresh, also while a long Codex run is in progress."""

    def __init__(self) -> None:
        self.state = "ready"
        self._lock = threading.Lock()

    def set(self, state: str) -> None:
        with self._lock:
            self.state = state
            self.write()

    def write(self) -> None:
        atomic_write(ROOT / "status.json", json.dumps({"state": self.state, "updated_at": _now()}).encode())

    def run_forever(self) -> None:
        while True:
            time.sleep(HEARTBEAT_SECONDS)
            with self._lock:
                self.write()


def build_prompt(job: dict) -> str:
    word = str(job.get("word") or "").strip()
    translation = str(job.get("translation") or "").strip()
    scene = str(job.get("scene") or "").strip()
    meaning = f" (Russian: {translation})" if translation else ""
    if scene:
        scene_part = f"Scene, the parent's idea (it may be written in Russian): {scene}"
    else:
        scene_part = (
            "First invent the scene yourself: funny and a bit absurd where it fits, "
            "so that the meaning of the word is obvious. Examples: " + "; ".join(SCENE_EXAMPLES) + "."
        )
    return (
        "Use your image generation tool. The attached pictures show one cartoon heroine: "
        "a little girl with brown curly hair, sticker-card style with a white rounded border. "
        "Draw a NEW picture of the same girl, same style and same face, "
        f"for a children's English vocabulary card for the word '{word}'{meaning}. "
        f"{scene_part} "
        f"The meaning of '{word}' must be obvious from the picture. Bright colors, child-friendly, "
        "no text, letters or captions in the picture. Religious words get calm, respectful scenes. "
        "Save the result as card.png in the current directory. Then write scene.txt in the current "
        "directory: one short sentence in Russian describing what the picture shows."
    )


def classify_failure(output: str) -> None:
    lowered = output.lower()
    if any(marker in lowered for marker in AUTH_MARKERS):
        raise AuthRequired(output[-300:])
    if any(marker in lowered for marker in LIMIT_MARKERS):
        raise LimitReached(output[-300:])


def logged_in() -> bool:
    try:
        return subprocess.run([CODEX, "login", "status"], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def reference_images() -> list[Path]:
    refs = ROOT / "refs"
    if not refs.is_dir():
        return []
    return sorted(path for path in refs.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES)[:MAX_REFS]


def find_card(workdir: Path) -> Path | None:
    card = workdir / "card.png"
    if card.is_file():
        return card
    images = sorted((path for path in workdir.rglob("*") if path.suffix.lower() in IMAGE_SUFFIXES and path.is_file()),
                    key=lambda path: path.stat().st_mtime)
    return images[-1] if images else None


def run_codex(job: dict, workdir: Path) -> dict:
    command = [CODEX, "exec", "--skip-git-repo-check", "--ephemeral",
               "--dangerously-bypass-approvals-and-sandbox", "--enable", "image_generation", "-C", str(workdir)]
    for ref in reference_images():
        command += ["-i", str(ref)]
    # -i takes several values, so another flag must follow it before the prompt.
    command += ["-o", str(workdir / "last.txt"), build_prompt(job)]
    try:
        completed = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                   timeout=JOB_TIMEOUT_SECONDS)
        output = f"{completed.stdout}\n{completed.stderr}"
        failed = completed.returncode != 0
    except subprocess.TimeoutExpired:
        return {"status": "failed", "error": "timed out"}
    card = find_card(workdir)
    if card is None:
        classify_failure(output)
        reason = "exit code" if failed else "no picture"
        return {"status": "failed", "error": f"{reason}: {output.strip()[-200:]}"}
    scene_file = workdir / "scene.txt"
    scene = scene_file.read_text(encoding="utf-8", errors="replace").strip() if scene_file.is_file() else ""
    return {"status": "ok", "scene": scene[:500], "card": card}


def publish(job_id: int, outcome: dict) -> None:
    target = ROOT / "results" / str(job_id)
    target.mkdir(parents=True, exist_ok=True)
    card = outcome.pop("card", None)
    if card is not None:
        shutil.copyfile(card, target / "card.png")
    # result.json is written last: the bot treats its presence as "complete".
    atomic_write(target / "result.json", json.dumps(outcome, ensure_ascii=False).encode())
    (ROOT / "jobs" / f"{job_id}.json").unlink(missing_ok=True)


def next_job() -> tuple[int, dict] | None:
    jobs_dir = ROOT / "jobs"
    if not jobs_dir.is_dir():
        return None
    for path in sorted((p for p in jobs_dir.glob("*.json") if p.stem.isdigit()), key=lambda p: int(p.stem)):
        try:
            return int(path.stem), json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            publish(int(path.stem), {"status": "failed", "error": "unreadable job"})
    return None


def process(job_id: int, job: dict) -> None:
    """Draw one job, retrying a plain failure once; auth and limit errors propagate."""
    outcome = {}
    for _ in range(2):
        with tempfile.TemporaryDirectory(prefix=f"job-{job_id}-") as tmp:
            outcome = run_codex(job, Path(tmp))
            if outcome["status"] == "ok":
                publish(job_id, outcome)
                return
    publish(job_id, outcome)


def main() -> None:
    heartbeat = Heartbeat()
    heartbeat.write()
    threading.Thread(target=heartbeat.run_forever, daemon=True).start()
    while True:
        if not logged_in():
            heartbeat.set("auth_required")
            time.sleep(AUTH_RETRY_SECONDS)
            continue
        found = next_job()
        if found is None:
            heartbeat.set("ready")
            time.sleep(IDLE_SECONDS)
            continue
        job_id, job = found
        heartbeat.set("busy")
        print(f"[artist] drawing job {job_id}: {job.get('word')!r}", flush=True)
        try:
            process(job_id, job)
            print(f"[artist] job {job_id} done", flush=True)
        except AuthRequired as exc:
            print(f"[artist] login required: {exc}", flush=True)
            heartbeat.set("auth_required")
            time.sleep(AUTH_RETRY_SECONDS)
        except LimitReached as exc:
            print(f"[artist] usage limit: {exc}", flush=True)
            heartbeat.set("limited")
            time.sleep(LIMIT_RETRY_SECONDS)


if __name__ == "__main__":
    main()
