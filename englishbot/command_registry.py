from dataclasses import dataclass

from aiogram.types import BotCommand


@dataclass(frozen=True)
class CommandDefinition:
    name: str
    description: str
    scope: str
    register_after_startup: bool = False

    @property
    def token(self) -> str:
        return f"/{self.name}"

    def to_bot_command(self) -> BotCommand:
        return BotCommand(command=self.name, description=self.description)


START_COMMAND = CommandDefinition(
    name="start",
    description="Открыть главное меню",
    scope="student",
    register_after_startup=True,
)
LEARN_COMMAND = CommandDefinition(
    name="learn",
    description="Начать тренировку",
    scope="student",
    register_after_startup=True,
)
ME_COMMAND = CommandDefinition(
    name="me",
    description="Показать мой профиль",
    scope="user",
    register_after_startup=True,
)
INVITE_COMMAND = CommandDefinition(
    name="invite",
    description="Создать код приглашения",
    scope="teacher",
)
JOIN_COMMAND = CommandDefinition(
    name="join",
    description="Присоединиться по коду",
    scope="user",
)
ASSIGN_COMMAND = CommandDefinition(
    name="assign",
    description="Назначить домашку ученику",
    scope="teacher",
)
GRANTTOPIC_COMMAND = CommandDefinition(
    name="granttopic",
    description="Открыть тему ученику",
    scope="teacher",
)
TOPICS_COMMAND = CommandDefinition(
    name="topics",
    description="Показать доступные темы",
    scope="student",
)
WORKBOOK_EXPORT_COMMAND = CommandDefinition(
    name="workbook_export",
    description="Экспортировать workbook",
    scope="teacher",
)
WORKBOOK_IMPORT_COMMAND = CommandDefinition(
    name="workbook_import",
    description="Импортировать workbook",
    scope="teacher",
)

ALL_COMMANDS = (
    START_COMMAND,
    LEARN_COMMAND,
    ME_COMMAND,
    INVITE_COMMAND,
    JOIN_COMMAND,
    ASSIGN_COMMAND,
    GRANTTOPIC_COMMAND,
    TOPICS_COMMAND,
    WORKBOOK_EXPORT_COMMAND,
    WORKBOOK_IMPORT_COMMAND,
)


def get_registered_commands() -> tuple[CommandDefinition, ...]:
    return tuple(
        command
        for command in ALL_COMMANDS
        if command.register_after_startup
    )


def build_bot_commands() -> list[BotCommand]:
    return [command.to_bot_command() for command in get_registered_commands()]


BOT_COMMANDS = build_bot_commands()
