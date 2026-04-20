from io import BytesIO

from aiogram import F
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, Message

from .db import save_user
from .runtime import router
from .workbook_admin import (
    build_export_summary_text,
    build_import_summary_text,
    export_teacher_workspace_workbook_file,
    import_teacher_workspace_workbook_file,
)
from .workbook_import import WorkbookImportError
from .workspaces import (
    WorkspaceEditPermissionError,
    WorkspaceKindMismatchError,
    WorkspaceNotFoundError,
)


WORKBOOK_EXPORT_COMMAND = "workbook_export"
WORKBOOK_IMPORT_COMMAND = "workbook_import"


def _build_export_usage_message() -> str:
    return "Использование: /workbook_export <teacher_workspace_id>"


def _build_import_usage_message() -> str:
    return (
        "Использование: отправьте .xlsx файлом с подписью "
        "/workbook_import <teacher_workspace_id>"
    )


def _parse_workspace_id(raw_value: str) -> int | None:
    normalized = raw_value.strip()
    if not normalized or not normalized.isdigit():
        return None
    return int(normalized)


def _extract_import_workspace_id(caption: str | None) -> int | None:
    if caption is None:
        return None
    first_line = caption.strip().splitlines()[0].strip() if caption.strip() else ""
    if not first_line:
        return None
    parts = first_line.split(maxsplit=1)
    command_name = parts[0].split("@", 1)[0].lstrip("/").lower()
    if command_name != WORKBOOK_IMPORT_COMMAND or len(parts) != 2:
        return None
    return _parse_workspace_id(parts[1])


@router.message(Command(WORKBOOK_EXPORT_COMMAND))
async def workbook_export(message: Message, command: CommandObject | None = None) -> None:
    if message.from_user is None:
        return

    save_user(message.from_user)
    raw_args = (command.args if command is not None and command.args is not None else "").strip()
    workspace_id = _parse_workspace_id(raw_args)
    if workspace_id is None:
        await message.answer(_build_export_usage_message())
        return

    try:
        report = export_teacher_workspace_workbook_file(message.from_user.id, workspace_id)
    except WorkspaceNotFoundError:
        await message.answer("Workspace не найден.")
        return
    except WorkspaceKindMismatchError:
        await message.answer("Экспорт workbook доступен только для teacher workspace.")
        return
    except WorkspaceEditPermissionError:
        await message.answer("У вас нет teacher-доступа к этому workspace.")
        return

    await message.answer_document(
        BufferedInputFile(
            file=bytes(report["workbook_bytes"]),
            filename=str(report["filename"]),
        ),
        caption=build_export_summary_text(report),
    )


@router.message(Command(WORKBOOK_IMPORT_COMMAND))
async def workbook_import_usage(
    message: Message,
    command: CommandObject | None = None,
) -> None:
    if message.document is not None:
        return

    raw_args = (command.args if command is not None and command.args is not None else "").strip()
    if _parse_workspace_id(raw_args) is None:
        await message.answer(_build_import_usage_message())
        return

    await message.answer(_build_import_usage_message())


@router.message(F.document)
async def workbook_import_document(message: Message) -> None:
    if message.from_user is None or message.document is None:
        return

    workspace_id = _extract_import_workspace_id(message.caption)
    if workspace_id is None:
        return

    save_user(message.from_user)
    filename = (message.document.file_name or "").lower()
    if not filename.endswith(".xlsx"):
        await message.answer("Нужен файл .xlsx.")
        return

    buffer = BytesIO()
    await message.bot.download(message.document, destination=buffer)
    workbook_bytes = buffer.getvalue()

    try:
        report = import_teacher_workspace_workbook_file(
            message.from_user.id,
            workspace_id,
            workbook_bytes,
        )
    except WorkspaceNotFoundError:
        await message.answer("Workspace не найден.")
        return
    except WorkspaceKindMismatchError:
        await message.answer("Импорт workbook доступен только для teacher workspace.")
        return
    except WorkspaceEditPermissionError:
        await message.answer("У вас нет teacher-доступа к этому workspace.")
        return
    except WorkbookImportError as error:
        await message.answer(f"Импорт не выполнен: {error}")
        return

    await message.answer(build_import_summary_text(report))
