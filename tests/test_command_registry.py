import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from englishbot.command_registry import (
    ALL_COMMANDS,
    ADD_FAMILY_COMMAND,
    BOT_COMMANDS,
    BULK_EDIT_COMMAND,
    CANCEL_COMMAND,
    CREATE_ASSIGNMENT_COMMAND,
    HELP_COMMAND,
    HOMEWORK_COMMAND,
    LEARN_COMMAND,
    ME_COMMAND,
    SEED_DEMO_COMMAND,
    SETTINGS_COMMAND,
    START_COMMAND,
    TEACHER_CONTENT_COMMAND,
    TOPICS_COMMAND,
    build_bot_commands,
    get_registered_commands,
)
from englishbot.i18n import translate


def test_command_registry_contains_all_canonical_commands() -> None:
    assert [command.name for command in ALL_COMMANDS] == [
        "start",
        "help",
        "learn",
        "homework",
        "me",
        "settings",
        "cancel",
        "create_assignment",
        "seed_demo",
        "add_family",
        "topics",
        "teacher_content",
        "bulk_edit",
    ]
    assert len({command.name for command in ALL_COMMANDS}) == len(ALL_COMMANDS)


def test_bot_command_collection_stays_consistent_with_registry() -> None:
    registered = get_registered_commands()
    owner_registered = get_registered_commands(include_owner_commands=True)

    assert registered == (
        START_COMMAND,
        HELP_COMMAND,
        LEARN_COMMAND,
        HOMEWORK_COMMAND,
        ME_COMMAND,
        SETTINGS_COMMAND,
        CANCEL_COMMAND,
        CREATE_ASSIGNMENT_COMMAND,
        TOPICS_COMMAND,
        TEACHER_CONTENT_COMMAND,
        BULK_EDIT_COMMAND,
    )
    assert owner_registered == registered + (SEED_DEMO_COMMAND,)
    assert BOT_COMMANDS == build_bot_commands()
    assert [command.command for command in BOT_COMMANDS] == [command.name for command in registered]


def test_bot_commands_use_centralized_i18n_descriptions() -> None:
    assert BOT_COMMANDS[0].description == translate("command.start", "en")
    assert CREATE_ASSIGNMENT_COMMAND.to_bot_command("en").description == translate(
        "command.create_assignment",
        "en",
    )
    assert HOMEWORK_COMMAND.to_bot_command("en").description == translate(
        "command.homework",
        "en",
    )
    assert SEED_DEMO_COMMAND.to_bot_command("en").description == translate(
        "command.seed_demo",
        "en",
    )
    assert ADD_FAMILY_COMMAND.to_bot_command("en").description == translate(
        "command.add_family",
        "en",
    )
    assert TEACHER_CONTENT_COMMAND.to_bot_command("en").description == translate(
        "command.teacher_content",
        "en",
    )
    assert BULK_EDIT_COMMAND.to_bot_command("en").description == translate(
        "command.bulk_edit",
        "en",
    )
