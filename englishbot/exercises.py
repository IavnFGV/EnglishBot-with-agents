import random
from dataclasses import dataclass
from typing import Literal, Sequence


ExerciseStage = Literal["easy", "medium", "hard"]
ExerciseType = Literal["multiple_choice", "jumbled_letters", "typed_answer"]


@dataclass(frozen=True, slots=True)
class TranslationEntry:
    language_code: str
    translation_text: str


@dataclass(frozen=True, slots=True)
class ResolvedLearningItem:
    learning_item_id: int
    headword: str
    translations: Sequence[TranslationEntry]
    image_ref: str | None = None


@dataclass(frozen=True, slots=True)
class DistractorLexeme:
    headword: str


@dataclass(frozen=True, slots=True)
class ExercisePromptPayload:
    prompt_text: str
    jumbled_letters: str | None = None


@dataclass(frozen=True, slots=True)
class ExerciseInstance:
    exercise_type: ExerciseType
    stage: ExerciseStage
    learning_item_id: int
    prompt_payload: ExercisePromptPayload
    expected_answer: str
    options: list[str] | None
    hint_text: str | None
    image_ref: str | None
    first_letter: str | None


class ExerciseBuildError(Exception):
    pass


def build_exercise(
    learning_item: ResolvedLearningItem,
    stage: ExerciseStage,
    hint_language: str,
    distractor_pool: Sequence[ResolvedLearningItem | DistractorLexeme],
) -> ExerciseInstance:
    expected_answer = _normalize_required_text(learning_item.headword, "learning item headword")
    prompt_text = _select_hint_text(learning_item.translations, hint_language, expected_answer)

    if stage == "easy":
        return ExerciseInstance(
            exercise_type="multiple_choice",
            stage=stage,
            learning_item_id=learning_item.learning_item_id,
            prompt_payload=ExercisePromptPayload(prompt_text=prompt_text),
            expected_answer=expected_answer,
            options=_build_multiple_choice_options(expected_answer, distractor_pool),
            hint_text=None,
            image_ref=learning_item.image_ref,
            first_letter=None,
        )

    if stage == "medium":
        return ExerciseInstance(
            exercise_type="jumbled_letters",
            stage=stage,
            learning_item_id=learning_item.learning_item_id,
            prompt_payload=ExercisePromptPayload(
                prompt_text=prompt_text,
                jumbled_letters=_build_jumbled_letters(expected_answer),
            ),
            expected_answer=expected_answer,
            options=None,
            hint_text=prompt_text,
            image_ref=learning_item.image_ref,
            first_letter=None,
        )

    return ExerciseInstance(
        exercise_type="typed_answer",
        stage=stage,
        learning_item_id=learning_item.learning_item_id,
        prompt_payload=ExercisePromptPayload(prompt_text=prompt_text),
        expected_answer=expected_answer,
        options=None,
        hint_text=prompt_text,
        image_ref=learning_item.image_ref,
        first_letter=expected_answer[:1],
    )


def _select_hint_text(
    translations: Sequence[TranslationEntry],
    hint_language: str,
    fallback_headword: str,
) -> str:
    translations_by_language = {
        translation.language_code.strip(): translation.translation_text.strip()
        for translation in translations
        if translation.language_code.strip() and translation.translation_text.strip()
    }
    for language_code in (hint_language.strip(), "ru", "uk"):
        if not language_code:
            continue
        prompt = translations_by_language.get(language_code)
        if prompt:
            return prompt
    first_available = next(iter(translations_by_language.values()), "")
    if first_available:
        return first_available
    fallback = fallback_headword.strip()
    if fallback:
        return fallback
    raise ExerciseBuildError("Unable to build hint text for learning item.")


def _build_multiple_choice_options(
    expected_answer: str,
    distractor_pool: Sequence[ResolvedLearningItem | DistractorLexeme],
) -> list[str]:
    distractor_headwords: list[str] = []
    seen: set[str] = set()
    normalized_expected = expected_answer.casefold()
    for distractor in distractor_pool:
        headword = _extract_headword(distractor).strip()
        normalized_headword = headword.casefold()
        if not headword or normalized_headword == normalized_expected or normalized_headword in seen:
            continue
        seen.add(normalized_headword)
        distractor_headwords.append(headword)
    if len(distractor_headwords) < 2:
        raise ExerciseBuildError("At least 2 distractors are required to build an easy exercise.")

    selected_distractors = random.sample(distractor_headwords, 2)
    options = [expected_answer, *selected_distractors]
    random.shuffle(options)
    return options


def _build_jumbled_letters(expected_answer: str) -> str:
    letters = list(expected_answer)
    if len(letters) < 2:
        return expected_answer

    original_letters = letters[:]
    for _ in range(8):
        random.shuffle(letters)
        if letters != original_letters:
            return "".join(letters)
    return "".join(letters)


def _extract_headword(distractor: ResolvedLearningItem | DistractorLexeme) -> str:
    return distractor.headword


def _normalize_required_text(value: str, field_name: str) -> str:
    normalized_value = value.strip()
    if not normalized_value:
        raise ExerciseBuildError(f"{field_name} must not be empty.")
    return normalized_value
