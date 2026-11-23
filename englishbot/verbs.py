"""Irregular verbs: a learning item whose text is the base form and whose details hold V2 and V3.

A verb is drilled by showing the base form with its translation and asking for the second and
third forms; the expected answer is "V2 V3" (e.g. "went gone", "was/were been").
"""

import json
import re

from .db import get_connection, utc_now
from .i18n import translate_for_user


ITEM_TYPE_WORD = "word"
ITEM_TYPE_VERB = "verb"
MAX_FORM_LENGTH = 40
DEFAULT_VERB_TOPIC = "Irregular verbs"

_FORM_RE = re.compile(r"^[a-z][a-z']*(/[a-z][a-z']*)*$")
_ANSWER_SPLIT_RE = re.compile(r"[\s,;/]+|\s*[-–—]+\s*")


class VerbFormsError(ValueError):
    pass


def clean_form(value: object) -> str:
    """One verb form in lower case; alternatives keep a slash without spaces ("was/were")."""
    text = " ".join(str(value or "").split()).lower()
    text = re.sub(r"\s*/\s*", "/", text)
    text = text.replace("’", "'")
    return text


def validate_forms(base: object, past: object, participle: object) -> tuple[str, str, str]:
    forms = (clean_form(base), clean_form(past), clean_form(participle))
    for form in forms:
        if not form or len(form) > MAX_FORM_LENGTH or not _FORM_RE.match(form):
            raise VerbFormsError("invalid_verb_forms")
    return forms


def dump_details(past: str, participle: str) -> str:
    return json.dumps({"past": past, "participle": participle}, ensure_ascii=False)


def load_forms(details_json: object) -> tuple[str, str] | None:
    """(past, participle) from stored details, or None when they are missing or broken."""
    try:
        details = json.loads(str(details_json or ""))
    except ValueError:
        return None
    if not isinstance(details, dict):
        return None
    past, participle = clean_form(details.get("past")), clean_form(details.get("participle"))
    if not past or not participle:
        return None
    return past, participle


def expected_answer(past: str, participle: str) -> str:
    return f"{past} {participle}"


def speech_text(base: str, answer: str) -> str:
    """All three forms read aloud: "go, went, gone"; alternatives become "was or were"."""
    forms = [base, *answer.split()]
    return ", ".join(form.replace("/", " or ") for form in forms)


def _slots(answer: str) -> list[set[str]]:
    return [set(slot.split("/")) for slot in answer.casefold().split()]


def answer_matches(expected: str, given: str) -> bool:
    """Compare "V2 V3" answers ignoring case and separators; "was/were" accepts was, were, or both."""
    tokens = [token for token in _ANSWER_SPLIT_RE.split(given.casefold().replace("’", "'")) if token]
    slots = _slots(expected)
    position = 0
    for alternatives in slots:
        taken: set[str] = set()
        while position < len(tokens) and tokens[position] in alternatives - taken:
            taken.add(tokens[position])
            position += 1
        if not taken:
            return False
    return position == len(tokens)


def regular_guess(base: str) -> str:
    """The typical learner mistake: the verb made regular (go -> goed, make -> maked)."""
    word = base.split("/")[0]
    if word.endswith("e"):
        return word + "d"
    if len(word) > 1 and word.endswith("y") and word[-2] not in "aeiou":
        return word[:-1] + "ied"
    return word + "ed"


def tricky_options(base: str, answer: str) -> list[str]:
    """Wrong "V2 V3" answers built from the verb itself, most confusing first."""
    parts = answer.split()
    if len(parts) != 2:
        return []
    past, participle = parts
    guess = regular_guess(base)
    candidates = [
        f"{participle} {past}",
        f"{past} {past}",
        f"{participle} {participle}",
        f"{guess} {guess}",
        f"{past} {guess}",
        f"{base} {participle}",
    ]
    result: list[str] = []
    for candidate in candidates:
        if candidate != answer and candidate not in result:
            result.append(candidate)
    return result


def find_family_verb(connection, family_id: int, base: str) -> int | None:
    row = connection.execute(
        """
        SELECT id FROM learning_items
        WHERE family_id = ? AND is_archived = 0 AND item_type = ? AND lower(text) = ?
        ORDER BY id LIMIT 1
        """,
        (family_id, ITEM_TYPE_VERB, base.lower()),
    ).fetchone()
    return int(row["id"]) if row is not None else None


def _lexeme_id(connection, lemma: str) -> int:
    row = connection.execute("SELECT id FROM lexemes WHERE lemma = ?", (lemma,)).fetchone()
    if row is not None:
        return int(row["id"])
    timestamp = utc_now()
    return int(connection.execute(
        "INSERT INTO lexemes (lemma, created_at, updated_at) VALUES (?, ?, ?)", (lemma, timestamp, timestamp)
    ).lastrowid)


def create_family_verb(family_id: int, topic_id: int, base: str, past: str, participle: str, russian: str = "") -> int:
    """A new verb item linked to the topic; the base form may also exist as a plain word."""
    base, past, participle = validate_forms(base, past, participle)
    timestamp = utc_now()
    with get_connection() as connection:
        verb_id = int(connection.execute(
            """
            INSERT INTO learning_items (family_id, lexeme_id, text, is_archived, item_type, details_json, created_at, updated_at)
            VALUES (?, ?, ?, 0, ?, ?, ?, ?)
            """,
            (family_id, _lexeme_id(connection, base), base, ITEM_TYPE_VERB, dump_details(past, participle), timestamp, timestamp),
        ).lastrowid)
        if russian:
            connection.execute(
                """
                INSERT INTO learning_item_translations (learning_item_id, language_code, translation_text, created_at, updated_at)
                VALUES (?, 'ru', ?, ?, ?)
                """,
                (verb_id, russian, timestamp, timestamp),
            )
        connection.execute("INSERT INTO topic_items (topic_id, learning_item_id) VALUES (?, ?)", (topic_id, verb_id))
    return verb_id


def set_item_verb_forms(connection, item_id: int, forms: dict[str, object] | None, base: str) -> None:
    """Make the item a verb with these forms, or a plain word when forms is None."""
    if forms is None:
        connection.execute(
            "UPDATE learning_items SET item_type = ?, details_json = NULL, updated_at = ? WHERE id = ?",
            (ITEM_TYPE_WORD, utc_now(), item_id),
        )
        return
    _, past, participle = validate_forms(base, forms.get("past"), forms.get("participle"))
    connection.execute(
        "UPDATE learning_items SET item_type = ?, details_json = ?, updated_at = ? WHERE id = ?",
        (ITEM_TYPE_VERB, dump_details(past, participle), utc_now(), item_id),
    )


def verb_task_text(telegram_user_id: int, question: dict[str, object]) -> str | None:
    """What to answer for a verb question: the 2nd and 3rd forms, typed with a space in hard mode."""
    if question.get("item_type") != ITEM_TYPE_VERB:
        return None
    key = "training.verb.ask_typed" if question.get("exercise_type") == "typed_answer" else "training.verb.ask"
    return translate_for_user(telegram_user_id, key)
