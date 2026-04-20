import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot.exercises import (
    DistractorLexeme,
    ExerciseBuildError,
    ExercisePromptPayload,
    ResolvedLearningItem,
    TranslationEntry,
    build_exercise,
)


def make_learning_item(
    learning_item_id: int = 1,
    headword: str = "apple",
    translations: list[TranslationEntry] | None = None,
    image_ref: str | None = "https://example.com/apple.png",
) -> ResolvedLearningItem:
    stored_translations = translations or [
        TranslationEntry(language_code="ru", translation_text="яблоко"),
        TranslationEntry(language_code="uk", translation_text="яблуко"),
    ]
    return ResolvedLearningItem(
        learning_item_id=learning_item_id,
        headword=headword,
        translations=stored_translations,
        image_ref=image_ref,
    )


def test_build_easy_exercise_returns_three_shuffled_options() -> None:
    random.seed(1)
    learning_item = make_learning_item()
    distractors = [
        DistractorLexeme(headword="pear"),
        DistractorLexeme(headword="plum"),
        DistractorLexeme(headword="grape"),
    ]

    exercise = build_exercise(learning_item, "easy", "ru", distractors)

    assert exercise.exercise_type == "multiple_choice"
    assert exercise.stage == "easy"
    assert exercise.expected_answer == "apple"
    assert exercise.hint_text is None
    assert exercise.options is not None
    assert len(exercise.options) == 3
    assert set(exercise.options) == {"apple", "pear", "plum"} or set(exercise.options) == {
        "apple",
        "pear",
        "grape",
    } or set(exercise.options) == {"apple", "plum", "grape"}
    assert "apple" in exercise.options


def test_build_easy_exercise_raises_when_not_enough_distractors() -> None:
    learning_item = make_learning_item()

    try:
        build_exercise(
            learning_item,
            "easy",
            "ru",
            [DistractorLexeme(headword="apple"), DistractorLexeme(headword="")],
        )
    except ExerciseBuildError as error:
        assert "At least 2 distractors" in str(error)
    else:
        raise AssertionError("Expected ExerciseBuildError for insufficient distractors")


def test_build_medium_exercise_returns_jumbled_letters_and_localized_hint() -> None:
    random.seed(2)
    learning_item = make_learning_item(headword="planet")

    exercise = build_exercise(learning_item, "medium", "ru", [])

    assert exercise.exercise_type == "jumbled_letters"
    assert exercise.hint_text == "яблоко"
    assert exercise.image_ref == "https://example.com/apple.png"
    assert exercise.options is None
    assert exercise.prompt_payload.jumbled_letters is not None
    assert exercise.prompt_payload.jumbled_letters != "planet"
    assert sorted(exercise.prompt_payload.jumbled_letters) == sorted("planet")


def test_build_hard_exercise_returns_first_letter_and_localized_hint() -> None:
    learning_item = make_learning_item(headword="banana")

    exercise = build_exercise(learning_item, "hard", "uk", [])

    assert exercise.exercise_type == "typed_answer"
    assert exercise.hint_text == "яблуко"
    assert exercise.first_letter == "b"
    assert exercise.options is None
    assert exercise.prompt_payload == ExercisePromptPayload(prompt_text="яблуко")


def test_build_exercise_hint_falls_back_when_requested_language_is_missing() -> None:
    learning_item = make_learning_item(
        translations=[TranslationEntry(language_code="bg", translation_text="ябълка")]
    )

    exercise = build_exercise(learning_item, "hard", "fr", [])

    assert exercise.hint_text == "ябълка"


def test_build_exercise_returns_consistent_structure_across_stages() -> None:
    random.seed(3)
    learning_item = make_learning_item()
    distractors = [DistractorLexeme(headword="pear"), DistractorLexeme(headword="plum")]

    easy = build_exercise(learning_item, "easy", "ru", distractors)
    medium = build_exercise(learning_item, "medium", "ru", distractors)
    hard = build_exercise(learning_item, "hard", "ru", distractors)

    for exercise in (easy, medium, hard):
        assert exercise.learning_item_id == 1
        assert exercise.expected_answer == "apple"
        assert isinstance(exercise.prompt_payload, ExercisePromptPayload)
        assert exercise.image_ref == "https://example.com/apple.png"

    assert easy.options is not None
    assert easy.first_letter is None
    assert medium.prompt_payload.jumbled_letters is not None
    assert medium.hint_text == "яблоко"
    assert hard.first_letter == "a"
    assert hard.hint_text == "яблоко"
