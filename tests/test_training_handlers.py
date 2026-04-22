import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.homework import create_assignment, start_assignment_training_session
from englishbot.teacher_student import create_invite, join_with_invite
from englishbot.training import get_active_training_session, get_current_question, submit_training_answer
from englishbot.training_handlers import (
    TRAINING_EASY_CALLBACK_PREFIX,
    TRAINING_HARD_SKIP_CALLBACK,
    TRAINING_MEDIUM_ADD_CALLBACK_PREFIX,
    TRAINING_MEDIUM_BACKSPACE_CALLBACK,
    TRAINING_MEDIUM_CHECK_CALLBACK,
    answer_training_easy,
    answer_training_hard_skip,
    answer_training_medium_add,
    answer_training_medium_backspace,
    answer_training_medium_check,
    answer_training_question,
    learn,
    render_started_training_session,
)
from englishbot.user_profiles import set_user_hint_language
from englishbot.user_profiles import set_user_role
from englishbot.vocabulary import create_learning_item, create_learning_item_translation, create_lexeme
from englishbot.workspaces import add_workspace_member


class FakeBot:
    def __init__(self) -> None:
        self.edited_messages: list[dict[str, object]] = []
        self.deleted_messages: list[dict[str, object]] = []
        self.fail_delete = False

    async def edit_message_text(
        self,
        *,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup=None,
    ) -> None:
        self.edited_messages.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "reply_markup": reply_markup,
            }
        )

    async def delete_message(self, *, chat_id: int, message_id: int) -> None:
        self.deleted_messages.append({"chat_id": chat_id, "message_id": message_id})
        if self.fail_delete:
            raise RuntimeError("delete failed")


class FakeMessage:
    def __init__(self, user: User, text: str | None = None, bot: FakeBot | None = None) -> None:
        self.from_user = user
        self.text = text
        self.bot = bot or FakeBot()
        self.chat = SimpleNamespace(id=user.id)
        self.answers: list[dict[str, object]] = []
        self._next_message_id = 1
        self.message_id = 0

    async def answer(self, text: str, **kwargs: object) -> SimpleNamespace:
        message = SimpleNamespace(message_id=self._next_message_id)
        self._next_message_id += 1
        self.answers.append({"text": text, "kwargs": kwargs, "message_id": message.message_id})
        return message


class FakeCallback:
    def __init__(self, user: User, data: str, message: FakeMessage) -> None:
        self.from_user = user
        self.data = data
        self.message = message
        self.answered = False

    async def answer(self) -> None:
        self.answered = True


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "training_handlers.sqlite3"
    db.init_db()


def seed_learning_items(item_count: int) -> None:
    teacher = make_user(499, "Teacher")
    db.save_user(teacher)
    add_workspace_member(db.get_default_content_workspace_id(), teacher.id, "teacher")
    for index in range(item_count):
        lexeme_id = create_lexeme(f"word-{index + 1}")
        learning_item_id = create_learning_item(lexeme_id, f"text-{index + 1}")
        create_learning_item_translation(learning_item_id, "ru", f"слово-{index + 1}")


def seed_linked_teacher_and_student() -> tuple[User, User]:
    teacher = make_user(498, "Teacher")
    student = make_user(497, "Student")
    db.save_user(teacher)
    db.save_user(student)
    set_user_role(teacher.id, "teacher")
    invite_code = create_invite(teacher.id)
    join_with_invite(student.id, invite_code)
    return teacher, student


def _find_keyboard_index_by_label(keyboard, label: str) -> int:
    for index, row in enumerate(keyboard.inline_keyboard):
        if row[0].text == label:
            return index
    raise AssertionError(f"Option {label!r} not found")


def test_learn_renders_one_progress_message_and_one_easy_question(tmp_path: Path) -> None:
    setup_db(tmp_path)
    seed_learning_items(3)
    user = make_user(401, "Learner")
    message = FakeMessage(user)

    asyncio.run(learn(message))

    assert [answer["text"] for answer in message.answers] == [
        "Item 1/3\nDone 0/3\nStage: easy",
        "слово-1",
    ]
    keyboard = message.answers[1]["kwargs"]["reply_markup"]
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 3
    assert sum(len(row) for row in keyboard.inline_keyboard) == 3
    session = get_active_training_session(user.id)
    assert session is not None
    assert session["progress_message_id"] == 1
    assert session["current_question_message_id"] == 2


def test_easy_callback_delegates_selected_option_to_training_logic(tmp_path: Path, monkeypatch) -> None:
    setup_db(tmp_path)
    user = make_user(402, "Learner")
    message = FakeMessage(user)
    callback = FakeCallback(user, f"{TRAINING_EASY_CALLBACK_PREFIX}1", message)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "englishbot.training_handlers.get_current_question",
        lambda user_id: {
            "session_id": 7,
            "prompt": "слово",
            "options": ["alpha", "beta", "gamma"],
        },
    )
    monkeypatch.setattr(
        "englishbot.training_handlers.get_active_training_session",
        lambda user_id: {
            "id": 7,
            "progress_message_id": None,
            "current_question_message_id": None,
        },
    )

    def fake_submit_training_answer(user_id: int, answer_text: str) -> dict[str, object]:
        captured["user_id"] = user_id
        captured["answer_text"] = answer_text
        return {
            "is_correct": True,
            "expected_answer": "beta",
            "status": "completed",
            "summary": {"total_questions": 1, "correct_answers": 1},
            "total_questions": 1,
        }

    monkeypatch.setattr(
        "englishbot.training_handlers.submit_training_answer",
        fake_submit_training_answer,
    )
    monkeypatch.setattr(
        "englishbot.training_handlers.set_training_session_progress_message_id",
        lambda session_id, message_id: None,
    )
    monkeypatch.setattr(
        "englishbot.training_handlers.set_training_session_current_question_message_id",
        lambda session_id, message_id: None,
    )

    asyncio.run(answer_training_easy(callback))

    assert callback.answered is True
    assert captured == {"user_id": user.id, "answer_text": "beta"}


def test_easy_callback_reuses_progress_message_and_replaces_question_message(tmp_path: Path) -> None:
    setup_db(tmp_path)
    seed_learning_items(3)
    user = make_user(403, "Learner")
    message = FakeMessage(user)

    asyncio.run(learn(message))

    keyboard = message.answers[1]["kwargs"]["reply_markup"]
    correct_index = _find_keyboard_index_by_label(keyboard, "word-1")
    callback = FakeCallback(user, f"{TRAINING_EASY_CALLBACK_PREFIX}{correct_index}", message)

    asyncio.run(answer_training_easy(callback))

    session = get_active_training_session(user.id)
    assert session is not None
    assert session["progress_message_id"] == 1
    assert session["current_question_message_id"] == 3
    assert message.bot.edited_messages == [
        {
            "chat_id": user.id,
            "message_id": 1,
            "text": "Item 2/3\nDone 0/3\nStage: easy",
            "reply_markup": None,
        }
    ]
    assert message.bot.deleted_messages == [{"chat_id": user.id, "message_id": 2}]
    assert message.answers[-1]["message_id"] == 3


def test_question_deletion_failures_are_tolerated_safely(tmp_path: Path) -> None:
    setup_db(tmp_path)
    seed_learning_items(3)
    user = make_user(404, "Learner")
    message = FakeMessage(user)

    asyncio.run(learn(message))
    message.bot.fail_delete = True

    keyboard = message.answers[1]["kwargs"]["reply_markup"]
    correct_index = _find_keyboard_index_by_label(keyboard, "word-1")
    callback = FakeCallback(user, f"{TRAINING_EASY_CALLBACK_PREFIX}{correct_index}", message)

    asyncio.run(answer_training_easy(callback))

    session = get_active_training_session(user.id)
    assert session is not None
    assert session["current_question_message_id"] == 3
    assert message.answers[-1]["message_id"] == 3


def test_text_answers_are_ignored_for_medium_stage(tmp_path: Path) -> None:
    setup_db(tmp_path)
    seed_learning_items(1)
    user = make_user(405, "Learner")
    message = FakeMessage(user)

    asyncio.run(learn(message))
    submit_training_answer(user.id, "word-1")
    submit_training_answer(user.id, "word-1")

    medium_answer = FakeMessage(user, text="word-1", bot=message.bot)
    medium_answer._next_message_id = message._next_message_id
    asyncio.run(answer_training_question(medium_answer))

    assert medium_answer.answers == []


def test_medium_callbacks_assemble_and_remove_letters(tmp_path: Path) -> None:
    setup_db(tmp_path)
    seed_learning_items(1)
    user = make_user(409, "Learner")
    message = FakeMessage(user)

    asyncio.run(learn(message))
    submit_training_answer(user.id, "word-1")
    submit_training_answer(user.id, "word-1")
    asyncio.run(render_started_training_session(message, user.id))

    session = get_active_training_session(user.id)
    assert session is not None
    message.message_id = int(session["current_question_message_id"])
    question = get_current_question(user.id)
    assert question is not None
    first_letter_index = 0
    callback = FakeCallback(user, f"{TRAINING_MEDIUM_ADD_CALLBACK_PREFIX}{first_letter_index}", message)

    asyncio.run(answer_training_medium_add(callback))

    assert callback.answered is True
    assert "Answer: " in message.bot.edited_messages[-1]["text"]
    asyncio.run(answer_training_medium_backspace(FakeCallback(user, TRAINING_MEDIUM_BACKSPACE_CALLBACK, message)))
    assert "_ _ _ _ _ _" in message.bot.edited_messages[-1]["text"]


def test_medium_check_uses_assembled_answer_and_advances(tmp_path: Path) -> None:
    setup_db(tmp_path)
    seed_learning_items(1)
    user = make_user(410, "Learner")
    message = FakeMessage(user)

    asyncio.run(learn(message))
    submit_training_answer(user.id, "word-1")
    submit_training_answer(user.id, "word-1")
    asyncio.run(render_started_training_session(message, user.id))
    session = get_active_training_session(user.id)
    assert session is not None
    message.message_id = int(session["current_question_message_id"])
    question = get_current_question(user.id)
    assert question is not None
    remaining_indexes = list(enumerate(str(question["jumbled_letters"])))
    for character in str(question["expected_answer"]):
        for position, candidate in remaining_indexes:
            if candidate == character:
                asyncio.run(
                    answer_training_medium_add(
                        FakeCallback(user, f"{TRAINING_MEDIUM_ADD_CALLBACK_PREFIX}{position}", message)
                    )
                )
                remaining_indexes.remove((position, candidate))
                break

    asyncio.run(answer_training_medium_check(FakeCallback(user, TRAINING_MEDIUM_CHECK_CALLBACK, message)))

    updated_question = get_current_question(user.id)
    assert updated_question is not None
    assert updated_question["current_stage"] == "medium"
    assert updated_question["medium_correct_count"] == 1


def test_text_answers_render_hint_and_first_letter_for_hard_stage(tmp_path: Path) -> None:
    setup_db(tmp_path)
    seed_learning_items(1)
    user = make_user(406, "Learner")
    start_message = FakeMessage(user)

    asyncio.run(learn(start_message))

    assert "Hint: слово-1" in start_message.answers[-1]["text"]
    assert "First letter: w" in start_message.answers[-1]["text"]


def test_session_completion_sends_summary_and_stops_question_rendering(tmp_path: Path) -> None:
    setup_db(tmp_path)
    seed_learning_items(1)
    user = make_user(408, "Learner")
    start_message = FakeMessage(user)

    asyncio.run(learn(start_message))

    submit_training_answer(user.id, "word-1")
    submit_training_answer(user.id, "word-1")
    submit_training_answer(user.id, "word-1")
    submit_training_answer(user.id, "word-1")
    session = get_active_training_session(user.id)
    assert session is not None
    start_message.message_id = int(session["current_question_message_id"])
    callback = FakeCallback(user, TRAINING_HARD_SKIP_CALLBACK, start_message)

    asyncio.run(answer_training_hard_skip(callback))

    assert get_active_training_session(user.id) is None
    assert len(start_message.answers) == 3
    assert start_message.answers[-1]["text"] == "Hard skipped.\nResult: 1 questions, 4 correct answers."
    assert start_message.bot.edited_messages[-1]["text"] == "Item 1/1\nDone 1/1\nStage: completed"


def test_learn_renders_hint_prompt_from_persisted_hint_language(tmp_path: Path) -> None:
    setup_db(tmp_path)
    seed_learning_items(3)
    user = make_user(407, "Learner")
    db.save_user(user)
    set_user_hint_language(user.id, "bg")
    create_learning_item_translation(1, "bg", "дума-1")
    message = FakeMessage(user)

    asyncio.run(learn(message))

    assert message.answers[1]["text"] == "дума-1"


def test_homework_completion_uses_homework_specific_summary(tmp_path: Path) -> None:
    setup_db(tmp_path)
    teacher, student = seed_linked_teacher_and_student()
    add_workspace_member(db.get_default_content_workspace_id(), teacher.id, "teacher")
    lexeme_id = create_lexeme("homework-word")
    learning_item_id = create_learning_item(lexeme_id, "homework-word")
    create_learning_item_translation(learning_item_id, "ru", "домашка")
    assignment = create_assignment(teacher.id, student.id, [learning_item_id], title="Homework set")
    start_assignment_training_session(student.id, int(assignment["assignment_id"]))
    start_message = FakeMessage(student)
    asyncio.run(render_started_training_session(start_message, student.id))

    submit_training_answer(student.id, "homework-word")
    submit_training_answer(student.id, "homework-word")
    submit_training_answer(student.id, "homework-word")
    submit_training_answer(student.id, "homework-word")
    session = get_active_training_session(student.id)
    assert session is not None
    start_message.message_id = int(session["current_question_message_id"])
    asyncio.run(answer_training_hard_skip(FakeCallback(student, TRAINING_HARD_SKIP_CALLBACK, start_message)))

    assert start_message.answers[-1]["text"] == (
        'Hard skipped.\nHomework "Homework set" completed.\nResult: 1 questions, 4 correct answers.'
    )
