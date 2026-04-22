from dataclasses import dataclass

from aiogram.types import BotCommand

from .i18n import DEFAULT_LANGUAGE_CODE, translate


@dataclass(frozen=True)
class CommandDefinition:
    name: str
    description_key: str
    scope: str
    register_after_startup: bool = False

    @property
    def token(self) -> str:
        return f"/{self.name}"

    def to_bot_command(self, language_code: str = DEFAULT_LANGUAGE_CODE) -> BotCommand:
        return BotCommand(
            command=self.name,
            description=translate(self.description_key, language_code),
        )


START_COMMAND = CommandDefinition(
    name="start",
    description_key="command.start",
    scope="student",
    register_after_startup=True,
)
LEARN_COMMAND = CommandDefinition(
    name="learn",
    description_key="command.learn",
    scope="student",
    register_after_startup=True,
)
ME_COMMAND = CommandDefinition(
    name="me",
    description_key="command.me",
    scope="user",
    register_after_startup=True,
)
SETTINGS_COMMAND = CommandDefinition(
    name="settings",
    description_key="command.settings",
    scope="user",
    register_after_startup=True,
)
CANCEL_COMMAND = CommandDefinition(
    name="cancel",
    description_key="command.cancel",
    scope="user",
    register_after_startup=True,
)
INVITE_COMMAND = CommandDefinition(
    name="invite",
    description_key="command.invite",
    scope="teacher",
    register_after_startup=True,)
JOIN_COMMAND = CommandDefinition(
    name="join",
    description_key="command.join",
    scope="user",
    register_after_startup=True,
)
ASSIGN_COMMAND = CommandDefinition(
    name="assign",
    description_key="command.assign",
    scope="teacher",
    register_after_startup=True,
)
CREATE_ASSIGNMENT_COMMAND = CommandDefinition(
    name="create_assignment",
    description_key="command.create_assignment",
    scope="teacher",
    register_after_startup=True,
)
GRANTTOPIC_COMMAND = CommandDefinition(
    name="granttopic",
    description_key="command.granttopic",
    scope="teacher",
    register_after_startup=True,
)
TOPICS_COMMAND = CommandDefinition(
    name="topics",
    description_key="command.topics",
    scope="student",
    register_after_startup=True,
)
WORKBOOK_EXPORT_COMMAND = CommandDefinition(
    name="workbook_export",
    description_key="command.workbook_export",
    scope="teacher",
    register_after_startup=True,
)
WORKBOOK_IMPORT_COMMAND = CommandDefinition(
    name="workbook_import",
    description_key="command.workbook_import",
    scope="teacher",
    register_after_startup=True,
)
TEACHER_CONTENT_COMMAND = CommandDefinition(
    name="teacher_content",
    description_key="command.teacher_content",
    scope="teacher",
    register_after_startup=True,
)

ALL_COMMANDS = (
    START_COMMAND,
    LEARN_COMMAND,
    ME_COMMAND,
    SETTINGS_COMMAND,
    CANCEL_COMMAND,
    INVITE_COMMAND,
    JOIN_COMMAND,
    ASSIGN_COMMAND,
    CREATE_ASSIGNMENT_COMMAND,
    GRANTTOPIC_COMMAND,
    TOPICS_COMMAND,
    WORKBOOK_EXPORT_COMMAND,
    WORKBOOK_IMPORT_COMMAND,
    TEACHER_CONTENT_COMMAND,
)


def get_registered_commands() -> tuple[CommandDefinition, ...]:
    return tuple(
        command
        for command in ALL_COMMANDS
        if command.register_after_startup
    )


def build_bot_commands(language_code: str = DEFAULT_LANGUAGE_CODE) -> list[BotCommand]:
    return [command.to_bot_command(language_code) for command in get_registered_commands()]


BOT_COMMANDS = build_bot_commands()
