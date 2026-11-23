from pathlib import Path

import pytest
from aiogram.types import User

from englishbot import db
from englishbot.ai_extraction import ExtractionResult, normalize_verbs, normalize_words
from englishbot.dictionary_editor import create_topic, create_word, list_words, search_words, update_word
from englishbot.families import add_family_member, create_family
from englishbot.homework_dialog import _drill_line
from englishbot.homework_sets import add_source, begin_processing, get_draft, get_set, save_draft, store_extraction
from englishbot.mini_app import MiniAppError, public_question
from englishbot.training import create_training_session_for_learning_items, get_current_question, submit_training_answer
from englishbot.training_handlers import render_question_text
from englishbot.verbs import answer_matches, regular_guess, tricky_options, validate_forms, VerbFormsError


MOM = 951
KID = 952


@pytest.fixture
def family(tmp_path: Path) -> int:
    db.DB_PATH = tmp_path / "verbs.sqlite3"
    db.init_db()
    for user_id, name in ((MOM, "Mom"), (KID, "Teia")):
        db.save_user(User(id=user_id, is_bot=False, first_name=name))
    family_row = create_family("Home", MOM)
    add_family_member(int(family_row["id"]), KID)
    return int(family_row["id"])


# Forms and answers


def test_answer_matches_ignores_separators_and_accepts_alternatives() -> None:
    assert answer_matches("went gone", "went gone")
    assert answer_matches("went gone", " Went, gone ")
    assert answer_matches("went gone", "went - gone")
    assert answer_matches("went gone", "went/gone")
    assert not answer_matches("went gone", "gone went")
    assert not answer_matches("went gone", "went")
    assert not answer_matches("went gone", "went gone go")
    assert answer_matches("was/were been", "was been")
    assert answer_matches("was/were been", "were been")
    assert answer_matches("was/were been", "was/were been")
    assert answer_matches("was/were been", "was, were, been")
    assert not answer_matches("was/were been", "was was been")
    assert not answer_matches("was/were been", "been")


def test_tricky_options_are_mistakes_of_the_same_verb() -> None:
    assert regular_guess("make") == "maked" and regular_guess("cry") == "cried" and regular_guess("go") == "goed"
    options = tricky_options("go", "went gone")
    assert options[0] == "gone went"
    assert "goed goed" in options and "went gone" not in options
    # V2 == V3: swapping is not a mistake, so it is skipped.
    assert "taught taught" not in tricky_options("teach", "taught taught")


def test_validate_forms_rejects_junk() -> None:
    assert validate_forms(" Be ", "was / were", "been") == ("be", "was/were", "been")
    for bad in (("go", "", "gone"), ("go", "went gone", "gone"), ("go", "went1", "gone")):
        with pytest.raises(VerbFormsError):
            validate_forms(*bad)


# Model output


def test_normalize_moves_three_forms_in_one_cell_to_verbs() -> None:
    payload = {
        "words": [
            {"en": "go went gone", "ru": "идти", "topic": "Irregular verbs"},
            {"en": "sing - sang - sung", "ru": "петь", "topic": "Irregular Verbs"},
            {"en": "red apple", "ru": "красное яблоко", "topic": "Food"},
            {"en": "big small fat", "ru": "?", "topic": "Adjectives"},
        ],
        "verbs": [
            {"base": "be", "past": "was / were", "participle": "been", "ru": "быть"},
            {"base": "go", "past": "went", "participle": "gone", "ru": "идти"},
            {"base": "bad", "past": "", "participle": "x", "ru": ""},
        ],
    }
    misplaced: list[dict[str, str]] = []
    words = normalize_words(payload, misplaced)
    verbs = normalize_verbs(payload, misplaced)
    assert [word["en"] for word in words] == ["red apple", "big small fat"]
    assert verbs == [
        {"base": "be", "past": "was/were", "participle": "been", "ru": "быть"},
        {"base": "go", "past": "went", "participle": "gone", "ru": "идти"},
        {"base": "sing", "past": "sang", "participle": "sung", "ru": "петь"},
    ]
    # Without a verbs list the old behaviour stays: nothing is moved.
    assert len(normalize_words(payload)) == 4


# Draft and save


def make_verb_draft(verbs: list[dict[str, str]], items: list[dict[str, object]] | None = None) -> int:
    row = add_source(MOM, text="Lesson 1: go went gone - идти")
    set_id = int(row["id"])
    begin_processing(MOM, set_id, "words")
    store_extraction(set_id, ExtractionResult(model="m", items=items or [], verbs=verbs))
    return set_id


GO = {"base": "go", "past": "went", "participle": "gone", "ru": "идти"}
BE = {"base": "be", "past": "was/were", "participle": "been", "ru": "быть"}


def test_draft_puts_verbs_into_their_own_task_and_save_creates_verb_items(family: int) -> None:
    set_id = make_verb_draft([GO, BE], items=[{"en": "dragon", "ru": "дракон", "topic": "Fairy Tales"}])
    draft = get_draft(MOM, set_id)
    kinds = [task["kind"] for task in draft["tasks"]]
    assert kinds == ["words", "verbs", "note"]
    verbs_task = draft["tasks"][1]
    assert [item["base"] for item in verbs_task["items"]] == ["go", "be"]
    assert verbs_task["items"][0]["topic"] == "Irregular verbs" and verbs_task["items"][0]["existing_id"] is None

    result = save_draft(MOM, set_id, {"tasks": draft["tasks"], "assign_to": KID, "mode": "hard"})
    assert result["word_count"] == 3 and result["created_words"] == 3 and result["assignment_id"]
    saved = get_set(MOM, set_id)
    assert [word["text"] for word in saved["words"]] == ["dragon", "go – went – gone", "be – was/were – been"]
    topics = {topic["title"] for topic in saved["topics"]}
    assert {"Irregular verbs", "Fairy Tales"} <= topics


def test_known_verbs_are_reused_and_a_plain_word_with_the_same_text_stays_separate(family: int) -> None:
    topic = create_topic(MOM, "Travel")
    create_word(MOM, topic["id"], "go", {"ru": "ехать"})
    first = make_verb_draft([GO])
    assert get_draft(MOM, first)["tasks"][0]["items"][0]["existing_id"] is None
    draft = get_draft(MOM, first)
    save_draft(MOM, first, {"tasks": draft["tasks"]})

    second = make_verb_draft([GO])
    draft = get_draft(MOM, second)
    existing_id = draft["tasks"][0]["items"][0]["existing_id"]
    assert existing_id is not None
    result = save_draft(MOM, second, {"tasks": draft["tasks"]})
    assert result["created_words"] == 0
    with db.get_connection() as connection:
        rows = connection.execute("SELECT item_type FROM learning_items WHERE text = 'go' ORDER BY id").fetchall()
    assert [row["item_type"] for row in rows] == ["word", "verb"]


def test_save_rejects_broken_verb_forms(family: int) -> None:
    set_id = make_verb_draft([GO])
    draft = get_draft(MOM, set_id)
    draft["tasks"][0]["items"][0]["past"] = "went gone"
    with pytest.raises(Exception) as caught:
        save_draft(MOM, set_id, {"tasks": draft["tasks"]})
    assert getattr(caught.value, "code", "") == "invalid_verb_forms"


# Training


def make_verb_session(family: int, mode: str, verbs: list[dict[str, str]]) -> None:
    set_id = make_verb_draft(verbs)
    draft = get_draft(MOM, set_id)
    save_draft(MOM, set_id, {"tasks": draft["tasks"]})
    with db.get_connection() as connection:
        ids = [int(row["id"]) for row in connection.execute(
            "SELECT id FROM learning_items WHERE item_type = 'verb' ORDER BY id").fetchall()]
    create_training_session_for_learning_items(KID, ids, training_mode=mode)


def test_easy_verb_question_shows_base_and_offers_mistakes_of_that_verb(family: int) -> None:
    make_verb_session(family, "easy", [GO, BE])
    question = get_current_question(KID)
    assert question["item_type"] == "verb"
    assert question["prompt"] == "go — идти"
    assert question["expected_answer"] == "went gone"
    assert "went gone" in question["options"] and len(question["options"]) == 3
    assert "gone went" in question["options"]
    assert question["speech_text"] == "go, went, gone"
    text = render_question_text(KID, question)
    assert "2" in text.splitlines()[0] and "go — идти" in text
    assert public_question(question)["task"]

    result = submit_training_answer(KID, "went gone")
    assert result["is_correct"]
    question = get_current_question(KID)
    assert question["prompt"] == "be — быть" and question["speech_text"] == "be, was or were, been"


def test_hard_verb_question_accepts_typed_forms_with_any_separator(family: int) -> None:
    make_verb_session(family, "hard", [GO])
    question = get_current_question(KID)
    assert question["exercise_type"] == "typed_answer"
    assert not submit_training_answer(KID, "goed goed")["is_correct"]
    assert submit_training_answer(KID, "Went, gone")["is_correct"]


def test_medium_verb_question_jumbles_both_forms(family: int) -> None:
    make_verb_session(family, "medium", [GO])
    question = get_current_question(KID)
    assert question["exercise_type"] == "jumbled_letters"
    assert sorted(question["jumbled_letters"]) == sorted("wentgone")
    assert question["medium_answer_mask"].count("_") == 8


def test_word_questions_never_offer_verb_answers(family: int) -> None:
    topic = create_topic(MOM, "Animals")
    word_ids = [create_word(MOM, topic["id"], text, {"ru": ru})["id"] for text, ru in (("cat", "кот"), ("dog", "собака"))]
    make_verb_draft([GO])
    set_id = make_verb_draft([BE])
    save_draft(MOM, set_id, {"tasks": get_draft(MOM, set_id)["tasks"]})
    create_training_session_for_learning_items(KID, word_ids, training_mode="easy")
    question = get_current_question(KID)
    assert all(" " not in option for option in question["options"])


# Dictionary editor and learner screens


def test_editor_creates_edits_and_converts_verbs(family: int) -> None:
    topic = create_topic(MOM, "Irregular verbs")
    verb = create_word(MOM, topic["id"], "sing", {"ru": "петь"}, {"past": "sang", "participle": "sung"})
    assert verb["type"] == "verb" and verb["forms"] == {"past": "sang", "participle": "sung"}
    assert verb["translations"]["ru"] == "петь"
    updated = update_word(MOM, verb["id"], translations={"ru": "петь"}, verb={"past": "sang", "participle": "sung/sang"})
    assert updated["forms"]["participle"] == "sung/sang"
    with pytest.raises(MiniAppError):
        update_word(MOM, verb["id"], verb={"past": "", "participle": "sung"})
    plain = update_word(MOM, verb["id"], verb=None)
    assert plain["type"] == "word" and plain["forms"] is None
    kept = update_word(MOM, verb["id"], text="sing")
    assert kept["type"] == "word"
    assert [word["text"] for word in list_words(MOM, topic["id"])["words"]] == ["sing"]
    assert search_words(MOM, "sing", item_type="verb") == []
    assert len(search_words(MOM, "sing", item_type="word")) == 1


def test_item_type_columns_survive_a_restart(family: int) -> None:
    topic = create_topic(MOM, "Irregular verbs")
    verb = create_word(MOM, topic["id"], "go", {}, {"past": "went", "participle": "gone"})
    db.init_db()
    with db.get_connection() as connection:
        row = connection.execute("SELECT item_type, details_json FROM learning_items WHERE id = ?", (verb["id"],)).fetchone()
    assert row["item_type"] == "verb" and "went" in row["details_json"]


def test_homework_screen_shows_one_drill_line_for_words_and_verbs() -> None:
    tasks = [{"kind": "words"}, {"kind": "verbs"}, {"kind": "paper"}]
    assignment = {"tasks": tasks, "words_done": False, "completed_items": 1, "total_items": 4}
    assert "1/4" in _drill_line(KID, assignment)
    only_verbs = {**assignment, "tasks": [{"kind": "verbs"}]}
    assert _drill_line(KID, only_verbs) != _drill_line(KID, assignment)


def test_a_word_saved_as_three_forms_can_be_fixed_into_a_verb(family: int) -> None:
    topic = create_topic(MOM, "Irregular verbs")
    create_word(MOM, topic["id"], "go", {"ru": "ехать"})
    broken = create_word(MOM, topic["id"], "go went gone", {"ru": "идти"})
    fixed = update_word(MOM, broken["id"], text="go", verb={"past": "went", "participle": "gone"})
    assert fixed["text"] == "go" and fixed["type"] == "verb"
    assert [word["text"] for word in list_words(MOM, topic["id"])["words"]] == ["go", "go"]
