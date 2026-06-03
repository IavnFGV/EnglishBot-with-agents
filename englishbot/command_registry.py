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
HELP_COMMAND = CommandDefinition(
    name="help",
    description_key="command.help",
    scope="user",
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
CREATE_ASSIGNMENT_COMMAND = CommandDefinition(
    name="create_assignment",
    description_key="command.create_assignment",
    scope="teacher",
    register_after_startup=True,
)
SEED_DEMO_COMMAND = CommandDefinition(
    name="seed_demo",
    description_key="command.seed_demo",
    scope="owner",
    register_after_startup=True,
)
ADD_FAMILY_COMMAND = CommandDefinition(
    name="add_family",
    description_key="command.add_family",
    scope="owner",
    register_after_startup=False,
)
TOPICS_COMMAND = CommandDefinition(
    name="topics",
    description_key="command.topics",
    scope="student",
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
    HELP_COMMAND,
    LEARN_COMMAND,
    ME_COMMAND,
    SETTINGS_COMMAND,
    CANCEL_COMMAND,
    CREATE_ASSIGNMENT_COMMAND,
    SEED_DEMO_COMMAND,
    ADD_FAMILY_COMMAND,
    TOPICS_COMMAND,
    TEACHER_CONTENT_COMMAND,
)


def get_registered_commands() -> tuple[CommandDefinition, ...]:
    return (
        START_COMMAND,
        HELP_COMMAND,
        LEARN_COMMAND,
        ME_COMMAND,
        SETTINGS_COMMAND,
        CANCEL_COMMAND,
        CREATE_ASSIGNMENT_COMMAND,
        SEED_DEMO_COMMAND,
        TOPICS_COMMAND,
        TEACHER_CONTENT_COMMAND,
    )


def build_bot_commands(language_code: str = DEFAULT_LANGUAGE_CODE) -> list[BotCommand]:
    return [command.to_bot_command(language_code) for command in get_registered_commands()]


BOT_COMMANDS = build_bot_commands()
