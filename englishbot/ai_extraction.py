"""Optional LLM extraction of learning material from tutor homework via OpenRouter."""

import base64
import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from io import BytesIO

from PIL import Image, ImageOps

from .ai_models import get_model_queue, record_model_result
from .config import get_openrouter_api_key


logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
REQUEST_TIMEOUT_SECONDS = 180
MAX_IMAGE_SIDE = 1600
MAX_ITEMS = 150

KIND_WORDS = "words"
# Extension point: add "verbs" or "phrases" with their own prompt and normalizer.
SUPPORTED_KINDS = (KIND_WORDS,)

WORDS_PROMPT = """You extract vocabulary from a tutor's English homework for a 9-year-old child who speaks Russian.
Return ONLY a JSON object, no prose: {"words":[{"en":"...","ru":"...","topic":"..."}]}
Rules:
- Include English words or short word groups the child must learn as vocabulary.
- "ru" is the Russian translation. Copy the translation from the material when given (convert Ukrainian to Russian). If none is given, translate it yourself.
- If the source lists alternatives like "Birthday boy / Birthday girl", make separate entries.
- "topic" is a short English topic name such as "Fairy Tales" or "Food"; use one topic for one list.
- Skip letters, sounds, phonics rules, transcriptions, grammar explanations, whole sentences, and instructions to the parent.
- Never invent words that are not in the material. An empty list is fine."""


class AIExtractionUnavailable(Exception):
    """Raised when extraction is not configured or every model failed."""


@dataclass
class ExtractionSource:
    text: str | None = None
    image: bytes | None = None


@dataclass
class ExtractionResult:
    model: str
    items: list[dict[str, str]] = field(default_factory=list)


def is_ai_extraction_configured() -> bool:
    return get_openrouter_api_key() is not None and bool(get_model_queue())


def _prepare_image(content: bytes) -> str:
    with Image.open(BytesIO(content)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        output = BytesIO()
        image.save(output, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def _build_user_content(sources: list[ExtractionSource]) -> list[dict[str, object]]:
    content: list[dict[str, object]] = [
        {"type": "text", "text": "Homework material follows (forwarded messages and pictures)."}
    ]
    for source in sources:
        if source.text:
            content.append({"type": "text", "text": source.text})
        if source.image:
            content.append({"type": "image_url", "image_url": {"url": _prepare_image(source.image)}})
    return content


def parse_json_object(raw: str) -> dict[str, object]:
    """Extract the first JSON object from a model reply, tolerating code fences and prose."""
    match = re.search(r"\{.*\}", raw or "", re.S)
    if match is None:
        raise ValueError("no JSON object in model reply")
    payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("model reply is not a JSON object")
    return payload


def normalize_words(payload: dict[str, object]) -> list[dict[str, str]]:
    words = payload.get("words")
    if not isinstance(words, list):
        return []
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for entry in words:
        if not isinstance(entry, dict):
            continue
        english = " ".join(str(entry.get("en") or "").split())
        russian = " ".join(str(entry.get("ru") or "").split())
        topic = " ".join(str(entry.get("topic") or "").split())
        key = english.lower()
        if not english or len(english) > 100 or key in seen:
            continue
        seen.add(key)
        result.append({"en": english, "ru": russian[:200], "topic": topic[:100]})
        if len(result) >= MAX_ITEMS:
            break
    return result


def _post(body: dict[str, object], api_key: str) -> dict[str, object]:
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "EnglishBot",
        },
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.load(response)


def _try_model(model: str, messages: list[dict[str, object]], api_key: str) -> dict[str, object]:
    started = time.monotonic()
    try:
        response = _post({"model": model, "messages": messages, "temperature": 0}, api_key)
        payload = parse_json_object(response["choices"][0]["message"]["content"])
    except urllib.error.HTTPError as exc:
        error = f"HTTP {exc.code}"
    except (OSError, KeyError, IndexError, TypeError, ValueError) as exc:
        error = f"{type(exc).__name__}: {exc}"
    else:
        record_model_result(model, ok=True, seconds=time.monotonic() - started)
        return payload
    record_model_result(model, ok=False, seconds=time.monotonic() - started, error=error)
    logger.warning("AI model failed: model=%s error=%s", model, error)
    raise AIExtractionUnavailable(error)


def extract_items(kind: str, sources: list[ExtractionSource], *, models: list[str] | None = None) -> ExtractionResult:
    """Try each queued model in order and record per-model success or failure."""
    if kind not in SUPPORTED_KINDS:
        raise ValueError(f"unsupported extraction kind: {kind}")
    api_key = get_openrouter_api_key()
    queue = models if models is not None else get_model_queue()
    if api_key is None or not queue:
        raise AIExtractionUnavailable("AI extraction is not configured")
    messages = [
        {"role": "system", "content": WORDS_PROMPT},
        {"role": "user", "content": _build_user_content(sources)},
    ]
    errors = []
    for model in queue:
        try:
            payload = _try_model(model, messages, api_key)
        except AIExtractionUnavailable as exc:
            errors.append(f"{model}: {exc}")
            continue
        items = normalize_words(payload)
        logger.info("AI extraction done: kind=%s model=%s items=%d sources=%d", kind, model, len(items), len(sources))
        return ExtractionResult(model=model, items=items)
    raise AIExtractionUnavailable("; ".join(errors))
