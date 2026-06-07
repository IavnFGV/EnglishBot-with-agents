import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from aiogram.types import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot import db
from englishbot.bulk_edit import get_active_bulk_edit_session
from englishbot.bulk_edit_handlers import handle_bulk_edit_callback, start_bulk_edit, upload_bulk_edit_workbook
from englishbot.families import create_family, create_family_learning_item
from englishbot.user_profiles import set_user_language
from englishbot.vocabulary import create_learning_item_translation, create_lexeme, list_learning_items
from englishbot.workbook_import import WorkbookImportProgress, WorkbookImportRow


class FakeBot:
    def __init__(self, payload: bytes = b"") -> None:
        self.payload = payload
        self.edits: list[dict[str, object]] = []

    async def download(self, file: object, destination) -> object:
        destination.write(self.payload)
        destination.seek(0)
        return destination

    async def edit_message_text(
        self,
        *,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup=None,
    ) -> None:
        self.edits.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "reply_markup": reply_markup,
            }
        )


class FakeMessage:
    def __init__(self, user: User, *, bot: FakeBot | None = None, document=None) -> None:
        self.from_user = user
        self.bot = bot or FakeBot()
        self.document = document
        self.chat = SimpleNamespace(id=user.id)
        self.answers: list[dict[str, object]] = []
        self.documents: list[dict[str, object]] = []

    async def answer(self, text: str, **kwargs: object):
        self.answers.append({"text": text, "kwargs": kwargs})
        return SimpleNamespace(chat=self.chat, message_id=len(self.answers))

    async def answer_document(self, document, **kwargs: object) -> None:
        self.documents.append({"document": document, "kwargs": kwargs})


class FakeCallback:
    def __init__(self, user: User, data: str, message: FakeMessage) -> None:
        self.from_user = user
        self.data = data
        self.message = message
        self.answers: list[dict[str, object]] = []

    async def answer(self, text: str | None = None, show_alert: bool = False) -> None:
        self.answers.append({"text": text, "show_alert": show_alert})


def make_user(user_id: int, first_name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=first_name.lower())


def setup_db(tmp_path: Path, monkeypatch) -> User:
    db.DB_PATH = tmp_path / "bulk_edit_handlers.sqlite3"
    monkeypatch.setenv("ENGLISHBOT_BACKUP_DIR", str(tmp_path / "backups"))
    db.init_db()
    owner = make_user(1501, "Owner")
    db.save_user(owner)
    family = create_family("Home", owner.id)
    item_id = create_family_learning_item(int(family["id"]), create_lexeme("apple"), "apple")
    create_learning_item_translation(item_id, "ru", "яблоко")
    return owner


def test_upload_then_apply_flow_works_through_handler_layer(tmp_path: Path, monkeypatch) -> None:
    owner = setup_db(tmp_path, monkeypatch)
    start_message = FakeMessage(owner)

    asyncio.run(start_bulk_edit(start_message))

    assert len(start_message.documents) == 1
    session = get_active_bulk_edit_session()
    assert session is not None
    assert Path(str(session["export_file_path"])).parent == tmp_path / "bulk-edit" / "exports"

    export_file = Path(str(session["export_file_path"]))
    upload_message = FakeMessage(
        owner,
        bot=FakeBot(export_file.read_bytes()),
        document=SimpleNamespace(file_name="family.xlsx"),
    )
    asyncio.run(upload_bulk_edit_workbook(upload_message))

    session = get_active_bulk_edit_session()
    assert session is not None
    assert session["status"] == "uploaded"

    callback_message = FakeMessage(owner)
    callback = FakeCallback(owner, "bulk_edit:apply", callback_message)
    asyncio.run(handle_bulk_edit_callback(callback))

    assert callback_message.bot.edits[-1]["text"].startswith("Bulk edit completed.")
    assert get_active_bulk_edit_session() is None
    assert [item["text"] for item in list_learning_items(family_id=1)] == ["apple"]


def test_control_message_is_reused_instead_of_spamming_new_messages(tmp_path: Path, monkeypatch) -> None:
    owner = setup_db(tmp_path, monkeypatch)
    bot = FakeBot()
    start_message = FakeMessage(owner, bot=bot)

    asyncio.run(start_bulk_edit(start_message))

    session = get_active_bulk_edit_session()
    assert session is not None
    export_file = Path(str(session["export_file_path"]))
    upload_message = FakeMessage(
        owner,
        bot=bot,
        document=SimpleNamespace(file_name="family.xlsx"),
    )
    upload_message.bot.payload = export_file.read_bytes()

    asyncio.run(upload_bulk_edit_workbook(upload_message))

    assert len(start_message.answers) == 2
    assert bot.edits[-1]["text"] == "Workbook file received. Review it if needed, then apply it or cancel the session."


def test_bulk_edit_start_and_active_session_messages_follow_user_language(tmp_path: Path, monkeypatch) -> None:
    owner = setup_db(tmp_path, monkeypatch)
    set_user_language(owner.id, "ru")
    start_message = FakeMessage(owner)

    asyncio.run(start_bulk_edit(start_message))

    assert start_message.answers[0]["text"].startswith("Сессия bulk edit для вашей семьи начата.")
    assert start_message.documents[0]["kwargs"]["caption"].startswith("Workbook экспортирован.")
    assert start_message.answers[1]["text"].startswith("Отредактируйте workbook и отправьте обновлённый .xlsx сюда.")

    followup_message = FakeMessage(owner)
    asyncio.run(start_bulk_edit(followup_message))

    assert followup_message.answers[0]["text"].startswith("Ваша сессия bulk edit всё ещё активна.")


def test_apply_shows_progress_status_before_completion(tmp_path: Path, monkeypatch) -> None:
    owner = setup_db(tmp_path, monkeypatch)
    start_message = FakeMessage(owner)

    asyncio.run(start_bulk_edit(start_message))

    session = get_active_bulk_edit_session()
    assert session is not None
    export_file = Path(str(session["export_file_path"]))
    upload_message = FakeMessage(
        owner,
        bot=FakeBot(export_file.read_bytes()),
        document=SimpleNamespace(file_name="family.xlsx"),
    )
    asyncio.run(upload_bulk_edit_workbook(upload_message))

    validated_rows = [
        WorkbookImportRow(
            row_number=2,
            item_key="item-1",
            text="apple",
            translations={"ru": "яблоко"},
            topic_titles=[],
            image_ref="",
            audio_ref="",
            is_archived=False,
        )
    ]

    def fake_validate(*args, **kwargs):
        return validated_rows

    def fake_backup(*args, **kwargs):
        backup_path = tmp_path / "backups" / "fake.sqlite3"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_bytes(b"backup")
        return backup_path

    def fake_prepare(*args, **kwargs):
        time.sleep(1.1)
        progress_callback = args[-1]
        progress_callback(
            WorkbookImportProgress(
                phase="preparing",
                processed_rows=1,
                total_rows=1,
                current_item_text="apple",
            )
        )
        return SimpleNamespace(rows=[], staged_asset_paths=())

    def fake_apply(*args, **kwargs):
        time.sleep(1.1)
        progress_callback = args[-1]
        progress_callback(
            WorkbookImportProgress(
                phase="applying",
                processed_rows=1,
                total_rows=1,
                current_item_text="apple",
            )
        )
        return SimpleNamespace(
            created=0,
            updated=0,
            archived=0,
            unchanged=1,
            backup_file_path=tmp_path / "backups" / "fake.sqlite3",
        )

    monkeypatch.setattr("englishbot.bulk_edit_handlers.validate_family_workbook_import", fake_validate)
    monkeypatch.setattr("englishbot.bulk_edit_handlers.create_bulk_edit_backup", fake_backup)
    monkeypatch.setattr("englishbot.bulk_edit_handlers.prepare_family_workbook_import", fake_prepare)
    monkeypatch.setattr("englishbot.bulk_edit_handlers.apply_prepared_family_workbook_import", fake_apply)

    callback_message = FakeMessage(owner)
    callback = FakeCallback(owner, "bulk_edit:apply", callback_message)
    asyncio.run(handle_bulk_edit_callback(callback))

    assert callback.answers == [{"text": None, "show_alert": False}]
    assert any(
        "Creating safety backup" in edit["text"]
        or "Preparing assets" in edit["text"]
        or "Applying database changes" in edit["text"]
        for edit in callback_message.bot.edits
    )
    assert callback_message.bot.edits[-1]["text"].startswith("Bulk edit completed.")
