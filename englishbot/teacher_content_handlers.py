from aiogram.filters import Command
from aiogram.types import Message
from aiogram_dialog import DialogManager, StartMode

from .command_registry import TEACHER_CONTENT_COMMAND
from .db import save_user
from .families import get_user_family
from .i18n import translate_for_user
from .runtime import router
from .teacher_content_dialog import TeacherContentDialogSG
@router.message(Command(TEACHER_CONTENT_COMMAND.name))
async def teacher_content(message: Message, dialog_manager: DialogManager) -> None:
    if message.from_user is None:
        return

    save_user(message.from_user)
    family = get_user_family(message.from_user.id)
    if family is None:
        await message.answer(
            translate_for_user(
                message.from_user.id,
                "family.command_family_only",
                command=TEACHER_CONTENT_COMMAND.token,
            )
        )
        return

    await dialog_manager.start(
        TeacherContentDialogSG.topics,
        mode=StartMode.RESET_STACK,
        data={"workspace_id": int(family["id"])},
    )
