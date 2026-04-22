import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot.command_registry import (
    ALL_COMMANDS,
    ASSIGN_COMMAND,
    BOT_COMMANDS,
    CANCEL_COMMAND,
    CREATE_ASSIGNMENT_COMMAND,
    GRANTTOPIC_COMMAND,
    JOIN_COMMAND,
    LEARN_COMMAND,
    ME_COMMAND,
    SETTINGS_COMMAND,
    START_COMMAND,
    TEACHER_CONTENT_COMMAND,
    WORKBOOK_EXPORT_COMMAND,
    WORKBOOK_IMPORT_COMMAND,
    build_bot_commands,
    get_registered_commands,
)
from englishbot.i18n import translate
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
        "settings",
        "cancel",
        "invite",
        "join",
        "assign",
        "create_assignment",
        "granttopic",
        "topics",
        "workbook_export",
        "workbook_import",
        "teacher_content",
    ]
    assert len({command.name for command in ALL_COMMANDS}) == len(ALL_COMMANDS)


def test_bot_command_collection_stays_consistent_with_registry() -> None:
    registered = get_registered_commands()

    assert registered == ALL_COMMANDS
    assert BOT_COMMANDS == build_bot_commands()
    assert [command.command for command in BOT_COMMANDS] == [command.name for command in ALL_COMMANDS]


def test_usage_messages_and_caption_parsing_use_canonical_command_names() -> None:
    assert _build_assign_usage_message(1) == (
        f"Usage: {ASSIGN_COMMAND.token} <student_user_id> <teacher_workspace_id> <topic_name>\n"
        f"Or: {ASSIGN_COMMAND.token} <student_user_id> <learning_item_id,learning_item_id,...>"
    )
    assert _build_grant_topic_usage_message(1) == (
        f"Usage: {GRANTTOPIC_COMMAND.token} <student_user_id> <teacher_workspace_id> <topic_name>"
    )
    assert _build_export_usage_message(1) == (
        f"Usage: {WORKBOOK_EXPORT_COMMAND.token} <teacher_workspace_id>"
    )
    assert _build_import_usage_message(1) == (
        "Usage: send a .xlsx file with caption "
        f"{WORKBOOK_IMPORT_COMMAND.token} <teacher_workspace_id>"
    )
    assert _extract_import_workspace_id(f"{WORKBOOK_IMPORT_COMMAND.token} 42") == 42
    assert _extract_import_workspace_id(f"{JOIN_COMMAND.token} 42") is None


def test_bot_commands_use_centralized_i18n_descriptions() -> None:
    assert BOT_COMMANDS[0].description == translate("command.start", "en")
    assert CREATE_ASSIGNMENT_COMMAND.to_bot_command("en").description == translate(
        "command.create_assignment",
        "en",
    )
    assert TEACHER_CONTENT_COMMAND.to_bot_command("en").description == translate(
        "command.teacher_content",
        "en",
    )
