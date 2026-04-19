import asyncio
import sys
from pathlib import Path

from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.training_handlers import answer_training_question, learn
from englishbot.vocabulary import create_learning_item, create_learning_item_translation, create_lexeme


class FakeMessage:
    def __init__(self, user: User, text: str | None = None) -> None:
        self.from_user = user
        self.text = text
        self.answers: list[str] = []

    async def answer(self, text: str, **_: object) -> None:
        self.answers.append(text)


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "training_handlers.sqlite3"
    db.init_db()


def seed_learning_item() -> None:
    lexeme_id = create_lexeme("apple")
    learning_item_id = create_learning_item(lexeme_id, "apple")
    create_learning_item_translation(learning_item_id, "ru", "яблоко")


def test_learn_handler_starts_session_and_sends_first_question(tmp_path: Path) -> None:
    setup_db(tmp_path)
    seed_learning_item()
    message = FakeMessage(make_user(401, "Learner"))

    asyncio.run(learn(message))

    assert message.answers == ["Тренировка началась.\nВопрос 1/1: яблоко"]


def test_learn_handler_handles_empty_vocabulary(tmp_path: Path) -> None:
    setup_db(tmp_path)
    message = FakeMessage(make_user(402, "Learner"))

    asyncio.run(learn(message))

    assert message.answers == ["Нет слов для тренировки."]


def test_answer_training_question_sends_feedback_and_summary(tmp_path: Path) -> None:
    setup_db(tmp_path)
    seed_learning_item()
    user = make_user(403, "Learner")

    asyncio.run(learn(FakeMessage(user)))

    answer_message = FakeMessage(user, text="APPLE")
    asyncio.run(answer_training_question(answer_message))

    assert answer_message.answers == [
        "Верно.\nИтог: 1 вопросов, 1 правильных ответов."
    ]
