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
from .verbs import VerbFormsError, validate_forms


logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
REQUEST_TIMEOUT_SECONDS = 180
MAX_IMAGE_SIDE = 1600
MAX_ITEMS = 150

KIND_WORDS = "words"  # one pass drafts both vocabulary and irregular verbs
# Extension point: add "phrases" with its own prompt and normalizer.
SUPPORTED_KINDS = (KIND_WORDS,)

WORDS_PROMPT = """You extract learning material from a tutor's English homework for a 9-year-old child who speaks Russian.
Return ONLY a JSON object, no prose:
{"words":[{"en":"...","ru":"...","topic":"..."}],
 "verbs":[{"base":"...","past":"...","participle":"...","ru":"..."}]}
Words:
- Include English words or short word groups the child must learn as vocabulary.
- "ru" is the Russian translation. Copy the translation from the material when given (convert Ukrainian to Russian). If none is given, translate it yourself.
- If the source lists alternatives like "Birthday boy / Birthday girl", make separate entries.
- "topic" is a short English topic name such as "Fairy Tales" or "Food"; use one topic for one list.
- Skip letters, sounds, phonics rules, transcriptions, grammar explanations, whole sentences, and instructions to the parent.
- Never invent words that are not in the material. An empty list is fine.
- Pictures are numbered ("Picture 1", "Picture 2", ...). When a word has its own drawing or photo in a picture, add
  "picture": that number and "box": [y_min, x_min, y_max, x_max] around the drawing only, normalized to 0-1000.
  The box must exclude all printed text: the word, transcription, and translation. In a matching exercise, match
  the word to the drawing that shows it. Leave both out when the word has no drawing of its own.
Verbs:
- A verb given with its forms ("sing sang sung - петь", "go - went - gone", a table of irregular verbs) goes to "verbs",
  one entry per verb, and never to "words". Put each form in its own field: "base" (V1), "past" (V2), "participle" (V3).
- Keep alternatives in one field with a slash and no spaces: "be" -> "past": "was/were".
- If the material is an irregular verbs list but a form of a listed verb is missing, fill it in from your knowledge.
  Do not add verbs that are not in the material.
- "ru" is the Russian infinitive ("петь"); copy it when given (convert Ukrainian to Russian), otherwise translate.
- Lower case, no "to", no transcription, no punctuation."""


class AIExtractionUnavailable(Exception):
    """Raised when extraction is not configured or every model failed."""


@dataclass
class ExtractionSource:
    text: str | None = None
    image: bytes | None = None


@dataclass
class ExtractionResult:
    model: str
    items: list[dict[str, object]] = field(default_factory=list)
    verbs: list[dict[str, str]] = field(default_factory=list)


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
    picture = 0
    for source in sources:
        if source.text:
            content.append({"type": "text", "text": source.text})
        if source.image:
            picture += 1
            content.append({"type": "text", "text": f"Picture {picture}:"})
            content.append({"type": "image_url", "image_url": {"url": _prepare_image(source.image)}})
    return content


def _picture_box(entry: dict[str, object]) -> dict[str, object]:
    """The picture number and 0-1000 box of a word's drawing, or nothing when absent or malformed."""
    box = entry.get("box")
    try:
        picture = int(str(entry.get("picture")).strip())
    except ValueError:
        return {}
    if picture < 1:
        return {}
    if not isinstance(box, list) or len(box) != 4:
        return {}
    try:
        y_min, x_min, y_max, x_max = (max(0.0, min(1000.0, float(value))) for value in box)
    except (TypeError, ValueError):
        return {}
    if y_max - y_min < 20 or x_max - x_min < 20:
        return {}
    return {"picture": picture, "box": [y_min, x_min, y_max, x_max]}


def parse_json_object(raw: str) -> dict[str, object]:
    """Extract the first JSON object from a model reply, tolerating code fences and prose."""
    match = re.search(r"\{.*\}", raw or "", re.S)
    if match is None:
        raise ValueError("no JSON object in model reply")
    payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("model reply is not a JSON object")
    return payload


def _split_forms(text: str) -> list[str]:
    """ "go - went - gone" or "sing sang sung" -> forms; "was / were" stays one form."""
    text = re.sub(r"\s*/\s*", "/", text.strip().lower())
    return [part for part in re.split(r"[\s,;\u2013\u2014-]+", text) if part]


def _verb_entry(base: object, past: object, participle: object, russian: object) -> dict[str, str] | None:
    try:
        clean_base, clean_past, clean_participle = validate_forms(base, past, participle)
    except VerbFormsError:
        return None
    return {"base": clean_base, "past": clean_past, "participle": clean_participle, "ru": " ".join(str(russian or "").split())[:200]}


def _word_as_verb(entry: dict[str, object]) -> dict[str, str] | None:
    """Safety net: a "word" that is really three verb forms in one cell, e.g. "go went gone"."""
    topic = str(entry.get("topic") or "").lower()
    forms = _split_forms(str(entry.get("en") or ""))
    if len(forms) != 3 or ("verb" not in topic and "глагол" not in topic and "дієслов" not in topic):
        return None
    return _verb_entry(*forms, entry.get("ru"))


def normalize_verbs(payload: dict[str, object], extra: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    verbs = payload.get("verbs")
    entries = [entry for entry in verbs if isinstance(entry, dict)] if isinstance(verbs, list) else []
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    candidates = [
        _verb_entry(entry.get("base"), entry.get("past"), entry.get("participle"), entry.get("ru")) for entry in entries
    ] + list(extra or [])
    for verb in candidates:
        if verb is None or verb["base"] in seen:
            continue
        seen.add(verb["base"])
        result.append(verb)
        if len(result) >= MAX_ITEMS:
            break
    return result


def normalize_words(payload: dict[str, object], verbs_found: list[dict[str, str]] | None = None) -> list[dict[str, object]]:
    """Clean word entries; entries that are really verb forms go to verbs_found instead when it is given."""
    words = payload.get("words")
    if not isinstance(words, list):
        return []
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for entry in words:
        if not isinstance(entry, dict):
            continue
        if verbs_found is not None:
            verb = _word_as_verb(entry)
            if verb is not None:
                verbs_found.append(verb)
                continue
        english = " ".join(str(entry.get("en") or "").split())
        russian = " ".join(str(entry.get("ru") or "").split())
        topic = " ".join(str(entry.get("topic") or "").split())
        key = english.lower()
        if not english or len(english) > 100 or key in seen:
            continue
        seen.add(key)
        result.append({"en": english, "ru": russian[:200], "topic": topic[:100], **_picture_box(entry)})
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
        misplaced: list[dict[str, str]] = []
        items = normalize_words(payload, misplaced)
        verbs = normalize_verbs(payload, misplaced)
        logger.info(
            "AI extraction done: kind=%s model=%s items=%d verbs=%d sources=%d",
            kind, model, len(items), len(verbs), len(sources),
        )
        return ExtractionResult(model=model, items=items, verbs=verbs)
    raise AIExtractionUnavailable("; ".join(errors))
