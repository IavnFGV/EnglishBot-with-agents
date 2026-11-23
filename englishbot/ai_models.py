"""Free OpenRouter model queue: stored order, per-model stats, and sync with the live catalog."""

import json
import logging
import urllib.request

from .config import get_ai_models
from .db import get_connection, utc_now


logger = logging.getLogger(__name__)

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
QUEUE_SETTING = "ai_model_queue"
KNOWN_FREE_SETTING = "ai_known_free_models"
MAX_QUEUE_LENGTH = 10


def _get_setting(key: str):
    with get_connection() as connection:
        row = connection.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row is not None else None


def _set_setting(key: str, value) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, json.dumps(value), utc_now()),
        )


def is_free_model_id(model: str) -> bool:
    # Only ":free" variants are allowed, so a model that stops being free fails instead of charging.
    return isinstance(model, str) and model.endswith(":free") and 0 < len(model) <= 200


def get_model_queue() -> list[str]:
    """The saved queue wins; otherwise the env or built-in default applies."""
    saved = _get_setting(QUEUE_SETTING)
    if isinstance(saved, list):
        return [model for model in saved if is_free_model_id(model)]
    return [model for model in get_ai_models() if is_free_model_id(model)]


def set_model_queue(models: list[str]) -> list[str]:
    clean: list[str] = []
    for model in models:
        if not is_free_model_id(model):
            raise ValueError(f"not a free model id: {model!r}")
        if model not in clean:
            clean.append(model)
    if len(clean) > MAX_QUEUE_LENGTH:
        raise ValueError("queue is too long")
    _set_setting(QUEUE_SETTING, clean)
    return clean


def record_model_result(model: str, *, ok: bool, seconds: float, error: str | None = None) -> None:
    timestamp = utc_now()
    with get_connection() as connection:
        connection.execute("INSERT OR IGNORE INTO ai_model_stats (model) VALUES (?)", (model,))
        if ok:
            connection.execute(
                """
                UPDATE ai_model_stats
                SET successes = successes + 1, total_success_seconds = total_success_seconds + ?, last_success_at = ?
                WHERE model = ?
                """,
                (seconds, timestamp, model),
            )
        else:
            connection.execute(
                "UPDATE ai_model_stats SET failures = failures + 1, last_failure_at = ?, last_error = ? WHERE model = ?",
                (timestamp, (error or "")[:300], model),
            )


def get_model_stats() -> dict[str, dict[str, object]]:
    with get_connection() as connection:
        rows = connection.execute("SELECT * FROM ai_model_stats").fetchall()
    return {
        str(row["model"]): {
            "successes": int(row["successes"]),
            "failures": int(row["failures"]),
            "avg_seconds": round(float(row["total_success_seconds"]) / int(row["successes"]), 1) if row["successes"] else None,
            "last_success_at": row["last_success_at"],
            "last_failure_at": row["last_failure_at"],
            "last_error": row["last_error"],
        }
        for row in rows
    }


def fetch_free_vision_models(timeout_seconds: int = 30) -> list[dict[str, object]]:
    """Free models that read images and answer with text (the catalog needs no API key)."""
    with urllib.request.urlopen(OPENROUTER_MODELS_URL, timeout=timeout_seconds) as response:
        catalog = json.load(response).get("data", [])
    models = []
    for entry in catalog:
        architecture = entry.get("architecture") or {}
        if (
            is_free_model_id(str(entry.get("id", "")))
            and "image" in (architecture.get("input_modalities") or [])
            and "text" in (architecture.get("output_modalities") or ["text"])
        ):
            models.append({
                "id": str(entry["id"]),
                "name": str(entry.get("name") or entry["id"]),
                "context_length": entry.get("context_length"),
            })
    models.sort(key=lambda model: str(model["name"]).lower())
    return models


def sync_model_queue(available_ids: list[str]) -> dict[str, list[str]]:
    """Drop queued models that are no longer free; report free models not seen before."""
    available = set(available_ids)
    queue = get_model_queue()
    removed = [model for model in queue if model not in available]
    if removed:
        set_model_queue([model for model in queue if model in available])
    known = _get_setting(KNOWN_FREE_SETTING)
    new = [] if known is None else sorted(available - set(known))
    _set_setting(KNOWN_FREE_SETTING, sorted(available))
    return {"removed": removed, "new": new, "queue": get_model_queue()}


_catalog_cache: dict[str, object] = {"at": 0.0, "models": None}
CATALOG_CACHE_SECONDS = 600

# A short realistic homework sample: four words to find among phonics and speaking noise.
TEST_SAMPLE = (
    "НТ\n1) Повторить буквосочетания sh /ш/, ch /ч/\n"
    "2) Выучить слова, тема «Сказки»:\nDragon — дракон\nCastle — замок\nWizard / Witch — волшебник / ведьма\n"
    "3) Разговорная практика: Do you like dragons? — Yes, I do."
)
TEST_EXPECTED = ("dragon", "castle", "wizard", "witch")


def get_free_vision_models_cached() -> list[dict[str, object]]:
    import time

    now = time.monotonic()
    if _catalog_cache["models"] is None or now - float(_catalog_cache["at"]) > CATALOG_CACHE_SECONDS:
        _catalog_cache["models"] = fetch_free_vision_models()
        _catalog_cache["at"] = now
    return list(_catalog_cache["models"])


def run_model_check(model: str) -> dict[str, object]:
    """Run the sample extraction on one model and score it against the expected words."""
    import time

    from .ai_extraction import AIExtractionUnavailable, ExtractionSource, extract_items

    if not is_free_model_id(model):
        raise ValueError("not a free model id")
    started = time.monotonic()
    try:
        result = extract_items("words", [ExtractionSource(text=TEST_SAMPLE)], models=[model])
    except AIExtractionUnavailable as exc:
        return {"ok": False, "seconds": round(time.monotonic() - started, 1), "error": str(exc)}
    found = {item["en"].lower() for item in result.items}
    return {
        "ok": True,
        "seconds": round(time.monotonic() - started, 1),
        "found": sum(1 for word in TEST_EXPECTED if word in found),
        "expected": len(TEST_EXPECTED),
        "items": result.items,
    }
