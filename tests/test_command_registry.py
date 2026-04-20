import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot.command_registry import (
    ALL_COMMANDS,
    ASSIGN_COMMAND,
    BOT_COMMANDS,
    GRANTTOPIC_COMMAND,
    JOIN_COMMAND,
    LEARN_COMMAND,
    ME_COMMAND,
    START_COMMAND,
    WORKBOOK_EXPORT_COMMAND,
    WORKBOOK_IMPORT_COMMAND,
    build_bot_commands,
    get_registered_commands,
)
from englishbot.teacher_handlers import (
    _build_assign_usage_message,
    _build_grant_topic_usage_message,
)
from englishbot.workbook_handlers import (
    _build_export_usage_message,
    _build_import_usage_message,
    _extract_import_workspace_id,
)


def test_command_registry_contains_all_canonical_commands() -> None:
    assert [command.name for command in ALL_COMMANDS] == [
        "start",
        "learn",
        "me",
        "invite",
        "join",
        "assign",
        "granttopic",
        "topics",
        "workbook_export",
        "workbook_import",
    ]
    assert len({command.name for command in ALL_COMMANDS}) == len(ALL_COMMANDS)


def test_bot_command_collection_respects_registration_flag() -> None:
    registered = get_registered_commands()

    assert [command.name for command in registered] == [
        START_COMMAND.name,
        LEARN_COMMAND.name,
        ME_COMMAND.name,
    ]
    assert BOT_COMMANDS == build_bot_commands()
    assert [command.command for command in BOT_COMMANDS] == [
        START_COMMAND.name,
        LEARN_COMMAND.name,
        ME_COMMAND.name,
    ]


def test_usage_messages_and_caption_parsing_use_canonical_command_names() -> None:
    assert _build_assign_usage_message() == (
        f"Использование: {ASSIGN_COMMAND.token} "
        "<student_user_id> <teacher_workspace_id> <topic_name>\n"
        f"Или: {ASSIGN_COMMAND.token} "
        "<student_user_id> <learning_item_id,learning_item_id,...>"
    )
    assert _build_grant_topic_usage_message() == (
        f"Использование: {GRANTTOPIC_COMMAND.token} "
        "<student_user_id> <teacher_workspace_id> <topic_name>"
    )
    assert _build_export_usage_message() == (
        f"Использование: {WORKBOOK_EXPORT_COMMAND.token} <teacher_workspace_id>"
    )
    assert _build_import_usage_message() == (
        "Использование: отправьте .xlsx файлом с подписью "
        f"{WORKBOOK_IMPORT_COMMAND.token} <teacher_workspace_id>"
    )
    assert _extract_import_workspace_id(f"{WORKBOOK_IMPORT_COMMAND.token} 42") == 42
    assert _extract_import_workspace_id(f"{JOIN_COMMAND.token} 42") is None
