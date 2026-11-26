"""Irregular verbs: one shared list (`irregular_verbs`) holds every verb's three forms.

A family verb is a learning item (item_type 'verb') whose text is the base form and whose
verb_id points at the list. It is drilled by showing the base form with its translation and
asking for the second and third forms; the expected answer is "V2 V3" (e.g. "went gone").
"""

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


# SQL pieces that read a learning item's forms from the list.
VERB_JOIN = "LEFT JOIN irregular_verbs ON irregular_verbs.id = learning_items.verb_id"
VERB_COLUMNS = "irregular_verbs.past AS verb_past, irregular_verbs.participle AS verb_participle"


def row_forms(row) -> tuple[str, str] | None:
    """(past, participle) from a row selected with VERB_COLUMNS, or None for a plain word."""
    if row["verb_past"] and row["verb_participle"]:
        return str(row["verb_past"]), str(row["verb_participle"])
    return None


def get_verb_forms(verb_id: object) -> tuple[str, str] | None:
    if verb_id is None:
        return None
    with get_connection() as connection:
        row = connection.execute("SELECT past, participle FROM irregular_verbs WHERE id = ?", (int(verb_id),)).fetchone()
    return (str(row["past"]), str(row["participle"])) if row is not None else None


def _serialize_list_verb(row) -> dict[str, object]:
    return {"id": int(row["id"]), "base": str(row["base"]), "past": str(row["past"]),
            "participle": str(row["participle"]), "ru": str(row["translation_ru"])}


def list_verbs(connection) -> list[dict[str, object]]:
    rows = connection.execute("SELECT * FROM irregular_verbs ORDER BY base").fetchall()
    return [_serialize_list_verb(row) for row in rows]


def find_list_verb(connection, base: object) -> dict[str, object] | None:
    row = connection.execute("SELECT * FROM irregular_verbs WHERE base = ?", (clean_form(base),)).fetchone()
    return _serialize_list_verb(row) if row is not None else None


def add_list_verb(connection, base: object, past: object, participle: object, russian: str = "") -> dict[str, object]:
    """Add a verb missing from the list (e.g. one from a tutor's homework); an existing one is returned as is."""
    base, past, participle = validate_forms(base, past, participle)
    connection.execute(
        "INSERT OR IGNORE INTO irregular_verbs (base, past, participle, translation_ru, created_at) VALUES (?, ?, ?, ?, ?)",
        (base, past, participle, russian, utc_now()),
    )
    return find_list_verb(connection, base)  # type: ignore[return-value]


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


def find_family_verb(connection, family_id: int, verb_id: int) -> int | None:
    row = connection.execute(
        """
        SELECT id FROM learning_items
        WHERE family_id = ? AND is_archived = 0 AND item_type = ? AND verb_id = ?
        ORDER BY id LIMIT 1
        """,
        (family_id, ITEM_TYPE_VERB, verb_id),
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


def ensure_family_verb(connection, family_id: int, topic_id: int, verb: dict[str, object]) -> tuple[int, bool]:
    """The family's item for a listed verb, created under the topic on first use; returns (id, created)."""
    existing = find_family_verb(connection, family_id, int(verb["id"]))
    if existing is None:
        timestamp = utc_now()
        existing = int(connection.execute(
            """
            INSERT INTO learning_items (family_id, lexeme_id, text, is_archived, item_type, verb_id, created_at, updated_at)
            VALUES (?, ?, ?, 0, ?, ?, ?, ?)
            """,
            (family_id, _lexeme_id(connection, str(verb["base"])), verb["base"], ITEM_TYPE_VERB, int(verb["id"]), timestamp, timestamp),
        ).lastrowid)
        if verb["ru"]:
            connection.execute(
                """
                INSERT INTO learning_item_translations (learning_item_id, language_code, translation_text, created_at, updated_at)
                VALUES (?, 'ru', ?, ?, ?)
                """,
                (existing, verb["ru"], timestamp, timestamp),
            )
        created = True
    else:
        created = False
    linked = connection.execute(
        "SELECT 1 FROM topic_items WHERE topic_id = ? AND learning_item_id = ?", (topic_id, existing)
    ).fetchone()
    if linked is None:
        connection.execute("INSERT INTO topic_items (topic_id, learning_item_id) VALUES (?, ?)", (topic_id, existing))
    return existing, created


def verb_task_text(telegram_user_id: int, question: dict[str, object]) -> str | None:
    """What to answer for a verb question: the 2nd and 3rd forms, typed with a space in hard mode."""
    if question.get("item_type") != ITEM_TYPE_VERB:
        return None
    key = "training.verb.ask_typed" if question.get("exercise_type") == "typed_answer" else "training.verb.ask"
    return translate_for_user(telegram_user_id, key)
