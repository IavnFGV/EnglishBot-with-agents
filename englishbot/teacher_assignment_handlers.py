from aiogram.filters import Command
from aiogram.types import Message
from aiogram_dialog import DialogManager, StartMode

from .command_registry import CREATE_ASSIGNMENT_COMMAND
from .db import save_user
from .i18n import translate_for_user
from .runtime import router
from .teacher_assignment_dialog import TeacherAssignmentDialogSG
from .user_profiles import get_user_role


@router.message(Command(CREATE_ASSIGNMENT_COMMAND.name))
async def create_assignment_flow(message: Message, dialog_manager: DialogManager) -> None:
    if message.from_user is None:
        return

    save_user(message.from_user)
    if get_user_role(message.from_user.id) != "teacher":
        await message.answer(
            translate_for_user(
                message.from_user.id,
                "teacher.command_teacher_only",
                command=CREATE_ASSIGNMENT_COMMAND.token,
            )
        )
        return

    await dialog_manager.start(
        TeacherAssignmentDialogSG.source_mode,
        mode=StartMode.RESET_STACK,
    )
